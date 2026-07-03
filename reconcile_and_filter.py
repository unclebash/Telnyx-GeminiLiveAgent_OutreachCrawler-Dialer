import os
import sqlite3
import re
from sheets_client import StandaloneSheetsClient

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "fundraiser.db")
SPREADSHEET_ID = "1TAc4BbIs2mRwI7lJ4HLigdBP-EwcnQlfiXoS5xakenQ"

# Expanded Corporate Blacklist definition from app.py
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

def main():
    print("🧹 STARTING LEAD RECONCILIATION & BLACKLIST FILTERING...")
    
    # 1. Connect to SQLite DB
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Get all organizations
    orgs = cursor.execute("SELECT id, name, place_id FROM organizations").fetchall()
    
    blacklisted_pids = []
    blacklisted_names = []
    
    for oid, name, pid in orgs:
        if is_corporate_chain(name):
            blacklisted_pids.append(pid)
            blacklisted_names.append(name)
            
    print(f"[*] Found {len(blacklisted_names)} corporate chains/invalid leads in local database:")
    for name in blacklisted_names:
        print(f"  - {name}")
        
    if blacklisted_pids:
        # Delete from local SQLite
        placeholders = ",".join(["?"] * len(blacklisted_pids))
        cursor.execute(f"DELETE FROM organizations WHERE place_id IN ({placeholders})", blacklisted_pids)
        conn.commit()
        print(f"✅ Deleted {len(blacklisted_pids)} rows from local SQLite database.")
    else:
        print("ℹ️ No blacklisted leads found in local SQLite database.")
        
    conn.close()
    
    # 2. Sync Google Sheet
    sheets_client = StandaloneSheetsClient(BASE_DIR)
    if not sheets_client.is_authenticated():
        print("❌ Error: StandaloneSheetsClient is not authenticated. Cannot sync Google Sheet.")
        return
        
    service = sheets_client.get_service()
    if not service:
        print("❌ Error: Failed to obtain Google Sheets API service.")
        return
        
    try:
        # Read current sheet
        rows = sheets_client.read_all_rows(SPREADSHEET_ID)
        if not rows:
            print("ℹ️ Google Sheet is empty.")
            return
            
        headers = rows[0]
        # Find Place ID column index
        headers_lower = [h.strip().lower() for h in headers]
        place_id_idx = None
        for idx, h in enumerate(headers_lower):
            if "place" in h or "id" in h:
                place_id_idx = idx
                break
                
        if place_id_idx is None:
            print("❌ Error: Could not find 'Place ID' column in Google Sheet.")
            return
            
        print(f"[*] Parsing Google Sheet (Total rows: {len(rows)})...")
        
        filtered_rows = [headers]
        removed_count = 0
        
        for row in rows[1:]:
            if len(row) > place_id_idx:
                pid = row[place_id_idx].strip()
                name = row[0] if len(row) > 0 else "Unknown"
                
                # Filter out if name is blacklisted or place_id is blacklisted
                if pid in blacklisted_pids or is_corporate_chain(name):
                    removed_count += 1
                    print(f"  [Sheet Pruned] {name} ({pid})")
                    continue
            filtered_rows.append(row)
            
        if removed_count > 0:
            # Clear the sheet first
            service.spreadsheets().values().clear(
                spreadsheetId=SPREADSHEET_ID,
                range="Sheet1!A1:Z1000"
            ).execute()
            
            # Write the updated rows
            body = {'values': filtered_rows}
            service.spreadsheets().values().update(
                spreadsheetId=SPREADSHEET_ID,
                range=f"Sheet1!A1:I{len(filtered_rows)}",
                valueInputOption="USER_ENTERED",
                body=body
            ).execute()
            
            print(f"✅ Successfully pruned {removed_count} rows from Google Sheet.")
        else:
            print("ℹ️ No blacklisted leads found in Google Sheet.")
            
    except Exception as e:
        print(f"❌ Error during Google Sheet reconciliation: {e}")

if __name__ == "__main__":
    main()
