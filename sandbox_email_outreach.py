import os
import sys
import time
import csv
import sqlite3
from gmail_sender import StandaloneGmailClient

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# Check for cleaned CSV first, fallback to raw sandbox CSV
CLEANED_CSV = os.path.join(BASE_DIR, "sandbox_tmz_results_cleaned.csv")
RAW_CSV = os.path.join(BASE_DIR, "sandbox_tmz_results.csv")

CSV_PATH = CLEANED_CSV if os.path.exists(CLEANED_CSV) else RAW_CSV

# =========================================================================
# CONFIGURATION
# =========================================================================
MODE = "send"  # Change to "send" to send emails directly instead of creating drafts
DELAY_SECONDS = 3.0  # Rate-limiting delay to prevent Google Spam blocks
START_INDEX = 0  # Starting row index in the CSV (0 is the first business)
LIMIT = 1000  # Number of emails to process in this run

SUBJECT_TEMPLATE = "[COMPANY NAME] | Outreach to Help 501c3 - Keeping People Employed"

HTML_BODY_TEMPLATE = """<div style="max-width: 600px; margin: 0 auto; background-color: #ffffff; font-family: Arial, sans-serif; line-height: 1.6; color: #222222; padding: 10px; display: block; clear: both;">
  
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

</div>"""

def main():
    print("=" * 60)
    print("📧 STANDALONE TMZ BULK OUTREACH INITIATOR")
    print(f"  Target Source: {os.path.basename(CSV_PATH)}")
    print(f"  Execution Mode: {MODE.upper()}")
    print("=" * 60)

    if not os.path.exists(CSV_PATH):
        print(f"Error: Target CSV not found at {CSV_PATH}. Please run the sweeper first.")
        sys.exit(1)

    # Initialize and verify Gmail Client
    gmail_client = StandaloneGmailClient(BASE_DIR)
    if not gmail_client.is_configured():
        print("Error: gmail_credentials.json is missing.")
        sys.exit(1)
        
    if not gmail_client.is_authenticated():
        print("Error: Gmail account is not authenticated. Please authenticate via the dashboard sidebar first.")
        sys.exit(1)

    sender_email = gmail_client.get_sender_email()
    print(f"Authenticating as: {sender_email}")
    print("Starting process...")

    # Load leads from CSV
    leads = []
    with open(CSV_PATH, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            email = row.get("Email", "").strip()
            name = row.get("Company Name", "").strip()
            if email and name:
                leads.append({
                    "name": name,
                    "email": email
                })

    total_leads = len(leads)
    print(f"Found {total_leads} leads with email addresses in CSV.")
    
    # Slice the leads based on configuration
    active_leads = leads[START_INDEX:START_INDEX + LIMIT]
    processed_count = 0
    success_count = 0

    print(f"Processing batch: index {START_INDEX} to {START_INDEX + len(active_leads) - 1} (Total: {len(active_leads)}).")
    print("-" * 60)

    for idx, lead in enumerate(active_leads):
        processed_count += 1
        comp_name = lead["name"]
        to_email = lead["email"]

        # Render placeholders
        subject = SUBJECT_TEMPLATE.replace("[COMPANY NAME]", comp_name).replace("{name}", comp_name)
        body = HTML_BODY_TEMPLATE.replace("[COMPANY NAME]", comp_name).replace("{name}", comp_name)

        print(f"[{processed_count}/{len(active_leads)}] {MODE.title()} to: {comp_name} ({to_email})... ", end="", flush=True)

        if MODE == "draft":
            success = gmail_client.create_draft(to_email, subject, body, is_html=True)
        else:
            success = gmail_client.send_email(to_email, subject, body, is_html=True)

        if success:
            success_count += 1
            print("✅ SUCCESS")
        else:
            print("❌ FAILED")

        # Sleep to avoid rate limits
        if idx < len(active_leads) - 1:
            time.sleep(DELAY_SECONDS)

    print("=" * 60)
    print("📊 BATCH OUTREACH SUMMARY")
    print("=" * 60)
    print(f"Total Leads Swept in Batch: {len(active_leads)}")
    print(f"Successfully Processed: {success_count}")
    print(f"Failed: {len(active_leads) - success_count}")
    print("=" * 60)

if __name__ == "__main__":
    main()
