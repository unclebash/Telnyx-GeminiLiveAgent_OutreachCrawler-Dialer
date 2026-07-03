import os
import sqlite3
import requests
import streamlit as nn_st # importing as nn_st to avoid standard streamlit variable conflicts
import pandas as pd
from datetime import datetime
from crawler import crawl_website_for_email
from gmail_sender import StandaloneGmailClient
from sheets_client import StandaloneSheetsClient


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "fundraiser.db")
SCHEMA_PATH = os.path.join(BASE_DIR, "schema.sql")

gmail_client = StandaloneGmailClient(BASE_DIR)
sheets_client = StandaloneSheetsClient(BASE_DIR)

def extract_city(address: str) -> str:
    if not address:
        return ""
    parts = [p.strip() for p in address.split(",") if p.strip()]
    if not parts:
        return ""
    idx = len(parts) - 1
    # 1. Skip country if it's the last element and has no digits
    if idx >= 0:
        last_part = parts[idx]
        if idx > 0 and (last_part.upper() in ["USA", "US", "UNITED STATES"] or (last_part.isalpha() and len(last_part) <= 4)):
            idx -= 1
            
    # 2. Skip state/zip if it has digits or is a 2-letter state
    if idx >= 0:
        state_part = parts[idx]
        has_digits = any(c.isdigit() for c in state_part)
        is_state_code = len(state_part) == 2 and state_part.isalpha()
        if idx > 0 and (has_digits or is_state_code):
            idx -= 1
            
    # 3. Return the city name
    if idx >= 0:
        return parts[idx]
    return address

# Streamlit Page Config
nn_st.set_page_config(
    page_title="Google Places Fundraiser Dialer",
    page_icon="📞",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Initialize Database
def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    if os.path.exists(SCHEMA_PATH):
        with open(SCHEMA_PATH, 'r') as f:
            cursor.executescript(f.read())
            
    # Migration: Add donation_amount if not exists
    try:
        cursor.execute("SELECT donation_amount FROM organizations LIMIT 1")
    except sqlite3.OperationalError:
        cursor.execute("ALTER TABLE organizations ADD COLUMN donation_amount TEXT DEFAULT ''")
        
    # Insert test lead "JET HOLDINGS"
    cursor.execute("""
        INSERT OR IGNORE INTO organizations (name, email, phone, place_id, status)
        VALUES (?, ?, ?, ?, ?)
    """, ("JET HOLDINGS", "judeinvestments@gmail.com", "(555) 555-5555", "ChIJtestjetholdings", "Pending"))
        
    conn.commit()
    conn.close()

init_db()

# DB Helper functions
def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def get_setting(key: str, default: str = "") -> str:
    conn = get_db_connection()
    row = conn.execute("SELECT value FROM system_config WHERE key = ?", (key,)).fetchone()
    conn.close()
    return row['value'] if row else default

def save_setting(key: str, value: str):
    conn = get_db_connection()
    conn.execute("INSERT OR REPLACE INTO system_config (key, value) VALUES (?, ?)", (key, value))
    conn.commit()
    conn.close()

def sync_with_google_sheet(sheet_url: str) -> tuple[bool, str]:
    try:
        # Convert sharing link to export CSV link if needed
        if "/edit" in sheet_url:
            base_url = sheet_url.split("/edit")[0]
            export_url = f"{base_url}/export?format=csv"
        else:
            export_url = sheet_url
            
        df = pd.read_csv(export_url)
        # Normalize column names for robust matching
        df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]
        
        # Support map of friendly columns
        col_mapping = {
            "company_name": "name",
            "location": "address"
        }
        df.rename(columns=col_mapping, inplace=True)
        
        required = ["name", "place_id"]
        if not all(col in df.columns for col in required):
            return False, "Google Sheet must contain at least 'Company Name' (or 'name') and 'Place ID' (or 'place_id') columns."
            
        conn = get_db_connection()
        import_count = 0
        update_count = 0
        
        for _, row in df.iterrows():
            place_id = str(row.get("place_id", ""))
            if not place_id or pd.isna(place_id) or place_id.strip() == "":
                continue
                
            name = str(row.get("name", ""))
            address = str(row.get("address", "")) if "address" in df.columns and not pd.isna(row.get("address")) else ""
            phone = str(row.get("phone", "")) if "phone" in df.columns and not pd.isna(row.get("phone")) else ""
            website = str(row.get("website", "")) if "website" in df.columns and not pd.isna(row.get("website")) else ""
            rating = float(row.get("rating", 0.0)) if "rating" in df.columns and not pd.isna(row.get("rating")) else 0.0
            user_ratings_total = int(row.get("user_ratings_total", 0)) if "user_ratings_total" in df.columns and not pd.isna(row.get("user_ratings_total")) else 0
            status = str(row.get("status", "Pending")) if "status" in df.columns and not pd.isna(row.get("status")) else "Pending"
            email = str(row.get("email", "")) if "email" in df.columns and not pd.isna(row.get("email")) else ""
            notes = str(row.get("notes", "")) if "notes" in df.columns and not pd.isna(row.get("notes")) else ""
            donation_amount = str(row.get("donation_amount", "")) if "donation_amount" in df.columns and not pd.isna(row.get("donation_amount")) else ""
            
            existing = conn.execute("SELECT id FROM organizations WHERE place_id = ?", (place_id,)).fetchone()
            if existing:
                conn.execute("""
                    UPDATE organizations 
                    SET status = ?, notes = ?, email = ?, donation_amount = ?
                    WHERE place_id = ?
                """, (status, notes, email, donation_amount, place_id))
                update_count += 1
            else:
                conn.execute("""
                    INSERT INTO organizations (name, place_id, address, phone, website, rating, user_ratings_total, status, email, notes, donation_amount)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (name, place_id, address, phone, website, rating, user_ratings_total, status, email, notes, donation_amount))
                import_count += 1
                
        conn.commit()
        conn.close()
        return True, f"Imported {import_count} new leads, Updated {update_count} existing leads."
    except Exception as e:
        return False, f"Error: {e}"

def run_two_way_sync():
    sheet_id = get_setting("spreadsheet_id")
    if not sheet_id or not sheets_client.is_authenticated():
        return
        
    try:
        rows = sheets_client.read_all_rows(sheet_id)
        if not rows or len(rows) <= 1:
            return
            
        headers = [h.strip().lower() for h in rows[0]]
        col_map = {h: idx for idx, h in enumerate(headers)}
        
        # Flexibly search for Place ID and Name indexes
        place_id_idx = col_map.get("place id")
        name_idx = col_map.get("company name")
        
        if place_id_idx is None or name_idx is None:
            for idx, h in enumerate(headers):
                if "place" in h or "id" in h:
                    place_id_idx = idx
                if "name" in h or "company" in h:
                    name_idx = idx
                    
        if place_id_idx is None or name_idx is None:
            return
            
        status_idx = col_map.get("status")
        notes_idx = col_map.get("notes")
        phone_idx = col_map.get("phone")
        website_idx = col_map.get("website")
        email_idx = col_map.get("email")
        address_idx = col_map.get("location")
        donation_idx = col_map.get("donation amount")
        
        conn = get_db_connection()
        for row in rows[1:]:
            if len(row) <= max(place_id_idx, name_idx):
                continue
                
            place_id = row[place_id_idx].strip()
            if not place_id or not place_id.startswith("ChI"):
                continue
                
            name = row[name_idx].strip()
            phone = row[phone_idx].strip() if phone_idx is not None and len(row) > phone_idx else ""
            address = row[address_idx].strip() if address_idx is not None and len(row) > address_idx else ""
            website = row[website_idx].strip() if website_idx is not None and len(row) > website_idx else ""
            email = row[email_idx].strip() if email_idx is not None and len(row) > email_idx else ""
            raw_status = row[status_idx].strip() if status_idx is not None and len(row) > status_idx else "Pending"
            status_clean = raw_status.strip().title()
            # Map common variations or typos to valid states
            if status_clean not in ["Pending", "Called", "Donated", "Denied"]:
                lower_status = status_clean.lower()
                if "donat" in lower_status:
                    status_clean = "Donated"
                elif "deny" in lower_status or "denie" in lower_status or "reject" in lower_status:
                    status_clean = "Denied"
                elif "call" in lower_status or "answer" in lower_status or "busy" in lower_status:
                    status_clean = "Called"
                else:
                    status_clean = "Pending"
            status = status_clean
            notes = row[notes_idx].strip() if notes_idx is not None and len(row) > notes_idx else ""
            donation_amount = row[donation_idx].strip() if donation_idx is not None and len(row) > donation_idx else ""
            
            existing = conn.execute("SELECT id FROM organizations WHERE place_id = ?", (place_id,)).fetchone()
            if existing:
                conn.execute("""
                    UPDATE organizations 
                    SET status = ?, notes = ?, email = ?, donation_amount = ?
                    WHERE place_id = ?
                """, (status, notes, email, donation_amount, place_id))
            else:
                conn.execute("""
                    INSERT INTO organizations (name, place_id, address, phone, website, status, email, notes, donation_amount)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (name, place_id, address, phone, website, status, email, notes, donation_amount))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Error during background sheets sync: {e}")

