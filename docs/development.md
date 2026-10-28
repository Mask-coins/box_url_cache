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
| `box_cache` | 未インストール（モジュール探索で未検出） |

確認は既存のPythonとpipの起動によって行った。パッケージのインストール・更新、仮想環境内部の直接編集は行っていない。
pipでのネットワーク経由の取得や、`box_cache` と接続した動作はまだ確認していない。

プロジェクトのルートから再確認する場合:

```powershell
.\.venv\Scripts\python.exe --version
.\.venv\Scripts\python.exe -m pip --version
.\.venv\Scripts\python.exe -m pip check
```

## 文書の更新

- 開発上の決定事項と注意事項は `docs/` に追記する。
- 設計方針・仕様の決定や変更は [design.md](design.md) に反映する。
- 提案・未決定事項を、合意済みや実装済みとして記載しない。
- 依存先の仕様と、このプロジェクト自身の仕様を区別する。
