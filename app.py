import streamlit as st
import plotly.graph_objects as go
import plotly.express as px
from prepare_data import prepare_and_save_data, convert_mf_csv_to_duckdb
import duckdb
import polars as pl
from typing import List, Tuple, Optional
from streamlit.runtime.uploaded_file_manager import UploadedFile

st.set_page_config(page_title="Expense Analysis", layout="wide")

st.title("Expense Analysis")

def _load_csvs(files: List[UploadedFile]) -> duckdb.DuckDBPyConnection:
    con: duckdb.DuckDBPyConnection = convert_mf_csv_to_duckdb(files)
    return con

@st.cache_data(show_spinner=True)
def load_and_processed_data(files: List[UploadedFile]) -> Tuple[pl.DataFrame, pl.DataFrame]:
    con: duckdb.DuckDBPyConnection = _load_csvs(files)
    con2: duckdb.DuckDBPyConnection = prepare_and_save_data(con)
    con.close()

    expenses: pl.DataFrame = con2.execute(
        """
        SELECT
            *,
            strftime(date, '%Y-%m') AS month,
            strftime(date, '%Y') AS year
        FROM expenses;
        """
    ).pl()

    refunds: pl.DataFrame = con2.execute(
        """
        SELECT
            *,
            strftime(date, '%Y-%m') AS month,
            strftime(date, '%Y') AS year
        FROM refunds;
        """
    ).pl()

    con2.close()
    return expenses, refunds

# ファイルアップローダー
files: List[UploadedFile] | None = st.file_uploader(
    "📤 Upload CSV files (multiple selection allowed)",
    type="csv",
    accept_multiple_files=True,
)

if not files:
    st.info("Please add MoneyForward data using the **📤 CSV Upload** in the upper left.")
    st.stop()

expenses: pl.DataFrame
refunds: pl.DataFrame
expenses, refunds = load_and_processed_data(files)

# 表示タイプの選択
display_type: str = st.selectbox("Select display type", ["Monthly", "Yearly"])

