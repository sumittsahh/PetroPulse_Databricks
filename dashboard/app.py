import streamlit as st
import pandas as pd
from databricks.sdk import WorkspaceClient
from databricks.sdk.core import Config
from databricks import sql
import os

st.set_page_config(page_title="PetroPulse Ops", layout="wide")
@st.cache_resource
def get_warehouse_http_path():
    w = WorkspaceClient(
        host=os.getenv("DATABRICKS_HOST"),
        client_id=os.getenv("DATABRICKS_CLIENT_ID"),
        client_secret=os.getenv("DATABRICKS_CLIENT_SECRET"),
    )
    for wh in w.warehouses.list():
        if wh.name == "Serverless Starter Warehouse":
            return f"/sql/1.0/warehouses/{wh.id}"
    raise RuntimeError("Serverless Starter Warehouse not found")

def get_connection():
    cfg = Config(
        host=os.getenv("DATABRICKS_HOST"),
        client_id=os.getenv("DATABRICKS_CLIENT_ID"),
        client_secret=os.getenv("DATABRICKS_CLIENT_SECRET"),
    )
    return sql.connect(
        server_hostname=os.getenv("DATABRICKS_HOST"),
        http_path=get_warehouse_http_path(),
        credentials_provider=lambda: cfg.authenticate,
    )

@st.cache_data(ttl=300)
def run_query(query):
    conn = get_connection()
    df = pd.read_sql(query, conn)
    conn.close()
    return df

st.title("🛢️ PetroPulse — Field Risk Monitor")

risk_df = run_query("""
    SELECT region_id, region_name, nearby_events, max_magnitude, wind_speed_kmh,
           precipitation_mm, seismic_score, wind_score, precip_score,
           base_risk_indicator, risk_score, risk_band
    FROM workspace.petropulse_gold.region_risk_scores
    ORDER BY risk_score DESC
""")

col1, col2, col3 = st.columns(3)
col1.metric("Regions monitored", len(risk_df))
col2.metric("High risk", (risk_df.risk_band == "High").sum())
col3.metric("Elevated risk", (risk_df.risk_band == "Elevated").sum())

st.subheader("Regional risk scores")
def color_band(val):
    color = {"High": "#ff4b4b", "Elevated": "#ffb84b", "Low": "#4bb543"}.get(val, "")
    return f"background-color: {color}; color: black"
st.dataframe(risk_df.style.map(color_band, subset=["risk_band"]), use_container_width=True)

st.subheader("Crude price volatility")
vol_df = run_query("""
    SELECT price_date, benchmark, price_usd_bbl, pct_change, volatility_impact
    FROM workspace.petropulse_gold.price_volatility
    ORDER BY price_date DESC, benchmark
    LIMIT 20
""")
st.dataframe(vol_df, use_container_width=True)
c1, c2 = st.columns(2)
for bench, col in [("WTI", c1), ("Brent", c2)]:
    chart_df = vol_df[vol_df.benchmark == bench].sort_values("price_date")
    col.line_chart(chart_df.set_index("price_date")["price_usd_bbl"])

st.subheader("Operational alerts")
alerts_df = run_query("""
    SELECT alert_id, region_name, event_type, severity, risk_score, status, message, created_at
    FROM workspace.petropulse_ops.operational_alerts
    ORDER BY created_at DESC
""")
open_alerts = alerts_df[alerts_df.status == "OPEN"]
st.write(f"**{len(open_alerts)} open alert(s)**")
for _, row in open_alerts.iterrows():
    with st.container(border=True):
        st.write(f"**[{row.severity}] {row.region_name}** — {row.event_type}")
        st.write(row.message)
        if st.button("Resolve", key=row.alert_id):
            conn = get_connection()
            cur = conn.cursor()
            cur.execute(f"""
                UPDATE workspace.petropulse_ops.operational_alerts
                SET status='RESOLVED', resolved_at=current_timestamp(),
                    resolved_by='dashboard_user', resolution_note='Resolved via dashboard'
                WHERE alert_id='{row.alert_id}'
            """)
            conn.close()
            st.cache_data.clear()
            st.rerun()

with st.expander("Resolved alerts history"):
    st.dataframe(alerts_df[alerts_df.status == "RESOLVED"], use_container_width=True)
