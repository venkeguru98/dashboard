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
    try:
        credentials_content_base64 = os.environ.get("GCP_SA_CREDENTIALS")
        credentials_content_bytes = base64.b64decode(credentials_content_base64)
        credentials_content_json = json.loads(credentials_content_bytes.decode('utf-8'))
        
        # Use a temporary file to store the credentials
        # This is the safest way to handle this on services like Heroku
        # which have an ephemeral file system.
        with tempfile.NamedTemporaryFile(mode="w+", delete=False, suffix=".json") as temp_file:
            json.dump(credentials_content_json, temp_file)
            temp_file_path = temp_file.name
        
        SERVICE_ACCOUNT_FILE = temp_file_path
        print("✅ Success: Using credentials from environment variable.")

    except (base64.binascii.Error, json.JSONDecodeError) as e:
        print(f"❌ Error decoding credentials from environment variable: {e}")
        SERVICE_ACCOUNT_FILE = r"C:\Users\JEEVALAKSHMI R\Videos\dashboard_for_expense\icic-salary-data-52568c61b6e3.json"
        
else:
    # Fallback to local file path for local development
    SERVICE_ACCOUNT_FILE = r"C:\Users\JEEVALAKSHMI R\Videos\dashboard_for_expense\icic-salary-data-52568c61b6e3.json"
    print("⚠️ Warning: Environment variable 'GCP_SA_CREDENTIALS' not found. Falling back to local file path.")


def load_data_from_google_sheets():
    df_icic = pd.DataFrame()
    df_canara = pd.DataFrame()
    df_investments = pd.DataFrame()
    error_message = None

    if not os.path.exists(SERVICE_ACCOUNT_FILE):
        error_message = f"❌ Error: Service account file not found at {SERVICE_ACCOUNT_FILE}. Please update the path."
        return df_icic, df_canara, df_investments, error_message
    
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

        # Charts Section
        dbc.Row([
            dbc.Col(dcc.Loading(id="loading-investments-trend", type="circle", color=CUSTOM_COLOR_PALETTE[0], children=dcc.Graph(id="investments-monthly-trend-chart")), lg=6, md=12, className="mb-4 chart-panel-new-theme"),
            dbc.Col(dcc.Loading(id="loading-investments-pie", type="circle", color=CUSTOM_COLOR_PALETTE[1], children=dcc.Graph(id="investments-category-pie-chart")), lg=6, md=12, className="mb-4 chart-panel-new-theme"),
        ], className="g-4"),

        dbc.Row([
            dbc.Col(dcc.Loading(id="loading-investments-bar", type="circle", color=CUSTOM_COLOR_PALETTE[2], children=dcc.Graph(id="investments-monthly-by-category-chart")), width=12, className="mb-4 chart-panel-new-theme"),
        ], className="g-4"),

        # Data Table Section
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

# --- Layout for the Analytics & Trends Page ---
analytics_page_layout = dbc.Col(
    [
        html.H2("📈 Analytics & Trends", className="section-title-new-theme text-center mb-4", style={'color': 'var(--accent-blue)', 'textShadow': 'var(--glow-blue)'}),
        
        # Trend Analysis
        dbc.Row(
            dbc.Col(
                dcc.Loading(
                    id="loading-trend-analysis",
                    type="circle", color=CUSTOM_COLOR_PALETTE[0],
                    children=dcc.Graph(id="expense-trend-analysis-chart")
                ),
                width=12, className="mb-4 chart-panel-new-theme"
            )
        ),
        
        # Category Trend Comparison
        dbc.Row([
            dbc.Col(
                html.Div([
                    html.Label("Select Categories to Compare:", className="form-label-new-theme"),
                    dcc.Dropdown(
                        id="analytics-category-select",
                        options=[],
                        multi=True,
                        placeholder="Select up to 4 Categories",
                        className="dropdown-new-theme"
                    ),
                ]),
                width=12, className="mb-3"
            )
        ]),
        dbc.Row(
            dbc.Col(
                dcc.Loading(
                    id="loading-category-comparison",
                    type="circle", color=CUSTOM_COLOR_PALETTE[1],
                    children=dcc.Graph(id="category-comparison-chart")
                ),
                width=12, className="mb-4 chart-panel-new-theme"
            )
        )
    ],
    width=12,
    className="main-content-new-theme"
)

