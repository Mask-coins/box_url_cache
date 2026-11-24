# box-url-cache

Windows用のURLアクセス結果キャッシュです。プロジェクト名とURLを渡すと、キャッシュがあれば返し、なければHTTPで取得して `box_cache` に保存します。
新しく取得した結果は、保存まで成功してから返します。

## インストールと初期設定

WindowsとPython 3.11以降が必要です。プロジェクトのルートで、利用するPython環境にインストールしてください。

```powershell
python -m pip install .
```

Requestsと `box-cache` が依存パッケージです。`box-cache` はGitHubの公開URLから取得し、0.2.0以降の付加情報APIを利用します。

`box_cache` が未設定の場合のみ、公式CLIで保存先を設定します。初回の保存先は未作成で、親ディレクトリが必要です。

```powershell
python -m box_cache configure --cache-dir C:\Data\box_cache
python -m box_cache config show
```

設定はWindowsユーザー単位で共有されます。設定済みなら、そのまま利用できます。

## 取得する

```python
import box_url_cache

response = box_url_cache.get("sample", "https://example.com/")
print(response.status_code)
print(response.text)
body = response.content  # bytes。JSONなら response.json() も利用可能
print(response.from_cache)
```

戻り値は `requests.Response` です。キャッシュからの取得でも `.content`、`.text`、`.json()`、`.headers`、`.url`、`.history` を利用できます。
追加の属性として `.from_cache`（その応答がキャッシュ由来か）と `.fetched_at`（元の取得日時、UTC）を持ちます。各リダイレクト応答にも付与します。
キャッシュからの復元では生の接続・`.raw`・Cookie・通信の所要時間は復元しません。

```python
response = box_url_cache.get(
    "sample", "https://example.com/",
    accepted_statuses=(200, 404),
    refresh=False,
    timeout=(5, 30),  # 接続・読み取りの秒数。既定は None（タイムアウトなし）
    allow_redirects=True,
    max_redirects=30,
)
```

- `accepted_statuses` の既定は `(200,)`。タプルの順にキャッシュを探し、最初に見つかった応答を返します。通信した場合は応答のステータスがタプルに含まれていれば返します。
- `refresh=True` はリダイレクトの途中も含めてキャッシュを使わず、取得・保存し直します。
- タイムアウトはRequestsと同じ指定方法です。読み取りタイムアウトは受信待ちの制限であり、処理全体の時間上限ではありません。
- リダイレクトを許容ステータスに明示した場合、その応答で終了します。例えば `(200, 301)` なら301を追従せず返します。
- `allow_redirects=False` で許容範囲外の3xxを受け取ると、保存してから `requests.HTTPError` を送出します。

このライブラリが404を許容しても、Requests自体の `.ok`、真偽値判定、`.raise_for_status()` の意味は変わりません。

## リダイレクトと保存先

```text
URL A → 301 → URL B → 302 → URL C → 200
```

保存先は次のように分かれます。キーはそれぞれのURLです。

| box_cacheのプロジェクト名 | キー | 保存する応答 |
| --- | --- | --- |
| `sample_301` | URL A | Aが返した301とLocation等 |
| `sample_302` | URL B | Bが返した302とLocation等 |
| `sample_200` | URL C | Cが返した200 |

URL Aに最終200を保存することはありません。次回もキャッシュのLocationを順にたどり、不足したURLだけ取得します。
最終レスポンスの `.history` で経路を、`.url` で最終URLを確認できます。

各URLで許容ステータスが見つからない場合は、301、302、303、307、308の順にキャッシュを確認します。
古いステータスのキャッシュは自動削除しないため、複数ある場合は新しさではなく、この優先順で選びます。最新の状態が必要なら `refresh=True` を使います。

## 異常を扱う・記録を参照する

許容範囲外のHTTP応答はステータス別に保存してから `requests.HTTPError` を送出します。

```python
import requests
import box_url_cache

try:
    response = box_url_cache.get("sample", "https://example.com/missing")
except requests.HTTPError as error:
    print(error.response.status_code)
    print(error.response.content)
```

通信せず、指定したステータスの最新記録を参照できます。リダイレクトも追従しません。

```python
record = box_url_cache.get_cached(
    "sample", "https://example.com/missing", statuses=(404, 500),
)
if record is not None:
    print(record.status_code, record.text, record.fetched_at)
    # これを見て次のアクセスを行うかどうかは、呼び出し側で判断する。
```

通信失敗は元のRequests例外を送出します。例外のクラス名でプロジェクトを分け（例: `sample_ConnectionError`）、空の本文と種別・メッセージ・発生日時を保存します。

```python
error_record = box_url_cache.get_error(
    "sample", "https://example.com/", "ConnectionError",
)
if error_record is not None:
    print(error_record["message"], error_record["occurred_at"])
```

実際の例外クラス名を指定します。例えば `ConnectTimeout`、`ReadTimeout`、`SSLError`、`ChunkedEncodingError`、`TooManyRedirects` などです。親クラス名によるまとめ読みは行いません。
取得失敗では正常キャッシュを作成しません。異常記録の存在だけでアクセスを自動スキップすることもありません。

`box_cache` の設定・読み書きのエラーは、その例外を伝えます。HTTP異常・通信失敗の記録にも失敗した場合は、保存例外の `__cause__` から元の異常を確認できます。
リダイレクトの途中で失敗しても、それまで保存済みの応答は残ります。

## 対象と制限

- HTTP/HTTPSのGET専用です。同じURLから同じ内容を期待できる用途、またはそのようにみなす用途を想定します。
- 認証・Cookie・言語等による応答の出し分けは扱いません。URL内の認証情報も受け付けません。
- 環境からの暗黙の認証を避けるためRequestsの `trust_env=False` を使い、環境変数のプロキシやCA設定も取り込みません。TLS検証は有効です。Cookieは次のアクセスに引き継ぎません。
- 入力URLの表記をキーとして使います。クエリの並べ替えなどの同一視は行いません。各応答の `.url` はRequestsが準備したURLです。
- 有効期限・自動削除・自動再試行・全履歴の読み出し・ストリーミングには対応しません。本文は全体をメモリに読み込みます。
- 保存先の名前・長さ・競合の制約は `box_cache` に従います。指定したプロジェクト名に接尾辞が付くことを考慮してください。他用途のデータと名前を共有しないでください。
- 付加情報のないデータや未対応の形式を同じ保存先で読むと、`ValueError` 等で停止します。

開発情報は [docs/](docs/README.md) にまとめています。