# Run background sync on load
run_two_way_sync()

CORPORATE_BLACKLIST = [
    "applebee's", "applebees", "bj's", "bj’s", "bjs", "mcdonald's", "mcdonalds", "starbucks", "subway", "wendy's", "wendys",
    "burger king", "taco bell", "dunkin", "domino's", "dominos", "pizza hut", "kfc", "chick-fil-a",
    "olive garden", "chili's", "chilis", "red lobster", "outback steakhouse", "panera", "chipotle",
    "buffalo wild wings", "cheesecake factory", "ruth's chris", "walmart", "target", "costco",
    "cvs", "walgreens", "rite aid", "home depot", "lowe's", "lowes", "best buy", "nordstrom",
    "macy's", "macys", "kohl's", "kohls", "t.j. maxx", "tj maxx", "marshalls", "ross dress",
    "starbucks", "dutch bros", "peet's", "7-eleven", "7 eleven", "wawa", "sheetz", "panera bread",
    "sonic drive-in", "sonic drive in", "ihop", "denny's", "dennys", "cracker barrel", "golden corral",
    "panda express", "five guys", "in-n-out", "whataburger", "culver's", "culvers", "jack in the box",
    "hardee's", "hardees", "carl's jr", "carls jr", "popeyes", "arby's", "arbys", "jimmy john's", "jimmy johns",
    "jersey mike's", "jersey mikes", "firehouse subs", "quiznos", "red robin", "texas roadhouse", "longhorn steakhouse",
    "the meltdown", "board & brew", "board and brew", "silverlake ramen", "la monarca", "chevron", "76", "ups store", 
    "ups freight", "fedex", "usps", "united states postal service", "jackson hewitt", "spectrum", "grm document",
    "post office", "iron mountain"
]


def is_corporate_chain(name: str) -> bool:
    name_lower = name.lower()
    for chain in CORPORATE_BLACKLIST:
        if chain in name_lower:
            return True
    return False


