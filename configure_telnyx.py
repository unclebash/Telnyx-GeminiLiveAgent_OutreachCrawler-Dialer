import os
import requests
from dotenv import load_dotenv

if os.path.exists(".env"):
    load_dotenv(".env")
else:
    load_dotenv()

TELNYX_API_KEY = os.environ.get("TELNYX_API_KEY")
APP_ID = "2993765676876826606"

def configure_telnyx():
    if not TELNYX_API_KEY:
        print("❌ Error: TELNYX_API_KEY not found in .env file.")
        return

    headers = {
        "Authorization": f"Bearer {TELNYX_API_KEY}",
        "Content-Type": "application/json"
    }

    print("🔍 Fetching active phone numbers on your Telnyx account...")
    # Get active phone numbers
    url = "https://api.telnyx.com/v2/phone_numbers"
    try:
        response = requests.get(url, headers=headers)
        if response.status_code != 200:
            print(f"❌ Failed to fetch numbers: {response.status_code} - {response.text}")
            return
            
        data = response.json().get("data", [])
        if not data:
            print("⚠️ No phone numbers found on the account. Please buy a number first in the Telnyx Portal.")
            return

        print(f"✅ Found {len(data)} phone number(s):")
        for num in data:
            phone_num = num.get("phone_number")
            num_id = num.get("id")
            current_app = num.get("connection_id")
            print(f"   - Number: {phone_num} (ID: {num_id}, Current App ID: {current_app})")
            
            # Update the number to use our Call Control Application
            print(f"     Updating number to use 'SocialSolidarity Dialer' (Application ID: {APP_ID})...")
            update_url = f"https://api.telnyx.com/v2/phone_numbers/{num_id}"
            payload = {
                "connection_id": APP_ID
            }
            update_resp = requests.patch(update_url, headers=headers, json=payload)
            if update_resp.status_code == 200:
                print(f"     ✅ Successfully linked {phone_num} to the dialer application!")
            else:
                print(f"     ❌ Failed to link number: {update_resp.status_code} - {update_resp.text}")

    except Exception as e:
        print(f"❌ Error during configuration: {repr(e)}")

if __name__ == "__main__":
    configure_telnyx()
