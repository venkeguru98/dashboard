import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from dash import Dash, dcc, html, dash_table, Input, Output, State, no_update
import plotly.express as px
import plotly.graph_objects as go
import re
import dash_bootstrap_components as dbc
import os
import time
import base64
import json
import tempfile

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
# IMPORTANT: Update this path to your service account JSON file.
#SERVICE_ACCOUNT_FILE = r"C:\Users\JEEVALAKSHMI R\Videos\dashboard_for_expense\icic-salary-data-52568c61b6e3.json"

# --- Google Sheets Authentication and Data Retrieval ---
# IMPORTANT: This section has been updated to handle credentials securely
# for deployment.

# Import these libraries at the top of your file

# Define the scopes required for Google Sheets API access
SCOPES = ['https://www.googleapis.com/auth/spreadsheets']

# Placeholder for client and DataFrame initialization
client = None
df_combined = pd.DataFrame()
error_message = None

try:
    if os.environ.get("GCP_SA_CREDENTIALS"):
        # Decode the Base64 string from the environment variable
        credentials_json_bytes = base64.b64decode(os.environ.get("GCP_SA_CREDENTIALS"))
        credentials_json = credentials_json_bytes.decode('utf-8')
        creds_dict = json.loads(credentials_json)
        creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
        print("Authenticated using Base64 environment variable.")
    else:
        # Fallback to local file for development
        SERVICE_ACCOUNT_FILE = "credentials.json"
        creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
        print("Authenticated using local file.")
        
    client = gspread.authorize(creds)
    print("Authentication successful!")

except Exception as e:
    error_message = f"❌ Authentication failed with error: {e}"
    print(error_message)
    client = None
    df_combined = pd.DataFrame()
    
def load_data_from_google_sheets():
    df_icic = pd.DataFrame()
    df_canara = pd.DataFrame()
    df_investments = pd.DataFrame()
    error_message = None

    try:
        scope = [
            "https://www.googleapis.com/auth/spreadsheets.readonly",
            "https://www.googleapis.com/auth/drive.readonly",
        ]
        creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=scope)
        client = gspread.authorize(creds)

        sheet_url = "https://docs.google.com/spreadsheets/d/1o1e8ouOghU_1L592pt_OSxn6aUSY5KNm1HOT6zbbQOA/edit?gid=1788780645#gid=1788780645"
        spreadsheet = client.open_by_url(sheet_url)

        # Load ICIC Salary Data
        try:
            worksheet_icic = spreadsheet.worksheet("ICIC salary")
            data_icic = worksheet_icic.get_all_values()
            df_raw_icic = pd.DataFrame(data_icic)
            df_icic, icic_error = process_icic_salary_data(df_raw_icic)
            if icic_error:
                print(f"ICIC Data Processing Warning: {icic_error}") # Log warning, don't block
        except gspread.exceptions.WorksheetNotFound:
            print("Warning: 'ICIC salary' worksheet not found. Skipping ICIC data load.")
        except Exception as e:
            print(f"Error loading 'ICIC salary' sheet: {e}")

        # Load CANARA Data
        try:
            worksheet_canara = spreadsheet.worksheet("CANARA")
            data_canara = worksheet_canara.get_all_values()
            df_raw_canara = pd.DataFrame(data_canara)
            df_canara, canara_error = process_canara_data(df_raw_canara)
            if canara_error:
                print(f"CANARA Data Processing Warning: {canara_error}") # Log warning
        except gspread.exceptions.WorksheetNotFound:
            print("Warning: 'CANARA' worksheet not found. Skipping CANARA data load.")
        except Exception as e:
                print(f"Error loading 'CANARA' sheet: {e}")

        # Load Investments Data
        try:
            worksheet_investments = spreadsheet.worksheet("GOLD & LIC & DEPOSITS")
            data_investments = worksheet_investments.get_all_values()
            df_raw_investments = pd.DataFrame(data_investments)
            df_investments, investments_error = process_investments_data(df_raw_investments)
            if investments_error:
                print(f"Investments Data Processing Warning: {investments_error}")
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

    if df_raw.empty:
        return df_result, "Raw DataFrame for ICIC is empty."

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

    if df_raw.empty:
        return df_result, "Raw DataFrame for CANARA is empty."

    if len(df_raw) <= 4:
        return df_result, "CANARA sheet has insufficient rows for data."

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

    if df_raw.empty or len(df_raw.columns) < 2:
        return df_result, "Raw DataFrame for Investments is empty or has insufficient columns."
    
    # Assuming months are in the first column, starting from the second row
    # The first row (index 0) contains the category names
    header_row = df_raw.iloc[0].tolist()
    
    frames = []
    
    # Iterate through columns, skipping the first one (Month)
    for i in range(len(header_row)):
        # Check if the column is an investment category (e.g., KUMARAN, THANGAMAYIL)
        category_name = str(header_row[i]).strip()
        
        # We need to find the pairs of category name and amount columns
        # The pattern is: [Category Name], [Amount Invested], [Category Name], [Amount Invested]...
        if category_name and category_name.upper() != 'AMOUNT INVESTED':
            try:
                # The 'Amount Invested' column should be the next one
                amount_col_name = str(header_row[i+1]).strip()
                if amount_col_name.upper() == 'AMOUNT INVESTED':
                    category_col_data = df_raw.iloc[1:, i].tolist()
                    amount_col_data = df_raw.iloc[1:, i+1].tolist()
                    
                    # Create a temporary DataFrame for this category's data
                    tmp_df = pd.DataFrame({
                        "Category": [category_name] * len(category_col_data),
                        "Month": category_col_data,
                        "Amount": amount_col_data
                    })
                    frames.append(tmp_df)
            except IndexError:
                # This handles cases where the last category doesn't have a following column
                continue
                
    if frames:
        df_result = pd.concat(frames, ignore_index=True)
        
        # Data Cleaning
        df_result = df_result[df_result['Month'].astype(str).str.strip() != '']
        df_result['Amount'] = pd.to_numeric(df_result['Amount'].astype(str).str.replace(',', ''), errors='coerce')
        df_result = df_result.dropna(subset=['Amount'])
        df_result['Amount'] = df_result['Amount'].fillna(0)
        df_result['Category'] = df_result['Category'].astype(str).str.strip()
        df_result['Month'] = df_result['Month'].astype(str).str.strip()
    else:
        error_message = "No valid investment data found."

    return df_result, error_message

# --- Custom Color Palette for Charts (Vaporwave Synapse Theme) ---
CUSTOM_COLOR_PALETTE = [
    "#00FFFF",   # Cyan
    "#FF00FF",   # Magenta
    "#39FF14",   # Neon Green
    "#8A2BE2",   # BlueViolet
    "#4169E1",   # RoyalBlue
    "#FFD700",   # Gold
    "#FF4500",   # OrangeRed
    "#7FFF00",   # Chartreuse
    "#DC143C",   # Crimson
    "#1E90FF",   # DodgerBlue
    "#00FA9A"    # MediumSpringGreen
]

# --- Generate a cache-busting timestamp ---
cache_buster = int(time.time())

# --- Dash App Initialization ---
app = Dash(__name__, external_stylesheets=[
    dbc.themes.DARKLY,
    dbc.icons.BOOTSTRAP,
    f'/assets/new_style.css?v={cache_buster}'
], suppress_callback_exceptions=True)
server = app.server

