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
import json
import tempfile
import base64

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
# IMPORTANT: This section has been updated to handle credentials securely
# for deployment.

# Check for credentials in an environment variable for deployment
if "GCP_SA_CREDENTIALS" in os.environ:
    credentials_content_base64 = os.environ.get("GCP_SA_CREDENTIALS")
    try:
        # Decode the Base64 string
        credentials_content = base64.b64decode(credentials_content_base64).decode('utf-8')
        # Create a temporary file to hold the credentials
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json') as temp_file:
            temp_file.write(credentials_content)
            SERVICE_ACCOUNT_FILE = temp_file.name
        print("Authenticated using Base64 environment variable.")
    except (json.JSONDecodeError, ValueError) as e:
        print(f"Error parsing JSON from environment variable: {e}")
        SERVICE_ACCOUNT_FILE = None
        raise Exception("Failed to load service account credentials from environment variable.")
else:
    # Fallback to local file path for local development
    SERVICE_ACCOUNT_FILE = r"C:\Users\JEEVALAKSHMI R\Videos\dashboard_for_expense\icic-salary-data-52568c61b6e3.json"
    print("Using local service account file path. Set GCP_SA_CREDENTIALS for deployment.")
    
def load_data_from_google_sheets():
    df_icic = pd.DataFrame()
    df_canara = pd.DataFrame()
    df_investments = pd.DataFrame()
    error_message = None
    
    # This check is for local development only. Render will handle the environment variable.
    if not os.path.exists(SERVICE_ACCOUNT_FILE) and "GCP_SA_CREDENTIALS" not in os.environ:
        error_message = f"❌ Error: Service account file not found at {SERVICE_ACCOUNT_FILE}. Please update the path."
        return df_icic, df_canara, df_investments, error_message
    
    try:
        scope = [
            "https://www.googleapis.com/auth/spreadsheets.readonly",
            "https://www.googleapis.com/auth/drive.readonly",
        ]
        creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=scope)
        client = gspread.authorize(creds)
        print("Authentication successful!")

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
        dcc.Store(id='stored-investments-data'),
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
                                dbc.NavLink([html.I(className="bi bi-currency-exchange me-2"), "Investments"], href="/investments", className="nav-link-new-theme"),
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
                    html.H4("📈 Detailed Savings Data", className="section-title-new-theme text-center mb-4"),
                    dcc.Loading(
                        id="loading-savings-table", type="circle", color=CUSTOM_COLOR_PALETTE[2],
                        children=dash_table.DataTable(
                            id="savings-data-table",
                            data=[],
                            columns=[],
                            style_table={"overflowX": "auto"},
                            style_cell={"textAlign": "center", "padding": "12px", "fontFamily": "Open Sans, sans-serif", "fontSize": "0.9em"},
                            style_header={"backgroundColor": "#000000", "color": "#FF00FF", "fontWeight": "bold", "borderBottom": "2px solid #39FF14"},
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

# --- Layout for the Analytics & Trends Page ---
analytics_page_layout = dbc.Col(
    [
        dbc.Row(
            dbc.Col(
                html.H2("📈 Analytics & Trends", className="section-title-new-theme text-center mb-4", style={'color': 'var(--accent-blue)', 'textShadow': 'var(--glow-blue)'}),
                width=12
            )
        ),
        dbc.Row(
            dbc.Col(
                dbc.Card(
                    dbc.CardBody([
                        html.H5("Select Data for Trend Analysis", className="card-title-new-theme text-center mb-3"),
                        dbc.Row([
                            dbc.Col(
                                html.Div([
                                    html.Label("Chart Type:", className="form-label-new-theme"),
                                    dcc.Dropdown(
                                        id="chart-type-dropdown",
                                        options=[
                                            {'label': 'Line Chart (Time Series)', 'value': 'line'},
                                            {'label': 'Area Chart', 'value': 'area'},
                                            {'label': 'Bar Chart (Comparison)', 'value': 'bar'}
                                        ],
                                        value='line',
                                        clearable=False,
                                        className="dropdown-new-theme"
                                    ),
                                ]),
                                lg=4, md=6, sm=12, className="mb-3"
                            ),
                            dbc.Col(
                                html.Div([
                                    html.Label("Select Month(s):", className="form-label-new-theme"),
                                    dcc.Dropdown(
                                        id="analytics-month-filter",
                                        options=[],
                                        multi=True,
                                        placeholder="All Months",
                                        className="dropdown-new-theme"
                                    ),
                                ]),
                                lg=4, md=6, sm=12, className="mb-3"
                            ),
                            dbc.Col(
                                html.Div([
                                    html.Label("Select Category(s):", className="form-label-new-theme"),
                                    dcc.Dropdown(
                                        id="analytics-category-filter",
                                        options=[],
                                        multi=True,
                                        placeholder="All Categories",
                                        className="dropdown-new-theme"
                                    ),
                                ]),
                                lg=4, md=12, sm=12, className="mb-3"
                            ),
                        ], className="g-3 justify-content-center")
                    ]),
                    className="filter-card-new-theme mb-5"
                ),
                width=12
            )
        ),
        dbc.Row([
            dbc.Col(dcc.Loading(id="loading-analytics-chart", type="circle", color=CUSTOM_COLOR_PALETTE[3], children=dcc.Graph(id="analytics-chart")), width=12, className="mb-4 chart-panel-new-theme"),
        ], className="g-4")
    ],
    width=12,
    className="main-content-new-theme"
)

# --- Layout for the Raw Data Table Page ---
data_table_layout = dbc.Col(
    [
        dbc.Row(
            dbc.Col(
                html.H2("📝 Raw Data Tables", className="section-title-new-theme text-center mb-4", style={'color': 'var(--accent-purple)', 'textShadow': 'var(--glow-purple)'}),
                width=12
            )
        ),
        dbc.Row([
            dbc.Col(
                html.Div([
                    html.H4("ICIC Salary Data", className="section-title-new-theme text-center mb-4"),
                    dcc.Loading(
                        id="loading-raw-icic", type="circle", color=CUSTOM_COLOR_PALETTE[0],
                        children=dash_table.DataTable(
                            id="raw-icic-table",
                            data=[],
                            columns=[],
                            style_table={"overflowX": "auto"},
                            style_cell={"textAlign": "left", "padding": "12px", "fontFamily": "Open Sans, sans-serif", "fontSize": "0.9em"},
                            style_header={"backgroundColor": "#000000", "color": "#00FFFF", "fontWeight": "bold", "borderBottom": "2px solid #00FF00"},
                            style_data={"backgroundColor": "#1A1A1A", "color": "#E0E0E0", "borderBottom": "1px solid rgba(255, 255, 255, 0.05)"},
                            style_data_conditional=[
                                {"if": {"row_index": "odd"}, "backgroundColor": "#121212"},
                                {"if": {"row_index": "even"}, "backgroundColor": "#1A1A1A"}, 
                            ],
                            page_action="native",
                            page_size=10,
                            sort_action="native",
                            filter_action="native",
                        )
                    )
                ], className="table-panel-new-theme p-4 mb-5"),
                width=12
            )
        ], className="g-4"),
        dbc.Row([
            dbc.Col(
                html.Div([
                    html.H4("CANARA Savings Data", className="section-title-new-theme text-center mb-4"),
                    dcc.Loading(
                        id="loading-raw-canara", type="circle", color=CUSTOM_COLOR_PALETTE[1],
                        children=dash_table.DataTable(
                            id="raw-canara-table",
                            data=[],
                            columns=[],
                            style_table={"overflowX": "auto"},
                            style_cell={"textAlign": "left", "padding": "12px", "fontFamily": "Open Sans, sans-serif", "fontSize": "0.9em"},
                            style_header={"backgroundColor": "#000000", "color": "#FF00FF", "fontWeight": "bold", "borderBottom": "2px solid #39FF14"},
                            style_data={"backgroundColor": "#1A1A1A", "color": "#E0E0E0", "borderBottom": "1px solid rgba(255, 255, 255, 0.05)"},
                            style_data_conditional=[
                                {"if": {"row_index": "odd"}, "backgroundColor": "#121212"},
                                {"if": {"row_index": "even"}, "backgroundColor": "#1A1A1A"}, 
                            ],
                            page_action="native",
                            page_size=10,
                            sort_action="native",
                            filter_action="native",
                        )
                    )
                ], className="table-panel-new-theme p-4 mb-5"),
                width=12
            )
        ], className="g-4"),
        dbc.Row([
            dbc.Col(
                html.Div([
                    html.H4("Investments Data", className="section-title-new-theme text-center mb-4"),
                    dcc.Loading(
                        id="loading-raw-investments", type="circle", color=CUSTOM_COLOR_PALETTE[2],
                        children=dash_table.DataTable(
                            id="raw-investments-table",
                            data=[],
                            columns=[],
                            style_table={"overflowX": "auto"},
                            style_cell={"textAlign": "left", "padding": "12px", "fontFamily": "Open Sans, sans-serif", "fontSize": "0.9em"},
                            style_header={"backgroundColor": "#000000", "color": "#39FF14", "fontWeight": "bold", "borderBottom": "2px solid #8A2BE2"},
                            style_data={"backgroundColor": "#1A1A1A", "color": "#E0E0E0", "borderBottom": "1px solid rgba(255, 255, 255, 0.05)"},
                            style_data_conditional=[
                                {"if": {"row_index": "odd"}, "backgroundColor": "#121212"},
                                {"if": {"row_index": "even"}, "backgroundColor": "#1A1A1A"}, 
                            ],
                            page_action="native",
                            page_size=10,
                            sort_action="native",
                            filter_action="native",
                        )
                    )
                ], className="table-panel-new-theme p-4 mb-5"),
                width=12
            )
        ], className="g-4")
    ],
    width=12,
    className="main-content-new-theme"
)

# --- Layout for the Investments Page ---
investments_page_layout = dbc.Col(
    [
        dbc.Row(
            dbc.Col(
                html.H2("📈 Investments", className="section-title-new-theme text-center mb-4", style={'color': 'var(--accent-cyan)', 'textShadow': 'var(--glow-cyan)'}),
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
                    html.H4("₹0.00", id="total-investments-kpi", className="kpi-value-new-theme primary-kpi", style={'color': 'var(--accent-lime)', 'textShadow': 'var(--glow-lime)'}),
                ]), className="kpi-card-new-theme"
            ), lg=4, md=6, sm=12, className="mb-4"),
            dbc.Col(dbc.Card(
                dbc.CardBody([
                    html.P("Avg Monthly Investment", className="kpi-label-new-theme"),
                    html.H4("₹0.00", id="avg-monthly-investment-kpi", className="kpi-value-new-theme accent-kpi", style={'color': 'var(--accent-magenta)', 'textShadow': 'var(--glow-magenta)'}),
                ]), className="kpi-card-new-theme"
            ), lg=4, md=6, sm=12, className="mb-4"),
            dbc.Col(dbc.Card(
                dbc.CardBody([
                    html.P("Highest Category", className="kpi-label-new-theme"),
                    html.H5("N/A", id="highest-investments-kpi-name", className="kpi-value-small-new-theme text-warning", style={'color': 'var(--accent-gold)', 'textShadow': 'var(--glow-gold)'}),
                    html.P("₹0.00", id="highest-investments-kpi-value", className="kpi-sub-value-new-theme-small"),
                ]), className="kpi-card-new-theme"
            ), lg=4, md=12, sm=12, className="mb-4"),
        ], className="g-4 mb-5"),
        # Charts for Investments
        dbc.Row([
            dbc.Col(dcc.Loading(id="loading-investments-pie-chart", type="circle", color=CUSTOM_COLOR_PALETTE[0], children=dcc.Graph(id="investments-pie-chart")), lg=6, md=12, className="mb-4 chart-panel-new-theme"),
            dbc.Col(dcc.Loading(id="loading-investments-bar-chart", type="circle", color=CUSTOM_COLOR_PALETTE[1], children=dcc.Graph(id="investments-bar-chart")), lg=6, md=12, className="mb-4 chart-panel-new-theme"),
        ], className="g-4"),
        # Data Table Section for Investments
        dbc.Row([
            dbc.Col(
                html.Div([
                    html.H4("📊 Detailed Investments Data", className="section-title-new-theme text-center mb-4"),
                    dcc.Loading(
                        id="loading-investments-table", type="circle", color=CUSTOM_COLOR_PALETTE[2],
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

# --- Layout for the Settings Page ---
settings_page_layout = dbc.Col(
    [
        dbc.Row(
            dbc.Col(
                html.H2("⚙️ Configuration & Settings", className="section-title-new-theme text-center mb-4", style={'color': 'var(--accent-gold)', 'textShadow': 'var(--glow-gold)'}),
                width=12
            )
        ),
        dbc.Row(
            dbc.Col(
                dbc.Card(
                    dbc.CardBody([
                        html.H5("Manage Data and Credentials", className="card-title-new-theme text-center mb-3"),
                        dbc.Row([
                            dbc.Col(
                                html.Div([
                                    html.Label("Spreadsheet URL:", className="form-label-new-theme"),
                                    dcc.Input(
                                        id="spreadsheet-url-input",
                                        type="url",
                                        placeholder="Enter Google Sheet URL...",
                                        className="form-control-new-theme w-100",
                                        value="https://docs.google.com/spreadsheets/d/1o1e8ouOghU_1L592pt_OSxn6aUSY5KNm1HOT6zbbQOA/edit#gid=1788780645"
                                    ),
                                ]),
                                lg=8, md=12, sm=12, className="mb-3"
                            ),
                            dbc.Col(
                                html.Button(
                                    [html.I(className="bi bi-arrow-clockwise me-2"), "Force Reload Data"],
                                    id="reload-data-button", n_clicks=0,
                                    className="btn-primary-new-theme w-100 mt-4"
                                ),
                                lg=4, md=12, sm=12, className="mb-3 d-flex align-items-end"
                            ),
                        ], className="g-3 justify-content-center"),
                        html.Div(id="reload-status-message", className="text-center mt-3 kpi-sub-value-new-theme-small")
                    ]),
                    className="filter-card-new-theme mb-5"
                ),
                width=12
            )
        )
    ],
    width=12,
    className="main-content-new-theme"
)

# --- Page Routing Callback ---
@app.callback(
    Output('page-content', 'children'),
    [Input('url', 'pathname')]
)
def display_page(pathname):
    if pathname == '/savings':
        return savings_monitor_layout
    elif pathname == '/analytics':
        return analytics_page_layout
    elif pathname == '/data-table':
        return data_table_layout
    elif pathname == '/investments':
        return investments_page_layout
    elif pathname == '/settings':
        return settings_page_layout
    else:
        return dashboard_page_layout

# --- Main Callback to Load Data on Page Load/Interval ---
@app.callback(
    Output('stored-icic-data', 'data'),
    Output('stored-canara-data', 'data'),
    Output('stored-investments-data', 'data'),
    Output('loading-error-message', 'data'),
    Input('interval-component', 'n_intervals'),
    Input('reload-data-button', 'n_clicks')
)
def fetch_data(n_intervals, n_clicks):
    if n_intervals is None and n_clicks is None:
        return no_update, no_update, no_update, no_update
    
    df_icic, df_canara, df_investments, error_message = load_data_from_google_sheets()
    
    icic_data = df_icic.to_dict('records') if not df_icic.empty else []
    canara_data = df_canara.to_dict('records') if not df_canara.empty else []
    investments_data = df_investments.to_dict('records') if not df_investments.empty else []
    
    return icic_data, canara_data, investments_data, error_message

# --- Callback to display data loading status ---
@app.callback(
    Output('data-load-status', 'children'),
    [Input('loading-error-message', 'data')]
)
def display_data_status(error_message):
    if error_message:
        return dbc.Alert(error_message, color="danger", dismissable=True, duration=5000, className="text-center w-100")
    else:
        return html.Div()

# --- Callback to reset filters ---
@app.callback(
    [Output("month-filter", "value"),
     Output("category-filter", "value"),
     Output("savings-month-filter", "value"),
     Output("savings-category-filter", "value"),
     Output("investments-month-filter", "value"),
     Output("investments-category-filter", "value"),
     Output("analytics-month-filter", "value"),
     Output("analytics-category-filter", "value")],
    [Input("reset-filters-button", "n_clicks"),
     Input("savings-reset-filters-button", "n_clicks"),
     Input("investments-reset-filters-button", "n_clicks")]
)
def reset_filters(n1, n2, n3):
    return None, None, None, None, None, None, None, None


# --- Callback for Dashboard page ---
@app.callback(
    Output("month-filter", "options"),
    Output("category-filter", "options"),
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
    Input("stored-icic-data", "data"),
    Input("month-filter", "value"),
    Input("category-filter", "value"),
)
def update_dashboard_page(icic_data, selected_months, selected_categories):
    if not icic_data:
        return (
            [],
            [],
            "₹0.00",
            "₹0.00",
            "N/A",
            "₹0.00",
            "N/A",
            "₹0.00",
            {},
            {},
            {},
            [],
        )

    df_icic = pd.DataFrame(icic_data)
    df_icic["Amount"] = pd.to_numeric(df_icic["Amount"], errors="coerce").fillna(0)

    # Filtering
    if selected_months:
        filtered_df = df_icic[df_icic["Month"].isin(selected_months)]
    else:
        filtered_df = df_icic.copy()
    if selected_categories:
        filtered_df = filtered_df[filtered_df["Category"].isin(selected_categories)]

    # Dynamic Dropdown Options
    month_options = sorted(list(df_icic["Month"].unique()))
    category_options = sorted(list(df_icic["Category"].unique()))

    # KPI Calculations
    total_expenses = filtered_df["Amount"].sum()
    monthly_expenses = filtered_df.groupby("Month")["Amount"].sum().reset_index()
    avg_monthly_kpi_value = monthly_expenses["Amount"].mean()
    highest_month = monthly_expenses.loc[monthly_expenses["Amount"].idxmax()] if not monthly_expenses.empty else {"Month": "N/A", "Amount": 0}
    lowest_month = monthly_expenses.loc[monthly_expenses["Amount"].idxmin()] if not monthly_expenses.empty else {"Month": "N/A", "Amount": 0}

    # Chart 1: Monthly Expenses Trend
    line_chart = px.line(
        monthly_expenses,
        x="Month",
        y="Amount",
        title=f"<span style='color:{CUSTOM_COLOR_PALETTE[0]}'>Monthly Expenses Trend</span>",
        markers=True,
        color_discrete_sequence=[CUSTOM_COLOR_PALETTE[0]],
        labels={"Amount": "Amount (₹)", "Month": "Month"},
        template="plotly_dark",
    )
    line_chart.update_layout(
        title_x=0.5,
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        font=dict(color=CUSTOM_COLOR_PALETTE[0]),
        yaxis_title="Amount (₹)",
        xaxis_title="Month",
    )

    # Chart 2: Top Expense Categories
    category_summary = filtered_df.groupby("Category")["Amount"].sum().sort_values(ascending=False).head(10).reset_index()
    pie_chart = px.pie(
        category_summary,
        names="Category",
        values="Amount",
        title=f"<span style='color:{CUSTOM_COLOR_PALETTE[1]}'>Top 10 Expense Categories</span>",
        color_discrete_sequence=CUSTOM_COLOR_PALETTE,
        template="plotly_dark",
    )
    pie_chart.update_layout(
        title_x=0.5,
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        font=dict(color=CUSTOM_COLOR_PALETTE[0]),
        legend_title="Categories",
    )
    pie_chart.update_traces(textposition='inside', textinfo='percent+label', marker=dict(line=dict(color='rgba(0,0,0,0)', width=1)))


    # Chart 3: Monthly Expenses by Category
    monthly_category_summary = filtered_df.groupby(["Month", "Category"])["Amount"].sum().reset_index()
    bar_chart = px.bar(
        monthly_category_summary,
        x="Month",
        y="Amount",
        color="Category",
        title=f"<span style='color:{CUSTOM_COLOR_PALETTE[2]}'>Monthly Expenses Breakdown by Category</span>",
        barmode="group",
        color_discrete_sequence=CUSTOM_COLOR_PALETTE,
        labels={"Amount": "Amount (₹)", "Month": "Month", "Category": "Category"},
        template="plotly_dark",
    )
    bar_chart.update_layout(
        title_x=0.5,
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        font=dict(color=CUSTOM_COLOR_PALETTE[0]),
        yaxis_title="Amount (₹)",
        xaxis_title="Month",
    )

    # Data Table
    table_data = filtered_df.to_dict('records')
    table_columns = [{"name": i, "id": i} for i in filtered_df.columns]

    return (
        month_options,
        category_options,
        f"₹{total_expenses:,.2f}",
        f"₹{avg_monthly_kpi_value:,.2f}",
        f"{highest_month['Month']}",
        f"₹{highest_month['Amount']:,.2f}",
        f"{lowest_month['Month']}",
        f"₹{lowest_month['Amount']:,.2f}",
        line_chart,
        pie_chart,
        bar_chart,
        table_data,
    )


# --- Callback for Savings Monitor Page ---
@app.callback(
    Output("savings-month-filter", "options"),
    Output("savings-category-filter", "options"),
    Output("total-savings-credit-kpi", "children"),
    Output("total-savings-debit-kpi", "children"),
    Output("net-savings-kpi", "children"),
    Output("savings-monthly-trend-chart", "figure"),
    Output("savings-category-bar-chart", "figure"),
    Output("savings-data-table", "data"),
    Input("stored-canara-data", "data"),
    Input("savings-month-filter", "value"),
    Input("savings-category-filter", "value"),
)
def update_savings_page(canara_data, selected_months, selected_categories):
    if not canara_data:
        return (
            [],
            [],
            "₹0.00",
            "₹0.00",
            "₹0.00",
            {},
            {},
            [],
        )

    df_canara = pd.DataFrame(canara_data)

    # Filtering
    if selected_months:
        filtered_df = df_canara[df_canara["Month"].isin(selected_months)]
    else:
        filtered_df = df_canara.copy()

    if selected_categories:
        filtered_df = filtered_df[filtered_df["Category"].isin(selected_categories)]

    # Dynamic Dropdown Options
    month_options = sorted(list(df_canara["Month"].unique()))
    category_options = sorted(list(df_canara["Category"].unique()))
    
    # KPI Calculations
    total_credits = filtered_df["Credit"].sum()
    total_debits = filtered_df["Debit"].sum()
    net_savings = total_credits - total_debits

    # Chart 1: Savings Monthly Trend
    monthly_savings = filtered_df.groupby("Month").agg(
        Total_Credit=("Credit", "sum"),
        Total_Debit=("Debit", "sum")
    ).reset_index()
    monthly_savings["Net_Savings"] = monthly_savings["Total_Credit"] - monthly_savings["Total_Debit"]

    trend_chart = go.Figure()
    trend_chart.add_trace(go.Scatter(
        x=monthly_savings["Month"],
        y=monthly_savings["Total_Credit"],
        mode='lines+markers',
        name='Total Credit',
        line=dict(color=CUSTOM_COLOR_PALETTE[0])
    ))
    trend_chart.add_trace(go.Scatter(
        x=monthly_savings["Month"],
        y=monthly_savings["Total_Debit"],
        mode='lines+markers',
        name='Total Debit',
        line=dict(color=CUSTOM_COLOR_PALETTE[1])
    ))
    trend_chart.add_trace(go.Bar(
        x=monthly_savings["Month"],
        y=monthly_savings["Net_Savings"],
        name='Net Savings',
        marker_color=CUSTOM_COLOR_PALETTE[2]
    ))
    trend_chart.update_layout(
        title=f"<span style='color:{CUSTOM_COLOR_PALETTE[0]}'>Monthly Savings Trend</span>",
        title_x=0.5,
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        font=dict(color=CUSTOM_COLOR_PALETTE[0]),
        legend_title="Metric",
        yaxis_title="Amount (₹)",
        xaxis_title="Month",
        template="plotly_dark",
    )

    # Chart 2: Savings by Category (Bar Chart)
    category_summary = filtered_df.groupby("Category").agg(
        Total_Credit=("Credit", "sum"),
        Total_Debit=("Debit", "sum")
    ).reset_index()

    bar_chart = px.bar(
        category_summary,
        x="Category",
        y=["Total_Credit", "Total_Debit"],
        title=f"<span style='color:{CUSTOM_COLOR_PALETTE[1]}'>Credits vs Debits by Category</span>",
        barmode="group",
        color_discrete_sequence=[CUSTOM_COLOR_PALETTE[0], CUSTOM_COLOR_PALETTE[1]],
        labels={"value": "Amount (₹)", "variable": "Transaction Type", "Category": "Category"},
        template="plotly_dark",
    )
    bar_chart.update_layout(
        title_x=0.5,
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        font=dict(color=CUSTOM_COLOR_PALETTE[0]),
        yaxis_title="Amount (₹)",
        xaxis_title="Category",
    )
    
    # Data Table
    table_data = filtered_df.to_dict('records')
    table_columns = [{"name": i, "id": i} for i in filtered_df.columns]

    return (
        month_options,
        category_options,
        f"₹{total_credits:,.2f}",
        f"₹{total_debits:,.2f}",
        f"₹{net_savings:,.2f}",
        trend_chart,
        bar_chart,
        table_data,
    )

# --- Callback for Investments Page ---
@app.callback(
    Output("investments-month-filter", "options"),
    Output("investments-category-filter", "options"),
    Output("total-investments-kpi", "children"),
    Output("avg-monthly-investment-kpi", "children"),
    Output("highest-investments-kpi-name", "children"),
    Output("highest-investments-kpi-value", "children"),
    Output("investments-pie-chart", "figure"),
    Output("investments-bar-chart", "figure"),
    Output("investments-data-table", "data"),
    Input("stored-investments-data", "data"),
    Input("investments-month-filter", "value"),
    Input("investments-category-filter", "value")
)
def update_investments_page(investments_data, selected_months, selected_categories):
    if not investments_data:
        return (
            [],
            [],
            "₹0.00",
            "₹0.00",
            "N/A",
            "₹0.00",
            {},
            {},
            [],
        )

    df_investments = pd.DataFrame(investments_data)
    df_investments["Amount"] = pd.to_numeric(df_investments["Amount"], errors="coerce").fillna(0)

    # Filtering
    filtered_df = df_investments.copy()
    if selected_months:
        filtered_df = filtered_df[filtered_df["Month"].isin(selected_months)]
    if selected_categories:
        filtered_df = filtered_df[filtered_df["Category"].isin(selected_categories)]

    # Dynamic Dropdown Options
    month_options = sorted(list(df_investments["Month"].unique()))
    category_options = sorted(list(df_investments["Category"].unique()))

    # KPI Calculations
    total_investments = filtered_df["Amount"].sum()
    monthly_summary = filtered_df.groupby("Month")["Amount"].sum()
    avg_monthly_investment = monthly_summary.mean() if not monthly_summary.empty else 0
    category_summary = filtered_df.groupby("Category")["Amount"].sum()
    highest_category = category_summary.idxmax() if not category_summary.empty else "N/A"
    highest_category_value = category_summary.max() if not category_summary.empty else 0

    # Chart 1: Investment Category Pie Chart
    pie_chart = px.pie(
        filtered_df,
        names="Category",
        values="Amount",
        title=f"<span style='color:{CUSTOM_COLOR_PALETTE[0]}'>Investment Breakdown by Category</span>",
        color_discrete_sequence=CUSTOM_COLOR_PALETTE,
        template="plotly_dark",
    )
    pie_chart.update_layout(
        title_x=0.5,
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        font=dict(color=CUSTOM_COLOR_PALETTE[0]),
    )
    pie_chart.update_traces(textposition='inside', textinfo='percent+label', marker=dict(line=dict(color='rgba(0,0,0,0)', width=1)))

    # Chart 2: Monthly Investment Bar Chart
    monthly_category_summary = filtered_df.groupby(["Month", "Category"])["Amount"].sum().reset_index()
    bar_chart = px.bar(
        monthly_category_summary,
        x="Month",
        y="Amount",
        color="Category",
        title=f"<span style='color:{CUSTOM_COLOR_PALETTE[1]}'>Monthly Investments Breakdown by Category</span>",
        barmode="group",
        color_discrete_sequence=CUSTOM_COLOR_PALETTE,
        labels={"Amount": "Amount (₹)", "Month": "Month", "Category": "Category"},
        template="plotly_dark",
    )
    bar_chart.update_layout(
        title_x=0.5,
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        font=dict(color=CUSTOM_COLOR_PALETTE[0]),
        yaxis_title="Amount (₹)",
        xaxis_title="Month",
    )

    # Data Table
    table_data = filtered_df.to_dict('records')
    table_columns = [{"name": i, "id": i} for i in filtered_df.columns]

    return (
        month_options,
        category_options,
        f"₹{total_investments:,.2f}",
        f"₹{avg_monthly_investment:,.2f}",
        f"{highest_category}",
        f"₹{highest_category_value:,.2f}",
        pie_chart,
        bar_chart,
        table_data,
    )


# --- Callback for Analytics & Trends Page ---
@app.callback(
    Output("analytics-month-filter", "options"),
    Output("analytics-category-filter", "options"),
    Output("analytics-chart", "figure"),
    Input("stored-icic-data", "data"),
    Input("chart-type-dropdown", "value"),
    Input("analytics-month-filter", "value"),
    Input("analytics-category-filter", "value"),
)
def update_analytics_page(icic_data, chart_type, selected_months, selected_categories):
    if not icic_data:
        return (
            [],
            [],
            {},
        )

    df_icic = pd.DataFrame(icic_data)
    df_icic["Amount"] = pd.to_numeric(df_icic["Amount"], errors="coerce").fillna(0)
    
    # Dynamic Dropdown Options
    month_options = sorted(list(df_icic["Month"].unique()))
    category_options = sorted(list(df_icic["Category"].unique()))

    # Filtering
    if selected_months:
        filtered_df = df_icic[df_icic["Month"].isin(selected_months)]
    else:
        filtered_df = df_icic.copy()
    if selected_categories:
        filtered_df = filtered_df[filtered_df["Category"].isin(selected_categories)]

    # Generate Chart
    monthly_category_summary = filtered_df.groupby(["Month", "Category"])["Amount"].sum().reset_index()

    if chart_type == 'line':
        fig = px.line(
            monthly_category_summary,
            x="Month",
            y="Amount",
            color="Category",
            title=f"<span style='color:{CUSTOM_COLOR_PALETTE[0]}'>Monthly Expenses Trend by Category</span>",
            markers=True,
            color_discrete_sequence=CUSTOM_COLOR_PALETTE,
            labels={"Amount": "Amount (₹)", "Month": "Month", "Category": "Category"},
            template="plotly_dark",
        )
    elif chart_type == 'area':
        fig = px.area(
            monthly_category_summary,
            x="Month",
            y="Amount",
            color="Category",
            title=f"<span style='color:{CUSTOM_COLOR_PALETTE[0]}'>Monthly Expenses Area Chart by Category</span>",
            color_discrete_sequence=CUSTOM_COLOR_PALETTE,
            labels={"Amount": "Amount (₹)", "Month": "Month", "Category": "Category"},
            template="plotly_dark",
        )
    elif chart_type == 'bar':
        fig = px.bar(
            monthly_category_summary,
            x="Month",
            y="Amount",
            color="Category",
            title=f"<span style='color:{CUSTOM_COLOR_PALETTE[0]}'>Monthly Expenses Breakdown by Category</span>",
            barmode="group",
            color_discrete_sequence=CUSTOM_COLOR_PALETTE,
            labels={"Amount": "Amount (₹)", "Month": "Month", "Category": "Category"},
            template="plotly_dark",
        )
    else:
        fig = {}

    fig.update_layout(
        title_x=0.5,
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        font=dict(color=CUSTOM_COLOR_PALETTE[0]),
        yaxis_title="Amount (₹)",
        xaxis_title="Month",
    )

    return (
        month_options,
        category_options,
        fig,
    )


# --- Callback for Raw Data Tables Page ---
@app.callback(
    Output("raw-icic-table", "data"),
    Output("raw-icic-table", "columns"),
    Output("raw-canara-table", "data"),
    Output("raw-canara-table", "columns"),
    Output("raw-investments-table", "data"),
    Output("raw-investments-table", "columns"),
    Input("stored-icic-data", "data"),
    Input("stored-canara-data", "data"),
    Input("stored-investments-data", "data"),
)
def update_raw_tables(icic_data, canara_data, investments_data):
    icic_df = pd.DataFrame(icic_data) if icic_data else pd.DataFrame()
    canara_df = pd.DataFrame(canara_data) if canara_data else pd.DataFrame()
    investments_df = pd.DataFrame(investments_data) if investments_data else pd.DataFrame()

    icic_cols = [{"name": i, "id": i} for i in icic_df.columns]
    canara_cols = [{"name": i, "id": i} for i in canara_df.columns]
    investments_cols = [{"name": i, "id": i} for i in investments_df.columns]

    return (
        icic_df.to_dict('records'),
        icic_cols,
        canara_df.to_dict('records'),
        canara_cols,
        investments_df.to_dict('records'),
        investments_cols,
    )


# --- Callback for Savings Goal Calculator ---
@app.callback(
    Output("savings-goal-output", "children"),
    Input("calculate-goal-button", "n_clicks"),
    State("stored-canara-data", "data"),
    State("target-amount-input", "value"),
    State("duration-input", "value")
)
def calculate_savings_goal(n_clicks, canara_data, target_amount, duration):
    if n_clicks is None or not canara_data:
        return no_update

    df_canara = pd.DataFrame(canara_data)
    df_canara["Credit"] = pd.to_numeric(df_canara["Credit"], errors="coerce").fillna(0)
    df_canara["Debit"] = pd.to_numeric(df_canara["Debit"], errors="coerce").fillna(0)
    df_canara["Month"] = df_canara["Month"].astype(str).str.strip()

    monthly_summary = df_canara.groupby("Month").agg(
        Total_Credit=("Credit", "sum"),
        Total_Debit=("Debit", "sum")
    ).reset_index()
    monthly_summary["Net_Savings"] = monthly_summary["Total_Credit"] - monthly_summary["Total_Debit"]
    
    historical_avg_monthly_net_savings = monthly_summary["Net_Savings"].mean()

    if target_amount is not None and duration is None:
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
    from waitress import serve
    print("Starting the Dashboard ... Loading data from Google Sheets. This may take a moment.")
    serve(app.server, host="0.0.0.0", port=8050)