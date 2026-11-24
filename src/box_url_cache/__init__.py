"""Cache URL responses using box_cache; return ordinary Requests responses."""

from .client import get, get_cached, get_error

__all__ = ["get", "get_cached", "get_error"]