# --- Layout of the Dashboard (Header-Only Vaporwave Synapse Theme) ---
app.layout = dbc.Container(
    [
        dcc.Store(id='stored-icic-data'),
        dcc.Store(id='stored-canara-data'),
        dcc.Store(id='stored-investments-data'),  # New store for investments data
        dcc.Store(id='loading-error-message'),
        dcc.Interval(
            id='interval-component',
            interval=60*1000,
            n_intervals=0
        ),
        
        html.Div(id="data-load-status", className="data-load-alert"),

        # Top Header/Navbar
        dbc.Row(
            dbc.Col(
                html.Div(
                    [
                        html.H1("VENKE FINANCE DASHBOARD", className="header-title-new-theme"),
                        dbc.Nav(
                            [
                                dbc.NavLink([html.I(className="bi bi-speedometer2 me-2"), "Dashboard"], href="/", active="exact", className="nav-link-new-theme"),
                                dbc.NavLink([html.I(className="bi bi-piggy-bank me-2"), "Savings Monitor"], href="/savings", className="nav-link-new-theme"),
                                dbc.NavLink([html.I(className="bi bi-graph-up me-2"), "Analytics & Trends"], href="/analytics", className="nav-link-new-theme"),
                                dbc.NavLink([html.I(className="bi bi-table me-2"), "Raw Data Table"], href="/data-table", className="nav-link-new-theme"),
                                dbc.NavLink([html.I(className="bi bi-currency-exchange me-2"), "Investments"], href="/investments", className="nav-link-new-theme"),  # New Investments tab
                                dbc.NavLink([html.I(className="bi bi-gear me-2"), "Configuration"], href="/settings", className="nav-link-new-theme"),
                            ],
                            className="header-nav-new-theme",
                            horizontal=True,
                            pills=True
                        )
                    ],
                    className="top-navbar-new-theme"
                ),
                width=12
            )
        ),
        dcc.Location(id='url', refresh=False),
        html.Div(id='page-content')
    ],
    fluid=True,
    className="dashboard-container-new-theme"
)

# --- Layout for the Dashboard Page ---
dashboard_page_layout = dbc.Col(
    [
        # Filters Section
        dbc.Row(
            dbc.Col(
                dbc.Card(
                    dbc.CardBody([
                        html.H5("Filter Your Data", className="card-title-new-theme text-center mb-3"),
                        dbc.Row([
                            dbc.Col(
                                html.Div([
                                    html.Label("Select Month(s):", className="form-label-new-theme"),
                                    dcc.Dropdown(
                                        id="month-filter",
                                        options=[],
                                        multi=True,
                                        placeholder="All Months",
                                        className="dropdown-new-theme"
                                    ),
                                ]),
                                lg=5, md=6, sm=12, className="mb-3"
                            ),
                            dbc.Col(
                                html.Div([
                                    html.Label("Select Category(s):", className="form-label-new-theme"),
                                    dcc.Dropdown(
                                        id="category-filter",
                                        options=[],
                                        multi=True,
                                        placeholder="All Categories",
                                        className="dropdown-new-theme"
                                    ),
                                ]),
                                lg=5, md=6, sm=12, className="mb-3"
                            ),
                            dbc.Col(
                                html.Button(
                                    [html.I(className="bi bi-arrow-clockwise me-2"), "Reset Filters"],
                                    id="reset-filters-button", n_clicks=0,
                                    className="btn-reset-new-theme w-100 mt-4"
                                ),
                                lg=2, md=12, sm=12, className="mb-3 d-flex align-items-end"
                            )
                        ], className="g-3 justify-content-center")
                    ]),
                    className="filter-card-new-theme mb-5"
                ),
                width=12
            )
        ),

        # KPI Cards
        dbc.Row([
            dbc.Col(dbc.Card(
                dbc.CardBody([
                    html.P("Total Expenses", className="kpi-label-new-theme"),
                    html.H4("₹0.00", id="total-expenses-kpi", className="kpi-value-new-theme primary-kpi"), 
                ]), className="kpi-card-new-theme"
            ), lg=3, md=6, sm=12, className="mb-4"),
            dbc.Col(dbc.Card(
                dbc.CardBody([
                    html.P("Avg Monthly Expense", className="kpi-label-new-theme"),
                    html.H4("₹0.00", id="avg-monthly-kpi", className="kpi-value-new-theme accent-kpi"), 
                ]), className="kpi-card-new-theme"
            ), lg=3, md=6, sm=12, className="mb-4"),
            dbc.Col(dbc.Card(
                dbc.CardBody([
                    html.P("Highest Month", className="kpi-label-new-theme"),
                    html.H5("N/A", id="highest-month-kpi-name", className="kpi-value-small-new-theme text-warning"),
                    html.P("₹0.00", id="highest-month-kpi-value", className="kpi-sub-value-new-theme-small"),
                ]), className="kpi-card-new-theme"
            ), lg=3, md=6, sm=12, className="mb-4"),
            dbc.Col(dbc.Card(
                dbc.CardBody([
                    html.P("Lowest Month", className="kpi-label-new-theme"),
                    html.H5("N/A", id="lowest-month-kpi-name", className="kpi-value-small-new-theme text-info"),
                    html.P("₹0.00", id="lowest-month-kpi-value", className="kpi-sub-value-new-theme-small"),
                ]), className="kpi-card-new-theme"
            ), lg=3, md=6, sm=12, className="mb-4"),
        ], className="g-4 mb-5"),

        # Charts Section
        dbc.Row([
            dbc.Col(dcc.Loading(id="loading-trend-chart", type="circle", color=CUSTOM_COLOR_PALETTE[0], children=dcc.Graph(id="monthly-expenses-trend-chart")), lg=6, md=12, className="mb-4 chart-panel-new-theme"),
            dbc.Col(dcc.Loading(id="loading-pie-chart", type="circle", color=CUSTOM_COLOR_PALETTE[1], children=dcc.Graph(id="top-expense-categories-chart")), lg=6, md=12, className="mb-4 chart-panel-new-theme"),
        ], className="g-4"),

        dbc.Row([
            dbc.Col(dcc.Loading(id="loading-bar-chart", type="circle", color=CUSTOM_COLOR_PALETTE[2], children=dcc.Graph(id="monthly-expenses-by-category-chart")), width=12, className="mb-4 chart-panel-new-theme"),
        ], className="g-4"),

        # Data Table Section
        dbc.Row([
            dbc.Col(
                html.Div([
                    html.H4("📊 Detailed Expense Data", className="section-title-new-theme text-center mb-4"),
                    dcc.Loading(
                        id="loading-overview-table", type="circle", color=CUSTOM_COLOR_PALETTE[3],
                        children=dash_table.DataTable(
                            id="overview-data-table",
                            data=[],
                            columns=[],
                            style_table={"overflowX": "auto"},
                            style_cell={"textAlign": "center", "padding": "12px", "fontFamily": "Open Sans, sans-serif", "fontSize": "0.9em"},
                            style_header={"backgroundColor": "#000000", "color": "#00FFFF", "fontWeight": "bold", "borderBottom": "2px solid #00FF00"},
                            style_data={"backgroundColor": "#1A1A1A", "color": "#E0E0E0", "borderBottom": "1px solid rgba(255, 255, 255, 0.05)"},
                            style_data_conditional=[
                                {"if": {"row_index": "odd"}, "backgroundColor": "#121212"},
                                {"if": {"row_index": "even"}, "backgroundColor": "#1A1A1A"}, 
                            ],
                            page_action="native",
                            page_size=10,
                        )
                    )
                ], className="table-panel-new-theme p-4"),
                width=12
            )
        ], className="g-4 mb-5")
    ],
    width=12,
    className="main-content-new-theme"
)

