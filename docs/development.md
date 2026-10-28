# 開発環境と作業上の注意

更新日: 2026-10-28

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

## 文書の更新

- 開発上の決定事項と注意事項は `docs/` に追記する。
- 設計方針・仕様の決定や変更は [design.md](design.md) に反映する。
- 提案・未決定事項を、合意済みや実装済みとして記載しない。
- 依存先の仕様と、このプロジェクト自身の仕様を区別する。
