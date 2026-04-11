import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
from datetime import date
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

st.title("⚡ Smart Meter Field Tracker")

# Create Connection
conn = st.connection("gsheets", type=GSheetsConnection)

def get_data(worksheet):
    return conn.read(worksheet=worksheet, ttl="0")

# ==========================================
# Tabs
# ==========================================
tab_dash, tab_inst, tab_inv, tab_admin = st.tabs(["📊 Dashboard", "🛠️ Installation", "📦 Inventory", "⚙️ Admin"])

# ------------------------------------------
# 1. Dashboard Tab (Unchanged)
# ------------------------------------------
with tab_dash:
    try:
        df_inst = get_data("Installations")
        df_inv = get_data("Inventory")
        
        st.subheader("Inventory Status")
        total_in_1ph = pd.to_numeric(df_inv[df_inv['type'] == '1 PH']['qty'], errors='coerce').sum()
        total_in_3ph = pd.to_numeric(df_inv[df_inv['type'] == '3 PH']['qty'], errors='coerce').sum()
        total_out_1ph = pd.to_numeric(df_inst['qty_1ph'], errors='coerce').sum()
        total_out_3ph = pd.to_numeric(df_inst['qty_3ph'], errors='coerce').sum()

        c1, c2 = st.columns(2)
        c1.metric("Pending 1PH", int(total_in_1ph - total_out_1ph))
        c2.metric("Pending 3PH", int(total_in_3ph - total_out_3ph))
        
        st.divider()
        st.subheader("Installation Summary")
        date_range = st.date_input("Date Range", [date.today().replace(day=1), date.today()])
        
        if len(date_range) == 2:
            mask = (pd.to_datetime(df_inst['date']).dt.date >= date_range[0]) & (pd.to_datetime(df_inst['date']).dt.date <= date_range[1])
            filtered_df = df_inst.loc[mask]
            
            m1, m2 = st.columns(2)
            m1.metric("1PH Installed", int(pd.to_numeric(filtered_df['qty_1ph'], errors='coerce').sum()))
            m2.metric("3PH Installed", int(pd.to_numeric(filtered_df['qty_3ph'], errors='coerce').sum()))
    except Exception as e:
        st.info("Awaiting initial data. Please add Admin data and Inventory first.")

# ------------------------------------------
# 2. Installations Tab (Updated)
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
                # Duplicate Check based on Date and Technician
                is_dup = not df_existing[(df_existing['date'] == str(entry_date)) & (df_existing['tech_name'] == tech)].empty
                
                if is_dup:
                    st.error(f"Entry already exists for {tech} on {entry_date}. Use the Edit menu below.")
                else:
                    new_row = pd.DataFrame([{"date": str(entry_date), "tech_name": tech, "location": loc, "qty_1ph": q1, "qty_3ph": q3}])
                    updated_df = pd.concat([df_existing, new_row], ignore_index=True)
                    conn.update(worksheet="Installations", data=updated_df)
                    st.success("Entry Saved to Cloud!")
                    st.rerun()

    st.divider()
    st.subheader("Installation Logs")
    
    log_data = get_data("Installations")
    if not log_data.empty:
        # Sort logs newest first
        log_data_sorted = log_data.iloc[::-1].reset_index(drop=True)
        
        # --- Pagination Logic ---
        items_per_page = 10
        total_pages = max(1, math.ceil(len(log_data_sorted) / items_per_page))
        
        # Move pagination controls above the table
        page_col, empty_col = st.columns([1, 3])
        with page_col:
            page = st.number_input("Page", min_value=1, max_value=total_pages, step=1)
        
        start_idx = (page - 1) * items_per_page
        end_idx = start_idx + items_per_page
        
        st.dataframe(log_data_sorted.iloc[start_idx:end_idx], use_container_width=True)

        st.divider()
        st.subheader("Edit / Delete Log")
        
        # Provide a list of entries to edit (Date - Tech)
        log_options = [f"{row['date']} | {row['tech_name']}" for index, row in log_data_sorted.iterrows()]
        target_log = st.selectbox("Select Record to Manage", ["-- Select --"] + log_options)

        if target_log != "-- Select --":
            target_date = target_log.split(" | ")[0]
            target_tech = target_log.split(" | ")[1]
            
            # Fetch current values for the selected row
            current_row = log_data[(log_data['date'] == target_date) & (log_data['tech_name'] == target_tech)].iloc[0]
            
            with st.expander("📝 Edit Entry"):
                with st.form("edit_form"):
                    e_loc = st.selectbox("Location", active_locs, index=active_locs.index(current_row['location']) if current_row['location'] in active_locs else 0)
                    e_q1 = st.number_input("1 PH Qty", min_value=0, step=1, value=int(current_row['qty_1ph']))
                    e_q3 = st.number_input("3 PH Qty", min_value=0, step=1, value=int(current_row['qty_3ph']))
                    
                    if st.form_submit_button("Update Entry"):
                        # Update the specific row in the dataframe
                        mask = (log_data['date'] == target_date) & (log_data['tech_name'] == target_tech)
                        log_data.loc[mask, ['location', 'qty_1ph', 'qty_3ph']] = [e_loc, e_q1, e_q3]
                        conn.update(worksheet="Installations", data=log_data)
                        st.success("Entry Updated!")
                        st.rerun()

            with st.expander("🗑️ Delete Entry"):
                st.warning("Are you sure you want to delete this record? This cannot be undone.")
                unlock_delete = st.toggle("Slide to unlock Delete button")
                if unlock_delete:
                    if st.button("Permanently Delete Entry", type="primary"):
                        mask = (log_data['date'] == target_date) & (log_data['tech_name'] == target_tech)
                        updated_logs = log_data[~mask]
                        conn.update(worksheet="Installations", data=updated_logs)
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
            new_inv = pd.DataFrame([{"date": str(idate), "type": itype, "qty": iqty, "mrn": imrn, "make": imake}])
            conn.update(worksheet="Inventory", data=pd.concat([df_inv_exist, new_inv]))
            st.success("Stock Inwarded!")
            st.rerun()

# ------------------------------------------
# 4. Admin Tab (Updated)
# ------------------------------------------
with tab_admin:
    subtab_tech, subtab_loc = st.tabs(["👷 Technicians", "📍 Locations"])
    
    with subtab_tech:
        st.header("Technician Management")
        with st.form("tech_form"):
            tname = st.text_input("Tech Name")
            tph = st.text_input("Phone")
            taad = st.text_input("Aadhar")
            if st.form_submit_button("Register Technician"):
                df_t = get_data("Technicians")
                new_t = pd.DataFrame([{"name": tname, "phone": tph, "aadhar": taad, "is_active": 1}])
                conn.update(worksheet="Technicians", data=pd.concat([df_t, new_t]))
                st.success("Tech Registered!")
                st.rerun()

    with subtab_loc:
        st.header("Location Management")
        with st.form("loc_form"):
            lname = st.text_input("Location Name / Ward / Area")
            if st.form_submit_button("Add Location"):
                df_l = get_data("Locations")
                new_l = pd.DataFrame([{"location_name": lname}])
                conn.update(worksheet="Locations", data=pd.concat([df_l, new_l]))
                st.success(f"Location {lname} Added!")
                st.rerun()
        
        st.divider()
        st.subheader("Current Locations")
        df_l_show = get_data("Locations")
        if not df_l_show.empty:
            st.dataframe(df_l_show, use_container_width=True)