# --- Layout for the Savings Monitor Page ---
savings_monitor_layout = dbc.Col(
    [
        dbc.Row(
            dbc.Col(
                html.H2("💰 Savings Monitor", className="section-title-new-theme text-center mb-4", style={'color': 'var(--accent-lime)', 'textShadow': 'var(--glow-lime)'}),
                width=12
            )
        ),
        # Filter Section for Savings Monitor
        dbc.Row(
            dbc.Col(
                dbc.Card(
                    dbc.CardBody([
                        html.H5("Filter Your Savings Data", className="card-title-new-theme text-center mb-3"),
                        dbc.Row([
                            dbc.Col(
                                html.Div([
                                    html.Label("Select Month(s):", className="form-label-new-theme"),
                                    dcc.Dropdown(
                                        id="savings-month-filter",
                                        options=[],
                                        multi=True,
                                        placeholder="All Months",
                                        className="dropdown-new-theme"
                                    ),
                                ]),
                                lg=5, md=6, sm=12, className="mb-3"
                            ),
                            dbc.Col(
                                html.Div([
                                    html.Label("Select Category(s):", className="form-label-new-theme"),
                                    dcc.Dropdown(
                                        id="savings-category-filter",
                                        options=[],
                                        multi=True,
                                        placeholder="All Categories",
                                        className="dropdown-new-theme"
                                    ),
                                ]),
                                lg=5, md=6, sm=12, className="mb-3"
                            ),
                            dbc.Col(
                                html.Button(
                                    [html.I(className="bi bi-arrow-clockwise me-2"), "Reset Filters"],
                                    id="savings-reset-filters-button", n_clicks=0,
                                    className="btn-reset-new-theme w-100 mt-4"
                                ),
                                lg=2, md=12, sm=12, className="mb-3 d-flex align-items-end"
                            )
                        ], className="g-3 justify-content-center")
                    ]),
                    className="filter-card-new-theme mb-5"
                ),
                width=12
            )
        ),

        dbc.Row([
            dbc.Col(dbc.Card(
                dbc.CardBody([
                    html.P("Total Savings (Credit)", className="kpi-label-new-theme"),
                    html.H4("₹0.00", id="total-savings-credit-kpi", className="kpi-value-new-theme primary-kpi", style={'color': 'var(--accent-lime)', 'textShadow': 'var(--glow-lime)'}), 
                ]), className="kpi-card-new-theme"
            ), lg=4, md=6, sm=12, className="mb-4"),
            dbc.Col(dbc.Card(
                dbc.CardBody([
                    html.P("Total Withdrawals (Debit)", className="kpi-label-new-theme"),
                    html.H4("₹0.00", id="total-savings-debit-kpi", className="kpi-value-new-theme accent-kpi", style={'color': 'var(--accent-magenta)', 'textShadow': 'var(--glow-magenta)'}), 
                ]), className="kpi-card-new-theme"
            ), lg=4, md=6, sm=12, className="mb-4"),
            dbc.Col(dbc.Card(
                dbc.CardBody([
                    html.P("Net Savings", className="kpi-label-new-theme"),
                    html.H4("₹0.00", id="net-savings-kpi", className="kpi-value-new-theme text-info", style={'color': 'var(--accent-cyan)', 'textShadow': 'var(--glow-cyan)'}), 
                ]), className="kpi-card-new-theme"
            ), lg=4, md=12, sm=12, className="mb-4"),
        ], className="g-4 mb-5"),

        # Savings Goal Calculator Section
        dbc.Row([
            dbc.Col(
                dbc.Card(
                    dbc.CardBody([
                        html.H5("🎯 Savings Goal Calculator", className="card-title-new-theme text-center mb-3", style={'color': 'var(--accent-gold)', 'textShadow': 'var(--glow-gold)'}),
                        dbc.Row([
                            dbc.Col(
                                html.Div([
                                    html.Label("Target Amount (₹):", className="form-label-new-theme"),
                                    dcc.Input(
                                        id="target-amount-input",
                                        type="number",
                                        min=0,
                                        placeholder="e.g., 50000",
                                        className="form-control-new-theme"
                                    ),
                                ]),
                                lg=4, md=6, sm=12, className="mb-3"
                            ),
                            dbc.Col(
                                html.Div([
                                    html.Label("Duration (Months):", className="form-label-new-theme"),
                                    dcc.Input(
                                        id="duration-input",
                                        type="number",
                                        min=1,
                                        placeholder="e.g., 12",
                                        className="form-control-new-theme"
                                    ),
                                ]),
                                lg=4, md=6, sm=12, className="mb-3"
                            ),
                            dbc.Col(
                                html.Button(
                                    [html.I(className="bi bi-calculator me-2"), "Calculate Goal"],
                                    id="calculate-goal-button", n_clicks=0,
                                    className="btn-primary-new-theme w-100 mt-4"
                                ),
                                lg=4, md=12, sm=12, className="mb-3 d-flex align-items-end"
                            )
                        ], className="g-3 justify-content-center"),
                        html.Div(id="savings-goal-output", className="text-center mt-3 kpi-sub-value-new-theme-small", style={'color': 'var(--accent-chartreuse)', 'textShadow': 'var(--glow-chartreuse)'})
                    ]),
                    className="filter-card-new-theme mb-5"
                ),
                width=12
            )
        ]),

        dbc.Row([
            dbc.Col(dcc.Loading(id="loading-savings-trend", type="circle", color=CUSTOM_COLOR_PALETTE[0], children=dcc.Graph(id="savings-monthly-trend-chart")), width=12, className="mb-4 chart-panel-new-theme"),
        ], className="g-4"),

        dbc.Row([
            dbc.Col(dcc.Loading(id="loading-savings-category", type="circle", color=CUSTOM_COLOR_PALETTE[1], children=dcc.Graph(id="savings-category-bar-chart")), width=12, className="mb-4 chart-panel-new-theme"),
        ], className="g-4"),

        dbc.Row([
            dbc.Col(
                html.Div([
                    html.H4("📊 Detailed Savings Transactions", className="section-title-new-theme text-center mb-4", style={'color': 'var(--accent-gold)', 'textShadow': 'var(--glow-gold)'}),
                    dcc.Loading(
                        id="loading-savings-table", type="circle", color=CUSTOM_COLOR_PALETTE[3],
                        children=dash_table.DataTable(
                            id="savings-data-table",
                            data=[],
                            columns=[],
                            style_table={"overflowX": "auto"},
                            style_cell={"textAlign": "center", "padding": "12px", "fontFamily": "Open Sans, sans-serif", "fontSize": "0.9em"},
                            style_header={"backgroundColor": "#000000", "color": "#00FFFF", "fontWeight": "bold", "borderBottom": "2px solid #00FF00"},
                            style_data={"backgroundColor": "#1A1A1A", "color": "#E0E0E0", "borderBottom": "1px solid rgba(255, 255, 255, 0.05)"},
                            style_data_conditional=[
                                {"if": {"row_index": "odd"}, "backgroundColor": "#121212"},
                                {"if": {"row_index": "even"}, "backgroundColor": "#1A1A1A"}, 
                            ],
                            page_action="native",
                            page_size=10,
                        )
                    )
                ], className="table-panel-new-theme p-4"),
                width=12
            )
        ], className="g-4 mb-5")
    ],
    width=12,
    className="main-content-new-theme"
)

