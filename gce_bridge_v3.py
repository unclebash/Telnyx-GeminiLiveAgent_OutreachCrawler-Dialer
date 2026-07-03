import os
import sys
import json
import base64
import asyncio
import logging
import struct
import time
import websockets
from fastapi import FastAPI, WebSocket, Request, Response
from fastapi.responses import JSONResponse
from dotenv import load_dotenv

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("telnyx-gemini-bridge-v3")

# Load environment variables
if os.path.exists(".env"):
    load_dotenv(".env")
else:
    load_dotenv()

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
GEMINI_MODEL = "gemini-3.1-flash-live-preview"
TELNYX_API_KEY = os.environ.get("TELNYX_API_KEY")

# Persona instructions
PERSONA_INSTRUCTIONS = """You are Tzipora, a warm, energetic, and empathetic AI outreach specialist calling from The SocialSolidarity Foundation.

Our mission: Upskilling and workforce development for local participants to keep them in their training modules (culinary/food service and entrepreneurship general computer suites).
Our tax status: We are a tax-exempt 501(c)(3) nonprofit, EIN 85-1446734.
Our website: socialsolidarity.foundation.

Speaking Style:
- Speak with a highly energetic, enthusiastic, and warm tone.
- Be conversational and flexible.

Your Dialog Flow:
1. Opening Statement (Accept ANY response, do NOT be rigid here):
   "Hi, my name is Tzipora, calling from The SocialSolidarity Foundation. We are a local upskilling and workforce development program here. Sponsoring a trainee makes an incredible difference in helping them complete their vocational modules. Would you be open to showing a giving heart and supporting us with a donation today?"

2. If they say "yes", "sure", "yeah", "okay", or agree:
   Proceed directly to asking for their details:
   "Thank you so much! Since SMS is currently experiencing carrier delays, I can register your donation manually. May I get your name and email address so we can email you the invoice and tax receipt?"

3. If they ask for more information or hesitate:
   Explain the impact:
   "It takes just $200 to keep one trainee in their career-track program for an entire month-long module. And it only takes three modules per trainee to secure permanent job placement in our local economy. Sponsoring makes a huge difference."
   Then re-ask: "Would you be able to support a trainee today?"

4. Rigidity Prevention disclaimer (ONLY say this if they give an ambiguous response to a yes/no question, or if you need to prompt them again):
   "Would you mind replying with a 'yes' or 'no,' please, as I'm actually still being programmed by our trainees and I'm still learning, too!"

5. Email Collection & Verification:
   Once they give their email, you MUST spell it back character-by-character to confirm it is correct (e.g. "Let me double check, is that j-u-d-e-i-n-v-e-s-t-m-e-n-t-s at gmail dot com?").

6. Call the Tool (CRITICAL):
   Once they confirm their email and agreed commitment amount, you MUST call the `record_donation_lead` tool immediately. Do not forget to call the tool.

7. Wrap Up:
   After calling the tool, say: "Great! I have registered your sponsorship. You'll receive a tax-deductible receipt to that same email once your donation is processed. Thank you so much for your support and have a wonderful day!"
"""

# Global registries
gemini_pool = {}
call_destination_map = {}  # Map call_control_id to target recipient phone number

# Initialize Gmail Client
try:
    from gmail_sender import StandaloneGmailClient
    gmail_client = StandaloneGmailClient(".")
    logger.info("✅ Gmail Sender client initialized successfully.")
except Exception as e:
    gmail_client = None
    logger.error(f"❌ Failed to load Gmail Sender client: {e}")

def double_sample_rate_8khz_to_16khz(pcm_8khz_bytes):
    num_samples = len(pcm_8khz_bytes) // 2
    samples = struct.unpack(f"{num_samples}h", pcm_8khz_bytes)
    doubled = [s for sample in samples for s in (sample, sample)]
    return struct.pack(f"{num_samples * 2}h", *doubled)

def downsample_24khz_to_8khz(pcm_24khz_bytes):
    num_samples = len(pcm_24khz_bytes) // 2
    samples = struct.unpack(f"{num_samples}h", pcm_24khz_bytes)
    downsampled = samples[::3]
    return struct.pack(f"{len(downsampled)}h", *downsampled)

