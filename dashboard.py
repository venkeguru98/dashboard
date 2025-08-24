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
# for deployment on services like Render.
def load_data_from_google_sheets():
    df_icic = pd.DataFrame()
    df_canara = pd.DataFrame()
    df_investments = pd.DataFrame()
    error_message = None
    
    creds_info = None

    # Check for credentials in an environment variable for production
    if "GCP_SA_CREDENTIALS_BASE64" in os.environ:
        credentials_content_base64 = os.environ.get("GCP_SA_CREDENTIALS_BASE64")
        try:
            # Decode the Base64 string and load as JSON
            credentials_json = base64.b64decode(credentials_content_base64).decode('utf-8')
            creds_info = json.loads(credentials_json)
            print("Using credentials from environment variable.")
        except Exception as e:
            error_message = f"❌ Error decoding credentials from environment variable: {e}"
            print(error_message)
            return df_icic, df_canara, df_investments, error_message
    else:
        # Fallback to local file for local development
        local_service_account_file = "icic-salary-data-52568c61b6e3.json"
        if os.path.exists(local_service_account_file):
            print("Using local service account file. This is for local development only.")
            creds_info = local_service_account_file
        else:
            error_message = f"❌ Error: 'GCP_SA_CREDENTIALS_BASE64' environment variable not found and local file '{local_service_account_file}' is missing. Please set up your credentials."
            print(error_message)
            return df_icic, df_canara, df_investments, error_message

    try:
        scope = [
            "https://www.googleapis.com/auth/spreadsheets.readonly",
            "https://www.googleapis.com/auth/drive.readonly",
        ]
        
        if isinstance(creds_info, dict):
            # Authenticate using the dictionary (from environment variable)
            creds = Credentials.from_service_account_info(creds_info, scopes=scope)
        else:
            # Authenticate using the file path (from local development)
            creds = Credentials.from_service_account_file(creds_info, scopes=scope)

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
            dbc.Col(dcc.Loading(id="loading-investments-pie", type="circle", color=CUSTOM_COLOR_PALETTE[1], children=dcc.Graph(id="investments-category-pie-chart")), lg=6, md=12, className="mb-4 chart-panel-new-theme"),
        ], className="g-4"),
        dbc.Row([
            dbc.Col(dcc.Loading(id="loading-investments-bar", type="circle", color=CUSTOM_COLOR_PALETTE[2], children=dcc.Graph(id="investments-monthly-by-category-chart")), width=12, className="mb-4 chart-panel-new-theme"),
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

# --- Layout for the Analytics & Trends Page ---
analytics_trends_layout = dbc.Col(
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
                        html.H5("Advanced Analysis Filters", className="card-title-new-theme text-center mb-3"),
                        dbc.Row([
                            dbc.Col(
                                html.Div([
                                    html.Label("Compare Categories:", className="form-label-new-theme"),
                                    dcc.Dropdown(
                                        id="trend-category-filter",
                                        options=[],
                                        multi=True,
                                        placeholder="Select Categories",
                                        className="dropdown-new-theme"
                                    ),
                                ]),
                                lg=6, md=12, sm=12, className="mb-3"
                            ),
                            dbc.Col(
                                html.Div([
                                    html.Label("Select Month Range:", className="form-label-new-theme"),
                                    dcc.RangeSlider(
                                        id="month-range-slider",
                                        min=0,
                                        max=1,
                                        step=1,
                                        marks={0: 'Start', 1: 'End'},
                                        value=[0, 1],
                                        tooltip={"placement": "bottom", "always_visible": True},
                                        className="rangeslider-new-theme"
                                    ),
                                ]),
                                lg=6, md=12, sm=12, className="mb-3 d-flex align-items-end"
                            ),
                        ], className="g-3 justify-content-center")
                    ]),
                    className="filter-card-new-theme mb-5"
                ),
                width=12
            )
        ),
        dbc.Row([
            dbc.Col(dcc.Loading(id="loading-line-chart", type="circle", color=CUSTOM_COLOR_PALETTE[0], children=dcc.Graph(id="category-trends-chart")), width=12, className="mb-4 chart-panel-new-theme"),
        ], className="g-4"),
        dbc.Row([
            dbc.Col(dcc.Loading(id="loading-scatter-chart", type="circle", color=CUSTOM_COLOR_PALETTE[1], children=dcc.Graph(id="monthly-correlation-chart")), lg=6, md=12, className="mb-4 chart-panel-new-theme"),
            dbc.Col(dcc.Loading(id="loading-heatmap", type="circle", color=CUSTOM_COLOR_PALETTE[2], children=dcc.Graph(id="category-heatmap-chart")), lg=6, md=12, className="mb-4 chart-panel-new-theme"),
        ], className="g-4")
    ],
    width=12,
    className="main-content-new-theme"
)