# 月別表示部分
if display_type == "Monthly":
    month_options: List[str] = sorted(expenses.select("month").filter(pl.col("month").is_not_null()).unique().to_series().to_list())
    selected_months: List[str] = st.multiselect(
        "Select months", month_options, default=[month_options[-1]]
    )
    if len(selected_months) == 0:
        st.stop()

    expenses_month: pl.DataFrame = expenses.filter(pl.col("month").is_in(selected_months))
    refunds_month: pl.DataFrame = refunds.filter(pl.col("month").is_in(selected_months))

    selected_month_label: str = (
        ", ".join(selected_months)
        if len(selected_months) <= 3
        else f"{selected_months[0]} and others"
    )

    # カテゴリー別の純支出を計算
    summary: pl.DataFrame = (
        expenses_month.group_by("category_main")
        .agg(pl.col("amount").abs().sum().alias("expense"))
        .sort("expense", descending=True)
        .filter(pl.col("expense") > 0)
    )

    refund_by_cat = (
        refunds_month.group_by("category_main")
        .agg(pl.col("amount").sum().alias("refund"))
    )

    # 左外部結合で返金データを追加
    summary = summary.join(refund_by_cat, on="category_main", how="left").fill_null(0)

    # パーセンテージと累積値を計算
    total_expense = summary["expense"].sum()
    summary = summary.with_columns([
        (pl.col("expense") / total_expense * 100).alias("percentage"),
    ])
    summary = summary.with_columns([
        pl.col("percentage").cum_sum().alias("cumulative_percentage")
    ])

    # パレート図
    fig = go.Figure()
    fig.add_bar(
        x=summary["category_main"],
        y=summary["expense"],
        name="Net expense",
        marker_color=px.colors.qualitative.Pastel,
    )
    fig.add_trace(
        go.Scatter(
            x=summary["category_main"],
            y=summary["cumulative_percentage"],
            mode="lines+markers",
            name="Cumulative %",
            yaxis="y2",
            line=dict(color="orange", width=2),
        )
    )
    fig.update_layout(
        yaxis=dict(title="Net expense (JPY)"),
        yaxis2=dict(
            title="Cumulative %",
            overlaying="y",
            side="right",
            type="linear",
            tickmode="array",
            tickvals=[0, 20, 40, 60, 80, 100],
            ticktext=["0%", "20%", "40%", "60%", "80%", "100%"],
            showgrid=False,
            zeroline=False,
            showline=False,
        ),
        title=f"Expense Pareto Analysis (By Main Category) - {selected_month_label}",
        height=500,
    )
    fig.add_shape(
        type="line",
        x0=-0.5,
        x1=len(summary["category_main"]) - 0.5,
        y0=80,
        y1=80,
        xref="x",
        yref="y2",
        line=dict(color="red", width=2, dash="dash"),
    )
    # --- タブを使った主要カテゴリの可視化（円グラフ、棒グラフ、パレート図、時系列） ---
    # 円グラフ
    fig_pie_main = go.Figure()
    fig_pie_main.add_trace(
        go.Pie(labels=summary["category_main"], values=summary["expense"], hole=0.4)
    )
    fig_pie_main.update_layout(title_text=f"Main Category Expense Composition - {selected_month_label}")

    # 水平棒グラフ
    fig_bar_main = go.Figure()
    fig_bar_main.add_trace(
        go.Bar(
            x=summary["expense"],
            y=summary["category_main"],
            orientation="h",
            text=[f"{p:.1f}%" for p in summary["percentage"]],
            textposition="outside",
        )
    )
    fig_bar_main.update_layout(
        title=f"Main Category Expenses - {selected_month_label}",
        xaxis_title="Net expense (JPY)",
        yaxis_title="",
    )

    # 月次支出の積み上げエリアチャート
    monthly_portfolio = (
        expenses_month
        .group_by(["date", "category_main"])
        .agg(pl.col("amount").abs().sum())
        .sort("date")
    )

    fig_stacked_area = px.area(
        monthly_portfolio,
        x="date",
        y="amount",
        color="category_main",
        title=f"Monthly Expense Portfolio - {selected_month_label}",
        labels={"amount": "Expense (JPY)", "date": "Date", "category_main": "Category"},
    )

    # 週次の積み上げエリアチャート
    weekly_portfolio = (
        expenses_month
        .with_columns(
            pl.col("date").dt.truncate("1w").alias("week_date")
        )
        .group_by(["week_date", "category_main"])
        .agg(pl.col("amount").abs().sum())
        .sort("week_date")
    )

    fig_weekly_area = px.area(
        weekly_portfolio,
        x="week_date",
        y="amount",
        color="category_main",
        title=f"Weekly Expense Portfolio - {selected_month_label}",
        labels={"amount": "Expense (JPY)", "week_date": "Week", "category_main": "Category"},
    )

    # 箱ひげ図
    # 日付ごとのカテゴリ別データを準備
    daily_by_category = expenses_month.with_columns(pl.col("amount").abs().alias("amount"))

    # 大項目ごとの箱ひげ図
    fig_box_main = px.box(
        daily_by_category,
        x="category_main",
        y="amount",
        title=f"Expense Distribution (By Main Category) - {selected_month_label}",
        labels={"category_main": "Category", "amount": "Expense (JPY)"}
    )
    fig_box_main.update_layout(
        xaxis_title="Category",
        yaxis_title="Expense (JPY)",
        height=500
    )
    # タブを更新
    tab_m1, tab_m2, tab_m3, tab_m4, tab_m5, tab_m6 = st.tabs(
        ["Pie Chart", "Horizontal Bar Chart", "Pareto Chart", "Monthly Portfolio", "Weekly Portfolio", "Box Plot"]
    )
    with tab_m1:
        st.plotly_chart(fig_pie_main, use_container_width=True)
    with tab_m2:
        st.plotly_chart(fig_bar_main, use_container_width=True)
    with tab_m3:
        st.plotly_chart(fig, use_container_width=True)
    with tab_m4:
        st.plotly_chart(fig_stacked_area, use_container_width=True)
    with tab_m5:
        st.plotly_chart(fig_weekly_area, use_container_width=True)
    with tab_m6:
        st.plotly_chart(fig_box_main, use_container_width=True)

    # メインカテゴリの選択とサブカテゴリの内訳（円グラフ + 水平棒グラフ）
    selected_category: str = st.selectbox(
        "Select a main category to view breakdown", summary["category_main"].to_list()
    )

    sub_data: pl.DataFrame = expenses_month.filter(pl.col("category_main") == selected_category)
    sub_summary: pl.DataFrame = (
        sub_data.group_by("category_sub")
        .agg(pl.col("amount").abs().sum().alias("amount"))
        .sort("amount", descending=True)
    )

    # サブカテゴリごとの割合を計算
    total_sub_amount = sub_summary["amount"].sum()
    sub_summary = sub_summary.with_columns(
        (pl.col("amount") / total_sub_amount * 100).alias("percentage")
    )

    if len(sub_summary) > 0:
        col1, col2 = st.columns(2)

        with col1:
            fig_pie = go.Figure()
            fig_pie.add_trace(
                go.Pie(
                    labels=sub_summary["category_sub"],
                    values=sub_summary["amount"],
                    hole=0.4,
                )
            )
            fig_pie.update_layout(
                title_text=f"{selected_category} Breakdown - {selected_month_label}"
            )

        with col2:
            fig_bar = go.Figure()
            fig_bar.add_trace(
                go.Bar(
                    x=sub_summary["amount"],
                    y=sub_summary["category_sub"],
                    orientation="h",
                    text=[f"{p:.1f}%" for p in sub_summary["percentage"]],
                    textposition="outside",
                )
            )
            fig_bar.update_layout(
                title=f"{selected_category} Subcategory Expenses - {selected_month_label}",
                xaxis_title="Expense (JPY)",
                yaxis_title="",
            )

        # パレート図用に累積パーセンテージを計算
        sub_summary = sub_summary.with_columns(
            pl.col("percentage").cum_sum().alias("cumulative_percentage")
        )

        fig_pareto = go.Figure()
        fig_pareto.add_bar(
            x=sub_summary["category_sub"], y=sub_summary["amount"], name="Expense"
        )
        fig_pareto.add_trace(
            go.Scatter(
                x=sub_summary["category_sub"],
                y=sub_summary["cumulative_percentage"],
                mode="lines+markers",
                name="Cumulative %",
                yaxis="y2",
                line=dict(color="orange", width=2),
            )
        )
        fig_pareto.update_layout(
            yaxis=dict(title="Expense (JPY)"),
            yaxis2=dict(
                title="Cumulative %",
                overlaying="y",
                side="right",
                type="linear",
                tickmode="array",
                tickvals=[0, 20, 40, 60, 80, 100],
                ticktext=["0%", "20%", "40%", "60%", "80%", "100%"],
                showgrid=False,
                zeroline=False,
                showline=False,
            ),
            title=f"{selected_category} Subcategory Pareto Chart - {selected_month_label}",
            height=400,
        )
        fig_pareto.add_shape(
            type="line",
            x0=-0.5,
            x1=len(sub_summary["category_sub"]) - 0.5,
            y0=80,
            y1=80,
            xref="x",
            yref="y2",
            line=dict(color="red", width=2, dash="dash"),
        )

        # サブカテゴリの月次積み上げエリアチャート
        sub_monthly_portfolio = (
            sub_data
            .group_by(["month", "category_sub"])
            .agg(pl.col("amount").abs().sum())
        )

        # 日付順にソート
        sub_monthly_portfolio = sub_monthly_portfolio.with_columns(
            pl.col("month").str.strptime(pl.Date, "%Y-%m").alias("month_date")
        ).sort("month_date")

        fig_sub_monthly_area = px.area(
            sub_monthly_portfolio,
            x="month",
            y="amount",
            color="category_sub",
            title=f"{selected_category} Monthly Subcategory Portfolio - {selected_month_label}",
            labels={"amount": "Expense (JPY)", "month": "Month", "category_sub": "Subcategory"},
        )

        # サブカテゴリの週次積み上げエリアチャート
        sub_weekly_portfolio = (
            sub_data
            .with_columns(
                pl.col("date").dt.truncate("1w").alias("week_date")
            )
            .group_by(["week_date", "category_sub"])
            .agg(pl.col("amount").abs().sum())
            .sort("week_date")
        )

        fig_sub_weekly_area = px.area(
            sub_weekly_portfolio,
            x="week_date",
            y="amount",
            color="category_sub",
            title=f"{selected_category} Weekly Subcategory Portfolio - {selected_month_label}",
            labels={"amount": "Expense (JPY)", "week_date": "Week", "category_sub": "Subcategory"},
        )

        # 中項目の箱ひげ図
        sub_data_for_box = sub_data.with_columns(pl.col("amount").abs().alias("amount"))

        fig_box_sub = px.box(
            sub_data_for_box,
            x="category_sub",
            y="amount",
            title=f"{selected_category} Subcategory Distribution - {selected_month_label}",
            labels={"category_sub": "Subcategory", "amount": "Expense (JPY)"}
        )
        fig_box_sub.update_layout(
            xaxis_title="Subcategory",
            yaxis_title="Expense (JPY)",
            height=400
        )

        # 中項目のタブ名
        tab1, tab2, tab3, tab4, tab5, tab6, = st.tabs(
            ["Pie Chart", "Bar Chart", "Pareto Chart", "Monthly Portfolio", "Weekly Portfolio", "Box Plot"]
        )

        with tab1:
            st.plotly_chart(fig_pie, use_container_width=True)
        with tab2:
            st.plotly_chart(fig_bar, use_container_width=True)
        with tab3:
            st.plotly_chart(fig_pareto, use_container_width=True)
        with tab4:
            st.plotly_chart(fig_sub_monthly_area, use_container_width=True)
        with tab5:
            st.plotly_chart(fig_sub_weekly_area, use_container_width=True)
        with tab6:
            st.plotly_chart(fig_box_sub, use_container_width=True)

        with st.container():
            detail_df = expenses_month.filter(pl.col("category_main") == selected_category)
            category_sub_options = ["All"] + sorted(
                detail_df.select("category_sub").filter(pl.col("category_sub").is_not_null()).unique().to_series().to_list()
            )
            selected_sub: str = st.selectbox(
                "Select subcategory", category_sub_options
            )
            if selected_sub != "All":
                detail_df = detail_df.filter(pl.col("category_sub") == selected_sub)

            detail_df = detail_df.select(
                "date", "description", "amount", "category_main", "category_sub", "memo"
            ).sort("date")

            st.markdown("#### Transaction Details")
            st.data_editor(detail_df, use_container_width=True, height=300)

            detail_df_desc = detail_df.with_columns(pl.col("amount").abs().alias("amount"))

            fig_box_desc = px.box(
                detail_df_desc,
                x="description",
                y="amount",
                title=f"{selected_category} Description Distribution - {selected_month_label}",
                labels={"description": "Description", "amount": "Expense (JPY)"}
            )
            fig_box_desc.update_layout(
                xaxis_title="Description",
                yaxis_title="Expense (JPY)",
                height=300
            )
            st.plotly_chart(fig_box_desc, use_container_width=True)

    else:
        st.info("No subcategory data found.")