# --- Layout for the Raw Data Table Page ---
data_table_page_layout = dbc.Col(
    [
        html.H2("📝 Raw Data Tables", className="section-title-new-theme text-center mb-4", style={'color': 'var(--accent-purple)', 'textShadow': 'var(--glow-purple)'}),
        
        dbc.Tabs(
            [
                dbc.Tab(
                    html.Div([
                        html.H4("ICIC Salary Data", className="section-title-new-theme mb-3"),
                        dcc.Loading(
                            id="loading-icic-table", type="circle", color=CUSTOM_COLOR_PALETTE[0],
                            children=dash_table.DataTable(
                                id="raw-icic-data-table",
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
                                export_format="xlsx"
                            )
                        )
                    ]),
                    label="ICIC", tab_id="icic_tab", className="tab-style-new-theme", active_tab_style={"backgroundColor": "#121212", "color": "#00FFFF"}
                ),
                dbc.Tab(
                    html.Div([
                        html.H4("CANARA Data", className="section-title-new-theme mb-3"),
                        dcc.Loading(
                            id="loading-canara-table", type="circle", color=CUSTOM_COLOR_PALETTE[1],
                            children=dash_table.DataTable(
                                id="raw-canara-data-table",
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
                                export_format="xlsx"
                            )
                        )
                    ]),
                    label="CANARA", tab_id="canara_tab", className="tab-style-new-theme", active_tab_style={"backgroundColor": "#121212", "color": "#00FFFF"}
                ),
                dbc.Tab(
                    html.Div([
                        html.H4("Investment Data", className="section-title-new-theme mb-3"),
                        dcc.Loading(
                            id="loading-investments-table-raw", type="circle", color=CUSTOM_COLOR_PALETTE[2],
                            children=dash_table.DataTable(
                                id="raw-investments-data-table",
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
                                export_format="xlsx"
                            )
                        )
                    ]),
                    label="Investments", tab_id="investments_tab", className="tab-style-new-theme", active_tab_style={"backgroundColor": "#121212", "color": "#00FFFF"}
                )
            ],
            id="raw-data-tabs",
            active_tab="icic_tab",
            className="tabs-container-new-theme mb-4"
        )
    ],
    width=12,
    className="main-content-new-theme"
)


# --- Layout for the Settings Page ---
settings_page_layout = dbc.Col(
    [
        html.H2("⚙️ Configuration & Settings", className="section-title-new-theme text-center mb-4", style={'color': 'var(--accent-gold)', 'textShadow': 'var(--glow-gold)'}),
        dbc.Card(
            dbc.CardBody([
                html.H4("Application Details", className="card-title-new-theme"),
                html.P("This dashboard is designed to provide financial insights from your Google Sheets data.", className="card-text-new-theme"),
                html.P([
                    "The application version is ", html.B("1.0.1"), "."
                ]),
                html.P([
                    "The last data refresh was on ", html.B(id="last-refresh-time")
                ]),
                html.P("To update the data, simply refresh the page or wait for the automatic refresh every 60 seconds."),
            ]),
            className="mb-4 settings-card-new-theme"
        ),
        dbc.Card(
            dbc.CardBody([
                html.H4("Developer Information", className="card-title-new-theme"),
                html.P("This dashboard was developed by Venke and is maintained for personal use.", className="card-text-new-theme"),
                html.P([
                    "Contact: ", html.A("venke.dashboard@email.com", href="mailto:venke.dashboard@email.com", className="link-new-theme")
                ]),
            ]),
            className="mb-4 settings-card-new-theme"
        )
    ],
    width=12,
    className="main-content-new-theme"
)

# --- Callbacks ---