# --- Layout for the Investments Page ---
investments_layout = dbc.Col(
    [
        dbc.Row(
            dbc.Col(
                html.H2("💰 Investments", className="section-title-new-theme text-center mb-4", style={'color': 'var(--accent-gold)', 'textShadow': 'var(--glow-gold)'}),
                width=12
            )
        ),
        
        # Filter Section for Investments
        dbc.Row(
            dbc.Col(
                dbc.Card(
                    dbc.CardBody([
                        html.H5("Filter Your Investment Data", className="card-title-new-theme text-center mb-3"),
                        dbc.Row([
                            dbc.Col(
                                html.Div([
                                    html.Label("Select Month(s):", className="form-label-new-theme"),
                                    dcc.Dropdown(
                                        id="investments-month-filter",
                                        options=[],
                                        multi=True,
                                        placeholder="All Months",
                                        className="dropdown-new-theme"
                                    ),
                                ]),
                                lg=5, md=6, sm=12, className="mb-3"
                            ),
                            dbc.Col(
                                html.Div([
                                    html.Label("Select Category(s):", className="form-label-new-theme"),
                                    dcc.Dropdown(
                                        id="investments-category-filter",
                                        options=[],
                                        multi=True,
                                        placeholder="All Categories",
                                        className="dropdown-new-theme"
                                    ),
                                ]),
                                lg=5, md=6, sm=12, className="mb-3"
                            ),
                            dbc.Col(
                                html.Button(
                                    [html.I(className="bi bi-arrow-clockwise me-2"), "Reset Filters"],
                                    id="investments-reset-filters-button", n_clicks=0,
                                    className="btn-reset-new-theme w-100 mt-4"
                                ),
                                lg=2, md=12, sm=12, className="mb-3 d-flex align-items-end"
                            )
                        ], className="g-3 justify-content-center")
                    ]),
                    className="filter-card-new-theme mb-5"
                ),
                width=12
            )
        ),

        # KPI Cards for Investments
        dbc.Row([
            dbc.Col(dbc.Card(
                dbc.CardBody([
                    html.P("Total Investments", className="kpi-label-new-theme"),
                    html.H4("₹0.00", id="total-investments-kpi", className="kpi-value-new-theme primary-kpi", style={'color': 'var(--accent-gold)', 'textShadow': 'var(--glow-gold)'}), 
                ]), className="kpi-card-new-theme"
            ), lg=3, md=6, sm=12, className="mb-4"),
            dbc.Col(dbc.Card(
                dbc.CardBody([
                    html.P("Avg Monthly Investment", className="kpi-label-new-theme"),
                    html.H4("₹0.00", id="avg-monthly-investment-kpi", className="kpi-value-new-theme accent-kpi", style={'color': 'var(--accent-cyan)', 'textShadow': 'var(--glow-cyan)'}), 
                ]), className="kpi-card-new-theme"
            ), lg=3, md=6, sm=12, className="mb-4"),
            dbc.Col(dbc.Card(
                dbc.CardBody([
                    html.P("Highest Investment Category", className="kpi-label-new-theme"),
                    html.H5("N/A", id="highest-category-kpi-name", className="kpi-value-small-new-theme text-warning"),
                    html.P("₹0.00", id="highest-category-kpi-value", className="kpi-sub-value-new-theme-small"),
                ]), className="kpi-card-new-theme"
            ), lg=3, md=6, sm=12, className="mb-4"),
            dbc.Col(dbc.Card(
                dbc.CardBody([
                    html.P("Lowest Investment Category", className="kpi-label-new-theme"),
                    html.H5("N/A", id="lowest-category-kpi-name", className="kpi-value-small-new-theme text-info"),
                    html.P("₹0.00", id="lowest-category-kpi-value", className="kpi-sub-value-new-theme-small"),
                ]), className="kpi-card-new-theme"
            ), lg=3, md=6, sm=12, className="mb-4"),
        ], className="g-4 mb-5"),
        
        # New KPI Row for remaining installments
        dbc.Row([
            dbc.Col(dbc.Card(
                dbc.CardBody([
                    html.P("LIC Installments Left", className="kpi-label-new-theme"),
                    html.H4("N/A", id="lic-installments-kpi", className="kpi-value-new-theme text-info"), 
                ]), className="kpi-card-new-theme"
            ), lg=4, md=6, sm=12, className="mb-4"),
            dbc.Col(dbc.Card(
                dbc.CardBody([
                    html.P("Kumaran Installments Left", className="kpi-label-new-theme"),
                    html.H4("N/A", id="kumaran-installments-kpi", className="kpi-value-new-theme text-info"), 
                ]), className="kpi-card-new-theme"
            ), lg=4, md=6, sm=12, className="mb-4"),
            dbc.Col(dbc.Card(
                dbc.CardBody([
                    html.P("Thangamayil Installments Left", className="kpi-label-new-theme"),
                    html.H4("N/A", id="thangamayil-installments-kpi", className="kpi-value-new-theme text-info"), 
                ]), className="kpi-card-new-theme"
            ), lg=4, md=6, sm=12, className="mb-4"),
        ], className="g-4 mb-5"),

        # Charts Section for Investments
        dbc.Row([
            dbc.Col(dcc.Loading(id="loading-investments-trend", type="circle", color=CUSTOM_COLOR_PALETTE[0], children=dcc.Graph(id="investments-monthly-trend-chart")), lg=6, md=12, className="mb-4 chart-panel-new-theme"),
            dbc.Col(dcc.Loading(id="loading-investments-pie", type="circle", color=CUSTOM_COLOR_PALETTE[1], children=dcc.Graph(id="investments-categories-chart")), lg=6, md=12, className="mb-4 chart-panel-new-theme"),
        ], className="g-4"),

        dbc.Row([
            dbc.Col(dcc.Loading(id="loading-investments-bar", type="circle", color=CUSTOM_COLOR_PALETTE[2], children=dcc.Graph(id="investments-by-category-chart")), width=12, className="mb-4 chart-panel-new-theme"),
        ], className="g-4"),

        # Data Table Section for Investments
        dbc.Row([
            dbc.Col(
                html.Div([
                    html.H4("📊 Detailed Investment Data", className="section-title-new-theme text-center mb-4", style={'color': 'var(--accent-gold)', 'textShadow': 'var(--glow-gold)'}),
                    dcc.Loading(
                        id="loading-investments-table", type="circle", color=CUSTOM_COLOR_PALETTE[3],
                        children=dash_table.DataTable(
                            id="investments-data-table",
                            data=[],
                            columns=[],
                            style_table={"overflowX": "auto"},
                            style_cell={"textAlign": "center", "padding": "12px", "fontFamily": "Open Sans, sans-serif", "fontSize": "0.9em"},
                            style_header={"backgroundColor": "#000000", "color": "#00FFFF", "fontWeight": "bold", "borderBottom": "2px solid #00FF00"},
                            style_data={"backgroundColor": "#1A1A1A", "color": "#E0E0E0", "borderBottom": "1px solid rgba(255, 255, 255, 0.05)"},
                            style_data_conditional=[
                                {"if": {"row_index": "odd"}, "backgroundColor": "#121212"},
                                {"if": {"row_index": "even"}, "backgroundColor": "#1A1A1A"}, 
                            ],
                            page_action="native",
                            page_size=10,
                        )
                    )
                ], className="table-panel-new-theme p-4"),
                width=12
            )
        ], className="g-4 mb-5")
    ],
    width=12,
    className="main-content-new-theme"
)

# --- Callbacks ---

# Callback for routing
@app.callback(Output('page-content', 'children'),
              Input('url', 'pathname'))
def display_page(pathname):
    if pathname == '/savings':
        return savings_monitor_layout
    elif pathname == '/investments':  # New Investments page
        return investments_layout
    elif pathname == '/analytics':
        return html.Div([html.H3("Analytics & Trends Page - Under Construction", className="text-light text-center mt-5")])
    elif pathname == '/data-table':
        return html.Div([html.H3("Raw Data Table Page - Under Construction", className="text-light text-center mt-5")])
    elif pathname == '/settings':
        return html.Div([html.H3("Configuration Page - Under Construction", className="text-light text-center mt-5")])
    else:
        return dashboard_page_layout

