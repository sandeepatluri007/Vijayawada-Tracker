import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
from datetime import date
import urllib.parse
import math

# ==========================================
# UI Configuration
# ==========================================
st.set_page_config(page_title="Field Meter Tracker", page_icon="⚡", layout="centered")

st.markdown("""
    <style>
    [data-testid="stMetricValue"] { font-size: 24px; }
    .stButton>button { width: 100%; border-radius: 5px; height: 3em; background-color: #007bff; color: white; }
    .save-btn>button { background-color: #28a745; }
    </style>
""", unsafe_allow_html=True)

st.title("⚡ Smart Meter Field Tracker")

# Create Connection
conn = st.connection("gsheets", type=GSheetsConnection)

def get_data(worksheet):
    try:
        # Force all incoming data to be strings to prevent Pandas TypeErrors
        return conn.read(worksheet=worksheet, ttl="0").astype(str).fillna("")
    except Exception:
        return pd.DataFrame()

# ==========================================
# Tabs
# ==========================================
tab_dash, tab_inst, tab_inv, tab_admin = st.tabs(["📊 Dashboard", "🛠️ Installation", "📦 Inventory", "⚙️ Admin"])

# ------------------------------------------
# 1. Dashboard Tab (Template 2 WhatsApp)
# ------------------------------------------
with tab_dash:
    df_inst = get_data("Installations")
    df_inv = get_data("Inventory")
    
    if df_inst.empty or df_inv.empty:
        st.info("Awaiting initial data. Please add Admin data and Inventory first.")
    else:
        st.subheader("Inventory Status")
        total_in_1ph = pd.to_numeric(df_inv[df_inv['type'] == '1 PH']['qty'], errors='coerce').sum()
        total_in_3ph = pd.to_numeric(df_inv[df_inv['type'] == '3 PH']['qty'], errors='coerce').sum()
        total_out_1ph = pd.to_numeric(df_inst['qty_1ph'], errors='coerce').sum()
        total_out_3ph = pd.to_numeric(df_inst['qty_3ph'], errors='coerce').sum()

        c1, c2 = st.columns(2)
        c1.metric("Pending 1PH", int(total_in_1ph - total_out_1ph))
        c2.metric("Pending 3PH", int(total_in_3ph - total_out_3ph))
        
        st.divider()
        st.subheader("Installation Summary & Filters")
        
        f_col1, f_col2 = st.columns(2)
        with f_col1:
            date_range = st.date_input("Date Range", [date.today(), date.today()])
        with f_col2:
            meter_filter = st.multiselect("Meter Type", ["1 PH", "3 PH"], default=["1 PH", "3 PH"])
        
        loc_list = [loc for loc in df_inst['location'].unique().tolist() if loc.strip() != ""]
        tech_list = [tech for tech in df_inst['tech_name'].unique().tolist() if tech.strip() != ""]
        
        f_col3, f_col4 = st.columns(2)
        with f_col3:
            loc_filter = st.multiselect("Locations", loc_list, default=loc_list)
        with f_col4:
            tech_filter = st.multiselect("Technicians", tech_list, default=tech_list)

        filtered_df = df_inst.copy()
        if len(date_range) == 2:
            filtered_df['date_obj'] = pd.to_datetime(filtered_df['date']).dt.date
            filtered_df = filtered_df[(filtered_df['date_obj'] >= date_range[0]) & (filtered_df['date_obj'] <= date_range[1])]
        
        if loc_filter:
            filtered_df = filtered_df[filtered_df['location'].isin(loc_filter)]
        if tech_filter:
            filtered_df = filtered_df[filtered_df['tech_name'].isin(tech_filter)]

        show_1ph = "1 PH" in meter_filter
        show_3ph = "3 PH" in meter_filter
        
        filtered_df['qty_1ph'] = pd.to_numeric(filtered_df['qty_1ph'], errors='coerce').fillna(0)
        filtered_df['qty_3ph'] = pd.to_numeric(filtered_df['qty_3ph'], errors='coerce').fillna(0)

        m1, m2 = st.columns(2)
        sum_1ph = int(filtered_df['qty_1ph'].sum()) if show_1ph else 0
        sum_3ph = int(filtered_df['qty_3ph'].sum()) if show_3ph else 0
        m1.metric("Filtered 1PH Installed", sum_1ph)
        m2.metric("Filtered 3PH Installed", sum_3ph)

        if not filtered_df.empty:
            st.subheader("Technician Breakdown")
            group_df = filtered_df.groupby(['tech_name', 'location'])[['qty_1ph', 'qty_3ph']].sum().reset_index()
            group_df['Total'] = group_df['qty_1ph'] + group_df['qty_3ph']
            st.dataframe(group_df, use_container_width=True)

            st.subheader("Export & Share")
            csv_data = group_df.to_csv(index=False).encode('utf-8')
            st.download_button("📥 Download Summary as CSV (Print to PDF from Excel)", data=csv_data, file_name="Installation_Summary.csv", mime="text/csv")

            # WhatsApp Template 2
            date_string = f"{date_range[0]} to {date_range[1]}" if len(date_range) == 2 else str(date_range[0])
            loc_string = ", ".join(loc_filter) if loc_filter else "Vijayawada"
            
            wa_text = f"📅 *Date:* {date_string} | *{loc_string}*\n\n"
            for index, row in group_df.iterrows():
                wa_text += f"*{row['tech_name']}* ({row['location']}) -> 1PH: {int(row['qty_1ph']) if show_1ph else 0}, 3PH: {int(row['qty_3ph']) if show_3ph else 0}\n"
            
            wa_text += f"\n*Total 1PH:* {sum_1ph} | *Total 3PH:* {sum_3ph} | *Grand Total:* {sum_1ph + sum_3ph}"
            
            wa_url = f"https://wa.me/?text={urllib.parse.quote(wa_text)}"
            st.markdown(f'<a href="{wa_url}" target="_blank" style="display: block; text-align: center; background-color: #25D366; color: white; padding: 10px; border-radius: 5px; text-decoration: none; font-weight: bold;">💬 Share to WhatsApp</a>', unsafe_allow_html=True)

