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
import io

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
        dcc.Store(id='stored-investments-data'),  # New store for investments data
        dcc.Store(id='loading-error-message'),
        dcc.Interval(
            id='interval-component',
            interval=60*1000,
            n_intervals=0
        ),
        

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
        html.Div(id="data-load-status", className="data-load-alert"),
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
        html.Div(id="savings-load-status", className="data-load-alert"),
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
        html.Div(id="investments-load-status", className="data-load-alert"),
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
        dbc.Row([
            dbc.Col(dcc.Loading(id="loading-investments-trend", type="circle", color=CUSTOM_COLOR_PALETTE[0], children=dcc.Graph(id="investments-monthly-trend-chart")), width=12, className="mb-4 chart-panel-new-theme"),
        ], className="g-4"),
        dbc.Row([
            dbc.Col(dcc.Loading(id="loading-investments-category", type="circle", color=CUSTOM_COLOR_PALETTE[1], children=dcc.Graph(id="investments-category-bar-chart")), width=12, className="mb-4 chart-panel-new-theme"),
        ], className="g-4"),
        dbc.Row([
            dbc.Col(
                html.Div([
                    html.H4("📊 Detailed Investments Data", className="section-title-new-theme text-center mb-4", style={'color': 'var(--accent-gold)', 'textShadow': 'var(--glow-gold)'}),
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

# --- Layout for the Analytics Page ---
analytics_page_layout = dbc.Col(
    [
        dbc.Row(
            dbc.Col(
                html.H2("📈 Analytics & Trends", className="section-title-new-theme text-center mb-4", style={'color': 'var(--accent-cyan)', 'textShadow': 'var(--glow-cyan)'}),
                width=12
            )
        ),
        dbc.Row([
            dbc.Col(dcc.Loading(id="loading-analytics-1", type="circle", color=CUSTOM_COLOR_PALETTE[0], children=dcc.Graph(id="analytics-chart-1")), lg=6, md=12, className="mb-4 chart-panel-new-theme"),
            dbc.Col(dcc.Loading(id="loading-analytics-2", type="circle", color=CUSTOM_COLOR_PALETTE[1], children=dcc.Graph(id="analytics-chart-2")), lg=6, md=12, className="mb-4 chart-panel-new-theme"),
        ], className="g-4"),
        dbc.Row([
            dbc.Col(dcc.Loading(id="loading-analytics-3", type="circle", color=CUSTOM_COLOR_PALETTE[2], children=dcc.Graph(id="analytics-chart-3")), width=12, className="mb-4 chart-panel-new-theme"),
        ], className="g-4"),
    ],
    width=12,
    className="main-content-new-theme"
)

# --- Layout for the Raw Data Table Page ---
data_table_layout = dbc.Col(
    [
        dbc.Row(
            dbc.Col(
                html.H2("📋 Raw Data Table", className="section-title-new-theme text-center mb-4", style={'color': 'var(--accent-magenta)', 'textShadow': 'var(--glow-magenta)'}),
                width=12
            )
        ),
        dbc.Row([
            dbc.Col(
                html.Div([
                    dcc.Dropdown(
                        id="raw-data-source-dropdown",
                        options=[
                            {'label': 'ICIC Salary Data', 'value': 'icic'},
                            {'label': 'CANARA Data', 'value': 'canara'},
                            {'label': 'Investments Data', 'value': 'investments'}
                        ],
                        value='icic',
                        clearable=False,
                        className="dropdown-new-theme mb-3"
                    ),
                    dcc.Loading(
                        id="loading-raw-table", type="circle", color=CUSTOM_COLOR_PALETTE[3],
                        children=dash_table.DataTable(
                            id="raw-data-table-display",
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
                            page_size=20,
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
                html.H2("⚙️ Configuration", className="section-title-new-theme text-center mb-4", style={'color': 'var(--accent-gold)', 'textShadow': 'var(--glow-gold)'}),
                width=12
            )
        ),
        dbc.Row(
            dbc.Col(
                dbc.Card(
                    dbc.CardBody([
                        html.H5("Update Google Sheet URL", className="card-title-new-theme text-center mb-3"),
                        dcc.Input(
                            id="google-sheet-url-input",
                            type="text",
                            placeholder="Enter new Google Sheet URL",
                            value="https://docs.google.com/spreadsheets/d/1o1e8ouOghU_1L592pt_OSxn6aUSY5KNm1HOT6zbbQOA/edit?gid=1788780645#gid=1788780645",
                            className="form-control-new-theme mb-3"
                        ),
                        dbc.Button("Save URL", id="save-url-button", n_clicks=0, className="btn-primary-new-theme w-100"),
                        html.Div(id="url-save-status", className="mt-3 text-center")
                    ]),
                    className="filter-card-new-theme"
                ),
                width=12, lg=6, className="mx-auto"
            )
        )
    ],
    width=12,
    className="main-content-new-theme"
)

# --- Callbacks ---

# Callback to update page content based on URL
@app.callback(Output('page-content', 'children'),
              Input('url', 'pathname'))
def display_page(pathname):
    if pathname == '/savings':
        return savings_monitor_layout
    elif pathname == '/analytics':
        return analytics_page_layout
    elif pathname == '/data-table':
        return data_table_layout
    elif pathname == '/investments':
        return investments_layout
    elif pathname == '/settings':
        return settings_page_layout
    else:
        return dashboard_page_layout

# Callback to load and store data from Google Sheets at intervals
@app.callback(
    [Output('stored-icic-data', 'data'),
     Output('stored-canara-data', 'data'),
     Output('stored-investments-data', 'data'),
     Output('loading-error-message', 'data')],
    [Input('interval-component', 'n_intervals'),
     Input('url-save-status', 'children')]
)
def fetch_and_store_data(n_intervals, url_save_status):
    print(f"Attempting to load data... Interval count: {n_intervals}")
    df_icic, df_canara, df_investments, error = load_data_from_google_sheets()
    
    # Check for empty DataFrames and set a user-friendly error message
    if df_icic.empty and df_canara.empty and df_investments.empty and not error:
        error = "❌ Failed to load data from all sheets. Please check the Google Sheet URL and permissions."
    
    # Use io.StringIO to resolve FutureWarning with pd.read_json
    icic_data_json = df_icic.to_json(orient='split', date_format='iso')
    canara_data_json = df_canara.to_json(orient='split', date_format='iso')
    investments_data_json = df_investments.to_json(orient='split', date_format='iso')
    
    return icic_data_json, canara_data_json, investments_data_json, error

# Callback for data-load-status and filters for the main dashboard
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

    status_message = html.Div([html.I(className="bi bi-check-circle me-2"), "Data loaded successfully!"], className="data-load-success")
    month_options = []
    category_options = []
    
    if error_message:
        status_message = html.Div([html.I(className="bi bi-x-circle me-2"), error_message], className="data-load-error")
        return status_message, no_update, no_update

    # Use io.StringIO to read JSON string
    try:
        if stored_icic_data_json:
            df_icic = pd.read_json(io.StringIO(stored_icic_data_json), orient='split')
            
            # Update month and category filters
            months = sorted(df_icic['Month'].unique().tolist())
            categories = sorted(df_icic['Category'].unique().tolist())
            month_options = [{'label': m, 'value': m} for m in months]
            category_options = [{'label': c, 'value': c} for c in categories]
            
    except Exception as e:
        status_message = html.Div([html.I(className="bi bi-exclamation-triangle me-2"), f"Error parsing data: {e}"], className="data-load-error")
    
    return status_message, month_options, category_options
    
# Callback for main dashboard KPIs and Charts
@app.callback(
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
    Input('stored-icic-data', 'data'),
    Input('reset-filters-button', 'n_clicks'),
    State('url', 'pathname')
)
def update_dashboard_content(selected_months, selected_categories, stored_icic_data_json, reset_clicks, pathname):
    if pathname != '/':
        return no_update, no_update, no_update, no_update, no_update, no_update, no_update, no_update, no_update, no_update, no_update

    ctx = dash.callback_context
    if not ctx.triggered:
        # Initial load or no interaction
        df_icic = pd.read_json(io.StringIO(stored_icic_data_json), orient='split') if stored_icic_data_json else pd.DataFrame()
        
    else:
        trigger_id = ctx.triggered[0]['prop_id'].split('.')[0]
        if trigger_id == 'reset-filters-button':
            selected_months = []
            selected_categories = []
        
        df_icic = pd.read_json(io.StringIO(stored_icic_data_json), orient='split') if stored_icic_data_json else pd.DataFrame()
    
    if df_icic.empty:
        # Return default values for empty data
        default_figure = go.Figure()
        default_figure.update_layout(template="plotly_dark", plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)", font=dict(color="#E0E0E0"), title="No data to display")
        
        return (
            "₹0.00", "₹0.00", "N/A", "₹0.00", "N/A", "₹0.00",
            default_figure, default_figure, default_figure,
            [], []
        )

    filtered_df = df_icic.copy()
    if selected_months:
        filtered_df = filtered_df[filtered_df['Month'].isin(selected_months)]
    if selected_categories:
        filtered_df = filtered_df[filtered_df['Category'].isin(selected_categories)]

    # 1. KPIs
    total_expenses = filtered_df['Amount'].sum()
    monthly_summary = filtered_df.groupby('Month')['Amount'].sum().reset_index()
    avg_monthly_expense = monthly_summary['Amount'].mean() if not monthly_summary.empty else 0
    highest_month = monthly_summary.loc[monthly_summary['Amount'].idxmax()] if not monthly_summary.empty else {'Month': 'N/A', 'Amount': 0}
    lowest_month = monthly_summary.loc[monthly_summary['Amount'].idxmin()] if not monthly_summary.empty else {'Month': 'N/A', 'Amount': 0}

    # 2. Charts
    # Monthly trend
    trend_chart = px.line(
        monthly_summary,
        x='Month',
        y='Amount',
        title=f"<span style='color:{CUSTOM_COLOR_PALETTE[0]}'>Monthly Expense Trend</span>",
        markers=True,
        color_discrete_sequence=[CUSTOM_COLOR_PALETTE[0]],
        labels={'Amount': 'Amount (₹)', 'Month': 'Month'},
        template="plotly_dark"
    )
    trend_chart.update_layout(
        title_x=0.5,
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        font=dict(color=CUSTOM_COLOR_PALETTE[0]),
        yaxis_title="Amount (₹)",
        xaxis_title="Month",
    )
    
    # Top categories pie chart
    category_summary = filtered_df.groupby('Category')['Amount'].sum().sort_values(ascending=False).reset_index()
    pie_chart = px.pie(
        category_summary,
        values='Amount',
        names='Category',
        title=f"<span style='color:{CUSTOM_COLOR_PALETTE[1]}'>Expense Distribution by Category</span>",
        hole=0.4,
        color_discrete_sequence=CUSTOM_COLOR_PALETTE,
        template="plotly_dark"
    )
    pie_chart.update_traces(textposition='inside', textinfo='percent+label', marker=dict(line=dict(color='white', width=1)))
    pie_chart.update_layout(
        title_x=0.5,
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        font=dict(color="#E0E0E0")
    )
    
    # Monthly expenses by category bar chart
    monthly_category_summary = filtered_df.groupby(['Month', 'Category'])['Amount'].sum().reset_index()
    bar_chart = px.bar(
        monthly_category_summary,
        x='Month',
        y='Amount',
        color='Category',
        title=f"<span style='color:{CUSTOM_COLOR_PALETTE[2]}'>Monthly Expenses Breakdown by Category</span>",
        barmode='group',
        color_discrete_sequence=CUSTOM_COLOR_PALETTE,
        labels={'Amount': 'Amount (₹)', 'Month': 'Month', 'Category': 'Category'},
        template="plotly_dark"
    )
    bar_chart.update_layout(
        title_x=0.5,
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        font=dict(color=CUSTOM_COLOR_PALETTE[0]),
        yaxis_title="Amount (₹)",
        xaxis_title="Month",
    )
    
    # 3. Data Table
    table_data = filtered_df.to_dict('records')
    table_columns = [{"name": i, "id": i} for i in filtered_df.columns]
    
    return (
        f"₹{total_expenses:,.2f}",
        f"₹{avg_monthly_expense:,.2f}",
        f"{highest_month['Month']}",
        f"₹{highest_month['Amount']:,.2f}",
        f"{lowest_month['Month']}",
        f"₹{lowest_month['Amount']:,.2f}",
        trend_chart,
        pie_chart,
        bar_chart,
        table_data,
        table_columns
    )

# Callback for Savings Monitor
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
    Input('stored-canara-data', 'data'),
    Input('savings-month-filter', 'value'),
    Input('savings-category-filter', 'value'),
    Input('savings-reset-filters-button', 'n_clicks'),
    State('url', 'pathname')
)
def update_savings_monitor(stored_canara_data_json, selected_months, selected_categories, reset_clicks, pathname):
    if pathname != '/savings':
        return no_update, no_update, no_update, no_update, no_update, no_update, no_update, no_update, no_update

    ctx = dash.callback_context
    if ctx.triggered and ctx.triggered[0]['prop_id'].split('.')[0] == 'savings-reset-filters-button':
        selected_months = []
        selected_categories = []

    # Use io.StringIO to read JSON string
    df_canara = pd.read_json(io.StringIO(stored_canara_data_json), orient='split') if stored_canara_data_json else pd.DataFrame()
    
    if df_canara.empty:
        default_figure = go.Figure()
        default_figure.update_layout(template="plotly_dark", plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)", font=dict(color="#E0E0E0"), title="No data to display")
        return [], [], "₹0.00", "₹0.00", "₹0.00", default_figure, default_figure, [], []

    df_canara['Month'] = pd.to_datetime(df_canara['Month'], format='%B %Y', errors='coerce').dt.strftime('%B %Y')
    
    months = sorted(df_canara['Month'].dropna().unique().tolist())
    categories = sorted(df_canara['Category'].dropna().unique().tolist())
    
    month_options = [{'label': m, 'value': m} for m in months]
    category_options = [{'label': c, 'value': c} for c in categories]
    
    filtered_df = df_canara.copy()
    if selected_months:
        filtered_df = filtered_df[filtered_df['Month'].isin(selected_months)]
    if selected_categories:
        filtered_df = filtered_df[filtered_df['Category'].isin(selected_categories)]
        
    # KPIs
    total_credits = filtered_df['Credit'].sum()
    total_debits = filtered_df['Debit'].sum()
    net_savings = total_credits - total_debits
    
    # Monthly trend chart
    monthly_trend = filtered_df.groupby('Month')[['Credit', 'Debit']].sum().reset_index()
    monthly_trend = monthly_trend.set_index('Month').reindex(months).reset_index()
    
    trend_chart = go.Figure()
    trend_chart.add_trace(go.Bar(x=monthly_trend['Month'], y=monthly_trend['Credit'], name='Credits', marker_color=CUSTOM_COLOR_PALETTE[6]))
    trend_chart.add_trace(go.Bar(x=monthly_trend['Month'], y=monthly_trend['Debit'], name='Debits', marker_color=CUSTOM_COLOR_PALETTE[8]))
    
    trend_chart.update_layout(
        title=f"<span style='color:{CUSTOM_COLOR_PALETTE[0]}'>Monthly Savings Trend (Credit vs Debit)</span>",
        barmode='group',
        template="plotly_dark",
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        font=dict(color="#E0E0E0"),
        xaxis_title="Month",
        yaxis_title="Amount (₹)",
        title_x=0.5
    )
    
    # Category bar chart
    category_summary = filtered_df.groupby('Category')[['Credit', 'Debit']].sum().reset_index()
    category_bar_chart = go.Figure()
    category_bar_chart.add_trace(go.Bar(x=category_summary['Category'], y=category_summary['Credit'], name='Credits', marker_color=CUSTOM_COLOR_PALETTE[6]))
    category_bar_chart.add_trace(go.Bar(x=category_summary['Category'], y=category_summary['Debit'], name='Debits', marker_color=CUSTOM_COLOR_PALETTE[8]))
    
    category_bar_chart.update_layout(
        title=f"<span style='color:{CUSTOM_COLOR_PALETTE[1]}'>Savings by Category (Credit vs Debit)</span>",
        barmode='group',
        template="plotly_dark",
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        font=dict(color="#E0E0E0"),
        xaxis_title="Category",
        yaxis_title="Amount (₹)",
        title_x=0.5
    )
    
    # Data table
    table_data = filtered_df.to_dict('records')
    table_columns = [{"name": i, "id": i} for i in filtered_df.columns]
    
    return (
        month_options,
        category_options,
        f"₹{total_credits:,.2f}",
        f"₹{total_debits:,.2f}",
        f"₹{net_savings:,.2f}",
        trend_chart,
        category_bar_chart,
        table_data,
        table_columns
    )

# Callback to calculate savings goal
@app.callback(
    Output('savings-goal-output', 'children'),
    Input('calculate-goal-button', 'n_clicks'),
    State('target-amount-input', 'value'),
    State('duration-input', 'value')
)
def calculate_savings_goal(n_clicks, target_amount, duration):
    if n_clicks > 0 and target_amount and duration:
        try:
            target_amount = float(target_amount)
            duration = int(duration)
            if target_amount <= 0 or duration <= 0:
                return "Please enter positive values."
            
            monthly_saving = target_amount / duration
            return f"You need to save ₹{monthly_saving:,.2f} per month to reach your goal."
        except (ValueError, TypeError):
            return "Please enter valid numbers."
    return ""

# Callback for Investments Page
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
    Output('investments-category-bar-chart', 'figure'),
    Output('investments-data-table', 'data'),
    Output('investments-data-table', 'columns'),
    Input('stored-investments-data', 'data'),
    Input('investments-month-filter', 'value'),
    Input('investments-category-filter', 'value'),
    Input('investments-reset-filters-button', 'n_clicks'),
    State('url', 'pathname')
)
def update_investments_page(stored_investments_data_json, selected_months, selected_categories, reset_clicks, pathname):
    if pathname != '/investments':
        return no_update, no_update, no_update, no_update, no_update, no_update, no_update, no_update, no_update, no_update, no_update

    ctx = dash.callback_context
    if ctx.triggered and ctx.triggered[0]['prop_id'].split('.')[0] == 'investments-reset-filters-button':
        selected_months = []
        selected_categories = []

    # Use io.StringIO to read JSON string
    df_investments = pd.read_json(io.StringIO(stored_investments_data_json), orient='split') if stored_investments_data_json else pd.DataFrame()

    if df_investments.empty:
        default_figure = go.Figure()
        default_figure.update_layout(template="plotly_dark", plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)", font=dict(color="#E0E0E0"), title="No data to display")
        return [], [], "₹0.00", "₹0.00", "N/A", "₹0.00", "N/A", "₹0.00", default_figure, default_figure, [], []
    
    months = sorted(df_investments['Month'].dropna().unique().tolist())
    categories = sorted(df_investments['Category'].dropna().unique().tolist())
    
    month_options = [{'label': m, 'value': m} for m in months]
    category_options = [{'label': c, 'value': c} for c in categories]

    filtered_df = df_investments.copy()
    if selected_months:
        filtered_df = filtered_df[filtered_df['Month'].isin(selected_months)]
    if selected_categories:
        filtered_df = filtered_df[filtered_df['Category'].isin(selected_categories)]
        
    # KPIs
    total_investments = filtered_df['Amount'].sum()
    monthly_summary = filtered_df.groupby('Month')['Amount'].sum().reset_index()
    avg_monthly_investment = monthly_summary['Amount'].mean() if not monthly_summary.empty else 0
    category_summary = filtered_df.groupby('Category')['Amount'].sum().reset_index()
    highest_category = category_summary.loc[category_summary['Amount'].idxmax()] if not category_summary.empty else {'Category': 'N/A', 'Amount': 0}
    lowest_category = category_summary.loc[category_summary['Amount'].idxmin()] if not category_summary.empty else {'Category': 'N/A', 'Amount': 0}
    
    # Charts
    # Monthly trend chart
    trend_chart = px.line(
        monthly_summary,
        x='Month',
        y='Amount',
        title=f"<span style='color:{CUSTOM_COLOR_PALETTE[0]}'>Monthly Investment Trend</span>",
        markers=True,
        color_discrete_sequence=[CUSTOM_COLOR_PALETTE[0]],
        labels={'Amount': 'Amount (₹)', 'Month': 'Month'},
        template="plotly_dark",
    )
    trend_chart.update_layout(
        title_x=0.5,
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        font=dict(color=CUSTOM_COLOR_PALETTE[0]),
        yaxis_title="Amount (₹)",
        xaxis_title="Month",
    )
    
    # Category bar chart
    monthly_category_summary = filtered_df.groupby(["Month", "Category"])["Amount"].sum().reset_index()
    bar_chart = px.bar(
        monthly_category_summary,
        x="Month",
        y="Amount",
        color="Category",
        title=f"<span style='color:{CUSTOM_COLOR_PALETTE[2]}'>Monthly Investments Breakdown by Category</span>",
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
        f"{highest_category['Category']}",
        f"₹{highest_category['Amount']:,.2f}",
        f"{lowest_category['Category']}",
        f"₹{lowest_category['Amount']:,.2f}",
        trend_chart,
        bar_chart,
        table_data,
        table_columns
    )

# Callback for Raw Data Table
@app.callback(
    Output('raw-data-table-display', 'data'),
    Output('raw-data-table-display', 'columns'),
    Input('raw-data-source-dropdown', 'value'),
    State('stored-icic-data', 'data'),
    State('stored-canara-data', 'data'),
    State('stored-investments-data', 'data'),
    State('url', 'pathname')
)
def update_raw_data_table(selected_source, icic_data_json, canara_data_json, investments_data_json, pathname):
    if pathname != '/data-table':
        return no_update, no_update
    
    df = pd.DataFrame()
    if selected_source == 'icic' and icic_data_json:
        df = pd.read_json(io.StringIO(icic_data_json), orient='split')
    elif selected_source == 'canara' and canara_data_json:
        df = pd.read_json(io.StringIO(canara_data_json), orient='split')
    elif selected_source == 'investments' and investments_data_json:
        df = pd.read_json(io.StringIO(investments_data_json), orient='split')
    
    if df.empty:
        return [], []
    
    table_data = df.to_dict('records')
    table_columns = [{"name": i, "id": i} for i in df.columns]
    
    return table_data, table_columns


if __name__ == '__main__':
    app.run_server(debug=True, host='0.0.0.0', port=os.environ.get("PORT", 8050))