# Callback to load data on app startup AND on interval
@app.callback(
    Output('stored-icic-data', 'data'),
    Output('stored-canara-data', 'data'),
    Output('stored-investments-data', 'data'),  # New output for investments data
    Output('loading-error-message', 'data'),
    Input('interval-component', 'n_intervals'),
)
def load_and_store_data(n_intervals):
    print(f"Attempting to load data... Interval count: {n_intervals}")
    df_icic_loaded, df_canara_loaded, df_investments_loaded, error = load_data_from_google_sheets()
    
    return (
        df_icic_loaded.to_json(date_format='iso', orient='split') if not df_icic_loaded.empty else None,
        df_canara_loaded.to_json(date_format='iso', orient='split') if not df_canara_loaded.empty else None,
        df_investments_loaded.to_json(date_format='iso', orient='split') if not df_investments_loaded.empty else None,  # New return
        error
    )

# Callback to display data load status and populate filter dropdowns (for Dashboard)
@app.callback(
    Output('data-load-status', 'children'),
    Output('month-filter', 'options'),
    Output('category-filter', 'options'),
    Input('stored-icic-data', 'data'),
    Input('loading-error-message', 'data'),
    State('url', 'pathname')
)
def update_load_status_and_filters(stored_icic_data_json, error_message, pathname):
    if pathname != '/':
        return no_update, no_update, no_update

    available_months = []
    available_categories = []

    if error_message:
        return dbc.Alert(
            [html.I(className="bi bi-exclamation-triangle-fill me-2"), error_message],
            color="danger", className="fade-in"
        ), available_months, available_categories
    elif stored_icic_data_json:
        df_from_store = pd.read_json(stored_icic_data_json, orient='split')
        if df_from_store.empty:
            return dbc.Alert(
                [html.I(className="bi bi-info-circle-fill me-2"), "ICIC data loaded, but it's empty. Please check your Google Sheet for content."],
                color="warning", className="fade-in"
            ), available_months, available_categories
        else:
            available_months = sorted(df_from_store["Month"].unique())
            available_categories = sorted(df_from_store["Category"].unique())
            month_options = [{"label": month, "value": month} for month in available_months]
            category_options = [{"label": cat, "value": cat} for cat in available_categories]
            
            month_options.insert(0, {"label": "All Months", "value": "ALL_MONTHS"})
            category_options.insert(0, {"label": "All Categories", "value": "ALL_CATEGORIES"})

            return dbc.Alert(
                [html.I(className="bi bi-check-circle-fill me-2"), "Data loaded successfully!"],
                color="success", className="fade-out"
            ), month_options, category_options
    return dbc.Alert(
        [html.I(className="bi bi-hourglass-split me-2"), "Loading data..."],
        color="info", className="fade-in"
    ), available_months, available_categories

# Callback to update Dashboard KPIs, Graphs, and Table based on filters
@app.callback(
    Output("total-expenses-kpi", "children"),
    Output("avg-monthly-kpi", "children"),
    Output("highest-month-kpi-name", "children"),
    Output("highest-month-kpi-value", "children"),
    Output("lowest-month-kpi-name", "children"),
    Output("lowest-month-kpi-value", "children"),
    Output("monthly-expenses-trend-chart", "figure"),
    Output("top-expense-categories-chart", "figure"),
    Output("monthly-expenses-by-category-chart", "figure"),
    Output("overview-data-table", "data"),
    Output("overview-data-table", "columns"),
    Input("month-filter", "value"),
    Input("category-filter", "value"),
    Input("stored-icic-data", "data"),
    State('url', 'pathname')
)
def update_dashboard_content(selected_months, selected_categories, stored_data_json, pathname):
    if pathname != '/':
        return no_update, no_update, no_update, no_update, \
               no_update, no_update, no_update, no_update, \
               no_update, no_update, no_update

    empty_figure = go.Figure()
    empty_figure.update_layout(
        template="plotly_dark",
        title_text=f"<span style='color:{CUSTOM_COLOR_PALETTE[0]}'>Data Not Found </span><br> <span style='font-size:12px;color:{CUSTOM_COLOR_PALETTE[5]}'>Adjust filters or check data source.</span>",
        height=300,
        xaxis={"visible": False},
        yaxis={"visible": False},
        annotations=[
            dict(text="No data available for current selection.",
                 xref="paper", yref="paper", showarrow=False,
                 font=dict(size=14, color=CUSTOM_COLOR_PALETTE[0]), align="center")
        ],
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)"
    )

    if stored_data_json is None:
        return (
            f"₹0.00", f"₹0.00", "N/A", f"₹0.00", "N/A", f"₹0.00",
            empty_figure, empty_figure, empty_figure,
            [], [{"name": "Loading Data...", "id": "loading"}]
        )

    df_from_store = pd.read_json(stored_data_json, orient='split')

    if df_from_store.empty:
        return (
            f"₹0.00", f"₹0.00", "N/A", f"₹0.00", "N/A", f"₹0.00",
            empty_figure, empty_figure, empty_figure,
            [], [{"name": "No Data", "id": "no_data"}]
        )

    filtered_df = df_from_store.copy()

    all_available_months = sorted(df_from_store["Month"].unique())
    all_available_categories = sorted(df_from_store["Category"].unique())

    if selected_months and "ALL_MONTHS" in selected_months:
        selected_months = all_available_months
    if selected_categories and "ALL_CATEGORIES" in selected_categories:
        selected_categories = all_available_categories

    if selected_months:
        filtered_df = filtered_df[filtered_df["Month"].isin(selected_months)]
    if selected_categories:
        filtered_df = filtered_df[filtered_df["Category"].isin(selected_categories)]

    if filtered_df.empty:
        return (
            f"₹0.00", f"₹0.00", "N/A", f"₹0.00", "N/A", f"₹0.00",
            empty_figure, empty_figure, empty_figure,
            [], [{"name": "No Data", "id": "no_data"}]
        )

    # Update KPIs
    current_total_expenses = filtered_df["Amount"].sum()
    monthly_summary_filtered = filtered_df.groupby("Month")["Amount"].sum().reset_index()
    current_avg_monthly = monthly_summary_filtered["Amount"].mean() if not monthly_summary_filtered.empty else 0

    if not monthly_summary_filtered.empty:
        current_highest = monthly_summary_filtered.loc[monthly_summary_filtered["Amount"].idxmax()]
        current_lowest = monthly_summary_filtered.loc[monthly_summary_filtered["Amount"].idxmin()]
        highest_kpi_name = current_highest['Month']
        highest_kpi_value = f"₹{current_highest['Amount']:,.2f}"
        lowest_kpi_name = current_lowest['Month']
        lowest_kpi_value = f"₹{current_lowest['Amount']:,.2f}"
    else:
        highest_kpi_name = "N/A"
        highest_kpi_value = f"₹0.00"
        lowest_kpi_name = "N/A"
        lowest_kpi_value = f"₹0.00"

    # Update Charts
    monthly_trend_chart_fig = px.area(
        monthly_summary_filtered,
        x="Month", y="Amount",
        title=f"<span style='color:{CUSTOM_COLOR_PALETTE[0]}'>Monthly Expense Trend</span>",
        labels={"Amount": "Amount (₹)"},
        template="plotly_dark",
        color_discrete_sequence=[CUSTOM_COLOR_PALETTE[0]],
        line_shape='spline',
        hover_name="Month",
        hover_data={"Amount": ":,.2f"}
    )
    monthly_trend_chart_fig.update_layout(xaxis_title=None, yaxis_title="Amount (₹)", plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)")
    monthly_trend_chart_fig.update_traces(fillcolor="rgba(0, 255, 255, 0.2)", line=dict(width=3, color=CUSTOM_COLOR_PALETTE[0]))

    top_expenses_filtered = filtered_df.groupby("Category")["Amount"].sum().nlargest(5).reset_index()
    pie_chart_fig = px.pie(
        top_expenses_filtered,
        values="Amount", names="Category",
        title=f"<span style='color:{CUSTOM_COLOR_PALETTE[1]}'>Top Expense Categories</span>",
        hole=0.4,
        template="plotly_dark",
        color_discrete_sequence=CUSTOM_COLOR_PALETTE
    )
    pie_chart_fig.update_traces(textinfo="percent+label", pull=[0.05] * len(top_expenses_filtered), marker=dict(line=dict(color='rgba(0,0,0,0)', width=1)))
    pie_chart_fig.update_layout(plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)')

    monthly_category_chart_fig = px.bar(
        filtered_df,
        x="Month", y="Amount", color="Category",
        title=f"<span style='color:{CUSTOM_COLOR_PALETTE[2]}'>Monthly Expenses by Category</span>",
        labels={"Amount": "Amount (₹)", "Category": "Expense Category"},
        template="plotly_dark",
        barmode="relative",
        color_discrete_sequence=CUSTOM_COLOR_PALETTE
    )
    monthly_category_chart_fig.update_layout(xaxis_title=None, yaxis_title="Amount (₹)", plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)')

    pivot_filtered = (
        filtered_df.pivot_table(index="Category", columns="Month", values="Amount", aggfunc="sum", fill_value=0)
        .reset_index()
    )
    table_data = pivot_filtered.to_dict("records")
    table_columns = [{"name": c, "id": c} for c in pivot_filtered.columns]

    return (
        f"₹{current_total_expenses:,.2f}",
        f"₹{current_avg_monthly:,.2f}",
        highest_kpi_name,
        highest_kpi_value,
        lowest_kpi_name,
        lowest_kpi_value,
        monthly_trend_chart_fig,
        pie_chart_fig,
        monthly_category_chart_fig,
        table_data,
        table_columns
    )

