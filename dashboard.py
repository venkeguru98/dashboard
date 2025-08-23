import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from dash import Dash, dcc, html, dash_table, Input, Output, State, no_update, callback
import plotly.express as px
import plotly.graph_objects as go
import re
import dash_bootstrap_components as dbc
import os
import time

# --- Helper function to ensure unique column names ---
def make_unique_column_names(column_list):
    seen = {}
    unique_list = []
    for col in column_list:
        original_col_name = str(col).strip()
        current_col_name = original_col_name
        count = seen.get(original_col_name, 0)
        while current_col_name in unique_list:
            count += 1
            current_col_name = f"{original_col_name}_{count}"
        seen[original_col_name] = count
        unique_list.append(current_col_name)
    return unique_list

# --- Google Sheets Authentication and Data Retrieval ---
def load_data_from_google_sheets():
    df_icic = pd.DataFrame()
    df_canara = pd.DataFrame()
    df_investments = pd.DataFrame()
    error_message = None

    try:
        credentials_json = os.environ.get("GOOGLE_SHEETS_CREDENTIALS")
        if credentials_json:
            creds = Credentials.from_service_account_info(
                eval(credentials_json),
                scopes=["https://www.googleapis.com/auth/spreadsheets.readonly", "https://www.googleapis.com/auth/drive.readonly"]
            )
        else:
            SERVICE_ACCOUNT_FILE = os.environ.get("SERVICE_ACCOUNT_FILE_PATH")
            if SERVICE_ACCOUNT_FILE and os.path.exists(SERVICE_ACCOUNT_FILE):
                creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=["https://www.googleapis.com/auth/spreadsheets.readonly", "https://www.googleapis.com/auth/drive.readonly"])
            else:
                error_message = f"❌ Error: Google Sheets credentials not found. Set the GOOGLE_SHEETS_CREDENTIALS environment variable or a valid SERVICE_ACCOUNT_FILE_PATH."
                return df_icic, df_canara, df_investments, error_message
        
        client = gspread.authorize(creds)
        sheet_url = "https://docs.google.com/spreadsheets/d/1o1e8ouOghU_1L592pt_OSxn6aUSY5KNm1HOT6zbbQOA/edit?gid=1788780645#gid=1788780645"
        spreadsheet = client.open_by_url(sheet_url)
        
        try:
            worksheet_icic = spreadsheet.worksheet("ICIC salary")
            data_icic = worksheet_icic.get_all_values()
            df_raw_icic = pd.DataFrame(data_icic)
            df_icic, icic_error = process_icic_salary_data(df_raw_icic)
            if icic_error: print(f"ICIC Data Processing Warning: {icic_error}")
        except gspread.exceptions.WorksheetNotFound:
            print("Warning: 'ICIC salary' worksheet not found. Skipping ICIC data load.")
        except Exception as e:
            print(f"Error loading 'ICIC salary' sheet: {e}")

        try:
            worksheet_canara = spreadsheet.worksheet("CANARA")
            data_canara = worksheet_canara.get_all_values()
            df_raw_canara = pd.DataFrame(data_canara)
            df_canara, canara_error = process_canara_data(df_raw_canara)
            if canara_error: print(f"CANARA Data Processing Warning: {canara_error}")
        except gspread.exceptions.WorksheetNotFound:
            print("Warning: 'CANARA' worksheet not found. Skipping CANARA data load.")
        except Exception as e:
            print(f"Error loading 'CANARA' sheet: {e}")

        try:
            worksheet_investments = spreadsheet.worksheet("GOLD & LIC & DEPOSITS")
            data_investments = worksheet_investments.get_all_values()
            df_raw_investments = pd.DataFrame(data_investments)
            df_investments, investments_error = process_investments_data(df_raw_investments)
            if investments_error: print(f"Investments Data Processing Warning: {investments_error}")
        except gspread.exceptions.WorksheetNotFound:
            print("Warning: 'GOLD & LIC & DEPOSITS' worksheet not found. Skipping Investments data load.")
        except Exception as e:
            print(f"Error loading 'GOLD & LIC & DEPOSITS' sheet: {e}")

    except Exception as e:
        error_message = f"Error authenticating or retrieving Google Sheet: {e}. Check your JSON key and sheet URL."
        return df_icic, df_canara, df_investments, error_message
    
    return df_icic, df_canara, df_investments, error_message

def process_icic_salary_data(df_raw):
    df_result = pd.DataFrame()
    error_message = None
    if df_raw.empty: return df_result, "Raw DataFrame for ICIC is empty."
    category_header_row = -1
    for r_idx, row in df_raw.iterrows():
        row_upper = [str(x).strip().upper() for x in row.tolist()]
        if any("EXPENSES CATEGORY" in x for x in row_upper):
            category_header_row = r_idx
            break
    if category_header_row == -1:
        return pd.DataFrame(), "Could not find 'EXPENSES CATEGORY' header in ICIC sheet."
    else:
        raw_header_values = df_raw.iloc[category_header_row].tolist()
        unique_cols = make_unique_column_names(raw_header_values)
        df_data = pd.DataFrame(df_raw.iloc[category_header_row + 1:].values, columns=unique_cols)
        def is_category(colname: str) -> bool:
            return isinstance(colname, str) and ("EXPENSES CATEGORY" in colname.upper())
        def is_amount(colname: str) -> bool:
            return isinstance(colname, str) and ("AMOUNT SPENT IN" in colname.upper())
        cols = list(df_data.columns)
        amt_cols_idx = [i for i, c in enumerate(cols) if is_amount(c)]
        pairs = []
        for ai in amt_cols_idx:
            amt_col = cols[ai]
            cat_idx = None
            for cj in range(ai - 1, -1, -1):
                if is_category(cols[cj]):
                    cat_idx = cj
                    break
            if cat_idx is not None:
                pairs.append((cols[cat_idx], amt_col))
        if not pairs:
            return pd.DataFrame(), "Could not pair category with amount columns in ICIC sheet."
        else:
            def clean_month_label(amt_header: str) -> str:
                label = re.sub(r"(?i)amount\s*spent\s*in", "", str(amt_header)).strip()
                return re.sub(r"\s+", " ", label)
            frames = []
            for cat_col, amt_col in pairs:
                tmp = df_data[[cat_col, amt_col]].copy()
                tmp.columns = ["Category", "Amount"]
                tmp = tmp[tmp["Category"].astype(str).str.strip() != ""]
                tmp["Category"] = tmp["Category"].astype(str).str.strip()
                tmp["Amount"] = pd.to_numeric(tmp["Amount"].astype(str).str.replace(",", ""), errors="coerce")
                tmp["Month"] = clean_month_label(amt_col)
                frames.append(tmp)
            df_result = pd.concat(frames, ignore_index=True)
            df_result = df_result.dropna(subset=["Amount"])
            df_result["Amount"] = df_result["Amount"].fillna(0)
    return df_result, error_message

