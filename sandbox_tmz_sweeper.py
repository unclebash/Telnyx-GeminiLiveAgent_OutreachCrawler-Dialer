import os
import re
import sys
import time
import sqlite3
import urllib.parse
import csv
import requests
from playwright.sync_api import sync_playwright

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LIVE_DB_PATH = os.path.join(BASE_DIR, "fundraiser.db")
SANDBOX_DB_PATH = os.path.join(BASE_DIR, "sandbox_tmz.db")
CSV_PATH = os.path.join(BASE_DIR, "sandbox_tmz_results.csv")

ZIP_CODES = ["90640", "91754", "91755", "90023", "90040", "90660", "91103", "91104"]
CATEGORIES = {
    "Law Office": "law office",
    "Creative Office": "creative agency",
    "Marketing Office": "marketing office",
    "Dental Office": "dental office",
    "Restaurant": "restaurant",
    "Bar": "bar",
    "Accounting/Tax Office": "accounting office",
    "Event Coordinator": "event planner"
}

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
    "jersey mike's", "jersey mikes", "firehouse subs", "quiznos", "red robin", "texas roadhouse", "longhorn steakhouse"
]

EMAIL_REGEX = r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+'
EXCLUDED_EXTENSIONS = ('.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp', '.pdf', '.css', '.js')