# Callback to populate savings filter dropdowns
@app.callback(
    Output('savings-month-filter', 'options'),
    Output('savings-category-filter', 'options'),
    Input('stored-canara-data', 'data'),
    State('url', 'pathname')
)
def populate_savings_filters(stored_canara_data_json, pathname):
    if pathname != '/savings':
        return no_update, no_update

    available_months = []
    available_categories = []

    if stored_canara_data_json:
        df_from_store = pd.read_json(stored_canara_data_json, orient='split')
        if not df_from_store.empty:
            available_months = sorted(df_from_store["Month"].unique())
            available_categories = sorted(df_from_store["Category"].unique())
            
            month_options = [{"label": month, "value": month} for month in available_months]
            category_options = [{"label": cat, "value": cat} for cat in available_categories]
            
            month_options.insert(0, {"label": "All Months", "value": "ALL_MONTHS"})
            category_options.insert(0, {"label": "All Categories", "value": "ALL_CATEGORIES"})

            return month_options, category_options
    
    return [], []

# Callback to populate investments filter dropdowns
@app.callback(
    Output('investments-month-filter', 'options'),
    Output('investments-category-filter', 'options'),
    Input('stored-investments-data', 'data'),
    State('url', 'pathname')
)
def populate_investments_filters(stored_investments_data_json, pathname):
    if pathname != '/investments':
        return no_update, no_update

    available_months = []
    available_categories = []

    if stored_investments_data_json:
        df_from_store = pd.read_json(stored_investments_data_json, orient='split')
        if not df_from_store.empty:
            available_months = sorted(df_from_store["Month"].unique())
            available_categories = sorted(df_from_store["Category"].unique())
            
            month_options = [{"label": month, "value": month} for month in available_months]
            category_options = [{"label": cat, "value": cat} for cat in available_categories]
            
            month_options.insert(0, {"label": "All Months", "value": "ALL_MONTHS"})
            category_options.insert(0, {"label": "All Categories", "value": "ALL_CATEGORIES"})

            return month_options, category_options
    
    return [], []

# Callback to update Savings Monitor KPIs, Graphs, and Table
@app.callback(
    Output("total-savings-credit-kpi", "children"),
    Output("total-savings-debit-kpi", "children"),
    Output("net-savings-kpi", "children"),
    Output("savings-monthly-trend-chart", "figure"),
    Output("savings-category-bar-chart", "figure"),
    Output("savings-data-table", "data"),
    Output("savings-data-table", "columns"),
    Input("stored-canara-data", "data"),
    Input("savings-month-filter", "value"),
    Input("savings-category-filter", "value"),
    Input("savings-reset-filters-button", "n_clicks"),
    State('url', 'pathname')
)
def update_savings_monitor_content(stored_canara_data_json, selected_months, selected_categories, n_clicks, pathname):
    if pathname != '/savings':
        return no_update, no_update, no_update, \
               no_update, no_update, no_update, no_update

    empty_figure = go.Figure()
    empty_figure.update_layout(
        template="plotly_dark",
        title_text=f"<span style='color:{CUSTOM_COLOR_PALETTE[0]}'>Savings Data Not Found </span><br> <span style='font-size:12px;color:{CUSTOM_COLOR_PALETTE[5]}'>Check data source.</span>",
        height=300,
        xaxis={"visible": False},
        yaxis={"visible": False},
        annotations=[
            dict(text="No savings data available.",
                 xref="paper", yref="paper", showarrow=False,
                 font=dict(size=14, color=CUSTOM_COLOR_PALETTE[0]), align="center")
        ],
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)"
    )

    if stored_canara_data_json is None:
        return (
            f"₹0.00", f"₹0.00", f"₹0.00",
            empty_figure, empty_figure,
            [], [{"name": "Loading Data...", "id": "loading"}]
        )

    df_canara_from_store = pd.read_json(stored_canara_data_json, orient='split')

    if df_canara_from_store.empty:
        return (
            f"₹0.00", f"₹0.00", f"₹0.00",
            empty_figure, empty_figure,
            [], [{"name": "No Data", "id": "no_data"}]
        )

    filtered_df = df_canara_from_store.copy()

    all_available_months = sorted(df_canara_from_store["Month"].unique())
    all_available_categories = sorted(df_canara_from_store["Category"].unique())

    if selected_months and "ALL_MONTHS" in selected_months:
        selected_months = all_available_months
    if selected_categories and "ALL_CATEGORIES" in selected_categories:
        selected_categories = all_available_categories

    if selected_months:
        filtered_df = filtered_df[filtered_df["Month"].isin(selected_months)]
    if selected_categories:
        filtered_df = filtered_df[filtered_df["Category"].isin(selected_categories)]

    if filtered_df.empty:
        return (
            f"₹0.00", f"₹0.00", f"₹0.00",
            empty_figure, empty_figure,
            [], [{"name": "No Data", "id": "no_data"}]
        )

    total_credit = filtered_df["Credit"].sum()
    total_debit = filtered_df["Debit"].sum()
    net_savings = total_credit - total_debit

    monthly_savings_summary = filtered_df.groupby("Month").agg(
        Total_Credit=("Credit", "sum"),
        Total_Debit=("Debit", "sum")
    ).reset_index()
    monthly_savings_summary["Net_Savings"] = monthly_savings_summary["Total_Credit"] - monthly_savings_summary["Total_Debit"]

    savings_trend_fig = go.Figure()
    savings_trend_fig.add_trace(go.Scatter(
        x=monthly_savings_summary["Month"], y=monthly_savings_summary["Total_Credit"],
        mode='lines+markers', name='Total Credit', line=dict(color=CUSTOM_COLOR_PALETTE[2], width=3)
    ))
    savings_trend_fig.add_trace(go.Scatter(
        x=monthly_savings_summary["Month"], y=monthly_savings_summary["Total_Debit"],
        mode='lines+markers', name='Total Debit', line=dict(color=CUSTOM_COLOR_PALETTE[1], width=3)
    ))
    savings_trend_fig.add_trace(go.Scatter(
        x=monthly_savings_summary["Month"], y=monthly_savings_summary["Net_Savings"],
        mode='lines+markers', name='Net Savings', line=dict(color=CUSTOM_COLOR_PALETTE[0], width=3, dash='dash')
    ))

    savings_trend_fig.update_layout(
        template="plotly_dark",
        title=f"<span style='color:{CUSTOM_COLOR_PALETTE[0]}'>Monthly Savings Trend</span>",
        xaxis_title=None,
        yaxis_title="Amount (₹)",
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        hovermode="x unified"
    )

    category_summary = filtered_df.groupby("Category").agg(
        Total_Credit=("Credit", "sum"),
        Total_Debit=("Debit", "sum")
    ).reset_index()

    savings_category_fig = go.Figure(data=[
        go.Bar(name='Total Credit', x=category_summary['Category'], y=category_summary['Total_Credit'], marker_color=CUSTOM_COLOR_PALETTE[2]),
        go.Bar(name='Total Debit', x=category_summary['Category'], y=category_summary['Total_Debit'], marker_color=CUSTOM_COLOR_PALETTE[1])
    ])
    savings_category_fig.update_layout(
        barmode='group',
        template="plotly_dark",
        title=f"<span style='color:{CUSTOM_COLOR_PALETTE[1]}'>Savings by Category (Credit vs. Debit)</span>",
        xaxis_title="Category",
        yaxis_title="Amount (₹)",
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)"
    )

    canara_table_data = filtered_df.to_dict("records")
    canara_table_columns = [{"name": col, "id": col} for col in filtered_df.columns]

    return (
        f"₹{total_credit:,.2f}",
        f"₹{total_debit:,.2f}",
        f"₹{net_savings:,.2f}",
        savings_trend_fig,
        savings_category_fig,
        canara_table_data,
        canara_table_columns
    )