@app.callback(
    [Output('page-content', 'children'),
     Output('last-refresh-time', 'children'),
     Output('month-filter', 'options'),
     Output('month-filter', 'value'),
     Output('category-filter', 'options'),
     Output('category-filter', 'value'),
     Output('savings-month-filter', 'options'),
     Output('savings-month-filter', 'value'),
     Output('savings-category-filter', 'options'),
     Output('savings-category-filter', 'value'),
     Output('investments-month-filter', 'options'),
     Output('investments-month-filter', 'value'),
     Output('investments-category-filter', 'options'),
     Output('investments-category-filter', 'value'),
     Output('analytics-category-select', 'options'),
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
     Output('total-savings-credit-kpi', 'children'),
     Output('total-savings-debit-kpi', 'children'),
     Output('net-savings-kpi', 'children'),
     Output('savings-monthly-trend-chart', 'figure'),
     Output('savings-category-bar-chart', 'figure'),
     Output('savings-data-table', 'data'),
     Output('savings-data-table', 'columns'),
     Output('total-investments-kpi', 'children'),
     Output('avg-monthly-investment-kpi', 'children'),
     Output('highest-category-kpi-name', 'children'),
     Output('highest-category-kpi-value', 'children'),
     Output('lowest-category-kpi-name', 'children'),
     Output('lowest-category-kpi-value', 'children'),
     Output('investments-monthly-trend-chart', 'figure'),
     Output('investments-category-pie-chart', 'figure'),
     Output('investments-monthly-by-category-chart', 'figure'),
     Output('raw-icic-data-table', 'data'),
     Output('raw-icic-data-table', 'columns'),
     Output('raw-canara-data-table', 'data'),
     Output('raw-canara-data-table', 'columns'),
     Output('raw-investments-data-table', 'data'),
     Output('raw-investments-data-table', 'columns'),
     Output('expense-trend-analysis-chart', 'figure'),
     Output('category-comparison-chart', 'figure')],
    [Input('url', 'pathname'),
     Input('stored-icic-data', 'data'),
     Input('stored-canara-data', 'data'),
     Input('stored-investments-data', 'data'),
     Input('month-filter', 'value'),
     Input('category-filter', 'value'),
     Input('savings-month-filter', 'value'),
     Input('savings-category-filter', 'value'),
     Input('investments-month-filter', 'value'),
     Input('investments-category-filter', 'value'),
     Input('analytics-category-select', 'value'),
     Input('reset-filters-button', 'n_clicks'),
     Input('savings-reset-filters-button', 'n_clicks'),
     Input('investments-reset-filters-button', 'n_clicks')]
)
def update_full_dashboard(
    pathname, icic_json, canara_json, investments_json, 
    months, categories, savings_months, savings_categories,
    investments_months, investments_categories, analytics_categories,
    reset_clicks, savings_reset_clicks, investments_reset_clicks
):
    ctx = dash.callback_context
    triggered_id = ctx.triggered[0]['prop_id'].split('.')[0] if ctx.triggered else 'no_trigger'

    # Load and combine data
    icic_df = pd.DataFrame()
    if icic_json:
        icic_df = pd.read_json(icic_json, orient='split')
        icic_df["Amount"] = pd.to_numeric(icic_df["Amount"], errors='coerce').fillna(0)
        icic_df["Month"] = icic_df["Month"].astype(str)
    
    canara_df = pd.DataFrame()
    if canara_json:
        canara_df = pd.read_json(canara_json, orient='split')
        canara_df["Debit"] = pd.to_numeric(canara_df["Debit"], errors='coerce').fillna(0)
        canara_df["Credit"] = pd.to_numeric(canara_df["Credit"], errors='coerce').fillna(0)
        canara_df["Month"] = canara_df["Month"].astype(str)
        
    investments_df = pd.DataFrame()
    if investments_json:
        investments_df = pd.read_json(investments_json, orient='split')
        investments_df["Amount"] = pd.to_numeric(investments_df["Amount"], errors='coerce').fillna(0)
        investments_df["Month"] = investments_df["Month"].astype(str)

    # Combine all month and category options for filters
    all_months = pd.unique(pd.concat([icic_df["Month"], canara_df["Month"], investments_df["Month"]])) if not (icic_df.empty and canara_df.empty and investments_df.empty) else []
    all_categories = pd.unique(pd.concat([icic_df["Category"], canara_df["Category"], investments_df["Category"]])) if not (icic_df.empty and canara_df.empty and investments_df.empty) else []
    month_options = [{"label": m, "value": m} for m in sorted(all_months)]
    category_options = [{"label": c, "value": c} for c in sorted(all_categories)]

    # Reset filter values if a reset button was clicked
    if triggered_id in ['reset-filters-button', 'savings-reset-filters-button', 'investments-reset-filters-button']:
        months, categories, savings_months, savings_categories, investments_months, investments_categories = [], [], [], [], [], []

    # Default outputs
    default_outputs = [
        "₹0.00", "₹0.00", "N/A", "₹0.00", "N/A", "₹0.00",
        {}, {}, {}, [], [],
        "₹0.00", "₹0.00", "₹0.00", {}, {}, [], [],
        "₹0.00", "₹0.00", "N/A", "₹0.00", "N/A", "₹0.00",
        {}, {}, {},
        [], [], [], [], [], [],
        {}, {}
    ]
    
    # Initialize all outputs to default values
    outputs = [no_update] * 53
    outputs[1] = time.strftime("%Y-%m-%d %H:%M:%S")

    # Update filter options based on available data, but don't change dropdown values
    outputs[2], outputs[4], outputs[6], outputs[8], outputs[10], outputs[12] = (
        month_options, category_options, month_options, category_options, month_options, category_options
    )
    outputs[14] = category_options

    # Handle filter value resets
    if triggered_id == 'reset-filters-button':
        outputs[3], outputs[5] = [], []
    if triggered_id == 'savings-reset-filters-button':
        outputs[7], outputs[9] = [], []
    if triggered_id == 'investments-reset-filters-button':
        outputs[11], outputs[13] = [], []

    if pathname == '/':
        outputs[0] = dashboard_page_layout
        
        combined_df = pd.DataFrame()
        if not icic_df.empty:
            combined_df = pd.concat([combined_df, icic_df], ignore_index=True)

        filtered_df = combined_df.copy()
        if months:
            filtered_df = filtered_df[filtered_df["Month"].isin(months)]
        if categories:
            filtered_df = filtered_df[filtered_df["Category"].isin(categories)]

        # KPI calculations
        total_expenses = filtered_df["Amount"].sum()
        monthly_summary = filtered_df.groupby("Month")["Amount"].sum().reset_index()
        avg_monthly_expense = monthly_summary["Amount"].mean() if not monthly_summary.empty else 0
        
        if not monthly_summary.empty:
            highest_month = monthly_summary.loc[monthly_summary["Amount"].idxmax()]
            lowest_month = monthly_summary.loc[monthly_summary["Amount"].idxmin()]
            highest_month_name = highest_month["Month"]
            highest_month_value = f"₹{highest_month['Amount']:,.2f}"
            lowest_month_name = lowest_month["Month"]
            lowest_month_value = f"₹{lowest_month['Amount']:,.2f}"
        else:
            highest_month_name = "N/A"
            highest_month_value = "₹0.00"
            lowest_month_name = "N/A"
            lowest_month_value = "₹0.00"

        # Monthly Trend Chart
        fig_trend = px.line(
            monthly_summary,
            x="Month",
            y="Amount",
            title=f"<span style='color:{CUSTOM_COLOR_PALETTE[0]}'>Monthly Expenses Trend</span>",
            labels={"Amount": "Amount (₹)", "Month": "Month"},
            template="plotly_dark",
            color_discrete_sequence=[CUSTOM_COLOR_PALETTE[0]]
        )
        fig_trend.update_layout(
            title_x=0.5,
            plot_bgcolor="rgba(0,0,0,0)",
            paper_bgcolor="rgba(0,0,0,0)",
            font=dict(color=CUSTOM_COLOR_PALETTE[0]),
            yaxis_title="Amount (₹)"
        )

        # Top Categories Pie Chart
        category_summary = filtered_df.groupby("Category")["Amount"].sum().reset_index()
        fig_pie = px.pie(
            category_summary,
            names="Category",
            values="Amount",
            title=f"<span style='color:{CUSTOM_COLOR_PALETTE[1]}'>Expenses by Category</span>",
            color_discrete_sequence=CUSTOM_COLOR_PALETTE,
            template="plotly_dark"
        )
        fig_pie.update_traces(textposition='inside', textinfo='percent+label')
        fig_pie.update_layout(
            title_x=0.5,
            plot_bgcolor="rgba(0,0,0,0)",
            paper_bgcolor="rgba(0,0,0,0)",
            font=dict(color=CUSTOM_COLOR_PALETTE[0]),
            legend_title="Category"
        )
        
        # Monthly Breakdown by Category Chart
        monthly_category_summary = filtered_df.groupby(["Month", "Category"])["Amount"].sum().reset_index()
        fig_bar = px.bar(
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
        fig_bar.update_layout(
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
        
        outputs[15], outputs[16], outputs[17], outputs[18], outputs[19], outputs[20] = (
            f"₹{total_expenses:,.2f}", f"₹{avg_monthly_expense:,.2f}", 
            highest_month_name, highest_month_value, 
            lowest_month_name, lowest_month_value
        )
        outputs[21], outputs[22], outputs[23] = fig_trend, fig_pie, fig_bar
        outputs[24], outputs[25] = table_data, table_columns
        
    elif pathname == '/savings':
        outputs[0] = savings_monitor_layout
        
        savings_filtered_df = canara_df.copy()
        if savings_months:
            savings_filtered_df = savings_filtered_df[savings_filtered_df["Month"].isin(savings_months)]
        if savings_categories:
            savings_filtered_df = savings_filtered_df[savings_filtered_df["Category"].isin(savings_categories)]
            
        # Calculate Savings KPIs
        total_savings_credit = savings_filtered_df['Credit'].sum()
        total_savings_debit = savings_filtered_df['Debit'].sum()
        net_savings = total_savings_credit - total_savings_debit
        
        # Savings Trend Chart
        monthly_savings_trend = savings_filtered_df.groupby("Month").agg(Credit=('Credit', 'sum'), Debit=('Debit', 'sum')).reset_index()
        monthly_savings_trend["Net"] = monthly_savings_trend["Credit"] - monthly_savings_trend["Debit"]
        
        fig_savings_trend = go.Figure()
        fig_savings_trend.add_trace(go.Bar(x=monthly_savings_trend['Month'], y=monthly_savings_trend['Credit'], name='Credit (Savings)', marker_color=CUSTOM_COLOR_PALETTE[0]))
        fig_savings_trend.add_trace(go.Bar(x=monthly_savings_trend['Month'], y=monthly_savings_trend['Debit'], name='Debit (Withdrawals)', marker_color=CUSTOM_COLOR_PALETTE[1]))
        fig_savings_trend.add_trace(go.Scatter(x=monthly_savings_trend['Month'], y=monthly_savings_trend['Net'], name='Net Savings', mode='lines+markers', line=dict(color=CUSTOM_COLOR_PALETTE[2], width=4)))
        
        fig_savings_trend.update_layout(
            barmode='group',
            title=f"<span style='color:{CUSTOM_COLOR_PALETTE[0]}'>Monthly Savings and Withdrawals Trend</span>",
            xaxis_title="Month",
            yaxis_title="Amount (₹)",
            legend_title="Type",
            template="plotly_dark",
            title_x=0.5,
            plot_bgcolor="rgba(0,0,0,0)",
            paper_bgcolor="rgba(0,0,0,0)",
            font=dict(color=CUSTOM_COLOR_PALETTE[0]),
        )
        
        # Savings by Category Bar Chart
        savings_category_summary = savings_filtered_df.groupby("Category").agg(TotalCredit=('Credit', 'sum'), TotalDebit=('Debit', 'sum')).reset_index()
        fig_savings_category_bar = go.Figure()
        fig_savings_category_bar.add_trace(go.Bar(x=savings_category_summary['Category'], y=savings_category_summary['TotalCredit'], name='Total Credit', marker_color=CUSTOM_COLOR_PALETTE[0]))
        fig_savings_category_bar.add_trace(go.Bar(x=savings_category_summary['Category'], y=savings_category_summary['TotalDebit'], name='Total Debit', marker_color=CUSTOM_COLOR_PALETTE[1]))
        
        fig_savings_category_bar.update_layout(
            barmode='group',
            title=f"<span style='color:{CUSTOM_COLOR_PALETTE[1]}'>Savings & Withdrawals by Category</span>",
            xaxis_title="Category",
            yaxis_title="Amount (₹)",
            legend_title="Type",
            template="plotly_dark",
            title_x=0.5,
            plot_bgcolor="rgba(0,0,0,0)",
            paper_bgcolor="rgba(0,0,0,0)",
            font=dict(color=CUSTOM_COLOR_PALETTE[0]),
        )
        
        # Data Table
        savings_table_data = savings_filtered_df.to_dict('records')
        savings_table_columns = [{"name": i, "id": i} for i in savings_filtered_df.columns]
        
        outputs[26], outputs[27], outputs[28] = (f"₹{total_savings_credit:,.2f}", f"₹{total_savings_debit:,.2f}", f"₹{net_savings:,.2f}")
        outputs[29], outputs[30] = fig_savings_trend, fig_savings_category_bar
        outputs[31], outputs[32] = savings_table_data, savings_table_columns

    elif pathname == '/investments':
        outputs[0] = investments_layout
        
        investments_filtered_df = investments_df.copy()
        if investments_months:
            investments_filtered_df = investments_filtered_df[investments_filtered_df["Month"].isin(investments_months)]
        if investments_categories:
            investments_filtered_df = investments_filtered_df[investments_filtered_df["Category"].isin(investments_categories)]

        # Calculate Investments KPIs
        total_investments = investments_filtered_df['Amount'].sum()
        avg_monthly_investment = investments_filtered_df.groupby("Month")['Amount'].sum().mean() if not investments_filtered_df.empty else 0
        
        category_investments = investments_filtered_df.groupby('Category')['Amount'].sum().reset_index()
        if not category_investments.empty:
            highest_category = category_investments.loc[category_investments['Amount'].idxmax()]
            lowest_category = category_investments.loc[category_investments['Amount'].idxmin()]
            highest_category_name = highest_category['Category']
            highest_category_value = f"₹{highest_category['Amount']:,.2f}"
            lowest_category_name = lowest_category['Category']
            lowest_category_value = f"₹{lowest_category['Amount']:,.2f}"
        else:
            highest_category_name = "N/A"
            highest_category_value = "₹0.00"
            lowest_category_name = "N/A"
            lowest_category_value = "₹0.00"
        
        # Investments Trend Chart
        monthly_investments_trend = investments_filtered_df.groupby("Month")["Amount"].sum().reset_index()
        fig_investments_trend = px.line(
            monthly_investments_trend,
            x="Month",
            y="Amount",
            title=f"<span style='color:{CUSTOM_COLOR_PALETTE[0]}'>Monthly Investments Trend</span>",
            labels={"Amount": "Amount (₹)", "Month": "Month"},
            template="plotly_dark",
            color_discrete_sequence=[CUSTOM_COLOR_PALETTE[0]]
        )
        fig_investments_trend.update_layout(
            title_x=0.5,
            plot_bgcolor="rgba(0,0,0,0)",
            paper_bgcolor="rgba(0,0,0,0)",
            font=dict(color=CUSTOM_COLOR_PALETTE[0]),
            yaxis_title="Amount (₹)"
        )

        # Investments Category Pie Chart
        category_summary = investments_filtered_df.groupby("Category")["Amount"].sum().reset_index()
        fig_investments_pie = px.pie(
            category_summary,
            names="Category",
            values="Amount",
            title=f"<span style='color:{CUSTOM_COLOR_PALETTE[1]}'>Investments by Category</span>",
            color_discrete_sequence=CUSTOM_COLOR_PALETTE,
            template="plotly_dark"
        )
        fig_investments_pie.update_traces(textposition='inside', textinfo='percent+label')
        fig_investments_pie.update_layout(
            title_x=0.5,
            plot_bgcolor="rgba(0,0,0,0)",
            paper_bgcolor="rgba(0,0,0,0)",
            font=dict(color=CUSTOM_COLOR_PALETTE[0]),
            legend_title="Category"
        )
        
        # Monthly Investments by Category Bar Chart
        monthly_category_summary = investments_filtered_df.groupby(["Month", "Category"])["Amount"].sum().reset_index()
        fig_investments_bar = px.bar(
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
        fig_investments_bar.update_layout(
            title_x=0.5,
            plot_bgcolor="rgba(0,0,0,0)",
            paper_bgcolor="rgba(0,0,0,0)",
            font=dict(color=CUSTOM_COLOR_PALETTE[0]),
            yaxis_title="Amount (₹)",
            xaxis_title="Month",
        )
        
        outputs[33], outputs[34] = (f"₹{total_investments:,.2f}", f"₹{avg_monthly_investment:,.2f}")
        outputs[35], outputs[36], outputs[37], outputs[38] = (highest_category_name, highest_category_value, lowest_category_name, lowest_category_value)
        outputs[39], outputs[40], outputs[41] = fig_investments_trend, fig_investments_pie, fig_investments_bar

    elif pathname == '/analytics':
        outputs[0] = analytics_page_layout
        
        combined_df_expenses = pd.DataFrame()
        if not icic_df.empty:
            combined_df_expenses = pd.concat([combined_df_expenses, icic_df], ignore_index=True)
            
        filtered_df = combined_df_expenses.copy()
        if analytics_categories:
            filtered_df = filtered_df[filtered_df["Category"].isin(analytics_categories)]
        
        # Overall Trend Analysis Chart
        monthly_expenses_trend = filtered_df.groupby("Month")["Amount"].sum().reset_index()
        fig_trend_analysis = px.line(
            monthly_expenses_trend,
            x="Month",
            y="Amount",
            title=f"<span style='color:{CUSTOM_COLOR_PALETTE[0]}'>Overall Expenses Trend</span>",
            labels={"Amount": "Amount (₹)", "Month": "Month"},
            template="plotly_dark",
            color_discrete_sequence=[CUSTOM_COLOR_PALETTE[0]]
        )
        fig_trend_analysis.update_layout(
            title_x=0.5,
            plot_bgcolor="rgba(0,0,0,0)",
            paper_bgcolor="rgba(0,0,0,0)",
            font=dict(color=CUSTOM_COLOR_PALETTE[0]),
            yaxis_title="Amount (₹)"
        )
        
        # Category Comparison Chart
        if analytics_categories:
            category_comparison_df = filtered_df.groupby(["Month", "Category"])["Amount"].sum().reset_index()
            fig_category_comparison = px.line(
                category_comparison_df,
                x="Month",
                y="Amount",
                color="Category",
                title=f"<span style='color:{CUSTOM_COLOR_PALETTE[1]}'>Monthly Expense Trend for Selected Categories</span>",
                labels={"Amount": "Amount (₹)", "Month": "Month", "Category": "Category"},
                template="plotly_dark",
                color_discrete_sequence=CUSTOM_COLOR_PALETTE
            )
            fig_category_comparison.update_layout(
                title_x=0.5,
                plot_bgcolor="rgba(0,0,0,0)",
                paper_bgcolor="rgba(0,0,0,0)",
                font=dict(color=CUSTOM_COLOR_PALETTE[0]),
                yaxis_title="Amount (₹)"
            )
        else:
            fig_category_comparison = {}
            
        outputs[48], outputs[49] = fig_trend_analysis, fig_category_comparison
        
    elif pathname == '/data-table':
        outputs[0] = data_table_page_layout
        
        icic_table_data = icic_df.to_dict('records') if not icic_df.empty else []
        icic_table_columns = [{"name": i, "id": i} for i in icic_df.columns] if not icic_df.empty else []
        
        canara_table_data = canara_df.to_dict('records') if not canara_df.empty else []
        canara_table_columns = [{"name": i, "id": i} for i in canara_df.columns] if not canara_df.empty else []
        
        investments_table_data = investments_df.to_dict('records') if not investments_df.empty else []
        investments_table_columns = [{"name": i, "id": i} for i in investments_df.columns] if not investments_df.empty else []

        outputs[42], outputs[43], outputs[44], outputs[45], outputs[46], outputs[47] = (
            icic_table_data, icic_table_columns, canara_table_data, canara_table_columns, investments_table_data, investments_table_columns
        )

    elif pathname == '/settings':
        outputs[0] = settings_page_layout
        
    else: # Default to dashboard page if path is not recognized
        outputs[0] = dashboard_page_layout

    # Return all outputs
    return outputs

@app.callback(
    Output('savings-goal-output', 'children'),
    [Input('calculate-goal-button', 'n_clicks')],
    [State('target-amount-input', 'value'),
     State('duration-input', 'value'),
     State('stored-canara-data', 'data')]
)
def calculate_savings_goal(n_clicks, target_amount, duration, canara_json):
    if not n_clicks:
        return no_update
        
    canara_df = pd.DataFrame()
    if canara_json:
        canara_df = pd.read_json(canara_json, orient='split')
        canara_df["Debit"] = pd.to_numeric(canara_df["Debit"], errors='coerce').fillna(0)
        canara_df["Credit"] = pd.to_numeric(canara_df["Credit"], errors='coerce').fillna(0)

    if canara_df.empty:
        return html.P("No savings data available to calculate a goal.", className="text-danger")

    # Calculate historical average monthly net savings
    monthly_net_savings = canara_df.groupby('Month').apply(lambda x: x['Credit'].sum() - x['Debit'].sum())
    historical_avg_monthly_net_savings = monthly_net_savings.mean()

    # Determine which calculation to perform
    if target_amount is not None and target_amount > 0 and (duration is None or duration == 0):
        if historical_avg_monthly_net_savings <= 0:
            return html.P("Your historical average monthly net savings is ₹0.00 or less. Cannot predict time to goal.", className="text-warning")
        
        time_needed_months = target_amount / historical_avg_monthly_net_savings
        
        return html.P(
            f"At your historical average monthly net savings of ₹{historical_avg_monthly_net_savings:,.2f}, "
            f"it will take approximately {time_needed_months:,.1f} months to save ₹{target_amount:,.2f}."
        )

    elif duration is not None and duration > 0 and (target_amount is None or target_amount == 0):
        projected_savings = historical_avg_monthly_net_savings * duration
        return html.P(
            f"At your historical average monthly net savings of ₹{historical_avg_monthly_net_savings:,.2f}, "
            f"you will save approximately ₹{projected_savings:,.2f} in {duration} months."
        )

    elif target_amount is not None and target_amount > 0 and duration is not None and duration > 0:
        monthly_saving_needed = target_amount / duration
        return html.P(
            f"To save ₹{target_amount:,.2f} in {duration} months, you need to save an average of ₹{monthly_saving_needed:,.2f} per month."
        )

    return html.P("Please enter a valid number for Target Amount, Duration, or both.", className="text-danger")

@app.callback(
    [Output('stored-icic-data', 'data'),
     Output('stored-canara-data', 'data'),
     Output('stored-investments-data', 'data'),
     Output('loading-error-message', 'data'),
     Output('data-load-status', 'children')],
    [Input('interval-component', 'n_intervals')]
)
def fetch_and_store_data(n_intervals):
    df_icic, df_canara, df_investments, error_message = load_data_from_google_sheets()

    status_message = ""
    if error_message:
        status_message = html.Div(
            [html.I(className="bi bi-exclamation-triangle-fill me-2"), error_message],
            className="alert alert-danger"
        )
    else:
        status_message = html.Div(
            [html.I(className="bi bi-check-circle-fill me-2"), "Data loaded successfully!"],
            className="alert alert-success"
        )
    
    return (
        df_icic.to_json(orient='split') if not df_icic.empty else None,
        df_canara.to_json(orient='split') if not df_canara.empty else None,
        df_investments.to_json(orient='split') if not df_investments.empty else None,
        error_message,
        status_message
    )


if __name__ == "__main__":
    from waitress import serve
    print("Starting the Dashboard ... Loading data from Google Sheets.")
    
    # You can choose to use 'app.run_server' for local development or 'waitress.serve' for production
    # app.run_server(debug=True, port=8050)
    serve(app.server, host="0.0.0.0", port=int(os.environ.get("PORT", 8050)))