# いちばん簡単な使い方（コマンド不要・ブラウザだけ）

プログラミングもコマンド入力も要りません。GitHub のページでボックスを埋めて
ボタンを押すだけで、あなたのアプリ（.apk）ができます。
**署名（アプリの更新に必要な鍵）も全部自動**です。

## 用意するもの

- GitHub のアカウント（無料。github.com で登録）
- スマホ、または PC のブラウザ

---

## ステップ 1: 自分用にコピーする（Fork）— 最初の1回だけ

1. このリポジトリのページ右上の **Fork** → **Create fork** を押す。
2. コピーできたら、上のタブの **Actions** を開き、
   「I understand my workflows, go ahead and enable them」を押して有効化。

## ステップ 2: 署名の鍵を作る — 最初の1回だけ（更新したいなら必須）

アプリは「鍵」で署名されます。**同じ鍵**で作った新バージョンだけが、古いバージョンの
上に上書きインストールできます。鍵が違うと「署名が一致しません」と拒否されます。

1. **リポジトリを非公開（Private）にする**:
   Settings → General → 一番下の Danger Zone → **Change visibility** → Private。
   （鍵ファイルを他人に見られないようにするため。無料でできます）
2. Actions → 左の **「Create signing key」** → **Run workflow** → 実行。
3. 実行が終わったら、そのページ下の **Artifacts** から **signing-key** をダウンロードし解凍。
4. 出てきた `signing-key.pem` をメモ帳などで開き、**全文をコピー**。
5. Settings → **Secrets and variables** → **Actions** → **New repository secret**。
   Name に `APK_SIGNING_KEY`、Value にさっきの全文を貼って **Add secret**。
6. 実行ページに戻り、Artifacts の **ゴミ箱アイコンで signing-key を削除**。
7. `signing-key.pem` は安全な場所にも保管してください。**失くすと二度と更新できません。**

これ以降、アプリを作るたびに自動でこの鍵で署名されます。

## ステップ 3: アプリを作る

Actions → 左の **「Make an APK (no coding)」** → **Run workflow**。フォームが出ます。

### かんたんモード（文字を表示するだけのアプリ）

上の4つだけ埋めて **Run workflow**:

- **App id**: 他と重複しない識別子。例 `com.yourname.hello`（半角英数と `.`）
- **App name**: アイコンの下に出る名前。例 `わたしのアプリ`
- **Text**: 画面に出る文字。例 `こんにちは！`
- **Icon color**: 6桁の色コード。例 `1E88E5`（青）`E53935`（赤）`43A047`（緑）

### 本格モード（ボタンや動きのあるアプリ）

**App spec (JSON)** の欄に、下のテンプレをコピーして貼り、好きに書き換えて
**Run workflow**。これだけで「文字」「ボタン」「タップしたときの動き」が作れます。

```json
{"package":"com.yourname.myapp","name":"わたしのアプリ","icon_color":"43A047",
 "widgets":[
  {"type":"text","id":"title","text":"こんにちは！ボタンを押してみて"},
  {"type":"image","src_url":"https://upload.wikimedia.org/wikipedia/commons/thumb/4/47/PNG_transparency_demonstration_1.png/240px-PNG_transparency_demonstration_1.png"},
  {"type":"button","text":"文字を変える","action":{"type":"set_text","target":"title","text":"変わりました ✅"}},
  {"type":"button","text":"サイトを開く","action":{"type":"open_url","url":"https://example.com"}},
  {"type":"button","text":"メッセージ","action":{"type":"toast","text":"やあ！ 👋"}},
  {"type":"text","id":"news","text":"（ここに通信の結果が出ます）"},
  {"type":"button","text":"ネットから読み込む","action":{"type":"fetch","url":"https://api.github.com/zen","target":"news"}},
  {"type":"list","items":[
    {"text":"一覧の項目 1"},
    {"text":"一覧の項目 2（タップで開く）","action":{"type":"open_url","url":"https://example.com"}},
    {"text":"一覧の項目 3"}
  ]}
 ]}
```

書き換えルール（これだけ覚えれば OK）:

| 書くもの | 意味 |
|---|---|
| `{"type":"text","id":"名前","text":"文字"}` | 文字を表示。`id` は後で書き換える目印（任意）。`action` を付けるとタップできる |
| `{"type":"button","text":"ボタンの文字","action":{...}}` | ボタン。押したときの `action` を1つ付けられる |
| `{"type":"image","src_url":"https://…/画像.png"}` | **画像**を表示（画面幅に合わせて縮小）。PNG/JPG。`src_url` はネット上の画像のURL |
| `{"type":"list","items":[{"text":"…"},{"text":"…","action":{...}}]}` | **一覧**。項目は上から並び、項目ごとに `action` を付けられる |
| `{"type":"set_text","target":"名前","text":"新しい文字"}` | `id` が「名前」の文字を書き換える |
| `{"type":"open_url","url":"https://..."}` | サイトをブラウザで開く |
| `{"type":"toast","text":"文字"}` | 画面下に短いメッセージを出す |
| `{"type":"fetch","url":"https://...","target":"名前"}` | **通信**。URL の中身（文字）を取ってきて `id` が「名前」の場所に表示。失敗してもアプリは落ちず、エラー内容を表示 |

`widgets` の中身は上から順に縦に並び、画面に収まらなければ**スクロール**します。
好きな数だけ足せます。日本語・絵文字もそのまま使えます。
`fetch` を使うと、アプリに「インターネット」の許可が自動で付きます（`https://` のみ）。

### 更新するとき

**Version number** を前回より1大きくして（1 → 2 → 3 …）もう一度作るだけ。
ステップ 2 の鍵で署名されるので、スマホでそのまま上書きインストールできます。

## ステップ 4: ダウンロードしてスマホに入れる

1. 実行が緑のチェックになったら、その実行ページ下の **Artifacts** の **apk** をクリック。
   `apk.zip` が落ちてくるので解凍すると `app.apk` が出ます。
2. Android スマホに `app.apk` をコピーし、ファイルアプリから開く。
3. 「提供元不明のアプリ」の許可を求められたら許可（自分で作ったアプリなので安全です。
   ストア外アプリを入れるとき Android が毎回出す確認です）。

---

## うまくいかないとき

- **Actions にワークフローが出ない** → Fork したか、Actions を有効化したか確認。
- **赤い×で失敗** → 実行ページの赤い行を開くと理由が出ます。よくある原因:
  - App id が `com.` のような `.` 入りの半角英数になっていない
  - Icon color が6桁の 0-9 / A-F になっていない
  - JSON の `,` や `"` の付け忘れ（テンプレからコピーして少しずつ変えると安全）
  - `set_text` の `target` に、存在しない `id` を書いている
- **「署名が一致しません」で入らない** → 前回と違う鍵で作られています。ステップ 2 の
  鍵（`APK_SIGNING_KEY`）が設定されているか確認。最初に鍵なしで作った版は一度
  アンインストールしてから入れ直してください。
- それでも分からなければ [サポート](../SUPPORT.md)（Discord）へ。
  **個人の方のサポートまで対応**しています。

---

これで「文字・ボタン・画像・一覧・通信」を持つスクロールする1画面アプリを、
コードなし・ブラウザだけで作って更新までできます。複数画面・入力フォーム・カメラなど
は今後の拡張ですが、**自分の手で本物の署名済みアプリを作る**ことは、ここで全部できます。