async def pre_warm_gemini(call_control_id: str):
    gemini_url = f"wss://generativelanguage.googleapis.com/ws/google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContent?key={GEMINI_API_KEY}"
    logger.info(f"Pre-warming Gemini socket for call_control_id: {call_control_id}")
    
    target_phone = call_destination_map.get(call_control_id, "")
    donor_first_name = ""
    if target_phone:
        # Clean phone number to match lookup (e.g. +16267167650 -> 16267167650 or 6267167650)
        clean_num = "".join(filter(str.isdigit, target_phone))
        try:
            if os.path.exists("phone_names.json"):
                with open("phone_names.json", "r") as f:
                    phone_map = json.load(f)
                    # Try looking up both with and without leading '1'
                    donor_first_name = phone_map.get(clean_num) or phone_map.get(clean_num[1:] if clean_num.startswith("1") else "1" + clean_num)
                    if donor_first_name:
                        logger.info(f"🔍 Found name '{donor_first_name}' for number {target_phone}")
            else:
                logger.info("ℹ️ phone_names.json not found, using generic greeting.")
        except Exception as e:
            logger.error(f"Error loading phone_names.json: {repr(e)}")

    custom_instructions = PERSONA_INSTRUCTIONS
    if donor_first_name:
        custom_instructions += f"\n\nIMPORTANT context for this call: The person you are calling is named {donor_first_name}. You MUST greet them as {donor_first_name} in your opening statement. (e.g. 'Hi {donor_first_name}, my name is Tzipora...')"

    try:
        ws = await websockets.connect(gemini_url)
        setup_message = {
            "setup": {
              "model": gemini_model_selector(GEMINI_MODEL),
              "generation_config": {
                "response_modalities": ["AUDIO"],
                "speech_config": {
                  "voice_config": {
                    "prebuilt_voice_config": {
                      "voice_name": "Aoede"
                    }
                  }
                }
              },
              "system_instruction": {
                "parts": [{"text": custom_instructions}]
              },
              "tools": [
                {
                  "function_declarations": [
                    {
                      "name": "record_donation_lead",
                      "description": "Records the verified lead details (name, email, and agreed donation amount) to the database when a user agrees to sponsor/donate.",
                      "parameters": {
                        "type": "OBJECT",
                        "properties": {
                          "name": {
                            "type": "STRING",
                            "description": "The name of the donor."
                          },
                          "email": {
                            "type": "STRING",
                            "description": "The verified email address of the donor."
                          },
                          "amount": {
                            "type": "NUMBER",
                            "description": "The sponsorship/donation amount in USD."
                          }
                        },
                        "required": ["name", "email", "amount"]
                      }
                    }
                  ]
                }
              ]
            }
        }
        await ws.send(json.dumps(setup_message))
        
        setup_confirmed = False
        for _ in range(10):
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=2.0)
                data = json.loads(msg)
                if "setupComplete" in data:
                    setup_confirmed = True
                    logger.info(f"✅ Gemini socket pre-warmed & setup complete for: {call_control_id}")
                    break
            except Exception:
                break
                
        if setup_confirmed:
            gemini_pool[call_control_id] = (ws, True)
        else:
            await ws.close()
            logger.warning(f"⚠️ Pre-warm failed to verify setupComplete for: {call_control_id}")
    except Exception as e:
        logger.error(f"❌ Failed to pre-warm Gemini socket for {call_control_id}: {repr(e)}")

def gemini_model_selector(model_id):
    if "/" not in model_id:
        return f"models/{model_id}"
    return model_id

async def send_sms_via_telnyx(to_phone: str):
    if not to_phone:
        logger.error("Cannot send SMS: Recipient phone number is empty.")
        return False
        
    url = "https://api.telnyx.com/v2/messages"
    headers = {
        "Authorization": f"Bearer {TELNYX_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "from": "+18335683663",
        "to": to_phone,
        "text": "Hi! Here is the link to sponsor a trainee at The SocialSolidarity Foundation: https://donate.stripe.com/abc123xyz Thank you so much for your support!"
    }
    
    import httpx
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=payload, headers=headers)
            logger.info(f"Telnyx SMS delivery response: {response.status_code} - {response.text}")
            return response.status_code == 200 or response.status_code == 201
    except Exception as e:
        logger.error(f"Failed to deliver Telnyx SMS: {repr(e)}")
        return False

