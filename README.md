# moneyforward-csv-visualization
マネーフォワード MEからダウンロードされる月別/年別の支出ファイルを視覚化します。
すべての処理はメモリ上で実施されます。

![demo](https://raw.githubusercontent.com/wiki/yqhr/moneyforward-csv-visualization/images/demo.gif)

## 実行環境
- Python 3.13で確認
- ![uv](https://github.com/astral-sh/uv)（高速なPythonパッケージマネージャー）

## 使い方
1. このリポジトリをクローンします。
```
git clone https://github.com/yqhr/moneyforward-csv-visualization
cd moneyforward-csv-visualization
```
2. uvで仮想環境を作成します。
```
uv venv
```
3. 仮想環境をアクティベートする。
```
source .venv/bin/activate
```
4. uvで依存パッケージをインストールする。
```
uv sync
```
5. streamlitで起動する。
```
streamlit run app.py
```
6. ![localhost:8501](http://localhost:8501) にアクセスする。
