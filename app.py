from __future__ import annotations

from datetime import datetime

import pandas as pd
import streamlit as st


# ------------------------------------------------------------
# PAGE CONFIGURATION
# ------------------------------------------------------------

st.set_page_config(
    page_title="TellCoSOL Market Intelligence",
    page_icon="☀️",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ------------------------------------------------------------
# SAMPLE DATA
# ------------------------------------------------------------
# This temporary sample lets us test the Streamlit layout.
# Later, it will be replaced with cleaned SAM.gov Parquet data.

sample_data = pd.DataFrame(
    {
        "title": [
            "Solar Microgrid System",
            "Battery Energy Storage Installation",
            "Deployable Mobile Power System",
            "Critical Facility Resilience Upgrade",
            "Solar-Powered Water Pumping System",
        ],
        "agency": [
            "Department of Defense",
            "Department of the Army",
            "Department of Homeland Security",
            "Department of Veterans Affairs",
            "Department of Agriculture",
        ],
        "segment": [
            "Microgrids and Resilience",
            "Battery Energy Storage",
            "Mobile and Deployable Power",
            "Defense and Mission Energy",
            "Water and Agritech",
        ],
        "fit_score": [91, 84, 79, 76, 68],
        "days_until_deadline": [12, 25, 7, 42, 31],
        "fit_level": [
            "High fit",
            "High fit",
            "High fit",
            "High fit",
            "Medium fit",
        ],
        "status": [
            "Active",
            "Active",
            "Active",
            "Active",
            "Active",
        ],
    }
)


# ------------------------------------------------------------
# SIDEBAR FILTERS
# ------------------------------------------------------------

st.sidebar.title("Dashboard Filters")

selected_segments = st.sidebar.multiselect(
    "TellCoSOL solution segment",
    options=sorted(sample_data["segment"].unique()),
    default=sorted(sample_data["segment"].unique()),
)

selected_fit_levels = st.sidebar.multiselect(
    "Fit level",
    options=sorted(sample_data["fit_level"].unique()),
    default=sorted(sample_data["fit_level"].unique()),
)

maximum_deadline = st.sidebar.slider(
    "Maximum days until deadline",
    min_value=0,
    max_value=90,
    value=90,
)

filtered_data = sample_data[
    sample_data["segment"].isin(selected_segments)
    & sample_data["fit_level"].isin(selected_fit_levels)
    & (
        sample_data["days_until_deadline"]
        <= maximum_deadline
    )
].copy()


# ------------------------------------------------------------
# HEADER
# ------------------------------------------------------------

st.title("Solar Market Trends Dashboard for TellCoSOL")

st.caption(
    "Initial SAM.gov opportunity-intelligence prototype"
)

st.markdown("---")


# ------------------------------------------------------------
# EXECUTIVE PULSE
# ------------------------------------------------------------

st.subheader("Executive Pulse")

metric_1, metric_2, metric_3, metric_4 = st.columns(4)

with metric_1:
    st.metric(
        label="Relevant opportunities",
        value=len(filtered_data),
    )

with metric_2:
    high_fit_count = (
        filtered_data["fit_level"] == "High fit"
    ).sum()

    st.metric(
        label="High-fit opportunities",
        value=int(high_fit_count),
    )

with metric_3:
    closing_soon_count = (
        filtered_data["days_until_deadline"]
        <= 30
    ).sum()

    st.metric(
        label="Closing within 30 days",
        value=int(closing_soon_count),
    )

with metric_4:
    average_score = (
        filtered_data["fit_score"].mean()
        if not filtered_data.empty
        else 0
    )

    st.metric(
        label="Average fit score",
        value=f"{average_score:.1f}",
    )


# ------------------------------------------------------------
# OPPORTUNITY DIRECTION
# ------------------------------------------------------------

st.markdown("---")
st.subheader("Opportunity Direction by TellCoSOL Solution")

if filtered_data.empty:
    st.warning(
        "No opportunities match the selected filters."
    )
else:
    segment_summary = (
        filtered_data
        .groupby("segment", as_index=False)
        .agg(
            opportunities=("title", "count"),
            average_fit_score=("fit_score", "mean"),
            earliest_deadline=(
                "days_until_deadline",
                "min",
            ),
        )
        .sort_values(
            "average_fit_score",
            ascending=False,
        )
    )

    segment_summary["average_fit_score"] = (
        segment_summary["average_fit_score"]
        .round(1)
    )

    st.dataframe(
        segment_summary,
        use_container_width=True,
        hide_index=True,
    )


# ------------------------------------------------------------
# PROCUREMENT FUNNEL
# ------------------------------------------------------------

st.markdown("---")
st.subheader("Procurement Funnel")

funnel_data = pd.DataFrame(
    {
        "stage": [
            "Raw matches",
            "Unique notices",
            "TellCoSOL relevant",
            "Medium or high fit",
            "High fit",
        ],
        "count": [
            12,
            10,
            len(filtered_data),
            int(
                filtered_data["fit_level"]
                .isin(["Medium fit", "High fit"])
                .sum()
            ),
            int(
                (
                    filtered_data["fit_level"]
                    == "High fit"
                ).sum()
            ),
        ],
    }
)

st.bar_chart(
    funnel_data,
    x="stage",
    y="count",
)


# ------------------------------------------------------------
# PROCUREMENT QUEUE
# ------------------------------------------------------------

st.markdown("---")
st.subheader("SAM.gov Procurement Queue")

st.dataframe(
    filtered_data,
    use_container_width=True,
    hide_index=True,
    column_config={
        "fit_score": st.column_config.ProgressColumn(
            "TellCoSOL Fit",
            min_value=0,
            max_value=100,
            format="%d",
        ),
        "days_until_deadline": (
            st.column_config.NumberColumn(
                "Days Remaining",
                format="%d",
            )
        ),
    },
)


# ------------------------------------------------------------
# SOURCE HEALTH
# ------------------------------------------------------------

st.markdown("---")
st.subheader("Source Health")

health_1, health_2, health_3, health_4 = st.columns(4)

with health_1:
    st.metric("Source", "SAM.gov")

with health_2:
    st.metric("Status", "Prototype data")

with health_3:
    st.metric("Cost", "Free API key")

with health_4:
    st.metric(
        "Last refresh",
        datetime.now().strftime("%Y-%m-%d %H:%M"),
    )

st.info(
    "The current page uses temporary sample records. "
    "The next step is to replace them with the cleaned "
    "SAM.gov Parquet feed."
)