def process_canara_data(df_raw):
    df_result = pd.DataFrame()
    error_message = None
    if df_raw.empty: return df_result, "Raw DataFrame for CANARA is empty."
    if len(df_raw) <= 4: return df_result, "CANARA sheet has insufficient rows for data."
    df_data = pd.DataFrame(df_raw.iloc[4:, :5].values, columns=['Month', 'Description', 'Category', 'Debit', 'Credit'])
    df_data["Month"] = df_data["Month"].astype(str).str.strip()
    df_data["Category"] = df_data["Category"].astype(str).str.strip()
    df_data["Debit"] = pd.to_numeric(df_data["Debit"].astype(str).str.replace(",", ""), errors="coerce").fillna(0)
    df_data["Credit"] = pd.to_numeric(df_data["Credit"].astype(str).str.replace(",", ""), errors="coerce").fillna(0)
    df_result = df_data[(df_data["Debit"] != 0) | (df_data["Credit"] != 0)].copy()
    return df_result, error_message

def process_investments_data(df_raw):
    df_result = pd.DataFrame()
    error_message = None
    if df_raw.empty or len(df_raw.columns) < 2: return df_result, "Raw DataFrame for Investments is empty or has insufficient columns."
    header_row = df_raw.iloc[0].tolist()
    frames = []
    for i in range(len(header_row)):
        category_name = str(header_row[i]).strip()
        if category_name and category_name.upper() != 'AMOUNT INVESTED':
            try:
                amount_col_name = str(header_row[i+1]).strip()
                if amount_col_name.upper() == 'AMOUNT INVESTED':
                    category_col_data = df_raw.iloc[1:, i].tolist()
                    amount_col_data = df_raw.iloc[1:, i+1].tolist()
                    tmp_df = pd.DataFrame({
                        "Category": [category_name] * len(category_col_data),
                        "Month": category_col_data,
                        "Amount": amount_col_data
                    })
                    frames.append(tmp_df)
            except IndexError:
                continue
    if frames:
        df_result = pd.concat(frames, ignore_index=True)
        df_result = df_result[df_result['Month'].astype(str).str.strip() != '']
        df_result['Amount'] = pd.to_numeric(df_result['Amount'].astype(str).str.replace(',', ''), errors='coerce')
        df_result = df_result.dropna(subset=['Amount'])
        df_result['Amount'] = df_result['Amount'].fillna(0)
        df_result['Category'] = df_result['Category'].astype(str).str.strip()
        df_result['Month'] = df_result['Month'].astype(str).str.strip()
    else:
        error_message = "No valid investment data found."
    return df_result, error_message

# --- Custom Color Palette ---
CUSTOM_COLOR_PALETTE = [
    "#00FFFF", "#FF00FF", "#39FF14", "#8A2BE2", "#4169E1", "#FFD700", 
    "#FF4500", "#7FFF00", "#DC143C", "#1E90FF", "#00FA9A"
]

# --- Generate a cache-busting timestamp ---
cache_buster = int(time.time())

# --- Dash App Initialization ---
app = Dash(__name__, external_stylesheets=[
    dbc.themes.DARKLY, dbc.icons.BOOTSTRAP, f'/assets/new_style.css?v={cache_buster}'
], suppress_callback_exceptions=True)
server = app.server

