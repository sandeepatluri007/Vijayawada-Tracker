"""
Smart Meter Field Tracker + Smart Planner Suite
=================================================
Backend : streamlit-gsheets-connection  (Google Sheets)
Theme   : Clean White & Light Greys (Field-Optimized)
Security: PIN Protected
"""

import streamlit as st
import streamlit.components.v1 as components
from streamlit_gsheets import GSheetsConnection
import pandas as pd
from datetime import date
import urllib.parse
import math
import time
import io
import base64
import re
from PIL import Image

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Field Meter Tracker & Optimization",
    page_icon="⚡",
    layout="centered",
    initial_sidebar_state="collapsed",
)

# ── CSS – Clean Light Theme ──────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Rajdhani:wght=500;600;700&family=Inter:wght=400;500;600&display=swap');

html, body, [class*="css"] { font-family: 'Inter', sans-serif; }
.stApp { background:#f8f9fa; color:#1e293b; }
#MainMenu, footer, header { visibility:hidden; }

/* ── top banner ── */
.top-banner {
    background: #ffffff;
    border: 1px solid #e2e8f0;
    border-radius: 10px;
    padding: 12px 16px;
    display:flex; align-items:center; gap:10px;
    box-shadow: 0 1px 3px rgba(0,0,0,0.05);
}
.top-banner .t { font-family:'Rajdhani',sans-serif; font-size:1.45rem;
    font-weight:700; color:#0f172a; letter-spacing:.6px; margin:0; }
.top-banner .s { font-size:.75rem; color:#64748b; margin:0; font-weight:500; }

/* ── tabs ── */
.stTabs [data-baseweb="tab-list"] {
    background:#e2e8f0; border-radius:10px; padding:4px; gap:4px;
    overflow-x:auto; white-space:nowrap;
}
.stTabs [data-baseweb="tab"] {
    border-radius:8px !important; padding:8px 13px !important;
    font-family:'Rajdhani',sans-serif; font-size:.88rem !important;
    font-weight:700 !important; color:#64748b !important;
    background:transparent !important; border:none !important;
    min-width:auto !important; flex-shrink:0;
}
.stTabs [aria-selected="true"] { 
    background:#ffffff !important; 
    color:#0f172a !important; 
    box-shadow: 0 1px 2px rgba(0,0,0,0.05);
}

/* ── metric cards ── */
[data-testid="stMetric"] {
    background: #ffffff;
    border: 1px solid #e2e8f0; border-radius:12px;
    padding: 14px 12px !important;
    box-shadow: 0 1px 2px rgba(0,0,0,0.02);
}
[data-testid="stMetricLabel"]  { color:#64748b !important; font-size:.75rem !important; text-transform:uppercase; letter-spacing:.6px; font-weight:600; }
[data-testid="stMetricValue"]  { font-family:'Rajdhani',sans-serif; font-size:1.9rem !important; font-weight:700; color:#0f172a !important; }
[data-testid="stMetricDelta"]  { font-size:.75rem !important; }

/* ── section headers ── */
.sec-hdr {
    font-family:'Rajdhani',sans-serif; font-size:1.15rem; font-weight:700;
    color:#334155; border-left:4px solid #cbd5e1; padding-left:10px;
    margin: 1.5rem 0 1rem;
}

/* ── buttons ── */
.stButton>button {
    background:#ffffff !important; color:#334155 !important;
    border:1px solid #cbd5e1 !important; border-radius:8px !important;
    font-family:'Rajdhani',sans-serif !important; font-weight:700 !important;
    font-size:.95rem !important; padding:9px 18px !important;
    width:100% !important; transition:all .2s;
    box-shadow: 0 1px 2px rgba(0,0,0,0.03);
}
.stButton>button:hover { background:#f1f5f9 !important; border-color:#94a3b8 !important; }

/* Primary CTA Override */
button[data-testid="baseButton-primary"], .stButton>button[type="primary"] {
    background:#0f172a !important; color:#ffffff !important; border-color:#0f172a !important;
}
button[data-testid="baseButton-primary"]:hover {
    background:#334155 !important; border-color:#334155 !important;
}

/* ── inputs ── */
.stSelectbox>div>div, .stNumberInput>div>div>input,
.stTextInput>div>div>input, .stDateInput>div>div>input, .stMultiSelect>div>div {
    background:#ffffff !important; border:1px solid #cbd5e1 !important;
    border-radius:8px !important; color:#0f172a !important; font-size:.9rem !important;
}
.stSelectbox label, .stNumberInput label, .stTextInput label,
.stDateInput label, .stMultiSelect label {
    color:#475569 !important; font-size:.85rem !important; font-weight:600 !important;
}

/* ── forms ── */
.stForm { background:#ffffff !important; border:1px solid #e2e8f0 !important;
    border-radius:12px !important; padding:16px !important; box-shadow: 0 1px 3px rgba(0,0,0,0.02); }

/* ── dataframe ── */
.stDataFrame { border-radius:10px; border: 1px solid #e2e8f0; overflow:hidden; }
[data-testid="stDataFrameResizable"] th {
    background:#f1f5f9 !important; color:#334155 !important;
    font-family:'Rajdhani',sans-serif; font-weight:700 !important; font-size:.85rem !important;
    border-bottom: 2px solid #e2e8f0 !important;
}
[data-testid="stDataFrameResizable"] td { color:#1e293b !important; font-size:.85rem !important; background:#ffffff !important; border-bottom:1px solid #f1f5f9 !important; }

/* ── warning / danger ── */
.warn-box {
    background:#fffbeb; border:1px solid #fcd34d; border-radius:9px;
    padding:10px 14px; color:#92400e; font-size:.85rem; margin-bottom:.8rem; font-weight:500;
}

/* ── whatsapp button ── */
.wa-btn {
    display:block; text-align:center; background:#10b981; color:#fff !important;
    padding:12px; border-radius:9px; text-decoration:none; font-weight:700;
    font-family:'Rajdhani',sans-serif; font-size:1.05rem; letter-spacing:.5px;
    margin-top:1rem; transition: background 0.2s;
}
.wa-btn:hover { background:#059669; }

hr { border-color:#e2e8f0; }

@media (max-width:600px){
    .top-banner .t { font-size:1.15rem; }
    [data-testid="stMetricValue"] { font-size:1.55rem !important; }
    .stTabs [data-baseweb="tab"] { padding:6px 9px !important; font-size:.8rem !important; }
}
</style>
""", unsafe_allow_html=True)

# ── Top banner & Refresh Button ───────────────────────────────────────────────
head_col1, head_col2 = st.columns([3.5, 1.2])
with head_col1:
    st.markdown("""
    <div class="top-banner">
      <span style="font-size:1.8rem;">⚡</span>
      <div>
        <p class="t">METER TRACKER</p>
        <p class="s">Vijayawada Field Ops</p>
      </div>
    </div>
    """, unsafe_allow_html=True)
with head_col2:
    st.write("") 
    if st.button("🔄 Refresh"):
        st.cache_data.clear()
        st.rerun()

st.write("") 

# ── Authentication / PIN Protection ───────────────────────────────────────────
if "authenticated" not in st.session_state:
    st.session_state["authenticated"] = False

if not st.session_state["authenticated"]:
    st.markdown('<div class="sec-hdr">🔒 Supervisor Login</div>', unsafe_allow_html=True)
    with st.form("login_form"):
        st.info("Please enter the daily operations PIN to access the system.")
        pin_entry = st.text_input("Enter PIN", type="password")
        if st.form_submit_button("Unlock Tracker", type="primary"):
            if pin_entry == "2333": 
                st.session_state["authenticated"] = True
                st.success("Access Granted!")
                st.rerun()
            else:
                st.error("❌ Incorrect PIN. Access Denied.")
    st.stop() 

# ── Google Sheets connection ──────────────────────────────────────────────────
conn = st.connection("gsheets", type=GSheetsConnection)

# ── Helpers ───────────────────────────────────────────────────────────────────
def get_data(worksheet: str, retries=3) -> pd.DataFrame:
    for attempt in range(retries):
        try:
            df = conn.read(worksheet=worksheet, ttl=5)
            return df.astype(str).fillna("") if not df.empty else pd.DataFrame()
        except:
            if attempt < retries - 1:
                time.sleep(1)
            else:
                st.toast(f"📡 Weak connection. Having trouble loading {worksheet}...", icon="⚠️")
                return pd.DataFrame()

def safe_int(val, default: int = 0) -> int:
    try: return int(float(val))
    except: return default

def safe_numeric_col(df: pd.DataFrame, col: str) -> pd.Series:
    return pd.to_numeric(df[col], errors="coerce").fillna(0)

def has_col(df: pd.DataFrame, *cols) -> bool:
    return all(c in df.columns for c in cols)

# ── Safe Extraction of Query Dictionary Parameters ──────────────────────────
query_dict = st.query_params.to_dict()
captured_lat = query_dict.get("lat", "")
captured_lng = query_dict.get("lng", "")

# ── Tabs Configuration ─────────────────────────────────────────────────────────
tab_dash, tab_survey, tab_planner, tab_inst, tab_inv, tab_admin = st.tabs([
    "📊 Dashboard", "🏍️ Survey Session", "🗂️ Work Planner", "🛠️ Installs", "📦 Store", "⚙️ Admin"
])

# ═══════════════════════════════════════════════════════════════════════════════
#  DASHBOARD
# ═══════════════════════════════════════════════════════════════════════════════
with tab_dash:
    df_inst = get_data("Installations")
    df_inv  = get_data("Inventory")

    st.markdown('<div class="sec-hdr">📦 Live Inventory Stock</div>', unsafe_allow_html=True)

    if not df_inv.empty and has_col(df_inv, "type", "qty"):
        total_in_1ph = safe_numeric_col(df_inv[df_inv["type"] == "1 PH"], "qty").sum()
        total_in_3ph = safe_numeric_col(df_inv[df_inv["type"] == "3 PH"], "qty").sum()
    else:
        total_in_1ph = total_in_3ph = 0

    if not df_inst.empty and has_col(df_inst, "qty_1ph", "qty_3ph"):
        total_out_1ph = safe_numeric_col(df_inst, "qty_1ph").sum()
        total_out_3ph = safe_numeric_col(df_inst, "qty_3ph").sum()
    else:
        total_out_1ph = total_out_3ph = 0

    pending_1ph = int(total_in_1ph - total_out_1ph)
    pending_3ph = int(total_in_3ph - total_out_3ph)

    sc1, sc2, sc3, sc4 = st.columns(4)
    sc1.metric("Received 1PH",  int(total_in_1ph))
    sc2.metric("Received 3PH",  int(total_in_3ph))
    sc3.metric("Pending 1PH",   pending_1ph, delta="⚠️ Deficit!" if pending_1ph < 0 else None, delta_color="inverse")
    sc4.metric("Pending 3PH",   pending_3ph, delta="⚠️ Deficit!" if pending_3ph < 0 else None, delta_color="inverse")

    st.divider()
    st.markdown('<div class="sec-hdr">🔌 Installation Summary</div>', unsafe_allow_html=True)

    if df_inst.empty or not has_col(df_inst, "date", "tech_name", "location", "qty_1ph", "qty_3ph"):
        st.info("No installation data yet. Add entries in the Installations tab.")
    else:
        f1, f2 = st.columns(2)
        with f1: date_range = st.date_input("Date Range", [date.today(), date.today()])
        with f2: meter_filter = st.multiselect("Meter Type", ["1 PH", "3 PH"], default=["1 PH", "3 PH"])

        loc_list  = sorted([l for l in df_inst["location"].unique() if l.strip()])
        tech_list = sorted([t for t in df_inst["tech_name"].unique() if t.strip()])

        f3, f4 = st.columns(2)
        with f3: loc_filter  = st.multiselect("Locations",   loc_list,  default=loc_list)
        with f4: tech_filter = st.multiselect("Technicians", tech_list, default=tech_list)

        filtered = df_inst.copy()
        if isinstance(date_range, (list, tuple)) and len(date_range) == 2: d_start, d_end = date_range[0], date_range[1]
        elif isinstance(date_range, (list, tuple)) and len(date_range) == 1: d_start = d_end = date_range[0]
        else: d_start = d_end = date_range

        filtered["_date"] = pd.to_datetime(filtered["date"], errors="coerce").dt.date
        filtered = filtered[(filtered["_date"] >= d_start) & (filtered["_date"] <= d_end)]
        if loc_filter: filtered = filtered[filtered["location"].isin(loc_filter)]
        if tech_filter: filtered = filtered[filtered["tech_name"].isin(tech_filter)]

        filtered["qty_1ph"] = safe_numeric_col(filtered, "qty_1ph")
        filtered["qty_3ph"] = safe_numeric_col(filtered, "qty_3ph")

        show_1ph, show_3ph = "1 PH" in meter_filter, "3 PH" in meter_filter
        sum_1ph  = int(filtered["qty_1ph"].sum()) if show_1ph else 0
        sum_3ph  = int(filtered["qty_3ph"].sum()) if show_3ph else 0

        m1, m2, m3 = st.columns(3)
        m1.metric("Filtered 1PH", sum_1ph)
        m2.metric("Filtered 3PH", sum_3ph)
        m3.metric("Grand Total",  sum_1ph + sum_3ph)

        if not filtered.empty:
            st.markdown('<div class="sec-hdr">👷 Technician Breakdown</div>', unsafe_allow_html=True)
            group_df = filtered.groupby(["tech_name", "location"])[["qty_1ph", "qty_3ph"]].sum().reset_index()
            group_df["Total"] = group_df["qty_1ph"] + group_df["qty_3ph"]
            group_df.columns = ["Technician", "Location", "1PH", "3PH", "Total"]
            st.dataframe(group_df, use_container_width=True, hide_index=True)

            st.markdown('<div class="sec-hdr">📤 Export & Share</div>', unsafe_allow_html=True)
            export_df = group_df.copy()
            export_df.loc[len(export_df)] = ["---", "---", "---", "---", "---"]
            export_df.loc[len(export_df)] = ["GRAND TOTAL", "", sum_1ph, sum_3ph, sum_1ph + sum_3ph]
            export_df.loc[len(export_df)] = ["PENDING STOCK", "", pending_1ph, pending_3ph, ""]
            
            csv_data = export_df.to_csv(index=False).encode("utf-8")
            st.download_button("📥 Download CSV Report", data=csv_data, file_name="Installation_Summary.csv", mime="text/csv", use_container_width=True)

            date_str = f"{d_start} to {d_end}" if d_start != d_end else str(d_start)
            wa_loc_df = filtered.groupby("location")[["qty_1ph", "qty_3ph"]].sum().reset_index()

            wa_lines = ["DPR- Touchlight Infra", f"Date: {date_str}\n"]
            for _, row in wa_loc_df.iterrows():
                wa_lines.append(f"{row['location']}:")
                wa_lines.append(f"1PH: {int(row['qty_1ph']) if show_1ph else 0}, 3PH: {int(row['qty_3ph']) if show_3ph else 0}\n")
            wa_lines.append(f"Total 1PH: {sum_1ph} | Total 3PH: {sum_3ph} | Grand Total: {sum_1ph + sum_3ph}")
            wa_lines.append(f"Pending Stock: 1PH: {pending_1ph} | 3PH: {pending_3ph}")

            wa_text = "\n".join(wa_lines)
            wa_url  = f"https://wa.me/?text={urllib.parse.quote(wa_text)}"
            st.markdown(f'<a href="{wa_url}" target="_blank" class="wa-btn">💬 Send to WhatsApp</a>', unsafe_allow_html=True)

# ═══════════════════════════════════════════════════════════════════════════════
#  TAB: SURVEY SESSION (SPEED CAPTURE MODE FOR MOTORCYCLE RIDES)
# ═══════════════════════════════════════════════════════════════════════════════
with tab_survey:
    if "survey_active" not in st.session_state: st.session_state["survey_active"] = False
    if "session_id" not in st.session_state: st.session_state["session_id"] = ""
    if "s_lineman" not in st.session_state: st.session_state["s_lineman"] = ""
    if "s_date" not in st.session_state: st.session_state["s_date"] = ""

    if not st.session_state["survey_active"]:
        st.markdown('<div class="sec-hdr">🏁 Start Survey Route Session</div>', unsafe_allow_html=True)
        with st.form("start_session_form"):
            input_lineman = st.text_input("Active Lineman Name", placeholder="Who is driving the bike?")
            input_date = st.date_input("Survey Date", date.today())
            if st.form_submit_button("🏁 Initialize Active Session", type="primary"):
                if not input_lineman.strip(): st.error("❌ Lineman name is mandatory.")
                else:
                    st.session_state["survey_active"] = True
                    st.session_state["session_id"] = f"SESS_{int(time.time())}"
                    st.session_state["s_lineman"] = input_lineman.strip()
                    st.session_state["s_date"] = str(input_date)
                    st.rerun()
    else:
        st.markdown(f"""
        <div style="background:#f0fdf4; border:1px solid #bbf7d0; padding:14px; border-radius:10px; margin-bottom:15px;">
            <b style="color:#166534; font-family:'Rajdhani',sans-serif; font-size:1.1rem;">🟢 ROUTE SURVEY IN PROGRESS</b><br/>
            <span style="font-size:13px; color:#334155;"><b>Lineman:</b> {st.session_state['s_lineman']} | <b>Date:</b> {st.session_state['s_date']}</span>
        </div>
        """, unsafe_allow_html=True)

        js_gps_locator = """
        <script>
        function captureLiveGPS() {
            if (navigator.geolocation) {
                navigator.geolocation.getCurrentPosition(function(position) {
                    const currentUrl = new URL(window.parent.location.href);
                    currentUrl.searchParams.set('lat', position.coords.latitude);
                    currentUrl.searchParams.set('lng', position.coords.longitude);
                    window.parent.location.href = currentUrl.toString();
                }, function(error) {
                    alert("GPS Error: Ensure location permissions are active on this device.");
                }, {enableHighAccuracy: true});
            } else { alert("GPS Geolocation is not supported by this mobile browser."); }
        }
        </script>
        <button onclick="captureLiveGPS()" style="
            width: 100%; background-color: #ff4b4b; color: #ffffff; padding: 14px; border: none; 
            border-radius: 8px; font-family: 'Rajdhani', sans-serif; font-weight: 700; font-size: 16px;
            cursor: pointer; box-shadow: 0 2px 4px rgba(0,0,0,0.1); margin-bottom: 15px;
        ">📍 STEP 1: ONE-CLICK LOCK LIVE GPS</button>
        """
        components.html(js_gps_locator, height=55)

        if captured_lat and captured_lng:
            st.success(f"🎯 Coordinates Locked: {captured_lat}, {captured_lng}")
        else:
            st.warning("⚠️ GPS tracking uninitialized. Tap the button above to capture coordinate vectors.")

        st.markdown('<div class="sec-hdr">📷 STEP 2: Capture Snapshot & Save</div>', unsafe_allow_html=True)
        with st.form("quick_pin_form", clear_on_submit=True):
            field_file = st.file_uploader("Upload Snapshot (Camera/File Preview)", type=["jpg", "jpeg", "png"])
            
            with st.expander("📝 Optional Parameters (Bypass completely to save time)"):
                field_bldg = st.text_input("Custom Building Description/Reference", value="")
                col_i1, col_i2 = st.columns(2)
                with col_i1: field_q1 = st.number_input("Est 1 PH Qty", min_value=0, value=0, step=1)
                with col_i2: field_q3 = st.number_input("Est 3 PH Qty", min_value=0, value=0, step=1)
                
            commit_pin = st.form_submit_button("➕ STEP 3: LOG PIN TO SHEET DRAFT", type="primary")

        if commit_pin:
            if not captured_lat or not captured_lng: st.error("❌ Location missing. Tap the red button first.")
            elif field_file is None: st.error("❌ Building Snapshot photo is mandatory.")
            else:
                try:
                    img = Image.open(field_file)
                    img.thumbnail((300, 300))
                    img_buf = io.BytesIO()
                    img.save(img_buf, format="JPEG", quality=65)
                    encoded_img_str = base64.b64encode(img_buf.getvalue()).decode()
                except: encoded_img_str = ""

                df_current_surveys = get_data("Surveys")
                stop_idx = 1
                if not df_current_surveys.empty and "session_id" in df_current_surveys.columns:
                    stop_idx = len(df_current_surveys[df_current_surveys["session_id"] == st.session_state["session_id"]]) + 1

                final_bldg_name = field_bldg.strip() if field_bldg.strip() else f"Stop #{stop_idx} (Asset Pin)"

                new_draft_row = pd.DataFrame([{
                    "id": str(int(time.time())), "session_id": st.session_state["session_id"],
                    "date": st.session_state["s_date"], "lineman": st.session_state["s_lineman"],
                    "building_name": final_bldg_name, "lat": str(captured_lat), "lng": str(captured_lng),
                    "qty_1ph": str(field_q1), "qty_3ph": str(field_q3), "image_b64": encoded_img_str,
                    "assigned_to": "", "status": "Draft"
                }])

                if df_current_surveys.empty:
                    df_master = new_draft_row
                else:
                    df_master = pd.concat([df_current_surveys, new_draft_row], ignore_index=True)
                
                conn.update(worksheet="Surveys", data=df_master.astype(str))
                st.query_params.clear()
                st.cache_data.clear()
                st.toast(f"✅ Securely logged {final_bldg_name} to cloud!", icon="💾")
                st.rerun()

        df_view = get_data("Surveys")
        s_pins_count = len(df_view[df_view["session_id"] == st.session_state["session_id"]]) if not df_view.empty and "session_id" in df_view.columns else 0
        st.write(f"📊 **Current Session Progress:** `{s_pins_count} Pins Saved to Cloud`")
        
        st.divider()
        col_end1, col_end2 = st.columns(2)
        with col_end1:
            if st.button("💾 END & FINALIZE ROUTE", type="primary", use_container_width=True):
                if s_pins_count == 0: st.error("Cannot finalize an empty survey log.")
                else:
                    df_view.loc[df_view["session_id"] == st.session_state["session_id"], "status"] = "Pending"
                    conn.update(worksheet="Surveys", data=df_view.astype(str))
                    st.session_state["survey_active"] = False
                    st.query_params.clear()
                    st.cache_data.clear()
                    st.success("🎉 Route compiled! All targets transferred to Work Planner.")
                    st.rerun()
        with col_end2:
            if st.button("🗑️ Abort Session", use_container_width=True):
                if s_pins_count > 0:
                    df_view = df_view[df_view["session_id"] != st.session_state["session_id"]]
                    conn.update(worksheet="Surveys", data=df_view.astype(str))
                st.session_state["survey_active"] = False
                st.query_params.clear()
                st.cache_data.clear()
                st.rerun()

# ── 🗂️ WORK PLANNER (DISTANCE CLUSTERING & GOOGLE ROUTING ENGINE APIS) ───────
with tab_planner:
    st.markdown('<div class="sec-hdr">🗂️ Capacity Proximity Optimizer Hub</div>', unsafe_allow_html=True)
    df_srv = get_data("Surveys")
    df_tchs = get_data("Technicians")
    
    active_installers = [str(r["name"]).strip() for _, r in df_tchs.iterrows() if str(r["is_active"]).strip() == "1"] if not df_tchs.empty else []

    if df_srv.empty or "status" not in df_srv.columns:
        st.info("No verified field surveys available to cluster.")
    elif not active_installers:
        st.warning("Please setup active installers inside Admin configuration matrices.")
    else:
        unassigned_pool = df_srv[
            (df_srv["status"] == "Pending") & 
            ((df_srv["assigned_to"] == "") | (df_srv["assigned_to"].isna()) | (df_srv["assigned_to"] == "None"))
        ].copy()
        
        if unassigned_pool.empty:
            st.success("🏁 All pins are locked into active assignments and dispatched.")
        else:
            st.write(f"Global unassigned target assets available: **{len(unassigned_pool)}**")
            with st.form("cluster_computation_form"):
                p_installer = st.selectbox("Assign Complete Smart Cluster to Installer Team", active_installers)
                p_max_capacity = st.number_input("Maximum Meter Payload Capacity Allocation", min_value=1, value=15, step=1)
                compute_cluster_btn = st.form_submit_button("⚡ Compute Proximity Route Cluster", type="primary")
                
            if compute_cluster_btn:
                records = []
                for _, r in unassigned_pool.iterrows():
                    q1, q3 = safe_int(r["qty_1ph"]), safe_int(r["qty_3ph"])
                    load_weight = (q1 + q3) if (q1 + q3) > 0 else 1
                    records.append({
                        "id": str(r["id"]), "building_name": str(r["building_name"]),
                        "lat": float(r["lat"]), "lng": float(r["lng"]),
                        "qty_1ph": q1, "qty_3ph": q3, "total_meters": load_weight,
                        "image_b64": str(r["image_b64"]), "lineman": str(r["lineman"])
                    })
                
                clustered_route = []
                running_load = 0
                if records:
                    pivot_node = records.pop(0)
                    if pivot_node["total_meters"] <= p_max_capacity:
                        clustered_route.append(pivot_node)
                        running_load += pivot_node["total_meters"]
                        
                        while records and (running_load < p_max_capacity):
                            clat, clng = pivot_node["lat"], pivot_node["lng"]
                            min_d, target_idx = float('inf'), 0
                            for i, cand in enumerate(records):
                                d = math.sqrt((cand["lat"] - clat)**2 + (cand["lng"] - clng)**2)
                                if d < min_d: min_d, target_idx = d, i
                                    
                            next_match = records[target_idx]
                            if running_load + next_match["total_meters"] <= p_max_capacity:
                                pivot_node = records.pop(target_idx)
                                clustered_route.append(pivot_node)
                                running_load += pivot_node["total_meters"]
                            else: break
                            
                st.session_state["active_computed_route"] = clustered_route
                st.session_state["route_target_installer"] = p_installer
                
            if "active_computed_route" in st.session_state and st.session_state["active_computed_route"]:
                computed_pts = st.session_state["active_computed_route"]
                inst_target = st.session_state["route_target_installer"]
                
                st.info(f"📍 Managed to bundle **{len(computed_pts)}** adjacent locations into a proximity route cluster for **{inst_target}**.")
                
                origin_str = f"{computed_pts[0]['lat']},{computed_pts[0]['lng']}"
                dest_str = f"{computed_pts[-1]['lat']},{computed_pts[-1]['lng']}"
                mid_waypoints = [f"{pt['lat']},{pt['lng']}" for pt in computed_pts[1:-1]]
                
                # Upgraded to Production Standard Google Maps Intent URL APIs
                optimized_gmaps_url = f"https://www.google.com/maps/dir/?api=1&origin={origin_str}&destination={dest_str}"
                if mid_waypoints: 
                    optimized_gmaps_url += f"&waypoints={'|'.join(mid_waypoints)}"
                    
                msg_body = [
                    f"⚡ *SMART METER DEPLOYMENT ROUTE* ⚡",
                    f"📅 *Date:* {date.today()}",
                    f"👷 *Assigned Installer:* {inst_target}\n",
                    f"🗺️ *Click to launch Sequential Route Mapping Navigation:*",
                    f"{optimized_gmaps_url}\n",
                    f"📋 *Sequence of Building Targets:*"
                ]
                for idx, pt in enumerate(computed_pts):
                    msg_body.append(f"{idx+1}. {pt['building_name']} (1PH:{pt['qty_1ph']}, 3PH:{pt['qty_3ph']})")
                    msg_body.append(f"   ↳ Map Pin: https://www.google.com/maps/search/?api=1&query={pt['lat']},{pt['lng']}")
                    
                final_wa_string = "\n".join(msg_body)
                wa_dispatch_endpoint = f"https://wa.me/?text={urllib.parse.quote(final_wa_string)}"
                
                st.markdown(f'<a href="{wa_dispatch_endpoint}" target="_blank" class="wa-btn" style="background:#10b981;">💬 Dispatch Route Map to {inst_target} via WhatsApp</a>', unsafe_allow_html=True)
                
                if st.button("🔒 Confirm Route Assignment & Lock Pins", type="primary", use_container_width=True):
                    target_ids = [pt["id"] for pt in computed_pts]
                    for target_id in target_ids:
                        df_srv.loc[df_srv["id"] == target_id, "assigned_to"] = inst_target
                        df_srv.loc[df_srv["id"] == target_id, "status"] = "Assigned"
                        
                    conn.update(worksheet="Surveys", data=df_srv.astype(str))
                    del st.session_state["active_computed_route"]
                    st.cache_data.clear()
                    st.success(f"Assignment locked securely for {inst_target}!")
                    st.rerun()

                st.markdown('<div class="sec-hdr">🔍 Cluster Route Composition Details</div>', unsafe_allow_html=True)
                for idx, pt in enumerate(computed_pts):
                    col_t, col_i = st.columns([3, 1])
                    with col_t:
                        st.write(f"**Stop #{idx+1}: {pt['building_name']}**")
                        st.caption(f"Surveyed by: {pt['lineman']} | GPS Core: {pt['lat']},{pt['lng']}")
                        st.write(f"🔌 Target Requirements: 1PH: **{pt['qty_1ph']}** | 3PH: **{pt['qty_3ph']}**")
                    with col_i:
                        if pt["image_b64"]:
                            try: st.image(io.BytesIO(base64.b64decode(pt["image_b64"])), use_container_width=True)
                            except: st.caption("🖼️ Load Error")
                        else: st.caption("No Photo")
                    st.divider()

# ═══════════════════════════════════════════════════════════════════════════════
#  INSTALLATIONS (COMPLETE VALIDATIONS, PAGINATION & EDIT/DELETE PIPELINES)
# ═══════════════════════════════════════════════════════════════════════════════
with tab_inst:
    df_techs = get_data("Technicians")
    df_locs  = get_data("Locations")

    active_techs = [str(r["name"]).strip() for _, r in df_techs.iterrows() if str(r.get("is_active","")).strip().lower() in ["1", "1.0", "true", "yes"]] if not df_techs.empty else []
    active_locs = [str(r["location_name"]).strip() for _, r in df_locs.iterrows() if str(r.get("location_name","")).strip()] if not df_locs.empty else []

    st.markdown('<div class="sec-hdr">➕ Daily Entry</div>', unsafe_allow_html=True)
    if not active_techs or not active_locs:
        st.warning("⚠️ Please add active Technicians and Locations in the Admin tab first.")
    else:
        with st.form("inst_form", clear_on_submit=True):
            fi1, fi2 = st.columns(2)
            with fi1: entry_date = st.date_input("Installation Date", date.today())
            with fi2: tech = st.selectbox("Technician", active_techs)
            loc  = st.selectbox("Location", active_locs)
            fc1, fc2 = st.columns(2)
            with fc1: q1 = st.number_input("1 PH Qty", min_value=0, step=1, value=0)
            with fc2: q3 = st.number_input("3 PH Qty", min_value=0, step=1, value=0)
            if st.form_submit_button("💾 Save Entry", type="primary"):
                if q1 == 0 and q3 == 0: st.error("❌ Both quantities are 0.")
                else:
                    df_existing = get_data("Installations")
                    is_dup = not df_existing[(df_existing["date"] == str(entry_date)) & (df_existing["tech_name"] == str(tech))].empty if not df_existing.empty else False
                    if is_dup: st.error(f"❌ Entry for **{tech}** on **{entry_date}** already exists.")
                    else:
                        new_row = pd.DataFrame([{"date": str(entry_date), "tech_name": str(tech), "location": str(loc), "qty_1ph": str(q1), "qty_3ph": str(q3)}])
                        updated = pd.concat([df_existing, new_row], ignore_index=True) if not df_existing.empty else new_row
                        conn.update(worksheet="Installations", data=updated.astype(str))
                        st.cache_data.clear(); st.success("✅ Saved!"); st.rerun()

    st.markdown('<div class="sec-hdr">📋 Installation Log</div>', unsafe_allow_html=True)
    log_data = get_data("Installations")
    if log_data.empty: st.info("No installation entries found.")
    else:
        log_sorted = log_data.iloc[::-1].reset_index(drop=True)
        total_pages = max(1, math.ceil(len(log_sorted) / 10))
        page = st.number_input(f"Page (1 – {total_pages})", min_value=1, max_value=total_pages, step=1, value=1)
        disp_log = log_sorted.iloc[(page - 1) * 10 : page * 10].copy()
        disp_log["qty_1ph"] = safe_numeric_col(disp_log, "qty_1ph").astype(int)
        disp_log["qty_3ph"] = safe_numeric_col(disp_log, "qty_3ph").astype(int)
        disp_log["Total"] = disp_log["qty_1ph"] + disp_log["qty_3ph"]
        st.dataframe(disp_log, use_container_width=True, hide_index=True)

        log_options_map = {f"#{idx+1} {row['date']} | {row['tech_name']}": idx for idx, row in log_sorted.iterrows()}
        target_label = st.selectbox("Select Record to Modify/Remove", ["-- Select --"] + list(log_options_map.keys()), key="inst_sel")
        
        if target_label != "-- Select --":
            sel_idx = log_options_map[target_label]
            curr_row = log_sorted.iloc[sel_idx]
            st.markdown(f'<div class="warn-box">⚠️ Modifying: <b>{curr_row["tech_name"]}</b> on <b>{curr_row["date"]}</b></div>', unsafe_allow_html=True)
            
            with st.form("edit_log_form"):
                e_loc = st.selectbox("Location", active_locs, index=active_locs.index(curr_row["location"]) if curr_row["location"] in active_locs else 0)
                ec1, ec2 = st.columns(2)
                with ec1: e_q1 = st.number_input("1 PH Qty", min_value=0, step=1, value=safe_int(curr_row["qty_1ph"]))
                with ec2: e_q3 = st.number_input("3 PH Qty", min_value=0, step=1, value=safe_int(curr_row["qty_3ph"]))
                bu, bd = st.columns(2)
                do_update = bu.form_submit_button("✏️ Update", type="primary")
                do_delete = bd.form_submit_button("🗑️ Delete")
                
            if do_update:
                if e_q1 == 0 and e_q3 == 0: st.error("❌ Quantities cannot be zero.")
                else:
                    log_data.iloc[len(log_data) - 1 - sel_idx, log_data.columns.get_loc("location")] = str(e_loc)
                    log_data.iloc[len(log_data) - 1 - sel_idx, log_data.columns.get_loc("qty_1ph")] = str(e_q1)
                    log_data.iloc[len(log_data) - 1 - sel_idx, log_data.columns.get_loc("qty_3ph")] = str(e_q3)
                    conn.update(worksheet="Installations", data=log_data.astype(str))
                    st.cache_data.clear(); st.success("Updated!"); st.rerun()
            if do_delete:
                st.session_state["pending_inst_del"] = f"{curr_row['date']}||{curr_row['tech_name']}"

        if "pending_inst_del" in st.session_state:
            d_date, d_tech = st.session_state["pending_inst_del"].split("||", 1)
            st.markdown(f'<div class="warn-box">⚠️ Confirm Delete for {d_tech}?</div>', unsafe_allow_html=True)
            cy, cn = st.columns(2)
            if cy.button("✅ Confirm Delete", key="c_inst_d"):
                log_data = log_data[~((log_data["date"] == d_date) & (log_data["tech_name"] == d_tech))]
                conn.update(worksheet="Installations", data=log_data.astype(str))
                del st.session_state["pending_inst_del"]; st.cache_data.clear(); st.rerun()
            if cn.button("❌ Cancel", key="c_inst_c"):
                del st.session_state["pending_inst_del"]; st.rerun()

# ═══════════════════════════════════════════════════════════════════════════════
#  INVENTORY (COMPLETE INWARD PIPE, LIVE STOCK SUM & FULL CRUD LOG PACKS)
# ═══════════════════════════════════════════════════════════════════════════════
with tab_inv:
    st.markdown('<div class="sec-hdr">📥 Inward Store Material</div>', unsafe_allow_html=True)
    with st.form("inv_form", clear_on_submit=True):
        iv1, iv2 = st.columns(2)
        with iv1: idate, itype = st.date_input("Received Date", date.today()), st.selectbox("Type", ["1 PH", "3 PH"])
        with iv2: iqty, imrn = st.number_input("Quantity", min_value=1, step=1, value=1), st.text_input("MRN No.")
        imake = st.selectbox("Make", ["Schneider", "Genus", "Other"])
        if st.form_submit_button("📥 Save Stock", type="primary"):
            if not imrn.strip(): st.error("❌ MRN No. is required.")
            else:
                df_inv_exist = get_data("Inventory")
                new_inv = pd.DataFrame([{"date": str(idate), "type": str(itype), "qty": str(iqty), "mrn": imrn.strip(), "make": str(imake)}])
                updated_inv = pd.concat([df_inv_exist, new_inv], ignore_index=True) if not df_inv_exist.empty else new_inv
                conn.update(worksheet="Inventory", data=updated_inv.astype(str))
                st.cache_data.clear(); st.success("✅ Stock Logged!"); st.rerun()

    st.markdown('<div class="sec-hdr">📊 Live Stock Summary</div>', unsafe_allow_html=True)
    df_inv_t  = get_data("Inventory")
    df_inst_s = get_data("Installations")
    r_1ph = safe_numeric_col(df_inv_t[df_inv_t["type"] == "1 PH"], "qty").sum() if not df_inv_t.empty else 0
    r_3ph = safe_numeric_col(df_inv_t[df_inv_t["type"] == "3 PH"], "qty").sum() if not df_inv_t.empty else 0
    u_1ph = safe_numeric_col(df_inst_s, "qty_1ph").sum() if not df_inst_s.empty else 0
    u_3ph = safe_numeric_col(df_inst_s, "qty_3ph").sum() if not df_inst_s.empty else 0

    sm1, sm2, sm3, sm4 = st.columns(4)
    sm1.metric("1PH Recd", int(r_1ph))
    sm2.metric("3PH Recd", int(r_3ph))
    sm3.metric("1PH Avail", max(int(r_1ph - u_1ph), 0))
    sm4.metric("3PH Avail", max(int(r_3ph - u_3ph), 0))

    st.markdown('<div class="sec-hdr">📋 Inventory Log</div>', unsafe_allow_html=True)
    if df_inv_t.empty: st.info("No records inside inventory.")
    else:
        inv_sorted = df_inv_t.iloc[::-1].reset_index(drop=True)
        st.download_button("⬇ Export Inventory CSV", inv_sorted.to_csv(index=False).encode(), "inventory.csv", "text/csv", use_container_width=True)
        
        total_inv_p = max(1, math.ceil(len(inv_sorted) / 10))
        inv_page = st.number_input(f"Page (1–{total_inv_p})", min_value=1, max_value=total_inv_p, step=1, value=1, key="inv_page_node")
        st.dataframe(inv_sorted.iloc[(inv_page - 1) * 10 : inv_page * 10], use_container_width=True, hide_index=True)

        inv_options_map = {f"#{idx+1} {row.get('date')} | {row.get('type')} | MRN:{row.get('mrn')}": idx for idx, row in inv_sorted.iterrows()}
        inv_target = st.selectbox("Select Inventory Record to Modify", ["-- Select --"] + list(inv_options_map.keys()), key="inv_sel")
        
        if inv_target != "-- Select --":
            inv_idx = inv_options_map[inv_target]
            inv_row = inv_sorted.iloc[inv_idx]
            st.markdown(f'<div class="warn-box">⚠️ Modifying: MRN <b>{inv_row.get("mrn")}</b></div>', unsafe_allow_html=True)
            
            with st.form("edit_inv_form"):
                e_qty  = st.number_input("Quantity", min_value=1, step=1, value=safe_int(inv_row.get("qty", 1)))
                e_mrn  = st.text_input("MRN No.", value=str(inv_row.get("mrn", "")))
                e_make = st.selectbox("Make", ["Schneider", "Genus", "Other"], index=["Schneider", "Genus", "Other"].index(inv_row.get("make")) if inv_row.get("make") in ["Schneider", "Genus", "Other"] else 0)
                ib1, ib2 = st.columns(2)
                if ib1.form_submit_button("✏️ Update", type="primary"):
                    if not e_mrn.strip(): st.error("❌ MRN cannot be blank.")
                    else:
                        df_inv_t.iloc[len(df_inv_t) - 1 - inv_idx, df_inv_t.columns.get_loc("qty")] = str(e_qty)
                        df_inv_t.iloc[len(df_inv_t) - 1 - inv_idx, df_inv_t.columns.get_loc("mrn")] = e_mrn.strip()
                        df_inv_t.iloc[len(df_inv_t) - 1 - inv_idx, df_inv_t.columns.get_loc("make")] = e_make
                        conn.update(worksheet="Inventory", data=df_inv_t.astype(str))
                        st.cache_data.clear(); st.success("Updated!"); st.rerun()
                if ib2.form_submit_button("🗑️ Delete"):
                    st.session_state["pending_inv_del"] = inv_idx

        if "pending_inv_del" in st.session_state:
            del_target_idx = st.session_state["pending_inv_del"]
            st.markdown('<div class="warn-box">⚠️ Confirm deletion of this inventory record?</div>', unsafe_allow_html=True)
            iy, in_c = st.columns(2)
            if iy.button("✅ Yes, Delete", key="c_inv_d"):
                df_inv_t = df_inv_t.drop(index=len(df_inv_t) - 1 - del_target_idx).reset_index(drop=True)
                conn.update(worksheet="Inventory", data=df_inv_t.astype(str))
                del st.session_state["pending_inv_del"]; st.cache_data.clear(); st.rerun()
            if in_c.button("❌ Cancel", key="c_inv_c"):
                del st.session_state["pending_inv_del"]; st.rerun()

# ═══════════════════════════════════════════════════════════════════════════════
#  ADMIN PANEL
# ═══════════════════════════════════════════════════════════════════════════════
with tab_admin:
    st.markdown('<div class="sec-hdr">⚙️ Administrative Tables Connection</div>', unsafe_allow_html=True)
    
    def process_editor_save(edited_df, worksheet_name, mandatory_cols):
        for m_col in mandatory_cols:
            if m_col not in edited_df.columns: return False, f"❌ Missing column '{m_col}'"
        df_clean = edited_df.fillna("").astype(str)
        for col in df_clean.columns: df_clean[col] = df_clean[col].str.strip()
        df_clean = df_clean[df_clean.astype(bool).any(axis=1)]
        if df_clean.empty: return False, "❌ Cannot save completely empty configurations."
        try:
            conn.update(worksheet=worksheet_name, data=df_clean.reset_index(drop=True))
            st.cache_data.clear(); return True, "✅ Saved Successfully!"
        except Exception as e: return False, f"❌ API Error: {str(e)}"

    subtab_tech, subtab_loc = st.tabs(["👷 Technicians", "📍 Locations"])
    
    with subtab_tech:
        df_t = get_data("Technicians")
        if df_t.empty: df_t = pd.DataFrame(columns=["name", "phone", "aadhar", "is_active"])
        edited_techs = st.data_editor(df_t, num_rows="dynamic", use_container_width=True, hide_index=True, key="tech_editor_box")
        if st.button("💾 Commit Technicians List", type="primary"):
            ok, msg = process_editor_save(edited_techs, "Technicians", ["name", "phone"])
            if ok: st.success(msg); st.rerun()
            else: st.error(msg)
            
    with subtab_loc:
        df_l = get_data("Locations")
        if df_l.empty: df_l = pd.DataFrame(columns=["location_name"])
        edited_locs = st.data_editor(df_l, num_rows="dynamic", use_container_width=True, hide_index=True, key="loc_editor_box")
        if st.button("💾 Commit Locations List", type="primary"):
            ok, msg = process_editor_save(edited_locs, "Locations", ["location_name"])
            if ok: st.success(msg); st.rerun()
            else: st.error(msg)
