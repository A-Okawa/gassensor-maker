# Gas Sensor Maker PC 版

Gas Sensor Maker を PC にダウンロードして、ブラウザーでローカル実行できます。
**初回セットアップには Python と依存パッケージが必要です。通常の ZIP は Python を含みません。**
一度セットアップすれば、起動・データ読込・描画・保存はインターネット接続なしで利用できます。
Python をインストール済みの PC なら、同じ環境向けの wheelhouse を用意して初回セットアップもオフラインにできます。

## Windows

1. Python 3.12 をインストールします。Python のインストーラーでは「Add Python to PATH」を選択してください。
2. `GasSensor-Maker-PC.zip` をすべて展開します。ZIP 内から直接実行しないでください。
3. `setup_windows.bat` をダブルクリックします。初回はパッケージのダウンロードに数分かかる場合があります。
4. セットアップ完了後、`launch_windows.bat` をダブルクリックします。ブラウザーが自動で開きます。
5. 終了するときは、起動時に開いたコマンドプロンプトで **Ctrl+C** を押してください。

## macOS

1. Python 3.12 をインストールします（Python 3.10 以降に対応、検証環境は Python 3.12）。
2. ZIP をすべて展開し、`setup_mac.command` を開きます。
3. セットアップ完了後、`launch_mac.command` を開きます。ブラウザーが自動で開きます。
4. 終了するときは、起動時に開いたターミナルで **Ctrl+C** を押してください。

`.command` を開けない場合は、ターミナルで展開先へ移動し、以下を実行できます。

```sh
bash setup_mac.command
bash launch_mac.command
```

macOS のセキュリティ確認が表示される場合は、ファイルの作成元と内容を確認してから、OS の案内に沿って許可してください。

## Linux

Python 3.10 以降と venv を用意し、展開先で以下を実行します。初回セットアップ時にはインターネットが必要です。

```sh
bash setup_linux.sh
bash launch_linux.sh
```

## 使い方

1. パルス解析アプリ（gas-pulse-analyzer.html）で生データを読み、分割とパルスの確認をして「セッション保存 (.json)」を押します。
2. Gas Sensor Maker のサイドバーで、そのセッション (.json) を読み込みます。
3. 図の種類・表示するラン・ラベル・色を選び、PDF / SVG / TIFF / PNG で保存します。

データと設定はこの PC の中だけで扱います。外部には送信しません。

## 日本語の軸ラベル

同梱のフォント（Liberation Sans / Serif）には日本語の文字がありません。図の中に日本語を使うときは、PC に入っている日本語フォント（Windows は Yu Gothic・Meiryo、macOS は Hiragino Sans、Linux は Noto Sans CJK JP）を自動で使います。

## 完全オフラインのセットアップ（任意）

インターネットにつながる同じ OS・CPU・Python の PC で、次のように wheel を集めておくと、初回セットアップもオフラインでできます。

```sh
python -m pip download -r requirements.txt -d wheelhouse
python build_bundle.py --wheelhouse wheelhouse
```