# --- Define Page Layouts as Functions to prevent render errors ---
def dashboard_page_layout():
    return dbc.Col(
        [
            dbc.Row(dbc.Col(dbc.Card(dbc.CardBody([
                html.H5("Filter Your Data", className="card-title-new-theme text-center mb-3"),
                dbc.Row([
                    dbc.Col(html.Div([html.Label("Select Month(s):", className="form-label-new-theme"), dcc.Dropdown(id="month-filter", options=[], multi=True, placeholder="All Months", className="dropdown-new-theme")]), lg=5, md=6, sm=12, className="mb-3"),
                    dbc.Col(html.Div([html.Label("Select Category(s):", className="form-label-new-theme"), dcc.Dropdown(id="category-filter", options=[], multi=True, placeholder="All Categories", className="dropdown-new-theme")]), lg=5, md=6, sm=12, className="mb-3"),
                    dbc.Col(html.Button([html.I(className="bi bi-arrow-clockwise me-2"), "Reset Filters"], id="reset-filters-button", n_clicks=0, className="btn-reset-new-theme w-100 mt-4"), lg=2, md=12, sm=12, className="mb-3 d-flex align-items-end")
                ], className="g-3 justify-content-center")
            ]), className="filter-card-new-theme mb-5"), width=12)),
            dbc.Row([
                dbc.Col(dbc.Card(dbc.CardBody([html.P("Total Expenses", className="kpi-label-new-theme"), html.H4("₹0.00", id="total-expenses-kpi", className="kpi-value-new-theme primary-kpi"), ]), className="kpi-card-new-theme"), lg=3, md=6, sm=12, className="mb-4"),
                dbc.Col(dbc.Card(dbc.CardBody([html.P("Avg Monthly Expense", className="kpi-label-new-theme"), html.H4("₹0.00", id="avg-monthly-kpi", className="kpi-value-new-theme accent-kpi"), ]), className="kpi-card-new-theme"), lg=3, md=6, sm=12, className="mb-4"),
                dbc.Col(dbc.Card(dbc.CardBody([html.P("Highest Month", className="kpi-label-new-theme"), html.H5("N/A", id="highest-month-kpi-name", className="kpi-value-small-new-theme text-warning"), html.P("₹0.00", id="highest-month-kpi-value", className="kpi-sub-value-new-theme-small"),]), className="kpi-card-new-theme"), lg=3, md=6, sm=12, className="mb-4"),
                dbc.Col(dbc.Card(dbc.CardBody([html.P("Lowest Month", className="kpi-label-new-theme"), html.H5("N/A", id="lowest-month-kpi-name", className="kpi-value-small-new-theme text-info"), html.P("₹0.00", id="lowest-month-kpi-value", className="kpi-sub-value-new-theme-small"),]), className="kpi-card-new-theme"), lg=3, md=6, sm=12, className="mb-4"),
            ], className="g-4 mb-5"),
            dbc.Row([
                dbc.Col(dcc.Loading(id="loading-trend-chart", type="circle", color=CUSTOM_COLOR_PALETTE[0], children=dcc.Graph(id="monthly-expenses-trend-chart")), lg=6, md=12, className="mb-4 chart-panel-new-theme"),
                dbc.Col(dcc.Loading(id="loading-pie-chart", type="circle", color=CUSTOM_COLOR_PALETTE[1], children=dcc.Graph(id="top-expense-categories-chart")), lg=6, md=12, className="mb-4 chart-panel-new-theme"),
            ], className="g-4"),
            dbc.Row([
                dbc.Col(dcc.Loading(id="loading-bar-chart", type="circle", color=CUSTOM_COLOR_PALETTE[2], children=dcc.Graph(id="monthly-expenses-by-category-chart")), width=12, className="mb-4 chart-panel-new-theme"),
            ], className="g-4"),
            dbc.Row([
                dbc.Col(html.Div([
                    html.H4("📊 Detailed Expense Data", className="section-title-new-theme text-center mb-4"),
                    dcc.Loading(id="loading-overview-table", type="circle", color=CUSTOM_COLOR_PALETTE[3], children=dash_table.DataTable(id="overview-data-table", data=[], columns=[], page_action="native", page_size=10, style_table={"overflowX": "auto"}, style_cell={"textAlign": "center", "padding": "12px", "fontFamily": "Open Sans, sans-serif", "fontSize": "0.9em"}, style_header={"backgroundColor": "#000000", "color": "#00FFFF", "fontWeight": "bold", "borderBottom": "2px solid #00FF00"}, style_data={"backgroundColor": "#1A1A1A", "color": "#E0E0E0", "borderBottom": "1px solid rgba(255, 255, 255, 0.05)"}, style_data_conditional=[{"if": {"row_index": "odd"}, "backgroundColor": "#121212"}, {"if": {"row_index": "even"}, "backgroundColor": "#1A1A1A"}]))
                ], className="table-panel-new-theme p-4"), width=12)
            ], className="g-4 mb-5")
        ], width=12, className="main-content-new-theme"
    )

def savings_monitor_layout():
    return dbc.Col(
        [
            dbc.Row(dbc.Col(html.H2("💰 Savings Monitor", className="section-title-new-theme text-center mb-4", style={'color': 'var(--accent-lime)', 'textShadow': 'var(--glow-lime)'}), width=12)),
            dbc.Row(dbc.Col(dbc.Card(dbc.CardBody([
                html.H5("Filter Your Savings Data", className="card-title-new-theme text-center mb-3"),
                dbc.Row([
                    dbc.Col(html.Div([html.Label("Select Month(s):", className="form-label-new-theme"), dcc.Dropdown(id="savings-month-filter", options=[], multi=True, placeholder="All Months", className="dropdown-new-theme")]), lg=5, md=6, sm=12, className="mb-3"),
                    dbc.Col(html.Div([html.Label("Select Category(s):", className="form-label-new-theme"), dcc.Dropdown(id="savings-category-filter", options=[], multi=True, placeholder="All Categories", className="dropdown-new-theme")]), lg=5, md=6, sm=12, className="mb-3"),
                    dbc.Col(html.Button([html.I(className="bi bi-arrow-clockwise me-2"), "Reset Filters"], id="savings-reset-filters-button", n_clicks=0, className="btn-reset-new-theme w-100 mt-4"), lg=2, md=12, sm=12, className="mb-3 d-flex align-items-end")
                ], className="g-3 justify-content-center")
            ]), className="filter-card-new-theme mb-5"), width=12)),
            dbc.Row([
                dbc.Col(dbc.Card(dbc.CardBody([html.P("Total Savings (Credit)", className="kpi-label-new-theme"), html.H4("₹0.00", id="total-savings-credit-kpi", className="kpi-value-new-theme primary-kpi", style={'color': 'var(--accent-lime)', 'textShadow': 'var(--glow-lime)'}), ]), className="kpi-card-new-theme"), lg=4, md=6, sm=12, className="mb-4"),
                dbc.Col(dbc.Card(dbc.CardBody([html.P("Total Withdrawals (Debit)", className="kpi-label-new-theme"), html.H4("₹0.00", id="total-savings-debit-kpi", className="kpi-value-new-theme accent-kpi", style={'color': 'var(--accent-magenta)', 'textShadow': 'var(--glow-magenta)'}), ]), className="kpi-card-new-theme"), lg=4, md=6, sm=12, className="mb-4"),
                dbc.Col(dbc.Card(dbc.CardBody([html.P("Net Savings", className="kpi-label-new-theme"), html.H4("₹0.00", id="net-savings-kpi", className="kpi-value-new-theme text-info", style={'color': 'var(--accent-cyan)', 'textShadow': 'var(--glow-cyan)'}), ]), className="kpi-card-new-theme"), lg=4, md=12, sm=12, className="mb-4"),
            ], className="g-4 mb-5"),
            dbc.Row([
                dbc.Col(dbc.Card(dbc.CardBody([
                    html.H5("🎯 Savings Goal Calculator", className="card-title-new-theme text-center mb-3", style={'color': 'var(--accent-gold)', 'textShadow': 'var(--glow-gold)'}),
                    dbc.Row([
                        dbc.Col(html.Div([html.Label("Target Amount (₹):", className="form-label-new-theme"), dcc.Input(id="target-amount-input", type="number", min=0, placeholder="e.g., 50000", className="form-control-new-theme")]), lg=4, md=6, sm=12, className="mb-3"),
                        dbc.Col(html.Div([html.Label("Duration (Months):", className="form-label-new-theme"), dcc.Input(id="duration-input", type="number", min=1, placeholder="e.g., 12", className="form-control-new-theme")]), lg=4, md=6, sm=12, className="mb-3"),
                        dbc.Col(html.Button([html.I(className="bi bi-calculator me-2"), "Calculate Goal"], id="calculate-goal-button", n_clicks=0, className="btn-primary-new-theme w-100 mt-4"), lg=4, md=12, sm=12, className="mb-3 d-flex align-items-end")
                    ], className="g-3 justify-content-center"),
                    html.Div(id="savings-goal-output", className="text-center mt-3 kpi-sub-value-new-theme-small", style={'color': 'var(--accent-chartreuse)', 'textShadow': 'var(--glow-chartreuse)'})
                ]), className="filter-card-new-theme mb-5"), width=12)
            ]),
            dbc.Row([
                dbc.Col(dcc.Loading(id="loading-savings-trend", type="circle", color=CUSTOM_COLOR_PALETTE[0], children=dcc.Graph(id="savings-monthly-trend-chart")), width=12, className="mb-4 chart-panel-new-theme"),
            ], className="g-4"),
            dbc.Row([
                dbc.Col(dcc.Loading(id="loading-savings-category", type="circle", color=CUSTOM_COLOR_PALETTE[1], children=dcc.Graph(id="savings-category-bar-chart")), width=12, className="mb-4 chart-panel-new-theme"),
            ], className="g-4"),
            dbc.Row([
                dbc.Col(html.Div([
                    html.H4("📊 Detailed Savings Transactions", className="section-title-new-theme text-center mb-4", style={'color': 'var(--accent-gold)', 'textShadow': 'var(--glow-gold)'}),
                    dcc.Loading(id="loading-savings-table", type="circle", color=CUSTOM_COLOR_PALETTE[3], children=dash_table.DataTable(id="savings-data-table", data=[], columns=[], page_action="native", page_size=10, style_table={"overflowX": "auto"}, style_cell={"textAlign": "center", "padding": "12px", "fontFamily": "Open Sans, sans-serif", "fontSize": "0.9em"}, style_header={"backgroundColor": "#000000", "color": "#00FFFF", "fontWeight": "bold", "borderBottom": "2px solid #00FF00"}, style_data={"backgroundColor": "#1A1A1A", "color": "#E0E0E0", "borderBottom": "1px solid rgba(255, 255, 255, 0.05)"}, style_data_conditional=[{"if": {"row_index": "odd"}, "backgroundColor": "#121212"}, {"if": {"row_index": "even"}, "backgroundColor": "#1A1A1A"}]))
                ], className="table-panel-new-theme p-4"), width=12)
            ], className="g-4 mb-5")
        ], width=12, className="main-content-new-theme"
    )