# Custom Premium Styling
nn_st.markdown("""
<style>
    /* Premium Earth-toned Light Theme Styling */
    .stApp {
        background-color: #d3d1c5 !important;
        color: #1e1b18 !important;
        font-family: 'Outfit', 'Inter', sans-serif;
    }
    
    /* Force text color for all normal text, paragraphs, lists, and form labels to dark charcoal */
    .stApp p, .stApp span, .stApp label, .stApp li, .stApp div {
        color: #1e1b18 !important;
    }
    
    /* Headers style using the dark olive #7d731c */
    .stApp h1, .stApp h2, .stApp h3, .stApp h4, .stApp h5, .stApp h6 {
        color: #7d731c !important;
        font-weight: 700 !important;
    }
    
    /* Input fields styling: light sand background, dark text, rose border */
    .stApp input, .stApp textarea, .stApp select, .stApp div[role="button"] {
        color: #1e1b18 !important;
        background-color: #e2e0d8 !important;
        border: 1px solid #be8a7c !important;
    }
    
    /* Make link elements look great in dusty rose */
    .stApp a {
        color: #be8a7c !important;
        text-decoration: underline !important;
        font-weight: 600;
    }
    
    /* Metrics panel styling with slightly darker sand background */
    .metric-card {
        background: #c4c1b5 !important;
        border: 1px solid rgba(125, 115, 28, 0.2) !important;
        border-radius: 16px;
        padding: 24px;
        text-align: center;
        box-shadow: 0 4px 15px rgba(0, 0, 0, 0.05);
        transition: transform 0.3s ease, border-color 0.3s ease;
    }
    .metric-card:hover {
        transform: translateY(-3px);
        border-color: #be8a7c !important;
    }
    .metric-value {
        font-size: 2.2rem;
        font-weight: 700;
        color: #7d731c !important;
        margin-bottom: 4px;
    }
    .metric-label {
        font-size: 0.9rem;
        text-transform: uppercase;
        letter-spacing: 1.5px;
        color: #1e1b18 !important;
        font-weight: 600;
    }
    
    /* Beautiful Dialer Display container */
    .dialer-container {
        background: #c4c1b5 !important;
        border: 1px solid rgba(125, 115, 28, 0.15) !important;
        border-radius: 20px;
        padding: 30px;
        box-shadow: 0 8px 25px rgba(0, 0, 0, 0.05);
    }
    
    /* Custom buttons: olive background with light sand text */
    .stButton>button {
        background: linear-gradient(135deg, #7d731c 0%, #be8a7c 100%) !important;
        color: #d3d1c5 !important;
        border: none !important;
        border-radius: 8px !important;
        padding: 10px 24px !important;
        font-weight: 600 !important;
        transition: all 0.2s ease-in-out !important;
        box-shadow: 0 4px 12px rgba(125, 115, 28, 0.2) !important;
    }
    .stButton>button:hover {
        background: linear-gradient(135deg, #be8a7c 0%, #7d731c 100%) !important;
        transform: scale(1.02) !important;
        box-shadow: 0 6px 15px rgba(190, 138, 124, 0.3) !important;
    }
    
    /* Staged Tab selectors */
    button[data-baseweb="tab"] {
        color: #1e1b18 !important;
        font-weight: 600 !important;
    }
    button[aria-selected="true"] {
        color: #7d731c !important;
        border-bottom-color: #7d731c !important;
    }
</style>
""", unsafe_allow_html=True)

# App Sidebar / Settings panel
with nn_st.sidebar:
    nn_st.markdown("<h2 style='color:#7d731c; font-weight:700; margin-bottom: 20px;'>⚙️ App Settings</h2>", unsafe_allow_html=True)
    
    places_key = nn_st.text_input("Google Places API Key", value=get_setting("places_api_key"), type="password")
    if places_key:
        save_setting("places_api_key", places_key)
        
    nn_st.markdown("---")
    
    # Gmail API Authentication Status
    nn_st.markdown("<h3 style='color:#f3f4f6;'>✉️ Gmail Connection</h3>", unsafe_allow_html=True)
    gmail_client = StandaloneGmailClient(BASE_DIR)
    
    if not gmail_client.is_configured():
        nn_st.info("To enable email sending, place `gmail_credentials.json` inside: `" + BASE_DIR + "/`")
    else:
        if gmail_client.is_authenticated():
            sender_email = gmail_client.get_sender_email()
            nn_st.success(f"Connected: {sender_email}")
        else:
            nn_st.warning("Gmail connection required.")
            if nn_st.button("🔗 Authenticate with Gmail"):
                if gmail_client.authenticate_interactive():
                    nn_st.success("Successfully authenticated!")
                    nn_st.rerun()
                else:
                    nn_st.error("Authentication failed. Make sure your credentials are valid and you authorized the app.")

    nn_st.markdown("---")
    
    # Google Sheets Integration Status
    nn_st.markdown("<h3 style='color:#f3f4f6;'>📊 Google Sheets Connection</h3>", unsafe_allow_html=True)
    sheets_client = StandaloneSheetsClient(BASE_DIR)
    
    sheet_id = nn_st.text_input("Google Spreadsheet ID", value=get_setting("spreadsheet_id"), placeholder="e.g. 1a2b3c4d5e...")
    if sheet_id:
        save_setting("spreadsheet_id", sheet_id)
        
    if not sheets_client.is_configured():
        nn_st.info("Place `gmail_credentials.json` in the folder to enable sheets sync.")
    else:
        if sheets_client.is_authenticated():
            nn_st.success("Sheets Connection: Connected")
            if sheet_id:
                if nn_st.button("🛠️ Initialize Column Headers"):
                    if sheets_client.create_headers_if_empty(sheet_id):
                        nn_st.success("Headers checked and updated!")
                    else:
                        nn_st.error("Failed to initialize headers. Double check Spreadsheet ID.")
                if nn_st.button("📤 Push Local Leads to Sheet"):
                    with nn_st.spinner("Syncing local database to Google Sheet..."):
                        # Read all rows from sheet first to prevent duplicates
                        existing_rows = sheets_client.read_all_rows(sheet_id)
                        # Scan all cells in each row for any Place ID (Google Place IDs always start with 'ChI')
                        existing_ids = {cell.strip() for row in existing_rows if row for cell in row if isinstance(cell, str) and cell.strip().startswith("ChI")}
                        
                        conn = get_db_connection()
                        local_leads = conn.execute("SELECT * FROM organizations").fetchall()
                        conn.close()
                        
                        rows_to_push = []
                        for lead in local_leads:
                            phone = lead["phone"]
                            if not phone or not phone.strip():
                                continue
                            if lead["place_id"] not in existing_ids:
                                rows_to_push.append([
                                    lead["name"],
                                    lead["phone"] or "",
                                    extract_city(lead["address"]),
                                    lead["status"] or "Pending",
                                    "", # Donation Amount
                                    lead["notes"] or "",
                                    lead["website"] or "",
                                    lead["email"] or "",
                                    lead["place_id"]
                                ])
                        if rows_to_push:
                            sheets_client.append_rows(sheet_id, rows_to_push)
                        sheets_client.apply_status_dropdown(sheet_id)
                        nn_st.success(f"Pushed {len(rows_to_push)} leads to Google Sheet!")
        else:
            nn_st.warning("Sheets connection required.")
            if nn_st.button("🔗 Authenticate Google Sheets"):
                if sheets_client.authenticate_interactive():
                    nn_st.success("Successfully authenticated Sheets!")
                    nn_st.rerun()
                else:
                    nn_st.error("Sheets authentication failed.")

