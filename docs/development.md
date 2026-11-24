# 開発環境と作業上の注意

更新日: 2026-11-24

## 仮想環境の扱い

ユーザーの指示により、既存の `.venv` を利用する。

- `.venv` 内のファイルを直接編集・削除・置換しない。
- 仮想環境の再作成や、設定ファイル・Python実行ファイルの直接変更を行わない。
- パッケージ管理にはpipなどの正規の管理コマンドを使ってよい。
- Pythonとpipは、対象を明確にするため `.venv\Scripts\python.exe` 経由で実行する。activateは必須ではない。

## 動作確認結果

2026-10-28に既存環境を確認した。

| 項目 | 結果 |
| --- | --- |
| Python | 3.14.0、Windows 64 bit |
| 仮想環境 | `sys.prefix != sys.base_prefix` が `True` |
| pip | 25.1.1、当該 `.venv` のpipが起動 |
| 依存関係 | `pip check`: `No broken requirements found.` |
| `box_cache` | 初回確認時は未インストール。その後、下記の公開手順で0.1.0をインストール済み |

初回確認は既存のPythonとpipの起動によって行った。その後のインストールと初期設定は次節に記録する。仮想環境内部の直接編集は行っていない。

プロジェクトのルートから再確認する場合:

```powershell
.\.venv\Scripts\python.exe --version
.\.venv\Scripts\python.exe -m pip --version
.\.venv\Scripts\python.exe -m pip check
```

## box_cacheのインストールと初期設定

2026-10-28に、ユーザーの指示で[公開README](https://github.com/Mask-coins/box_cache/blob/master/README.md)の手順を実行した。Pythonの呼び出し先は既存の `.venv` を明示した。

```powershell
.\.venv\Scripts\python.exe -m pip install "https://github.com/Mask-coins/box_cache/archive/refs/heads/master.zip"
.\.venv\Scripts\python.exe -m box_cache configure --cache-dir C:\Data\box_cache
.\.venv\Scripts\python.exe -m box_cache config show
```

- pipで `box-cache 0.1.0` をインストールした。pip自体の更新は行っていない。
- 保存先は公開手順の例示どおり `C:\Data\box_cache` とした。実行前に親の `C:\Data` が存在し、保存先が未作成であることを確認した。
- 保存先と設定の作成は公式CLIで行った。設定ファイルやvenv内部は直接編集していない。
- 設定は `%LOCALAPPDATA%\box_cache\config.json` に保存され、同じWindowsユーザー・同じ `LOCALAPPDATA` の別プロジェクトや仮想環境でも共有される。
- 制限された実行環境ではGitHubの名前解決に失敗したため、許可された制限外実行でインストールした。初期設定と設定の確認も同じユーザー環境で実行した。
- インストール後、当該venvからのインポート、`load_config()` の保存先、`pip check` の成功を確認した。
- `master.zip` は可変のURLであり、依存先のコミットを固定したインストールではない。
- キャッシュへのサンプルデータの保存は行っていない。

## 2026-11-24の更新

公開READMEの更新手順に従い、既存venvの `box-cache` を0.1.0から0.2.0へ更新した。

```powershell
.\.venv\Scripts\python.exe -m pip install --upgrade --force-reinstall "https://github.com/Mask-coins/box_cache/archive/refs/heads/master.zip"
```

- 更新後のインポート、バージョン0.2.0、`put()` の `attributes` 引数、`get_with_attributes()` の存在を確認した。
- `pip check` は `No broken requirements found.`。pip自体は更新していない。
- 設定確認時に `%LOCALAPPDATA%\box_cache` が存在せず、`ConfigurationError` となった。設定がなくなった原因は未確認。
- `C:\Data\box_cache` と所有マーカーは存在したため、公式CLIの `configure --cache-dir C:\Data\box_cache` で従来の保存先へ再設定した。`config show` が正常に保存先を返すことを確認した。
- 更新作業はpipと公式CLIで行い、venv内部の直接編集や既存キャッシュの移動・削除は行っていない。更新時点では実データの保存・読み出しは未実施で、その後の初期版実装時に下記の隔離テストで確認した。

## 文書の更新

- 開発上の決定事項と注意事項は `docs/` に追記する。
- 設計方針・仕様の決定や変更は [design.md](design.md) に反映する。
- 提案・未決定事項を、合意済みや実装済みとして記載しない。
- 依存先の仕様と、このプロジェクト自身の仕様を区別する。

## 開発用インストールとテスト

2026-11-24に初期版を実装し、既存venvへRequests 2.34.2と本ライブラリ0.1.0をpipでインストールした。通常の開発用インストールは次のとおり。

```powershell
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m pip check
```

今回の作業では、Requestsをpipで追加後、更新済みの `box-cache 0.2.0` を保ったまま `pip install --no-deps -e .` で開発用インストールした。

テストはプロジェクト内の `.test-work/` に一時ディレクトリを作成し、そのテストプロセス内だけ `LOCALAPPDATA` を切り替える。実際の `box_cache.configure()` で一時保存先を作り、実際の保存・読み出しを検証する。`C:\Data\box_cache` やユーザー共通の設定はテストで変更しない。

HTTPは127.0.0.1の一時ポートで動かす。外部サイトへの通信は不要。サンドボックスでローカル通信がWinError 10013により拒否された場合は、許可された実行環境で同じテストを行う。

19件のテストで、本文・日本語JSON・空本文・圧縮本文、プロジェクト分離、HTTP異常の保存、許容タプルの順序、再取得、各URLのリダイレクト保存と再利用、Cookieの非継承、接続失敗・タイムアウト・本文途切れ、保存失敗、例外チェーン、参照APIの通信なしを確認した。

Windowsでは、接続が成立しない場合の例外が接続拒否か接続タイムアウトかで異なることがある。記録はRequestsが実際に返した例外クラス名に従い、テストもその名前で参照する。
