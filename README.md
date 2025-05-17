# moneyforward-csv-visualization
マネーフォワード MEからダウンロードされる月別/年別の支出ファイルを視覚化します。

![demo](https://raw.githubusercontent.com/wiki/yqhr/moneyforward-csv-visualization/images/demo.gif)

## 使い方
1. このリポジトリをクローンします。
```
git clone https://github.com/yqhr/moneyforward-csv-visualization
cd moneyforward-csv-visualization
```
2. ![uv](https://github.com/astral-sh/uv)で仮想環境を作成します。
```
uv venv
```
3. uvで依存パッケージをインストールする。
```
uv sync
```
4. streamlitで起動する。
```
streamlit run app.py
```