if display_type == "Yearly":
    year_options = sorted(expenses.select("year").filter(pl.col("year").is_not_null()).unique().to_series().to_list())
    year_options_int = [int(y) for y in year_options]

    selected_years = st.multiselect(
        "Select years",
        options=year_options_int,
        default=[max(year_options_int)],  # デフォルトは最新の年
    )

    if not selected_years:
        st.warning("Please select at least one year to display data.")
        st.stop()

    selected_year_label: str = (
        f"{selected_years[0]}" if len(selected_years) == 1
        else f"{min(selected_years)}–{max(selected_years)}"
    )

    # 年別データの抽出
    expenses_year = expenses.filter(pl.col("year").cast(pl.Int32).is_in(selected_years))

    # 集計
    summary = (
        expenses_year
        .group_by("category_main")
        .agg(pl.col("amount").abs().sum().alias("expense"))
        .filter(pl.col("expense") > 0)
        .sort("expense", descending=True)
    )

    # パーセンテージと累積値を計算
    total_expense = summary["expense"].sum()
    summary = summary.with_columns([
        (pl.col("expense") / total_expense * 100).alias("percentage"),
    ])
    summary = summary.with_columns([
        pl.col("percentage").cum_sum().alias("cumulative_percentage")
    ])

    fig = go.Figure()
    fig.add_bar(
        x=summary["category_main"],
        y=summary["expense"],
        name="Net expense",
        marker_color=px.colors.qualitative.Pastel,
    )
    fig.add_trace(
        go.Scatter(
            x=summary["category_main"],
            y=summary["cumulative_percentage"],
            mode="lines+markers",
            name="Cumulative %",
            yaxis="y2",
            line=dict(color="orange", width=2),
        )
    )
    fig.update_layout(
        yaxis=dict(title="Net expense (JPY)"),
        yaxis2=dict(
            title="Cumulative %",
            overlaying="y",
            side="right",
            type="linear",
            tickmode="array",
            tickvals=[0, 20, 40, 60, 80, 100],
            ticktext=["0%", "20%", "40%", "60%", "80%", "100%"],
            showgrid=False,
            zeroline=False,
            showline=False,
        ),
        title=f"Expense Pareto Analysis (By Main Category) - {selected_year_label}",
        height=500,
    )
    fig.add_shape(
        type="line",
        x0=-0.5,
        x1=len(summary["category_main"]) - 0.5,
        y0=80,
        y1=80,
        xref="x",
        yref="y2",
        line=dict(color="red", width=2, dash="dash"),
    )
    # --- タブを使った主要カテゴリの可視化（円グラフ、棒グラフ、パレート図、時系列） ---
    # 円グラフ
    fig_pie_main = go.Figure()
    fig_pie_main.add_trace(
        go.Pie(labels=summary["category_main"], values=summary["expense"], hole=0.4)
    )
    fig_pie_main.update_layout(title_text=f"Main Category Expense Composition - {selected_year_label}")

    # 水平棒グラフ
    fig_bar_main = go.Figure()
    fig_bar_main.add_trace(
        go.Bar(
            x=summary["expense"],
            y=summary["category_main"],
            orientation="h",
            text=[f"{p:.1f}%" for p in summary["percentage"]],
            textposition="outside",
        )
    )
    fig_bar_main.update_layout(
        title=f"Main Category Expenses - {selected_year_label}",
        xaxis_title="Net expense (JPY)",
        yaxis_title="",
    )

    # 月別の年間支出の積み上げエリアチャート
    yearly_portfolio = (
        expenses_year
        .group_by(["month", "category_main"])
        .agg(pl.col("amount").abs().sum())
    )

    # 日付順にソート
    yearly_portfolio = yearly_portfolio.with_columns(
        pl.col("month").str.strptime(pl.Date, "%Y-%m").alias("month_date")
    ).sort("month_date")

    fig_stacked_area = px.area(
        yearly_portfolio,
        x="month",
        y="amount",
        color="category_main",
        title=f"Monthly Expense Portfolio - {selected_year_label}",
        labels={"amount": "Expense (JPY)", "month": "Month", "category_main": "Category"},
    )

    # 週ごとの積み上げ面グラフを追加
    weekly_yearly_portfolio = (
        expenses_year
        .with_columns(
            pl.col("date").dt.truncate("1w").alias("week_date")
        )
        .group_by(["week_date", "category_main"])
        .agg(pl.col("amount").abs().sum())
        .sort("week_date")
    )

    fig_weekly_yearly_area = px.area(
        weekly_yearly_portfolio,
        x="week_date",
        y="amount",
        color="category_main",
        title=f"Weekly Expense Portfolio - {selected_year_label}",
        labels={"amount": "Expense (JPY)", "week_date": "Week", "category_main": "Category"},
    )

    # 箱ひげ図
    # 日付ごとのカテゴリ別データを準備
    daily_by_category = expenses_year.with_columns(pl.col("amount").abs().alias("amount"))

    # 大項目ごとの箱ひげ図
    fig_box_main = px.box(
        daily_by_category,
        x="category_main",
        y="amount",
        title=f"Expense Distribution (By Main Category) - {selected_year_label}",
        labels={"category_main": "Category", "amount": "Expense (JPY)"}
    )
    fig_box_main.update_layout(
        xaxis_title="Category",
        yaxis_title="Expense (JPY)",
        height=500
    )

    tab_m1, tab_m2, tab_m3, tab_m4, tab_m5, tab_m6 = st.tabs(
        ["Pie Chart", "Horizontal Bar Chart", "Pareto Chart", "Monthly Portfolio", "Weekly Portfolio", "Box Plot"]
    )
    with tab_m1:
        st.plotly_chart(fig_pie_main, use_container_width=True)
    with tab_m2:
        st.plotly_chart(fig_bar_main, use_container_width=True)
    with tab_m3:
        st.plotly_chart(fig, use_container_width=True)
    with tab_m4:
        st.plotly_chart(fig_stacked_area, use_container_width=True)
    with tab_m5:
        st.plotly_chart(fig_weekly_yearly_area, use_container_width=True)
    with tab_m6:
        st.plotly_chart(fig_box_main, use_container_width=True)

    selected_category: str = st.selectbox(
        "Select a main category to view breakdown", summary["category_main"].to_list()
    )

    sub_data = expenses_year.filter(pl.col("category_main") == selected_category)
    sub_summary = (
        sub_data.group_by("category_sub")
        .agg(pl.col("amount").abs().sum().alias("amount"))
        .sort("amount", descending=True)
    )

    # サブカテゴリごとの割合を計算
    total_sub_amount = sub_summary["amount"].sum()
    sub_summary = sub_summary.with_columns(
        (pl.col("amount") / total_sub_amount * 100).alias("percentage")
    )

    if len(sub_summary) > 0:
        col1, col2 = st.columns(2)

        with col1:
            fig_pie = go.Figure()
            fig_pie.add_trace(
                go.Pie(
                    labels=sub_summary["category_sub"],
                    values=sub_summary["amount"],
                    hole=0.4,
                )
            )
            fig_pie.update_layout(
                title_text=f"{selected_category} Breakdown - {selected_year_label}"
            )

        with col2:
            fig_bar = go.Figure()
            fig_bar.add_trace(
                go.Bar(
                    x=sub_summary["amount"],
                    y=sub_summary["category_sub"],
                    orientation="h",
                    text=[f"{p:.1f}%" for p in sub_summary["percentage"]],
                    textposition="outside",
                )
            )
            fig_bar.update_layout(
                title=f"{selected_category} Subcategory Expenses - {selected_year_label}",
                xaxis_title="Expense (JPY)",
                yaxis_title="",
            )

        # パレート図用に累積パーセンテージを計算
        sub_summary = sub_summary.with_columns(
            pl.col("percentage").cum_sum().alias("cumulative_percentage")
        )

        fig_pareto = go.Figure()
        fig_pareto.add_bar(
            x=sub_summary["category_sub"], y=sub_summary["amount"], name="Expense"
        )
        fig_pareto.add_trace(
            go.Scatter(
                x=sub_summary["category_sub"],
                y=sub_summary["cumulative_percentage"],
                mode="lines+markers",
                name="Cumulative %",
                yaxis="y2",
                line=dict(color="orange", width=2),
            )
        )
        fig_pareto.update_layout(
            yaxis=dict(title="Expense (JPY)"),
            yaxis2=dict(
                title="Cumulative %",
                overlaying="y",
                side="right",
                type="linear",
                tickmode="array",
                tickvals=[0, 20, 40, 60, 80, 100],
                ticktext=["0%", "20%", "40%", "60%", "80%", "100%"],
                showgrid=False,
                zeroline=False,
                showline=False,
            ),
            title=f"{selected_category} Subcategory Pareto Chart",
            height=400,
        )
        fig_pareto.add_shape(
            type="line",
            x0=-0.5,
            x1=len(sub_summary["category_sub"]) - 0.5,
            y0=80,
            y1=80,
            xref="x",
            yref="y2",
            line=dict(color="red", width=2, dash="dash"),
        )

        # サブカテゴリの月次積み上げエリアチャート
        sub_monthly_portfolio = (
            sub_data
            .group_by(["month", "category_sub"])
            .agg(pl.col("amount").abs().sum())
        )

        # 日付順にソート
        sub_monthly_portfolio = sub_monthly_portfolio.with_columns(
            pl.col("month").str.strptime(pl.Date, "%Y-%m").alias("month_date")
        ).sort("month_date")

        fig_sub_monthly_area = px.area(
            sub_monthly_portfolio,
            x="month",
            y="amount",
            color="category_sub",
            title=f"{selected_category} Monthly Subcategory Portfolio - {selected_year_label}",
            labels={"amount": "Expense (JPY)", "month": "Month", "category_sub": "Subcategory"},
        )

        # サブカテゴリの週次積み上げエリアチャート
        sub_weekly_portfolio = (
            sub_data
            .with_columns(
                pl.col("date").dt.truncate("1w").alias("week_date")
            )
            .group_by(["week_date", "category_sub"])
            .agg(pl.col("amount").abs().sum())
            .sort("week_date")
        )

        fig_sub_weekly_area = px.area(
            sub_weekly_portfolio,
            x="week_date",
            y="amount",
            color="category_sub",
            title=f"{selected_category} Weekly Subcategory Portfolio - {selected_year_label}",
            labels={"amount": "Expense (JPY)", "week_date": "Week", "category_sub": "Subcategory"},
        )

        # 中項目の箱ひげ図
        sub_data_for_box = sub_data.with_columns(pl.col("amount").abs().alias("amount"))

        fig_box_sub = px.box(
            sub_data_for_box,
            x="category_sub",
            y="amount",
            title=f"{selected_category} Subcategory Distribution - {selected_year_label}",
            labels={"category_sub": "Subcategory", "amount": "Expense (JPY)"}
        )
        fig_box_sub.update_layout(
            xaxis_title="Subcategory",
            yaxis_title="Expense (JPY)",
            height=400
        )

        tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs(
            ["Pie Chart", "Bar Chart", "Pareto Chart", "Monthly Portfolio", "Weekly Portfolio", "Box Plot"]
        )

        with tab1:
            st.plotly_chart(fig_pie, use_container_width=True)
        with tab2:
            st.plotly_chart(fig_bar, use_container_width=True)
        with tab3:
            st.plotly_chart(fig_pareto, use_container_width=True)
        with tab4:
            st.plotly_chart(fig_sub_monthly_area, use_container_width=True)
        with tab5:
            st.plotly_chart(fig_sub_weekly_area, use_container_width=True)
        with tab6:
            st.plotly_chart(fig_box_sub, use_container_width=True)

        with st.container():
            detail_df = expenses_year.filter(pl.col("category_main") == selected_category)
            category_sub_options = ["All"] + sorted(
                detail_df.select("category_sub").filter(pl.col("category_sub").is_not_null()).unique().to_series().to_list()
            )
            selected_sub: str = st.selectbox(
                "Select subcategory", category_sub_options
            )
            if selected_sub != "All":
                detail_df = detail_df.filter(pl.col("category_sub") == selected_sub)

            detail_df = detail_df.select(
                "date", "description", "amount", "category_main", "category_sub", "memo"
            ).sort("date")

            st.markdown("#### Transaction Details")
            st.data_editor(detail_df, use_container_width=True, height=300)

            detail_df_desc = detail_df.with_columns(pl.col("amount").abs().alias("amount"))

            fig_box_desc = px.box(
                detail_df_desc,
                x="description",
                y="amount",
                title=f"{selected_category} Description Distribution - {selected_year_label}",
                labels={"description": "Description", "amount": "Expense (JPY)"}
            )
            fig_box_desc.update_layout(
                xaxis_title="Description",
                yaxis_title="Expense (JPY)",
                height=300
            )
            st.plotly_chart(fig_box_desc, use_container_width=True)
    else:
        st.info("No subcategory data found.")
