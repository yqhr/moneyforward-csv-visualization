import polars as pl
from rapidfuzz import fuzz
from typing import Dict, Set, List
from streamlit.runtime.uploaded_file_manager import UploadedFile
from datetime import timedelta

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

CSV_SCHEMA: Dict[str, type[pl.Int64] | type[pl.String] | type[pl.Float64]] = {
    "計算対象": pl.Int64,
    "日付": pl.String,
    "内容": pl.String,
    "金額（円）": pl.Float64,
    "保有金融機関": pl.String,
    "大項目": pl.String,
    "中項目": pl.String,
    "メモ": pl.String,
    "振替": pl.String,
    "ID": pl.String
}

def convert_mf_csv_to_polars(files: List[UploadedFile]) -> pl.DataFrame:
    dfs = []
    for f in files:
        df = pl.read_csv(f,
                         encoding="utf8",
                         schema_overrides=CSV_SCHEMA)
        dfs += [df]
    if dfs:
        df = pl.concat(dfs, how="vertical")
        # 列名を日本語→英語に変換
        return df.rename({jp: en for jp, en in COLUMN_MAP.items() if jp in df.columns})
    else:
        return pl.DataFrame()

def prepare_and_save_data(df: pl.DataFrame) -> tuple[pl.DataFrame, pl.DataFrame]:
    def clean(text: str) -> str:
        if text is None or (isinstance(text, float) and pl.Series([text]).is_null().item()):
            return ""
        return str(text).strip().replace("　", "")

    # 必要なカラム型変換
    df = df.with_columns([
        pl.col("amount").cast(pl.Float64),
        pl.col("include").cast(pl.Int64),
        pl.col("id").cast(pl.Utf8),
        pl.col("date").str.strptime(pl.Date, "%Y/%m/%d", strict=False)
    ])

    # 支出・返金に分離
    expenses = df.filter((pl.col("include") == 1) & (pl.col("amount") < 0))
    refunds = df.filter((pl.col("include") == 1) & (pl.col("amount") > 0))

    # 返金が支出のキャンセルである候補を探す
    matched_refund_ids: Set[str] = set()
    canceled_expense_ids: Set[str] = set()

    # 返金候補の探索（±100円または±5%、日付±14日、説明類似度0.8以上）
    for exp in expenses.iter_rows(named=True):
        exp_date = exp["date"]
        exp_abs_amount = abs(exp["amount"])
        exp_desc = clean(exp["description"])
        if not exp_desc or exp_desc.lower() == "nan":
            continue

        # 日付の加減算はPythonのdatetime.dateで行う
        date_min = exp_date - timedelta(days=14)
        date_max = exp_date + timedelta(days=14)

        refund_candidates = refunds.filter(
            (pl.col("date") >= date_min) &
            (pl.col("date") <= date_max) &
            (
                ((pl.col("amount").abs() >= exp_abs_amount - 100) & (pl.col("amount").abs() <= exp_abs_amount + 100)) |
                ((pl.col("amount").abs() >= exp_abs_amount * 0.95) & (pl.col("amount").abs() <= exp_abs_amount * 1.05))
            )
        )

        for ref in refund_candidates.iter_rows(named=True):
            if ref["id"] in matched_refund_ids:
                continue
            ref_desc = clean(ref["description"])
            if not ref_desc or ref_desc.lower() == "nan":
                continue
            if all(len(word) < 2 for doc in [exp_desc, ref_desc] for word in doc.split()):
                continue
            sim = fuzz.token_set_ratio(exp_desc, ref_desc) / 100.0
            if sim >= 0.8:
                matched_refund_ids.add(ref["id"])
                canceled_expense_ids.add(exp["id"])
                break  # 1つマッチしたら次の支出へ

    # キャンセルされた項目を除外
    valid_expenses = expenses.filter(~pl.col("id").is_in(list(canceled_expense_ids)))
    valid_refunds = refunds.filter(~pl.col("id").is_in(list(matched_refund_ids)))

    return valid_expenses, valid_refunds

if __name__ == "__main__":
    pass