# Callback to update Investments KPIs, Graphs, and Table
@app.callback(
    Output("total-investments-kpi", "children"),
    Output("avg-monthly-investment-kpi", "children"),
    Output("highest-category-kpi-name", "children"),
    Output("highest-category-kpi-value", "children"),
    Output("lowest-category-kpi-name", "children"),
    Output("lowest-category-kpi-value", "children"),
    Output("lic-installments-kpi", "children"),
    Output("kumaran-installments-kpi", "children"),
    Output("thangamayil-installments-kpi", "children"),
    Output("investments-monthly-trend-chart", "figure"),
    Output("investments-categories-chart", "figure"),
    Output("investments-by-category-chart", "figure"),
    Output("investments-data-table", "data"),
    Output("investments-data-table", "columns"),
    Input("stored-investments-data", "data"),
    Input("investments-month-filter", "value"),
    Input("investments-category-filter", "value"),
    Input("investments-reset-filters-button", "n_clicks"),
    Input('url', 'pathname')  # ADDED: This line is the fix
)
def update_investments_content(stored_investments_data_json, selected_months, selected_categories, n_clicks, pathname):
    if pathname != '/investments':
        return no_update, no_update, no_update, no_update, \
               no_update, no_update, no_update, no_update, \
               no_update, no_update, no_update, no_update, \
               no_update, no_update

    empty_figure = go.Figure()
    empty_figure.update_layout(
        template="plotly_dark",
        title_text=f"<span style='color:{CUSTOM_COLOR_PALETTE[0]}'>Investments Data Not Found </span><br> <span style='font-size:12px;color:{CUSTOM_COLOR_PALETTE[5]}'>Check data source.</span>",
        height=300,
        xaxis={"visible": False},
        yaxis={"visible": False},
        annotations=[
            dict(text="No investments data available.",
                 xref="paper", yref="paper", showarrow=False,
                 font=dict(size=14, color=CUSTOM_COLOR_PALETTE[0]), align="center")
        ],
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)"
    )

    if stored_investments_data_json is None:
        return (
            f"₹0.00", f"₹0.00", "N/A", f"₹0.00", "N/A", f"₹0.00",
            "N/A", "N/A", "N/A",
            empty_figure, empty_figure, empty_figure,
            [], [{"name": "Loading Data...", "id": "loading"}]
        )

    df_investments_from_store = pd.read_json(stored_investments_data_json, orient='split')

    if df_investments_from_store.empty:
        return (
            f"₹0.00", f"₹0.00", "N/A", f"₹0.00", "N/A", f"₹0.00",
            "N/A", "N/A", "N/A",
            empty_figure, empty_figure, empty_figure,
            [], [{"name": "No Data", "id": "no_data"}]
        )

    filtered_df = df_investments_from_store.copy()

    all_available_months = sorted(filtered_df["Month"].unique())
    all_available_categories = sorted(filtered_df["Category"].unique())

    if selected_months and "ALL_MONTHS" in selected_months:
        selected_months = all_available_months
    if selected_categories and "ALL_CATEGORIES" in selected_categories:
        selected_categories = all_available_categories

    if selected_months:
        filtered_df = filtered_df[filtered_df["Month"].isin(selected_months)]
    if selected_categories:
        filtered_df = filtered_df[filtered_df["Category"].isin(selected_categories)]

    if filtered_df.empty:
        return (
            f"₹0.00", f"₹0.00", "N/A", f"₹0.00", "N/A", f"₹0.00",
            "N/A", "N/A", "N/A",
            empty_figure, empty_figure, empty_figure,
            [], [{"name": "No Data", "id": "no_data"}]
        )

    # Update KPIs
    current_total_investments = filtered_df["Amount"].sum()
    monthly_summary_filtered = filtered_df.groupby("Month")["Amount"].sum().reset_index()
    current_avg_monthly = monthly_summary_filtered["Amount"].mean() if not monthly_summary_filtered.empty else 0

    category_summary = filtered_df.groupby("Category")["Amount"].sum().reset_index()
    if not category_summary.empty:
        current_highest = category_summary.loc[category_summary["Amount"].idxmax()]
        current_lowest = category_summary.loc[category_summary["Amount"].idxmin()]
        highest_kpi_name = current_highest['Category']
        highest_kpi_value = f"₹{current_highest['Amount']:,.2f}"
        lowest_kpi_name = current_lowest['Category']
        lowest_kpi_value = f"₹{current_lowest['Amount']:,.2f}"
    else:
        highest_kpi_name = "N/A"
        highest_kpi_value = f"₹0.00"
        lowest_kpi_name = "N/A"
        lowest_kpi_value = f"₹0.00"

    # --- New KPI Calculations for Installments ---
    lic_total_months = 15 * 12
    kumaran_total_months = 11
    thangamayil_total_months = 11

    lic_paid = filtered_df[filtered_df['Category'] == 'LIC'].shape[0]
    kumaran_paid = filtered_df[filtered_df['Category'] == 'KUMARAN'].shape[0]
    thangamayil_paid = filtered_df[filtered_df['Category'] == 'THANGAMAYIL'].shape[0]
    
    lic_remaining = max(0, lic_total_months - lic_paid)
    kumaran_remaining = max(0, kumaran_total_months - kumaran_paid)
    thangamayil_remaining = max(0, thangamayil_total_months - thangamayil_paid)

    # Update Charts
    monthly_trend_chart_fig = px.area(
        monthly_summary_filtered,
        x="Month", y="Amount",
        title=f"<span style='color:{CUSTOM_COLOR_PALETTE[0]}'>Monthly Investment Trend</span>",
        labels={"Amount": "Amount (₹)"},
        template="plotly_dark",
        color_discrete_sequence=[CUSTOM_COLOR_PALETTE[4]],  # RoyalBlue
        line_shape='spline',
        hover_name="Month",
        hover_data={"Amount": ":,.2f"}
    )
    monthly_trend_chart_fig.update_layout(xaxis_title=None, yaxis_title="Amount (₹)", plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)")
    monthly_trend_chart_fig.update_traces(fillcolor="rgba(65, 105, 225, 0.2)", line=dict(width=3, color=CUSTOM_COLOR_PALETTE[4]))

    pie_chart_fig = px.pie(
        category_summary,
        values="Amount", names="Category",
        title=f"<span style='color:{CUSTOM_COLOR_PALETTE[1]}'>Investment Categories</span>",
        hole=0.4,
        template="plotly_dark",
        color_discrete_sequence=CUSTOM_COLOR_PALETTE
    )
    pie_chart_fig.update_traces(textinfo="percent+label", pull=[0.05] * len(category_summary), marker=dict(line=dict(color='rgba(0,0,0,0)', width=1)))
    pie_chart_fig.update_layout(plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)')

    category_monthly_chart_fig = px.bar(
        filtered_df,
        x="Month", y="Amount", color="Category",
        title=f"<span style='color:{CUSTOM_COLOR_PALETTE[2]}'>Monthly Investments by Category</span>",
        labels={"Amount": "Amount (₹)", "Category": "Investment Category"},
        template="plotly_dark",
        barmode="stack",
        color_discrete_sequence=CUSTOM_COLOR_PALETTE
    )
    category_monthly_chart_fig.update_layout(xaxis_title=None, yaxis_title="Amount (₹)", plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)')

    pivot_filtered = (
        filtered_df.pivot_table(index="Category", columns="Month", values="Amount", aggfunc="sum", fill_value=0)
        .reset_index()
    )
    table_data = pivot_filtered.to_dict("records")
    table_columns = [{"name": c, "id": c} for c in pivot_filtered.columns]

    return (
        f"₹{current_total_investments:,.2f}",
        f"₹{current_avg_monthly:,.2f}",
        highest_kpi_name,
        highest_kpi_value,
        lowest_kpi_name,
        lowest_kpi_value,
        f"{lic_remaining} of {lic_total_months}",
        f"{kumaran_remaining} of {kumaran_total_months}",
        f"{thangamayil_remaining} of {thangamayil_total_months}",
        monthly_trend_chart_fig,
        pie_chart_fig,
        category_monthly_chart_fig,
        table_data,
        table_columns
    )