async def hangup_call_via_telnyx(call_control_id: str):
    url = f"https://api.telnyx.com/v2/calls/{call_control_id}/actions/hangup"
    headers = {
        "Authorization": f"Bearer {TELNYX_API_KEY}",
        "Content-Type": "application/json"
    }
    import httpx
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(url, json={}, headers=headers)
            logger.info(f"Telnyx Call Hangup response: {response.status_code}")
    except Exception as e:
        logger.error(f"Failed to hangup call: {repr(e)}")

app = FastAPI()

@app.post("/webhook")
async def telnyx_webhook(request: Request):
    try:
        body = await request.json()
        event_type = body.get("data", {}).get("event_type")
        payload_data = body.get("data", {}).get("payload", {})
        call_control_id = payload_data.get("call_control_id")
        
        logger.info(f"Received webhook event: {event_type} (Call Control ID: {call_control_id})")
        
        if event_type == "call.initiated":
            # Determine the human's phone number by filtering out our own Telnyx system lines
            caller_from = payload_data.get("from")
            caller_to = payload_data.get("to")
            
            # Filter out both our local line and toll-free vanity line
            system_numbers = {"+17472676543", "+18335683663"}
            if caller_from in system_numbers:
                target_phone = caller_to
            else:
                target_phone = caller_from
                
            call_destination_map[call_control_id] = target_phone
            logger.info(f"Registered call destination map: {call_control_id} -> {target_phone}")
            
            asyncio.create_task(pre_warm_gemini(call_control_id))
            
        elif event_type in ("call.machine.detection.updated", "call.machine.detection.ended"):
            # Inspect the Answering Machine Detection result
            logger.info(f"🤖 Full AMD Webhook payload: {payload_data}")
            detection_result = payload_data.get("detection_result") or payload_data.get("result")
            logger.info(f"🤖 Answering Machine Detection update for {call_control_id}: {detection_result}")
            
            if detection_result in ("machine", "fax"):
                logger.info(f"🔇 Voicemail detected. Hanging up call control {call_control_id} immediately.")
                asyncio.create_task(hangup_call_via_telnyx(call_control_id))
            
        elif event_type == "call.answered":
            host = request.headers.get("host")
            stream_url = f"wss://{host}/media-stream?call_control_id={call_control_id}"
            
            logger.info(f"Call answered. Directing Telnyx media stream to: {stream_url}")
            
            url = f"https://api.telnyx.com/v2/calls/{call_control_id}/actions/streaming_start"
            headers = {
                "Authorization": f"Bearer {TELNYX_API_KEY}",
                "Content-Type": "application/json"
            }
            payload = {
                "stream_url": stream_url,
                "stream_track": "both_tracks",
                "stream_bidirectional_mode": "rtp",
                "stream_bidirectional_codec": "PCMU"
            }
            
            import httpx
            async with httpx.AsyncClient() as client:
                for attempt in range(4):
                    logger.info(f"Attempting to start Telnyx media stream (Attempt {attempt+1}/4)...")
                    response = await client.post(url, json=payload, headers=headers)
                    if response.status_code == 200:
                        logger.info("✅ Telnyx media stream started successfully!")
                        break
                    elif response.status_code == 422 and attempt < 3:
                        await asyncio.sleep(1.5)
                    else:
                        break
            
    except Exception as e:
        logger.error(f"Error handling webhook: {repr(e)}")
        
    return Response(status_code=200)