# ------------------------------------------
# 2. Installations Tab
# ------------------------------------------
with tab_inst:
    st.header("Daily Entry")
    df_techs = get_data("Technicians")
    df_locs = get_data("Locations")
    
    active_techs = df_techs[df_techs['is_active'] == "1"]['name'].tolist() if not df_techs.empty and 'is_active' in df_techs.columns else []
    active_locs = df_locs['location_name'].dropna().tolist() if not df_locs.empty else []

    if not active_techs or not active_locs:
        st.warning("Please add Active Technicians and Locations in the Admin tab first.")
    else:
        with st.form("inst_form"):
            entry_date = st.date_input("Installation Date", date.today())
            tech = st.selectbox("Technician", active_techs)
            loc = st.selectbox("Location", active_locs)
            c1, c2 = st.columns(2)
            q1 = c1.number_input("1 PH Qty", min_value=0, step=1)
            q3 = c2.number_input("3 PH Qty", min_value=0, step=1)
            
            if st.form_submit_button("Submit Data"):
                df_existing = get_data("Installations")
                is_dup = not df_existing[(df_existing['date'] == str(entry_date)) & (df_existing['tech_name'] == str(tech))].empty
                if is_dup:
                    st.error(f"Entry already exists for {tech} on {entry_date}. Edit below.")
                else:
                    new_row = pd.DataFrame([{"date": str(entry_date), "tech_name": str(tech), "location": str(loc), "qty_1ph": str(q1), "qty_3ph": str(q3)}])
                    updated_df = pd.concat([df_existing, new_row], ignore_index=True)
                    conn.update(worksheet="Installations", data=updated_df.astype(str))
                    st.success("Entry Saved!")
                    st.rerun()

    st.divider()
    st.subheader("Recent Logs & Edits")
    
    log_data = get_data("Installations")
    if not log_data.empty:
        log_data_sorted = log_data.iloc[::-1].reset_index(drop=True)
        items_per_page = 10
        total_pages = max(1, math.ceil(len(log_data_sorted) / items_per_page))
        page = st.number_input("Page", min_value=1, max_value=total_pages, step=1)
        
        start_idx = (page - 1) * items_per_page
        end_idx = start_idx + items_per_page
        st.dataframe(log_data_sorted.iloc[start_idx:end_idx], use_container_width=True)

        st.caption("To edit or delete an entry, select it below:")
        log_options = [f"{row['date']} | {row['tech_name']}" for index, row in log_data_sorted.iterrows()]
        target_log = st.selectbox("Select Record", ["-- Select --"] + log_options)

        if target_log != "-- Select --":
            t_date, t_tech = target_log.split(" | ")
            curr_row = log_data[(log_data['date'] == t_date) & (log_data['tech_name'] == t_tech)].iloc[0]
            
            with st.form("edit_log"):
                e_loc = st.selectbox("Location", active_locs, index=active_locs.index(curr_row['location']) if curr_row['location'] in active_locs else 0)
                e_q1 = st.number_input("1 PH Qty", min_value=0, step=1, value=int(curr_row['qty_1ph']) if curr_row['qty_1ph'] else 0)
                e_q3 = st.number_input("3 PH Qty", min_value=0, step=1, value=int(curr_row['qty_3ph']) if curr_row['qty_3ph'] else 0)
                
                col_up, col_del = st.columns(2)
                with col_up:
                    if st.form_submit_button("Update Entry"):
                        mask = (log_data['date'] == t_date) & (log_data['tech_name'] == t_tech)
                        log_data.loc[mask, ['location', 'qty_1ph', 'qty_3ph']] = [str(e_loc), str(e_q1), str(e_q3)]
                        conn.update(worksheet="Installations", data=log_data.astype(str))
                        st.success("Updated!")
                        st.rerun()
                with col_del:
                    if st.form_submit_button("🗑️ Delete Entry", type="primary"):
                        mask = (log_data['date'] == t_date) & (log_data['tech_name'] == t_tech)
                        log_data = log_data[~mask]
                        conn.update(worksheet="Installations", data=log_data.astype(str))
                        st.success("Deleted!")
                        st.rerun()

