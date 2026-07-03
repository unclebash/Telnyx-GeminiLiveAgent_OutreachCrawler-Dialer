import os
import sqlite3
from sheets_client import StandaloneSheetsClient

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "fundraiser.db")
SPREADSHEET_ID = "1TAc4BbIs2mRwI7lJ4HLigdBP-EwcnQlfiXoS5xakenQ"

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def main():
    print("🔄 STARTING FULL TWO-WAY RECONCILIATION SYNC...")
    
    sheets_client = StandaloneSheetsClient(BASE_DIR)
    if not sheets_client.is_authenticated():
        print("❌ Error: StandaloneSheetsClient is not authenticated.")
        return
        
    service = sheets_client.get_service()
    if not service:
        print("❌ Error: Failed to obtain Google Sheets service.")
        return
        
    # 1. Fetch all rows from Google Sheet
    sheet_rows = sheets_client.read_all_rows(SPREADSHEET_ID)
    if not sheet_rows:
        print("❌ Error: Google Sheet is empty or couldn't be read.")
        return
        
    headers = sheet_rows[0]
    headers_lower = [h.strip().lower() for h in headers]
    
    # Map headers to column indices
    col_map = {h: idx for idx, h in enumerate(headers_lower)}
    place_id_idx = col_map.get("place id")
    name_idx = col_map.get("company name")
    phone_idx = col_map.get("phone")
    location_idx = col_map.get("location")
    status_idx = col_map.get("status")
    donation_idx = col_map.get("donation amount")
    email_idx = col_map.get("email")
    notes_idx = col_map.get("notes")
    website_idx = col_map.get("website")
    
    if place_id_idx is None or name_idx is None:
        print("❌ Error: Spreadsheet headers must contain 'Place ID' and 'Company Name'.")
        return
        
    # Build sheet dataset mapped by Place ID
    sheet_data = {}
    for r_idx, row in enumerate(sheet_rows[1:]):
        if len(row) <= max(place_id_idx, name_idx):
            continue
        pid = row[place_id_idx].strip()
        if not pid:
            continue
            
        sheet_data[pid] = {
            "row_num": r_idx + 2, # 1-indexed, skipping header
            "name": row[name_idx].strip(),
            "phone": row[phone_idx].strip() if phone_idx is not None and len(row) > phone_idx else "",
            "location": row[location_idx].strip() if location_idx is not None and len(row) > location_idx else "",
            "status": row[status_idx].strip() if status_idx is not None and len(row) > status_idx else "Pending",
            "donation_amount": row[donation_idx].strip() if donation_idx is not None and len(row) > donation_idx else "",
            "email": row[email_idx].strip() if email_idx is not None and len(row) > email_idx else "",
            "notes": row[notes_idx].strip() if notes_idx is not None and len(row) > notes_idx else "",
            "website": row[website_idx].strip() if website_idx is not None and len(row) > website_idx else ""
        }
        
    # 2. Fetch all rows from local database
    conn = get_db_connection()
    db_leads = conn.execute("SELECT * FROM organizations").fetchall()
    conn.close()
    
    db_data = {lead["place_id"]: dict(lead) for lead in db_leads if lead["place_id"]}
    
    print(f"[*] Loaded {len(sheet_data)} leads from Google Sheets.")
    print(f"[*] Loaded {len(db_data)} leads from SQLite DB.")
    
    # 3. Reconcile
    missing_in_sheet = [] # Leads in DB but not in Sheet
    missing_in_db = []    # Leads in Sheet but not in DB
    mismatches = []       # Leads in both but with different info
    
    # Check DB leads
    for pid, db_lead in db_data.items():
        if pid not in sheet_data:
            missing_in_sheet.append(db_lead)
        else:
            # Check fields
            s_lead = sheet_data[pid]
            mismatched_fields = {}
            
            # Email (DB has crawler, prioritize DB if sheet is empty)
            if db_lead["email"] and not s_lead["email"]:
                mismatched_fields["email"] = ("db_to_sheet", db_lead["email"])
            elif s_lead["email"] and not db_lead["email"]:
                mismatched_fields["email"] = ("sheet_to_db", s_lead["email"])
                
            # Status (Sheet is updated by dialer/agents, prioritize Sheet)
            if db_lead["status"] != s_lead["status"]:
                mismatched_fields["status"] = ("sheet_to_db", s_lead["status"])
                
            # Notes (Prioritize Sheet)
            if (db_lead["notes"] or "") != s_lead["notes"]:
                mismatched_fields["notes"] = ("sheet_to_db", s_lead["notes"])
                
            # Donation Amount
            if (db_lead["donation_amount"] or "") != s_lead["donation_amount"]:
                mismatched_fields["donation_amount"] = ("sheet_to_db", s_lead["donation_amount"])
                
            if mismatched_fields:
                mismatches.append((pid, mismatched_fields, s_lead["row_num"]))
                
    # Check Sheet leads
    for pid, s_lead in sheet_data.items():
        if pid not in db_data:
            missing_in_db.append(s_lead)
            
    print(f"[*] Sync Analysis:")
    print(f"  - Missing in Google Sheets: {len(missing_in_sheet)}")
    print(f"  - Missing in SQLite DB: {len(missing_in_db)}")
    print(f"  - Field Mismatches (to sync): {len(mismatches)}")
    
    # 4. Resolve Missing in DB (Insert to local SQLite)
    if missing_in_db:
        conn = get_db_connection()
        for s_lead in missing_in_db:
            conn.execute("""
                INSERT INTO organizations (name, place_id, address, phone, website, status, email, notes, donation_amount)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (s_lead["name"], s_lead["place_id"], s_lead["location"], s_lead["phone"], s_lead["website"], s_lead["status"], s_lead["email"], s_lead["notes"], s_lead["donation_amount"]))
        conn.commit()
        conn.close()
        print(f"✅ Imported {len(missing_in_db)} missing leads into local SQLite database.")
        
    # 5. Resolve Missing in Sheets (Append to Google Sheet)
    if missing_in_sheet:
        rows_to_append = []
        for db_lead in missing_in_sheet:
            row_data = ["" for _ in range(len(headers))]
            row_data[name_idx] = db_lead["name"]
            if phone_idx is not None: row_data[phone_idx] = db_lead["phone"] or ""
            if location_idx is not None: row_data[location_idx] = db_lead["address"] or ""
            if status_idx is not None: row_data[status_idx] = db_lead["status"] or "Pending"
            if donation_idx is not None: row_data[donation_idx] = db_lead["donation_amount"] or ""
            if email_idx is not None: row_data[email_idx] = db_lead["email"] or ""
            if notes_idx is not None: row_data[notes_idx] = db_lead["notes"] or ""
            if website_idx is not None: row_data[website_idx] = db_lead["website"] or ""
            if place_id_idx is not None: row_data[place_id_idx] = db_lead["place_id"]
            rows_to_append.append(row_data)
            
        sheets_client.append_rows(SPREADSHEET_ID, rows_to_append)
        print(f"✅ Appended {len(missing_in_sheet)} missing leads to Google Sheet.")
        
    # 6. Sync Field Mismatches
    if mismatches:
        conn = get_db_connection()
        for pid, fields, row_num in mismatches:
            # Sync to local DB
            db_updates = {}
            for field, (direction, val) in fields.items():
                if direction == "sheet_to_db":
                    db_updates[field] = val
                    
            if db_updates:
                set_clause = ", ".join([f"{f} = ?" for f in db_updates.keys()])
                params = list(db_updates.values()) + [pid]
                conn.execute(f"UPDATE organizations SET {set_clause} WHERE place_id = ?", params)
                
            # Sync to Sheets
            for field, (direction, val) in fields.items():
                if direction == "db_to_sheet":
                    col_letter = None
                    if field == "email" and email_idx is not None:
                        col_letter = chr(ord('A') + email_idx)
                    if field == "status" and status_idx is not None:
                        col_letter = chr(ord('A') + status_idx)
                        
                    if col_letter:
                        range_name = f"Sheet1!{col_letter}{row_num}"
                        service.spreadsheets().values().update(
                            spreadsheetId=SPREADSHEET_ID,
                            range=range_name,
                            valueInputOption='USER_ENTERED',
                            body={'values': [[val]]}
                        ).execute()
                        
        conn.commit()
        conn.close()
        print(f"✅ Synced field mismatches across {len(mismatches)} rows.")
        
    print("🎉 TWO-WAY RECONCILIATION SYNC COMPLETED SUCCESSFULLY!")

if __name__ == "__main__":
    main()