# Main Application Tabs
tabs = nn_st.tabs(["🔍 Lead Harvesting", "📞 Outbound Queue", "✉️ Email Outreach", "👥 Referrals & Stats"])

# =========================================================================
# TAB 1: LEAD HARVESTING
# =========================================================================
with tabs[0]:
    nn_st.markdown("<h2 style='color:#7d731c;'>🔍 Google Places Lead Harvesting</h2>", unsafe_allow_html=True)
    nn_st.write("Harvest targeted lists of businesses using Google Places API and crawl their web pages to find outreach email addresses automatically.")
    
    col1, col2, col3 = nn_st.columns([2, 1, 1])
    with col1:
        search_query = nn_st.text_input("Search Query", placeholder="e.g., nonprofits, software companies, dental clinics")
    with col2:
        search_location = nn_st.text_input("Location (Optional)", placeholder="e.g., Austin, TX or California")
    with col3:
        search_radius = nn_st.number_input("Radius in miles (Optional)", min_value=1, max_value=100, value=10, step=1)
        
    if nn_st.button("🚀 Harvest Leads"):
        api_key = get_setting("places_api_key")
        if not api_key:
            nn_st.error("Please add your Google Places API Key in the sidebar settings.")
        elif not search_query:
            nn_st.warning("Please provide a search query.")
        else:
            # Places API (New) Text Search
            places_url = "https://places.googleapis.com/v1/places:searchText"
            query_str = f"{search_query} in {search_location}" if search_location else search_query
            
            headers = {
                "Content-Type": "application/json",
                "X-Goog-Api-Key": api_key,
                "X-Goog-FieldMask": "places.id,places.displayName,places.formattedAddress,places.rating,places.userRatingCount,places.nationalPhoneNumber,places.websiteUri,nextPageToken"
            }
            payload = {
                "textQuery": query_str
            }
            
            places_list = []
            next_page_token = None
            
            with nn_st.spinner(f"Querying Google Places (New) for '{query_str}'..."):
                try:
                    # Page 1
                    res = requests.post(places_url, headers=headers, json=payload)
                    res_data = res.json()
                    places_list.extend(res_data.get("places", []))
                    next_page_token = res_data.get("nextPageToken")
                    
                    # Page 2 & 3 (Fetch up to 60 total to meet 50+ request)
                    import time
                    page = 1
                    while next_page_token and len(places_list) < 50 and page < 3:
                        time.sleep(1.5) # Wait for page token to activate
                        payload["pageToken"] = next_page_token
                        res = requests.post(places_url, headers=headers, json=payload)
                        res_data = res.json()
                        places_list.extend(res_data.get("places", []))
                        next_page_token = res_data.get("nextPageToken")
                        page += 1
                except Exception as e:
                    nn_st.error(f"Failed to query Google Places: {e}")
                    
            if not places_list:
                error_msg = res_data.get("error", {}).get("message", "No businesses found matching this query.")
                nn_st.warning(f"Search status: {error_msg}")
            else:
                nn_st.success(f"Discovered {len(places_list)} potential targets. Filtering chains & importing...")
                
                progress_bar = nn_st.progress(0)
                status_text = nn_st.empty()
                
                conn = get_db_connection()
                
                for idx, place in enumerate(places_list):
                    place_id = place.get("id")
                    display_name_obj = place.get("displayName", {})
                    name = display_name_obj.get("text", "Unknown Name")
                    
                    status_text.text(f"Processing ({idx+1}/{len(places_list)}): {name}")
                    
                    # 1. Filter out corporate chains
                    if is_corporate_chain(name):
                        progress_bar.progress((idx + 1) / len(places_list))
                        continue
                        
                    # 2. Check if already exists
                    existing = conn.execute("SELECT id FROM organizations WHERE place_id = ?", (place_id,)).fetchone()
                    if existing:
                        progress_bar.progress((idx + 1) / len(places_list))
                        continue
                        
                    phone = place.get("nationalPhoneNumber", "")
                    website = place.get("websiteUri", "")
                    address = place.get("formattedAddress", "")
                    rating = place.get("rating", 0.0)
                    user_ratings_total = place.get("userRatingCount", 0)
                        
                    # Crawl website for email if website exists
                    email = ""
                    if website:
                        try:
                            email = crawl_website_for_email(website)
                        except Exception as e:
                            print(f"Error crawling website {website}: {e}")
                            
                    # Save to DB
                    conn.execute("""
                        INSERT INTO organizations (name, place_id, address, phone, website, rating, user_ratings_total, email)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """, (name, place_id, address, phone, website, rating, user_ratings_total, email))
                    conn.commit()
                    
                    # Save to Google Sheets if connected and has phone
                    if sheet_id and sheets_client.is_authenticated():
                        if phone and phone.strip():
                            try:
                                sheets_client.append_row(sheet_id, [
                                    name,
                                    phone,
                                    extract_city(address),
                                    'Pending',
                                    '', # Donation Amount
                                    '', # Notes
                                    website,
                                    email,
                                    place_id
                                ])
                            except Exception as e:
                                print(f"Error syncing with Google Sheets: {e}")
                    
                    progress_bar.progress((idx + 1) / len(places_list))
                    
                conn.close()
                status_text.text("Harvesting completed!")
                nn_st.success("All new leads imported successfully and websites queued for extraction.")

