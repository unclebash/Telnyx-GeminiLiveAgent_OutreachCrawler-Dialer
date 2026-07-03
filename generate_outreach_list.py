import os
import csv

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CLEANED_CSV_PATH = os.path.join(BASE_DIR, "sandbox_tmz_results_cleaned.csv")
BOUNCES_TXT_PATH = os.path.join(BASE_DIR, "bounces.txt")
OUTPUT_CSV_PATH = os.path.join(BASE_DIR, "sandbox_tmz_nonbounced_calls.csv")

def main():
    print("=" * 60)
    print("📋 GENERATING NON-BOUNCED EMAIL DIALER LIST")
    print("=" * 60)

    # 1. Read Bounces list
    bounced_emails = set()
    if os.path.exists(BOUNCES_TXT_PATH):
        with open(BOUNCES_TXT_PATH, "r", encoding="utf-8") as f:
            for line in f:
                email = line.strip().lower()
                if email:
                    bounced_emails.add(email)
        print(f"Loaded {len(bounced_emails)} bounced emails from bounces.txt.")
    else:
        # Create empty bounces.txt so user can paste into it
        with open(BOUNCES_TXT_PATH, "w", encoding="utf-8") as f:
            f.write("# Paste your bounced emails here, one per line\n")
        print(f"Created empty bounces.txt at {BOUNCES_TXT_PATH}.")
        print("Please open bounces.txt, paste the bounced emails from your inbox, and run this script again.")
        return

    if not os.path.exists(CLEANED_CSV_PATH):
        print(f"Error: Source cleaned CSV not found at {CLEANED_CSV_PATH}")
        return

    # 2. Filter leads
    non_bounced_leads = []
    skipped_bounced = 0
    skipped_no_email = 0
    skipped_no_phone = 0

    with open(CLEANED_CSV_PATH, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            email = row.get("Email", "").strip().lower()
            phone = row.get("Phone", "").strip()

            # Filter out empty emails (since this list is specifically for emailed leads)
            if not email:
                skipped_no_email += 1
                continue

            # Filter out empty phone numbers (since this is for a calling log)
            if not phone:
                skipped_no_phone += 1
                continue

            # Filter out bounces
            if email in bounced_emails:
                skipped_bounced += 1
                continue

            non_bounced_leads.append(row)

    # 3. Save output CSV
    with open(OUTPUT_CSV_PATH, "w", newline="", encoding="utf-8") as f:
        if non_bounced_leads:
            writer = csv.DictWriter(f, fieldnames=non_bounced_leads[0].keys())
            writer.writeheader()
            writer.writerows(non_bounced_leads)

    print("\n" + "=" * 60)
    print("📊 LIST GENERATION SUMMARY")
    print("=" * 60)
    print(f"Total leads with valid emails & phones: {len(non_bounced_leads) + skipped_bounced}")
    print(f"Bounces filtered out: {skipped_bounced}")
    print(f"Warm follow-up leads saved to CSV: {len(non_bounced_leads)}")
    print(f"Output File: {OUTPUT_CSV_PATH}")
    print("=" * 60)

if __name__ == "__main__":
    main()