def investments_layout():
    return dbc.Col(
        [
            dbc.Row(dbc.Col(html.H2("💰 Investments", className="section-title-new-theme text-center mb-4", style={'color': 'var(--accent-gold)', 'textShadow': 'var(--glow-gold)'}), width=12)),
            dbc.Row(dbc.Col(dbc.Card(dbc.CardBody([
                html.H5("Filter Your Investment Data", className="card-title-new-theme text-center mb-3"),
                dbc.Row([
                    dbc.Col(html.Div([html.Label("Select Month(s):", className="form-label-new-theme"), dcc.Dropdown(id="investments-month-filter", options=[], multi=True, placeholder="All Months", className="dropdown-new-theme")]), lg=5, md=6, sm=12, className="mb-3"),
                    dbc.Col(html.Div([html.Label("Select Category(s):", className="form-label-new-theme"), dcc.Dropdown(id="investments-category-filter", options=[], multi=True, placeholder="All Categories", className="dropdown-new-theme")]), lg=5, md=6, sm=12, className="mb-3"),
                    dbc.Col(html.Button([html.I(className="bi bi-arrow-clockwise me-2"), "Reset Filters"], id="investments-reset-filters-button", n_clicks=0, className="btn-reset-new-theme w-100 mt-4"), lg=2, md=12, sm=12, className="mb-3 d-flex align-items-end")
                ], className="g-3 justify-content-center")
            ]), className="filter-card-new-theme mb-5"), width=12)),
            dbc.Row([
                dbc.Col(dbc.Card(dbc.CardBody([html.P("Total Investments", className="kpi-label-new-theme"), html.H4("₹0.00", id="total-investments-kpi", className="kpi-value-new-theme primary-kpi", style={'color': 'var(--accent-gold)', 'textShadow': 'var(--glow-gold)'}), ]), className="kpi-card-new-theme"), lg=3, md=6, sm=12, className="mb-4"),
                dbc.Col(dbc.Card(dbc.CardBody([html.P("Avg Monthly Investment", className="kpi-label-new-theme"), html.H4("₹0.00", id="avg-monthly-investment-kpi", className="kpi-value-new-theme accent-kpi", style={'color': 'var(--accent-cyan)', 'textShadow': 'var(--glow-cyan)'}), ]), className="kpi-card-new-theme"), lg=3, md=6, sm=12, className="mb-4"),
                dbc.Col(dbc.Card(dbc.CardBody([html.P("Highest Investment Category", className="kpi-label-new-theme"), html.H5("N/A", id="highest-category-kpi-name", className="kpi-value-small-new-theme text-warning"), html.P("₹0.00", id="highest-category-kpi-value", className="kpi-sub-value-new-theme-small"),]), className="kpi-card-new-theme"), lg=3, md=6, sm=12, className="mb-4"),
                dbc.Col(dbc.Card(dbc.CardBody([html.P("Lowest Investment Category", className="kpi-label-new-theme"), html.H5("N/A", id="lowest-category-kpi-name", className="kpi-value-small-new-theme text-info"), html.P("₹0.00", id="lowest-category-kpi-value", className="kpi-sub-value-new-theme-small"),]), className="kpi-card-new-theme"), lg=3, md=6, sm=12, className="mb-4"),
            ], className="g-4 mb-5"),
            dbc.Row([
                dbc.Col(dbc.Card(dbc.CardBody([html.P("LIC Installments Left", className="kpi-label-new-theme"), html.H4("N/A", id="lic-installments-kpi", className="kpi-value-new-theme text-info"),]), className="kpi-card-new-theme"), lg=4, md=6, sm=12, className="mb-4"),
                dbc.Col(dbc.Card(dbc.CardBody([html.P("Kumaran Installments Left", className="kpi-label-new-theme"), html.H4("N/A", id="kumaran-installments-kpi", className="kpi-value-new-theme text-info"),]), className="kpi-card-new-theme"), lg=4, md=6, sm=12, className="mb-4"),
                dbc.Col(dbc.Card(dbc.CardBody([html.P("Thangamayil Installments Left", className="kpi-label-new-theme"), html.H4("N/A", id="thangamayil-installments-kpi", className="kpi-value-new-theme text-info"),]), className="kpi-card-new-theme"), lg=4, md=6, sm=12, className="mb-4"),
            ], className="g-4 mb-5"),
            dbc.Row([
                dbc.Col(dcc.Loading(id="loading-investments-trend", type="circle", color=CUSTOM_COLOR_PALETTE[0], children=dcc.Graph(id="investments-monthly-trend-chart")), lg=6, md=12, className="mb-4 chart-panel-new-theme"),
                dbc.Col(dcc.Loading(id="loading-investments-pie", type="circle", color=CUSTOM_COLOR_PALETTE[1], children=dcc.Graph(id="investments-categories-chart")), lg=6, md=12, className="mb-4 chart-panel-new-theme"),
            ], className="g-4"),
            dbc.Row([
                dbc.Col(dcc.Loading(id="loading-investments-bar", type="circle", color=CUSTOM_COLOR_PALETTE[2], children=dcc.Graph(id="investments-by-category-chart")), width=12, className="mb-4 chart-panel-new-theme"),
            ], className="g-4"),
            dbc.Row([
                dbc.Col(html.Div([
                    html.H4("📊 Detailed Investment Data", className="section-title-new-theme text-center mb-4", style={'color': 'var(--accent-gold)', 'textShadow': 'var(--glow-gold)'}),
                    dcc.Loading(id="loading-investments-table", type="circle", color=CUSTOM_COLOR_PALETTE[3], children=dash_table.DataTable(id="investments-data-table", data=[], columns=[], page_action="native", page_size=10, style_table={"overflowX": "auto"}, style_cell={"textAlign": "center", "padding": "12px", "fontFamily": "Open Sans, sans-serif", "fontSize": "0.9em"}, style_header={"backgroundColor": "#000000", "color": "#00FFFF", "fontWeight": "bold", "borderBottom": "2px solid #00FF00"}, style_data={"backgroundColor": "#1A1A1A", "color": "#E0E0E0", "borderBottom": "1px solid rgba(255, 255, 255, 0.05)"}, style_data_conditional=[{"if": {"row_index": "odd"}, "backgroundColor": "#121212"}, {"if": {"row_index": "even"}, "backgroundColor": "#1A1A1A"}]))
                ], className="table-panel-new-theme p-4"), width=12)
            ], className="g-4 mb-5")
        ], width=12, className="main-content-new-theme"
    )

