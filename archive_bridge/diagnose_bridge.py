import os
import json
import asyncio
import requests
import websockets
from dotenv import load_dotenv

if os.path.exists(".env"):
    load_dotenv(".env")
else:
    load_dotenv()

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
NGROK_DOMAIN = "socialsolidarity.ngrok.app"

async def test_webhook_post():
    print("[*] Test 1: Verifying Webhook POST endpoint...")
    url = f"https://{NGROK_DOMAIN}/webhook"
    payload = {
        "data": {
            "event_type": "call.initiated",
            "payload": {
                "call_control_id": "test_verification_id"
            }
        }
    }
    try:
        response = requests.post(url, json=payload, timeout=5)
        if response.status_code == 200:
            print("🟢 SUCCESS: Webhook endpoint returned 200 OK.")
            return True
        else:
            print(f"🔴 FAILURE: Webhook endpoint returned status {response.status_code} - {response.text}")
            return False
    except Exception as e:
        print(f"🔴 FAILURE: Webhook endpoint unreachable: {repr(e)}")
        return False

async def test_websocket_handshake():
    print("[*] Test 2: Verifying localtunnel/ngrok WebSocket handshake...")
    url = f"wss://{NGROK_DOMAIN}/media-stream"
    try:
        async with websockets.connect(url) as ws:
            print("🟢 SUCCESS: WebSocket media-stream handshake completed successfully.")
            return True
    except Exception as e:
        print(f"🔴 FAILURE: WebSocket handshake failed: {repr(e)}")
        return False

async def test_gemini_live_api():
    print("[*] Test 3: Verifying Gemini Live API connection...")
    if not GEMINI_API_KEY:
        print("🔴 FAILURE: GEMINI_API_KEY is not configured in .env.")
        return False
        
    model = GEMINI_MODEL
    if "/" not in model:
        model = f"models/{model}"
        
    url = f"wss://generativelanguage.googleapis.com/ws/google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContent?key={GEMINI_API_KEY}"
    setup_message = {
        "setup": {
          "model": model,
          "generation_config": {
            "response_modalities": ["AUDIO"]
          }
        }
    }
    try:
        async with websockets.connect(url) as ws:
            await ws.send(json.dumps(setup_message))
            response = await ws.recv()
            data = json.loads(response)
            if "setup_complete" in data or "server_content" in data or len(data) > 0:
                print("🟢 SUCCESS: Gemini Live API connected and accepted session configuration.")
                return True
            else:
                print(f"🔴 FAILURE: Gemini returned unexpected setup response: {data}")
                return False
    except Exception as e:
        print(f"🔴 FAILURE: Gemini Live API connection failed: {repr(e)}")
        return False

async def main():
    print("=" * 60)
    print("🔬 DIALER BRIDGE STACK DIAGNOSTIC TOOL")
    print("=" * 60)
    
    t1 = await test_webhook_post()
    t2 = await test_websocket_handshake()
    t3 = await test_gemini_live_api()
    
    print("=" * 60)
    print("📊 DIAGNOSTIC SUMMARY:")
    print(f"  - Webhook POST Endpoint : {'🟢 PASS' if t1 else '🔴 FAIL'}")
    print(f"  - WebSocket Handshake  : {'🟢 PASS' if t2 else '🔴 FAIL'}")
    print(f"  - Gemini Live API      : {'🟢 PASS' if t3 else '🔴 FAIL'}")
    print("=" * 60)

if __name__ == "__main__":
    asyncio.run(main())
