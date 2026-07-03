import os
import sys
import requests
from dotenv import load_dotenv

if os.path.exists(".env"):
    load_dotenv(".env")
else:
    load_dotenv()

TELNYX_API_KEY = os.environ.get("TELNYX_API_KEY")
FROM_NUMBER = "+17472676543"
APP_ID = "2993765676876826606"

def trigger_dial(to_number):
    if not TELNYX_API_KEY:
        print("❌ Error: TELNYX_API_KEY not found in .env file.")
        return

    # Clean the target phone number
    clean_to = "".join(filter(str.isdigit, to_number))
    if not clean_to.startswith("1") and len(clean_to) == 10:
        clean_to = "1" + clean_to
        
    formatted_to = "+" + clean_to
    print("=" * 60)
    print("📞 TELNYX PROGRAMMABLE OUTBOUND DIALER")
    print(f"  Target Number : {formatted_to}")
    print(f"  Caller ID     : {FROM_NUMBER}")
    print(f"  Application ID: {APP_ID}")
    print("=" * 60)

    url = "https://api.telnyx.com/v2/calls"
    headers = {
        "Authorization": f"Bearer {TELNYX_API_KEY}",
        "Content-Type": "application/json"
    }
    
    # We call the number and link it to our Call Control Application
    payload = {
        "to": formatted_to,
        "from": FROM_NUMBER,
        "connection_id": APP_ID
    }
    
    try:
        print("Initiating call via Telnyx Call Control API...")
        response = requests.post(url, headers=headers, json=payload)
        
        if response.status_code == 201 or response.status_code == 200:
            data = response.json().get("data", {})
            call_control_id = data.get("call_control_id")
            call_leg_id = data.get("call_leg_id")
            print(f"✅ Call requested successfully!")
            print(f"  Call Control ID: {call_control_id}")
            print(f"  Call Leg ID    : {call_leg_id}")
        else:
            print(f"❌ Failed to initiate call: {response.status_code} - {response.text}")
            
    except Exception as e:
        print(f"❌ Error: {repr(e)}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 trigger_telnyx_dial.py <target_phone_number>")
        sys.exit(1)
        
    trigger_dial(sys.argv[1])
