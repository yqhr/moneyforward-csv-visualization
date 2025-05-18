import streamlit as st
import plotly.graph_objects as go
import plotly.express as px
from prepare_data import prepare_and_save_data, convert_mf_csv_to_duckdb
import duckdb
import pandas as pd
from typing import List, Tuple, Optional
from streamlit.runtime.uploaded_file_manager import UploadedFile

st.set_page_config(page_title="Expense Analysis", layout="wide")

st.title("Expense Analysis")

def _load_csvs(files: List[UploadedFile]) -> duckdb.DuckDBPyConnection:
    con: duckdb.DuckDBPyConnection = convert_mf_csv_to_duckdb(files)
    return con

@st.cache_data(show_spinner=True)
def load_and_processed_data(files: List[UploadedFile]) -> Tuple[pd.DataFrame, pd.DataFrame]:
    con: duckdb.DuckDBPyConnection = _load_csvs(files)
    con2: duckdb.DuckDBPyConnection = prepare_and_save_data(con)
    con.close()

    expenses: pd.DataFrame = con2.execute(
        """
        SELECT
            *,
            strftime(date, '%Y-%m') AS month,
            strftime(date, '%Y') AS year
        FROM expenses;
        """
    ).df()

    refunds: pd.DataFrame = con2.execute(
        """
        SELECT
            *,
            strftime(date, '%Y-%m') AS month,
            strftime(date, '%Y') AS year
        FROM refunds;
        """
    ).df()

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

expenses: pd.DataFrame
refunds: pd.DataFrame
expenses, refunds = load_and_processed_data(files)

# 表示タイプの選択
display_type: str = st.selectbox("Select display type", ["Monthly", "Yearly"])

