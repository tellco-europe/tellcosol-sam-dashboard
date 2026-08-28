from __future__ import annotations

from pathlib import Path
from typing import Iterable

import pandas as pd
import plotly.express as px
import streamlit as st


# ------------------------------------------------------------
# PAGE CONFIGURATION
# ------------------------------------------------------------

st.set_page_config(
    page_title="TellCoSOL Opportunities",
    page_icon="☀️",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ------------------------------------------------------------
# PATHS
# ------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent
DATA_DIR = PROJECT_ROOT / "data"

OPPORTUNITIES_FILE = DATA_DIR / "sam_opportunities_current.parquet"
SUMMARY_FILE = DATA_DIR / "dashboard_summary.parquet"
AGENCY_FILE = DATA_DIR / "opportunities_by_agency.parquet"
TYPE_FILE = DATA_DIR / "opportunities_by_type.parquet"
DEADLINE_FILE = DATA_DIR / "deadline_distribution.parquet"
SOURCE_HEALTH_FILE = DATA_DIR / "source_health.parquet"
RUN_STATUS_FILE = DATA_DIR / "sam_run_status.json"


# ------------------------------------------------------------
# DISPLAY SETTINGS
# ------------------------------------------------------------

TELLCO_RED = "#e30613"

DEADLINE_ORDER = [
    "<= 14 days",
    "15-30 days",
    "31-60 days",
    "60+ days",
    "No deadline",
    "Past deadline",
]


# ------------------------------------------------------------
# CUSTOM STYLING
# ------------------------------------------------------------

st.markdown(
    """
    <style>
        .block-container {
            padding-top: 3.75rem;
            padding-bottom: 2rem;
            max-width: 1500px;
        }

        [data-testid="stSidebar"] {
            border-right: 1px solid #e5e7eb;
        }

        .dashboard-title {
            font-size: 2.05rem;
            font-weight: 750;
            line-height: 1.2;
            margin-top: 0.35rem;
            margin-bottom: 0.25rem;
        }

        .dashboard-subtitle {
            color: #667085;
            font-size: 0.98rem;
            margin-bottom: 1.25rem;
        }

        div[data-testid="stMetric"] {
            background: white;
            border: 1px solid #e5e7eb;
            border-radius: 14px;
            padding: 1rem 1.1rem;
            min-height: 118px;
            box-shadow: 0 2px 8px rgba(16, 24, 40, 0.06);
        }

        .kpi-card {
            background: white;
            border: 1px solid #e5e7eb;
            border-radius: 14px;
            padding: 1rem 1.1rem;
            min-height: 124px;
            box-shadow: 0 2px 8px rgba(16, 24, 40, 0.06);
        }

        .kpi-top {
            display: flex;
            align-items: center;
            gap: 0.75rem;
            margin-bottom: 0.5rem;
        }

        .kpi-icon {
            width: 42px;
            height: 42px;
            border-radius: 50%;
            background: #fde8ea;
            color: #e30613;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 1.25rem;
            font-weight: 700;
            flex: 0 0 auto;
        }

        .kpi-label {
            color: #475467;
            font-size: 0.9rem;
            font-weight: 600;
        }

        .kpi-value {
            font-size: 2rem;
            line-height: 1;
            font-weight: 800;
            color: #101828;
            margin-left: 3.4rem;
        }

        div[data-testid="stMetricLabel"] {
            font-size: 0.9rem;
            color: #667085;
        }

        div[data-testid="stMetricValue"] {
            font-size: 2rem;
            font-weight: 750;
        }

        .section-heading {
            font-size: 1.15rem;
            font-weight: 700;
            margin-top: 0.25rem;
            margin-bottom: 0.35rem;
        }

        .method-note {
            color: #667085;
            font-size: 0.84rem;
        }

        [data-testid="stDataFrame"] {
            border: 1px solid #dfe3e8;
            border-radius: 10px;
            overflow: hidden;
            background: white;
        }

        [data-testid="stDataFrame"] [role="columnheader"] {
            background: #f8fafc;
            color: #344054;
            font-weight: 700;
            border-right: 1px solid #dfe3e8;
            border-bottom: 1px solid #cfd6dd;
        }

        [data-testid="stDataFrame"] [role="gridcell"] {
            border-right: 1px solid #e2e8f0;
            border-bottom: 1px solid #e2e8f0;
        }

        .status-success {
            background: #ecfdf3;
            border: 1px solid #abefc6;
            border-radius: 8px;
            padding: 0.7rem 0.85rem;
            color: #067647;
        }

        .status-warning {
            background: #fffaeb;
            border: 1px solid #fedf89;
            border-radius: 8px;
            padding: 0.7rem 0.85rem;
            color: #b54708;
        }
    </style>
    """,
    unsafe_allow_html=True,
)


# ------------------------------------------------------------
# DATA LOADING
# ------------------------------------------------------------

def require_file(path: Path) -> None:
    """Stop the app with a helpful message when a required file is missing."""

    if not path.exists():
        st.error(
            f"Required data file was not found: `{path.relative_to(PROJECT_ROOT)}`"
        )
        st.info(
            "Run `python scripts/collect_sam_data.py` and commit the generated "
            "dashboard data files before opening the deployed app."
        )
        st.stop()


@st.cache_data(show_spinner=False)
def read_parquet(path: str) -> pd.DataFrame:
    """Load a Parquet file using Streamlit's data cache."""

    return pd.read_parquet(path)


@st.cache_data(show_spinner=False)
def load_dashboard_data() -> tuple[
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
]:
    """Load all datasets required by the dashboard."""

    required_files = [
        OPPORTUNITIES_FILE,
        SUMMARY_FILE,
        AGENCY_FILE,
        TYPE_FILE,
        DEADLINE_FILE,
    ]

    for path in required_files:
        require_file(path)

    opportunities = read_parquet(str(OPPORTUNITIES_FILE))
    summary = read_parquet(str(SUMMARY_FILE))
    agency = read_parquet(str(AGENCY_FILE))
    notice_type = read_parquet(str(TYPE_FILE))
    deadlines = read_parquet(str(DEADLINE_FILE))

    source_health = (
        read_parquet(str(SOURCE_HEALTH_FILE))
        if SOURCE_HEALTH_FILE.exists()
        else pd.DataFrame()
    )

    return (
        opportunities,
        summary,
        agency,
        notice_type,
        deadlines,
        source_health,
    )


def ensure_columns(frame: pd.DataFrame, columns: Iterable[str]) -> pd.DataFrame:
    """Add any optional columns that are missing from the dataset."""

    result = frame.copy()

    for column in columns:
        if column not in result.columns:
            result[column] = pd.NA

    return result


def prepare_opportunities(frame: pd.DataFrame) -> pd.DataFrame:
    """Standardize dashboard data types and display fields."""

    required_columns = [
        "title",
        "agency",
        "opportunity_type",
        "posted_date",
        "response_deadline",
        "days_left",
        "deadline_band",
        "set_aside",
        "place_of_performance",
        "solicitation_number",
        "matched_keywords",
        "sam_gov_link",
        "naics_code",
        "primary_contact_name",
        "primary_contact_email",
        "description",
    ]

    df = ensure_columns(frame, required_columns)

    for column in ["posted_date", "response_deadline"]:
        df[column] = pd.to_datetime(
            df[column],
            errors="coerce",
            utc=True,
        )

    df["days_left"] = pd.to_numeric(
        df["days_left"],
        errors="coerce",
    ).astype("Int64")

    text_defaults = {
        "title": "Title not provided",
        "agency": "Agency not provided",
        "opportunity_type": "Type not provided",
        "deadline_band": "No deadline",
        "set_aside": "Not provided",
        "place_of_performance": "Not provided",
        "matched_keywords": "Not provided",
    }

    for column, default in text_defaults.items():
        df[column] = df[column].fillna(default).astype(str)

    df["posted_date_display"] = df["posted_date"].dt.strftime("%b %d, %Y")
    df["deadline_display"] = df["response_deadline"].dt.strftime("%b %d, %Y")

    df["posted_date_display"] = df["posted_date_display"].fillna("Not provided")
    df["deadline_display"] = df["deadline_display"].fillna("No deadline")

    df["days_left_display"] = df["days_left"].map(format_days_left)

    return df


def format_days_left(value: object) -> str:
    """Return a readable deadline label."""

    if value is None or pd.isna(value):
        return "No deadline"

    days = int(value)

    if days == 0:
        return "Due today"

    if days == 1:
        return "1 day"

    return f"{days} days"


def safe_scalar(
    summary: pd.DataFrame,
    column: str,
    fallback: int | str = 0,
) -> int | str:
    """Return the first summary value without failing on missing columns."""

    if summary.empty or column not in summary.columns:
        return fallback

    value = summary.iloc[0][column]

    if value is None or pd.isna(value):
        return fallback

    return value


def top_n_with_other(
    frame: pd.DataFrame,
    category_column: str,
    count_column: str,
    top_n: int = 8,
) -> pd.DataFrame:
    """Keep the largest categories and combine the remainder as Other."""

    if frame.empty:
        return frame.copy()

    ordered = frame.sort_values(
        count_column,
        ascending=False,
    ).reset_index(drop=True)

    if len(ordered) <= top_n:
        return ordered

    top = ordered.head(top_n).copy()
    remainder = int(
        ordered.iloc[top_n:][count_column].sum()
    )

    other = pd.DataFrame(
        {
            category_column: ["Other"],
            count_column: [remainder],
        }
    )

    return pd.concat(
        [top, other],
        ignore_index=True,
    )


def render_kpi_card(icon: str, label: str, value: int) -> None:
    """Render a KPI card styled to match the approved mockup."""

    st.markdown(
        f"""
        <div class="kpi-card">
            <div class="kpi-top">
                <div class="kpi-icon">{icon}</div>
                <div class="kpi-label">{label}</div>
            </div>
            <div class="kpi-value">{value:,}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


# ------------------------------------------------------------
# LOAD AND PREPARE DATA
# ------------------------------------------------------------

with st.spinner("Loading SAM.gov opportunity data..."):
    (
        opportunities_raw,
        summary_data,
        agency_summary_raw,
        type_summary_raw,
        deadline_summary_raw,
        source_health,
    ) = load_dashboard_data()

opportunities = prepare_opportunities(opportunities_raw)


# ------------------------------------------------------------
# SIDEBAR FILTERS
# ------------------------------------------------------------

st.sidebar.title("Dashboard Filters")
st.sidebar.caption("Filters apply to the KPI cards, charts, and detailed table.")

agency_options = sorted(
    opportunities["agency"].dropna().unique().tolist()
)

type_options = sorted(
    opportunities["opportunity_type"].dropna().unique().tolist()
)

set_aside_options = sorted(
    opportunities["set_aside"].dropna().unique().tolist()
)

deadline_options = [
    band
    for band in DEADLINE_ORDER
    if band in opportunities["deadline_band"].unique()
]

selected_agencies = st.sidebar.multiselect(
    "Agency",
    options=agency_options,
    default=agency_options,
)

selected_types = st.sidebar.multiselect(
    "Opportunity type",
    options=type_options,
    default=type_options,
)

selected_deadlines = st.sidebar.multiselect(
    "Deadline",
    options=deadline_options,
    default=deadline_options,
)

selected_set_asides = st.sidebar.multiselect(
    "Set-aside",
    options=set_aside_options,
    default=set_aside_options,
)

keyword_search = st.sidebar.text_input(
    "Search title or keyword",
    placeholder="Example: solar or microgrid",
)

filtered = opportunities[
    opportunities["agency"].isin(selected_agencies)
    & opportunities["opportunity_type"].isin(selected_types)
    & opportunities["deadline_band"].isin(selected_deadlines)
    & opportunities["set_aside"].isin(selected_set_asides)
].copy()

if keyword_search.strip():
    search_term = keyword_search.strip()

    match_title = filtered["title"].str.contains(
        search_term,
        case=False,
        na=False,
        regex=False,
    )

    match_keywords = filtered["matched_keywords"].str.contains(
        search_term,
        case=False,
        na=False,
        regex=False,
    )

    filtered = filtered[
        match_title | match_keywords
    ].copy()

if st.sidebar.button("Clear cached data"):
    st.cache_data.clear()
    st.rerun()

st.sidebar.markdown("---")
st.sidebar.caption(
    "Source: SAM.gov Opportunities API\n\n"
    "Search period: previous 90 days\n\n"
    "Keywords: 11 terms documented in the procurement and funding queue."
)


# ------------------------------------------------------------
# HEADER
# ------------------------------------------------------------

st.markdown(
    '<div class="dashboard-title">TellCoSOL Opportunities</div>',
    unsafe_allow_html=True,
)

st.markdown(
    (
        '<div class="dashboard-subtitle">'
        "Open SAM.gov opportunities identified from TellCoSOL's documented "
        "procurement keywords."
        "</div>"
    ),
    unsafe_allow_html=True,
)


# ------------------------------------------------------------
# KPI CARDS
# ------------------------------------------------------------

today_utc = pd.Timestamp.now(tz="UTC").normalize()
current_month_start = today_utc.replace(day=1)

total_open = len(filtered)

new_this_month = int(
    (
        filtered["posted_date"].notna()
        & filtered["posted_date"].between(
            current_month_start,
            today_utc + pd.Timedelta(days=1),
            inclusive="left",
        )
    ).sum()
)

closing_14_days = int(
    filtered["days_left"].between(
        0,
        14,
        inclusive="both",
    ).sum()
)

distinct_agencies = int(
    filtered["agency"].nunique()
)

metric_1, metric_2, metric_3, metric_4 = st.columns(4)

with metric_1:
    render_kpi_card("▤", "Open Opportunities", total_open)

with metric_2:
    render_kpi_card("✦", "New This Month", new_this_month)

with metric_3:
    render_kpi_card("◷", "Closing Within 14 Days", closing_14_days)

with metric_4:
    render_kpi_card("⌂", "Distinct Agencies", distinct_agencies)


# ------------------------------------------------------------
# SUMMARY CHARTS
# ------------------------------------------------------------

st.markdown("<div style=\"height:0.35rem\"></div>", unsafe_allow_html=True)
chart_col_1, chart_col_2, chart_col_3 = st.columns(3)

filtered_agency = (
    filtered.groupby(
        "agency",
        as_index=False,
    )
    .size()
    .rename(columns={"size": "opportunity_count"})
)

filtered_agency = top_n_with_other(
    filtered_agency,
    category_column="agency",
    count_column="opportunity_count",
    top_n=7,
)

with chart_col_1:
    st.markdown(
        '<div class="section-heading">Opportunities by Agency</div>',
        unsafe_allow_html=True,
    )

    if filtered_agency.empty:
        st.info("No agency data matches the selected filters.")
    else:
        agency_chart = px.bar(
            filtered_agency.sort_values(
                "opportunity_count",
                ascending=True,
            ),
            x="opportunity_count",
            y="agency",
            orientation="h",
            labels={
                "opportunity_count": "Opportunities",
                "agency": "",
            },
            text="opportunity_count",
        )

        agency_chart.update_traces(
            marker_color=TELLCO_RED,
            textposition="outside",
            cliponaxis=False,
        )

        agency_chart.update_layout(
            height=285,
            margin=dict(l=5, r=25, t=10, b=10),
            showlegend=False,
            xaxis_title="Opportunities",
            yaxis_title="",
        )

        st.plotly_chart(
            agency_chart,
            use_container_width=True,
            config={"displayModeBar": False},
        )



filtered_types = (
    filtered.groupby(
        "opportunity_type",
        as_index=False,
    )
    .size()
    .rename(columns={"size": "opportunity_count"})
)

with chart_col_2:
    st.markdown(
        '<div class="section-heading">Opportunities by Type</div>',
        unsafe_allow_html=True,
    )

    if filtered_types.empty:
        st.info("No opportunity-type data matches the selected filters.")
    else:
        type_chart = px.pie(
            filtered_types,
            names="opportunity_type",
            values="opportunity_count",
            hole=0.58,
        )

        type_chart.update_traces(
            textposition="inside",
            textinfo="percent",
            hovertemplate=(
                "<b>%{label}</b><br>"
                "Opportunities: %{value}<br>"
                "Share: %{percent}"
                "<extra></extra>"
            ),
        )

        type_chart.update_layout(
            height=285,
            margin=dict(l=5, r=5, t=10, b=10),
            legend_title_text="",
            annotations=[
                dict(
                    text=f"<b>{len(filtered)}</b><br>Total",
                    x=0.5,
                    y=0.5,
                    font_size=17,
                    showarrow=False,
                )
            ],
            legend=dict(
                orientation="h",
                yanchor="top",
                y=-0.05,
                xanchor="center",
                x=0.5,
            ),
        )

        st.plotly_chart(
            type_chart,
            use_container_width=True,
            config={"displayModeBar": False},
        )



# ------------------------------------------------------------
# DEADLINE DISTRIBUTION
# ------------------------------------------------------------

filtered_deadlines = (
    filtered.groupby(
        "deadline_band",
        as_index=False,
    )
    .size()
    .rename(columns={"size": "opportunity_count"})
)

filtered_deadlines["deadline_band"] = pd.Categorical(
    filtered_deadlines["deadline_band"],
    categories=DEADLINE_ORDER,
    ordered=True,
)

filtered_deadlines = filtered_deadlines.sort_values(
    "deadline_band"
)

with chart_col_3:
    st.markdown(
        '<div class="section-heading">Deadline Distribution</div>',
        unsafe_allow_html=True,
    )

    if filtered_deadlines.empty:
        st.info("No deadline data matches the selected filters.")
    else:
        deadline_chart = px.bar(
            filtered_deadlines,
            x="deadline_band",
            y="opportunity_count",
            labels={
                "deadline_band": "",
                "opportunity_count": "Opportunities",
            },
            text="opportunity_count",
        )
    
        deadline_chart.update_traces(
            marker_color=TELLCO_RED,
            textposition="outside",
            cliponaxis=False,
        )
    
        deadline_chart.update_layout(
            height=285,
            margin=dict(l=5, r=10, t=10, b=10),
            showlegend=False,
            yaxis_title="Opportunities",
            xaxis_title="",
        )
    
        st.plotly_chart(
            deadline_chart,
            use_container_width=True,
            config={"displayModeBar": False},
        )



# ------------------------------------------------------------
# DETAILED OPPORTUNITIES TABLE
# ------------------------------------------------------------

table_header_col, table_search_col, table_download_col = st.columns(
    [5.2, 2.2, 1.15],
    vertical_alignment="center",
)

with table_header_col:
    st.markdown(
        f'<div class="section-heading">Opportunities ({len(filtered):,})</div>',
        unsafe_allow_html=True,
    )

with table_search_col:
    table_search = st.text_input(
        "Search opportunities",
        placeholder="Search opportunities...",
        label_visibility="collapsed",
        key="table_search",
    )

table_filtered = filtered.copy()

if table_search.strip():
    table_term = table_search.strip()

    searchable_columns = [
        "title",
        "agency",
        "opportunity_type",
        "set_aside",
        "place_of_performance",
        "matched_keywords",
    ]

    matches = pd.Series(False, index=table_filtered.index)

    for column in searchable_columns:
        matches = matches | table_filtered[column].astype(str).str.contains(
            table_term,
            case=False,
            na=False,
            regex=False,
        )

    table_filtered = table_filtered[matches].copy()

download_columns = [
    "title",
    "agency",
    "opportunity_type",
    "posted_date",
    "response_deadline",
    "days_left",
    "set_aside",
    "place_of_performance",
    "sam_gov_link",
]

download_csv = (
    table_filtered[download_columns]
    .to_csv(index=False)
    .encode("utf-8")
)

with table_download_col:
    st.download_button(
        "Download",
        data=download_csv,
        file_name="tellcosol_sam_opportunities.csv",
        mime="text/csv",
        use_container_width=True,
    )

if table_filtered.empty:
    st.warning("No opportunities match the selected filters.")
else:
    table = table_filtered[
        [
            "title",
            "agency",
            "opportunity_type",
            "posted_date",
            "response_deadline",
            "days_left_display",
            "set_aside",
            "place_of_performance",
            "sam_gov_link",
        ]
    ].copy()

    table = table.rename(
        columns={
            "title": "Title",
            "agency": "Agency",
            "opportunity_type": "Opportunity Type",
            "posted_date": "Posted Date",
            "response_deadline": "Deadline",
            "days_left_display": "Days Left",
            "set_aside": "Set-Aside",
            "place_of_performance": "Place of Performance",
            "sam_gov_link": "View on SAM.gov",
        }
    )

    st.dataframe(
        table,
        use_container_width=True,
        hide_index=True,
        height=470,
        row_height=46,
        column_order=[
            "Title",
            "Agency",
            "Opportunity Type",
            "Posted Date",
            "Deadline",
            "Days Left",
            "Set-Aside",
            "Place of Performance",
            "View on SAM.gov",
        ],
        column_config={
            "Title": st.column_config.TextColumn(
                "Title",
                width="large",
            ),
            "Agency": st.column_config.TextColumn(
                "Agency",
                width="medium",
            ),
            "Opportunity Type": st.column_config.TextColumn(
                "Opportunity Type",
                width="large",
            ),
            "Posted Date": st.column_config.DatetimeColumn(
                "Posted Date",
                format="MMM D, YYYY",
                width="medium",
            ),
            "Deadline": st.column_config.DatetimeColumn(
                "Deadline",
                format="MMM D, YYYY",
                width="medium",
            ),
            "Days Left": st.column_config.TextColumn(
                "Days Left",
                width="medium",
            ),
            "Set-Aside": st.column_config.TextColumn(
                "Set-Aside",
                width="medium",
            ),
            "Place of Performance": st.column_config.TextColumn(
                "Place of Performance",
                width="medium",
            ),
            "View on SAM.gov": st.column_config.LinkColumn(
                "View on SAM.gov",
                display_text="View",
                width="small",
            ),
        },
    )

# ------------------------------------------------------------
# SOURCE AND METHODOLOGY
# ------------------------------------------------------------

with st.expander("Data source and methodology", expanded=False):
    refresh_value = safe_scalar(
        summary_data,
        "last_refresh_utc",
        fallback="Not available",
    )

    posting_start = safe_scalar(
        summary_data,
        "posting_period_start",
        fallback="Not available",
    )

    posting_end = safe_scalar(
        summary_data,
        "posting_period_end",
        fallback="Not available",
    )

    run_status = safe_scalar(
        summary_data,
        "run_status",
        fallback="Not available",
    )

    source_col_1, source_col_2, source_col_3, source_col_4 = st.columns(4)

    with source_col_1:
        st.metric("Source", "SAM.gov")

    with source_col_2:
        st.metric("Run Status", str(run_status))

    with source_col_3:
        st.metric("Posting Period", f"{posting_start} to {posting_end}")

    with source_col_4:
        st.metric("Last Refresh", str(refresh_value))

    st.markdown(
        """
        <div class="method-note">
        The collector searches the SAM.gov Opportunities API using the 11
        keywords documented in the TellCoSOL procurement and funding queue.
        The dashboard includes active, non-award notices whose response
        deadlines have not passed, plus qualifying notices for which SAM.gov
        provides no response deadline. Award notices and expired deadlines
        remain outside the current-opportunities dashboard.
        </div>
        """,
        unsafe_allow_html=True,
    )

    if not source_health.empty:
        st.markdown("#### Keyword collection status")

        health_columns = [
            column
            for column in [
                "keyword",
                "status",
                "records_collected",
                "records_reported_by_api",
                "cache_hits",
                "error_message",
            ]
            if column in source_health.columns
        ]

        st.dataframe(
            source_health[health_columns],
            use_container_width=True,
            hide_index=True,
        )