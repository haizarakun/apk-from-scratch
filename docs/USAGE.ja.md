# 使い方リファレンス（全部）

このページには **できること全部**が載っています。目的別に探すなら
[レシピ集](RECIPES.ja.md)、詰まったら [FAQ](FAQ.ja.md) へ。

- [1. 3 つの作り方](#1-3-つの作り方)
- [2. `apkforge` コマンド 全オプション](#2-apkforge-コマンド-全オプション)
- [3. 署名鍵 `apkforge keygen`](#3-署名鍵-apkforge-keygen)
- [4. JSON 設計図（`--spec`）全フィールド](#4-json-設計図---spec全フィールド)
- [5. Web アプリ（`--web` / `--html`）と JavaScript の橋](#5-web-アプリ---web----htmlと-javascript-の橋)
- [6. ブラウザ（GitHub Actions）フォームの全項目](#6-ブラウザgithub-actionsフォームの全項目)
- [7. `apkinspect` — APK を読む](#7-apkinspect--apk-を読む)
- [8. Python から使う](#8-python-から使う)
- [9. スマホに入れる](#9-スマホに入れる)

---

## 1. 3 つの作り方

| 作り方 | 向いている人 | 書くもの |
|---|---|---|
| **かんたん** | まず 1 個作りたい | コマンド 1 行（または引数なしのウィザード） |
| **JSON 設計図** | コードを書かずにボタン・画像・一覧・通信のあるアプリ | `app.json` |
| **Web アプリ** | 何でも作りたい（Android Studio の代わり） | `index.html`（＋CSS/JS/画像） |

どの作り方でも、**署名鍵（`--key`）を同じにすれば更新版が上書きインストール**できます。

---

## 2. `apkforge` コマンド 全オプション

```
apkforge [オプション] -o 出力.apk
apkforge                       # 引数なし → 対話ウィザード
apkforge keygen [-o key.pem]   # 署名鍵を作る
```

| オプション | 意味 | 既定値 |
|---|---|---|
| `--package ID` | アプリ ID（逆ドメイン。例 `com.yourname.app`）。**必須**（`--spec` 使用時は JSON 側） | — |
| `--label 名前` | アイコンの下に出る名前。日本語・絵文字可 | `From Scratch` |
| `--message 文字` | かんたんモードで画面に出す文字 | `Built from scratch.` |
| `--icon PNG` | ランチャーアイコンの画像（正方形 PNG、192×192 など） | 単色アイコンを自動生成 |
| `--icon-color RRGGBB` | 自動生成アイコンの色（6 桁 16 進） | `1E88E5` |
| `--version-code N` | 更新のたびに 1 ずつ増やす整数 | `1` |
| `--version-name 文字` | 表示用バージョン | `1.0` |
| `--min-sdk N` | 動く最低の Android API（23 = Android 6.0） | `23` |
| `--target-sdk N` | 動作確認した API | `28` |
| `--key key.pem` | 署名鍵（`keygen` で作ったもの）。**更新したいなら毎回同じ鍵** | 使い捨て鍵 |
| `--spec app.json` | JSON 設計図から作る（[4 章](#4-json-設計図---spec全フィールド)） | — |
| `--web フォルダ` | Web アプリ。`index.html` があるフォルダを丸ごと同梱（[5 章](#5-web-アプリ---web----htmlと-javascript-の橋)） | — |
| `--html ファイル` | Web アプリ。HTML 1 ファイルから | — |
| `--permissions a,b` | Web アプリの端末機能: `camera,mic,location,vibrate,notify` | なし（INTERNET は常時） |
| `--install` | 作った後に `adb install -r` で接続中の端末へ入れる | — |
| `-o ファイル` | 出力先 | `app.apk` |

例:

```bash
apkforge --package com.me.hello --label "こんにちは" --message "やあ" -o hello.apk
apkforge --spec app.json --key mykey.pem --icon icon.png -o app.apk
apkforge --web ./site --package com.me.web --label "Webアプリ" --permissions camera,location --key mykey.pem --install
```

---

## 3. 署名鍵 `apkforge keygen`

```bash
apkforge keygen -o mykey.pem [--name "証明書の名前"]
```

- P-256 の秘密鍵＋自己署名証明書を 1 つの PEM に保存（30 年有効）。**なくすと更新不能**。
- 表示される `certificate SHA-256` が、Android が「同じ開発者か」を見るときの指紋です。
- 既にあるファイルは上書きしません。
- ブラウザで作る場合は「Create signing key」ワークフロー → Secret `APK_SIGNING_KEY` に保存
  （[EASY](EASY.ja.md) ステップ 2）。

---

## 4. JSON 設計図（`--spec`）全フィールド

```json
{
  "package": "com.me.app",          必須。アプリ ID
  "name": "アプリ名",                 既定 "My App"
  "icon": "icon.png",               任意。JSON と同じフォルダからの相対パス
  "icon_base64": "...",             任意。PNG を base64 で埋め込み
  "icon_color": "1E88E5",           任意。自動生成アイコンの色
  "version_code": 1, "version_name": "1.0",
  "min_sdk": 23, "target_sdk": 28,  任意
  "widgets": [ ... ]                必須。上から順に縦に並ぶ（画面に収まらなければスクロール）
}
```

### widgets（部品）

| 部品 | 書き方 | 説明 |
|---|---|---|
| 文字 | `{"type":"text","id":"名前","text":"文字"}` | `id` は任意（他の部品から書き換える目印） |
| ボタン | `{"type":"button","text":"文字","action":{...}}` | |
| 画像 | `{"type":"image","src":"a.png"}` / `"src_url":"https://…"` / `"src_base64":"…"` | PNG/JPG/WebP、5 MB まで。画面幅にフィット |
| 一覧 | `{"type":"list","items":[{"text":"…","action":{...}}, …]}` | 項目ごとに `id` と `action` を付けられる |

どの部品にも `"action"` を付けるとタップできます（`id` も付けられます）。

### action（タップしたときの動き）

| 動き | 書き方 |
|---|---|
| 文字を書き換える | `{"type":"set_text","target":"id名","text":"新しい文字"}` |
| サイトを開く | `{"type":"open_url","url":"https://…"}` |
| 短いメッセージ | `{"type":"toast","text":"文字"}` |
| ネットから読み込む | `{"type":"fetch","url":"https://…","target":"id名"}` — バックグラウンドで取得し、失敗時はエラー文を表示（落ちない）。INTERNET 権限は自動 |

`target` は `text`／`button`／一覧の項目の `id` を指します（画像は不可）。
完全な例: [`examples/spec_app/app.json`](../examples/spec_app/app.json)

---

## 5. Web アプリ（`--web` / `--html`）と JavaScript の橋

**フォルダに `index.html` を置く**（`--web`）か **HTML 1 ファイル**（`--html`）。
CSS・JS・画像・フォントは相対パスでそのまま使えます。`apkfs-bridge.js` が自動で同梱されます。

### JavaScript から使えるもの

`<script src="apkfs-bridge.js"></script>` を入れておくと `App` が使えます。

| 呼び方 | 何が起きる | 必要な `--permissions` |
|---|---|---|
| `App.toast("文字")` | 画面下に短いメッセージ | — |
| `App.open("https://…")` | 端末のブラウザで開く | — |
| `App.share("文字")` | 共有シート（LINE・メール等） | — |
| `App.copy("文字")` | クリップボードへ | — |
| `App.notify("題名","本文")` | 通知（ステータスバー） | `notify` |
| `App.exit()` | アプリを閉じる | — |

Web 標準 API はそのまま動きます（ホストが許可を通します）:

| 使うもの | 必要な `--permissions` |
|---|---|
| `alert()`（メッセージとして表示） | — |
| `localStorage` / `sessionStorage` / IndexedDB | — |
| `fetch()` / `XMLHttpRequest`（https） | —（INTERNET は常時） |
| `navigator.geolocation.getCurrentPosition(...)` | `location` |
| `navigator.mediaDevices.getUserMedia({video:true, audio:true})` | `camera` / `mic` |
| `<input type="file" accept="image/*" capture>`（撮影／写真選択） | — |
| `navigator.vibrate(ミリ秒)` | `vibrate` |
| CSS アニメーション、Canvas、WebGL、Web Audio、Service Worker | — |

- スマホの「戻る」は Web の履歴を戻り、履歴が無ければアプリを閉じます。
- 複数画面は `<a href="page2.html">` でも、1 ページ内で JS 切替でも OK。
- 起動時に `--permissions` の許可ダイアログが自動で出ます。
- **プッシュ通知（サーバー配信）・Bluetooth・NFC・バックグラウンド常駐は未対応**。

例: [`examples/web_app/site`](../examples/web_app/site)（メモ帳: 保存・一覧・共有・通信・カメラ・現在地・通知）

---

## 6. ブラウザ（GitHub Actions）フォームの全項目

Actions → **Make an APK (no coding)** → Run workflow:

| 項目 | 意味 |
|---|---|
| App id / App name / Text / Icon color | かんたんモード |
| Version number | 更新のたびに +1 |
| App spec (JSON) | 4 章の JSON をそのまま貼る（かんたんモードより優先） |
| Web app HTML | 5 章の HTML をそのまま貼る（JSON より優先） |
| permissions | Web アプリの端末機能 `camera,mic,location,vibrate,notify` |
| icon_url | 正方形 PNG の https URL（アイコン） |

署名は Secret `APK_SIGNING_KEY` があれば自動で使用（**Create signing key** ワークフローで作成）。
結果は実行ページの **Artifacts → apk** からダウンロード。

---

## 7. `apkinspect` — APK を読む

```bash
apkinspect 何か.apk
```

エントリ一覧・マニフェスト（XML 復元）・リソース（アプリ名/アイコン）・DEX の要約
（クラス/フィールド/メソッド）・v2/v3 署名の検証結果を表示します。自作でなくても読めます。

署名だけ検証: `python3 -m apkfs.verify 何か.apk`
（Python から `verify.verify(bytes, expected_cert_der=...)` で「同じ開発者か」まで確認可能）

---

## 8. Python から使う

```python
from apkfs import apkforge, appspec, webapp, keys, verify

key, cert = keys.generate("me")            # または keys.load("mykey.pem")

apk1 = apkforge.build_apk("com.me.a", "A", "hello", (0x1E,0x88,0xE5), signing_key=(key, cert))
apk2 = appspec.build_from_spec({"package":"com.me.b","widgets":[{"type":"text","text":"hi"}]},
                               signing_key=(key, cert))
apk3 = webapp.build_from_html("<h1>hi</h1>", "com.me.c", label="C",
                              permissions=["camera"], signing_key=(key, cert))
open("a.apk","wb").write(apk1)
print(verify.verify(apk1)["schemes"])      # ['v2', 'v3']
```

低レベル API（`axml`, `dex`, `dalvik`, `arsc`, `apk`, `decode`）は各モジュールの先頭コメントと
[format.md](format.md) を参照。

---

## 9. スマホに入れる

| 方法 | 手順 |
|---|---|
| ファイルを送る | `.apk` を LINE・Drive・USB でスマホへ → ファイルアプリで開く → 「提供元不明」を許可 |
| USB（adb） | PC に platform-tools を入れ、スマホの USB デバッグを ON → `adb install -r app.apk`（または `apkforge ... --install`） |
| スマホ本体で作る | [INSTALL の Termux 節](INSTALL.ja.md#e-android-スマホ本体でtermux) |

「署名が一致しません」と出たら、前回と違う鍵です。同じ `--key` を使うか、一度アンインストール。
