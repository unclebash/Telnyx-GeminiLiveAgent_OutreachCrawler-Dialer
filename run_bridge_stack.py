import os
import sys
import time
import json
import subprocess
import requests
from dotenv import load_dotenv

# Load env variables
if os.path.exists(".env"):
    load_dotenv(".env")
else:
    load_dotenv()

TELNYX_API_KEY = os.environ.get("TELNYX_API_KEY")
APP_ID = "2993765676876826606"
STATIC_DOMAIN = "socialsolidarity.ngrok.app"

def start_ngrok_tunnel():
    print(f"[*] Launching Ngrok Tunnel on static domain {STATIC_DOMAIN}...")
    
    # Start ngrok in a subprocess pointing to port 8000
    process = subprocess.Popen(
        ["./ngrok", "http", "8000", f"--domain={STATIC_DOMAIN}", "--config=/Users/judeostudio/.ngrok2/ngrok.yml"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1
    )
    
    public_url = f"https://{STATIC_DOMAIN}"
    
    # Wait a few seconds to let ngrok connect in the background
    time.sleep(3)
    
    if process.poll() is not None:
        stdout, stderr = process.communicate()
        print(f"❌ Ngrok exited immediately with code {process.returncode}")
        print(f"Stderr: {stderr}")
        return None, None
        
    print("=" * 60)
    print(f"🎉 NGROK STATIC TUNNEL ESTABLISHED!")
    print(f"   Your Public URL: {public_url}")
    print("=" * 60)
    return public_url, process

def update_telnyx_webhook(public_url):
    webhook_url = f"{public_url}/webhook"
    print(f"🌐 Updating Telnyx Call Control Application Webhook to: {webhook_url}")
    
    url = f"https://api.telnyx.com/v2/call_control_applications/{APP_ID}"
    headers = {
        "Authorization": f"Bearer {TELNYX_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "webhook_event_url": webhook_url
    }
    
    try:
        response = requests.patch(url, headers=headers, json=payload)
        if response.status_code == 200:
            print("✅ Successfully updated webhook URL in Telnyx portal!")
            return True
        else:
            print(f"❌ Failed to update webhook URL in Telnyx: {response.status_code} - {response.text}")
            return False
    except Exception as e:
        print(f"❌ Error updating webhook: {repr(e)}")
        return False

def start_bridge_server():
    print("[*] Starting telnyx_bridge.py server on port 8000...")
    try:
        subprocess.run(["python3", "telnyx_bridge.py"])
    except KeyboardInterrupt:
        print("\n[*] Shutting down bridge server...")

def main():
    if not TELNYX_API_KEY:
        print("❌ Error: TELNYX_API_KEY not found in .env file.")
        return
        
    public_url, tunnel_proc = start_ngrok_tunnel()
    if not public_url:
        return
        
    success = update_telnyx_webhook(public_url)
    if not success:
        tunnel_proc.terminate()
        return
        
    print("\n" + "=" * 60)
    print("🚀 DIALER BRIDGE STACK ACTIVE!")
    print("   Press Ctrl+C to terminate both the tunnel and the bridge server.")
    print("=" * 60 + "\n")
    
    try:
        start_bridge_server()
    finally:
        print("[*] Cleaning up background processes...")
        tunnel_proc.terminate()
        print("✅ Cleanup complete.")

if __name__ == "__main__":
    main()
