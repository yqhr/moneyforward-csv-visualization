# moneyforward-expense-csv-visualization

マネーフォワード MEからダウンロードされる月別/年別の支出ファイルを可視化します。

![demo](https://raw.githubusercontent.com/wiki/yqhr/moneyforward-expense-csv-visualization/images/demo.gif)

## 何ができるか

- 月別、年別を指定してグラフの表示。どちらも複数指定可能。

- カテゴリーの大項目、中項目別の支出についての以下のグラフの表示。
  - 円グラフ
  - 横棒グラフ
  - パレート図
  - 月別支出ポートフォリオ
  - 週別支出ポートフォリオ
  - 箱ひげ図


- 指定した中項目の支出一覧表示。

- 指定した中項目の支出箱ひげ図を表示。

## CSVファイルのダウンロード方法

- ![マネーフォワード MEサポートサイト](https://support.me.moneyforward.com/hc/ja/articles/900004382483-%E5%85%A5%E5%87%BA%E9%87%91%E5%B1%A5%E6%AD%B4%E3%81%AF%E3%83%80%E3%82%A6%E3%83%B3%E3%83%AD%E3%83%BC%E3%83%89%E3%81%A7%E3%81%8D%E3%81%BE%E3%81%99%E3%81%8B) を参照ください。

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