# 月別表示部分を修正
if display_type == "Monthly":
    month_options: List[str] = sorted(expenses["month"].dropna().unique())
    selected_months: List[str] = st.multiselect(
        "Select months", month_options, default=[month_options[-1]]
    )
    if len(selected_months) == 0:
        st.stop()

    expenses_month: pd.DataFrame = expenses[expenses["month"].isin(selected_months)]
    refunds_month: pd.DataFrame = refunds[refunds["month"].isin(selected_months)]

    selected_month_label: str = (
        ", ".join(selected_months)
        if len(selected_months) <= 3
        else f"{selected_months[0]} and others"
    )

    # カテゴリー別の純支出を計算
    summary: pd.DataFrame = (
        expenses_month.groupby("category_main")["amount"]
        .sum()
        .abs()
        .to_frame(name="expense")
    )
    summary["refund"] = refunds_month.groupby("category_main")["amount"].sum()
    summary.fillna(0, inplace=True)
    summary = (
        summary[summary["expense"] > 0]
        .sort_values("expense", ascending=False)
        .reset_index()
    )

    # パーセンテージと累積値を計算
    summary["percentage"] = summary["expense"] / summary["expense"].sum() * 100
    summary["cumulative_percentage"] = summary["percentage"].cumsum()

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
            text=summary["percentage"].map("{:.1f}%".format),
            textposition="outside",
        )
    )
    fig_bar_main.update_layout(
        title=f"Main Category Expenses - {selected_month_label}",
        xaxis_title="Net expense (JPY)",
        yaxis_title="",
    )

    # 時系列チャート
    ts_main: pd.DataFrame = (
        expenses_month[expenses_month["category_main"] == summary["category_main"].iloc[0]]
        .groupby("date")["amount"]
        .sum()
        .abs()
        .reset_index(name="expense")
    )
    fig_ts_main = px.line(
        ts_main.sort_values("date"),
        x="date",
        y="expense",
        markers=True,
        title=f"Total Expense Time Series - {selected_month_label}",
    )

    # 月次支出の積み上げエリアチャート
    monthly_portfolio: pd.DataFrame = (
        expenses_month
        .groupby(["date", "category_main"])["amount"]
        .sum()
        .abs()
        .reset_index()
    )

    # 正しく表示するために日付でソート
    monthly_portfolio = monthly_portfolio.sort_values("date")

    fig_stacked_area = px.area(
        monthly_portfolio,
        x="date",
        y="amount",
        color="category_main",
        title=f"Monthly Expense Portfolio - {selected_month_label}",
        labels={"amount": "Expense (JPY)", "date": "Date", "category_main": "Category"},
    )

    # 週次の積み上げエリアチャートを追加
    weekly_portfolio: pd.DataFrame = (
        expenses_month
        .assign(week=lambda x: pd.to_datetime(x["date"]).dt.strftime("%Y-%U"))
        .groupby(["week", "category_main"])["amount"]
        .sum()
        .abs()
        .reset_index()
    )

    # 週番号を実際の日付（週の初日）に変換
    weekly_portfolio["week_date"] = pd.to_datetime(
        weekly_portfolio["week"].apply(
            lambda x: f"{x.split('-')[0]}-W{x.split('-')[1]}-1"
        ), format="%Y-W%W-%w"
    )
    weekly_portfolio = weekly_portfolio.sort_values("week_date")

    fig_weekly_area = px.area(
        weekly_portfolio,
        x="week_date",
        y="amount",
        color="category_main",
        title=f"Weekly Expense Portfolio - {selected_month_label}",
        labels={"amount": "Expense (JPY)", "week_date": "Week", "category_main": "Category"},
    )

    # タブを更新
    tab_m1, tab_m2, tab_m3, tab_m4, tab_m5, tab_m6 = st.tabs(
        ["Pie Chart", "Horizontal Bar Chart", "Pareto Chart", "Time Series Chart",
         "Monthly Portfolio", "Weekly Portfolio"]
    )
    with tab_m1:
        st.plotly_chart(fig_pie_main, use_container_width=True)
    with tab_m2:
        st.plotly_chart(fig_bar_main, use_container_width=True)
    with tab_m3:
        st.plotly_chart(fig, use_container_width=True)
    with tab_m4:
        st.plotly_chart(fig_ts_main, use_container_width=True)
    with tab_m5:
        st.plotly_chart(fig_stacked_area, use_container_width=True)
    with tab_m6:
        st.plotly_chart(fig_weekly_area, use_container_width=True)

    # メインカテゴリの選択とサブカテゴリの内訳（円グラフ + 水平棒グラフ）
    selected_category: str = st.selectbox(
        "Select a main category to view breakdown", summary["category_main"]
    )

    sub_data: pd.DataFrame = expenses_month[expenses_month["category_main"] == selected_category]
    sub_summary: pd.DataFrame = sub_data.groupby("category_sub")["amount"].sum().abs().reset_index()
    sub_summary["percentage"] = (
        sub_summary["amount"] / sub_summary["amount"].sum() * 100
    )
    sub_summary = sub_summary.sort_values("amount", ascending=False)

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
                    text=sub_summary["percentage"].map("{:.1f}%".format),
                    textposition="outside",
                )
            )
            fig_bar.update_layout(
                title=f"{selected_category} Subcategory Expenses - {selected_month_label}",
                xaxis_title="Expense (JPY)",
                yaxis_title="",
            )

        fig_pareto = go.Figure()
        fig_pareto.add_bar(
            x=sub_summary["category_sub"], y=sub_summary["amount"], name="Expense"
        )
        fig_pareto.add_trace(
            go.Scatter(
                x=sub_summary["category_sub"],
                y=sub_summary["percentage"].cumsum(),
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

        # 時系列チャート
        ts_summary: pd.DataFrame = sub_data.copy()
        ts_summary["amount"] = ts_summary["amount"].abs()
        ts_summary = ts_summary.groupby("date")["amount"].sum().reset_index()
        fig_ts = px.line(
            ts_summary,
            x="date",
            y="amount",
            markers=True,
            title=f"{selected_category} Expense Time Series - {selected_month_label}",
        )

        # サブカテゴリの月次積み上げエリアチャート
        sub_monthly_portfolio: pd.DataFrame = (
            sub_data
            .groupby(["month", "category_sub"])["amount"]
            .sum()
            .abs()
            .reset_index()
        )

        # 日付順にソート
        sub_monthly_portfolio["month_date"] = pd.to_datetime(sub_monthly_portfolio["month"] + "-01")
        sub_monthly_portfolio = sub_monthly_portfolio.sort_values("month_date")

        fig_sub_monthly_area = px.area(
            sub_monthly_portfolio,
            x="month",
            y="amount",
            color="category_sub",
            title=f"{selected_category} Monthly Subcategory Portfolio - {selected_month_label}",
            labels={"amount": "Expense (JPY)", "month": "Month", "category_sub": "Subcategory"},
        )

        # サブカテゴリの週次積み上げエリアチャート - これは既存のコードを再利用
        sub_weekly_portfolio: pd.DataFrame = (
            sub_data
            .assign(week=lambda x: pd.to_datetime(x["date"]).dt.strftime("%Y-%U"))
            .groupby(["week", "category_sub"])["amount"]
            .sum()
            .abs()
            .reset_index()
        )

        # 週番号を実際の日付に変換
        sub_weekly_portfolio["week_date"] = pd.to_datetime(
            sub_weekly_portfolio["week"].apply(
                lambda x: f"{x.split('-')[0]}-W{x.split('-')[1]}-1"
            ), format="%Y-W%W-%w"
        )
        sub_weekly_portfolio = sub_weekly_portfolio.sort_values("week_date")

        fig_sub_weekly_area = px.area(
            sub_weekly_portfolio,
            x="week_date",
            y="amount",
            color="category_sub",
            title=f"{selected_category} Weekly Subcategory Portfolio - {selected_month_label}",
            labels={"amount": "Expense (JPY)", "week_date": "Week", "category_sub": "Subcategory"},
        )

        # 中項目のタブ名を更新（"Daily Portfolio"→"Monthly Portfolio"）
        tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs(
            ["Pie Chart", "Bar Chart", "Pareto Chart", "Time Series Chart",
             "Monthly Portfolio", "Weekly Portfolio"]
        )

        with tab1:
            st.plotly_chart(fig_pie, use_container_width=True)
        with tab2:
            st.plotly_chart(fig_bar, use_container_width=True)
        with tab3:
            st.plotly_chart(fig_pareto, use_container_width=True)
        with tab4:
            st.plotly_chart(fig_ts, use_container_width=True)
        with tab5:
            st.plotly_chart(fig_sub_monthly_area, use_container_width=True)
        with tab6:
            st.plotly_chart(fig_sub_weekly_area, use_container_width=True)

        with st.container():
            detail_df: pd.DataFrame = expenses_month[
                expenses_month["category_main"] == selected_category
            ]
            category_sub_options: List[str] = ["All"] + sorted(
                detail_df["category_sub"].dropna().unique()
            )
            selected_sub: str = st.selectbox(
                "Select subcategory", category_sub_options
            )
            if selected_sub != "All":
                detail_df = detail_df[detail_df["category_sub"] == selected_sub]
            detail_df = detail_df[
                [
                    "date",
                    "description",
                    "amount",
                    "category_main",
                    "category_sub",
                    "memo",
                ]
            ]
            detail_df = detail_df.sort_values("date")
            st.markdown("#### Transaction Details")
            st.data_editor(detail_df, use_container_width=True, height=300)
    else:
        st.info("No subcategory data found.")

if display_type == "Yearly":
    year_options: List[str] = sorted(expenses["year"].dropna().unique())
    year_options_int: List[int] = [int(y) for y in year_options]

    selected_years: List[int] = st.multiselect(
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

    # DataFrameの型を明示的に定義
    expenses_year: pd.DataFrame = expenses[
        expenses["year"].astype(int).isin(selected_years)
    ]
    summary: pd.DataFrame = (
        expenses_year.groupby("category_main")["amount"]
        .sum()
        .abs()
        .to_frame(name="expense")
    )
    summary.fillna(0, inplace=True)
    summary = (
        summary[summary["expense"] > 0]
        .sort_values("expense", ascending=False)
        .reset_index()
    )

    summary["percentage"] = summary["expense"] / summary["expense"].sum() * 100
    summary["cumulative_percentage"] = summary["percentage"].cumsum()

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
            text=summary["percentage"].map("{:.1f}%".format),
            textposition="outside",
        )
    )
    fig_bar_main.update_layout(
        title=f"Main Category Expenses - {selected_year_label}",
        xaxis_title="Net expense (JPY)",
        yaxis_title="",
    )

    # 時系列チャート
    ts_main: pd.DataFrame = (
        expenses_year[expenses_year["category_main"] == summary["category_main"].iloc[0]]
        .groupby("date")["amount"]
        .sum()
        .abs()
        .reset_index(name="expense")
    )
    fig_ts_main = px.line(
        ts_main.sort_values("date"),
        x="date",
        y="expense",
        markers=True,
        title=f"Total Expense Time Series - {selected_year_label}",
    )

    # 月別の年間支出の積み上げエリアチャート
    yearly_portfolio: pd.DataFrame = (
        expenses_year
        .groupby(["month", "category_main"])["amount"]
        .sum()
        .abs()
        .reset_index()
    )

    # 日付順にソートしてグラフが正しく表示されるようにする
    yearly_portfolio["month_date"] = pd.to_datetime(yearly_portfolio["month"] + "-01")
    yearly_portfolio = yearly_portfolio.sort_values("month_date")

    fig_stacked_area = px.area(
        yearly_portfolio,
        x="month",
        y="amount",
        color="category_main",
        title=f"Monthly Expense Portfolio - {selected_year_label}",
        labels={"amount": "Expense (JPY)", "month": "Month", "category_main": "Category"},
    )

    # 週ごとの積み上げ面グラフを追加
    weekly_yearly_portfolio: pd.DataFrame = (
        expenses_year
        .assign(week=lambda x: pd.to_datetime(x["date"]).dt.strftime("%Y-%U"))
        .groupby(["week", "category_main"])["amount"]
        .sum()
        .abs()
        .reset_index()
    )

    # 週番号を実際の日付に変換
    weekly_yearly_portfolio["week_date"] = pd.to_datetime(
        weekly_yearly_portfolio["week"].apply(
            lambda x: f"{x.split('-')[0]}-W{x.split('-')[1]}-1"
        ), format="%Y-W%W-%w"
    )
    weekly_yearly_portfolio = weekly_yearly_portfolio.sort_values("week_date")

    fig_weekly_yearly_area = px.area(
        weekly_yearly_portfolio,
        x="week",
        y="amount",
        color="category_main",
        title=f"Weekly Expense Portfolio - {selected_year_label}",
        labels={"amount": "Expense (JPY)", "week": "Week", "category_main": "Category"},
    )

    # ポートフォリオチャート用の新しいタブを作成
    tab_m1, tab_m2, tab_m3, tab_m4, tab_m5, tab_m6 = st.tabs(
        ["Pie Chart", "Horizontal Bar Chart", "Pareto Chart", "Time Series Chart",
         "Monthly Portfolio", "Weekly Portfolio"]
    )
    with tab_m1:
        st.plotly_chart(fig_pie_main, use_container_width=True)
    with tab_m2:
        st.plotly_chart(fig_bar_main, use_container_width=True)
    with tab_m3:
        st.plotly_chart(fig, use_container_width=True)
    with tab_m4:
        st.plotly_chart(fig_ts_main, use_container_width=True)
    with tab_m5:
        st.plotly_chart(fig_stacked_area, use_container_width=True)
    with tab_m6:
        st.plotly_chart(fig_weekly_yearly_area, use_container_width=True)

    selected_category: str = st.selectbox(
        "Select a main category to view breakdown", summary["category_main"]
    )

    sub_data: pd.DataFrame = expenses_year[expenses_year["category_main"] == selected_category]
    sub_summary: pd.DataFrame = sub_data.groupby("category_sub")["amount"].sum().abs().reset_index()
    sub_summary["percentage"] = (
        sub_summary["amount"] / sub_summary["amount"].sum() * 100
    )
    sub_summary = sub_summary.sort_values("amount", ascending=False)

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
                    text=sub_summary["percentage"].map("{:.1f}%".format),
                    textposition="outside",
                )
            )
            fig_bar.update_layout(
                title=f"{selected_category} Subcategory Expenses - {selected_year_label}",
                xaxis_title="Expense (JPY)",
                yaxis_title="",
            )

        fig_pareto = go.Figure()
        fig_pareto.add_bar(
            x=sub_summary["category_sub"], y=sub_summary["amount"], name="Expense"
        )
        fig_pareto.add_trace(
            go.Scatter(
                x=sub_summary["category_sub"],
                y=sub_summary["percentage"].cumsum(),
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

        # 年別表示の中項目表示部分を修正
        # 時系列チャート
        ts_summary: pd.DataFrame = sub_data.copy()
        ts_summary["amount"] = ts_summary["amount"].abs()
        ts_summary = ts_summary.groupby("date")["amount"].sum().reset_index()
        fig_ts = px.line(
            ts_summary,
            x="date",
            y="amount",
            markers=True,
            title=f"{selected_category} Expense Time Series - {selected_year_label}",
        )

        # サブカテゴリの月次積み上げエリアチャート
        sub_monthly_portfolio: pd.DataFrame = (
            sub_data
            .groupby(["month", "category_sub"])["amount"]
            .sum()
            .abs()
            .reset_index()
        )

        # 日付順にソート
        sub_monthly_portfolio["month_date"] = pd.to_datetime(sub_monthly_portfolio["month"] + "-01")
        sub_monthly_portfolio = sub_monthly_portfolio.sort_values("month_date")

        fig_sub_monthly_area = px.area(
            sub_monthly_portfolio,
            x="month",
            y="amount",
            color="category_sub",
            title=f"{selected_category} Monthly Subcategory Portfolio - {selected_year_label}",
            labels={"amount": "Expense (JPY)", "month": "Month", "category_sub": "Subcategory"},
        )

        # サブカテゴリの週次積み上げエリアチャート
        sub_weekly_portfolio: pd.DataFrame = (
            sub_data
            .assign(week=lambda x: pd.to_datetime(x["date"]).dt.strftime("%Y-%U"))
            .groupby(["week", "category_sub"])["amount"]
            .sum()
            .abs()
            .reset_index()
        )

        # 週番号を実際の日付に変換
        sub_weekly_portfolio["week_date"] = pd.to_datetime(
            sub_weekly_portfolio["week"].apply(
                lambda x: f"{x.split('-')[0]}-W{x.split('-')[1]}-1"
            ), format="%Y-W%W-%w"
        )
        sub_weekly_portfolio = sub_weekly_portfolio.sort_values("week_date")

        fig_sub_weekly_area = px.area(
            sub_weekly_portfolio,
            x="week_date",
            y="amount",
            color="category_sub",
            title=f"{selected_category} Weekly Subcategory Portfolio - {selected_year_label}",
            labels={"amount": "Expense (JPY)", "week_date": "Week", "category_sub": "Subcategory"},
        )

        # タブを更新
        tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs(
            ["Pie Chart", "Bar Chart", "Pareto Chart", "Time Series Chart",
             "Monthly Portfolio", "Weekly Portfolio"]
        )

        with tab1:
            st.plotly_chart(fig_pie, use_container_width=True)
        with tab2:
            st.plotly_chart(fig_bar, use_container_width=True)
        with tab3:
            st.plotly_chart(fig_pareto, use_container_width=True)
        with tab4:
            st.plotly_chart(fig_ts, use_container_width=True)
        with tab5:
            st.plotly_chart(fig_sub_monthly_area, use_container_width=True)
        with tab6:
            st.plotly_chart(fig_sub_weekly_area, use_container_width=True)

        with st.container():
            detail_df: pd.DataFrame = expenses_year[
                expenses_year["category_main"] == selected_category
            ]
            category_sub_options: List[str] = ["All"] + sorted(
                detail_df["category_sub"].dropna().unique()
            )
            selected_sub: str = st.selectbox(
                "Select subcategory", category_sub_options
            )
            if selected_sub != "All":
                detail_df = detail_df[detail_df["category_sub"] == selected_sub]
            detail_df = detail_df[
                [
                    "date",
                    "description",
                    "amount",
                    "category_main",
                    "category_sub",
                    "memo",
                ]
            ]
            detail_df = detail_df.sort_values("date")
            st.markdown("#### Transaction Details")
            st.data_editor(detail_df, use_container_width=True, height=300)
    else:
        st.info("No subcategory data found.")
