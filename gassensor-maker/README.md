# Gas Sensor Maker

ガスセンサの論文用の図を作る Streamlit アプリです。XRD Maker・Raman Maker などと同じ体裁（figure_style・palettes・rich_text・fonts を共有）で図を出します。

パルス解析アプリ（gas-pulse-analyzer.html）が保存したセッション (.json) を読み込みます。パルスの検出はやり直さないので、解析の表と図の数値が一致します。

## 図の種類

| 種類 | 内容 |
|---|---|
| 抵抗値の積み上げ | ランごとに縦軸の範囲と単位（Ω〜GΩ）を自動で決め、軸の切れ目で区切って積み上げる。生データ（半透明）＋移動平均 |
| 抵抗変化率の重ね合わせ | (R − R_b)/R_b を 1 つの軸に重ねる。R_b は初回導入前 1 min の中央値 |
| 濃度に対する値 | 最大応答・応答 S・回復時間 t50・5 min 後の未回復率・ベースライン変化 |
| ベースライン変化 | 各パルス直前の R0 の、R_b からのずれ |
| 回復曲線 | 選んだパルスの後の回復を、応答の大きさを 1 に揃えて描く |

## 起動

```sh
pip install -r requirements.txt
streamlit run app.py
```

Streamlit Community Cloud では main ブランチの app.py を指定します。`packages.txt`（fonts-noto-cjk）は、図の中に日本語を使うためのものです。パスワードをかけるときは Secrets に `password = "..."` を入れます（入れなければ認証なし）。

## 共有ファイル

figure_style.py・palettes.py・rich_text.py・colors.csv・fonts/ は XRD Maker（2026-11-13 の版）と同じ内容です。片方を直したら、ほかのアプリにもコピーしてください。

## テスト

```sh
python -m pytest tests
```
