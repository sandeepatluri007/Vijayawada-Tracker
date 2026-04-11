import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
from datetime import date

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

# Helper to fetch data from specific worksheets
def get_data(worksheet):
    return conn.read(worksheet=worksheet, ttl="0")

# ==========================================
# Tabs
# ==========================================
tab_dash, tab_inst, tab_inv, tab_tech = st.tabs(["📊 Dashboard", "🛠️ Installation", "📦 Inventory", "👷 Techs"])

# ------------------------------------------
# 1. Dashboard Tab
# ------------------------------------------
with tab_dash:
    try:
        df_inst = get_data("Installations")
        df_inv = get_data("Inventory")
        
        st.subheader("Inventory Status")
        # Calc live stock
        total_in_1ph = df_inv[df_inv['type'] == '1 PH']['qty'].sum()
        total_in_3ph = df_inv[df_inv['type'] == '3 PH']['qty'].sum()
        total_out_1ph = df_inst['qty_1ph'].sum()
        total_out_3ph = df_inst['qty_3ph'].sum()

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
            m1.metric("1PH Installed", int(filtered_df['qty_1ph'].sum()))
            m2.metric("3PH Installed", int(filtered_df['qty_3ph'].sum()))
    except:
        st.info("No data found. Please add Technicians and Inventory first.")

# ------------------------------------------
# 2. Installations Tab
# ------------------------------------------
with tab_inst:
    st.header("Daily Entry")
    df_techs = get_data("Technicians")
    active_techs = df_techs[df_techs['is_active'] == 1]['name'].tolist() if not df_techs.empty else []

    if not active_techs:
        st.warning("No technicians found. Add them in the Techs tab.")
    else:
        with st.form("inst_form"):
            entry_date = st.date_input("Installation Date", date.today())
            tech = st.selectbox("Technician", active_techs)
            c1, c2 = st.columns(2)
            q1 = c1.number_input("1 PH Qty", min_value=0, step=1)
            q3 = c2.number_input("3 PH Qty", min_value=0, step=1)
            
            if st.form_submit_button("Submit Data"):
                # Duplicate Check
                df_existing = get_data("Installations")
                is_dup = not df_existing[(df_existing['date'] == str(entry_date)) & (df_existing['tech_name'] == tech)].empty
                
                if is_dup:
                    st.error(f"Entry already exists for {tech} on {entry_date}. Delete/Edit below.")
                else:
                    new_row = pd.DataFrame([{"date": str(entry_date), "tech_name": tech, "qty_1ph": q1, "qty_3ph": q3}])
                    updated_df = pd.concat([df_existing, new_row], ignore_index=True)
                    conn.update(worksheet="Installations", data=updated_df)
                    st.success("Entry Saved to Cloud!")
                    st.rerun()

    st.divider()
    st.subheader("Recent Logs")
    log_data = get_data("Installations")
    if not log_data.empty:
        st.dataframe(log_data.iloc[::-1], use_container_width=True)
        if st.button("Delete Last Entry"):
            st.warning("Deleting the most recent entry...")
            conn.update(worksheet="Installations", data=log_data.iloc[:-1])
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
            new_inv = pd.DataFrame([{"date": str(idate), "type": itype, "qty": iqty, "mrn": imrn, "make": imake}])
            conn.update(worksheet="Inventory", data=pd.concat([df_inv_exist, new_inv]))
            st.success("Stock Inwarded!")
            st.rerun()

# ------------------------------------------
# 4. Technicians Tab
# ------------------------------------------
with tab_tech:
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