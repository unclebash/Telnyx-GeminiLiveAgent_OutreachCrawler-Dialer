import os
import sqlite3
import re
import urllib.parse
from crawler import crawl_website_for_email
from sheets_client import StandaloneSheetsClient

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "fundraiser.db")
SPREADSHEET_ID = "1TAc4BbIs2mRwI7lJ4HLigdBP-EwcnQlfiXoS5xakenQ"

def main():
    print("🕸️ STARTING BATCH WEBSITE EMAIL CRAWLER...")
    
    # 1. Fetch leads from DB that have a website but no email
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    leads = cursor.execute(
        "SELECT id, name, website, place_id FROM organizations WHERE website IS NOT NULL AND website != '' AND (email IS NULL OR email = '')"
    ).fetchall()
    conn.close()
    
    print(f"[*] Found {len(leads)} organizations with websites but no emails in database.")
    
    if not leads:
        print("ℹ️ No organizations need crawling.")
        return
        
    sheets_client = StandaloneSheetsClient(BASE_DIR)
    sheets_authenticated = sheets_client.is_authenticated()
    
    service = None
    sheet_rows = []
    place_id_idx = None
    email_col_letter = None
    
    if sheets_authenticated:
        service = sheets_client.get_service()
        if service:
            sheet_rows = sheets_client.read_all_rows(SPREADSHEET_ID)
            if sheet_rows:
                headers = [h.strip().lower() for h in sheet_rows[0]]
                # Find Place ID and Email indexes
                for idx, h in enumerate(headers):
                    if "place" in h or "id" in h:
                        place_id_idx = idx
                    if "email" in h:
                        # Convert 0-indexed number to Excel column letter (e.g. 5 -> 'F')
                        email_col_letter = chr(ord('A') + idx)
                        
    print(f"[*] Starting crawl on {len(leads)} sites...")
    
    success_count = 0
    for idx, (lead_id, name, website, place_id) in enumerate(leads):
        print(f"[{idx+1}/{len(leads)}] Crawling '{name}' website: {website}")
        
        email = None
        try:
            email = crawl_website_for_email(website)
        except Exception as e:
            print(f"  ❌ Error crawling {website}: {e}")
            
        if email:
            print(f"  ✅ Discovered email: {email}")
            success_count += 1
            
            # Save to SQLite
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute("UPDATE organizations SET email = ? WHERE id = ?", (email, lead_id))
            conn.commit()
            conn.close()
            
            # Sync to Google Sheets
            if service and sheet_rows and place_id_idx is not None and email_col_letter is not None:
                # Find row index matching place_id
                row_num = -1
                for r_idx, row in enumerate(sheet_rows):
                    if len(row) > place_id_idx and row[place_id_idx].strip() == place_id:
                        row_num = r_idx + 1 # 1-indexed
                        break
                        
                if row_num != -1:
                    try:
                        # Update the specific email cell
                        range_name = f"Sheet1!{email_col_letter}{row_num}"
                        service.spreadsheets().values().update(
                            spreadsheetId=SPREADSHEET_ID,
                            range=range_name,
                            valueInputOption='USER_ENTERED',
                            body={'values': [[email]]}
                        ).execute()
                        print(f"  ✅ Synced email to Google Sheets cell {email_col_letter}{row_num}")
                    except Exception as e:
                        print(f"  ❌ Failed to sync to Google Sheets: {e}")
        else:
            print("  ❌ No email found.")
            
    print(f"🎉 BATCH CRAWL COMPLETE! Found emails for {success_count}/{len(leads)} websites.")

if __name__ == "__main__":
    main()
