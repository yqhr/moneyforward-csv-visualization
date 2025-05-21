import polars as pl
import duckdb
from rapidfuzz import fuzz
from typing import Dict, Set, List
from streamlit.runtime.uploaded_file_manager import UploadedFile
import tempfile
import os

COLUMN_MAP: Dict[str, str] = {
    "計算対象":   "include",
    "日付":       "date",
    "内容":       "description",
    "金額（円）": "amount",
    "保有金融機関": "institution",
    "大項目":     "category_main",
    "中項目":     "category_sub",
    "メモ":       "memo",
    "振替":       "transfer",
    "ID":        "id",
}

def convert_mf_csv_to_duckdb(files: List[UploadedFile]) -> duckdb.DuckDBPyConnection:
    con: duckdb.DuckDBPyConnection = duckdb.connect()

    # 一時ディレクトリを作成
    with tempfile.TemporaryDirectory() as temp_dir:
        for idx, f in enumerate(files):
            # 一時ファイルパスを作成
            temp_file_path = os.path.join(temp_dir, f"temp_csv_{idx}.csv")

            # アップロードされたファイルの内容を一時ファイルに書き込む
            with open(temp_file_path, 'wb') as temp_file:
                temp_file.write(f.read())

            # ファイルポインタをリセット（他の場所でも使用できるように）
            f.seek(0)

            # DuckDBに一時ファイルを読み込ませる
            rel = con.read_csv(
                temp_file_path,
                header=True,
                sample_size=-1
            )

            select_expr: str = ",\n            ".join(
                f'"{jp}" AS {en}' for jp, en in COLUMN_MAP.items()
            )
            rel = con.sql(f"SELECT {select_expr} FROM rel")

            if idx == 0:
                rel.create("transactions")
            else:
                con.sql("INSERT INTO transactions SELECT * FROM rel")

    return con

def prepare_and_save_data(con: duckdb.DuckDBPyConnection) -> duckdb.DuckDBPyConnection:
    def clean(text: str) -> str:
        if text is None or isinstance(text, float) and pl.Series([text]).is_null().item():
            return ""
        return str(text).strip().replace("　", "")

    # トランザクションから支出と返金を分離
    con.sql(
        "CREATE OR REPLACE TABLE expenses AS SELECT * FROM transactions WHERE include = 1 AND amount < 0;"
    )
    con.sql(
        "CREATE OR REPLACE TABLE refunds AS SELECT * FROM transactions WHERE include = 1 AND amount > 0;"
    )

    # 返金が支出のキャンセルである候補を検索
    candidates = con.execute(
        """
        -- ① 計算済みテーブルをセッション内に作成
        CREATE TEMP TABLE expenses_pre AS
        SELECT
            id,
            description,
            date,
            ABS(amount) AS abs_amount
        FROM expenses;

        CREATE TEMP TABLE refunds_pre AS
        SELECT
            id,
            description,
            date,
            ABS(amount) AS abs_amount
        FROM refunds;

        -- ② 範囲検索に効くインデックスを貼る
        CREATE INDEX idx_expenses_abs_date ON expenses_pre(abs_amount, date);
        CREATE INDEX idx_refunds_abs_date  ON refunds_pre (abs_amount, date);

        -- ③ JOIN クエリ（±100 円の例）
        SELECT
            e.id AS expense_id,
            r.id AS refund_id,
            e.description AS expense_description,
            r.description AS refund_description
        FROM expenses_pre e
        JOIN refunds_pre  r
        ON r.date BETWEEN e.date - INTERVAL '14 DAY'
                       AND e.date + INTERVAL '14 DAY'
        AND r.abs_amount BETWEEN e.abs_amount - 100
                              AND e.abs_amount + 100

        UNION ALL

        -- ④ ±5 %
        SELECT
            e.id,
            r.id,
            e.description,
            r.description
        FROM expenses_pre e
        JOIN refunds_pre  r
        ON r.date BETWEEN e.date - INTERVAL '14 DAY'
                       AND e.date + INTERVAL '14 DAY'
        AND r.abs_amount BETWEEN e.abs_amount * 0.95
                              AND e.abs_amount * 1.05;
        """
    ).pl()  # duckdb結果をpolarsデータフレームとして取得

    # 一致した返金IDと対応する支出IDを保持する集合
    matched_refund_ids: Set[str] = set()
    canceled_expense_ids: Set[str] = set()

    # 各候補の説明文の類似度を計算して、キャンセルと見なすかどうかを判断
    for row in candidates.iter_rows(named=True):
        if row["refund_id"] in matched_refund_ids:
            continue

        desc1 = clean(row["expense_description"])
        desc2 = clean(row["refund_description"])

        if not desc1 or not desc2 or desc1.lower() == "nan" or desc2.lower() == "nan":
            continue

        combined = [desc1, desc2]
        if all(len(word) < 2 for doc in combined for word in doc.split()):
            continue

        sim = fuzz.token_set_ratio(desc1, desc2) / 100.0
        if sim >= 0.8:
            matched_refund_ids.add(row["refund_id"])
            canceled_expense_ids.add(row["expense_id"])

    # 有効な支出と返金のデータフレームを取得
    valid_expenses = con.sql("SELECT * FROM expenses").pl()
    valid_refunds = con.sql("SELECT * FROM refunds").pl()

    con.close()

    # キャンセルされた項目を除外
    valid_expenses = valid_expenses.filter(~pl.col("id").is_in(list(canceled_expense_ids)))
    valid_refunds = valid_refunds.filter(~pl.col("id").is_in(list(matched_refund_ids)))

    # 新しいDuckDB接続を作成し、処理済みのデータフレームを登録
    con2: duckdb.DuckDBPyConnection = duckdb.connect()
    con2.register("valid_expenses", valid_expenses)
    con2.register("valid_refunds", valid_refunds)
    con2.execute("CREATE OR REPLACE TABLE expenses AS SELECT * FROM valid_expenses")
    con2.execute("CREATE OR REPLACE TABLE refunds AS SELECT * FROM valid_refunds")
    return con2

if __name__ == "__main__":
    pass
