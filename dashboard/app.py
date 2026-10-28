"""
Smart PPE Compliance Monitoring Dashboard
==========================================
Streamlit-based dashboard for monitoring PPE compliance, scan history,
violations, and worker management.

Reads data from the local SQLite database populated by ppe_integration.py.

Usage:
  streamlit run dashboard/app.py

Part of: AI-Based Smart PPE Compliance Monitoring System (Industrial IoT)
"""

import sys
import io
from pathlib import Path
from datetime import datetime, timedelta

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

# ── Project root and database import ─────────────────────────
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from database.db_manager import PPEDatabase, _normalize_uid

# ── Database path (same as ppe_integration.py) ───────────────
DB_PATH = PROJECT_ROOT / "database" / "ppe_monitor.db"

# ── Color palette (industrial / professional) ────────────────
COLORS = {
    "primary":      "#1B2A4A",   # Dark navy
    "secondary":    "#2D4A7A",   # Slate blue
    "success":      "#10B981",   # Green — compliant
    "danger":       "#EF4444",   # Red — violation
    "warning":      "#F59E0B",   # Amber — pending
    "info":         "#3B82F6",   # Blue — info
    "text":         "#E2E8F0",   # Light text
    "card_bg":      "#1E293B",   # Card background
    "bg":           "#0F172A",   # Page background
}

# ── Plotly theme ──────────────────────────────────────────────
PLOTLY_TEMPLATE = "plotly_dark"
CHART_COLORS = ["#10B981", "#EF4444", "#F59E0B", "#3B82F6", "#8B5CF6"]


# ════════════════════════════════════════════════════════════════
# HELPER FUNCTIONS
# ════════════════════════════════════════════════════════════════

def get_db():
    """Get a database instance. Returns None if unavailable."""
    try:
        db = PPEDatabase(db_path=DB_PATH)
        db.initialize_database()
        return db
    except Exception as e:
        st.error(f"❌ Database unavailable: {e}")
        return None


def mask_uid(uid):
    """Partially mask an RFID UID for display. E.g. '69 A1 ** **'."""
    if not uid or len(uid) < 8:
        return uid or "N/A"
    parts = uid.split(" ")
    if len(parts) >= 4:
        return f"{parts[0]} {parts[1]} ** **"
    return uid[:5] + "***"


def status_badge(status, kind="ppe"):
    """Return a styled status badge HTML string."""
    if kind == "ppe":
        badge_map = {
            "helmet_on":          ("✅ HELMET ON",       COLORS["success"]),
            "helmet_off":         ("❌ NO HELMET",       COLORS["danger"]),
            "no_person":          ("👤 NO PERSON",       COLORS["warning"]),
            "verification_error": ("⚠️ ERROR",           "#6B7280"),
            None:                 ("⏳ PENDING",         COLORS["warning"]),
        }
    else:  # access
        badge_map = {
            "AUTHORIZED": ("🟢 AUTHORIZED", COLORS["success"]),
            "DENIED":     ("🔴 DENIED",     COLORS["danger"]),
        }
    label, color = badge_map.get(status, (str(status), "#6B7280"))
    return f'<span style="background:{color};color:white;padding:2px 8px;'\
           f'border-radius:4px;font-size:0.85em;font-weight:600;">{label}</span>'


def format_timestamp(ts):
    """Format an ISO timestamp for display."""
    if not ts:
        return "N/A"
    try:
        dt = datetime.fromisoformat(ts)
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return ts


# ════════════════════════════════════════════════════════════════
# PAGE CONFIG AND STYLING
# ════════════════════════════════════════════════════════════════

