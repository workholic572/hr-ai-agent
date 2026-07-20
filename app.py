import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from pathlib import Path
from datetime import datetime
from dateutil.relativedelta import relativedelta
import logging
import os
import logging.config

from config.settings import get_logging_config, STANDARD_CATEGORIES, EXPECTED_HEADCOUNT_COLUMNS, EXPECTED_LEAVERS_COLUMNS
from database.db_helper import DBHelper, CachedDBHelper
from modules.excel_reader import ExcelReader
from modules.headcount_reader import HeadcountReader
from modules.turnover_engine import TurnoverEngine
from modules.resignation_analytics import ResignationAnalytics
from modules.ai_classifier import AIClassifier
from modules.summary_generator import SummaryGenerator
from modules.pdf_generator import PDFReportGenerator

# Configure logging
logging.config.dictConfig(get_logging_config())
logger = logging.getLogger("dashboard")

# Streamlit App Configurations
st.set_page_config(
    page_title="Monal Group | HR AI Analytics",
    page_icon="💼",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Premium Custom CSS
st.markdown("""
<style>
    /* Styling settings */
    @import url('https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;600;700&display=swap');
    
    html, body, [class*="css"] {
        font-family: 'Outfit', sans-serif;
    }
    
    /* Title bar styling */
    .title-container {
        background: linear-gradient(135deg, #1A365D 0%, #2A4365 100%);
        padding: 2rem;
        border-radius: 12px;
        color: white;
        margin-bottom: 2rem;
        box-shadow: 0 4px 20px rgba(0, 0, 0, 0.1);
    }
    .title-container h1 {
        margin: 0;
        font-size: 2.5rem;
        font-weight: 700;
    }
    .title-container p {
        margin: 5px 0 0 0;
        opacity: 0.8;
    }
    
    /* Card Container design */
    .kpi-card {
        background-color: #ffffff;
        border-radius: 10px;
        padding: 1.5rem;
        box-shadow: 0 4px 6px rgba(0,0,0,0.05);
        border: 1px solid #E2E8F0;
        text-align: center;
        transition: transform 0.2s;
    }
    .kpi-card:hover {
        transform: translateY(-2px);
        box-shadow: 0 10px 15px rgba(0,0,0,0.08);
    }
    .kpi-title {
        font-size: 0.9rem;
        color: #718096;
        text-transform: uppercase;
        font-weight: 600;
        margin-bottom: 0.5rem;
    }
    .kpi-value {
        font-size: 2.2rem;
        font-weight: 700;
        color: #2D3748;
        margin-bottom: 0.2rem;
    }
    .kpi-delta {
        font-size: 0.85rem;
        font-weight: 600;
    }
    .delta-up { color: #E53E3E; }
    .delta-down { color: #38A169; }
    .delta-neutral { color: #4A5568; }
</style>
""", unsafe_allow_html=True)

# Helper function to initialize helpers (v1.1 - hot reload modules)
@st.cache_resource
def get_services(dummy_version="1.4"):
    import importlib
    import database.db_helper
    import modules.turnover_engine
    import modules.excel_reader
    import modules.headcount_reader
    import modules.resignation_analytics
    import modules.ai_classifier
    import modules.summary_generator
    import modules.pdf_generator
    
    importlib.reload(database.db_helper)
    importlib.reload(modules.turnover_engine)
    importlib.reload(modules.excel_reader)
    importlib.reload(modules.headcount_reader)
    importlib.reload(modules.resignation_analytics)
    importlib.reload(modules.ai_classifier)
    importlib.reload(modules.summary_generator)
    importlib.reload(modules.pdf_generator)
    
    db = CachedDBHelper()
    reader = ExcelReader(db_helper=db)
    hc_reader = HeadcountReader(db_helper=db, excel_reader=reader)
    turnover = TurnoverEngine(db_helper=db)
    analytics = ResignationAnalytics(db_helper=db)
    classifier = AIClassifier(db_helper=db)
    summary = SummaryGenerator(db_helper=db, turnover_engine=turnover, resignation_analytics=analytics)
    return db, reader, hc_reader, turnover, analytics, classifier, summary

db, reader, hc_reader, turnover, analytics, classifier, summary = get_services(dummy_version="1.5")

# --- SIDEBAR FILTERS ---
st.sidebar.image("https://placehold.co/300x80/1a365d/ffffff?text=The+Monal+Group&font=outfit", use_column_width=True)

# Secret Diagnostics (Debug only, safely masked)
try:
    if st.secrets:
        keys = list(st.secrets.keys())
        st.sidebar.info(f"🔑 Secrets keys loaded: {keys}")
        if "supabase_url" in keys:
            url_val = st.secrets["supabase_url"]
            has_pooler = "pooler" in url_val or "aws-0" in url_val
            st.sidebar.success(f"Supabase secret detected! Pooler: {has_pooler}")
        else:
            st.sidebar.error("supabase_url secret is missing from Streamlit Cloud Secrets!")
    else:
        st.sidebar.error("st.secrets is completely empty!")
except Exception as secrets_err:
    st.sidebar.error(f"Error checking secrets: {secrets_err}")

try:
    from config.settings import load_standards_registry
    depts = load_standards_registry().get("departments", [])
    st.sidebar.info(f"📋 Registered Depts: {depts}")
except Exception as reg_err:
    st.sidebar.error(f"Error loading registry: {reg_err}")


st.sidebar.title("HR Analytics Engine")

# Fetch unique filters from DB dynamically
try:
    all_projects = [p["name"] for p in db.get_projects()]
except Exception:
    all_projects = []

# Fetch months, depts, positions from leavers records if any
df_leavers_raw = pd.DataFrame(db.get_leavers_summary())
if not df_leavers_raw.empty:
    months_list = sorted(df_leavers_raw["record_month"].unique().tolist(), reverse=True)
    depts_list = sorted(df_leavers_raw["department"].unique().tolist())
    positions_list = sorted(df_leavers_raw["position"].unique().tolist())
    reasons_list = sorted(df_leavers_raw["ai_category"].dropna().unique().tolist())
else:
    months_list = []
    depts_list = []
    positions_list = []
    reasons_list = []

# --- Period Selector ---
st.sidebar.subheader("Period Selection")

# 1. Select Year
if months_list and months_list[0] != "No Data Available":
    years_available = sorted(list(set([m.split("-")[0] for m in months_list])), reverse=True)
else:
    years_available = [str(datetime.now().year)]

selected_year = st.sidebar.selectbox("Select Year", years_available)

# Filter months_list to only include months in the selected year
filtered_months = [m for m in months_list if m.startswith(selected_year)] if months_list else []

# 2. Select Period Type
period_type = st.sidebar.selectbox("Period Type", ["Monthly", "Quarterly", "Semi-Annual", "Annual", "Custom Range"])

def _resolve_period(period_type, year, months_in_year):
    """Compute (start_month, end_month, display_label) based on selected year and period type."""
    if not months_in_year:
        return "No Data Available", "No Data Available", "No Data Available"

    if period_type == "Monthly":
        # e.g., "2026-06"
        sel_m = st.sidebar.selectbox("Select Month", sorted(months_in_year, reverse=True))
        return sel_m, sel_m, sel_m

    elif period_type == "Quarterly":
        # Build quarter options for this year
        quarters = {}
        for m in sorted(months_in_year):
            dt = datetime.strptime(m, "%Y-%m")
            q = (dt.month - 1) // 3 + 1
            key = f"{year} Q{q}"
            if key not in quarters:
                q_start = datetime(int(year), (q - 1) * 3 + 1, 1)
                q_end = q_start + relativedelta(months=2)
                quarters[key] = (q_start.strftime("%Y-%m"), q_end.strftime("%Y-%m"))
        q_options = sorted(quarters.keys(), reverse=True)
        if not q_options:
            return "No Data Available", "No Data Available", "No Data Available"
        sel_q = st.sidebar.selectbox("Select Quarter", q_options)
        s, e = quarters[sel_q]
        return s, e, sel_q

    elif period_type == "Semi-Annual":
        halves = {}
        for m in sorted(months_in_year):
            dt = datetime.strptime(m, "%Y-%m")
            h = 1 if dt.month <= 6 else 2
            key = f"{year} H{h}"
            if key not in halves:
                h_start = datetime(int(year), 1 if h == 1 else 7, 1)
                h_end = h_start + relativedelta(months=5)
                halves[key] = (h_start.strftime("%Y-%m"), h_end.strftime("%Y-%m"))
        h_options = sorted(halves.keys(), reverse=True)
        if not h_options:
            return "No Data Available", "No Data Available", "No Data Available"
        sel_h = st.sidebar.selectbox("Select Half-Year", h_options)
        s, e = halves[sel_h]
        return s, e, sel_h

    elif period_type == "Annual":
        s = f"{year}-01"
        e = f"{year}-12"
        return s, e, f"{year} Full Year"

    else:  # Custom Range within Year
        sorted_m = sorted(months_in_year)
        start_m = st.sidebar.selectbox("Start Month", sorted_m)
        # Filter end months to be >= start month
        end_options = [m for m in sorted_m if m >= start_m]
        end_m = st.sidebar.selectbox("End Month", sorted(end_options, reverse=True))
        label = f"{start_m} → {end_m}"
        return start_m, end_m, label

start_month, end_month, period_label = _resolve_period(period_type, selected_year, filtered_months)

# Keep backward-compat variable for pages that still use single-month logic
selected_month = end_month

# Filter options
st.sidebar.subheader("Global Filters")
filter_project = st.sidebar.multiselect("Project Focus", ["All"] + all_projects, default=["All"])
filter_dept = st.sidebar.multiselect("Department Focus", ["All"] + depts_list, default=["All"])
filter_pos = st.sidebar.multiselect("Position Focus", ["All"] + positions_list, default=["All"])

# Navigation Menu
st.sidebar.subheader("Navigation")
menu_selection = st.sidebar.radio(
    "Select Dashboard View",
    [
        "Executive Summary",
        "Turnover Dashboard",
        "Projects Analytics",
        "Departments & Positions",
        "Resignation Reasons",
        "Length of Service",
        "Employee Explorer",
        "Monthly Comparison",
        "Data Ingestion",
        "Data Quality Reports",
        "System Configurations"
    ]
)

# Apply global filters to dataframes local to the views
def apply_filters(df):
    if df.empty:
        return df
    filtered_df = df.copy()
    if filter_project and "All" not in filter_project and "project_name" in filtered_df.columns:
        filtered_df = filtered_df[filtered_df["project_name"].isin(filter_project)]
    if filter_dept and "All" not in filter_dept and "department" in filtered_df.columns:
        filtered_df = filtered_df[filtered_df["department"].isin(filter_dept)]
    if filter_pos and "All" not in filter_pos and "position" in filtered_df.columns:
        filtered_df = filtered_df[filtered_df["position"].isin(filter_pos)]
    return filtered_df

# Check database seed size
db_is_empty = df_leavers_raw.empty

# --- DASHBOARD PAGES ---

# Banner Header
st.markdown(f"""
<div class="title-container">
    <h1>The Monal Group — HR Intelligence</h1>
    <p>AI-Powered Turnover Analytics & Talent Insights Dashboard | Period: {period_label}</p>
</div>
""", unsafe_allow_html=True)

if db_is_empty and menu_selection != "Data Ingestion":
    st.warning("⚠️ No data has been loaded into the system yet. Please head to the **Data Ingestion** page in the sidebar to upload headcount and leavers spreadsheets.")
    st.stop()

# Helper function to render KPI Metric Cards
def render_kpis(metrics_dict):
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        hc_raw = metrics_dict.get('headcount', 0)
        hc_adj = metrics_dict.get('headcount_adjusted', hc_raw)
        st.markdown(f"""
        <div class="kpi-card">
            <div class="kpi-title">Active Headcount</div>
            <div class="kpi-value">{hc_raw}</div>
            <div class="kpi-delta delta-neutral">Turnover Avg HC: {hc_adj}</div>
        </div>
        """, unsafe_allow_html=True)
    with c2:
        st.markdown(f"""
        <div class="kpi-card">
            <div class="kpi-title">Monthly Leavers</div>
            <div class="kpi-value">{metrics_dict.get('leavers', '0')}</div>
            <div class="kpi-delta delta-up">Total Departures</div>
        </div>
        """, unsafe_allow_html=True)
    with c3:
        st.markdown(f"""
        <div class="kpi-card">
            <div class="kpi-title">Monthly Turnover</div>
            <div class="kpi-value">{metrics_dict.get('turnover', '0.0')}%</div>
            <div class="kpi-delta delta-neutral">Turnover Rate</div>
        </div>
        """, unsafe_allow_html=True)
    with c4:
        st.markdown(f"""
        <div class="kpi-card">
            <div class="kpi-title">Early Turnover Risk</div>
            <div class="kpi-value">{metrics_dict.get('early_turnover', '0')}</div>
            <div class="kpi-delta delta-up">< 6 Months Service</div>
        </div>
        """, unsafe_allow_html=True)
    st.markdown("<br>", unsafe_allow_html=True)

if menu_selection == "Executive Summary":
    if selected_month != "No Data Available":
        # Compile KPI metrics for current selected period
        df_hc_curr = pd.DataFrame(db.get_headcount_history(start_month=start_month, end_month=end_month))
        df_hc_adj = turnover.get_adjusted_headcount(start_month=start_month, end_month=end_month)
        df_lv_curr = pd.DataFrame(db.get_leavers_summary(start_month=start_month, end_month=end_month))
        
        # Apply filters
        df_hc_filtered = apply_filters(df_hc_curr)
        df_hc_adj_filtered = apply_filters(df_hc_adj)
        df_lv_filtered = apply_filters(df_lv_curr)
        
        # Calculate rates
        hc_val = int(df_hc_filtered["headcount"].sum()) if not df_hc_filtered.empty else 0
        hc_adj_val = round(df_hc_adj_filtered["headcount"].sum(), 1) if not df_hc_adj_filtered.empty else 0.0
        lv_val = len(df_lv_filtered)
        
        # Aggregate turnover rate using adjusted headcount
        if hc_adj_val > 0:
            rate_val = round((lv_val / hc_adj_val) * 100, 2)
        else:
            rate_val = 0.0
            
        early_val = len(df_lv_filtered[df_lv_filtered["length_of_service_months"] < 6.0]) if not df_lv_filtered.empty else 0
        
        render_kpis({
            "headcount": hc_val,
            "headcount_adjusted": hc_adj_val,
            "leavers": lv_val,
            "turnover": rate_val,
            "early_turnover": early_val
        })
        
        # Split screen for AI narrative vs drill down preview
        col_summary, col_kpis = st.columns([3, 2])
        
        with col_summary:
            st.subheader("🤖 AI Executive Insights")
            with st.spinner("AI is analyzing period metrics and drafting report..."):
                narrative = summary.generate_summary(start_month, end_month)
                st.markdown(narrative)
                
                # Dynamic PDF Report Generator
                st.markdown("---")
                pdf_gen = PDFReportGenerator(db_helper=db)
                try:
                    pdf_filename = f"Monal_Turnover_Report_{start_month}_to_{end_month}.pdf" if start_month != end_month else f"Monal_Turnover_Report_{start_month}.pdf"
                    pdf_path = pdf_gen.generate_report(
                        start_month=start_month,
                        end_month=end_month,
                        period_label=period_label,
                        exec_summary_text=narrative,
                        output_filename=pdf_filename
                    )
                    
                    with open(pdf_path, "rb") as f:
                        pdf_data = f.read()
                    
                    col_dl, col_open = st.columns(2)
                    with col_dl:
                        st.download_button(
                            label="📥 Download PDF Report",
                            data=pdf_data,
                            file_name=pdf_filename,
                            mime="application/pdf",
                            use_container_width=True
                        )
                    with col_open:
                        if st.button("📂 Open PDF Report", use_container_width=True):
                            abs_path = str(pdf_path.resolve())
                            try:
                                import subprocess
                                if os.name == 'nt':
                                    os.startfile(abs_path)
                                    st.success(f"Opening report: {pdf_filename}")
                                else:
                                    st.info("📥 Use the Download button to get your PDF report. Direct file opening is only available when running locally on Windows.")
                            except Exception as e:
                                st.error(f"Could not open file: {e}")
                except Exception as e:
                    st.error(f"Error generating PDF report: {e}")
                    logger.error(f"PDF generation failed: {e}", exc_info=True)

                
        with col_kpis:
            st.subheader("💡 Key Areas Affected")
            if not df_lv_filtered.empty:
                top_data = analytics.get_top_affected_areas(df_lv_filtered, top_n=3)
                
                st.markdown("**Top Affected Departments:**")
                for d in top_data["departments"]:
                    st.write(f"- {d['name']}: {d['count']} departures ({d['percentage']}%)")
                    
                st.markdown("**Top Departure Drivers (AI Classified):**")
                for r in top_data["reasons"]:
                    st.write(f"- {r['name']}: {r['count']} departures ({r['percentage']}%)")
                    
                # Small doughnut chart of reasons
                df_reason_chart = df_lv_filtered["ai_category"].value_counts().reset_index()
                fig = px.pie(df_reason_chart, values="count", names="ai_category", hole=0.4, title="Departures by AI Category", color_discrete_sequence=px.colors.qualitative.Pastel)
                fig.update_layout(margin=dict(l=0, r=0, t=30, b=0), height=250)
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("No departures recorded under these filter selections for this period.")

elif menu_selection == "Turnover Dashboard":
    st.subheader("📉 Corporate Turnover & Trend Analysis")
    
    # Establish tabs
    tab_turnover, tab_headcount = st.tabs(["📈 Turnover Trends", "📊 Headcount & Net Change"])
    
    # Common data fetching
    df_hc_all = pd.DataFrame(db.get_headcount_history())
    df_lv_all = pd.DataFrame(db.get_leavers_summary())
    
    with tab_turnover:
        # Group by month and project to calculate overall monthly turnover rate (using adjusted headcount!)
        months_trend = sorted(df_lv_all["record_month"].dropna().unique().tolist())
        trend_rates = []
        
        for m in months_trend:
            df_lv_m = df_lv_all[df_lv_all["record_month"] == m]
            df_lv_filt = apply_filters(df_lv_m)
            tot_lv = len(df_lv_filt)
            
            # Fetch adjusted headcount for this specific month
            df_hc_adj = turnover.get_adjusted_headcount(start_month=m, end_month=m)
            df_hc_adj_filt = apply_filters(df_hc_adj)
            tot_hc_adj = df_hc_adj_filt["headcount"].sum() if not df_hc_adj_filt.empty else 0.0
            
            rate = round((tot_lv / tot_hc_adj) * 100, 2) if tot_hc_adj > 0 else 0.0
            trend_rates.append({
                "Month": m,
                "Headcount (Adjusted)": tot_hc_adj,
                "Departures": tot_lv,
                "Turnover Rate (%)": rate
            })
            
        df_trend = pd.DataFrame(trend_rates)
        
        col_line, col_roll = st.columns([3, 2])
        
        with col_line:
            if not df_trend.empty:
                fig_line = px.line(df_trend, x="Month", y="Turnover Rate (%)", text="Turnover Rate (%)", title="Monthly Turnover Rate Trend (%) (Using Adjusted Headcount)", markers=True)
                fig_line.update_traces(textposition="top center", line=dict(color="#1A365D", width=3))
                fig_line.update_layout(xaxis_title="Month", yaxis_title="Turnover Rate (%)", height=400)
                st.plotly_chart(fig_line, use_container_width=True)
            else:
                st.info("No trend data available.")
                
        with col_roll:
            st.subheader("🔄 Rolling 12-Month Indicator")
            if selected_month != "No Data Available":
                try:
                    rolling_metrics = turnover.calculate_rolling_12_month_turnover(selected_month)
                    
                    st.markdown(f"**Period:** {rolling_metrics['period']}")
                    st.markdown(f"**Average 12M Headcount (Adjusted):** {rolling_metrics['avg_headcount']}")
                    st.markdown(f"**Total Departures (12M):** {rolling_metrics['leavers_count']}")
                    
                    # Gauge chart
                    fig_gauge = go.Figure(go.Indicator(
                        mode = "gauge+number",
                        value = rolling_metrics['turnover_rate'],
                        domain = {'x': [0, 1], 'y': [0, 1]},
                        title = {'text': "Rolling 12M Turnover (%)", 'font': {'size': 18}},
                        gauge = {
                            'axis': {'range': [None, 30]},
                            'bar': {'color': "#1A365D"},
                            'steps': [
                                {'range': [0, 10], 'color': "#D4EDDA"},
                                {'range': [10, 20], 'color': "#FFF3CD"},
                                {'range': [20, 30], 'color': "#F8D7DA"}
                            ]
                        }
                    ))
                    fig_gauge.update_layout(height=280, margin=dict(l=20, r=20, t=40, b=0))
                    st.plotly_chart(fig_gauge, use_container_width=True)
                except Exception as e:
                    st.warning(f"Could not calculate rolling 12M trend: {e}")

    with tab_headcount:
        st.subheader("📊 Headcount Net Increase / Decrease Analysis")
        
        if selected_month != "No Data Available":
            previous_month = turnover.get_previous_month(selected_month)
            
            # Fetch current and previous headcount
            df_hc_curr = df_hc_all[df_hc_all["record_month"] == selected_month]
            df_hc_prev = df_hc_all[df_hc_all["record_month"] == previous_month]
            
            df_hc_curr_filt = apply_filters(df_hc_curr)
            df_hc_prev_filt = apply_filters(df_hc_prev)
            
            curr_hc = int(df_hc_curr_filt["headcount"].sum()) if not df_hc_curr_filt.empty else 0
            prev_hc = int(df_hc_prev_filt["headcount"].sum()) if not df_hc_prev_filt.empty else 0
            
            net_change = curr_hc - prev_hc
            pct_change = round((net_change / prev_hc * 100), 1) if prev_hc > 0 else 0.0
            
            # Net change visual indicators
            c_curr, c_prev, c_net = st.columns(3)
            with c_curr:
                st.metric("Current Month Headcount", f"{curr_hc}", help=f"Total headcount in {selected_month}")
            with c_prev:
                st.metric("Previous Month Headcount", f"{prev_hc}", help=f"Total headcount in {previous_month}")
            with c_net:
                delta_str = f"+{net_change} ({pct_change}%)" if net_change > 0 else f"{net_change} ({pct_change}%)"
                st.metric("Net Headcount Change", delta_str, delta=net_change, help="Change in raw headcount comparing to last month")
                
            st.markdown("---")
            
            col_trends, col_table = st.columns([3, 2])
            
            with col_trends:
                st.markdown("#### Headcount Trend (Raw vs Adjusted)")
                # Generate historical comparison of raw vs adjusted
                hc_trends = []
                all_months = sorted(df_hc_all["record_month"].dropna().unique().tolist())
                for m in all_months:
                    df_raw_m = df_hc_all[df_hc_all["record_month"] == m]
                    df_raw_m_filt = apply_filters(df_raw_m)
                    raw_sum = int(df_raw_m_filt["headcount"].sum()) if not df_raw_m_filt.empty else 0
                    
                    df_adj_m = turnover.get_adjusted_headcount(start_month=m, end_month=m)
                    df_adj_m_filt = apply_filters(df_adj_m)
                    adj_sum = round(df_adj_m_filt["headcount"].sum(), 1) if not df_adj_m_filt.empty else 0.0
                    
                    hc_trends.append({
                        "Month": m,
                        "Raw Headcount": raw_sum,
                        "Adjusted Headcount": adj_sum
                    })
                df_hc_trends = pd.DataFrame(hc_trends)
                
                if not df_hc_trends.empty:
                    fig_hc_line = px.line(
                        df_hc_trends, x="Month", y=["Raw Headcount", "Adjusted Headcount"],
                        markers=True, title="Monthly Headcount Smoothing Trend",
                        color_discrete_map={"Raw Headcount": "#1A365D", "Adjusted Headcount": "#D69E2E"}
                    )
                    fig_hc_line.update_layout(xaxis_title="Month", yaxis_title="Headcount Strength", height=350)
                    st.plotly_chart(fig_hc_line, use_container_width=True)
                else:
                    st.info("No headcount trend data available.")
                    
            with col_table:
                st.markdown("#### Project-wise Net Changes")
                proj_comparison = []
                for p in all_projects:
                    df_curr_p = df_hc_curr[df_hc_curr["project_name"] == p]
                    df_prev_p = df_hc_prev[df_hc_prev["project_name"] == p]
                    
                    # Apply project filter
                    df_curr_p_filt = apply_filters(df_curr_p)
                    df_prev_p_filt = apply_filters(df_prev_p)
                    
                    c_val = int(df_curr_p_filt["headcount"].sum()) if not df_curr_p_filt.empty else 0
                    p_val = int(df_prev_p_filt["headcount"].sum()) if not df_prev_p_filt.empty else 0
                    
                    n_change = c_val - p_val
                    p_change = round((n_change / p_val * 100), 1) if p_val > 0 else 0.0
                    
                    proj_comparison.append({
                        "Project": p,
                        f"{previous_month} HC": p_val,
                        f"{selected_month} HC": c_val,
                        "Net Change": n_change,
                        "Change (%)": p_change
                    })
                df_proj_comparison = pd.DataFrame(proj_comparison)
                st.dataframe(df_proj_comparison, hide_index=True, use_container_width=True)
                
            # Horizontal Bar Chart for project changes
            if not df_proj_comparison.empty:
                # Add color category for positive vs negative changes
                df_proj_comparison["Direction"] = df_proj_comparison["Net Change"].apply(lambda x: "Increase" if x > 0 else ("Decrease" if x < 0 else "No Change"))
                fig_change_bar = px.bar(
                    df_proj_comparison,
                    x="Net Change",
                    y="Project",
                    orientation="h",
                    text="Net Change",
                    color="Direction",
                    color_discrete_map={"Increase": "#38A169", "Decrease": "#E53E3E", "No Change": "#A0AEC0"},
                    title="Headcount Net Increase/Decrease by Project"
                )
                fig_change_bar.update_layout(height=280)
                st.plotly_chart(fig_change_bar, use_container_width=True)
        else:
            st.info("Please select a month to view the net change report.")

elif menu_selection == "Projects Analytics":
    st.subheader("🏢 Project-Wise Drill Down")
    
    df_hc_adj = turnover.get_adjusted_headcount(start_month=start_month, end_month=end_month)
    df_lv = pd.DataFrame(db.get_leavers_summary(start_month=start_month, end_month=end_month))
    
    # Calculate project-specific headcount averages & leavers
    project_metrics = []
    for p in all_projects:
        df_hc_p = df_hc_adj[df_hc_adj["project_name"] == p]
        df_lv_p = df_lv[df_lv["project_name"] == p]
        
        hc_count = float(df_hc_p["headcount"].sum()) if not df_hc_p.empty else 0.0
        lv_count = len(df_lv_p)
        rate = round((lv_count / hc_count) * 100, 2) if hc_count > 0 else 0.0
        
        project_metrics.append({
            "Project": p,
            "Headcount (Adjusted)": round(hc_count, 1),
            "Departures": lv_count,
            "Turnover Rate (%)": rate
        })
        
    df_proj = pd.DataFrame(project_metrics)
    
    col_bar, col_table = st.columns([3, 2])
    with col_bar:
        fig_bar = px.bar(df_proj, x="Project", y="Turnover Rate (%)", color="Project", text="Turnover Rate (%)", title="Turnover Rate by Project (%)", color_discrete_sequence=px.colors.qualitative.Dark2)
        fig_bar.update_layout(height=400, showlegend=False)
        st.plotly_chart(fig_bar, use_container_width=True)
        
    with col_table:
        st.write("### Project Summary Metrics")
        st.dataframe(df_proj, hide_index=True)

elif menu_selection == "Departments & Positions":
    st.subheader("👥 Department & Position Vulnerability")
    
    df_lv = apply_filters(pd.DataFrame(db.get_leavers_summary(start_month=start_month, end_month=end_month)))
    
    if not df_lv.empty:
        col_dept, col_pos = st.columns(2)
        
        with col_dept:
            df_dept = df_lv["department"].value_counts().reset_index()
            df_dept.columns = ["Department", "Departures"]
            fig_dept = px.bar(df_dept, y="Department", x="Departures", orientation="h", text="Departures", title="Departures by Department", color="Departures", color_continuous_scale="reds")
            fig_dept.update_layout(height=400)
            st.plotly_chart(fig_dept, use_container_width=True)
            
        with col_pos:
            df_pos = df_lv["position"].value_counts().reset_index()
            df_pos.columns = ["Position", "Departures"]
            fig_pos = px.bar(df_pos, x="Position", y="Departures", text="Departures", title="Departures by Position", color="Departures", color_continuous_scale="blues")
            fig_pos.update_layout(height=400)
            st.plotly_chart(fig_pos, use_container_width=True)
    else:
        st.info("No departure records found matching selections.")

elif menu_selection == "Resignation Reasons":
    st.subheader("💬 Reason Classification Analysis")
    
    df_lv = apply_filters(pd.DataFrame(db.get_leavers_summary(start_month=start_month, end_month=end_month)))
    
    if not df_lv.empty:
        # Use AI category as the primary reason column
        # Fill nulls with "Unclassified" so they surface visibly
        df_lv["ai_category"] = df_lv["ai_category"].fillna("Other")
        
        col_table, col_chart = st.columns([2, 3])
        
        with col_table:
            st.markdown("#### Standard HR Categories (AI Classified)")
            cat_counts = df_lv["ai_category"].value_counts().reset_index()
            cat_counts.columns = ["HR Category", "Departures"]
            cat_counts["Share (%)"] = (cat_counts["Departures"] / len(df_lv) * 100).round(1)
            st.dataframe(cat_counts, hide_index=True, use_container_width=True)
            
            # Original reason as secondary reference inside expander
            with st.expander("📋 View Original Reason Entries"):
                orig_df = df_lv[["employee_name", "original_reason", "ai_category"]].copy()
                orig_df.columns = ["Employee", "Original Reason", "Assigned Category"]
                st.dataframe(orig_df, hide_index=True, use_container_width=True)
            
        with col_chart:
            st.markdown("#### Departure Distribution by HR Category")
            ai_counts = df_lv["ai_category"].value_counts().reset_index()
            ai_counts.columns = ["AI HR Category", "Count"]
            fig_ai = px.treemap(
                ai_counts,
                path=["AI HR Category"],
                values="Count",
                title="Departures by Standard HR Category",
                color="Count",
                color_continuous_scale="viridis"
            )
            fig_ai.update_layout(height=400)
            st.plotly_chart(fig_ai, use_container_width=True)
            
            # Bar chart breakdown
            fig_bar = px.bar(
                cat_counts.sort_values("Departures", ascending=True),
                x="Departures", y="HR Category", orientation="h",
                text="Departures",
                title="Ranked Breakdown of HR Categories",
                color="Departures",
                color_continuous_scale="reds"
            )
            fig_bar.update_layout(height=350, coloraxis_showscale=False)
            st.plotly_chart(fig_bar, use_container_width=True)
    else:
        st.info("No departures for this period.")


elif menu_selection == "Length of Service":
    st.subheader("⏳ Tenure & Length of Service Analysis")
    
    df_lv = apply_filters(pd.DataFrame(db.get_leavers_summary(start_month=start_month, end_month=end_month)))
    
    if not df_lv.empty:
        # Bracket counts
        brackets = df_lv["length_of_service_months"].apply(ResignationAnalytics.get_service_bracket)
        bracket_order = ["< 3 Months", "3 - 6 Months", "6 - 12 Months", "1 - 2 Years", "> 2 Years"]
        bracket_counts = brackets.value_counts().reindex(bracket_order, fill_value=0).reset_index()
        bracket_counts.columns = ["Service Bracket", "Departures"]
        
        col_chart, col_early = st.columns([3, 2])
        
        with col_chart:
            fig_bracket = px.bar(bracket_counts, x="Service Bracket", y="Departures", text="Departures", title="Departures by Service Bracket", color="Service Bracket", color_discrete_sequence=px.colors.sequential.Sunset_r)
            fig_bracket.update_layout(height=400, showlegend=False)
            st.plotly_chart(fig_bracket, use_container_width=True)
            
        with col_early:
            st.write("### Early Turnover Records (< 6 Months)")
            early_records = df_lv[df_lv["length_of_service_months"] < 6.0]
            if not early_records.empty:
                st.dataframe(early_records[["employee_id", "employee_name", "department", "position", "length_of_service_months"]], hide_index=True)
            else:
                st.success("No early turnover recorded in this period!")
    else:
        st.info("No departure data.")

elif menu_selection == "Employee Explorer":
    st.subheader("🔍 Employee Talent Explorer")
    
    df_lv_all = apply_filters(pd.DataFrame(db.get_leavers_summary()))
    
    if not df_lv_all.empty:
        # Filters in body
        search_query = st.text_input("Search Employee Name or ID", "")
        if search_query:
            df_lv_all = df_lv_all[
                df_lv_all["employee_name"].str.contains(search_query, case=False, na=False) |
                df_lv_all["employee_id"].str.contains(search_query, case=False, na=False)
            ]
            
        # Display Interactive Table
        st.dataframe(
            df_lv_all[[
                "employee_id", "employee_name", "project_name", "department",
                "position", "date_of_joining", "date_of_leaving",
                "length_of_service_months", "original_reason", "ai_category", "record_month"
            ]],
            use_container_width=True,
            hide_index=True
        )
    else:
        st.info("No records found.")

elif menu_selection == "Monthly Comparison":
    st.subheader(f"📅 Period Attrition Report — {period_label}")
    
    if start_month == "No Data Available":
        st.info("No data is available to compare.")
    else:
        # Helper to retrieve months within range
        def _get_months_in_period(s_month, e_month):
            s_dt = datetime.strptime(s_month, "%Y-%m")
            e_dt = datetime.strptime(e_month, "%Y-%m")
            res = []
            curr = s_dt
            while curr <= e_dt:
                res.append(curr.strftime("%Y-%m"))
                curr += relativedelta(months=1)
            return res

        # Helper to format month label e.g. "2026-01" -> "Jan-26"
        def _short_month_label(m):
            dt = datetime.strptime(m, "%Y-%m")
            return dt.strftime("%b-%y")

        months_current = _get_months_in_period(start_month, end_month)

        # ── SECTION 1: Current Period Month-by-Month Breakdown ──
        st.write(f"### 📊 {period_label} — Monthly Turnover by Project")

        breakdown_rows = []
        for p in all_projects:
            row = {"Project": p}
            for m in months_current:
                label = _short_month_label(m)
                rate = turnover.calculate_project_turnover(p, m, m)
                row[label] = f"{rate}%"
            breakdown_rows.append(row)
        
        df_breakdown = pd.DataFrame(breakdown_rows)
        st.dataframe(df_breakdown, hide_index=True, use_container_width=True)

        # ── SECTION 2: Period vs Previous Period Comparison ──
        st.markdown("---")
        
        start_b, end_b = summary._calculate_previous_range(start_month, end_month)
        
        if start_month == end_month:
            label_a = start_month
            label_b = start_b
        else:
            label_a = f"{start_month} to {end_month}"
            label_b = f"{start_b} to {end_b}"

        st.write(f"### 🔄 Period Comparison: {label_a} vs {label_b}")

        rate_a = turnover.calculate_overall_turnover(start_month, end_month)
        rate_b = turnover.calculate_overall_turnover(start_b, end_b)
        diff = round(rate_a - rate_b, 2)
        
        c_overall1, c_overall2, c_diff = st.columns(3)
        with c_overall1:
            st.metric(f"Turnover ({label_a})", f"{rate_a}%")
        with c_overall2:
            st.metric(f"Turnover ({label_b})", f"{rate_b}%")
        with c_diff:
            st.metric("Difference", f"{diff}%", delta=diff, delta_color="inverse")

        # Project-wise comparison table
        proj_data = []
        for p in all_projects:
            curr_proj = turnover.calculate_project_turnover(p, start_month, end_month)
            comp_proj = turnover.calculate_project_turnover(p, start_b, end_b)
            proj_data.append({
                "Project": p,
                f"Turnover ({label_a}) (%)": curr_proj,
                f"Turnover ({label_b}) (%)": comp_proj,
                "Difference (%)": round(curr_proj - comp_proj, 2)
            })
        st.dataframe(pd.DataFrame(proj_data), hide_index=True, use_container_width=True)

        # ── SECTION 3: Resignation & Termination Details ──
        st.markdown("---")
        st.write(f"### 📋 Separation Details — {period_label}")

        leavers_raw = db.get_leavers_summary(start_month=start_month, end_month=end_month)

        if not leavers_raw:
            st.info("No leaver records found for this period.")
        else:
            df_leavers = pd.DataFrame(leavers_raw)

            # Build clean display DataFrame
            display_cols = {
                "employee_id": "Employee ID",
                "employee_name": "Employee Name",
                "project_name": "Project",
                "department": "Department",
                "position": "Position",
                "date_of_joining": "Date of Joining",
                "date_of_leaving": "Date of Leaving",
                "length_of_service_months": "Tenure (Months)",
                "status": "Status",
                "ai_category": "Separation Category",
                "original_reason": "Original Reason",
            }
            # Only keep columns that exist in the data
            cols_available = [c for c in display_cols.keys() if c in df_leavers.columns]
            df_display = df_leavers[cols_available].rename(columns=display_cols)

            # Round tenure
            if "Tenure (Months)" in df_display.columns:
                df_display["Tenure (Months)"] = df_display["Tenure (Months)"].round(1)

            # Split into Terminations vs Resignations/Other based on Status column
            if "Status" in df_display.columns:
                mask_term = df_display["Status"].str.lower().str.strip() == "terminated"
            else:
                # Fallback to category if Status is somehow missing
                termination_categories = ["Termination", "Attendance / Discipline"]
                mask_term = df_display["Separation Category"].isin(termination_categories) if "Separation Category" in df_display.columns else pd.Series([False] * len(df_display))
            
            df_terminations = df_display[mask_term].reset_index(drop=True)
            df_resignations = df_display[~mask_term].reset_index(drop=True)

            # Summary KPIs
            total_separations = len(df_display)
            total_terminations = len(df_terminations)
            total_resignations = len(df_resignations)

            kpi1, kpi2, kpi3 = st.columns(3)
            with kpi1:
                st.metric("Total Separations", total_separations)
            with kpi2:
                st.metric("🔴 Terminations / Discipline", total_terminations)
            with kpi3:
                st.metric("Voluntary Resignations", total_resignations)

            tab_term, tab_resign, tab_all = st.tabs(["🔴 Terminations", "📄 Resignations", "📊 All Separations"])

            with tab_term:
                if df_terminations.empty:
                    st.success("No terminations in this period.")
                else:
                    st.warning(f"⚠️ {total_terminations} employee(s) terminated / left without notice in this period.")
                    st.dataframe(
                        df_terminations.style.map(
                            lambda _: "background-color: #ffebee; color: #c62828;",
                            subset=["Separation Category"] if "Separation Category" in df_terminations.columns else []
                        ),
                        hide_index=True,
                        use_container_width=True
                    )

            with tab_resign:
                if df_resignations.empty:
                    st.info("No voluntary resignations in this period.")
                else:
                    st.dataframe(df_resignations, hide_index=True, use_container_width=True)

            with tab_all:
                st.dataframe(df_display, hide_index=True, use_container_width=True)

elif menu_selection == "Data Ingestion":
    st.subheader("📥 Excel Data Ingestion Pipeline")

    # ⚠️ Streamlit Cloud Ephemeral Filesystem Warning
    import platform
    if not os.path.exists("/mount/src") is False or os.path.exists("/mount/src"):
        st.warning(
            "⚠️ **Streamlit Cloud Notice:** This app runs on an ephemeral filesystem — "
            "the database resets whenever the app restarts or redeploys. "
            "You will need to **re-upload your headcount and leavers files** after each restart. "
            "For persistent storage, consider connecting a cloud database (e.g. Supabase, PlanetScale)."
        )
    
    st.markdown("""
    Upload monthly files to process headcount and leavers lists. 
    The file names must contain the target month (e.g. `headcount_2026_06.xlsx` or `leavers_2026_06.xlsx`).
    """)
    
    with st.expander("📥 Download Blank Excel Templates"):
        import io
        
        # Headcount Template
        df_hc_template = pd.DataFrame(columns=EXPECTED_HEADCOUNT_COLUMNS)
        buffer_hc = io.BytesIO()
        with pd.ExcelWriter(buffer_hc, engine="openpyxl") as writer:
            df_hc_template.to_excel(writer, index=False, sheet_name="Headcount")
        buffer_hc.seek(0)
        st.download_button(
            label="📄 Download Headcount Template",
            data=buffer_hc,
            file_name="headcount_YYYY_MM.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        
        # Leavers Template
        df_lv_template = pd.DataFrame(columns=EXPECTED_LEAVERS_COLUMNS)
        buffer_lv = io.BytesIO()
        with pd.ExcelWriter(buffer_lv, engine="openpyxl") as writer:
            df_lv_template.to_excel(writer, index=False, sheet_name="Leavers")
        buffer_lv.seek(0)
        st.download_button(
            label="📄 Download Leavers Template",
            data=buffer_lv,
            file_name="leavers_YYYY_MM.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        
        st.caption("ℹ️ Rename `YYYY_MM` to the actual year and month (e.g., `2026_07`) before uploading.")
        
    st.markdown("---")
    
    upload_type = st.radio("File Type", ["Headcount", "Leavers"])
    uploaded_file = st.file_uploader(f"Choose {upload_type} Excel File", type=["xlsx", "xls"])
    
    if uploaded_file:
        # Create temp folder inside workspace to save the file
        temp_dir = Path("data/processed/temp_upload")
        temp_dir.mkdir(parents=True, exist_ok=True)
        file_path = temp_dir / uploaded_file.name
        
        # Save uploaded file
        with open(file_path, "wb") as f:
            f.write(uploaded_file.getbuffer())
            
        st.info(f"File uploaded. Processing: {uploaded_file.name}")
        
        # Parse and validate
        if upload_type == "Headcount":
            # Troubleshoot helper: print the raw Excel structure if it yields 0 records
            try:
                raw_df = pd.read_excel(file_path)
                st.write(f"🔍 Debug Info: Raw file columns: {list(raw_df.columns)} | Shape: {raw_df.shape}")
                st.dataframe(raw_df.head(5))
            except Exception as e:
                st.write(f"Debug Info Error reading file: {e}")
            
            report = reader.parse_and_validate_headcount(file_path)
        else:
            report = reader.parse_and_validate_leavers(file_path)
            
        # Display report status
        if report["is_valid"]:
            st.success(f"✅ File Validation Successful! Clean data extracted for Month **{report['record_month']}**.")
            st.write(f"Total valid records: **{report['valid_rows_count']}**.")
            
            # Show fuzzy normalization corrections if any (Leavers only)
            normalizations = report.get("normalizations", [])
            if normalizations:
                # Deduplicate by (field, original, normalized)
                seen = set()
                unique_norms = []
                for n in normalizations:
                    key = (n["field"], n["original"], n["normalized"])
                    if key not in seen:
                        seen.add(key)
                        unique_norms.append(n)
                
                with st.expander(f"🔄 Auto-Corrections Applied ({len(unique_norms)} unique fixes) — click to review"):
                    st.info(
                        "The system detected similar Department and Position names and merged them "
                        "automatically. These corrections are applied before saving to the database."
                    )
                    df_norms = pd.DataFrame(unique_norms)[["field", "original", "normalized"]]
                    df_norms.columns = ["Field", "Original Value", "Normalized To"]
                    st.dataframe(df_norms, hide_index=True, use_container_width=True)
            
            st.dataframe(pd.DataFrame(report["data"]).head(10), use_container_width=True)
            
            if st.button("Commit to Database"):
                st.write("🔄 Commit process started...")
                with st.spinner("Writing data and executing classification..."):
                    try:
                        # Process file writes to DB
                        if upload_type == "Headcount":
                            for rec in report["data"]:
                                db.insert_headcount(rec["project"], rec["record_month"], rec["headcount"])
                        else:
                            for rec in report["data"]:
                                db.insert_leaver(rec)
                            # Run batch classification
                            classifier.classify_unprocessed_leavers()
                            
                        # Clear Streamlit cache data to reload new dataset
                        st.cache_data.clear()
                        st.success("🎉 Data successfully written to the database! Refreshing dashboard...")
                        st.rerun()
                    except Exception as commit_err:
                        st.error(f"❌ Database Commit Failed: {commit_err}")
                        logger.error(f"Database commit error: {commit_err}", exc_info=True)
        else:
            st.error(f"❌ File Validation Failed! Errors detected in the spreadsheet.")
            st.write("Please correct the following errors and re-upload:")
            st.dataframe(pd.DataFrame(report["errors"]), use_container_width=True)
            
            # Quick-fix logic: extract unrecognized standard values and offer automatic addition
            try:
                errors_df = pd.DataFrame(report["errors"])
                unrecognized_items = errors_df[errors_df["message"].str.contains("Unrecognized", na=False)]
                
                if not unrecognized_items.empty:
                    st.write("---")
                    st.info("💡 **Quick Fix:** Some columns contain values not present in your System Standards. You can add them automatically below:")
                    
                    depts_to_add = unrecognized_items[unrecognized_items["column"] == "Department"]["value"].dropna().unique().tolist()
                    positions_to_add = unrecognized_items[unrecognized_items["column"] == "Position"]["value"].dropna().unique().tolist()
                    projects_to_add = unrecognized_items[unrecognized_items["column"] == "Project"]["value"].dropna().unique().tolist()
                    
                    if depts_to_add:
                        st.write(f"- **Departments to add:** {depts_to_add}")
                    if positions_to_add:
                        st.write(f"- **Positions to add:** {positions_to_add}")
                    if projects_to_add:
                        st.write(f"- **Projects to add:** {projects_to_add}")
                        
                    if st.button("➕ Add Unrecognized Values to System Standards"):
                        from config.settings import save_standards_registry
                        import json
                        from pathlib import Path
                        
                        registry_path = Path("config/standards_registry.json")
                        try:
                            with open(registry_path, "r") as f:
                                registry = json.load(f)
                        except:
                            registry = {"departments": [], "positions": [], "projects": []}
                            
                        added_count = 0
                        for d in depts_to_add:
                            if d not in registry["departments"]:
                                registry["departments"].append(d)
                                added_count += 1
                        for p in positions_to_add:
                            if p not in registry["positions"]:
                                registry["positions"].append(p)
                                added_count += 1
                        for pr in projects_to_add:
                            if pr not in registry["projects"]:
                                registry["projects"].append(pr)
                                added_count += 1
                                
                        if added_count > 0:
                            save_standards_registry(registry)
                            st.cache_data.clear()  # Clear cache
                            st.success(f"🎉 Successfully added {added_count} new standard values! Re-validating file...")
                            st.rerun()
            except Exception as quickfix_err:
                logger.error(f"Error rendering standards quick-fix: {quickfix_err}", exc_info=True)
            
        # Clean up temp file
        try:
            file_path.unlink()
            temp_dir.rmdir()
        except Exception:
            pass

elif menu_selection == "Data Quality Reports":
    st.subheader("📋 System Quality Audits")
    
    st.write("Scan and execute diagnostics on active data directories.")
    
    col_scan, col_run = st.columns(2)
    with col_scan:
        if st.button("Audit Data Directory Files"):
            # Check data/headcount and data/leavers and parse all files
            hc_files = list(Path("data/headcount").glob("*.xlsx"))
            lv_files = list(Path("data/leavers").glob("*.xlsx"))
            
            st.write(f"Found **{len(hc_files)}** Headcount files and **{len(lv_files)}** Leavers files.")
            
            for file in hc_files:
                rep = reader.parse_and_validate_headcount(file)
                st.write(f"- `{file.name}`: Valid: **{rep['is_valid']}**, Rows: {rep['total_rows']}, Errors: {len(rep['errors'])}")
            for file in lv_files:
                rep = reader.parse_and_validate_leavers(file)
                st.write(f"- `{file.name}`: Valid: **{rep['is_valid']}**, Rows: {rep['total_rows']}, Errors: {len(rep['errors'])}")
                
    with col_run:
        st.write("### AI Reason Engine Processing")
        unclassified_count = len(db.get_unclassified_leavers())
        st.write(f"Unclassified leavers in DB: **{unclassified_count}**.")
        if unclassified_count > 0:
            if st.button("Trigger AI Reason Classification"):
                with st.spinner("Classifying reasons..."):
                    proc = classifier.classify_unprocessed_leavers()
                    st.success(f"Successfully classified {proc} records!")

elif menu_selection == "System Configurations":
    st.subheader("⚙️ System Standards Configuration")
    st.write("Manage the strict registry of recognized Departments, Projects, and Positions.")
    st.info("💡 Any newly uploaded Excel data MUST match these canonical names exactly (or be close enough for the AI normalizer to safely match them), otherwise the upload will be blocked.")
    
    from config.settings import STANDARDS_REGISTRY, save_standards_registry
    
    # Reload from disk just to be safe
    import json
    from pathlib import Path
    registry_path = Path("config/standards_registry.json")
    try:
        with open(registry_path, "r") as f:
            registry = json.load(f)
    except:
        registry = {"departments": [], "positions": [], "projects": []}
    
    tabs = st.tabs(["📂 Projects", "🏢 Departments", "👔 Positions"])
    
    # helper for managing lists
    def render_manager(key, title, icon):
        st.write(f"### {icon} Authorized {title}")
        items = sorted(registry.get(key, []))
        
        # Display as pills/tags
        if items:
            st.markdown(
                " ".join([f"<span style='background-color:#e1e8f0; padding:4px 10px; border-radius:15px; margin:2px; display:inline-block; font-size:14px;'>{x}</span>" for x in items]), 
                unsafe_allow_html=True
            )
        else:
            st.warning(f"No {title} found in registry.")
            
        st.write("---")
        c1, c2 = st.columns(2)
        with c1:
            new_item = st.text_input(f"Add New {title[:-1]}", key=f"add_{key}")
            if st.button(f"➕ Add", key=f"btn_add_{key}"):
                if new_item and new_item not in registry[key]:
                    registry[key].append(new_item.strip())
                    save_standards_registry(registry)
                    st.cache_data.clear()  # Clear cache
                    st.success(f"Added '{new_item}'")
                    st.rerun()
        with c2:
            del_item = st.selectbox(f"Remove {title[:-1]}", [""] + items, key=f"del_{key}")
            if st.button(f"🗑️ Remove", key=f"btn_del_{key}"):
                if del_item and del_item in registry[key]:
                    registry[key].remove(del_item)
                    save_standards_registry(registry)
                    st.cache_data.clear()  # Clear cache
                    st.success(f"Removed '{del_item}'")
                    st.rerun()

    with tabs[0]:
        render_manager("projects", "Projects", "📂")
    with tabs[1]:
        render_manager("departments", "Departments", "🏢")
    with tabs[2]:
        render_manager("positions", "Positions", "👔")