# =========================================================================
# TAB 2: OUTBOUND QUEUE DIALER
# =========================================================================
with tabs[1]:
    nn_st.markdown("<h2 style='color:#7d731c;'>📞 Outbound Calling Console</h2>", unsafe_allow_html=True)
    
    def update_lead_status_and_sheets(lead_id, place_id, status, notes):
        conn = get_db_connection()
        conn.execute("UPDATE organizations SET status = ?, notes = ? WHERE id = ?", (status, notes, lead_id))
        conn.commit()
        conn.close()
        if sheet_id and sheets_client.is_authenticated():
            try:
                sheets_client.update_status_and_notes(sheet_id, place_id, status, notes)
            except Exception as e:
                print(f"Error syncing status with Google Sheets: {e}")
    
    conn = get_db_connection()
    leads = conn.execute("""
        SELECT * FROM organizations 
        WHERE status IN ('Pending', 'Called') 
        ORDER BY status DESC, rating DESC
    """).fetchall()
    conn.close()
    
    if not leads:
        nn_st.info("No leads currently in the dialing queue. Go harvest some leads first!")
    else:
        # Save indices in session state to handle queue loop
        if 'dialer_index' not in nn_st.session_state or nn_st.session_state.dialer_index >= len(leads):
            nn_st.session_state.dialer_index = 0
            
        current_lead = leads[nn_st.session_state.dialer_index]
        
        col_queue, col_details = nn_st.columns([1, 2])
        
        with col_queue:
            nn_st.markdown("### Queue List")
            for idx, lead in enumerate(leads):
                is_current = (idx == nn_st.session_state.dialer_index)
                prefix = "▶️ " if is_current else "🔘 "
                label = f"{prefix}{lead['name']} ({lead['rating'] or 'N/A'}⭐)"
                if nn_st.button(label, key=f"select_lead_{lead['id']}", use_container_width=True):
                    nn_st.session_state.dialer_index = idx
                    nn_st.rerun()
                
        with col_details:
            nn_st.markdown(f"<div class='dialer-container'>", unsafe_allow_html=True)
            nn_st.markdown(f"<h2 style='color:#be8a7c; margin-top:0;'>{current_lead['name']}</h2>", unsafe_allow_html=True)
            
            # Sub-details columns
            c1, c2, c3 = nn_st.columns(3)
            with c1:
                nn_st.markdown(f"**📞 Phone:** `{current_lead['phone'] or 'Unavailable'}`")
            with c2:
                if current_lead['website']:
                    nn_st.markdown(f"**🌐 Website:** [Visit Site]({current_lead['website']})")
                else:
                    nn_st.markdown("**🌐 Website:** `None`")
            with c3:
                nn_st.markdown(f"**✉️ Email:** `{current_lead['email'] or 'Not Found'}`")
                
            # Fetch donation_amount if present
            donation_val = ""
            try:
                donation_val = current_lead['donation_amount']
            except Exception:
                pass
                
            nn_st.markdown(f"**📍 Address:** {current_lead['address']}")
            nn_st.markdown(f"**⭐ Google Rating:** {current_lead['rating']} ({current_lead['user_ratings_total']} reviews)")
            if donation_val:
                nn_st.markdown(f"**💰 Donation Amount:** `{donation_val}`")
            nn_st.markdown(f"**📧 Intro Email Sent:** {'✅ Yes' if current_lead['intro_email_sent'] else '❌ No'}")
            
            nn_st.markdown("---")
            
            # Interactive Pitching Script
            nn_st.markdown("### 🗣️ Smart Calling Script Assistant")
            script_template = f"""
            "Hi, is this the program director or coordinator at {current_lead['name']}? 
            My name is [Your Name], and I'm calling from [Nonprofit Name]. We noticed your amazing rating of {current_lead['rating']} on Google and your commitment to community service. 
            We're currently hosting a fundraiser to support local outreach programs, and we'd love to partner or see if you would be open to supporting our cause with a donation."
            """
            nn_st.info(script_template)
            
            # Disposition Logic Form
            nn_st.markdown("### 📋 Log Call Outcome")
            call_notes = nn_st.text_area("Call Notes", placeholder="Write details about the call outcome...")
            
            # Referrals fields if Referral disposition is clicked
            add_referral = nn_st.checkbox("Log Referral Contact details?")
            ref_name, ref_email, ref_phone = "", "", ""
            if add_referral:
                rc1, rc2, rc3 = nn_st.columns(3)
                with rc1:
                    ref_name = nn_st.text_input("Referral Contact Name")
                with rc2:
                    ref_email = nn_st.text_input("Referral Email")
                with rc3:
                    ref_phone = nn_st.text_input("Referral Phone")
                    
            # Outcome Action buttons
            b1, b2, b3, b4 = nn_st.columns(4)
            
            with b1:
                if nn_st.button("No Answer / Busy", key="btn_busy"):
                    conn = get_db_connection()
                    conn.execute("INSERT INTO outbound_calls (organization_id, outcome, notes) VALUES (?, ?, ?)", 
                                 (current_lead['id'], 'busy/no_answer', call_notes))
                    conn.commit()
                    conn.close()
                    # Update status in local DB and Sheets
                    update_lead_status_and_sheets(current_lead['id'], current_lead['place_id'], 'Called', call_notes)
                    # Loop index to next item or circle back
                    nn_st.session_state.dialer_index = (nn_st.session_state.dialer_index + 1) % len(leads)
                    nn_st.success("Logged Busy/No Answer. Queued to bottom.")
                    nn_st.rerun()
                    
            with b2:
                if nn_st.button("🎉 Donated", key="btn_donated"):
                    conn = get_db_connection()
                    conn.execute("INSERT INTO outbound_calls (organization_id, outcome, notes) VALUES (?, ?, ?)", 
                                 (current_lead['id'], 'donated', call_notes))
                    conn.commit()
                    conn.close()
                    # Update status in local DB and Sheets
                    update_lead_status_and_sheets(current_lead['id'], current_lead['place_id'], 'Donated', call_notes)
                    nn_st.success("Fantastic! Registered donation.")
                    nn_st.session_state.dialer_index = max(0, nn_st.session_state.dialer_index - 1)
                    nn_st.rerun()
                    
            with b3:
                if nn_st.button("❌ Denied / Remove", key="btn_denied"):
                    conn = get_db_connection()
                    conn.execute("INSERT INTO outbound_calls (organization_id, outcome, notes) VALUES (?, ?, ?)", 
                                 (current_lead['id'], 'denied', call_notes))
                    conn.commit()
                    conn.close()
                    # Update status in local DB and Sheets
                    update_lead_status_and_sheets(current_lead['id'], current_lead['place_id'], 'Denied', call_notes)
                    nn_st.success("Removed from Queue.")
                    nn_st.session_state.dialer_index = max(0, nn_st.session_state.dialer_index - 1)
                    nn_st.rerun()
                    
            with b4:
                if nn_st.button("👥 Referred", key="btn_referred"):
                    conn = get_db_connection()
                    conn.execute("INSERT INTO outbound_calls (organization_id, outcome, notes) VALUES (?, ?, ?)", 
                                 (current_lead['id'], 'referred', call_notes))
                    if ref_name or ref_email or ref_phone:
                        conn.execute("INSERT INTO referrals (original_org_id, contact_name, contact_email, contact_phone) VALUES (?, ?, ?, ?)",
                                     (current_lead['id'], ref_name, ref_email, ref_phone))
                    conn.commit()
                    conn.close()
                    # Update status in local DB and Sheets
                    update_lead_status_and_sheets(current_lead['id'], current_lead['place_id'], 'Called', call_notes)
                    nn_st.success("Logged referral contact and updated lead.")
                    nn_st.session_state.dialer_index = (nn_st.session_state.dialer_index + 1) % len(leads)
                    nn_st.rerun()
            
            nn_st.markdown(f"</div>", unsafe_allow_html=True)

