# 設計・責任分担

更新日: 2026-11-24

## 実装状況

初期版の実装は `src/box_url_cache/client.py` にまとめる。公開関数は `get()`、`get_cached()`、`get_error()` の3つ。利用方法は利用者向けのルートREADMEに記載する。

## 対象と責任

- HTTP/HTTPSのGETによるリソース取得を対象とする。
- 同じURLについて、取得元の内部データが変わらなければ同じ応答が得られる用途、または呼び出し側でそのようにみなす用途を想定する。
- 認証・Cookie・言語指定などによる応答の出し分けは扱わない。URL内の認証情報は拒否する。
- `box_url_cache` は通信、許容ステータス、再取得、リダイレクト、HTTP関連の付加情報を担当する。
- `box_cache` はファイル化・復元、保存先、版管理、破損検出・記録、ファイルの整合性確認を担当する。URL側で保存ファイルを直接読んだり、独自の履歴台帳を作ったりしない。
- `box_cache` の公開APIが `None` を返した場合は、未登録と破損を区別せず取得に進む。基盤が送出した例外はキャッシュなしと同一視しない。
- HTTP関連の付加情報の項目・互換性は本ライブラリが管理する。未対応の形式は例外で停止し、基盤の破損とみなして修復しない。

## 保存先と形式

本文と付加情報を `box_cache.put(..., attributes=...)` で同じ版として保存する。読み出しは `get_with_attributes()` を使う。独自のファイル形式は設けない。

| 記録 | box_cacheのプロジェクト | キー | 本文 |
| --- | --- | --- | --- |
| HTTP応答 | `<project>_<status>` | その応答を得た入力URL | Requestsが受信・展開したbytes |
| 通信・追従失敗 | `<project>_<例外クラス名>` | 失敗した段階のURL | 空のbytes |

HTTP付加情報は `schema_version=1`、`kind=response`、`status_code`、応答の `url`、`headers`、`encoding`、`reason`、UTCの `fetched_at` を持つ。
失敗の付加情報は `schema_version=1`、`kind=error`、`url`、`error_type`、`message`、UTCの `occurred_at` を持つ。例外オブジェクトは保存しない。

入力URLの表記をキーとして使い、クエリの並べ替えなどによる正規化・同一視はしない。応答URLにはRequestsが準備したURLを保存する。プロジェクト名と接尾辞のWindows名・長さの制約は `box_cache` が検証する。
他用途と同じプロジェクト・キーを共有しない。

## getの処理

1. 許容ステータスのタプルを指定順に確認する。既定は `(200,)`。
2. 許容するキャッシュがあれば、正常な戻り値として返す。
3. なければ301、302、303、307、308の順にリダイレクトキャッシュを確認する。Locationがあるものを使い、次のURLで同じ処理を繰り返す。
4. 使用できるキャッシュがなければ、そのURLへ通信する。HTTP応答を実際のステータス別に保存する。
5. 許容ステータスなら返す。明示的に許容した301等も、その応答で終了する。
6. 許容外でも追従可能なリダイレクトなら次のURLへ進み、それ以外は `requests.HTTPError` を送出する。

`refresh=True` は全段階のキャッシュ利用を省略する。保存済みキャッシュは消さず、新しい版を追加する。
異なるステータスの版を横断した新旧比較は行わない。複数存在する場合も上記の優先順位を使う。

## リダイレクト

`A --301--> B --302--> C --200` なら、`(project_301, A)`、`(project_302, B)`、`(project_200, C)` に保存する。
最終200をAに保存しない。キャッシュでもLocationを順にたどり、不足したURLから通信する。

相対Locationは応答URLを基準に解決する。RequestsのLocation解釈を利用する。
既定では自動追従し、上限は30回。`allow_redirects` と `max_redirects` をユーザー指定できる。循環または上限超過は `requests.TooManyRedirects` として記録・送出する。
経路は戻り値の `.history` に組み立て、最終URLは `.url` で確認できる。経路そのものを独立したキャッシュとして保存しない。

## 戻り値

独自の戻り値型は作らず、通信・キャッシュとも `requests.Response` を返す。
キャッシュからも `.content`、`.text`、`.json()`、`.status_code`、`.headers`、`.url`、`.history` を利用できる。
本文の復元に必要なRequests内部属性への代入は `_response()` に限定する。

`.from_cache` と `.fetched_at` を付与する。リダイレクト経路内の応答も、それぞれの取得元・取得日時を持つ。
生の接続・ストリーム・Cookie・通信所要時間はキャッシュから復元しない。
404を許容してもRequestsの `.ok`、真偽値判定、`.raise_for_status()` の意味は変えない。

## 失敗と記録の参照

- 新規取得は保存まで成功して正常リターンとする。保存失敗でも正常データを返す設定は、必要になった時点で拡張する。
- 許容外のHTTP応答は保存後に `requests.HTTPError` を送出し、応答は例外の `.response` から確認できる。
- 通信失敗は例外種別ごとに保存し、元のRequests例外を送出する。本文が途中で途切れた結果を正常キャッシュにしない。
- 不正URLや引数の不備は取得元の通信失敗記録と分ける。
- 基盤の保存にも失敗したらその例外を送出し、HTTP・通信異常があれば `__cause__` に保持する。
- 各段階は個別保存で、一括トランザクションではない。途中で失敗しても保存済みの段階は残し、ロールバックしない。
- `get_cached(project, url, statuses=...)` は指定タプル順に最新HTTP応答を読み、最初の1件または `None` を返す。通信も追従もしない。異常ステータスもこの関数で参照する。
- `get_error(project, url, error_type)` はクラス名が一致する最新失敗の付加情報または `None` を返す。親例外クラスによる集約はしない。
- 記録は利用側の判断材料として提供する。スキップするかは利用側が判断する。本ライブラリは異常記録を理由に自動スキップしない。

## 通信設定と初期版の範囲

タイムアウトはRequestsと同じく既定 `None`。秒数または接続・読み取りのタプルで指定する。処理全体の時間上限ではない。
暗黙の認証を防ぐため `Session.trust_env=False` を使う。環境のプロキシ・CA設定も無効になる点はREADMEに明示する。TLS検証は有効のまま、各段階の送信前にCookieを消す。

初期版には有効期限、自動削除、自動再試行、全履歴の参照、ストリーミングを設けない。本文全体をメモリに読み込む。
全履歴が必要になったら `box_cache` 側の履歴API拡張を検討する。

## 依存先

`box_cache 0.2.0` の本文・付加情報APIを利用する。公開元は https://github.com/Mask-coins/box_cache 。
2026-11-24に公開手順で既存venvを更新済み。保存先は `C:\Data\box_cache`。
配布メタデータは公開READMEに合わせて `master.zip` を依存URLとしており、コミット固定ではない。

参照:

- [box_cacheの確認済み更新](https://github.com/Mask-coins/box_cache/commit/a6825395406a0069d29687bb11b846be675a7f54)
- [Requests Quickstart](https://requests.readthedocs.io/en/latest/user/quickstart/)
- [RequestsのAPI](https://requests.readthedocs.io/en/latest/api/)
- [開発環境と検証](development.md)
