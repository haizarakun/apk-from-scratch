# レシピ集（「〜したい」から引く）

すべて `pip install apk-from-scratch` 済みの前提。ブラウザ派は同じ内容を
[フォーム](USAGE.ja.md#6-ブラウザgithub-actionsフォームの全項目)に貼れば同じです。

## まず 1 個作りたい
```bash
apkforge --package com.me.first --label "はじめて" --message "できた！" -o first.apk
```
コマンドを覚えたくないなら `apkforge`（引数なし）で質問に答えるだけ。

## 更新できるアプリにしたい（一番大事）
```bash
apkforge keygen -o mykey.pem                       # 1 回だけ
apkforge ... --key mykey.pem --version-code 1 -o v1.apk
apkforge ... --key mykey.pem --version-code 2 -o v2.apk   # v1 の上に入る
```

## 自分のアイコンにしたい
```bash
apkforge ... --icon myicon.png       # 正方形 PNG（192×192 以上推奨）
```
JSON なら `"icon": "myicon.png"`、フォームなら `icon_url`。

## ボタンを押したら文字が変わる
```json
{"package":"com.me.b","name":"ボタン","widgets":[
 {"type":"text","id":"t","text":"押してみて"},
 {"type":"button","text":"押す","action":{"type":"set_text","target":"t","text":"押した！"}}]}
```
```bash
apkforge --spec app.json -o app.apk
```

## サイトへのショートカットアプリ
```json
{"package":"com.me.site","name":"マイサイト","widgets":[
 {"type":"button","text":"開く","action":{"type":"open_url","url":"https://example.com"}}]}
```
または HTML 1 行で全画面表示: `<meta http-equiv="refresh" content="0;url=https://example.com">`
を `--html` に渡す（アプリ内で表示。戻るボタンも効く）。

## 画像ギャラリー（一覧＋画像）
```json
{"package":"com.me.gallery","name":"写真","widgets":[
 {"type":"image","src":"1.jpg"},{"type":"image","src":"2.jpg"},
 {"type":"list","items":[{"text":"1 枚目の説明"},{"text":"2 枚目の説明"}]}]}
```

## ネットのデータを表示する（API 連携）
```json
{"type":"button","text":"更新","action":{"type":"fetch","url":"https://api.example.com/now","target":"out"}}
```
複雑な整形が要るなら Web アプリで `fetch()` → JS で加工。

## メモ帳・ToDo（保存つき）
`examples/web_app/site/index.html` をコピーして `--web` で。保存は `localStorage`。

## 入力フォーム（名前・数字・選択）
HTML の `<input>`, `<select>`, `<textarea>` がそのまま使えます。送信先が要るなら `fetch()` で POST。
```html
<input id="n" placeholder="名前"><button onclick="App.toast('こんにちは ' + n.value)">送信</button>
```

## 複数画面
- 簡単: `index.html` から `<a href="second.html">次へ</a>`（戻るボタンで戻れる）
- 1 ページ内: `<section>` を JS で `hidden` 切替

## カメラで撮って表示
```html
<input type="file" accept="image/*" capture onchange="img.src=URL.createObjectURL(this.files[0])"><img id="img">
```
（`--permissions` 不要。ライブ映像なら `getUserMedia` ＋ `--permissions camera`）

## 現在地を表示
```html
<button onclick="navigator.geolocation.getCurrentPosition(p=>alert(p.coords.latitude+','+p.coords.longitude))">現在地</button>
```
`--permissions location`

## 通知を出す
```html
<button onclick="App.notify('リマインダー','水を飲もう')">通知</button>
```
`--permissions notify`

## バイブ・共有・コピー
```html
<button onclick="navigator.vibrate(300)">ブルッ</button>       <!-- --permissions vibrate -->
<button onclick="App.share(location.href)">共有</button>
<button onclick="App.copy('ABC')">コピー</button>
```

## ChatGPT / Claude に書かせたアプリを APK にする
「〜というアプリを **HTML 1 ファイル**（CSS/JS 埋め込み、外部ライブラリなし）で書いて」と頼み、
出てきた HTML を `index.html` に保存 → `apkforge --html index.html --package com.me.ai -o ai.apk`。
ブラウザ派はフォームの **Web app HTML** に貼るだけ。

## ゲーム（Canvas）
HTML の `<canvas>` ＋ JS がそのまま動きます。`<meta name="viewport" content="width=device-width">`
を忘れずに。フルスクリーン感を出すなら `body{margin:0}`。

## オフラインで動くようにしたい
Web アプリはファイルが APK に同梱されるので、外部 URL を参照しなければ**最初からオフライン**です。

## 古い Android でも動かしたい / 新しい API を使いたい
```bash
apkforge ... --min-sdk 21          # Android 5.0 から（通知は 8.0 未満でトーストに）
apkforge ... --target-sdk 33
```

## 作った APK の中身を確認したい
```bash
apkinspect app.apk
```

## 他人の APK が改ざんされていないか確かめたい
```bash
python3 -m apkfs.verify their.apk     # 署名の整合性
```
「同じ開発者か」まで見るなら Python で `verify.verify(data, expected_cert_der=...)`。

## USB でそのまま端末へ
```bash
apkforge ... --install                 # adb が必要
```

## スマホだけで完結させたい（PC なし）
[INSTALL の Termux 節](INSTALL.ja.md#e-android-スマホ本体でtermux)。

## 自分のプログラム（Python）から自動生成したい
[USAGE 8 章](USAGE.ja.md#8-python-から使う)。