# --- Layout for the Raw Data Table Page ---
raw_data_table_layout = dbc.Col(
    [
        dbc.Row(
            dbc.Col(
                html.H2("📖 Raw Data", className="section-title-new-theme text-center mb-4", style={'color': 'var(--accent-purple)', 'textShadow': 'var(--glow-purple)'}),
                width=12
            )
        ),
        dbc.Tabs(
            [
                dbc.Tab(
                    dcc.Loading(
                        id="loading-raw-icic", type="circle", color=CUSTOM_COLOR_PALETTE[3],
                        children=dash_table.DataTable(
                            id='icic-raw-data-table',
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
                    ),
                    label="ICIC Salary Data",
                    tab_style={"backgroundColor": "#121212", "borderColor": "#0A0A0A"},
                    label_style={"color": CUSTOM_COLOR_PALETTE[0]}
                ),
                dbc.Tab(
                    dcc.Loading(
                        id="loading-raw-canara", type="circle", color=CUSTOM_COLOR_PALETTE[3],
                        children=dash_table.DataTable(
                            id='canara-raw-data-table',
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
                    ),
                    label="CANARA Bank Data",
                    tab_style={"backgroundColor": "#121212", "borderColor": "#0A0A0A"},
                    label_style={"color": CUSTOM_COLOR_PALETTE[1]}
                ),
                dbc.Tab(
                    dcc.Loading(
                        id="loading-raw-investments", type="circle", color=CUSTOM_COLOR_PALETTE[3],
                        children=dash_table.DataTable(
                            id='investments-raw-data-table',
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
                    ),
                    label="Investments Data",
                    tab_style={"backgroundColor": "#121212", "borderColor": "#0A0A0A"},
                    label_style={"color": CUSTOM_COLOR_PALETTE[2]}
                ),
            ],
            id="raw-data-tabs",
            active_tab="tab-1",
            className="tabs-panel-new-theme"
        )
    ],
    width=12,
    className="main-content-new-theme"
)

# --- Layout for the Settings Page ---
settings_layout = dbc.Col(
    [
        dbc.Row(
            dbc.Col(
                html.H2("⚙️ Configuration & Settings", className="section-title-new-theme text-center mb-4", style={'color': 'var(--accent-gold)', 'textShadow': 'var(--glow-gold)'}),
                width=12
            )
        ),
        dbc.Row([
            dbc.Col(
                dbc.Card(
                    dbc.CardBody([
                        html.H5("Data Refresh Settings", className="card-title-new-theme text-center mb-3"),
                        html.P("Force a manual data refresh from Google Sheets.", className="card-text-new-theme text-center"),
                        dbc.Button(
                            [html.I(className="bi bi-arrow-repeat me-2"), "Refresh Data"],
                            id="refresh-button", n_clicks=0,
                            className="btn-primary-new-theme w-100"
                        ),
                        html.Div(id="refresh-status", className="text-center mt-3", style={"fontStyle": "italic", "color": "var(--accent-lime)"})
                    ]),
                    className="card-panel-new-theme"
                ),
                lg=6, md=12, className="mb-4"
            ),
            dbc.Col(
                dbc.Card(
                    dbc.CardBody([
                        html.H5("About This Dashboard", className="card-title-new-theme text-center mb-3"),
                        html.P("This dashboard is built with Dash and Python to visualize personal finance data from Google Sheets.", className="card-text-new-theme"),
                        html.P("Developed by Venke", className="card-text-new-theme text-muted"),
                    ]),
                    className="card-panel-new-theme"
                ),
                lg=6, md=12, className="mb-4"
            )
        ])
    ],
    width=12,
    className="main-content-new-theme"
)


# --- Callbacks ---

@app.callback(
    [Output('stored-icic-data', 'data'),
     Output('stored-canara-data', 'data'),
     Output('stored-investments-data', 'data'),
     Output('loading-error-message', 'data'),
     Output("data-load-status", "children")],
    [Input('interval-component', 'n_intervals'),
     Input('refresh-button', 'n_clicks')]
)
def fetch_and_store_data(n_intervals, n_clicks):
    if n_intervals == 0 and n_clicks == 0:
        # Initial load, don't show loading message immediately
        data_status = ""
    else:
        data_status = html.Div([
            dbc.Spinner(size="sm"),
            html.Span("  Loading new data...", className="ms-2")
        ], className="data-load-alert loading-message")

    df_icic, df_canara, df_investments, error_msg = load_data_from_google_sheets()

    if error_msg:
        # If there's an error, don't update data stores, just the error message
        return no_update, no_update, no_update, error_msg, html.Div(error_msg, className="data-load-alert error-message")
    
    # Store data as JSON strings
    icic_json = df_icic.to_json(date_format='iso', orient='split') if not df_icic.empty else None
    canara_json = df_canara.to_json(date_format='iso', orient='split') if not df_canara.empty else None
    investments_json = df_investments.to_json(date_format='iso', orient='split') if not df_investments.empty else None

    # Clear status message after successful load
    data_status = html.Div("Data loaded successfully! ✅", className="data-load-alert success-message")
    
    return icic_json, canara_json, investments_json, None, data_status


@app.callback(Output('page-content', 'children'),
              Input('url', 'pathname'))
def display_page(pathname):
    if pathname == '/savings':
        return savings_monitor_layout
    elif pathname == '/analytics':
        return analytics_trends_layout
    elif pathname == '/data-table':
        return raw_data_table_layout
    elif pathname == '/investments':
        return investments_layout
    elif pathname == '/settings':
        return settings_layout
    else:
        return dashboard_page_layout

# --- Main Dashboard Page Callbacks ---

@app.callback(
    [Output("month-filter", "options"),
     Output("category-filter", "options")],
    Input("stored-icic-data", "data")
)
def populate_main_filters(icic_json):
    if icic_json:
        df_icic = pd.read_json(icic_json, orient='split')
        months = sorted(df_icic["Month"].unique())
        categories = sorted(df_icic["Category"].unique())
        month_options = [{"label": m, "value": m} for m in months]
        category_options = [{"label": c, "value": c} for c in categories]
        return month_options, category_options
    return [], []

@app.callback(
    [Output("month-filter", "value"),
     Output("category-filter", "value")],
    Input("reset-filters-button", "n_clicks")
)
def reset_main_filters(n_clicks):
    if n_clicks > 0:
        return None, None
    return no_update, no_update

@app.callback(
    [Output("total-expenses-kpi", "children"),
     Output("avg-monthly-kpi", "children"),
     Output("highest-month-kpi-name", "children"),
     Output("highest-month-kpi-value", "children"),
     Output("lowest-month-kpi-name", "children"),
     Output("lowest-month-kpi-value", "children"),
     Output("monthly-expenses-trend-chart", "figure"),
     Output("top-expense-categories-chart", "figure"),
     Output("monthly-expenses-by-category-chart", "figure"),
     Output("overview-data-table", "data"),
     Output("overview-data-table", "columns")],
    [Input("stored-icic-data", "data"),
     Input("month-filter", "value"),
     Input("category-filter", "value")]
)
def update_main_dashboard(icic_json, selected_months, selected_categories):
    if icic_json:
        df_icic = pd.read_json(icic_json, orient='split')
        
        # Filtering logic
        filtered_df = df_icic.copy()
        if selected_months:
            filtered_df = filtered_df[filtered_df['Month'].isin(selected_months)]
        if selected_categories:
            filtered_df = filtered_df[filtered_df['Category'].isin(selected_categories)]
        
        # KPI calculations
        total_expenses = filtered_df["Amount"].sum()
        
        monthly_summary = filtered_df.groupby("Month")["Amount"].sum().reset_index()
        avg_monthly_expense = monthly_summary["Amount"].mean() if not monthly_summary.empty else 0
        
        if not monthly_summary.empty:
            highest_month = monthly_summary.loc[monthly_summary["Amount"].idxmax()]
            lowest_month = monthly_summary.loc[monthly_summary["Amount"].idxmin()]
            highest_month_name = highest_month["Month"]
            highest_month_value = highest_month["Amount"]
            lowest_month_name = lowest_month["Month"]
            lowest_month_value = lowest_month["Amount"]
        else:
            highest_month_name, highest_month_value, lowest_month_name, lowest_month_value = "N/A", 0, "N/A", 0
            
        # Charts
        # Trend Chart
        monthly_trend = filtered_df.groupby("Month")["Amount"].sum().reset_index()
        line_chart = px.line(
            monthly_trend,
            x="Month",
            y="Amount",
            title=f"<span style='color:{CUSTOM_COLOR_PALETTE[0]}'>Monthly Expense Trend</span>",
            labels={"Amount": "Expenses (₹)", "Month": "Month"},
            template="plotly_dark"
        )
        line_chart.update_traces(line=dict(color=CUSTOM_COLOR_PALETTE[0], width=4), mode="lines+markers", marker=dict(size=8, color=CUSTOM_COLOR_PALETTE[0]))
        line_chart.update_layout(
            title_x=0.5, 
            plot_bgcolor="rgba(0,0,0,0)",
            paper_bgcolor="rgba(0,0,0,0)",
            font=dict(color=CUSTOM_COLOR_PALETTE[0]),
            yaxis_title="Expenses (₹)",
            xaxis_title="Month"
        )
        
        # Pie Chart
        category_summary = filtered_df.groupby("Category")["Amount"].sum().reset_index()
        pie_chart = px.pie(
            category_summary,
            names="Category",
            values="Amount",
            title=f"<span style='color:{CUSTOM_COLOR_PALETTE[1]}'>Top Expense Categories</span>",
            color_discrete_sequence=CUSTOM_COLOR_PALETTE,
            template="plotly_dark",
        )
        pie_chart.update_layout(
            title_x=0.5,
            plot_bgcolor="rgba(0,0,0,0)",
            paper_bgcolor="rgba(0,0,0,0)",
            font=dict(color=CUSTOM_COLOR_PALETTE[0])
        )
        
        # Bar Chart
        monthly_category_summary = filtered_df.groupby(["Month", "Category"])["Amount"].sum().reset_index()
        bar_chart = px.bar(
            monthly_category_summary,
            x="Month",
            y="Amount",
            color="Category",
            title=f"<span style='color:{CUSTOM_COLOR_PALETTE[2]}'>Monthly Expenses Breakdown by Category</span>",
            barmode="group",
            color_discrete_sequence=CUSTOM_COLOR_PALETTE,
            labels={"Amount": "Expenses (₹)", "Month": "Month"},
            template="plotly_dark",
        )
        bar_chart.update_layout(
            title_x=0.5,
            plot_bgcolor="rgba(0,0,0,0)",
            paper_bgcolor="rgba(0,0,0,0)",
            font=dict(color=CUSTOM_COLOR_PALETTE[0]),
            yaxis_title="Expenses (₹)",
            xaxis_title="Month"
        )

        # Data Table
        table_data = filtered_df.to_dict('records')
        table_columns = [{"name": i, "id": i} for i in filtered_df.columns]

        return (
            f"₹{total_expenses:,.2f}",
            f"₹{avg_monthly_expense:,.2f}",
            highest_month_name,
            f"₹{highest_month_value:,.2f}",
            lowest_month_name,
            f"₹{lowest_month_value:,.2f}",
            line_chart,
            pie_chart,
            bar_chart,
            table_data,
            table_columns
        )
        
    # Return empty values if no data is loaded
    return "₹0.00", "₹0.00", "N/A", "₹0.00", "N/A", "₹0.00", go.Figure(), go.Figure(), go.Figure(), [], []


# --- Savings Monitor Page Callbacks ---

@app.callback(
    [Output("savings-month-filter", "options"),
     Output("savings-category-filter", "options")],
    Input("stored-canara-data", "data")
)
def populate_savings_filters(canara_json):
    if canara_json:
        df_canara = pd.read_json(canara_json, orient='split')
        months = sorted(df_canara["Month"].unique())
        categories = sorted(df_canara["Category"].unique())
        month_options = [{"label": m, "value": m} for m in months]
        category_options = [{"label": c, "value": c} for c in categories]
        return month_options, category_options
    return [], []

@app.callback(
    [Output("savings-month-filter", "value"),
     Output("savings-category-filter", "value")],
    Input("savings-reset-filters-button", "n_clicks")
)
def reset_savings_filters(n_clicks):
    if n_clicks > 0:
        return None, None
    return no_update, no_update


@app.callback(
    [Output("total-savings-credit-kpi", "children"),
     Output("total-savings-debit-kpi", "children"),
     Output("net-savings-kpi", "children"),
     Output("savings-monthly-trend-chart", "figure"),
     Output("savings-category-bar-chart", "figure"),
     Output("savings-data-table", "data"),
     Output("savings-data-table", "columns")],
    [Input("stored-canara-data", "data"),
     Input("savings-month-filter", "value"),
     Input("savings-category-filter", "value")]
)
def update_savings_monitor(canara_json, selected_months, selected_categories):
    if canara_json:
        df_canara = pd.read_json(canara_json, orient='split')
        
        filtered_df = df_canara.copy()
        if selected_months:
            filtered_df = filtered_df[filtered_df['Month'].isin(selected_months)]
        if selected_categories:
            filtered_df = filtered_df[filtered_df['Category'].isin(selected_categories)]
        
        # KPI Calculations
        total_credit = filtered_df["Credit"].sum()
        total_debit = filtered_df["Debit"].sum()
        net_savings = total_credit - total_debit

        # Charts
        # Monthly Trend (Credit and Debit on same chart)
        monthly_summary = filtered_df.groupby("Month")[["Credit", "Debit"]].sum().reset_index()
        monthly_summary_melt = monthly_summary.melt(id_vars=["Month"], var_name="Transaction Type", value_name="Amount")
        
        line_chart = px.line(
            monthly_summary_melt,
            x="Month",
            y="Amount",
            color="Transaction Type",
            title=f"<span style='color:{CUSTOM_COLOR_PALETTE[0]}'>Monthly Savings and Withdrawals Trend</span>",
            labels={"Amount": "Amount (₹)", "Month": "Month"},
            template="plotly_dark",
            color_discrete_map={"Credit": CUSTOM_COLOR_PALETTE[0], "Debit": CUSTOM_COLOR_PALETTE[1]},
        )
        line_chart.update_layout(
            title_x=0.5,
            plot_bgcolor="rgba(0,0,0,0)",
            paper_bgcolor="rgba(0,0,0,0)",
            font=dict(color=CUSTOM_COLOR_PALETTE[0]),
            yaxis_title="Amount (₹)",
            xaxis_title="Month"
        )

        # Category Breakdown
        category_summary = filtered_df.groupby("Category")["Credit"].sum().reset_index()
        category_summary = category_summary.sort_values(by="Credit", ascending=False)
        
        bar_chart = px.bar(
            category_summary,
            x="Category",
            y="Credit",
            title=f"<span style='color:{CUSTOM_COLOR_PALETTE[1]}'>Savings by Category</span>",
            color="Category",
            color_discrete_sequence=CUSTOM_COLOR_PALETTE,
            labels={"Credit": "Total Savings (₹)", "Category": "Category"},
            template="plotly_dark",
        )
        bar_chart.update_layout(
            title_x=0.5,
            plot_bgcolor="rgba(0,0,0,0)",
            paper_bgcolor="rgba(0,0,0,0)",
            font=dict(color=CUSTOM_COLOR_PALETTE[0]),
            yaxis_title="Total Savings (₹)",
            xaxis_title="Category"
        )
        
        # Data Table
        table_data = filtered_df.to_dict('records')
        table_columns = [{"name": i, "id": i} for i in filtered_df.columns]
        
        return (
            f"₹{total_credit:,.2f}",
            f"₹{total_debit:,.2f}",
            f"₹{net_savings:,.2f}",
            line_chart,
            bar_chart,
            table_data,
            table_columns
        )

    return "₹0.00", "₹0.00", "₹0.00", go.Figure(), go.Figure(), [], []

# --- Savings Goal Calculator Callback ---
@app.callback(
    Output("savings-goal-output", "children"),
    [Input("calculate-goal-button", "n_clicks")],
    [State("target-amount-input", "value"),
     State("duration-input", "value"),
     State("stored-canara-data", "data")]
)
def calculate_savings_goal(n_clicks, target_amount, duration, canara_json):
    if n_clicks is None or n_clicks == 0:
        return no_update

    if not canara_json:
        return html.P("No savings data available to calculate.", className="text-danger")

    df_canara = pd.read_json(canara_json, orient='split')
    monthly_summary = df_canara.groupby("Month")[["Credit", "Debit"]].sum().reset_index()
    monthly_summary["Net Savings"] = monthly_summary["Credit"] - monthly_summary["Debit"]
    
    if monthly_summary.empty:
        return html.P("No historical data to calculate savings goal.", className="text-warning")

    historical_avg_monthly_net_savings = monthly_summary["Net Savings"].mean()

    if target_amount is not None and duration is None:
        if historical_avg_monthly_net_savings <= 0:
            return html.P("Your historical average monthly net savings is ₹0.00 or less. Cannot predict time to goal.", className="text-warning")
        
        time_needed_months = target_amount / historical_avg_monthly_net_savings
        
        return html.P(
            f"At your historical average monthly net savings of ₹{historical_avg_monthly_net_savings:,.2f}, "
            f"it will take approximately {time_needed_months:,.1f} months to save ₹{target_amount:,.2f}."
        )

    elif duration is not None and target_amount is None:
        if duration <= 0:
            return html.P("Duration must be a positive number of months.", className="text-danger")
        
        if historical_avg_monthly_net_savings <= 0:
            return html.P("Your historical average monthly net savings is ₹0.00 or less. You won't save anything in this duration.", className="text-warning")

        projected_savings = historical_avg_monthly_net_savings * duration
        return html.P(
            f"At your historical average monthly net savings of ₹{historical_avg_monthly_net_savings:,.2f}, "
            f"you will save approximately ₹{projected_savings:,.2f} in {duration} months."
        )
        
    elif target_amount is not None and duration is not None:
        if duration <= 0:
            return html.P("Duration must be a positive number of months.", className="text-danger")
        if target_amount <= 0:
            return html.P("Target amount must be a positive number.", className="text-danger")

        monthly_contribution_needed = target_amount / duration
        return html.P(
            f"To save ₹{target_amount:,.2f} in {duration} months, you need to save ₹{monthly_contribution_needed:,.2f} per month.",
            className="text-info"
        )
    
    return html.P("Please enter valid numbers for target amount and/or duration.", className="text-danger")


# --- Investments Page Callbacks ---
@app.callback(
    [Output("investments-month-filter", "options"),
     Output("investments-category-filter", "options")],
    Input("stored-investments-data", "data")
)
def populate_investments_filters(investments_json):
    if investments_json:
        df_investments = pd.read_json(investments_json, orient='split')
        months = sorted(df_investments["Month"].unique())
        categories = sorted(df_investments["Category"].unique())
        month_options = [{"label": m, "value": m} for m in months]
        category_options = [{"label": c, "value": c} for c in categories]
        return month_options, category_options
    return [], []

@app.callback(
    [Output("investments-month-filter", "value"),
     Output("investments-category-filter", "value")],
    Input("investments-reset-filters-button", "n_clicks")
)
def reset_investments_filters(n_clicks):
    if n_clicks > 0:
        return None, None
    return no_update, no_update

@app.callback(
    [Output("total-investments-kpi", "children"),
     Output("avg-monthly-investment-kpi", "children"),
     Output("highest-category-kpi-name", "children"),
     Output("highest-category-kpi-value", "children"),
     Output("lowest-category-kpi-name", "children"),
     Output("lowest-category-kpi-value", "children"),
     Output("investments-monthly-trend-chart", "figure"),
     Output("investments-category-pie-chart", "figure"),
     Output("investments-monthly-by-category-chart", "figure"),
     Output("investments-data-table", "data"),
     Output("investments-data-table", "columns")],
    [Input("stored-investments-data", "data"),
     Input("investments-month-filter", "value"),
     Input("investments-category-filter", "value")]
)
def update_investments_dashboard(investments_json, selected_months, selected_categories):
    if investments_json:
        df_investments = pd.read_json(investments_json, orient='split')
        
        # Filtering logic
        filtered_df = df_investments.copy()
        if selected_months:
            filtered_df = filtered_df[filtered_df['Month'].isin(selected_months)]
        if selected_categories:
            filtered_df = filtered_df[filtered_df['Category'].isin(selected_categories)]
            
        # KPI calculations
        total_investments = filtered_df["Amount"].sum()
        
        monthly_summary = filtered_df.groupby("Month")["Amount"].sum().reset_index()
        avg_monthly_investment = monthly_summary["Amount"].mean() if not monthly_summary.empty else 0
        
        category_summary = filtered_df.groupby("Category")["Amount"].sum().reset_index()
        if not category_summary.empty:
            highest_category = category_summary.loc[category_summary["Amount"].idxmax()]
            lowest_category = category_summary.loc[category_summary["Amount"].idxmin()]
        else:
            highest_category = {'Category': 'N/A', 'Amount': 0}
            lowest_category = {'Category': 'N/A', 'Amount': 0}
            
        # Charts
        # Trend Chart
        line_chart = px.line(
            monthly_summary,
            x="Month",
            y="Amount",
            title=f"<span style='color:{CUSTOM_COLOR_PALETTE[0]}'>Monthly Investment Trend</span>",
            labels={"Amount": "Amount (₹)", "Month": "Month"},
            template="plotly_dark"
        )
        line_chart.update_traces(line=dict(color=CUSTOM_COLOR_PALETTE[0], width=4), mode="lines+markers", marker=dict(size=8, color=CUSTOM_COLOR_PALETTE[0]))
        line_chart.update_layout(
            title_x=0.5,
            plot_bgcolor="rgba(0,0,0,0)",
            paper_bgcolor="rgba(0,0,0,0)",
            font=dict(color=CUSTOM_COLOR_PALETTE[0]),
            yaxis_title="Amount (₹)",
            xaxis_title="Month",
        )
        
        # Pie Chart
        pie_chart = px.pie(
            category_summary,
            names="Category",
            values="Amount",
            title=f"<span style='color:{CUSTOM_COLOR_PALETTE[1]}'>Investment Categories Breakdown</span>",
            color_discrete_sequence=CUSTOM_COLOR_PALETTE,
            template="plotly_dark",
        )
        pie_chart.update_layout(
            title_x=0.5,
            plot_bgcolor="rgba(0,0,0,0)",
            paper_bgcolor="rgba(0,0,0,0)",
            font=dict(color=CUSTOM_COLOR_PALETTE[0])
        )

        # Bar Chart
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
            f"₹{total_investments:,.2f}",
            f"₹{avg_monthly_investment:,.2f}",
            f"{highest_category['Category']}",
            f"₹{highest_category['Amount']:,.2f}",
            f"{lowest_category['Category']}",
            f"₹{lowest_category['Amount']:,.2f}",
            line_chart,
            pie_chart,
            bar_chart,
            table_data,
            table_columns
        )
    
    return "₹0.00", "₹0.00", "N/A", "₹0.00", "N/A", "₹0.00", go.Figure(), go.Figure(), go.Figure(), [], []

# --- Analytics & Trends Page Callbacks ---
@app.callback(
    [Output("trend-category-filter", "options"),
     Output("month-range-slider", "marks"),
     Output("month-range-slider", "max"),
     Output("month-range-slider", "value")],
    Input("stored-icic-data", "data")
)
def populate_analytics_filters(icic_json):
    if icic_json:
        df_icic = pd.read_json(icic_json, orient='split')
        categories = sorted(df_icic["Category"].unique())
        category_options = [{"label": c, "value": c} for c in categories]
        
        months = sorted(df_icic["Month"].unique())
        marks = {i: month for i, month in enumerate(months)}
        max_val = len(months) - 1
        value = [0, max_val]
        
        return category_options, marks, max_val, value
    return [], {}, 1, [0, 1]

@app.callback(
    [Output("category-trends-chart", "figure"),
     Output("monthly-correlation-chart", "figure"),
     Output("category-heatmap-chart", "figure")],
    [Input("stored-icic-data", "data"),
     Input("trend-category-filter", "value"),
     Input("month-range-slider", "value")]
)
def update_analytics_dashboard(icic_json, selected_categories, month_range_index):
    if icic_json:
        df_icic = pd.read_json(icic_json, orient='split')
        months = sorted(df_icic["Month"].unique())
        
        start_month_idx, end_month_idx = month_range_index
        filtered_months = months[start_month_idx:end_month_idx+1]
        
        filtered_df = df_icic[df_icic['Month'].isin(filtered_months)]
        
        if selected_categories:
            filtered_df = filtered_df[filtered_df['Category'].isin(selected_categories)]

        # Line Chart
        monthly_trends = filtered_df.groupby(["Month", "Category"])["Amount"].sum().reset_index()
        line_chart = px.line(
            monthly_trends,
            x="Month",
            y="Amount",
            color="Category",
            title=f"<span style='color:{CUSTOM_COLOR_PALETTE[0]}'>Expense Trends for Selected Categories</span>",
            labels={"Amount": "Expenses (₹)", "Month": "Month"},
            template="plotly_dark",
            color_discrete_sequence=CUSTOM_COLOR_PALETTE,
        )
        line_chart.update_layout(
            title_x=0.5,
            plot_bgcolor="rgba(0,0,0,0)",
            paper_bgcolor="rgba(0,0,0,0)",
            font=dict(color=CUSTOM_COLOR_PALETTE[0]),
            yaxis_title="Expenses (₹)",
            xaxis_title="Month"
        )
        
        # Scatter Plot
        monthly_summary = filtered_df.groupby("Month")["Amount"].sum().reset_index()
        monthly_summary["Month"] = pd.to_datetime(monthly_summary["Month"], format="%B %Y")
        monthly_summary = monthly_summary.sort_values(by="Month")
        monthly_summary["Lagged_Amount"] = monthly_summary["Amount"].shift(1)
        scatter_chart = px.scatter(
            monthly_summary.dropna(),
            x="Lagged_Amount",
            y="Amount",
            title=f"<span style='color:{CUSTOM_COLOR_PALETTE[1]}'>Monthly Expenses Correlation (Month vs. Previous Month)</span>",
            labels={"Amount": "Current Month Expenses (₹)", "Lagged_Amount": "Previous Month Expenses (₹)"},
            template="plotly_dark",
            color_discrete_sequence=[CUSTOM_COLOR_PALETTE[1]],
        )
        scatter_chart.update_layout(
            title_x=0.5,
            plot_bgcolor="rgba(0,0,0,0)",
            paper_bgcolor="rgba(0,0,0,0)",
            font=dict(color=CUSTOM_COLOR_PALETTE[0])
        )

        # Heatmap
        heatmap_data = filtered_df.groupby(["Month", "Category"])["Amount"].sum().unstack(fill_value=0)
        heatmap_figure = go.Figure(data=go.Heatmap(
            z=heatmap_data.values,
            x=heatmap_data.columns,
            y=heatmap_data.index,
            colorscale=[[0, 'rgba(0,0,0,0)'], [1, CUSTOM_COLOR_PALETTE[2]]],
            showscale=True,
            hovertemplate="Month: %{y}<br>Category: %{x}<br>Amount: ₹%{z:,.2f}<extra></extra>"
        ))
        heatmap_figure.update_layout(
            title=f"<span style='color:{CUSTOM_COLOR_PALETTE[2]}'>Expense Heatmap (Month vs. Category)</span>",
            title_x=0.5,
            plot_bgcolor="rgba(0,0,0,0)",
            paper_bgcolor="rgba(0,0,0,0)",
            font=dict(color=CUSTOM_COLOR_PALETTE[0]),
            xaxis_title="Category",
            yaxis_title="Month",
        )

        return line_chart, scatter_chart, heatmap_figure
    
    return go.Figure(), go.Figure(), go.Figure()

# --- Raw Data Tables Callbacks ---
@app.callback(
    [Output("icic-raw-data-table", "data"),
     Output("icic-raw-data-table", "columns")],
    Input("raw-data-tabs", "active_tab"),
    State("stored-icic-data", "data")
)
def update_icic_raw_table(active_tab, icic_json):
    if active_tab == "tab-1" and icic_json:
        df = pd.read_json(icic_json, orient='split')
        data = df.to_dict('records')
        columns = [{"name": i, "id": i} for i in df.columns]
        return data, columns
    return [], []

@app.callback(
    [Output("canara-raw-data-table", "data"),
     Output("canara-raw-data-table", "columns")],
    Input("raw-data-tabs", "active_tab"),
    State("stored-canara-data", "data")
)
def update_canara_raw_table(active_tab, canara_json):
    if active_tab == "tab-2" and canara_json:
        df = pd.read_json(canara_json, orient='split')
        data = df.to_dict('records')
        columns = [{"name": i, "id": i} for i in df.columns]
        return data, columns
    return [], []

@app.callback(
    [Output("investments-raw-data-table", "data"),
     Output("investments-raw-data-table", "columns")],
    Input("raw-data-tabs", "active_tab"),
    State("stored-investments-data", "data")
)
def update_investments_raw_table(active_tab, investments_json):
    if active_tab == "tab-3" and investments_json:
        df = pd.read_json(investments_json, orient='split')
        data = df.to_dict('records')
        columns = [{"name": i, "id": i} for i in df.columns]
        return data, columns
    return [], []


if __name__ == "__main__":
    from waitress import serve
    print("Starting the Dashboard ... Loading data from Google Sheets...")
    serve(server, host="0.0.0.0", port=8080)