@app.websocket("/media-stream")
async def media_stream_endpoint(websocket: WebSocket):
    await websocket.accept()
    logger.info("Telnyx Media Stream connection handshake accepted.")
    
    call_control_id = websocket.query_params.get("call_control_id")
    stream_id = None
    
    # Retrieve the mapped recipient phone number for this call control ID
    recipient_phone = call_destination_map.get(call_control_id)
    logger.info(f"Streaming connection initialized. Call ID: {call_control_id}, Target Recipient: {recipient_phone}")
    
    gemini_ws = None
    if call_control_id and call_control_id in gemini_pool:
        try:
            ws, ready = gemini_pool.pop(call_control_id)
            is_open = False
            try:
                is_open = ws.state.name == "OPEN"
            except AttributeError:
                is_open = ws.open
                
            if ready and is_open:
                gemini_ws = ws
                logger.info("🔥 Reused pre-warmed Gemini socket connection successfully.")
        except Exception as e:
            logger.warning(f"Failed to pop pre-warmed socket: {repr(e)}")
            
    if not gemini_ws:
        logger.info("On-demand connecting to Gemini Live API...")
        gemini_url = f"wss://generativelanguage.googleapis.com/ws/google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContent?key={GEMINI_API_KEY}"
        gemini_ws = await websockets.connect(gemini_url)
        setup_message = {
            "setup": {
              "model": gemini_model_selector(GEMINI_MODEL),
              "generation_config": {
                "response_modalities": ["AUDIO"],
                "speech_config": {
                  "voice_config": {
                    "prebuilt_voice_config": {
                      "voice_name": "Aoede"
                    }
                  }
                }
              },
              "system_instruction": {
                "parts": [{"text": PERSONA_INSTRUCTIONS}]
              },
              "tools": [
                {
                  "function_declarations": [
                    {
                      "name": "record_donation_lead",
                      "description": "Records the verified lead details (name, email, and agreed donation amount) to the database when a user agrees to sponsor/donate.",
                      "parameters": {
                        "type": "OBJECT",
                        "properties": {
                          "name": {
                            "type": "STRING",
                            "description": "The name of the donor."
                          },
                          "email": {
                            "type": "STRING",
                            "description": "The verified email address of the donor."
                          },
                          "amount": {
                            "type": "NUMBER",
                            "description": "The sponsorship/donation amount in USD."
                          }
                        },
                        "required": ["name", "email", "amount"]
                      }
                    }
                  ]
                }
              ]
            }
        }
        await gemini_ws.send(json.dumps(setup_message))
        setup_confirmed = False
        for _ in range(10):
            try:
                msg = await asyncio.wait_for(gemini_ws.recv(), timeout=2.0)
                data = json.loads(msg)
                if "setupComplete" in data:
                    setup_confirmed = True
                    break
            except Exception:
                break
        if not setup_confirmed:
            logger.error("❌ Failed to verify setupComplete. Closing WebSocket.")
            await gemini_ws.close()
            await websocket.close()
            return

    last_audio_time = time.time()
    has_warned_silence = False

    telnyx_to_gemini_queue = asyncio.Queue()
    session_active = asyncio.Event()
    session_active.set()

    import audioop

    async def read_telnyx():
        nonlocal stream_id, last_audio_time
        try:
            while session_active.is_set():
                msg = await websocket.receive_text()
                data = json.loads(msg)
                if data.get("event") == "media":
                    if data.get("media", {}).get("track") == "inbound":
                        if not stream_id:
                            stream_id = data.get("stream_id")
                            logger.info(f"Identified stream_id: {stream_id}")
                        
                        payload = base64.b64decode(data["media"]["payload"])
                        
                        # Decode ulaw to 16-bit linear PCM first (width=2)
                        pcm_linear = audioop.ulaw2lin(payload, 2)
                        
                        # Calculate RMS on the decoded 16-bit linear PCM (width=2)
                        rms = audioop.rms(pcm_linear, 2)
                        
                        # Set noise gate threshold on linear PCM (100 is a standard quiet room gate)
                        if rms > 80:
                            last_audio_time = time.time()
                            pcm_16khz = double_sample_rate_8khz_to_16khz(pcm_linear)
                            await telnyx_to_gemini_queue.put(pcm_16khz)
                        else:
                            # Send 20ms of digital silence (640 null bytes) to keep the stream ticking
                            await telnyx_to_gemini_queue.put(bytes(640))
        except Exception as e:
            logger.info(f"Telnyx socket read completed/closed: {repr(e)}")
        finally:
            session_active.clear()

    packets_to_gemini = 0
    async def write_gemini():
        nonlocal packets_to_gemini
        try:
            while session_active.is_set():
                pcm_16khz = await telnyx_to_gemini_queue.get()
                payload = {
                    "realtime_input": {
                        "audio": {
                            "mime_type": "audio/pcm",
                            "data": base64.b64encode(pcm_16khz).decode("utf-8")
                        }
                    }
                }
                await gemini_ws.send(json.dumps(payload))
                packets_to_gemini += 1
                if packets_to_gemini % 100 == 0:
                    logger.info(f"🎤 Forwarded {packets_to_gemini} audio packets to Gemini")
        except Exception as e:
            logger.info(f"Gemini socket write completed/closed: {repr(e)}")
        finally:
            session_active.clear()

    packets_from_gemini = 0
    async def read_gemini_and_write_telnyx():
        nonlocal packets_from_gemini
        try:
            async for message in gemini_ws:
                if not session_active.is_set():
                    break
                    
                response_data = json.loads(message)
                
                # Detailed JSON debug logging
                debug_data = json.loads(message)
                if "serverContent" in debug_data:
                    model_turn = debug_data["serverContent"].get("modelTurn", {})
                    for part in model_turn.get("parts", []):
                        if "inlineData" in part:
                            part["inlineData"]["data"] = f"...<{len(part['inlineData']['data'])} bytes>..."
                    logger.info(f"🔮 Gemini ServerContent: {json.dumps(debug_data)}")
                else:
                    logger.info(f"🔮 Gemini Other Event: {message}")
                
                # Check for tool call events
                if "toolCall" in response_data:
                    function_calls = response_data["toolCall"].get("functionCalls", [])
                    for fc in function_calls:
                        if fc.get("name") == "record_donation_lead":
                            call_id = fc.get("id")
                            args = fc.get("args", {})
                            donor_name = args.get("name", "Unknown")
                            donor_email = args.get("email", "Unknown")
                            donor_amount = args.get("amount", 0)
                            
                            logger.info(f"☎️ Tool execution request: record_donation_lead: {donor_name} ({donor_email}) - ${donor_amount}")
                            
                            # Log lead to CSV
                            csv_path = "donation_leads.csv"
                            from datetime import datetime
                            timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
                            
                            csv_success = False
                            try:
                                import csv
                                file_exists = os.path.exists(csv_path)
                                with open(csv_path, mode="a", newline="") as f:
                                    writer = csv.writer(f)
                                    if not file_exists:
                                        writer.writerow(["Timestamp", "Call Control ID", "Phone Number", "Name", "Email", "Amount"])
                                    writer.writerow([timestamp, call_control_id, recipient_phone, donor_name, donor_email, donor_amount])
                                logger.info(f"✅ Lead saved successfully to CSV: {donor_name} ({donor_email})")
                                csv_success = True
                            except Exception as e:
                                logger.error(f"❌ Failed to save lead to CSV: {repr(e)}")
                            
                            # Deliver automated email via Gmail Client
                            email_success = False
                            if gmail_client:
                                subject = f"Complete your sponsorship - The SocialSolidarity Foundation"
                                
                                # Professional brand-aligned HTML template
                                body_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Your Support Makes a Difference - SocialSolidarity Foundation</title>
  <style>
    body, table, td, a {{ -webkit-text-size-adjust: 100%; -ms-text-size-adjust: 100%; }}
    table, td {{ mso-table-lspace: 0pt; mso-table-rspace: 0pt; }}
    img {{ -ms-interpolation-mode: bicubic; border: 0; height: auto; line-height: 100%; outline: none; text-decoration: none; }}
    table {{ border-collapse: collapse !important; }}
    body {{ height: 100% !important; margin: 0 !important; padding: 0 !important; width: 100% !important; background-color: #f7f9fa; }}
    .email-container {{ max-width: 600px !important; width: 100%; margin: 0 auto !important; }}
    .btn-cta:hover {{ background-color: #b11e26 !important; transform: translateY(-1px); box-shadow: 0 5px 12px rgba(210, 38, 48, 0.3) !important; }}
    @media screen and (max-width: 600px) {{
      .content-padding {{ padding: 30px 20px !important; }}
      .footer-padding {{ padding: 24px 20px !important; }}
      .mobile-stack {{ display: block !important; width: 100% !important; text-align: center !important; box-sizing: border-box; }}
      .mobile-spacer {{ height: 20px !important; }}
      .signature-logo {{ text-align: center !important; padding-top: 15px !important; }}
      .collage-cell {{ display: block !important; width: 100% !important; padding-left: 0 !important; padding-right: 0 !important; padding-bottom: 12px !important; }}
      .collage-spacer {{ display: none !important; }}
    }}
  </style>
</head>
<body style="background-color: #f7f9fa; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; margin: 0; padding: 0;">
  <table border="0" cellpadding="0" cellspacing="0" width="100%" style="table-layout: fixed; background-color: #f7f9fa; min-width: 100%;">
    <tr>
      <td align="center" style="padding: 24px 10px 40px 10px;">
        <table class="email-container" border="0" cellpadding="0" cellspacing="0" width="100%" style="background-color: #ffffff; border: 1px solid #e1e8ed; border-radius: 12px; overflow: hidden; box-shadow: 0 4px 12px rgba(0, 0, 0, 0.04);">
          <tr>
            <td align="center" style="background-color: #ffffff; padding: 0; border-bottom: 4px solid #D22630;">
              <a href="https://socialsolidarity.foundation" target="_blank" style="display: block; text-decoration: none;">
                <img src="https://static.wixstatic.com/media/375a01_fe7d52b289bb479e996823ad53ebeade~mv2.png" alt="SocialSolidarity Banner" width="600" style="display: block; width: 100%; max-width: 600px; height: auto; border: 0;" />
              </a>
            </td>
          </tr>
          <tr>
            <td class="content-padding" style="padding: 40px 40px 30px 40px; font-size: 16px; line-height: 1.625; color: #2d3748;">
              <p style="margin-top: 0; margin-bottom: 20px; font-size: 18px; font-weight: 700; color: #1a202c;">Hi {donor_name},</p>
              <p style="margin-top: 0; margin-bottom: 18px;">Thank you so much for speaking with me today and agreeing to support our upskilling and workforce development program! Sponsoring a trainee makes an incredible difference in helping them complete their vocational modules.</p>
              <p style="margin-top: 0; margin-bottom: 24px;">To finalize your secure sponsorship commitment of <strong>${donor_amount}</strong>, please click the secure link below to complete your donation. You can choose any contribution level that feels right to you:</p>
              <table border="0" cellpadding="0" cellspacing="0" width="100%">
                <tr>
                  <td align="center" style="padding: 5px 0 24px 0;">
                    <table border="0" cellpadding="0" cellspacing="0">
                      <tr>
                        <td align="center" bgcolor="#D22630" style="border-radius: 6px; box-shadow: 0 4px 10px rgba(210, 38, 48, 0.2);">
                          <a href="https://donate.stripe.com/9B67sMdrb01BbE3cHV48000" class="btn-cta" target="_blank" style="font-size: 16px; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; color: #ffffff; text-decoration: none; border-radius: 6px; padding: 15px 36px; border: 1px solid #D22630; display: inline-block; font-weight: bold; transition: all 0.2s ease-in-out; letter-spacing: 0.3px;">Complete Your Sponsorship</a>
                        </td>
                      </tr>
                    </table>
                  </td>
                </tr>
              </table>
              <table border="0" cellpadding="0" cellspacing="0" width="100%" style="margin-bottom: 30px;">
                <tr>
                  <td style="background-color: #fff8f8; border-left: 4px solid #D22630; border-radius: 4px; padding: 20px;">
                    <p style="margin: 0; font-size: 16px; line-height: 1.55; color: #2d3748;">
                      <strong style="color: #D22630; font-size: 17px;">The impact is real:</strong> It takes just <strong>$200</strong> to keep one trainee in their career-track program for an <strong>ENTIRE</strong> month-long module. It takes only three modules per trainee to secure permanent job placement in our local economy.
                    </p>
                  </td>
                </tr>
              </table>
              <p style="margin-top: 10px; margin-bottom: 18px;">Once your donation is processed, a formal tax-deductible receipt will be sent directly to this email address.</p>
              <p style="margin-top: 0; margin-bottom: 30px;">Thank you once again for your incredible warmth, local leadership, and solidarity!</p>
              <table border="0" cellpadding="0" cellspacing="0" width="100%" style="border-top: 1px solid #edf2f7; padding-top: 25px; margin-bottom: 30px;">
                <tr>
                  <td class="mobile-stack" align="left" valign="middle" style="width: 70%;">
                    <p style="margin: 0; font-size: 15px; color: #718096; font-style: italic;">Warmly,</p>
                    <p style="margin: 4px 0 0 0; font-size: 18px; font-weight: bold; color: #D22630;">Tzipora</p>
                    <p style="margin: 2px 0 0 0; font-size: 14px; color: #4a5568; line-height: 1.45;">Outreach Team<br /><strong style="color: #2d3748;">The SocialSolidarity Foundation</strong></p>
                  </td>
                  <td class="mobile-stack signature-logo" align="right" valign="middle" style="width: 30%;">
                    <img src="https://static.wixstatic.com/media/375a01_2ff3a71a887843088ae98b298d0e80bd~mv2.png" alt="SocialSolidarity Seal" width="85" style="display: inline-block; width: 85px; height: auto;" />
                  </td>
                </tr>
              </table>
              <table border="0" cellpadding="0" cellspacing="0" width="100%" style="border-top: 1px solid #edf2f7; padding-top: 30px; margin-top: 10px;">
                <tr>
                  <td align="center">
                    <table border="0" cellpadding="0" cellspacing="0" style="max-width: 520px; width: 100%;">
                      <tr>
                        <td class="collage-cell" align="center" valign="top" style="width: 48%; padding: 0;">
                          <table border="0" cellpadding="0" cellspacing="0" width="100%">
                            <tr>
                              <td align="center" style="padding-bottom: 12px;">
                                <img src="https://static.wixstatic.com/media/375a01_c3e666b72d01446092ec59e3c38fa333~mv2.png" alt="" width="55" style="display: block; width: 55px; height: auto;" />
                              </td>
                            </tr>
                            <tr>
                              <td align="center">
                                <div style="border: 1px solid #e1e8ed; border-radius: 8px; overflow: hidden; background-color: #ffffff; box-shadow: 0 4px 6px rgba(0, 0, 0, 0.02);">
                                  <img src="https://static.wixstatic.com/media/375a01_e38d5e67e8f44e39b6ea479408daf8fa~mv2.jpg" alt="Cohort Training Component" width="230" style="display: block; width: 100%; max-width: 230px; height: auto; border: 0;" />
                                </div>
                              </td>
                            </tr>
                          </table>
                        </td>
                        <td class="collage-spacer" style="width: 4%; font-size: 1px; line-height: 1px;">&nbsp;</td>
                        <td class="collage-cell" align="center" valign="top" style="width: 48%; padding: 0;">
                          <table border="0" cellpadding="0" cellspacing="0" width="100%">
                            <tr>
                              <td align="center" style="padding-bottom: 12px;">
                                <img src="https://static.wixstatic.com/media/375a01_4b6f495acdd04715a6de0a7c9d7c8334~mv2.png" alt="" width="55" style="display: block; width: 55px; height: auto;" />
                              </td>
                            </tr>
                            <tr>
                              <td align="center">
                                <div style="border: 1px solid #e1e8ed; border-radius: 8px; overflow: hidden; background-color: #ffffff; box-shadow: 0 4px 6px rgba(0, 0, 0, 0.02);">
                                  <img src="https://static.wixstatic.com/media/375a01_7e85af27e7874a169a6bb9963dc19fa4~mv2.jpg" alt="Food Truck Mechanics" width="230" style="display: block; width: 100%; max-width: 230px; height: auto; border: 0;" />
                                </div>
                              </td>
                            </tr>
                          </table>
                        </td>
                      </tr>
                    </table>
                  </td>
                </tr>
                <tr>
                  <td align="center" style="padding-top: 14px; padding-bottom: 10px; font-size: 13px; color: #718096; font-style: italic;">SocialSolidarity Food Truck Cohort in Action</td>
                </tr>
              </table>
            </td>
          </tr>
          <tr>
            <td class="footer-padding" style="padding: 24px 40px 35px 40px; background-color: #fcfdfe; border-top: 1px solid #edf2f7; font-size: 12px; line-height: 1.6; color: #718096;">
              <table border="0" cellpadding="0" cellspacing="0" width="100%">
                <tr>
                  <td>
                    <p style="margin: 0 0 10px 0;">This email was sent to confirm your outreach pledge. If you received this in error, please reply directly to this address.</p>
                    <p style="margin: 0; font-weight: 500;">The SocialSolidarity Foundation is a registered 501(c)(3) tax-exempt nonprofit organization.<br /><strong>EIN:</strong> 85-1446734 &bull; <strong>Web:</strong> <a href="https://socialsolidarity.foundation" target="_blank" style="color: #D22630; text-decoration: none; font-weight: 600;">socialsolidarity.foundation</a></p>
                  </td>
                </tr>
              </table>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""
                                
                                logger.info(f"Sending HTML sponsorship email to: {donor_email}...")
                                email_success = gmail_client.send_email(donor_email, subject, body_html, is_html=True)
                                if email_success:
                                    logger.info(f"✅ Automated email sent successfully to {donor_email}")
                                else:
                                    logger.error(f"❌ Failed to send email to {donor_email}")
                                    
                            tool_response = {
                                "tool_response": {
                                    "function_responses": [
                                        {
                                            "response": {
                                                "output": {
                                                    "success": csv_success, 
                                                    "email_sent": email_success,
                                                    "status": "recorded_and_notified"
                                                }
                                            },
                                            "id": call_id
                                        }
                                    ]
                                }
                            }
                            await gemini_ws.send(json.dumps(tool_response))
                            logger.info("Sent tool response confirmation back to Gemini.")
                    continue
                
                if "interruption" in response_data:
                    logger.info("⚡ Gemini Interruption detected! Telling Telnyx to clear output buffer.")
                    telnyx_clear_payload = {
                        "event": "clear",
                        "stream_id": stream_id
                    }
                    await websocket.send_text(json.dumps(telnyx_clear_payload))
                    continue
                
                server_content = response_data.get("serverContent", {})
                model_turn = server_content.get("modelTurn", {})
                parts = model_turn.get("parts", [])
                
                for part in parts:
                    inline_data = part.get("inlineData", {})
                    mime = inline_data.get("mimeType", "")
                    if "audio/pcm;rate=24000" in mime or "audio/pcm" in mime:
                        raw_24khz_audio = base64.b64decode(inline_data["data"])
                        pcm_8khz = downsample_24khz_to_8khz(raw_24khz_audio)
                        ulaw_audio = audioop.lin2ulaw(pcm_8khz, 2)
                        
                        telnyx_payload = {
                            "event": "media",
                            "media": {
                                "payload": base64.b64encode(ulaw_audio).decode("utf-8")
                            }
                        }
                        await websocket.send_text(json.dumps(telnyx_payload))
                        packets_from_gemini += 1
                        if packets_from_gemini % 50 == 0:
                            logger.info(f"🔊 Sent {packets_from_gemini} audio packets back to Telnyx")
        except Exception as e:
            logger.info(f"Gemini socket read loop completed/closed: {repr(e)}")
        finally:
            session_active.clear()

    # Silence watchdog loop
    async def silence_watchdog():
        nonlocal has_warned_silence
        try:
            while session_active.is_set():
                await asyncio.sleep(1.0)
                elapsed = time.time() - last_audio_time
                
                if elapsed > 25.0 and not has_warned_silence:
                    logger.info("⏳ 25 seconds of silence detected. Injecting check-in prompt.")
                    has_warned_silence = True
                    text_prompt = {
                        "client_content": {
                            "turns": [
                                {
                                    "role": "user",
                                    "parts": [{"text": "[User has been silent for 25 seconds. Ask them gently if they are still on the line with you.]"}]
                                }
                            ],
                            "turn_complete": True
                        }
                    }
                    await gemini_ws.send(json.dumps(text_prompt))
                    
                if elapsed > 60.0:
                    logger.info("⏳ 60 seconds of silence detected. Auto-disconnecting call.")
                    await hangup_call_via_telnyx(call_control_id)
                    break
        except Exception as e:
            logger.error(f"Error in silence watchdog: {repr(e)}")
        finally:
            session_active.clear()

    tasks = [
        asyncio.create_task(read_telnyx()),
        asyncio.create_task(write_gemini()),
        asyncio.create_task(read_gemini_and_write_telnyx()),
        asyncio.create_task(silence_watchdog())
    ]
    
    while session_active.is_set():
        await asyncio.sleep(0.1)
        
    logger.info("Cleaning up conversational bridge tasks and closing all endpoints.")
    for task in tasks:
        task.cancel()
        
    try:
        await gemini_ws.close()
    except Exception:
        pass
    try:
        await websocket.close()
    except Exception:
        pass

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8002)
