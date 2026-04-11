"""
VIJAYAWADA Field Tracker
=========================
"""

import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
from datetime import date
import urllib.parse
import math

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Field Meter Tracker",
    page_icon="⚡",
    layout="centered",
    initial_sidebar_state="collapsed",
)

# ── CSS – mobile-first, field-grade ──────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Rajdhani:wght@500;600;700&family=Inter:wght@400;500;600&display=swap');

html, body, [class*="css"] { font-family: 'Inter', sans-serif; }
.stApp { background:#0f1117; color:#e8ecf0; }
#MainMenu, footer, header { visibility:hidden; }

/* ── top banner ── */
.top-banner {
    background: linear-gradient(135deg,#1a2744,#0d1b35);
    border-bottom: 2px solid #2563eb;
    padding: 12px 16px 10px;
    margin: -1rem -1rem 1rem;
    display:flex; align-items:center; gap:10px;
}
.top-banner .t { font-family:'Rajdhani',sans-serif; font-size:1.45rem;
    font-weight:700; color:#f0f4ff; letter-spacing:.6px; margin:0; }
.top-banner .s { font-size:.72rem; color:#7fb3f5; margin:0; }

/* ── tabs ── */
.stTabs [data-baseweb="tab-list"] {
    background:#131720; border-radius:10px; padding:4px; gap:2px;
    overflow-x:auto; white-space:nowrap;
}
.stTabs [data-baseweb="tab"] {
    border-radius:8px !important; padding:8px 13px !important;
    font-family:'Rajdhani',sans-serif; font-size:.88rem !important;
    font-weight:600 !important; color:#8a9bbf !important;
    background:transparent !important; border:none !important;
    min-width:auto !important; flex-shrink:0;
}
.stTabs [aria-selected="true"] { background:#2563eb !important; color:#fff !important; }

/* ── metric cards ── */
[data-testid="stMetric"] {
    background: linear-gradient(145deg,#1a2540,#141c2e);
    border: 1px solid #243050; border-radius:12px;
    padding: 14px 12px !important;
}
[data-testid="stMetricLabel"]  { color:#6b7fa3 !important; font-size:.75rem !important; text-transform:uppercase; letter-spacing:.6px; }
[data-testid="stMetricValue"]  { font-family:'Rajdhani',sans-serif; font-size:1.9rem !important; font-weight:700; color:#fff !important; }
[data-testid="stMetricDelta"]  { font-size:.75rem !important; }

/* ── section headers ── */
.sec-hdr {
    font-family:'Rajdhani',sans-serif; font-size:1.05rem; font-weight:700;
    color:#7fb3f5; border-left:3px solid #2563eb; padding-left:9px;
    margin: 1rem 0 .5rem;
}

/* ── buttons ── */
.stButton>button {
    background:#2563eb !important; color:#fff !important;
    border:none !important; border-radius:8px !important;
    font-family:'Rajdhani',sans-serif !important; font-weight:600 !important;
    font-size:.93rem !important; padding:9px 18px !important;
    width:100% !important; transition:background .2s;
}
.stButton>button:hover { background:#1d4ed8 !important; }

/* ── inputs ── */
.stSelectbox>div>div, .stNumberInput>div>div>input,
.stTextInput>div>div>input, .stDateInput>div>div>input {
    background:#1a2235 !important; border:1px solid #2a3a58 !important;
    border-radius:8px !important; color:#e0e8f5 !important; font-size:.9rem !important;
}
.stSelectbox label, .stNumberInput label, .stTextInput label,
.stDateInput label, .stMultiSelect label {
    color:#8ca4c8 !important; font-size:.8rem !important; font-weight:500 !important;
}

/* ── forms ── */
.stForm { background:#141c2e !important; border:1px solid #243050 !important;
    border-radius:12px !important; padding:14px !important; }

/* ── dataframe ── */
.stDataFrame { border-radius:10px; overflow:hidden; }
[data-testid="stDataFrameResizable"] th {
    background:#1a2540 !important; color:#7fb3f5 !important;
    font-family:'Rajdhani',sans-serif; font-weight:600 !important; font-size:.82rem !important;
}
[data-testid="stDataFrameResizable"] td { color:#ccd6e8 !important; font-size:.8rem !important; }

/* ── warning / danger ── */
.warn-box {
    background:#2d1b0a; border:1px solid #d97706; border-radius:9px;
    padding:9px 13px; color:#fbbf24; font-size:.83rem; margin-bottom:.6rem;
}
.danger-btn>button { background:#991b1b !important; }
.success-btn>button { background:#065f46 !important; }

/* ── whatsapp button ── */
.wa-btn {
    display:block; text-align:center; background:#25D366; color:#fff !important;
    padding:11px; border-radius:9px; text-decoration:none; font-weight:700;
    font-family:'Rajdhani',sans-serif; font-size:1rem; letter-spacing:.4px;
    margin-top:.5rem;
}
.wa-btn:hover { background:#1ebe57; }

hr { border-color:#1e2d47; }

@media (max-width:600px){
    .top-banner .t { font-size:1.15rem; }
    [data-testid="stMetricValue"] { font-size:1.55rem !important; }
    .stTabs [data-baseweb="tab"] { padding:6px 9px !important; font-size:.8rem !important; }
}
</style>
""", unsafe_allow_html=True)

# ── Top banner ────────────────────────────────────────────────────────────────
st.markdown("""
<div class="top-banner">
  <span style="font-size:1.7rem;">⚡</span>
  <div>
    <p class="t">SMART METER FIELD TRACKER</p>
    <p class="s">Live via Google Sheets · Vijayawada</p>
  </div>
</div>
""", unsafe_allow_html=True)

# ── Google Sheets connection ──────────────────────────────────────────────────
conn = st.connection("gsheets", type=GSheetsConnection)

# ── Helpers ───────────────────────────────────────────────────────────────────

def get_data(worksheet: str) -> pd.DataFrame:
    try:
        df = conn.read(worksheet=worksheet, ttl=0)
        return df.astype(str).fillna("") if not df.empty else pd.DataFrame()
    except Exception:
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


# ── Tabs ──────────────────────────────────────────────────────────────────────
tab_dash, tab_inst, tab_inv, tab_admin = st.tabs([
    "📊 Dashboard", "🛠️ Installations", "📦 Inventory", "⚙️ Admin"
])


# ═══════════════════════════════════════════════════════════════════════════════
#  DASHBOARD
# ═══════════════════════════════════════════════════════════════════════════════
with tab_dash:

    df_inst = get_data("Installations")
    df_inv  = get_data("Inventory")

    # ── Inventory stock cards ─────────────────────────────────────
    st.markdown('<div class="sec-hdr">📦 Inventory Stock</div>', unsafe_allow_html=True)

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
            csv_data = group_df.to_csv(index=False).encode("utf-8")
            st.download_button("📥 Download CSV", data=csv_data,
                               file_name="Installation_Summary.csv", mime="text/csv",
                               use_container_width=True)

            date_str = f"{d_start} to {d_end}" if d_start != d_end else str(d_start)
            loc_str  = ", ".join(loc_filter) if loc_filter else "All Locations"

            wa_lines = [f"📅 *Date:* {date_str} | *{loc_str}*\n"]
            for _, row in group_df.iterrows():
                q1_str = str(int(row["1PH"])) if show_1ph else "—"
                q3_str = str(int(row["3PH"])) if show_3ph else "—"
                wa_lines.append(f"*{row['Technician']}* ({row['Location']}) → 1PH: {q1_str}, 3PH: {q3_str}")
            wa_lines.append(f"\n*Total 1PH:* {sum_1ph} | *Total 3PH:* {sum_3ph} | *Grand Total:* {sum_1ph + sum_3ph}")

            wa_text = "\n".join(wa_lines)
            wa_url  = f"https://wa.me/?text={urllib.parse.quote(wa_text)}"
            st.markdown(
                f'<a href="{wa_url}" target="_blank" class="wa-btn">💬 Share Summary via WhatsApp</a>',
                unsafe_allow_html=True,
            )
        else:
            st.info("No records match the selected filters.")


# ═══════════════════════════════════════════════════════════════════════════════
#  INSTALLATIONS
# ═══════════════════════════════════════════════════════════════════════════════
with tab_inst:

    df_techs = get_data("Technicians")
    df_locs  = get_data("Locations")

    # BUG FIX 1: Safely handle "1", "1.0", "True" active states from Google Sheets
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
            f_sub = st.form_submit_button("💾 Submit Entry")

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
                    # BUG FIX 2: Manually clear Streamlit cache after every update
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
                f'<div class="warn-box">⚠️ Editing / deleting: <b>{curr_row["tech_name"]}</b>'
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
                    do_update = st.form_submit_button("✏️ Update Entry")
                with btn_delete:
                    do_delete = st.form_submit_button("🗑️ Delete Entry")

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
                f' on <b>{del_date}</b>? This cannot be undone.</div>',
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

    st.markdown('<div class="sec-hdr">📥 Inward Material from Store</div>', unsafe_allow_html=True)

    with st.form("inv_form", clear_on_submit=True):
        iv1, iv2 = st.columns(2)
        with iv1:
            idate = st.date_input("Received Date", date.today())
            itype = st.selectbox("Type", ["1 PH", "3 PH"])
        with iv2:
            iqty  = st.number_input("Quantity", min_value=1, step=1, value=1)
            imrn  = st.text_input("MRN No.")
        imake = st.selectbox("Make", ["Schneider", "Genus", "Other"])
        iv_sub = st.form_submit_button("📥 Add to Stock")

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

    st.markdown('<div class="sec-hdr">📊 Stock Summary</div>', unsafe_allow_html=True)
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
                f'<div class="warn-box">⚠️ Editing / deleting: MRN <b>{inv_row.get("mrn","")}</b>'
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
                    inv_do_update = st.form_submit_button("✏️ Update")
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
    <div class="warn-box" style="background:#0d1f35;border-color:#2563eb;color:#7fb3f5;">
    💡 <b>Tip:</b> Tap a cell to type, tap <b>+</b> at the bottom to add a row.
    Set <b>Active?</b> to <code>0</code> to hide a technician from entry forms.
    </div>
    """, unsafe_allow_html=True)

    subtab_tech, subtab_loc = st.tabs(["👷 Technicians", "📍 Locations"])

    # ── Technicians ───────────────────────────────────────────────
    with subtab_tech:
        st.markdown('<div class="sec-hdr">Manage Technicians</div>', unsafe_allow_html=True)
        df_t = get_data("Technicians")
        if df_t.empty:
            df_t = pd.DataFrame(columns=["name", "phone", "aadhar", "is_active"])

        edited_techs = st.data_editor(
            df_t,
            num_rows="dynamic",
            use_container_width=True,
            hide_index=True,
            column_config={
                "name"     : st.column_config.TextColumn("Name",       required=True),
                "phone"    : st.column_config.TextColumn("Phone",      required=True),
                "aadhar"   : st.column_config.TextColumn("Aadhar No.", required=True),
                "is_active": st.column_config.SelectboxColumn(
                    "Active?", options=["1", "0"], required=True
                ),
            },
        )

        if st.button("💾 Save Technician Changes", key="save_techs"):
            # 1. Fresh copy
            clean_techs = edited_techs.copy()
            # 2. Fill invisible NaNs with blanks
            clean_techs = clean_techs.fillna("")
            # 3. Force entire table to pure strings
            clean_techs = clean_techs.astype(str)
            # 4. Strip invisible whitespace from names
            clean_techs["name"] = clean_techs["name"].str.strip()
            # 5. Drop completely empty names
            clean_techs = clean_techs[clean_techs["name"] != ""]
            # 6. Reset the Pandas index so Google Sheets can read it (CRITICAL FIX)
            clean_techs = clean_techs.reset_index(drop=True)
            
            if clean_techs.empty:
                st.error("❌ Cannot save an empty table. Add at least one technician.")
            else:
                conn.update(worksheet="Technicians", data=clean_techs)
                st.cache_data.clear()
                st.success("✅ Technicians saved.")
                st.rerun()

    # ── Locations ─────────────────────────────────────────────────
    with subtab_loc:
        st.markdown('<div class="sec-hdr">Manage Locations</div>', unsafe_allow_html=True)
        df_l = get_data("Locations")
        if df_l.empty:
            df_l = pd.DataFrame(columns=["location_name"])

        edited_locs = st.data_editor(
            df_l,
            num_rows="dynamic",
            use_container_width=True,
            hide_index=True,
            column_config={
                "location_name": st.column_config.TextColumn("Location Name", required=True),
            },
        )

        if st.button("💾 Save Location Changes", key="save_locs"):
            # 1. Fresh copy
            clean_locs = edited_locs.copy()
            # 2. Fill invisible NaNs with blanks
            clean_locs = clean_locs.fillna("")
            # 3. Force entire table to pure strings
            clean_locs = clean_locs.astype(str)
            # 4. Strip invisible whitespace
            clean_locs["location_name"] = clean_locs["location_name"].str.strip()
            # 5. Drop completely empty names
            clean_locs = clean_locs[clean_locs["location_name"] != ""]
            # 6. Reset the Pandas index so Google Sheets can read it (CRITICAL FIX)
            clean_locs = clean_locs.reset_index(drop=True)
            
            if clean_locs.empty:
                st.error("❌ Cannot save an empty table. Add at least one location.")
            else:
                conn.update(worksheet="Locations", data=clean_locs)
                st.cache_data.clear()
                st.success("✅ Locations saved.")
                st.rerun()