# ------------------------------------------
# 3. Inventory Tab
# ------------------------------------------
with tab_inv:
    st.header("Material Inward")
    with st.form("inv_form"):
        idate = st.date_input("Received Date", date.today())
        itype = st.selectbox("Type", ["1 PH", "3 PH"])
        iqty = st.number_input("Quantity", min_value=1)
        imrn = st.text_input("MRN No")
        imake = st.selectbox("Make", ["Schneider", "Genus"])
        if st.form_submit_button("Add to Stock"):
            df_inv_exist = get_data("Inventory")
            new_inv = pd.DataFrame([{"date": str(idate), "type": str(itype), "qty": str(iqty), "mrn": str(imrn), "make": str(imake)}])
            conn.update(worksheet="Inventory", data=pd.concat([df_inv_exist, new_inv]).astype(str))
            st.success("Stock Inwarded!")
            st.rerun()

# ------------------------------------------
# 4. Admin Tab (Simplified Editor)
# ------------------------------------------
with tab_admin:
    st.caption("✨ **Pro Tip:** You can edit these tables directly. Tap a cell to type, click the '+' at the bottom to add a row, or select a row to delete it.")
    subtab_tech, subtab_loc = st.tabs(["👷 Technicians", "📍 Locations"])
    
    # --- TECHNICIANS SUBTAB ---
    with subtab_tech:
        st.subheader("Manage Technicians")
        df_t = get_data("Technicians")
        
        # If empty, create an empty structure
        if df_t.empty:
            df_t = pd.DataFrame(columns=["name", "phone", "aadhar", "is_active"])
            
        edited_techs = st.data_editor(
            df_t, 
            num_rows="dynamic", 
            use_container_width=True, 
            hide_index=True,
            column_config={
                "is_active": st.column_config.SelectboxColumn("Active?", options=["1", "0"], required=True)
            }
        )
        
        st.markdown('<div class="save-btn">', unsafe_allow_html=True)
        if st.button("💾 Save Technician Changes", use_container_width=True):
            conn.update(worksheet="Technicians", data=edited_techs.astype(str))
            st.success("Technicians updated successfully!")
            st.rerun()
        st.markdown('</div>', unsafe_allow_html=True)

    # --- LOCATIONS SUBTAB ---
    with subtab_loc:
        st.subheader("Manage Locations")
        df_l = get_data("Locations")
        
        if df_l.empty:
             df_l = pd.DataFrame(columns=["location_name"])
             
        edited_locs = st.data_editor(df_l, num_rows="dynamic", use_container_width=True, hide_index=True)
        
        st.markdown('<div class="save-btn">', unsafe_allow_html=True)
        if st.button("💾 Save Location Changes", use_container_width=True):
            conn.update(worksheet="Locations", data=edited_locs.astype(str))
            st.success("Locations updated successfully!")
            st.rerun()
        st.markdown('</div>', unsafe_allow_html=True)