# =========================================================================
# TAB 3: EMAIL OUTREACH
# =========================================================================
with tabs[2]:
    nn_st.markdown("<h2 style='color:#7d731c;'>✉️ Automated Email Outreach</h2>", unsafe_allow_html=True)
    
    conn = get_db_connection()
    email_leads = conn.execute("""
        SELECT * FROM organizations 
        WHERE email IS NOT NULL AND email != '' AND intro_email_sent = 0
    """).fetchall()
    conn.close()
    
    if not email_leads:
        nn_st.info("No outreach emails to send. Verify that you have crawled emails or that they aren't already sent.")
    else:
        nn_st.write(f"You have **{len(email_leads)}** leads with contact emails ready for introductory outreach.")
        
        # Email Template Customizer
        subject_template = nn_st.text_input("Subject Line Template", value="[COMPANY NAME] | Outreach to Help 501c3 - Keeping People Employed")
        body_template = nn_st.text_area("Email Body Template", value="""<div style="max-width: 600px; margin: 0 auto; background-color: #ffffff; font-family: Arial, sans-serif; line-height: 1.6; color: #222222; padding: 10px; display: block; clear: both;">
  
  <div style="text-align: center; margin-bottom: 25px; display: block;">
    <img src="https://static.wixstatic.com/media/375a01_fe7d52b289bb479e996823ad53ebeade~mv2.png" alt="SocialSolidarity Banner" style="display: block; width: 100%; max-width: 600px; height: auto; border: 0; margin: 0 auto;" />
  </div>

  <div style="text-align: left; margin-bottom: 30px; display: block;">
    <h1 style="margin: 0 0 16px 0; font-weight: bold; font-size: 24px; color: #D22630; font-family: Arial, sans-serif;">Hello Neighbor!</h1>
    
    <p style="margin: 0 0 16px 0;">As locals born and raised right here in the area, we are reaching out directly to our fellow neighborhood businesses. For the past six years, <strong>SocialSolidarity</strong> has operated with absolute dedication and self-reliance. Funded entirely by our founding director and a core group of local corporate sponsors, we have proudly built an operational model that is highly efficient, robust, and sustainable.</p>
    
    <p style="margin: 0 0 16px 0;">During this time, our focus has been entirely on workforce development. We have successfully moved hundreds of recently rehabilitated individuals back into productive, long-term careers through our intensive <strong>Upskilling Initiatives</strong>, specialized <strong>Food Truck Technical Training</strong>, and rigorous <strong>Entrepreneurial Development</strong> programs—backed by direct job placement pipelines into our local economy.</p>
    
    <p style="margin: 0 0 16px 0;">Unfortunately, the harsh economic realities of recent months have caught up to us. We are currently facing an immediate, unexpected budget shortfall that threatens to force a complete operational shutdown <strong style="color: #D22630;">in the middle of active training cohorts</strong>.</p>
    
    <p style="margin: 0 0 24px 0;">We refuse to abandon our participants mid-stream and stall their professional re-entry. We are looking for local business leaders in our community to step up and partner with us. A direct sponsorship of <strong>$200</strong> keeps our educational tracks open, our professional instruction running, and our neighborhood’s job placement momentum alive.</p>
  </div>

  <div style="margin-bottom: 5px; text-align: center; display: block; width: 100%;">
    <div style="margin-bottom: 8px; display: block;">
      <img src="https://static.wixstatic.com/media/375a01_c3e666b72d01446092ec59e3c38fa333~mv2.png" alt="" style="display: inline-block; width: 45%; max-width: 108px; height: auto; border: 0; vertical-align: middle; margin: 0 4px;" />
      <img src="https://static.wixstatic.com/media/375a01_e38d5e67e8f44e39b6ea479408daf8fa~mv2.jpg" alt="Cohort Training Component" style="display: inline-block; width: 45%; max-width: 192px; height: auto; border: 0; border-radius: 4px; vertical-align: middle; margin: 0 4px;" />
    </div>
    <div style="display: block;">
      <img src="https://static.wixstatic.com/media/375a01_7e85af27e7874a169a6bb9963dc19fa4~mv2.jpg" alt="Food Truck Mechanics" style="display: inline-block; width: 45%; max-width: 192px; height: auto; border: 0; border-radius: 4px; vertical-align: middle; margin: 0 4px;" />
      <img src="https://static.wixstatic.com/media/375a01_4b6f495acdd04715a6de0a7c9d7c8334~mv2.png" alt="" style="display: inline-block; width: 45%; max-width: 108px; height: auto; border: 0; vertical-align: middle; margin: 0 4px;" />
    </div>
  </div>

  <div style="text-align: center; padding: 8px 0 35px 0; font-size: 13px; color: #666666; font-style: italic; display: block;">
    SocialSolidarity Food Truck Cohort in Action
  </div>

  <div style="text-align: center; margin-bottom: 40px; display: block; clear: both;">
    <div style="display: inline-block; background-color: #D22630; border-radius: 4px;">
      <a href="https://www.paypal.com/ncp/payment/WNHBNMHTDVHW4" target="_blank" style="font-size: 16px; font-weight: bold; color: #ffffff; text-decoration: none; padding: 16px 35px; display: inline-block; border-radius: 4px; border: 1px solid #D22630; letter-spacing: 0.5px; font-family: Arial, sans-serif;">Sponsor a Participant for $200</a>
    </div>
    <p style="margin: 15px 0 0 0; font-size: 14px; color: #666666; font-family: Arial, sans-serif;">
      Or <a href="https://www.paypal.com/ncp/payment/WNHBNMHTDVHW4" target="_blank" style="color: #D22630; text-decoration: underline;">Donate What You Can</a> to support our training tracks.
    </p>
  </div>

  <div style="border-top: 1px solid #eeeeee; padding-top: 25px; text-align: left; display: block; clear: both;">
    <div style="display: inline-block; width: 65%; vertical-align: middle;">
      <p style="margin: 0 0 4px 0; font-weight: bold; color: #D22630; font-family: Arial, sans-serif;">Thank you for your solidarity,</p>
      <p style="margin: 0; font-size: 15px; color: #555555; font-family: Arial, sans-serif;">The SocialSolidarity Leadership Team</p>
    </div><div style="display: inline-block; width: 30%; text-align: right; vertical-align: middle;">
      <img src="https://static.wixstatic.com/media/375a01_2ff3a71a887843088ae98b298d0e80bd~mv2.png" alt="SocialSolidarity Badge" style="display: inline-block; width: 80px; height: auto; border: 0;" />
    </div>
  </div>

</div>""", height=350)
        
        # Staging & Sending Table
        lead_data = []
        for lead in email_leads:
            rendered_subject = subject_template.replace("{name}", lead["name"]).replace("[COMPANY NAME]", lead["name"])
            rendered_body = body_template.replace("{name}", lead["name"]).replace("[COMPANY NAME]", lead["name"])
            lead_data.append({
                "ID": lead["id"],
                "Business Name": lead["name"],
                "Email": lead["email"],
                "Subject": rendered_subject,
                "Body": rendered_body
            })
            
        df = pd.DataFrame(lead_data)
        nn_st.dataframe(df[["Business Name", "Email", "Subject"]])
        
        action_col1, action_col2 = nn_st.columns(2)
        
        with action_col1:
            if nn_st.button("✉️ Send Emails Directly via Gmail"):
                if not gmail_client.is_authenticated():
                    nn_st.error("Please connect Gmail in the sidebar first.")
                else:
                    success_count = 0
                    progress = nn_st.progress(0)
                    conn = get_db_connection()
                    for idx, item in enumerate(lead_data):
                        sent = gmail_client.send_email(item["Email"], item["Subject"], item["Body"], is_html=True)
                        if sent:
                            conn.execute("UPDATE organizations SET intro_email_sent = 1 WHERE id = ?", (item["ID"],))
                            conn.commit()
                            success_count += 1
                        progress.progress((idx + 1) / len(lead_data))
                    conn.close()
                    nn_st.success(f"Successfully sent {success_count} emails directly!")
                    nn_st.rerun()
                    
        with action_col2:
            if nn_st.button("✍️ Create Drafts in Gmail"):
                if not gmail_client.is_authenticated():
                    nn_st.error("Please connect Gmail in the sidebar first.")
                else:
                    success_count = 0
                    progress = nn_st.progress(0)
                    conn = get_db_connection()
                    for idx, item in enumerate(lead_data):
                        drafted = gmail_client.create_draft(item["Email"], item["Subject"], item["Body"], is_html=True)
                        if drafted:
                            conn.execute("UPDATE organizations SET intro_email_sent = 1 WHERE id = ?", (item["ID"],))
                            conn.commit()
                            success_count += 1
                        progress.progress((idx + 1) / len(lead_data))
                    conn.close()
                    nn_st.success(f"Successfully generated {success_count} drafts inside your Gmail account!")
                    nn_st.rerun()

