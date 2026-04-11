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
    </style>
""", unsafe_allow_html=True)

st.title("⚡ Vijayawada Tracker")

# Create Connection
conn = st.connection("gsheets", type=GSheetsConnection)

def get_data(worksheet):
    try:
        return conn.read(worksheet=worksheet, ttl="0").fillna("")
    except Exception:
        return pd.DataFrame()

# ==========================================
# Tabs
# ==========================================
tab_dash, tab_inst, tab_inv, tab_admin = st.tabs(["📊 Dashboard", "🛠️ Installation", "📦 Inventory", "⚙️ Admin"])

# ------------------------------------------
# 1. Dashboard Tab (Updated with Filters & Export)
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
        
        # Filters
        f_col1, f_col2 = st.columns(2)
        with f_col1:
            date_range = st.date_input("Date Range", [date.today(), date.today()])
        with f_col2:
            meter_filter = st.multiselect("Meter Type", ["1 PH", "3 PH"], default=["1 PH", "3 PH"])
        
        loc_list = df_inst['location'].unique().tolist()
        tech_list = df_inst['tech_name'].unique().tolist()
        
        f_col3, f_col4 = st.columns(2)
        with f_col3:
            loc_filter = st.multiselect("Locations", loc_list, default=loc_list)
        with f_col4:
            tech_filter = st.multiselect("Technicians", tech_list, default=tech_list)

        # Apply Filters
        filtered_df = df_inst.copy()
        if len(date_range) == 2:
            filtered_df['date_obj'] = pd.to_datetime(filtered_df['date']).dt.date
            filtered_df = filtered_df[(filtered_df['date_obj'] >= date_range[0]) & (filtered_df['date_obj'] <= date_range[1])]
        
        if loc_filter:
            filtered_df = filtered_df[filtered_df['location'].isin(loc_filter)]
        if tech_filter:
            filtered_df = filtered_df[filtered_df['tech_name'].isin(tech_filter)]

        # Meter Type Toggle
        show_1ph = "1 PH" in meter_filter
        show_3ph = "3 PH" in meter_filter
        
        filtered_df['qty_1ph'] = pd.to_numeric(filtered_df['qty_1ph'], errors='coerce').fillna(0)
        filtered_df['qty_3ph'] = pd.to_numeric(filtered_df['qty_3ph'], errors='coerce').fillna(0)

        # Render Metrics
        m1, m2 = st.columns(2)
        sum_1ph = int(filtered_df['qty_1ph'].sum()) if show_1ph else 0
        sum_3ph = int(filtered_df['qty_3ph'].sum()) if show_3ph else 0
        m1.metric("Filtered 1PH Installed", sum_1ph)
        m2.metric("Filtered 3PH Installed", sum_3ph)

        # Group by Technician
        if not filtered_df.empty:
            st.subheader("Technician Breakdown")
            group_df = filtered_df.groupby('tech_name')[['qty_1ph', 'qty_3ph']].sum().reset_index()
            group_df['Total'] = group_df['qty_1ph'] + group_df['qty_3ph']
            st.dataframe(group_df, use_container_width=True)

            # Export Section
            st.subheader("Export & Share")
            
            # 1. CSV Download
            csv_data = group_df.to_csv(index=False).encode('utf-8')
            st.download_button("📥 Download Summary as CSV (Print to PDF from Excel)", data=csv_data, file_name="Installation_Summary.csv", mime="text/csv")

            # 2. WhatsApp Generation
            loc_string = ", ".join(loc_filter) if loc_filter else "All Locations"
            date_string = f"{date_range[0]} to {date_range[1]}" if len(date_range) == 2 else str(date_range[0])
            
            wa_text = f"*Vijayawada - ({loc_string})*\n*Date:* {date_string}\n\n"
            for index, row in group_df.iterrows():
                wa_text += f"👷 *{row['tech_name']}:*\n"
                wa_text += f"1 PH: {int(row['qty_1ph'])} | 3 PH: {int(row['qty_3ph'])} | Total: {int(row['Total'])}\n\n"
            
            wa_text += f"📊 *OVERALL SUM:*\nTotal 1 PH: {sum_1ph}\nTotal 3 PH: {sum_3ph}\n*Grand Total: {sum_1ph + sum_3ph}*"
            
            wa_url = f"https://wa.me/?text={urllib.parse.quote(wa_text)}"
            st.markdown(f'<a href="{wa_url}" target="_blank" style="display: block; text-align: center; background-color: #25D366; color: white; padding: 10px; border-radius: 5px; text-decoration: none; font-weight: bold;">💬 Share Summary to WhatsApp</a>', unsafe_allow_html=True)


# ------------------------------------------
# 2. Installations Tab (Unchanged from previous update)
# ------------------------------------------
with tab_inst:
    st.header("Daily Entry")
    df_techs = get_data("Technicians")
    df_locs = get_data("Locations")
    
    active_techs = df_techs[df_techs['is_active'] == 1]['name'].tolist() if not df_techs.empty else []
    active_locs = df_locs['location_name'].dropna().tolist() if not df_locs.empty else []

    if not active_techs or not active_locs:
        st.warning("Please add Technicians and Locations in the Admin tab first.")
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
                is_dup = not df_existing[(df_existing['date'] == str(entry_date)) & (df_existing['tech_name'] == tech)].empty
                if is_dup:
                    st.error(f"Entry already exists for {tech} on {entry_date}. Use the Edit menu below.")
                else:
                    new_row = pd.DataFrame([{"date": str(entry_date), "tech_name": tech, "location": loc, "qty_1ph": q1, "qty_3ph": q3}]).fillna("")
                    updated_df = pd.concat([df_existing, new_row], ignore_index=True)
                    conn.update(worksheet="Installations", data=updated_df)
                    st.success("Entry Saved to Cloud!")
                    st.rerun()

    st.divider()
    st.subheader("Installation Logs")
    
    log_data = get_data("Installations")
    if not log_data.empty:
        log_data_sorted = log_data.iloc[::-1].reset_index(drop=True)
        items_per_page = 10
        total_pages = max(1, math.ceil(len(log_data_sorted) / items_per_page))
        page_col, empty_col = st.columns([1, 3])
        with page_col:
            page = st.number_input("Page", min_value=1, max_value=total_pages, step=1)
        
        start_idx = (page - 1) * items_per_page
        end_idx = start_idx + items_per_page
        st.dataframe(log_data_sorted.iloc[start_idx:end_idx], use_container_width=True)

        st.divider()
        st.subheader("Edit / Delete Log")
        log_options = [f"{row['date']} | {row['tech_name']}" for index, row in log_data_sorted.iterrows()]
        target_log = st.selectbox("Select Record to Manage", ["-- Select --"] + log_options)

        if target_log != "-- Select --":
            target_date = target_log.split(" | ")[0]
            target_tech = target_log.split(" | ")[1]
            current_row = log_data[(log_data['date'] == target_date) & (log_data['tech_name'] == target_tech)].iloc[0]
            
            with st.expander("📝 Edit Entry"):
                with st.form("edit_form"):
                    e_loc = st.selectbox("Location", active_locs, index=active_locs.index(current_row['location']) if current_row['location'] in active_locs else 0)
                    e_q1 = st.number_input("1 PH Qty", min_value=0, step=1, value=int(current_row['qty_1ph']))
                    e_q3 = st.number_input("3 PH Qty", min_value=0, step=1, value=int(current_row['qty_3ph']))
                    
                    if st.form_submit_button("Update Entry"):
                        mask = (log_data['date'] == target_date) & (log_data['tech_name'] == target_tech)
                        log_data.loc[mask, ['location', 'qty_1ph', 'qty_3ph']] = [e_loc, e_q1, e_q3]
                        conn.update(worksheet="Installations", data=log_data.fillna(""))
                        st.success("Entry Updated!")
                        st.rerun()

            with st.expander("🗑️ Delete Entry"):
                st.warning("Are you sure you want to delete this record?")
                if st.toggle("Slide to unlock Delete button"):
                    if st.button("Permanently Delete Entry", type="primary"):
                        mask = (log_data['date'] == target_date) & (log_data['tech_name'] == target_tech)
                        updated_logs = log_data[~mask]
                        conn.update(worksheet="Installations", data=updated_logs.fillna(""))
                        st.success("Entry Deleted!")
                        st.rerun()

# ------------------------------------------
# 3. Inventory Tab (Unchanged)
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
            new_inv = pd.DataFrame([{"date": str(idate), "type": itype, "qty": iqty, "mrn": imrn, "make": imake}]).fillna("")
            conn.update(worksheet="Inventory", data=pd.concat([df_inv_exist, new_inv]))
            st.success("Stock Inwarded!")
            st.rerun()

# ------------------------------------------
# 4. Admin Tab (Updated with Edit/Logs)
# ------------------------------------------
with tab_admin:
    subtab_tech, subtab_loc = st.tabs(["👷 Technicians", "📍 Locations"])
    
    # --- TECHNICIANS SUBTAB ---
    with subtab_tech:
        st.header("Add Technician")
        with st.form("tech_form"):
            tname = st.text_input("Tech Name")
            tph = st.text_input("Phone")
            taad = st.text_input("Aadhar (Optional)")
            if st.form_submit_button("Register Technician"):
                if tname and tph:
                    df_t = get_data("Technicians")
                    new_t = pd.DataFrame([{"name": tname, "phone": tph, "aadhar": taad, "is_active": 1}]).fillna("")
                    conn.update(worksheet="Technicians", data=pd.concat([df_t, new_t]))
                    st.success("Tech Registered!")
                    st.rerun()
                else:
                    st.error("Name and Phone are mandatory.")

        st.divider()
        st.subheader("Technician Directory")
        df_t_show = get_data("Technicians")
        if not df_t_show.empty:
            st.dataframe(df_t_show[['name', 'phone', 'aadhar', 'is_active']], use_container_width=True)
            
            with st.expander("Edit / Manage Technician"):
                t_target = st.selectbox("Select Technician", ["-- Select --"] + df_t_show['name'].tolist())
                if t_target != "-- Select --":
                    curr_t = df_t_show[df_t_show['name'] == t_target].iloc[0]
                    with st.form("edit_t_form"):
                        e_tph = st.text_input("Phone", value=str(curr_t['phone']))
                        e_taad = st.text_input("Aadhar", value=str(curr_t['aadhar']))
                        e_act = st.checkbox("Active (Uncheck to hide from lists)", value=bool(curr_t['is_active'] == 1))
                        
                        if st.form_submit_button("Update Details"):
                            mask = df_t_show['name'] == t_target
                            df_t_show.loc[mask, ['phone', 'aadhar', 'is_active']] = [e_tph, e_taad, 1 if e_act else 0]
                            conn.update(worksheet="Technicians", data=df_t_show.fillna(""))
                            st.success("Technician Updated!")
                            st.rerun()

    # --- LOCATIONS SUBTAB ---
    with subtab_loc:
        st.header("Add Location")
        with st.form("loc_form"):
            lname = st.text_input("Location Name / Ward / Area")
            if st.form_submit_button("Add Location"):
                if lname:
                    df_l = get_data("Locations")
                    new_l = pd.DataFrame([{"location_name": lname}]).fillna("")
                    conn.update(worksheet="Locations", data=pd.concat([df_l, new_l]))
                    st.success(f"Location {lname} Added!")
                    st.rerun()
                else:
                    st.error("Location name cannot be blank.")
        
        st.divider()
        st.subheader("Current Locations")
        df_l_show = get_data("Locations")
        if not df_l_show.empty:
            st.dataframe(df_l_show, use_container_width=True)
            
            with st.expander("Edit Location"):
                l_target = st.selectbox("Select Location", ["-- Select --"] + df_l_show['location_name'].tolist())
                if l_target != "-- Select --":
                    with st.form("edit_l_form"):
                        e_lname = st.text_input("Rename Location", value=l_target)
                        if st.form_submit_button("Update Location Name"):
                            mask = df_l_show['location_name'] == l_target
                            df_l_show.loc[mask, 'location_name'] = e_lname
                            conn.update(worksheet="Locations", data=df_l_show.fillna(""))
                            st.success("Location Updated!")
                            st.rerun()