# --- Layout of the Dashboard ---
app.layout = dbc.Container(
    [
        dcc.Store(id='stored-icic-data'),
        dcc.Store(id='stored-canara-data'),
        dcc.Store(id='stored-investments-data'),
        dcc.Store(id='loading-error-message'),
        dcc.Interval(id='interval-component', interval=60*1000, n_intervals=0),
        
        html.Div(id="data-load-status", className="data-load-alert"),
        dbc.Row(dbc.Col(
            html.Div([
                html.H1("VENKE FINANCE DASHBOARD", className="header-title-new-theme"),
                dbc.Nav(
                    [
                        dbc.NavLink([html.I(className="bi bi-speedometer2 me-2"), "Dashboard"], href="/", active="exact", className="nav-link-new-theme"),
                        dbc.NavLink([html.I(className="bi bi-piggy-bank me-2"), "Savings Monitor"], href="/savings", className="nav-link-new-theme"),
                        dbc.NavLink([html.I(className="bi bi-graph-up me-2"), "Analytics & Trends"], href="/analytics", className="nav-link-new-theme"),
                        dbc.NavLink([html.I(className="bi bi-table me-2"), "Raw Data Table"], href="/data-table", className="nav-link-new-theme"),
                        dbc.NavLink([html.I(className="bi bi-currency-exchange me-2"), "Investments"], href="/investments", className="nav-link-new-theme"),
                        dbc.NavLink([html.I(className="bi bi-gear me-2"), "Configuration"], href="/settings", className="nav-link-new-theme"),
                    ],
                    className="header-nav-new-theme", horizontal=True, pills=True
                )
            ], className="top-navbar-new-theme"), width=12)),
        dcc.Location(id='url', refresh=False),
        html.Div(id='page-content')
    ],
    fluid=True, className="dashboard-container-new-theme"
)


# --- Callbacks ---
# Main callback to load data and populate filter options
@app.callback(
    Output('stored-icic-data', 'data'),
    Output('stored-canara-data', 'data'),
    Output('stored-investments-data', 'data'),
    Output('loading-error-message', 'data'),
    Input('interval-component', 'n_intervals'),
)
def load_and_store_data(n_intervals):
    print(f"Attempting to load data... Interval count: {n_intervals}")
    df_icic_loaded, df_canara_loaded, df_investments_loaded, error = load_data_from_google_sheets()
    return (
        df_icic_loaded.to_json(date_format='iso', orient='split') if not df_icic_loaded.empty else None,
        df_canara_loaded.to_json(date_format='iso', orient='split') if not df_canara_loaded.empty else None,
        df_investments_loaded.to_json(date_format='iso', orient='split') if not df_investments_loaded.empty else None,
        error
    )

@app.callback(
    Output('data-load-status', 'children'),
    Input('loading-error-message', 'data'),
    State('stored-icic-data', 'data')
)
def update_load_status(error_message, stored_icic_data_json):
    if error_message:
        return dbc.Alert([html.I(className="bi bi-exclamation-triangle-fill me-2"), error_message], color="danger", className="fade-in")
    elif stored_icic_data_json:
        return dbc.Alert([html.I(className="bi bi-check-circle-fill me-2"), "Data loaded successfully! 🚀"], color="success", className="fade-in")
    else:
        return html.Div()


