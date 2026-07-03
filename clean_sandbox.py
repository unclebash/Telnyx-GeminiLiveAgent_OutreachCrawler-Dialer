import sqlite3
import csv
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SANDBOX_DB_PATH = os.path.join(BASE_DIR, "sandbox_tmz.db")
CSV_PATH = os.path.join(BASE_DIR, "sandbox_tmz_results_cleaned.csv")
BACKLOG_CSV_PATH = os.path.join(BASE_DIR, "sandbox_tmz_results_backlog.csv")

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
        
    if ".." in domain or ".." in username:
        return False
        
    if "sentry.io" in domain or "ingest" in domain:
        return False
        
    domain_parts = domain.split(".")
    if len(domain_parts) < 2:
        return False
    tld = domain_parts[-1]
    if not tld.isalpha() or len(tld) < 2:
        return False
        
    invalid_domains = {
        "domain.com", "domain.co", "example.com", "yourdomain.com", "yourdomain.co",
        "email.com", "test.com", "abc.com", "placeholder.com", "placeholder.co",
        "yourwebsite.com", "yourwebsite.co", "company.com", "company.co",
        "gargle.com", "mysite.com", "mysite.co"
    }
    if domain in invalid_domains:
        return False
        
    invalid_emails = {
        "email@domain.com", "example@example.com", "user@domain.com", "yourname@yourdomain.com",
        "name@email.com", "xyz@abc.com", "test@test.com", "mail@domain.com", "name@domain.com",
        "patient@mail.com", "you@company.com"
    }
    if email in invalid_emails:
        return False
        
    return True

def clean_database():
    conn = sqlite3.connect(SANDBOX_DB_PATH)
    cursor = conn.cursor()
    
    # Select all details for logs and backlog tracking
    cursor.execute("SELECT id, name, phone, city, website, email, place_id FROM sandbox_leads WHERE email != ''")
    rows = cursor.fetchall()
    
    cleaned_count = 0
    removed_count = 0
    backlog_data = []
    
    for row_id, name, phone, city, website, email, place_id in rows:
        if not is_valid_business_email(email):
            cursor.execute("UPDATE sandbox_leads SET email = '' WHERE id = ?", (row_id,))
            backlog_data.append([name, phone, city, website, email, place_id])
            removed_count += 1
        else:
            cleaned_count += 1
            
    conn.commit()
    
    # Save Backlog CSV
    with open(BACKLOG_CSV_PATH, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(["Company Name", "Phone", "Location", "Website", "Extracted Bad Email", "Place ID"])
        writer.writerows(backlog_data)
    
    # Regenerate Cleaned CSV
    cursor.execute("SELECT name, phone, city, website, email, place_id FROM sandbox_leads")
    all_leads = cursor.fetchall()
    
    with open(CSV_PATH, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(["Company Name", "Phone", "Location", "Status", "Donation Amount", "Notes", "Website", "Email", "Place ID"])
        for lead in all_leads:
            writer.writerow([lead[0], lead[1], lead[2], "Pending", "", "", lead[3], lead[4], lead[5]])
            
    conn.close()
    print(f"Cleaned Database & Rebuilt CSVs.")
    print(f"Removed {removed_count} invalid/placeholder emails (Saved to sandbox_tmz_results_backlog.csv).")
    print(f"Left {cleaned_count} clean, high-quality business emails.")

if __name__ == "__main__":
    clean_database()