def init_sandbox_db():
    conn = sqlite3.connect(SANDBOX_DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sandbox_leads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            phone TEXT,
            city TEXT,
            website TEXT,
            email TEXT,
            place_id TEXT UNIQUE,
            zip_code TEXT,
            category TEXT,
            rating REAL,
            reviews_count INTEGER
        )
    """)
    conn.commit()
    conn.close()

def get_live_api_key():
    if not os.path.exists(LIVE_DB_PATH):
        print(f"Error: Live DB not found at {LIVE_DB_PATH}")
        sys.exit(1)
    conn = sqlite3.connect(LIVE_DB_PATH)
    row = conn.execute("SELECT value FROM system_config WHERE key = ?", ("places_api_key",)).fetchone()
    conn.close()
    return row[0] if row else ""

def is_corporate_chain(name: str) -> bool:
    name_lower = name.lower()
    for chain in CORPORATE_BLACKLIST:
        if chain in name_lower:
            return True
    return False

def extract_city(address: str) -> str:
    if not address:
        return ""
    parts = [p.strip() for p in address.split(",") if p.strip()]
    if not parts:
        return ""
    idx = len(parts) - 1
    if idx >= 0:
        last_part = parts[idx]
        if idx > 0 and (last_part.upper() in ["USA", "US", "UNITED STATES"] or (last_part.isalpha() and len(last_part) <= 4)):
            idx -= 1
    if idx >= 0:
        state_part = parts[idx]
        has_digits = any(c.isdigit() for c in state_part)
        is_state_code = len(state_part) == 2 and state_part.isalpha()
        if idx > 0 and (has_digits or is_state_code):
            idx -= 1
    if idx >= 0:
        return parts[idx]
    return address

def is_valid_business_email(email: str) -> bool:
    email = email.lower().strip()
    if "@" not in email:
        return False
    parts = email.split("@")
    if len(parts) != 2:
        return False
    username, domain = parts[0], parts[1]
    if not username or not domain:
        return False
        
    invalid_domains = {
        "domain.com", "domain.co", "example.com", "yourdomain.com", "yourdomain.co",
        "email.com", "test.com", "abc.com", "placeholder.com", "placeholder.co",
        "gmail.com.png", "gmail.com.jpg"
    }
    if domain in invalid_domains:
        return False
        
    invalid_emails = {
        "email@domain.com", "example@example.com", "user@domain.com", "yourname@yourdomain.com",
        "name@email.com", "xyz@abc.com", "test@test.com", "mail@domain.com", "name@domain.com"
    }
    if email in invalid_emails:
        return False
        
    if "." not in domain or len(domain.split(".")[-1]) < 2:
        return False
        
    return True

def crawl_for_email(url: str) -> str:
    if not url:
        return ""
    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
            page = context.new_page()
            
            emails_found = []
            try:
                page.goto(url, timeout=8000, wait_until="domcontentloaded")
                content = page.content()
                emails_found.extend(re.findall(EMAIL_REGEX, content))
            except Exception:
                browser.close()
                return ""
                
            # Filter and clean
            valid_emails = [e.strip().lower() for e in emails_found if not any(e.lower().endswith(ext) for ext in EXCLUDED_EXTENSIONS)]
            valid_emails = [e for e in valid_emails if is_valid_business_email(e)]
            
            if valid_emails:
                for email in valid_emails:
                    if any(email.startswith(prefix) for prefix in ['info', 'contact', 'hello', 'support', 'office', 'admin']):
                        browser.close()
                        return email
                browser.close()
                return valid_emails[0]
                
            # Check contact/about subpage
            try:
                links = page.locator('a').all()
                contact_link = None
                for link in links:
                    href = link.get_attribute('href')
                    text = link.inner_text().lower()
                    if href:
                        href_lower = href.lower()
                        if 'contact' in href_lower or 'about' in href_lower or 'contact' in text or 'about' in text:
                            contact_link = urllib.parse.urljoin(url, href)
                            break
                            
                if contact_link:
                    page.goto(contact_link, timeout=6000, wait_until="domcontentloaded")
                    content = page.content()
                    sub_emails = re.findall(EMAIL_REGEX, content)
                    valid_emails.extend([e.strip().lower() for e in sub_emails if not any(e.lower().endswith(ext) for ext in EXCLUDED_EXTENSIONS)])
            except Exception:
                pass
                
            browser.close()
            valid_emails = [e for e in valid_emails if is_valid_business_email(e)]
            if valid_emails:
                for email in valid_emails:
                    if any(email.startswith(prefix) for prefix in ['info', 'contact', 'hello', 'support', 'office', 'admin']):
                        return email
                return valid_emails[0]
    except Exception as e:
        print(f"Crawl error for {url}: {e}")
    return ""

def main():
    print("=" * 60)
    print("🚀 STARTING STANDALONE TMZ ZIP CODE HARVESTER SANDBOX")
    print("=" * 60)
    
    api_key = get_live_api_key()
    if not api_key:
        print("Error: Could not retrieve Places API Key from Live database config.")
        sys.exit(1)
        
    init_sandbox_db()
    
    places_url = "https://places.googleapis.com/v1/places:searchText"
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": "places.id,places.displayName,places.formattedAddress,places.rating,places.userRatingCount,places.nationalPhoneNumber,places.websiteUri,nextPageToken"
    }
    
    total_queries = len(ZIP_CODES) * len(CATEGORIES)
    query_count = 0
    leads_saved = 0
    emails_crawled = 0
    corporate_skipped = 0
    
    conn = sqlite3.connect(SANDBOX_DB_PATH)
    
    for zip_code in ZIP_CODES:
        for cat_name, cat_query in CATEGORIES.items():
            query_count += 1
            query_str = f"{cat_query} in {zip_code}"
            print(f"\n[{query_count}/{total_queries}] Sweeping: '{query_str}'...")
            
            payload = {
                "textQuery": query_str
            }
            
            places_list = []
            next_page_token = None
            
            # Fetch Page 1
            try:
                res = requests.post(places_url, headers=headers, json=payload)
                res_data = res.json()
                places_list.extend(res_data.get("places", []))
                next_page_token = res_data.get("nextPageToken")
            except Exception as e:
                print(f"  Error calling Places API: {e}")
                continue
                
            # Fetch Page 2 & 3 (Up to 60 results total)
            page = 1
            while next_page_token and len(places_list) < 60 and page < 3:
                time.sleep(1.5)
                payload["pageToken"] = next_page_token
                try:
                    res = requests.post(places_url, headers=headers, json=payload)
                    res_data = res.json()
                    places_list.extend(res_data.get("places", []))
                    next_page_token = res_data.get("nextPageToken")
                    page += 1
                except Exception:
                    break
                    
            print(f"  Found {len(places_list)} raw Google results.")
            
            for place in places_list:
                name = place.get("displayName", {}).get("text", "")
                place_id = place.get("id", "")
                phone = place.get("nationalPhoneNumber", "")
                address = place.get("formattedAddress", "")
                website = place.get("websiteUri", "")
                rating = place.get("rating", 0.0)
                reviews_count = place.get("userRatingCount", 0)
                
                # Filter 1: Must have phone number
                if not phone:
                    continue
                    
                # Filter 2: Blacklist corporate chains
                if is_corporate_chain(name):
                    corporate_skipped += 1
                    continue
                    
                # Check for duplicates in sandbox
                dup = conn.execute("SELECT id FROM sandbox_leads WHERE place_id = ?", (place_id,)).fetchone()
                if dup:
                    continue
                    
                # Extract city name
                city = extract_city(address)
                
                # Fetch / Crawl email
                email = ""
                if website:
                    print(f"    Crawling {website} for email...")
                    email = crawl_for_email(website)
                    if email:
                        emails_crawled += 1
                        print(f"      ✅ Extracted: {email}")
                    else:
                        print("      ❌ No email found.")
                
                try:
                    conn.execute("""
                        INSERT INTO sandbox_leads (name, phone, city, website, email, place_id, zip_code, category, rating, reviews_count)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (name, phone, city, website, email, place_id, zip_code, cat_name, rating, reviews_count))
                    conn.commit()
                    leads_saved += 1
                    print(f"    💾 Saved: {name} ({city}) | Phone: {phone}")
                except Exception as e:
                    print(f"    Error saving lead: {e}")
                    
    conn.close()
    
    # Export to CSV
    print("\nExporting sandbox results to CSV...")
    try:
        conn = sqlite3.connect(SANDBOX_DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT name, phone, city, website, email, place_id FROM sandbox_leads")
        rows = cursor.fetchall()
        
        with open(CSV_PATH, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(["Company Name", "Phone", "Location", "Status", "Donation Amount", "Notes", "Website", "Email", "Place ID"])
            for row in rows:
                writer.writerow([row[0], row[1], row[2], "Pending", "", "", row[3], row[4], row[5]])
        conn.close()
        print(f"CSV saved successfully: {CSV_PATH}")
    except Exception as e:
        print(f"Failed to export CSV: {e}")
        
    print("\n" + "=" * 60)
    print("📊 SANDBOX RUN SUMMARY")
    print("=" * 60)
    print(f"Total Queries Executed: {query_count}")
    print(f"Corporate Chains Filtered: {corporate_skipped}")
    print(f"Boutique Phone-Valid Leads Saved: {leads_saved}")
    print(f"Emails Successfully Extracted: {emails_crawled}")
    print(f"All results saved in separate database: {SANDBOX_DB_PATH}")
    print("=" * 60)

if __name__ == "__main__":
    main()
