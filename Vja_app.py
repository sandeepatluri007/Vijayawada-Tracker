"""
Smart Meter Field Tracker + Route Planner
=========================================
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
import base64

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Field Meter Tracker",
    page_icon="⚡",
    layout="centered",
    initial_sidebar_state="collapsed",
)

# ── CSS – Clean Light Theme ──────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Rajdhani:wght@500;600;700&family=Inter:wght@400;500;600&display=swap');

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

# ── Safe Version-Agnostic Query Params ────────────────────────────────────────
captured_lat, captured_lng = "", ""
try:
    if hasattr(st, "query_params"):
        captured_lat = st.query_params.get("lat", "")
        captured_lng = st.query_params.get("lng", "")
    elif hasattr(st, "experimental_get_query_params"):
        params = st.experimental_get_query_params()
        captured_lat = params.get("lat", [""])[0] if "lat" in params else ""
        captured_lng = params.get("lng", [""])[0] if "lng" in params else ""
except Exception:
    pass

def clear_query_params():
    try:
        if hasattr(st, "query_params"):
            st.query_params.clear()
        elif hasattr(st, "experimental_set_query_params"):
            st.experimental_set_query_params()
    except Exception:
        pass

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
    st.write("") # slight vertical padding
    if st.button("🔄 Refresh"):
        st.cache_data.clear()
        st.rerun()

st.write("") # Spacing before tabs

# ── Authentication / PIN Protection ───────────────────────────────────────────
if "authenticated" not in st.session_state:
    st.session_state["authenticated"] = False

if not st.session_state["authenticated"]:
    st.markdown('<div class="sec-hdr">🔒 Supervisor Login</div>', unsafe_allow_html=True)
    
    with st.form("login_form"):
        st.info("Please enter the daily operations PIN to access the system.")
        pin_entry = st.text_input("Enter PIN", type="password")
        login_btn = st.form_submit_button("Unlock Tracker", type="primary")
        
        if login_btn:
            # Change "2333" to whatever PIN you want to use
            if pin_entry == "2333": 
                st.session_state["authenticated"] = True
                st.success("Access Granted!")
                st.rerun()
            else:
                st.error("❌ Incorrect PIN. Access Denied.")
                
    st.stop() 
# ──────────────────────────────────────────────────────────────────────────────

# ── Google Sheets connection ──────────────────────────────────────────────────
conn = st.connection("gsheets", type=GSheetsConnection)

# ── Helpers ───────────────────────────────────────────────────────────────────
def get_data(worksheet: str, retries=3) -> pd.DataFrame:
    """Fetches data with built-in retries for spotty mobile networks."""
    for attempt in range(retries):
        try:
            df = conn.read(worksheet=worksheet, ttl=10)
            return df.astype(str).fillna("") if not df.empty else pd.DataFrame()
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(1)
            else:
                st.toast(f"📡 Weak connection. Having trouble loading {worksheet}...", icon="⚠️")
                return pd.DataFrame()

def safe_int(val, default: int = 0) -> int:
    try:
        return int(float(val))
    except (ValueError, TypeError):
        return default

def safe_numeric_col(df: pd.DataFrame, col: str) -> pd.Series:
    return pd.to_numeric(df[col], errors="coerce").fillna(0)

def has_col(df: pd.DataFrame, *cols) -> bool:
    return all(c in df.columns for c in cols)


# ── Tabs Configuration ────────────────────────────────────────────────────────
tab_dash, tab_survey, tab_planner, tab_inst, tab_inv, tab_admin = st.tabs([
    "📊 Dashboard", "🏍️ Survey Run", "🗂️ Work Planner", "🛠️ Installs", "📦 Store", "⚙️ Admin"
])


# ═══════════════════════════════════════════════════════════════════════════════
#  DASHBOARD
# ═══════════════════════════════════════════════════════════════════════════════
with tab_dash:

    df_inst = get_data("Installations")
    df_inv  = get_data("Inventory")

    # ── Inventory stock cards ─────────────────────────────────────
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
    sc3.metric("Pending 1PH",   pending_1ph,
               delta="⚠️ Deficit!" if pending_1ph < 0 else None,
               delta_color="inverse")
    sc4.metric("Pending 3PH",   pending_3ph,
               delta="⚠️ Deficit!" if pending_3ph < 0 else None,
               delta_color="inverse")

    st.divider()

    # ── Installation filters ──────────────────────────────────────
    st.markdown('<div class="sec-hdr">🔌 Installation Summary</div>', unsafe_allow_html=True)

    if df_inst.empty or not has_col(df_inst, "date", "tech_name", "location", "qty_1ph", "qty_3ph"):
        st.info("No installation data yet. Add entries in the Installations tab.")
    else:
        f1, f2 = st.columns(2)
        with f1:
            date_range = st.date_input("Date Range", [date.today(), date.today()])
        with f2:
            meter_filter = st.multiselect("Meter Type", ["1 PH", "3 PH"], default=["1 PH", "3 PH"])

        loc_list  = sorted([l for l in df_inst["location"].unique() if l.strip()])
        tech_list = sorted([t for t in df_inst["tech_name"].unique() if t.strip()])

        f3, f4 = st.columns(2)
        with f3:
            loc_filter  = st.multiselect("Locations",   loc_list,  default=loc_list)
        with f4:
            tech_filter = st.multiselect("Technicians", tech_list, default=tech_list)

        filtered = df_inst.copy()

        if isinstance(date_range, (list, tuple)) and len(date_range) == 2:
            d_start, d_end = date_range[0], date_range[1]
        elif isinstance(date_range, (list, tuple)) and len(date_range) == 1:
            d_start = d_end = date_range[0]
        else:
            d_start = d_end = date_range

        filtered["_date"] = pd.to_datetime(filtered["date"], errors="coerce").dt.date
        filtered = filtered[
            (filtered["_date"] >= d_start) &
            (filtered["_date"] <= d_end)
        ]
        if loc_filter:
            filtered = filtered[filtered["location"].isin(loc_filter)]
        if tech_filter:
            filtered = filtered[filtered["tech_name"].isin(tech_filter)]

        filtered["qty_1ph"] = safe_numeric_col(filtered, "qty_1ph")
        filtered["qty_3ph"] = safe_numeric_col(filtered, "qty_3ph")

        show_1ph = "1 PH" in meter_filter
        show_3ph = "3 PH" in meter_filter
        sum_1ph  = int(filtered["qty_1ph"].sum()) if show_1ph else 0
        sum_3ph  = int(filtered["qty_3ph"].sum()) if show_3ph else 0

        m1, m2, m3 = st.columns(3)
        m1.metric("Filtered 1PH", sum_1ph)
        m2.metric("Filtered 3PH", sum_3ph)
        m3.metric("Grand Total",  sum_1ph + sum_3ph)

        if not filtered.empty:
            st.markdown('<div class="sec-hdr">👷 Technician Breakdown</div>', unsafe_allow_html=True)
            group_df = (
                filtered
                .groupby(["tech_name", "location"])[["qty_1ph", "qty_3ph"]]
                .sum()
                .reset_index()
            )
            group_df["Total"] = group_df["qty_1ph"] + group_df["qty_3ph"]
            group_df.columns = ["Technician", "Location", "1PH", "3PH", "Total"]
            st.dataframe(group_df, use_container_width=True, hide_index=True)

            st.markdown('<div class="sec-hdr">📤 Export & Share</div>', unsafe_allow_html=True)
            
            export_df = group_df.copy()
            export_df.loc[len(export_df)] = ["---", "---", "---", "---", "---"]
            export_df.loc[len(export_df)] = ["GRAND TOTAL", "", sum_1ph, sum_3ph, sum_1ph + sum_3ph]
            export_df.loc[len(export_df)] = ["PENDING STOCK", "", pending_1ph, pending_3ph, ""]
            
            csv_data = export_df.to_csv(index=False).encode("utf-8")
            st.download_button("📥 Download CSV Report", data=csv_data,
                               file_name="Installation_Summary.csv", mime="text/csv",
                               use_container_width=True)

            date_str = f"{d_start} to {d_end}" if d_start != d_end else str(d_start)
            wa_loc_df = filtered.groupby("location")[["qty_1ph", "qty_3ph"]].sum().reset_index()

            wa_lines = [
                "DPR- Touchlight Infra",
                f"Date: {date_str}\n"
            ]
            
            for _, row in wa_loc_df.iterrows():
                q1_val = int(row["qty_1ph"]) if show_1ph else 0
                q3_val = int(row["qty_3ph"]) if show_3ph else 0
                wa_lines.append(f"{row['location']}:")
                wa_lines.append(f"1PH: {q1_val}, 3PH: {q3_val}\n")
                
            wa_lines.append(f"Total 1PH: {sum_1ph} | Total 3PH: {sum_3ph} | Grand Total: {sum_1ph + sum_3ph}")
            wa_lines.append(f"Pending Stock: 1PH: {pending_1ph} | 3PH: {pending_3ph}")

            wa_text = "\n".join(wa_lines)
            wa_url  = f"https://wa.me/?text={urllib.parse.quote(wa_text)}"
            st.markdown(
                f'<a href="{wa_url}" target="_blank" class="wa-btn">💬 Send to WhatsApp</a>',
                unsafe_allow_html=True,
            )
        else:
            st.info("No records match the selected filters.")


# ═══════════════════════════════════════════════════════════════════════════════
#  SURVEY SESSION (RIDE & PIN)
# ═══════════════════════════════════════════════════════════════════════════════
with tab_survey:
    if "survey_active" not in st.session_state: st.session_state["survey_active"] = False
    if "session_id" not in st.session_state: st.session_state["session_id"] = ""
    if "s_lineman" not in st.session_state: st.session_state["s_lineman"] = ""
    if "s_date" not in st.session_state: st.session_state["s_date"] = ""

    if not st.session_state["survey_active"]:
        st.markdown('<div class="sec-hdr">🏁 Start Survey Route</div>', unsafe_allow_html=True)
        with st.form("start_session_form"):
            input_lineman = st.text_input("Active Lineman Name", placeholder="Who is navigating on the bike?")
            input_date = st.date_input("Survey Date", date.today())
            if st.form_submit_button("🏁 Begin Active Tracking", type="primary"):
                if not input_lineman.strip():
                    st.error("❌ Lineman name is mandatory.")
                else:
                    st.session_state["survey_active"] = True
                    st.session_state["session_id"] = f"SESS_{int(time.time())}"
                    st.session_state["s_lineman"] = input_lineman.strip()
                    st.session_state["s_date"] = str(input_date)
                    st.rerun()

    else:
        st.markdown(f"""
        <div style="background:#f0fdf4; border:1px solid #bbf7d0; padding:12px; border-radius:8px; margin-bottom:15px;">
            <b style="color:#166534;">🟢 ACTIVE SURVEY ROUTE</b><br/>
            <span style="font-size:13px; color:#1e293b;"><b>Lineman:</b> {st.session_state['s_lineman']} | <b>Date:</b> {st.session_state['s_date']}</span>
        </div>
        """, unsafe_allow_html=True)

        # Smart JS Geolocation that prevents infinite reload loops
        js_gps_locator = """
        <script>
        function captureLiveGPS() {
            if (navigator.geolocation) {
                navigator.geolocation.getCurrentPosition(function(position) {
                    const currentUrl = new URL(window.parent.location.href);
                    const newLat = position.coords.latitude.toString();
                    const newLng = position.coords.longitude.toString();
                    
                    if (currentUrl.searchParams.get('lat') !== newLat || currentUrl.searchParams.get('lng') !== newLng) {
                        currentUrl.searchParams.set('lat', newLat);
                        currentUrl.searchParams.set('lng', newLng);
                        window.parent.location.href = currentUrl.toString();
                    } else {
                        alert("Location is already up to date!");
                    }
                }, function(error) {
                    alert("GPS Error. Ensure location permissions are active.");
                }, {enableHighAccuracy: true});
            } else {
                alert("Geolocation not supported on this browser.");
            }
        }
        </script>
        <button onclick="captureLiveGPS()" style="
            width: 100%; background-color: #ff4b4b; color: #ffffff; padding: 14px; border: none; 
            border-radius: 8px; font-family: 'Inter', sans-serif; font-weight: 700; font-size: 15px;
            cursor: pointer; box-shadow: 0 2px 4px rgba(0,0,0,0.1); margin-bottom: 12px;
        ">📍 STEP 1: AUTO-CAPTURE GPS PIN</button>
        """
        components.html(js_gps_locator, height=55)

        if captured_lat and captured_lng:
            st.success(f"🎯 GPS Locked: {captured_lat}, {captured_lng}")
        else:
            st.warning("⚠️ GPS tracking uninitialized. Tap the red button to capture position.")

        st.markdown('<div class="sec-hdr">📷 STEP 2: Document & Log</div>', unsafe_allow_html=True)
        
        with st.form("quick_pin_form", clear_on_submit=True):
            field_file = st.file_uploader("Capture Snapshot (Camera/File)", type=["jpg", "jpeg", "png"])
            
            with st.expander("📝 Optional Fields (Bypass to save time)"):
                field_bldg = st.text_input("Structure Reference / Door No.", value="")
                col_i1, col_i2 = st.columns(2)
                with col_i1: field_q1 = st.number_input("Est 1 PH Qty", min_value=0, value=0, step=1)
                with col_i2: field_q3 = st.number_input("Est 3 PH Qty", min_value=0, value=0, step=1)
                
            commit_pin = st.form_submit_button("➕ STEP 3: ADD PIN TO SESSION", type="primary")

        if commit_pin:
            if not captured_lat or not captured_lng:
                st.error("❌ Location missing. Tap the red button first.")
            elif field_file is None:
                st.error("❌ Building Snapshot photo is mandatory.")
            else:
                encoded_img_str = ""
                try:
                    encoded_img_str = base64.b64encode(field_file.getvalue()).decode()
                except Exception:
                    pass

                df_current_surveys = get_data("Surveys")
                stop_idx = 1
                if not df_current_surveys.empty and "session_id" in df_current_surveys.columns:
                    stop_idx = len(df_current_surveys[df_current_surveys["session_id"] == st.session_state["session_id"]]) + 1

                # Zero Typing Auto-Name
                final_bldg_name = field_bldg.strip() if field_bldg.strip() else f"Asset-Stop #{stop_idx}"

                new_draft_row = pd.DataFrame([{
                    "id": str(int(time.time())), 
                    "session_id": st.session_state["session_id"],
                    "date": st.session_state["s_date"], 
                    "lineman": st.session_state["s_lineman"],
                    "building_name": final_bldg_name, 
                    "lat": str(captured_lat), 
                    "lng": str(captured_lng),
                    "qty_1ph": str(field_q1), 
                    "qty_3ph": str(field_q3), 
                    "image_b64": encoded_img_str,
                    "assigned_to": "", 
                    "status": "Draft"
                }])

                if df_current_surveys.empty:
                    df_master = new_draft_row
                else:
                    df_master = pd.concat([df_current_surveys, new_draft_row], ignore_index=True)
                
                conn.update(worksheet="Surveys", data=df_master.astype(str))
                clear_query_params()
                st.cache_data.clear()
                st.toast(f"✅ Saved {final_bldg_name} to cloud!", icon="💾")
                st.rerun()

        # Monitor local session volume indices
        df_view = get_data("Surveys")
        s_pins_count = len(df_view[df_view["session_id"] == st.session_state["session_id"]]) if not df_view.empty and "session_id" in df_view.columns else 0

        st.write(f"📊 **Current Progress:** `{s_pins_count} Pins Captured on this Route`")
        
        st.divider()
        col_end1, col_end2 = st.columns(2)
        with col_end1:
            if st.button("💾 END & FINALIZE ROUTE", type="primary", use_container_width=True):
                if s_pins_count == 0:
                    st.error("Cannot finalize an empty tracking routine session.")
                else:
                    df_view.loc[df_view["session_id"] == st.session_state["session_id"], "status"] = "Pending"
                    conn.update(worksheet="Surveys", data=df_view.astype(str))
                    
                    st.session_state["survey_active"] = False
                    clear_query_params()
                    st.cache_data.clear()
                    st.success("🎉 Route compiled! Pins moved to Work Planner.")
                    st.rerun()
                    
        with col_end2:
            if st.button("🗑️ Abort Session", use_container_width=True):
                if s_pins_count > 0:
                    df_view = df_view[df_view["session_id"] != st.session_state["session_id"]]
                    conn.update(worksheet="Surveys", data=df_view.astype(str))
                st.session_state["survey_active"] = False
                clear_query_params()
                st.cache_data.clear()
                st.rerun()

# ═══════════════════════════════════════════════════════════════════════════════
#  WORK PLANNER
# ═══════════════════════════════════════════════════════════════════════════════
with tab_planner:
    st.markdown('<div class="sec-hdr">🗂️ Work Planner & Auto-Routing</div>', unsafe_allow_html=True)
    df_srv = get_data("Surveys")
    df_tchs = get_data("Technicians")
    
    active_installers = [str(r["name"]).strip() for _, r in df_tchs.iterrows() if str(r["is_active"]).strip() == "1"] if not df_tchs.empty else []

    if df_srv.empty or "status" not in df_srv.columns:
        st.info("No field surveys available. Start a Survey Session first.")
    elif not active_installers:
        st.warning("Please setup active installers inside the Admin panel.")
    else:
        unassigned_pool = df_srv[
            (df_srv["status"] == "Pending") & 
            ((df_srv["assigned_to"] == "") | (df_srv["assigned_to"].isna()) | (df_srv["assigned_to"] == "None"))
        ].copy()
        
        if unassigned_pool.empty:
            st.success("🏁 All captured pins are securely assigned and locked!")
        else:
            st.write(f"Unassigned structures awaiting dispatch: **{len(unassigned_pool)}**")
            
            with st.form("cluster_computation_form"):
                p_installer = st.selectbox("Assign Route To Installer:", active_installers)
                p_max_capacity = st.number_input("Max Meter Load Limit for Route:", min_value=1, value=15, step=1)
                compute_cluster_btn = st.form_submit_button("⚡ Generate Shortest Route Cluster", type="primary")
                
            if compute_cluster_btn:
                records = []
                for _, r in unassigned_pool.iterrows():
                    q1, q3 = safe_int(r["qty_1ph"]), safe_int(r["qty_3ph"])
                    load_weight = (q1 + q3) if (q1 + q3) > 0 else 1
                    try:
                        lat_val, lng_val = float(r["lat"]), float(r["lng"])
                    except Exception:
                        continue
                        
                    records.append({
                        "id": str(r["id"]), "building_name": str(r["building_name"]),
                        "lat": lat_val, "lng": lng_val,
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
                
                st.info(f"📍 Successfully clustered **{len(computed_pts)}** locations into an optimized route for **{inst_target}**.")
                
                origin_str = f"{computed_pts[0]['lat']},{computed_pts[0]['lng']}"
                dest_str = f"{computed_pts[-1]['lat']},{computed_pts[-1]['lng']}"
                mid_waypoints = [f"{pt['lat']},{pt['lng']}" for pt in computed_pts[1:-1]]
                
                optimized_gmaps_url = f"https://www.google.com/maps/dir/?api=1?api=1&origin={origin_str}&destination={dest_str}"
                if mid_waypoints: 
                    optimized_gmaps_url += f"&waypoints={'|'.join(mid_waypoints)}"
                    
                msg_body = [
                    f"⚡ *METER DEPLOYMENT ROUTE* ⚡",
                    f"📅 *Date:* {date.today()}",
                    f"👷 *Installer:* {inst_target}\n",
                    f"🗺️ *Click here to open Navigation Map:*",
                    f"{optimized_gmaps_url}\n",
                    f"📋 *Building Sequence:*"
                ]
                
                for idx, pt in enumerate(computed_pts):
                    msg_body.append(f"{idx+1}. {pt['building_name']} (1PH:{pt['qty_1ph']}, 3PH:{pt['qty_3ph']})")
                    msg_body.append(f"   ↳ Map Pin: mymaps.google.com3?api=1&query={pt['lat']},{pt['lng']}")
                    
                final_wa_string = "\n".join(msg_body)
                wa_dispatch_endpoint = f"https://wa.me/?text={urllib.parse.quote(final_wa_string)}"
                
                st.markdown(f'<a href="{wa_dispatch_endpoint}" target="_blank" class="wa-btn" style="background:#10b981;">💬 Dispatch to WhatsApp</a>', unsafe_allow_html=True)
                
                if st.button("🔒 Confirm Assignment & Lock Pins", type="primary", use_container_width=True):
                    target_ids = [pt["id"] for pt in computed_pts]
                    for target_id in target_ids:
                        df_srv.loc[df_srv["id"] == target_id, "assigned_to"] = inst_target
                        df_srv.loc[df_srv["id"] == target_id, "status"] = "Assigned"
                        
                    conn.update(worksheet="Surveys", data=df_srv.astype(str))
                    del st.session_state["active_computed_route"]
                    st.cache_data.clear()
                    st.success(f"Assignment locked securely for {inst_target}!")
                    st.rerun()

                st.markdown('<div class="sec-hdr">🔍 Assignment Details Preview</div>', unsafe_allow_html=True)
                for idx, pt in enumerate(computed_pts):
                    st.write(f"**Stop #{idx+1}: {pt['building_name']}**")
                    st.caption(f"Surveyed by: {pt['lineman']} | GPS Core: {pt['lat']},{pt['lng']}")
                    st.write(f"🔌 1PH: **{pt['qty_1ph']}** | 3PH: **{pt['qty_3ph']}**")
                    st.divider()

# ═══════════════════════════════════════════════════════════════════════════════
#  INSTALLATIONS
# ═══════════════════════════════════════════════════════════════════════════════
with tab_inst:

    df_techs = get_data("Technicians")
    df_locs  = get_data("Locations")

    active_techs = []
    if not df_techs.empty and has_col(df_techs, "is_active", "name"):
        for _, r in df_techs.iterrows():
            val = str(r["is_active"]).strip().lower()
            if val in ["1", "1.0", "true", "yes"]:
                n = str(r["name"]).strip()
                if n: active_techs.append(n)

    active_locs = []
    if not df_locs.empty and "location_name" in df_locs.columns:
        for _, r in df_locs.iterrows():
            l = str(r["location_name"]).strip()
            if l: active_locs.append(l)

    st.markdown('<div class="sec-hdr">➕ Daily Entry</div>', unsafe_allow_html=True)

    if not active_techs or not active_locs:
        st.warning("⚠️ Please add active Technicians and Locations in the **Admin** tab first.")
    else:
        with st.form("inst_form", clear_on_submit=True):
            fi1, fi2 = st.columns(2)
            with fi1:
                entry_date = st.date_input("Installation Date", date.today())
            with fi2:
                tech = st.selectbox("Technician", active_techs)
            loc  = st.selectbox("Location", active_locs)
            fc1, fc2 = st.columns(2)
            with fc1:
                q1 = st.number_input("1 PH Qty", min_value=0, step=1, value=0)
            with fc2:
                q3 = st.number_input("3 PH Qty", min_value=0, step=1, value=0)
            f_sub = st.form_submit_button("💾 Save Entry", type="primary")

        if f_sub:
            if q1 == 0 and q3 == 0:
                st.error("❌ Both quantities are 0. Enter at least one.")
            else:
                df_existing = get_data("Installations")
                is_dup = False
                if not df_existing.empty and has_col(df_existing, "date", "tech_name"):
                    is_dup = not df_existing[
                        (df_existing["date"]      == str(entry_date)) &
                        (df_existing["tech_name"] == str(tech))
                    ].empty
                if is_dup:
                    st.error(f"❌ Entry for **{tech}** on **{entry_date}** already exists. Edit it below.")
                else:
                    new_row = pd.DataFrame([{
                        "date"     : str(entry_date),
                        "tech_name": str(tech),
                        "location" : str(loc),
                        "qty_1ph"  : str(q1),
                        "qty_3ph"  : str(q3),
                    }])
                    updated = pd.concat([df_existing, new_row], ignore_index=True)
                    conn.update(worksheet="Installations", data=updated.astype(str))
                    st.cache_data.clear() 
                    st.success(f"✅ Entry saved for {tech} on {entry_date}.")
                    st.rerun()

    st.markdown('<div class="sec-hdr">📋 Installation Log</div>', unsafe_allow_html=True)
    log_data = get_data("Installations")

    if log_data.empty:
        st.info("No installation entries yet.")
    else:
        log_sorted = log_data.iloc[::-1].reset_index(drop=True)

        ITEMS = 10
        total_pages = max(1, math.ceil(len(log_sorted) / ITEMS))
        page = st.number_input(f"Page (1 – {total_pages})", min_value=1, max_value=total_pages, step=1, value=1)
        s, e = (page - 1) * ITEMS, page * ITEMS

        disp_log = log_sorted.iloc[s:e].copy()
        if has_col(disp_log, "qty_1ph", "qty_3ph"):
            disp_log["qty_1ph"] = disp_log["qty_1ph"].apply(lambda x: safe_int(x))
            disp_log["qty_3ph"] = disp_log["qty_3ph"].apply(lambda x: safe_int(x))
            disp_log["Total"]   = disp_log["qty_1ph"] + disp_log["qty_3ph"]
        st.dataframe(disp_log, use_container_width=True, hide_index=True)

        st.caption("Select a record to edit or delete:")

        log_options_map = {}
        for idx, row in log_sorted.iterrows():
            label = f"#{idx+1}  {row['date']} | {row['tech_name']}"
            log_options_map[label] = idx

        target_label = st.selectbox(
            "Select Record",
            ["-- Select --"] + list(log_options_map.keys()),
            key="inst_sel",
        )

        if target_label != "-- Select --":
            sel_idx  = log_options_map[target_label]
            curr_row = log_sorted.iloc[sel_idx]

            curr_q1 = safe_int(curr_row.get("qty_1ph", 0))
            curr_q3 = safe_int(curr_row.get("qty_3ph", 0))
            curr_loc = curr_row.get("location", "")
            loc_idx  = active_locs.index(curr_loc) if curr_loc in active_locs and active_locs else 0

            st.markdown(
                f'<div class="warn-box">⚠️ Modifying: <b>{curr_row["tech_name"]}</b>'
                f' on <b>{curr_row["date"]}</b></div>',
                unsafe_allow_html=True,
            )

            with st.form("edit_log_form"):
                if active_locs:
                    e_loc = st.selectbox("Location", active_locs, index=loc_idx)
                else:
                    e_loc = st.text_input("Location", value=curr_loc)

                ec1, ec2 = st.columns(2)
                with ec1:
                    e_q1 = st.number_input("1 PH Qty", min_value=0, step=1, value=curr_q1)
                with ec2:
                    e_q3 = st.number_input("3 PH Qty", min_value=0, step=1, value=curr_q3)

                btn_update, btn_delete = st.columns(2)
                with btn_update:
                    do_update = st.form_submit_button("✏️ Update", type="primary")
                with btn_delete:
                    do_delete = st.form_submit_button("🗑️ Delete")

            if do_update:
                if e_q1 == 0 and e_q3 == 0:
                    st.error("❌ Both quantities cannot be 0.")
                else:
                    mask = (
                        (log_data["date"]      == curr_row["date"]) &
                        (log_data["tech_name"] == curr_row["tech_name"])
                    )
                    log_data.loc[mask, ["location", "qty_1ph", "qty_3ph"]] = [
                        str(e_loc), str(e_q1), str(e_q3)
                    ]
                    conn.update(worksheet="Installations", data=log_data.astype(str))
                    st.cache_data.clear()
                    st.success("✅ Entry updated.")
                    st.rerun()

            if do_delete:
                st.session_state["pending_inst_del"] = curr_row["date"] + "||" + curr_row["tech_name"]

        if "pending_inst_del" in st.session_state:
            del_key  = st.session_state["pending_inst_del"]
            del_date, del_tech = del_key.split("||", 1)
            st.markdown(
                f'<div class="warn-box">⚠️ Confirm delete for <b>{del_tech}</b>'
                f' on <b>{del_date}</b>?</div>',
                unsafe_allow_html=True,
            )
            cy, cn = st.columns(2)
            with cy:
                if st.button("✅ Yes, Delete", key="conf_del_inst"):
                    mask = (
                        (log_data["date"]      == del_date) &
                        (log_data["tech_name"] == del_tech)
                    )
                    log_data = log_data[~mask]
                    conn.update(worksheet="Installations", data=log_data.astype(str))
                    del st.session_state["pending_inst_del"]
                    st.cache_data.clear()
                    st.success("Deleted.")
                    st.rerun()
            with cn:
                if st.button("❌ Cancel", key="cancel_del_inst"):
                    del st.session_state["pending_inst_del"]
                    st.rerun()


# ═══════════════════════════════════════════════════════════════════════════════
#  INVENTORY
# ═══════════════════════════════════════════════════════════════════════════════
with tab_inv:

    st.markdown('<div class="sec-hdr">📥 Inward Store Material</div>', unsafe_allow_html=True)

    with st.form("inv_form", clear_on_submit=True):
        iv1, iv2 = st.columns(2)
        with iv1:
            idate = st.date_input("Received Date", date.today())
            itype = st.selectbox("Type", ["1 PH", "3 PH"])
        with iv2:
            iqty  = st.number_input("Quantity", min_value=1, step=1, value=1)
            imrn  = st.text_input("MRN No.")
        imake = st.selectbox("Make", ["Schneider", "Genus", "Other"])
        iv_sub = st.form_submit_button("📥 Save Stock", type="primary")

    if iv_sub:
        if not imrn.strip():
            st.error("❌ MRN No. is required.")
        else:
            df_inv_exist = get_data("Inventory")
            new_inv = pd.DataFrame([{
                "date" : str(idate),
                "type" : str(itype),
                "qty"  : str(iqty),
                "mrn"  : imrn.strip(),
                "make" : str(imake),
            }])
            updated_inv = pd.concat([df_inv_exist, new_inv], ignore_index=True)
            conn.update(worksheet="Inventory", data=updated_inv.astype(str))
            st.cache_data.clear()
            st.success(f"✅ Inwarded {iqty} × {itype} ({imake}) — MRN {imrn.strip()}")
            st.rerun()

    st.markdown('<div class="sec-hdr">📊 Live Stock Summary</div>', unsafe_allow_html=True)
    df_inv_t  = get_data("Inventory")
    df_inst_s = get_data("Installations")

    r_1ph = r_3ph = u_1ph = u_3ph = 0
    if not df_inv_t.empty and has_col(df_inv_t, "type", "qty"):
        r_1ph = int(safe_numeric_col(df_inv_t[df_inv_t["type"] == "1 PH"], "qty").sum())
        r_3ph = int(safe_numeric_col(df_inv_t[df_inv_t["type"] == "3 PH"], "qty").sum())
    if not df_inst_s.empty and has_col(df_inst_s, "qty_1ph", "qty_3ph"):
        u_1ph = int(safe_numeric_col(df_inst_s, "qty_1ph").sum())
        u_3ph = int(safe_numeric_col(df_inst_s, "qty_3ph").sum())

    sm1, sm2, sm3, sm4 = st.columns(4)
    sm1.metric("1PH Received",      r_1ph)
    sm2.metric("3PH Received",      r_3ph)
    sm3.metric("1PH Pending Stock", max(r_1ph - u_1ph, 0))
    sm4.metric("3PH Pending Stock", max(r_3ph - u_3ph, 0))

    st.markdown('<div class="sec-hdr">📋 Inventory Log</div>', unsafe_allow_html=True)

    if df_inv_t.empty:
        st.info("No inventory entries yet.")
    else:
        inv_sorted = df_inv_t.iloc[::-1].reset_index(drop=True)

        inv_exp = inv_sorted.rename(columns={
            "date":"Date","type":"Type","qty":"Qty","mrn":"MRN No","make":"Make"
        })
        st.download_button(
            "⬇ Export Inventory CSV",
            inv_exp.to_csv(index=False).encode(),
            "inventory.csv", "text/csv",
            use_container_width=True,
        )

        ITEMS_INV   = 10
        total_inv_p = max(1, math.ceil(len(inv_sorted) / ITEMS_INV))
        inv_page    = st.number_input(f"Page (1–{total_inv_p})", min_value=1,
                                      max_value=total_inv_p, step=1, value=1, key="inv_page")
        si, ei = (inv_page - 1) * ITEMS_INV, inv_page * ITEMS_INV
        st.dataframe(inv_sorted.iloc[si:ei], use_container_width=True, hide_index=True)

        st.caption("Select an inventory entry to edit or delete:")

        inv_options_map = {}
        for idx, row in inv_sorted.iterrows():
            label = f"#{idx+1}  {row.get('date','')} | {row.get('type','')} | MRN:{row.get('mrn','')}"
            inv_options_map[label] = idx

        inv_target = st.selectbox(
            "Select Inventory Record",
            ["-- Select --"] + list(inv_options_map.keys()),
            key="inv_sel",
        )

        if inv_target != "-- Select --":
            inv_idx = inv_options_map[inv_target]
            inv_row = inv_sorted.iloc[inv_idx]

            st.markdown(
                f'<div class="warn-box">⚠️ Modifying: MRN <b>{inv_row.get("mrn","")}</b>'
                f' — {inv_row.get("type","")} ({inv_row.get("make","")})</div>',
                unsafe_allow_html=True,
            )

            with st.form("edit_inv_form"):
                ei1, ei2, ei3 = st.columns(3)
                with ei1:
                    e_qty  = st.number_input("Quantity", min_value=1, step=1,
                                             value=safe_int(inv_row.get("qty", 1), 1))
                with ei2:
                    e_mrn  = st.text_input("MRN No.", value=str(inv_row.get("mrn", "")))
                with ei3:
                    make_opts = ["Schneider", "Genus", "Other"]
                    curr_make = inv_row.get("make", "Schneider")
                    mk_idx    = make_opts.index(curr_make) if curr_make in make_opts else 0
                    e_make    = st.selectbox("Make", make_opts, index=mk_idx)

                ib1, ib2 = st.columns(2)
                with ib1:
                    inv_do_update = st.form_submit_button("✏️ Update", type="primary")
                with ib2:
                    inv_do_delete = st.form_submit_button("🗑️ Delete")

            if inv_do_update:
                if not e_mrn.strip():
                    st.error("❌ MRN No. cannot be empty.")
                else:
                    orig_df = df_inv_t.copy()
                    orig_inv_idx = len(orig_df) - 1 - inv_idx
                    orig_df.iloc[orig_inv_idx, orig_df.columns.get_loc("qty")]  = str(e_qty)
                    orig_df.iloc[orig_inv_idx, orig_df.columns.get_loc("mrn")]  = e_mrn.strip()
                    orig_df.iloc[orig_inv_idx, orig_df.columns.get_loc("make")] = e_make
                    conn.update(worksheet="Inventory", data=orig_df.astype(str))
                    st.cache_data.clear()
                    st.success("✅ Inventory entry updated.")
                    st.rerun()

            if inv_do_delete:
                st.session_state["pending_inv_del"] = inv_idx

        if "pending_inv_del" in st.session_state:
            del_inv_idx = st.session_state["pending_inv_del"]
            st.markdown(
                '<div class="warn-box">⚠️ Confirm delete? This will affect stock totals.</div>',
                unsafe_allow_html=True,
            )
            iy, inv_n = st.columns(2)
            with iy:
                if st.button("✅ Yes, Delete", key="conf_del_inv"):
                    orig_df     = df_inv_t.copy()
                    orig_inv_ri = len(orig_df) - 1 - del_inv_idx
                    orig_df     = orig_df.drop(index=orig_inv_ri).reset_index(drop=True)
                    conn.update(worksheet="Inventory", data=orig_df.astype(str))
                    del st.session_state["pending_inv_del"]
                    st.cache_data.clear()
                    st.success("Deleted.")
                    st.rerun()
            with inv_n:
                if st.button("❌ Cancel", key="cancel_del_inv"):
                    del st.session_state["pending_inv_del"]
                    st.rerun()


# ═══════════════════════════════════════════════════════════════════════════════
#  ADMIN
# ═══════════════════════════════════════════════════════════════════════════════
with tab_admin:

    st.markdown("""
    <div class="warn-box" style="background:#f8f9fa;border-color:#cbd5e1;color:#475569;">
    💡 <b>Tip:</b> Tap a cell to type, tap <b>+</b> at the bottom to add a row.
    Set <b>Active?</b> to <code>0</code> to hide a technician from entry forms.
    </div>
    """, unsafe_allow_html=True)

    def process_editor_save(edited_df, worksheet_name, mandatory_cols):
        for m_col in mandatory_cols:
            if m_col not in edited_df.columns:
                return False, f"❌ Missing column '{m_col}'. Add a row using the '+' button."

        df_clean = edited_df.fillna("").astype(str)

        for col in df_clean.columns:
            df_clean[col] = df_clean[col].str.strip()
            df_clean[col] = df_clean[col].replace(["nan", "NaN", "None", "<NA>"], "")

        df_clean = df_clean[df_clean.astype(bool).any(axis=1)]

        if df_clean.empty:
            return False, "❌ Cannot save: Table is completely empty. Leave at least one valid row."

        for m_col in mandatory_cols:
            if not df_clean[df_clean[m_col] == ""].empty:
                return False, f"❌ Validation Error: '{m_col}' cannot be blank."

        df_clean = df_clean.reset_index(drop=True)

        try:
            conn.update(worksheet=worksheet_name, data=df_clean)
            st.cache_data.clear()
            return True, "✅ Saved successfully!"
        except Exception as e:
            return False, f"❌ Google API Error: {str(e)}"

    subtab_tech, subtab_loc = st.tabs(["👷 Technicians", "📍 Locations"])

    # ── Technicians ───────────────────────────────────────────────
    with subtab_tech:
        st.markdown('<div class="sec-hdr">Manage Technicians</div>', unsafe_allow_html=True)
        df_t = get_data("Technicians")
        expected_cols_t = ["name", "phone", "aadhar", "is_active"]

        if not df_t.empty:
            col_map_t = {c: str(c).strip().lower() for c in df_t.columns}
            df_t = df_t.rename(columns=col_map_t)

        if df_t.empty:
            df_t = pd.DataFrame(columns=expected_cols_t)
        else:
            for col in expected_cols_t:
                if col not in df_t.columns:
                    df_t[col] = ""
            df_t = df_t[expected_cols_t]

        edited_techs = st.data_editor(
            df_t,
            num_rows="dynamic",
            use_container_width=True,
            hide_index=True,
            key="editor_techs",
            column_config={
                "name": st.column_config.TextColumn("Name", required=True),
                "phone": st.column_config.TextColumn("Phone", required=True),
                "aadhar": st.column_config.TextColumn("Aadhar No."),
                "is_active": st.column_config.SelectboxColumn(
                    "Active?", options=["1", "0"], required=True, default="1"
                ),
            },
        )

        if st.button("💾 Save Technicians", key="save_techs", type="primary"):
            success, message = process_editor_save(edited_techs, "Technicians", ["name", "phone"])
            if success:
                st.success(message)
                st.rerun()
            else:
                st.error(message)

    # ── Locations ─────────────────────────────────────────────────
    with subtab_loc:
        st.markdown('<div class="sec-hdr">Manage Locations</div>', unsafe_allow_html=True)
        df_l = get_data("Locations")
        expected_cols_l = ["location_name"]

        if not df_l.empty:
            col_map_l = {c: str(c).strip().lower() for c in df_l.columns}
            df_l = df_l.rename(columns=col_map_l)

        if df_l.empty:
            df_l = pd.DataFrame(columns=expected_cols_l)
        else:
            if "location_name" not in df_l.columns:
                df_l["location_name"] = ""
            df_l = df_l[expected_cols_l]

        edited_locs = st.data_editor(
            df_l,
            num_rows="dynamic",
            use_container_width=True,
            hide_index=True,
            key="editor_locs",
            column_config={
                "location_name": st.column_config.TextColumn("Location Name", required=True),
            },
        )

        if st.button("💾 Save Locations", key="save_locs", type="primary"):
            success, message = process_editor_save(edited_locs, "Locations", ["location_name"])
            if success:
                st.success(message)
                st.rerun()
            else:
                st.error(message)
