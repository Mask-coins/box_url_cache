"""HTTP GET, per-response persistence, and read-only record access."""

from datetime import datetime, timezone
from urllib.parse import urljoin, urlsplit

import box_cache
import requests
from requests.structures import CaseInsensitiveDict
from requests.utils import requote_uri


REDIRECT_STATUSES = (301, 302, 303, 307, 308)
SCHEMA = 1


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _project(project: str, suffix: int | str) -> str:
    if not isinstance(project, str):
        raise TypeError("project must be str")
    if not project:
        raise ValueError("project must not be empty")
    # Windows name/length validation belongs to box_cache.
    return f"{project}_{suffix}"


def _url(url: str) -> None:
    if not isinstance(url, str):
        raise TypeError("url must be str")
    parts = urlsplit(url)
    if parts.scheme.lower() not in ("http", "https") or not parts.hostname:
        raise requests.exceptions.InvalidURL("An absolute HTTP(S) URL is required")
    if parts.username is not None or parts.password is not None:
        raise requests.exceptions.InvalidURL("URLs containing credentials are not supported")
    # Validate/encode via Requests before reading a cache or making a request.
    requests.Request("GET", url).prepare()


def _statuses(statuses: tuple[int, ...]) -> None:
    if not isinstance(statuses, tuple):
        raise TypeError("statuses must be a tuple of HTTP status codes")
    if not statuses or any(type(code) is not int or not 100 <= code <= 599
                           for code in statuses):
        raise ValueError("statuses must contain HTTP status codes (100..599)")


def _response(project: str, url: str, status: int) -> requests.Response | None:
    record = box_cache.get_with_attributes(_project(project, status), url)
    if record is None:
        return None
    body, attrs = record
    if (not isinstance(body, bytes) or attrs.get("schema_version") != SCHEMA
            or attrs.get("kind") != "response" or attrs.get("status_code") != status):
        raise ValueError("Unsupported box_url_cache response record")
    response = requests.Response()
    # Requests has no public setter for buffered content. Keep this adaptation here.
    response._content = body
    response._content_consumed = True
    response.status_code = status
    response.headers = CaseInsensitiveDict(attrs["headers"])
    response.url = attrs["url"]
    response.encoding = attrs["encoding"]
    response.reason = attrs["reason"]
    response.request = requests.Request("GET", response.url).prepare()
    response.from_cache = True
    response.fetched_at = attrs["fetched_at"]
    return response


def get_cached(project: str, url: str, *,
               statuses: tuple[int, ...] = (200,)) -> requests.Response | None:
    """Read the first available status, without networking or following redirects."""
    _url(url)
    _statuses(statuses)
    for status in statuses:
        response = _response(project, url, status)
        if response is not None:
            return response
    return None


def get_error(project: str, url: str, error_type: str) -> dict | None:
    """Read the latest transport-error attributes for an exception class name."""
    _url(url)
    if not isinstance(error_type, str) or not error_type.isidentifier():
        raise ValueError("error_type must be an exception class name, e.g. ConnectionError")
    record = box_cache.get_with_attributes(_project(project, error_type), url)
    if record is None:
        return None
    _, attrs = record
    if (attrs.get("schema_version") != SCHEMA or attrs.get("kind") != "error"
            or attrs.get("error_type") != error_type):
        raise ValueError("Unsupported box_url_cache error record")
    return attrs


def _save_response(project: str, url: str, response: requests.Response,
                   error: Exception | None = None) -> None:
    response.from_cache = False
    response.fetched_at = _now()
    attrs = {
        "schema_version": SCHEMA, "kind": "response",
        "status_code": response.status_code, "url": response.url,
        "headers": dict(response.headers), "encoding": response.encoding,
        "reason": response.reason, "fetched_at": response.fetched_at,
    }
    try:
        box_cache.put(_project(project, response.status_code), url,
                      response.content, attributes=attrs)
    except box_cache.CacheError as save_error:
        if error is not None:
            raise save_error from error
        raise


def _save_error(project: str, url: str, error: requests.RequestException) -> None:
    try:
        box_cache.put(_project(project, type(error).__name__), url, b"", attributes={
            "schema_version": SCHEMA, "kind": "error", "url": url,
            "error_type": type(error).__name__, "message": str(error),
            "occurred_at": _now(),
        })
    except box_cache.CacheError as save_error:
        raise save_error from error


def _next_url(session: requests.Session, response: requests.Response) -> str:
    target = session.get_redirect_target(response)
    result = urljoin(response.url, target)
    # Match Requests' handling of a redirect without an explicit fragment.
    if not urlsplit(result).fragment and urlsplit(response.url).fragment:
        result += "#" + urlsplit(response.url).fragment
    return requote_uri(result)


def get(project: str, url: str, *, accepted_statuses: tuple[int, ...] = (200,),
        refresh: bool = False, timeout: float | tuple[float, float] | None = None,
        allow_redirects: bool = True, max_redirects: int = 30) -> requests.Response:
    """Return an accepted response only after saving each newly fetched response.

    Cache lookup follows accepted_statuses, then redirect statuses. HTTP results
    outside the accepted statuses raise requests.HTTPError after being saved.
    Transport exceptions are recorded separately and re-raised unchanged.
    """
    _url(url)
    _project(project, 200)
    _statuses(accepted_statuses)
    if type(max_redirects) is not int or max_redirects < 0:
        raise ValueError("max_redirects must be a non-negative integer")
    history = []
    visited = set()
    current = url
    with requests.Session() as session:
        # Resource identity is URL-only: do not load netrc auth or retain cookies.
        session.trust_env = False
        while True:
            _url(current)
            visited.add(current)
            response = None
            if not refresh:
                response = get_cached(project, current, statuses=accepted_statuses)
                if response is None and allow_redirects:
                    for status in REDIRECT_STATUSES:
                        if status not in accepted_statuses:
                            candidate = _response(project, current, status)
                            if candidate is not None and candidate.is_redirect:
                                response = candidate
                                break
            if response is None:
                session.cookies.clear()
                try:
                    response = session.get(current, timeout=timeout, allow_redirects=False)
                except (requests.exceptions.InvalidURL, requests.exceptions.InvalidSchema,
                        requests.exceptions.MissingSchema):
                    raise
                except requests.RequestException as error:
                    _save_error(project, current, error)
                    raise
                response.history = history.copy()
                accepted = response.status_code in accepted_statuses
                following = allow_redirects and response.is_redirect and not accepted
                http_error = None if accepted or following else requests.HTTPError(
                    f"Status {response.status_code} is not in {accepted_statuses}",
                    response=response, request=response.request,
                )
                try:
                    _save_response(project, current, response, http_error)
                finally:
                    response.close()
            response.history = history.copy()
            if response.status_code in accepted_statuses:
                return response
            if not allow_redirects or not response.is_redirect:
                raise requests.HTTPError(
                    f"Status {response.status_code} is not in {accepted_statuses}",
                    response=response, request=response.request,
                )
            next_url = _next_url(session, response)
            if len(history) >= max_redirects or next_url in visited:
                error = requests.TooManyRedirects(
                    "Redirect limit exceeded or redirect loop detected",
                    response=response, request=response.request,
                )
                _save_error(project, current, error)
                raise error
            history.append(response)
            current = next_url