# =========================================================================
# TAB 4: REFERRALS & STATS
# =========================================================================
with tabs[3]:
    nn_st.markdown("<h2 style='color:#7d731c;'>📊 Analytics Dashboard & Referrals</h2>", unsafe_allow_html=True)
    
    conn = get_db_connection()
    total_leads = conn.execute("SELECT COUNT(*) FROM organizations").fetchone()[0]
    total_emails = conn.execute("SELECT COUNT(*) FROM organizations WHERE intro_email_sent = 1").fetchone()[0]
    total_calls = conn.execute("SELECT COUNT(*) FROM outbound_calls").fetchone()[0]
    total_donations = conn.execute("SELECT COUNT(*) FROM organizations WHERE status = 'Donated'").fetchone()[0]
    
    referrals_list = conn.execute("""
        SELECT r.*, o.name as original_org_name 
        FROM referrals r 
        LEFT JOIN organizations o ON r.original_org_id = o.id
    """).fetchall()
    
    conn.close()
    
    # KPI Grid
    kpi1, kpi2, kpi3, kpi4 = nn_st.columns(4)
    with kpi1:
        nn_st.markdown(f"""
        <div class='metric-card'>
            <div class='metric-value'>{total_leads}</div>
            <div class='metric-label'>Total Leads</div>
        </div>
        """, unsafe_allow_html=True)
    with kpi2:
        nn_st.markdown(f"""
        <div class='metric-card'>
            <div class='metric-value'>{total_calls}</div>
            <div class='metric-label'>Calls Placed</div>
        </div>
        """, unsafe_allow_html=True)
    with kpi3:
        nn_st.markdown(f"""
        <div class='metric-card'>
            <div class='metric-value'>{total_emails}</div>
            <div class='metric-label'>Emails Sent</div>
        </div>
        """, unsafe_allow_html=True)
    with kpi4:
        nn_st.markdown(f"""
        <div class='metric-card'>
            <div class='metric-value'>{total_donations}</div>
            <div class='metric-label'>Conversions (Donated)</div>
        </div>
        """, unsafe_allow_html=True)
        
    nn_st.markdown("---")
    
    # Referrals Management Queue
    nn_st.markdown("### 👥 Referred Contacts (Secondary Outreach Queue)")
    if not referrals_list:
        nn_st.info("No referred contacts logged yet.")
    else:
        ref_data = []
        for ref in referrals_list:
            ref_data.append({
                "Referred Lead ID": ref["id"],
                "Source business": ref["original_org_name"],
                "Contact Name": ref["contact_name"],
                "Contact Email": ref["contact_email"],
                "Contact Phone": ref["contact_phone"],
                "Status": ref["status"],
                "Logged At": ref["created_at"]
            })
        df_ref = pd.DataFrame(ref_data)
        nn_st.dataframe(df_ref)
        
        # Quick actions to update referral status
        nn_st.markdown("#### Update Referral Status")
        ref_id_to_update = nn_st.selectbox("Select Referral Contact", options=[r["id"] for r in referrals_list], format_func=lambda x: next(r["contact_name"] for r in referrals_list if r["id"] == x))
        new_status = nn_st.selectbox("New Status", ["Pending", "Contacted", "Denied", "Donated"])
        
        if nn_st.button("Update Referral"):
            conn = get_db_connection()
            conn.execute("UPDATE referrals SET status = ? WHERE id = ?", (new_status, ref_id_to_update))
            conn.commit()
            conn.close()
            nn_st.success("Referral status updated!")
            nn_st.rerun()

    nn_st.markdown("---")
    nn_st.markdown("### 🔗 Google Sheets Sync & CSV Operations")
    
    col_sync, col_csv = nn_st.columns(2)
    
    with col_sync:
        nn_st.markdown("#### Sync from Google Sheet")
        sheet_url = nn_st.text_input("Paste Google Sheet Share/CSV URL", 
                                     placeholder="https://docs.google.com/spreadsheets/d/your-id/edit")
        if nn_st.button("🔄 Sync with Google Sheet"):
            if not sheet_url:
                nn_st.warning("Please provide a valid Google Sheet URL.")
            else:
                with nn_st.spinner("Syncing leads..."):
                    success, msg = sync_with_google_sheet(sheet_url)
                    if success:
                        nn_st.success(msg)
                        nn_st.rerun()
                    else:
                        nn_st.error(msg)
                        
    with col_csv:
        nn_st.markdown("#### Export Leads to CSV")
        # Load all leads
        conn = get_db_connection()
        df_leads = pd.read_sql_query("SELECT * FROM organizations", conn)
        conn.close()
        
        if df_leads.empty:
            nn_st.info("No leads available to export.")
        else:
            csv_data = df_leads.to_csv(index=False).encode('utf-8')
            nn_st.download_button(
                label="📥 Download Master Leads CSV",
                data=csv_data,
                file_name="master_leads_fundraiser.csv",
                mime="text/csv",
                use_container_width=True
            )
            nn_st.info("💡 Tip: Upload this CSV to Google Sheets to share with your fundraising team!")