# --- Callback for page routing based on URL ---
@app.callback(
    Output('page-content', 'children'),
    Input('url', 'pathname')
)
def display_page(pathname):
    if pathname == '/':
        return dashboard_page_layout()
    elif pathname == '/savings':
        return savings_monitor_layout()
    elif pathname == '/investments':
        return investments_layout()
    elif pathname == '/analytics':
        return html.Div([html.H3("Analytics & Trends Page - Under Construction", className="text-light text-center mt-5")])
    elif pathname == '/data-table':
        return html.Div([html.H3("Raw Data Table Page - Under Construction", className="text-light text-center mt-5")])
    elif pathname == '/settings':
        return html.Div([html.H3("Configuration Page - Under Construction", className="text-light text-center mt-5")])
    else:
        return html.Div([html.H3("404: Page not found", className="text-danger text-center mt-5")])


# --- Callbacks for Dashboard Page ---
@app.callback(
    Output('month-filter', 'options'),
    Output('category-filter', 'options'),
    Output('total-expenses-kpi', 'children'),
    Output('avg-monthly-kpi', 'children'),
    Output('highest-month-kpi-name', 'children'),
    Output('highest-month-kpi-value', 'children'),
    Output('lowest-month-kpi-name', 'children'),
    Output('lowest-month-kpi-value', 'children'),
    Output('monthly-expenses-trend-chart', 'figure'),
    Output('top-expense-categories-chart', 'figure'),
    Output('monthly-expenses-by-category-chart', 'figure'),
    Output('overview-data-table', 'data'),
    Output('overview-data-table', 'columns'),
    Input('month-filter', 'value'),
    Input('category-filter', 'value'),
    State('stored-icic-data', 'data')
)
def update_dashboard_content(months, categories, icic_json):
    empty_kpi = "₹0.00"
    empty_text = "N/A"
    empty_fig = go.Figure()
    empty_list = []
    
    if not icic_json:
        return (
            empty_list, empty_list,
            empty_kpi, empty_kpi,
            empty_text, empty_kpi, empty_text, empty_kpi,
            empty_fig, empty_fig, empty_fig,
            empty_list, empty_list
        )
    
    df_icic = pd.read_json(icic_json, orient='split')
    df_icic["Month"] = df_icic["Month"].astype(str)
    
    available_months = sorted(df_icic["Month"].unique())
    available_categories = sorted(df_icic["Category"].unique())
    
    dff = df_icic.copy()
    if months: dff = dff[dff["Month"].isin(months)]
    if categories: dff = dff[dff["Category"].isin(categories)]
    
    if dff.empty:
        return (
            [{"label": m, "value": m} for m in available_months],
            [{"label": c, "value": c} for c in available_categories],
            empty_kpi, empty_kpi,
            empty_text, empty_kpi, empty_text, empty_kpi,
            empty_fig, empty_fig, empty_fig,
            empty_list, empty_list
        )
    
    total_expenses = dff['Amount'].sum()
    monthly_expenses = dff.groupby('Month')['Amount'].sum().reset_index()
    avg_monthly_expense = monthly_expenses['Amount'].mean()
    highest_month = monthly_expenses.loc[monthly_expenses['Amount'].idxmax()]
    lowest_month = monthly_expenses.loc[monthly_expenses['Amount'].idxmin()]
    
    trend_fig = px.line(monthly_expenses, x="Month", y="Amount", title="Monthly Expense Trend", labels={"Amount": "Total Expenses (₹)", "Month": "Month"}, template="plotly_dark", color_discrete_sequence=CUSTOM_COLOR_PALETTE)
    trend_fig.update_traces(mode='lines+markers', marker={'size': 8})
    trend_fig.update_layout(title_font_color=CUSTOM_COLOR_PALETTE[0], paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', font_color=CUSTOM_COLOR_PALETTE[9], xaxis_title=None, yaxis_title="Amount (₹)")
    
    category_summary = dff.groupby('Category')['Amount'].sum().reset_index().sort_values(by='Amount', ascending=False)
    pie_fig = px.pie(category_summary, values='Amount', names='Category', title='Expense Distribution by Category', template="plotly_dark", color_discrete_sequence=CUSTOM_COLOR_PALETTE)
    pie_fig.update_layout(title_font_color=CUSTOM_COLOR_PALETTE[1], paper_bgcolor='rgba(0,0,0,0)', font_color=CUSTOM_COLOR_PALETTE[9], legend_title_text='Categories')
    pie_fig.update_traces(textposition='inside', textinfo='percent+label')
    
    expenses_by_cat_month = dff.groupby(['Month', 'Category'])['Amount'].sum().reset_index()
    bar_fig = px.bar(expenses_by_cat_month, x="Month", y="Amount", color="Category", title="Monthly Expenses by Category", labels={"Amount": "Total Expenses (₹)", "Month": "Month"}, template="plotly_dark", color_discrete_sequence=CUSTOM_COLOR_PALETTE)
    bar_fig.update_layout(title_font_color=CUSTOM_COLOR_PALETTE[2], paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', font_color=CUSTOM_COLOR_PALETTE[9], xaxis_title=None, yaxis_title="Amount (₹)")

    table_data = dff.to_dict('records')
    table_columns = [{"name": i, "id": i} for i in dff.columns]
    
    return (
        [{"label": m, "value": m} for m in available_months],
        [{"label": c, "value": c} for c in available_categories],
        f"₹{total_expenses:,.2f}",
        f"₹{avg_monthly_expense:,.2f}",
        highest_month['Month'],
        f"₹{highest_month['Amount']:,.2f}",
        lowest_month['Month'],
        f"₹{lowest_month['Amount']:,.2f}",
        trend_fig,
        pie_fig,
        bar_fig,
        table_data,
        table_columns
    )


# --- Callbacks for Savings Page ---
@app.callback(
    Output('savings-month-filter', 'options'),
    Output('savings-category-filter', 'options'),
    Output('total-savings-credit-kpi', 'children'),
    Output('total-savings-debit-kpi', 'children'),
    Output('net-savings-kpi', 'children'),
    Output('savings-monthly-trend-chart', 'figure'),
    Output('savings-category-bar-chart', 'figure'),
    Output('savings-data-table', 'data'),
    Output('savings-data-table', 'columns'),
    Input('savings-month-filter', 'value'),
    Input('savings-category-filter', 'value'),
    State('stored-canara-data', 'data')
)
def update_savings_content(months, categories, canara_json):
    empty_kpi = "₹0.00"
    empty_fig = go.Figure()
    empty_list = []
    
    if not canara_json:
        return (empty_list, empty_list, empty_kpi, empty_kpi, empty_kpi, empty_fig, empty_fig, empty_list, empty_list)

    df_canara = pd.read_json(canara_json, orient='split')
    df_canara["Month"] = df_canara["Month"].astype(str)

    available_months = sorted(df_canara["Month"].unique())
    available_categories = sorted(df_canara["Category"].unique())

    dff = df_canara.copy()
    if months: dff = dff[dff["Month"].isin(months)]
    if categories: dff = dff[dff["Category"].isin(categories)]

    if dff.empty:
        return (
            [{"label": m, "value": m} for m in available_months],
            [{"label": c, "value": c} for c in available_categories],
            empty_kpi, empty_kpi, empty_kpi, empty_fig, empty_fig, empty_list, empty_list
        )

    total_credit = dff['Credit'].sum()
    total_debit = dff['Debit'].sum()
    net_savings = total_credit - total_debit
    
    monthly_trend = dff.groupby('Month').agg(Total_Credit=('Credit', 'sum'), Total_Debit=('Debit', 'sum')).reset_index()
    trend_fig = go.Figure()
    trend_fig.add_trace(go.Bar(x=monthly_trend['Month'], y=monthly_trend['Total_Credit'], name='Credit', marker_color=CUSTOM_COLOR_PALETTE[0]))
    trend_fig.add_trace(go.Bar(x=monthly_trend['Month'], y=monthly_trend['Total_Debit'], name='Debit', marker_color=CUSTOM_COLOR_PALETTE[1]))
    trend_fig.update_layout(barmode='group', title='Monthly Credit vs Debit Trend', template='plotly_dark', title_font_color=CUSTOM_COLOR_PALETTE[0], paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', font_color=CUSTOM_COLOR_PALETTE[9], xaxis_title=None, yaxis_title="Amount (₹)")

    category_summary = dff.groupby('Category').agg(Total_Credit=('Credit', 'sum'), Total_Debit=('Debit', 'sum')).reset_index()
    category_fig = go.Figure()
    category_fig.add_trace(go.Bar(x=category_summary['Category'], y=category_summary['Total_Credit'], name='Credit', marker_color=CUSTOM_COLOR_PALETTE[0]))
    category_fig.add_trace(go.Bar(x=category_summary['Category'], y=category_summary['Total_Debit'], name='Debit', marker_color=CUSTOM_COLOR_PALETTE[1]))
    category_fig.update_layout(barmode='group', title='Credit & Debit by Category', template='plotly_dark', title_font_color=CUSTOM_COLOR_PALETTE[1], paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', font_color=CUSTOM_COLOR_PALETTE[9], xaxis_title=None, yaxis_title="Amount (₹)")

    table_data = dff.to_dict('records')
    table_columns = [{"name": i, "id": i} for i in dff.columns]

    return (
        [{"label": m, "value": m} for m in available_months],
        [{"label": c, "value": c} for c in available_categories],
        f"₹{total_credit:,.2f}",
        f"₹{total_debit:,.2f}",
        f"₹{net_savings:,.2f}",
        trend_fig,
        category_fig,
        table_data,
        table_columns
    )

# --- Callbacks for Investments Page ---
@app.callback(
    Output('investments-month-filter', 'options'),
    Output('investments-category-filter', 'options'),
    Output('total-investments-kpi', 'children'),
    Output('avg-monthly-investment-kpi', 'children'),
    Output('highest-category-kpi-name', 'children'),
    Output('highest-category-kpi-value', 'children'),
    Output('lowest-category-kpi-name', 'children'),
    Output('lowest-category-kpi-value', 'children'),
    Output('investments-monthly-trend-chart', 'figure'),
    Output('investments-categories-chart', 'figure'),
    Output('investments-by-category-chart', 'figure'),
    Output('investments-data-table', 'data'),
    Output('investments-data-table', 'columns'),
    Output("lic-installments-kpi", "children"),
    Output("kumaran-installments-kpi", "children"),
    Output("thangamayil-installments-kpi", "children"),
    Input('investments-month-filter', 'value'),
    Input('investments-category-filter', 'value'),
    State('stored-investments-data', 'data')
)
def update_investments_content(months, categories, invest_json):
    empty_kpi = "₹0.00"
    empty_text = "N/A"
    empty_fig = go.Figure()
    empty_list = []
    
    if not invest_json:
        return (
            empty_list, empty_list,
            empty_kpi, empty_kpi,
            empty_text, empty_kpi, empty_text, empty_kpi,
            empty_fig, empty_fig, empty_fig,
            empty_list, empty_list,
            empty_text, empty_text, empty_text
        )

    df_investments = pd.read_json(invest_json, orient='split')
    df_investments["Month"] = df_investments["Month"].astype(str)
    
    available_months = sorted(df_investments["Month"].unique())
    available_categories = sorted(df_investments["Category"].unique())
    
    dff = df_investments.copy()
    if months: dff = dff[dff["Month"].isin(months)]
    if categories: dff = dff[dff["Category"].isin(categories)]
    
    if dff.empty:
        return (
            [{"label": m, "value": m} for m in available_months],
            [{"label": c, "value": c} for c in available_categories],
            empty_kpi, empty_kpi,
            empty_text, empty_kpi, empty_text, empty_kpi,
            empty_fig, empty_fig, empty_fig,
            empty_list, empty_list,
            empty_text, empty_text, empty_text
        )

    total_investments = dff['Amount'].sum()
    monthly_investments = dff.groupby('Month')['Amount'].sum().reset_index()
    avg_monthly_investment = monthly_investments['Amount'].mean()
    category_summary = dff.groupby('Category')['Amount'].sum().reset_index().sort_values(by='Amount', ascending=False)
    
    highest_cat_name, highest_cat_value = (category_summary.iloc[0]['Category'], category_summary.iloc[0]['Amount']) if not category_summary.empty else (empty_text, 0)
    lowest_cat_name, lowest_cat_value = (category_summary.iloc[-1]['Category'], category_summary.iloc[-1]['Amount']) if not category_summary.empty else (empty_text, 0)
    
    total_installments = {"LIC": 156, "KUMARAN": 20, "THANGAMAYIL": 12}
    installments_paid = df_investments.groupby("Category").size()

    trend_fig = px.line(monthly_investments, x="Month", y="Amount", title="Monthly Investment Trend", labels={"Amount": "Total Investments (₹)", "Month": "Month"}, template="plotly_dark", color_discrete_sequence=CUSTOM_COLOR_PALETTE)
    trend_fig.update_traces(mode='lines+markers', marker={'size': 8})
    trend_fig.update_layout(title_font_color=CUSTOM_COLOR_PALETTE[0], paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', font_color=CUSTOM_COLOR_PALETTE[9], xaxis_title=None, yaxis_title="Amount (₹)")
    
    pie_fig = px.pie(category_summary, values='Amount', names='Category', title='Investment Distribution by Category', template="plotly_dark", color_discrete_sequence=CUSTOM_COLOR_PALETTE)
    pie_fig.update_layout(title_font_color=CUSTOM_COLOR_PALETTE[1], paper_bgcolor='rgba(0,0,0,0)', font_color=CUSTOM_COLOR_PALETTE[9], legend_title_text='Categories')
    pie_fig.update_traces(textposition='inside', textinfo='percent+label')
    
    investments_by_cat_month = dff.groupby(['Month', 'Category'])['Amount'].sum().reset_index()
    bar_fig = px.bar(investments_by_cat_month, x="Month", y="Amount", color="Category", title="Monthly Investments by Category", labels={"Amount": "Total Investments (₹)", "Month": "Month"}, template="plotly_dark", color_discrete_sequence=CUSTOM_COLOR_PALETTE)
    bar_fig.update_layout(title_font_color=CUSTOM_COLOR_PALETTE[2], paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', font_color=CUSTOM_COLOR_PALETTE[9], xaxis_title=None, yaxis_title="Amount (₹)")

    table_data = dff.to_dict('records')
    table_columns = [{"name": i, "id": i} for i in dff.columns]

    return (
        [{"label": m, "value": m} for m in available_months],
        [{"label": c, "value": c} for c in available_categories],
        f"₹{total_investments:,.2f}",
        f"₹{avg_monthly_investment:,.2f}",
        highest_cat_name,
        f"₹{highest_cat_value:,.2f}",
        lowest_cat_name,
        f"₹{lowest_cat_value:,.2f}",
        trend_fig,
        pie_fig,
        bar_fig,
        table_data,
        table_columns,
        str(max(0, total_installments["LIC"] - installments_paid.get("LIC", 0))),
        str(max(0, total_installments["KUMARAN"] - installments_paid.get("KUMARAN", 0))),
        str(max(0, total_installments["THANGAMAYIL"] - installments_paid.get("THANGAMAYIL", 0)))
    )


# --- Callback for Dashboard Reset Filters ---
@app.callback(
    Output('month-filter', 'value'),
    Output('category-filter', 'value'),
    Input('reset-filters-button', 'n_clicks'),
    prevent_initial_call=True
)
def reset_icic_filters(n_clicks):
    return [], []

# --- Callback for Savings Reset Filters ---
@app.callback(
    Output('savings-month-filter', 'value'),
    Output('savings-category-filter', 'value'),
    Input('savings-reset-filters-button', 'n_clicks'),
    prevent_initial_call=True
)
def reset_canara_filters(n_clicks):
    return [], []

# --- Callback for Investments Reset Filters ---
@app.callback(
    Output('investments-month-filter', 'value'),
    Output('investments-category-filter', 'value'),
    Input('investments-reset-filters-button', 'n_clicks'),
    prevent_initial_call=True
)
def reset_investments_filters(n_clicks):
    return [], []

# --- Callback for Savings Goal Calculator
@app.callback(
    Output("savings-goal-output", "children"),
    Input("calculate-goal-button", "n_clicks"),
    State("target-amount-input", "value"),
    State("duration-input", "value"),
    State('stored-canara-data', 'data'),
    prevent_initial_call=True
)
def calculate_savings_goal(n_clicks, target_amount, duration, stored_canara_data_json):
    if not stored_canara_data_json:
        return html.P("No savings data available to perform calculations.", className="text-danger")
    df_canara = pd.read_json(stored_canara_data_json, orient='split')
    if df_canara.empty:
        return html.P("Historical data is empty. Cannot perform calculations.", className="text-warning")

    monthly_summary = df_canara.groupby('Month').agg(Total_Credit=('Credit', 'sum'), Total_Debit=('Debit', 'sum')).reset_index()
    monthly_summary['Net_Savings'] = monthly_summary['Total_Credit'] - monthly_summary['Total_Debit']
    historical_avg_monthly_net_savings = monthly_summary['Net_Savings'].mean()
    
    if target_amount is None and duration is None:
        return html.P("Please enter a target amount or a duration.", className="text-danger")
    if target_amount is not None and duration is not None:
        if duration <= 0: return html.P("Duration must be a positive number of months.", className="text-danger")
        required_monthly_savings = target_amount / duration
        output_message = (f"To reach your goal of ₹{target_amount:,.2f} in {duration} months, you need to save an average of ₹{required_monthly_savings:,.2f} per month.")
        if required_monthly_savings <= historical_avg_monthly_net_savings:
            output_message += " You are currently on track to meet this goal!"
        else:
            output_message += " Your required monthly savings is higher than your historical average. You need to save more per month."
        return html.P(output_message)
    elif target_amount is not None:
        if historical_avg_monthly_net_savings <= 0: return html.P("Your historical average monthly net savings is ₹0.00 or less. Cannot predict time to goal.", className="text-warning")
        time_needed_months = target_amount / historical_avg_monthly_net_savings
        return html.P(f"At your historical average monthly net savings of ₹{historical_avg_monthly_net_savings:,.2f}, it will take approximately {time_needed_months:,.1f} months to save ₹{target_amount:,.2f}.")
    elif duration is not None:
        if duration <= 0: return html.P("Duration must be a positive number of months.", className="text-danger")
        if historical_avg_monthly_net_savings <= 0: return html.P("Your historical average monthly net savings is ₹0.00 or less. You won't save anything in this duration.", className="text-warning")
        projected_savings = historical_avg_monthly_net_savings * duration
        return html.P(f"At your historical average monthly net savings of ₹{historical_avg_monthly_net_savings:,.2f}, you will save approximately ₹{projected_savings:,.2f} in {duration} months.")
    return html.P("Please enter valid numbers for target amount and/or duration.", className="text-danger")


if __name__ == "__main__":
    from waitress import serve
    print("Starting the Dashboard ... Loading data, this might take a moment...")
    app.run_server(debug=True)