st.set_page_config(
    page_title="Smart PPE Monitoring Dashboard",
    page_icon="🏭",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS for industrial dark theme
st.markdown(f"""
<style>
    /* Main background */
    .stApp {{
        background-color: {COLORS["bg"]};
    }}

    /* Sidebar */
    section[data-testid="stSidebar"] {{
        background-color: {COLORS["primary"]};
    }}
    section[data-testid="stSidebar"] .stMarkdown p,
    section[data-testid="stSidebar"] .stMarkdown h1,
    section[data-testid="stSidebar"] .stMarkdown h2,
    section[data-testid="stSidebar"] .stMarkdown h3 {{
        color: {COLORS["text"]};
    }}

    /* Metric cards */
    div[data-testid="stMetric"] {{
        background-color: {COLORS["card_bg"]};
        border: 1px solid #334155;
        border-radius: 12px;
        padding: 16px;
        box-shadow: 0 4px 6px -1px rgba(0,0,0,0.3);
    }}
    div[data-testid="stMetric"] label {{
        color: #94A3B8 !important;
        font-weight: 500;
    }}
    div[data-testid="stMetric"] [data-testid="stMetricValue"] {{
        color: {COLORS["text"]} !important;
        font-weight: 700;
    }}

    /* Headers */
    .main-header {{
        background: linear-gradient(135deg, {COLORS["primary"]}, {COLORS["secondary"]});
        padding: 20px 30px;
        border-radius: 12px;
        margin-bottom: 24px;
        border: 1px solid #334155;
    }}
    .main-header h1 {{
        color: white;
        margin: 0;
        font-size: 1.8rem;
    }}
    .main-header p {{
        color: #94A3B8;
        margin: 4px 0 0 0;
        font-size: 0.95rem;
    }}

    /* Section headers */
    .section-header {{
        color: {COLORS["text"]};
        border-bottom: 2px solid {COLORS["secondary"]};
        padding-bottom: 8px;
        margin-top: 16px;
        margin-bottom: 12px;
    }}

    /* Tables */
    .dataframe {{
        font-size: 0.85rem;
    }}

    /* Tabs */
    .stTabs [data-baseweb="tab"] {{
        color: #94A3B8;
    }}
    .stTabs [aria-selected="true"] {{
        color: {COLORS["info"]} !important;
        border-bottom-color: {COLORS["info"]} !important;
    }}

    /* Success/warning/error boxes */
    .success-box {{
        background-color: rgba(16,185,129,0.1);
        border: 1px solid {COLORS["success"]};
        border-radius: 8px;
        padding: 12px 16px;
        color: {COLORS["success"]};
    }}
    .warning-box {{
        background-color: rgba(245,158,11,0.1);
        border: 1px solid {COLORS["warning"]};
        border-radius: 8px;
        padding: 12px 16px;
        color: {COLORS["warning"]};
    }}
    .error-box {{
        background-color: rgba(239,68,68,0.1);
        border: 1px solid {COLORS["danger"]};
        border-radius: 8px;
        padding: 12px 16px;
        color: {COLORS["danger"]};
    }}

    /* Hide streamlit branding */
    #MainMenu {{visibility: hidden;}}
    footer {{visibility: hidden;}}
</style>
""", unsafe_allow_html=True)


# ════════════════════════════════════════════════════════════════
# SIDEBAR NAVIGATION
# ════════════════════════════════════════════════════════════════

with st.sidebar:
    st.markdown("## 🏭 PPE Monitor")
    st.markdown("---")

    page = st.radio(
        "Navigation",
        ["📊 Overview", "📋 Scan History", "🚨 Violations",
         "👷 Workers", "📄 Reports"],
        label_visibility="collapsed"
    )

    st.markdown("---")

    # Auto-refresh control
    auto_refresh = st.checkbox("Auto-refresh", value=False)
    if auto_refresh:
        refresh_interval = st.slider("Interval (seconds)", 10, 60, 30)
        st.caption(f"Auto-refreshing every {refresh_interval}s")
        # Use HTML meta refresh for non-blocking auto-refresh
        st.markdown(
            f'<meta http-equiv="refresh" content="{refresh_interval}">',
            unsafe_allow_html=True
        )

    if st.button("🔄 Refresh Now", use_container_width=True):
        st.rerun()

    st.markdown("---")
    st.caption("Smart PPE Monitoring System")
    st.caption(f"Database: {DB_PATH.name}")
    st.caption(f"Last refresh: {datetime.now().strftime('%H:%M:%S')}")


# ════════════════════════════════════════════════════════════════
# DATABASE CONNECTION
# ════════════════════════════════════════════════════════════════

db = get_db()
if db is None:
    st.error("❌ Cannot connect to database. Please ensure the database "
             "file exists and the integration script has been run at least once.")
    st.info(f"Expected database path: `{DB_PATH}`")
    st.stop()


# ════════════════════════════════════════════════════════════════
# PAGE: OVERVIEW
# ════════════════════════════════════════════════════════════════

if page == "📊 Overview":
    st.markdown("""
    <div class="main-header">
        <h1>🏭 Smart PPE Compliance Dashboard</h1>
        <p>AI-Based Smart PPE Compliance Monitoring System — Real-time Overview</p>
    </div>
    """, unsafe_allow_html=True)

    summary = db.get_compliance_summary()

    # ── KPI Cards Row 1 ──
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.metric("Total Scans", summary["total_scans"])
    with c2:
        st.metric("Authorized", summary["authorized_scans"])
    with c3:
        st.metric("Denied", summary["denied_scans"])
    with c4:
        pct = summary["compliance_percentage"]
        st.metric("Compliance %", f"{pct}%",
                   delta="Good" if pct >= 80 else ("Low" if pct > 0 else None),
                   delta_color="normal" if pct >= 80 else "inverse")

    # ── KPI Cards Row 2 ──
    c5, c6, c7, c8 = st.columns(4)
    with c5:
        st.metric("🟢 Helmet On", summary["helmet_on_count"])
    with c6:
        st.metric("🔴 Helmet Off", summary["helmet_off_count"])
    with c7:
        st.metric("👤 No Person", summary["no_person_count"])
    with c8:
        st.metric("⚠️ Failures", summary["verification_failures"])

    st.markdown("---")

    # ── Charts ──
    col_left, col_right = st.columns(2)

    with col_left:
        st.markdown('<h3 class="section-header">📈 Daily Compliance Trend</h3>',
                    unsafe_allow_html=True)
        daily = db.get_daily_compliance(days=30)
        if daily:
            df_daily = pd.DataFrame(daily)
            fig = px.line(
                df_daily, x="date", y="compliance_pct",
                markers=True,
                labels={"date": "Date", "compliance_pct": "Compliance %"},
                template=PLOTLY_TEMPLATE,
                color_discrete_sequence=[COLORS["success"]]
            )
            fig.update_layout(
                yaxis_range=[0, 105],
                height=350,
                margin=dict(l=20, r=20, t=20, b=20),
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
            )
            fig.add_hline(y=80, line_dash="dash", line_color=COLORS["warning"],
                          annotation_text="80% Target")
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("📭 No compliance data available yet. "
                    "Run the PPE integration script to generate scan records.")

    with col_right:
        st.markdown('<h3 class="section-header">🪖 PPE Status Distribution</h3>',
                    unsafe_allow_html=True)
        helmet_on = summary["helmet_on_count"]
        helmet_off = summary["helmet_off_count"]
        if helmet_on > 0 or helmet_off > 0:
            fig_pie = go.Figure(data=[go.Pie(
                labels=["Helmet On", "Helmet Off"],
                values=[helmet_on, helmet_off],
                marker=dict(colors=[COLORS["success"], COLORS["danger"]]),
                hole=0.45,
                textinfo="label+percent",
                textfont=dict(color="white", size=13),
            )])
            fig_pie.update_layout(
                height=350,
                margin=dict(l=20, r=20, t=20, b=20),
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                legend=dict(font=dict(color=COLORS["text"])),
                showlegend=True
            )
            st.plotly_chart(fig_pie, use_container_width=True)
        else:
            st.info("📭 No helmet detection results yet.")

    # ── Access Distribution & Recent Scans ──
    col_a, col_b = st.columns(2)

    with col_a:
        st.markdown('<h3 class="section-header">🔐 Access Distribution</h3>',
                    unsafe_allow_html=True)
        dist = db.get_access_distribution()
        if dist["authorized"] > 0 or dist["denied"] > 0:
            fig_access = go.Figure(data=[go.Bar(
                x=["Authorized", "Denied"],
                y=[dist["authorized"], dist["denied"]],
                marker_color=[COLORS["success"], COLORS["danger"]],
                text=[dist["authorized"], dist["denied"]],
                textposition="outside",
                textfont=dict(color=COLORS["text"]),
            )])
            fig_access.update_layout(
                height=300,
                margin=dict(l=20, r=20, t=20, b=20),
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                xaxis=dict(color=COLORS["text"]),
                yaxis=dict(color=COLORS["text"]),
            )
            st.plotly_chart(fig_access, use_container_width=True)
        else:
            st.info("📭 No access records yet.")

    with col_b:
        st.markdown('<h3 class="section-header">🕐 Recent Activity</h3>',
                    unsafe_allow_html=True)
        recent = db.get_recent_scans(limit=8)
        if recent:
            for scan in recent:
                ts = format_timestamp(scan.get("timestamp"))
                name = scan.get("worker_name")
                if not name or name == "Unknown":
                    # Show actual RFID UID for unregistered cards
                    name = scan.get("rfid_uid") or "Unknown"
                access = scan.get("access_status", "")
                ppe = scan.get("ppe_status")
                icon = "🟢" if access == "AUTHORIZED" else "🔴"
                if access == "DENIED":
                    ppe_icon = "🔴"
                    ppe_label = "Access Denied"
                else:
                    ppe_icon = {"helmet_on": "✅", "helmet_off": "❌",
                                "no_person": "👤",
                                "verification_error": "⚠️"}.get(ppe, "⏳")
                    ppe_label = ppe or "pending"
                st.markdown(
                    f"**{icon} {name}** — {ppe_icon} {ppe_label} "
                    f"<small style='color:#64748B'>{ts}</small>",
                    unsafe_allow_html=True
                )
        else:
            st.info("📭 No scan activity yet. Scan an RFID card to begin.")


# ════════════════════════════════════════════════════════════════
# PAGE: SCAN HISTORY
# ════════════════════════════════════════════════════════════════

elif page == "📋 Scan History":
    st.markdown("""
    <div class="main-header">
        <h1>📋 Scan History</h1>
        <p>Browse and filter all PPE scan records</p>
    </div>
    """, unsafe_allow_html=True)

    # ── Filters ──
    with st.expander("🔍 Filters", expanded=True):
        fc1, fc2, fc3, fc4 = st.columns(4)
        with fc1:
            date_from = st.date_input("From Date",
                                       value=datetime.now() - timedelta(days=30),
                                       key="hist_from")
        with fc2:
            date_to = st.date_input("To Date",
                                     value=datetime.now(),
                                     key="hist_to")
        with fc3:
            ppe_filter = st.selectbox("PPE Status",
                                       ["All", "helmet_on", "helmet_off",
                                        "no_person", "verification_error"],
                                       key="hist_ppe")
        with fc4:
            access_filter = st.selectbox("Access Status",
                                          ["All", "AUTHORIZED", "DENIED"],
                                          key="hist_access")

        fc5, fc6 = st.columns(2)
        with fc5:
            worker_filter = st.text_input("Worker Name", key="hist_worker")
        with fc6:
            depts = db.get_departments()
            dept_filter = st.selectbox("Department",
                                        ["All"] + depts,
                                        key="hist_dept")

    # Build filter params
    params = {
        "date_from": date_from.isoformat() if date_from else None,
        "date_to": (date_to + timedelta(days=1)).isoformat() if date_to else None,
        "ppe_status": ppe_filter if ppe_filter != "All" else None,
        "access_status": access_filter if access_filter != "All" else None,
        "worker_name": worker_filter if worker_filter else None,
        "department": dept_filter if dept_filter != "All" else None,
    }

    scans = db.get_recent_scans(limit=200, **params)

    st.markdown(f"**{len(scans)}** records found")

    if scans:
        rows = []
        for s in scans:
            rows.append({
                "Timestamp": format_timestamp(s.get("timestamp")),
                "Worker": s.get("worker_name") if s.get("worker_name") and s.get("worker_name") != "Unknown" else s.get("rfid_uid", "Unknown"),
                "RFID UID": mask_uid(s.get("rfid_uid")),
                "Department": s.get("department") or "N/A",
                "Access": s.get("access_status", ""),
                "PPE Status": s.get("ppe_status") or "—",
                "Verification": s.get("verification_status", ""),
                "Attempts": s.get("attempts", 0),
            })
        df = pd.DataFrame(rows)

        # Color-coded display
        def highlight_row(row):
            if row["Access"] == "DENIED":
                return ["background-color: rgba(239,68,68,0.08)"] * len(row)
            if row["PPE Status"] == "helmet_off":
                return ["background-color: rgba(239,68,68,0.08)"] * len(row)
            if row["PPE Status"] == "helmet_on":
                return ["background-color: rgba(16,185,129,0.08)"] * len(row)
            return [""] * len(row)

        styled = df.style.apply(highlight_row, axis=1)
        st.dataframe(styled, use_container_width=True, height=500)
    else:
        st.info("📭 No scan records match the current filters.")


# ════════════════════════════════════════════════════════════════
# PAGE: VIOLATIONS
# ════════════════════════════════════════════════════════════════

elif page == "🚨 Violations":
    st.markdown("""
    <div class="main-header">
        <h1>🚨 PPE Violations</h1>
        <p>Helmet-off incidents requiring attention</p>
    </div>
    """, unsafe_allow_html=True)

    # ── Filters ──
    with st.expander("🔍 Filters", expanded=False):
        vc1, vc2, vc3, vc4 = st.columns(4)
        with vc1:
            v_date_from = st.date_input("From",
                                         value=datetime.now() - timedelta(days=30),
                                         key="viol_from")
        with vc2:
            v_date_to = st.date_input("To",
                                       value=datetime.now(),
                                       key="viol_to")
        with vc3:
            v_worker = st.text_input("Worker", key="viol_worker")
        with vc4:
            v_depts = db.get_departments()
            v_dept = st.selectbox("Department",
                                   ["All"] + v_depts,
                                   key="viol_dept")

    v_params = {
        "date_from": v_date_from.isoformat() if v_date_from else None,
        "date_to": (v_date_to + timedelta(days=1)).isoformat() if v_date_to else None,
        "worker_name": v_worker if v_worker else None,
        "department": v_dept if v_dept != "All" else None,
    }

    violations = db.get_violation_records(limit=200, **v_params)
    by_worker = db.get_violations_by_worker(**v_params)

    # ── Summary cards ──
    total_violations = len(violations)
    unique_workers = len(by_worker)

    mc1, mc2, mc3 = st.columns(3)
    with mc1:
        st.metric("Total Violations", total_violations)
    with mc2:
        st.metric("Workers Involved", unique_workers)
    with mc3:
        if by_worker:
            worst = by_worker[0]
            st.metric("Most Violations",
                       f"{worst['worker_name']} ({worst['violation_count']})")
        else:
            st.metric("Most Violations", "N/A")

    st.markdown("---")

    col_v1, col_v2 = st.columns(2)

    with col_v1:
        st.markdown('<h3 class="section-header">📊 Violations by Worker</h3>',
                    unsafe_allow_html=True)
        if by_worker:
            df_workers = pd.DataFrame(by_worker)
            fig_vw = px.bar(
                df_workers, x="worker_name", y="violation_count",
                color="violation_count",
                color_continuous_scale=["#FCA5A5", "#EF4444", "#991B1B"],
                labels={"worker_name": "Worker", "violation_count": "Violations"},
                template=PLOTLY_TEMPLATE,
            )
            fig_vw.update_layout(
                height=350,
                margin=dict(l=20, r=20, t=20, b=20),
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                showlegend=False,
            )
            st.plotly_chart(fig_vw, use_container_width=True)
        else:
            st.info("📭 No violations recorded.")

    with col_v2:
        st.markdown('<h3 class="section-header">📈 Daily Violation Trend</h3>',
                    unsafe_allow_html=True)
        daily_v = db.get_daily_violations(**v_params)
        if daily_v:
            df_dv = pd.DataFrame(daily_v)
            fig_dv = px.line(
                df_dv, x="date", y="violation_count",
                markers=True,
                labels={"date": "Date", "violation_count": "Violations"},
                template=PLOTLY_TEMPLATE,
                color_discrete_sequence=[COLORS["danger"]]
            )
            fig_dv.update_layout(
                height=350,
                margin=dict(l=20, r=20, t=20, b=20),
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
            )
            st.plotly_chart(fig_dv, use_container_width=True)
        else:
            st.info("📭 No daily violation data.")

    # ── Violation detail table ──
    st.markdown('<h3 class="section-header">📋 Violation Records</h3>',
                unsafe_allow_html=True)
    if violations:
        v_rows = []
        for v in violations:
            v_rows.append({
                "Timestamp": format_timestamp(v.get("timestamp")),
                "Worker": v.get("worker_name") if v.get("worker_name") and v.get("worker_name") != "Unknown" else v.get("rfid_uid", "Unknown"),
                "RFID UID": mask_uid(v.get("rfid_uid")),
                "Department": v.get("department") or "N/A",
                "Attempts": v.get("attempts", 0),
            })
        df_v = pd.DataFrame(v_rows)
        st.dataframe(df_v, use_container_width=True, height=400)
    else:
        st.success("✅ No PPE violations found for the selected period. "
                    "Great compliance!")


# ════════════════════════════════════════════════════════════════
# PAGE: WORKER MANAGEMENT
# ════════════════════════════════════════════════════════════════

elif page == "👷 Workers":
    st.markdown("""
    <div class="main-header">
        <h1>👷 Worker Management</h1>
        <p>Register, view, and manage worker RFID cards</p>
    </div>
    """, unsafe_allow_html=True)

    tab_list, tab_register, tab_edit = st.tabs(
        ["📋 Worker List", "➕ Register Worker", "✏️ Edit Worker"]
    )

    with tab_list:
        workers = db.get_all_workers()
        if workers:
            w_rows = []
            for w in workers:
                w_rows.append({
                    "ID": w["worker_id"],
                    "Name": w["worker_name"],
                    "RFID UID": w["rfid_uid"],
                    "Department": w.get("department") or "N/A",
                    "Status": "🟢 Active" if w["is_active"] else "🔴 Inactive",
                    "Registered": format_timestamp(w.get("created_at")),
                })
            df_w = pd.DataFrame(w_rows)

            def highlight_inactive(row):
                if "Inactive" in row["Status"]:
                    return ["background-color: rgba(239,68,68,0.08)"] * len(row)
                return ["background-color: rgba(16,185,129,0.05)"] * len(row)

            styled_w = df_w.style.apply(highlight_inactive, axis=1)
            st.dataframe(styled_w, use_container_width=True, height=400)
            st.caption(f"Total workers: {len(workers)}")
        else:
            st.info("📭 No workers registered yet. Use the 'Register Worker' "
                    "tab to add workers.")

    with tab_register:
        st.markdown("#### Register New Worker")

        with st.form("register_worker_form", clear_on_submit=True):
            reg_uid = st.text_input(
                "RFID Card UID *",
                placeholder="e.g. 69 A1 0D 07",
                help="The UID from the RFID card. Use space-separated hex format."
            )
            reg_name = st.text_input(
                "Worker Name *",
                placeholder="e.g. Aryan Salunke"
            )
            reg_dept = st.text_input(
                "Department",
                placeholder="e.g. Safety, Operations, Maintenance"
            )
            submitted = st.form_submit_button(
                "Register Worker", use_container_width=True
            )

            if submitted:
                if not reg_uid or not reg_name:
                    st.error("❌ RFID UID and Worker Name are required.")
                else:
                    result = db.register_worker(
                        reg_uid.strip(), reg_name.strip(),
                        reg_dept.strip() if reg_dept else None
                    )
                    if result["success"]:
                        st.success(f"✅ {result['message']}")
                        st.balloons()
                    else:
                        st.error(f"❌ {result['message']}")

    with tab_edit:
        st.markdown("#### Edit Worker Details")

        workers = db.get_all_workers()
        if not workers:
            st.info("📭 No workers to edit.")
        else:
            worker_options = {
                f"{w['worker_name']} (UID: {w['rfid_uid']})": w
                for w in workers
            }
            selected = st.selectbox("Select Worker", list(worker_options.keys()),
                                     key="edit_worker_select")
            worker = worker_options[selected]

            with st.form("edit_worker_form"):
                edit_name = st.text_input("Worker Name",
                                           value=worker["worker_name"])
                edit_dept = st.text_input("Department",
                                           value=worker.get("department") or "")

                col_save, col_toggle = st.columns(2)
                with col_save:
                    save = st.form_submit_button("💾 Save Changes",
                                                  use_container_width=True)
                with col_toggle:
                    if worker["is_active"]:
                        deact = st.form_submit_button(
                            "🔴 Deactivate Worker",
                            use_container_width=True
                        )
                    else:
                        deact = st.form_submit_button(
                            "🟢 Activate Worker",
                            use_container_width=True
                        )

                if save:
                    result = db.update_worker(
                        worker["worker_id"],
                        worker_name=edit_name if edit_name != worker["worker_name"] else None,
                        department=edit_dept if edit_dept != (worker.get("department") or "") else None
                    )
                    if result["success"]:
                        st.success(f"✅ {result['message']}")
                    else:
                        st.warning(f"⚠️ {result['message']}")

                if deact:
                    if worker["is_active"]:
                        # Deactivate
                        confirm = True  # Streamlit form submit is the confirmation
                        if confirm:
                            r = db.deactivate_worker(worker["worker_id"])
                            if r["success"]:
                                st.success(
                                    f"✅ Worker '{worker['worker_name']}' "
                                    f"deactivated. Historical scans are preserved."
                                )
                            else:
                                st.error(f"❌ {r['message']}")
                    else:
                        r = db.activate_worker(worker["worker_id"])
                        if r["success"]:
                            st.success(
                                f"✅ Worker '{worker['worker_name']}' activated."
                            )
                        else:
                            st.error(f"❌ {r['message']}")


# ════════════════════════════════════════════════════════════════
# PAGE: REPORTS
# ════════════════════════════════════════════════════════════════

elif page == "📄 Reports":
    st.markdown("""
    <div class="main-header">
        <h1>📄 Reports & Export</h1>
        <p>Generate and download compliance reports</p>
    </div>
    """, unsafe_allow_html=True)

    # ── Date range selection ──
    rc1, rc2 = st.columns(2)
    with rc1:
        r_from = st.date_input("From Date",
                                value=datetime.now() - timedelta(days=30),
                                key="report_from")
    with rc2:
        r_to = st.date_input("To Date",
                              value=datetime.now(),
                              key="report_to")

    r_date_from = r_from.isoformat() if r_from else None
    r_date_to = (r_to + timedelta(days=1)).isoformat() if r_to else None

    # ── Summary metrics for the period ──
    summary = db.get_compliance_summary(date_from=r_date_from,
                                         date_to=r_date_to)

    st.markdown('<h3 class="section-header">📊 Period Summary</h3>',
                unsafe_allow_html=True)

    m1, m2, m3, m4 = st.columns(4)
    with m1:
        st.metric("Total Scans", summary["total_scans"])
    with m2:
        st.metric("Compliance", f"{summary['compliance_percentage']}%")
    with m3:
        st.metric("Helmet On", summary["helmet_on_count"])
    with m4:
        st.metric("Violations", summary["helmet_off_count"])

    st.markdown("---")

    # ── CSV Export ──
    st.markdown('<h3 class="section-header">📥 Download Scan Data (CSV)</h3>',
                unsafe_allow_html=True)

    export_data = db.get_all_scans_for_export(
        date_from=r_date_from, date_to=r_date_to
    )

    if export_data:
        df_export = pd.DataFrame(export_data)
        csv_buffer = io.StringIO()
        df_export.to_csv(csv_buffer, index=False)
        csv_str = csv_buffer.getvalue()

        st.download_button(
            label=f"📥 Download CSV ({len(export_data)} records)",
            data=csv_str,
            file_name=f"ppe_scan_report_{r_from}_{r_to}.csv",
            mime="text/csv",
            use_container_width=True,
        )

        st.markdown("**Preview:**")
        st.dataframe(df_export.head(20), use_container_width=True)
    else:
        st.info("📭 No scan data available for the selected period.")

    st.markdown("---")

    # ── Period compliance breakdown ──
    st.markdown('<h3 class="section-header">📊 Compliance Breakdown</h3>',
                unsafe_allow_html=True)

    if summary["total_scans"] > 0:
        breakdown_data = {
            "Category": ["Helmet On", "Helmet Off", "No Person",
                         "Verification Error", "Denied"],
            "Count": [
                summary["helmet_on_count"],
                summary["helmet_off_count"],
                summary["no_person_count"],
                summary["verification_failures"],
                summary["denied_scans"]
            ],
            "Color": [COLORS["success"], COLORS["danger"], COLORS["warning"],
                       "#6B7280", "#6B7280"]
        }
        df_breakdown = pd.DataFrame(breakdown_data)
        fig_bd = px.bar(
            df_breakdown, x="Category", y="Count",
            color="Category",
            color_discrete_map={
                "Helmet On": COLORS["success"],
                "Helmet Off": COLORS["danger"],
                "No Person": COLORS["warning"],
                "Verification Error": "#6B7280",
                "Denied": "#475569"
            },
            template=PLOTLY_TEMPLATE,
        )
        fig_bd.update_layout(
            height=350,
            margin=dict(l=20, r=20, t=20, b=20),
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            showlegend=False,
        )
        st.plotly_chart(fig_bd, use_container_width=True)
    else:
        st.info("📭 No data for the selected period.")
