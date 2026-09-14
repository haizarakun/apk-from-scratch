# 導入手順（全環境）

自分の環境の節だけ読めば OK です。**どの環境でも「Python 3.8 以上」＋ `pip install` の 1 行**が本体で、
Android SDK・Java・Android Studio は一切要りません。

| あなたの環境 | 読む節 |
|---|---|
| PC もコマンドも触りたくない | [A. ブラウザだけ](#a-ブラウザだけpc不要) |
| Windows | [B. Windows](#b-windows) |
| Mac | [C. Mac](#c-mac) |
| Linux | [D. Linux](#d-linux) |
| **Android スマホ本体で作りたい**（PC なし） | [E. Android（Termux）](#e-android-スマホ本体でtermux) |
| 開発に参加したい | [F. 開発者向け](#f-開発者向けソースから) |

---

## A. ブラウザだけ（PC 不要）

GitHub の画面でボタンを押すだけです。手順は **[いちばん簡単な使い方](EASY.ja.md)** を
そのまま読んでください（Fork → 鍵作成 → フォーム入力 → APK をダウンロード）。
インストールという作業自体がありません。

---

## B. Windows

1. **Python を入れる**: [python.org/downloads](https://www.python.org/downloads/) から
   最新版をダウンロードして実行。**「Add python.exe to PATH」に必ずチェック**を入れて Install。
   （Microsoft Store 版の Python でも可）
2. **PowerShell** を開く（スタートで「powershell」と入力）。
3. 次を打つ:
   ```powershell
   pip install apk-from-scratch
   apkforge --version 2>$null; apkforge --help
   ```
   `apkforge` のヘルプが出れば完了。

`apkforge` が見つからないと言われたら → `python -m apkfs.apkforge --help` で代替できます
（PATH の設定が効いていないだけ。PowerShell を開き直すと直ることが多い）。

---

## C. Mac

1. **ターミナル**を開く（Spotlight で「ターミナル」）。
2. Python 3 は macOS に同梱されていることが多いです。無ければ
   [python.org](https://www.python.org/downloads/) から入れるか、Homebrew で `brew install python`。
3. 次を打つ:
   ```bash
   python3 -m pip install --user apk-from-scratch
   apkforge --help
   ```
   `apkforge` が見つからない場合は `python3 -m apkfs.apkforge --help`。
   （`--user` で入れたコマンドは `~/Library/Python/3.x/bin` にあります。
   `pipx install apk-from-scratch` を使うと PATH の悩みがありません）

---

## D. Linux

```bash
sudo apt install python3 python3-pip        # Debian/Ubuntu の場合
python3 -m pip install --user apk-from-scratch
apkforge --help
```

`externally-managed-environment` と出る最近のディストリでは、どちらかで:

```bash
pipx install apk-from-scratch                       # 推奨
# または
python3 -m venv ~/apkfs && ~/apkfs/bin/pip install apk-from-scratch && ~/apkfs/bin/apkforge --help
```

端末にそのまま入れたいなら `sudo apt install adb` の後、`apkforge ... --install`。

---

## E. Android スマホ本体で（Termux）

**PC なしで、スマホの中で APK を作って、そのまま自分にインストール**できます。

1. **Termux** を入れる（Google Play 版は古いので **F-Droid** か GitHub Releases から）。
2. Termux を開いて次を打つ（1 行ずつ）:
   ```bash
   pkg update && pkg install python rust binutils -y
   pip install apk-from-scratch
   apkforge --help
   ```
   ※ `cryptography` のビルドに `rust` が要ることがあります（数分かかる）。
   `pkg install python-cryptography` が使える場合はそちらが速いです。
3. アプリを作る:
   ```bash
   apkforge keygen -o ~/mykey.pem
   apkforge --package com.me.hello --label "こんにちは" --message "スマホで作った" --key ~/mykey.pem -o ~/hello.apk
   termux-setup-storage            # 初回だけ。ストレージ許可を出す
   cp ~/hello.apk ~/storage/downloads/
   ```
4. スマホの「ファイル」アプリで **ダウンロード** フォルダの `hello.apk` を開いてインストール。

Termux の中で HTML を書けば（`nano index.html`）、`apkforge --html index.html ...` でそのまま
Web アプリにもできます。

---

## F. 開発者向け（ソースから）

```bash
git clone https://github.com/haizarakun/apk-from-scratch.git
cd apk-from-scratch
python3 -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -e ".[test]"                                # androguard + pytest も入る
python3 tests/test_build.py                             # all tests passed と出れば OK
```

---

## 更新・削除

```bash
pip install -U apk-from-scratch      # 更新
pip uninstall apk-from-scratch       # 削除
```

## 導入で詰まったら

| 症状 | 対処 |
|---|---|
| `pip` が無い | `python3 -m ensurepip --upgrade` を実行。Windows は Python を「Add to PATH」で入れ直す |
| `apkforge` コマンドが無い | `python3 -m apkfs.apkforge` で同じことができる。または `pipx` で入れ直す |
| `cryptography` のインストールで失敗 | `pip install -U pip` してから再実行。Termux は `pkg install rust`。古い Python(3.7 以下)は非対応 |
| `Permission denied` | `--user` を付ける、または venv/pipx を使う（`sudo pip` は避ける） |
| プロキシ環境 | `pip install --proxy http://host:port apk-from-scratch` |
| ネット無しの PC に入れたい | ネットのある PC で `pip download apk-from-scratch -d pkgs` → コピーして `pip install --no-index -f pkgs apk-from-scratch` |

それでも駄目なら [サポート](../SUPPORT.md)（Discord）へ。個人の方まで対応します。