# Callback to reset filters for Dashboard
@app.callback(
    Output("month-filter", "value"),
    Output("category-filter", "value"),
    Input("reset-filters-button", "n_clicks"),
    State('url', 'pathname')
)
def reset_filters(n_clicks, pathname):
    if pathname != '/' or not (n_clicks and n_clicks > 0):
        return no_update, no_update
    return [], []

# Callback to reset filters for Savings Monitor
@app.callback(
    Output("savings-month-filter", "value"),
    Output("savings-category-filter", "value"),
    Input("savings-reset-filters-button", "n_clicks"),
    State('url', 'pathname')
)
def reset_savings_filters(n_clicks, pathname):
    if pathname != '/savings' or not (n_clicks and n_clicks > 0):
        return no_update, no_update
    return [], []

# Callback to reset filters for Investments
@app.callback(
    Output("investments-month-filter", "value"),
    Output("investments-category-filter", "value"),
    Input("investments-reset-filters-button", "n_clicks"),
    State('url', 'pathname')
)
def reset_investments_filters(n_clicks, pathname):
    if pathname != '/investments' or not (n_clicks and n_clicks > 0):
        return no_update, no_update
    return [], []

# Callback for Savings Goal Calculator
@app.callback(
    Output("savings-goal-output", "children"),
    Input("calculate-goal-button", "n_clicks"),
    State("target-amount-input", "value"),
    State("duration-input", "value"),
    State("stored-canara-data", "data"),
    prevent_initial_call=True
)
def calculate_savings_goal(n_clicks, target_amount, duration, stored_canara_data_json):
    if not n_clicks:
        return no_update

    if stored_canara_data_json is None:
        return html.P("No savings data available to calculate goals.", className="text-danger")

    df_canara = pd.read_json(stored_canara_data_json, orient='split')

    if df_canara.empty:
        return html.P("Empty savings data. Cannot calculate goals.", className="text-warning")

    monthly_summary = df_canara.groupby("Month").agg(
        Total_Credit=("Credit", "sum"),
        Total_Debit=("Debit", "sum")
    ).reset_index()
    monthly_summary["Net_Savings"] = monthly_summary["Total_Credit"] - monthly_summary["Total_Debit"]
    
    historical_avg_monthly_net_savings = monthly_summary["Net_Savings"].mean() if not monthly_summary.empty else 0

    target_amount = float(target_amount) if target_amount is not None else None
    duration = int(duration) if duration is not None else None

    if target_amount is None and duration is None:
        return html.P("Please enter a Target Amount, Duration, or both.", className="text-info")

    elif target_amount is not None and duration is not None:
        if duration <= 0:
            return html.P("Duration must be a positive number of months.", className="text-danger")
        required_monthly_savings = target_amount / duration
        
        output_message = f"To save ₹{target_amount:,.2f} in {duration} months, you need to save " \
                         f"₹{required_monthly_savings:,.2f} per month. <br>"
        
        if historical_avg_monthly_net_savings > 0:
            output_message += f"Your historical average monthly net savings is ₹{historical_avg_monthly_net_savings:,.2f}. "
            if required_monthly_savings > historical_avg_monthly_net_savings:
                diff = required_monthly_savings - historical_avg_monthly_net_savings
                output_message += f"You need to increase your monthly savings by ₹{diff:,.2f}."
            elif required_monthly_savings < historical_avg_monthly_net_savings:
                diff = historical_avg_monthly_net_savings - required_monthly_savings
                output_message += f"You are currently saving ₹{diff:,.2f} more than needed for this goal!"
            else:
                output_message += "You are on track to meet this goal with your current savings rate!"
        else:
             output_message += "Your historical average monthly net savings is ₹0.00. You need to start saving!"
        
        return html.P(output_message)

    elif target_amount is not None:
        if historical_avg_monthly_net_savings <= 0:
            return html.P("Your historical average monthly net savings is ₹0.00 or less. Cannot predict time to goal.", className="text-warning")
        
        time_needed_months = target_amount / historical_avg_monthly_net_savings
        
        return html.P(
            f"At your historical average monthly net savings of ₹{historical_avg_monthly_net_savings:,.2f}, "
            f"it will take approximately {time_needed_months:,.1f} months to save ₹{target_amount:,.2f}."
        )

    elif duration is not None:
        if duration <= 0:
            return html.P("Duration must be a positive number of months.", className="text-danger")
        
        if historical_avg_monthly_net_savings <= 0:
            return html.P("Your historical average monthly net savings is ₹0.00 or less. You won't save anything in this duration.", className="text-warning")

        projected_savings = historical_avg_monthly_net_savings * duration
        return html.P(
            f"At your historical average monthly net savings of ₹{historical_avg_monthly_net_savings:,.2f}, "
            f"you will save approximately ₹{projected_savings:,.2f} in {duration} months."
        )
    
    return html.P("Please enter valid numbers for target amount and/or duration.", className="text-danger")

if __name__ == "__main__":
    app.run_server(debug=True)