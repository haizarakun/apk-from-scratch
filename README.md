# apk-from-scratch

日本語がメインのドキュメントです。英語は簡易対応（[English (partial)](README.en.md)）。
その他の言語には対応しません。

Android SDK も aapt も d8 も JDK も zipalign も apksigner も使わず、**Python だけ**で
**署名済み・インストール可能な Android APK** を生成し、さらに**読み戻す**ツールキットです。
依存は署名計算のための [`cryptography`](https://pypi.org/project/cryptography/) だけ。

```bash
pip install apk-from-scratch
apkforge --package com.example.hello --label "こんにちは" \
    --message "スクラッチ製" -o hello.apk
# wrote hello.apk — package com.example.hello
```

生成した APK はアプリ名とランチャーアイコンを持ち、Activity を起動し、Android の
インストーラが要求する **APK Signature Scheme v2 + v3** の暗号検証を通ります。

## なぜ作るのか

普通の Android 入門は Gradle と SDK と数百 MB のビルドツールを渡して「ボタンを押せ」と言う。
APK が「何であるか」は見えないままです。

APK は魔法ではなく、仕様化されたバイナリ形式を詰めた ZIP にすぎません。

- **バイナリマニフェスト**（`AndroidManifest.xml` を AXML にコンパイルしたもの）
- **Dalvik バイトコード**（`classes.dex`）
- **コンパイル済みリソース表**（`resources.arsc`、名前とアイコン）
- **署名**（改ざんされていない証明）

このプロジェクトはそれらを**手書きで生成し、読み戻し**ます。全バイトを両方向で確認できるので、
「encode → decode で元に戻る」こと自体が外部ツール不要の正しさの検証になります。

## できること

| 機能 | モジュール | 代替する道具 |
|------|-----------|-------------|
| バイナリ `AndroidManifest.xml`（型付き属性・リソース参照・バージョン） | `apkfs/axml.py` | `aapt` |
| `classes.dex`（フィールド・インターフェース・direct/virtual メソッド・分岐/ループ） | `apkfs/dex.py`, `apkfs/dalvik.py` | `d8` / `dx` |
| `resources.arsc`（アプリ名・ランチャーアイコン） | `apkfs/arsc.py`, `apkfs/png.py` | `aapt` |
| ZIP パック + **v2/v3 署名**（EC P-256） | `apkfs/apk.py` | `zipalign` + `apksigner` |
| 独立した暗号検証器 | `apkfs/verify.py` | `apksigner verify` |
| **デコーダ**（AXML→XML、arsc→エントリ、DEX→要約） | `apkfs/decode.py` | `apktool d` |
| ビルド CLI / 解析 CLI | `apkfs/apkforge.py`, `apkfs/apkinspect.py` | Gradle / `aapt dump` |

日本語・絵文字を含む Unicode のアプリ名・表示文字列にも対応（DEX は MUTF-8、
リソースは UTF-8、長さは UTF-16 コード単位で数える）。

## 使い方

```bash
pip install apk-from-scratch                 # チェックアウトからは pip install .

apkforge --package com.example.app --label "My App" \
    --message "Hi" --icon-color 1E88E5 -o my.apk   # 生成
apkinspect my.apk                            # 中身を表示
adb install -r my.apk                        # 端末/エミュレータに導入
```

開発時は `pip install -e ".[test]"`（androguard と pytest が入る）。
各サンプルは `python3 examples/<name>/build.py` で直接ビルドできます。

## テスト

`tests/test_build.py` は、出力が独立パーサ [androguard](https://github.com/androguard/androguard)
に受理されること、v2/v3 署名が暗号的に検証されること、**改ざん APK が拒否される**こと、
そして各形式が **encode→decode で往復する**ことを確認します。

## サポート・コミュニティ

- **Discord**（メインのサポート窓口）: <DISCORD_INVITE>
- [docs/format.md](docs/format.md) — 各バイナリ形式のバイト単位の解説
- [CONTRIBUTING.md](CONTRIBUTING.md) / [SUPPORT.md](SUPPORT.md) / [SECURITY.md](SECURITY.md) / [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) / [CHANGELOG.md](CHANGELOG.md)

質問・不具合報告は Discord を優先してください。セキュリティに関わる報告のみ
[SECURITY.md](SECURITY.md) の非公開ルートでお願いします。

## ライセンス

MIT。[LICENSE](LICENSE) を参照。
