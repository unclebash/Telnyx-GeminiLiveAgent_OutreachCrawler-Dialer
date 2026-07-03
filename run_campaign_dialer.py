import os
import sys
import json
import time
import asyncio
import httpx
from dotenv import load_dotenv

if os.path.exists(".env"):
    load_dotenv(".env")
else:
    load_dotenv()

TELNYX_API_KEY = os.environ.get("TELNYX_API_KEY")
FROM_NUMBER = "+17472676543"
APP_ID = "2993765676876826606"

# Safety Concurrency for Telnyx Trial Accounts
CONCURRENCY_LIMIT = 2
STAGGER_DELAY = 30.0

dial_queue = asyncio.Queue()
report_log = []
campaign_log_path = "campaign_outflow_log.json"

# Track already dialed numbers
dialed_numbers = set()
if os.path.exists(campaign_log_path):
    try:
        with open(campaign_log_path, "r") as f:
            report_log = json.load(f)
            dialed_numbers = {entry.get("phone") for entry in report_log if entry.get("status") == "success"}
    except Exception:
        report_log = []

async def dial_prospect(client, phone, name, index, total):
    # E.164 formatting
    clean_phone = "".join(filter(str.isdigit, phone))
    if not clean_phone.startswith("1") and len(clean_phone) == 10:
        clean_phone = "1" + clean_phone
    formatted_phone = "+" + clean_phone

    if formatted_phone in dialed_numbers:
        return

    print(f"📞 [{index}/{total}] Dialing {name} at {formatted_phone}...")

    url = "https://api.telnyx.com/v2/calls"
    headers = {
        "Authorization": f"Bearer {TELNYX_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "to": formatted_phone,
        "from": FROM_NUMBER,
        "connection_id": APP_ID,
        "answering_machine_detection": "detect"
    }

    try:
        response = await client.post(url, json=payload, headers=headers)
        status_code = response.status_code
        
        entry = {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "name": name,
            "phone": formatted_phone,
            "status": "success" if status_code in (200, 201) else "failed",
            "status_code": status_code,
            "response": response.json() if status_code in (200, 201) else response.text
        }
        
        report_log.append(entry)
        
        # Iteratively save the campaign logs
        with open(campaign_log_path, "w") as f:
            json.dump(report_log, f, indent=2)

        if status_code in (200, 201):
            data = response.json().get("data", {})
            print(f"  ✅ Call leg requested successfully for {name} ({formatted_phone}).")
            # Mark dialed to avoid double attempts in memory
            dialed_numbers.add(formatted_phone)
        else:
            print(f"  ❌ Dial failed for {name}: {status_code} - {response.text}")
            
    except Exception as e:
        print(f"  ❌ Request error dialing {name}: {repr(e)}")
        entry = {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "name": name,
            "phone": formatted_phone,
            "status": "error",
            "error": repr(e)
        }
        report_log.append(entry)
        with open(campaign_log_path, "w") as f:
            json.dump(report_log, f, indent=2)

async def worker(client, total):
    while not dial_queue.empty():
        item = await dial_queue.get()
        index, phone, name = item
        await dial_prospect(client, phone, name, index, total)
        # Safe stagger pacing to protect channel limits
        await asyncio.sleep(STAGGER_DELAY)
        dial_queue.task_done()

async def main():
    if not TELNYX_API_KEY:
        print("❌ Error: TELNYX_API_KEY not found in .env file.")
        return

    if not os.path.exists("phone_names.json"):
        print("❌ Error: phone_names.json not found. Run build_and_deploy_prospects.py first.")
        return

    with open("phone_names.json", "r") as f:
        prospects = json.load(f)

    # Queue up the prospects
    index = 1
    for phone, name in prospects.items():
        # Only queue if not already dialed
        clean_phone = "".join(filter(str.isdigit, phone))
        if not clean_phone.startswith("1") and len(clean_phone) == 10:
            clean_phone = "1" + clean_phone
        formatted_phone = "+" + clean_phone
        
        if formatted_phone not in dialed_numbers:
            await dial_queue.put((index, phone, name))
            index += 1

    total_prospects = dial_queue.qsize()
    print("=" * 60)
    print(f"🚀 LAUNCHING PACE-THROTTLED CAMPAIGN DIALER")
    print(f"  Active concurrent lines: {CONCURRENCY_LIMIT}")
    print(f"  Breather Stagger: {STAGGER_DELAY}s")
    print(f"  Queue size remaining: {total_prospects} contacts")
    print(f"  Caller ID: {FROM_NUMBER}")
    print("=" * 60)

    if total_prospects == 0:
        print("ℹ️ All prospects already dialed successfully.")
        return

    # Start HTTP Client Session
    limits = httpx.Limits(max_keepalive_connections=CONCURRENCY_LIMIT, max_connections=CONCURRENCY_LIMIT)
    async with httpx.AsyncClient(limits=limits, timeout=15.0) as client:
        # Spawn concurrent worker tasks
        tasks = []
        for _ in range(CONCURRENCY_LIMIT):
            task = asyncio.create_task(worker(client, total_prospects))
            tasks.append(task)

        # Wait for all workers to finish
        await asyncio.gather(*tasks)

    print("\n" + "=" * 60)
    print("🏁 CAMPAIGN COMPLETE!")
    print(f"  Logs saved to: {campaign_log_path}")
    print("=" * 60)

if __name__ == "__main__":
    asyncio.run(main())
