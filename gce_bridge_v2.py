import os
import sys
import json
import base64
import asyncio
import logging
import audioop
import websockets
from fastapi import FastAPI, WebSocket, Request, Response
from fastapi.responses import JSONResponse
from dotenv import load_dotenv

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("telnyx-gemini-bridge-v2")

# Load environment variables
if os.path.exists(".env"):
    load_dotenv(".env")
else:
    load_dotenv()

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.1-flash-live-preview")

# Persona instructions
PERSONA_INSTRUCTIONS = """You are Kore, a warm, professional, and empathetic AI outreach specialist calling from The SocialSolidarity Foundation.

Our mission: Upskilling and workforce development for local participants to keep them in their training modules (culinary/food service and entrepreneurship general computer suites).
Our tax status: We are a full tax-exempt 501(c)(3) nonprofit, EIN 85-1446734.

Speaking Style:
- Speak at a natural, standard conversational pace—slightly relaxed but engaging.
- Sound warm, clear, and paced like a professional phone call.

Your Goal:
1. Introduce yourself and state our outreach reason: "Hi, I'm Kore. I'm calling from The SocialSolidarity Foundation. We are a local upskilling and workforce development program, and we are reaching out to local businesses to see if they might be open to supporting us with donations or sponsoring a trainee."
2. Ask: "Would you be the right person to speak to regarding donations or sponsorships?"
3. If they say yes, pitch keeping a trainee in their upskilling program for $200.
4. If they say no, secure a next-step micro-commitment (like sending them a text link or email).
5. Be friendly, polite, and conversational.
"""

app = FastAPI()

@app.post("/webhook")
async def telnyx_webhook(request: Request):
    """
    Handles Telnyx Call Control Webhook events.
    """
    try:
        body = await request.json()
        event_type = body.get("data", {}).get("event_type")
        call_control_id = body.get("data", {}).get("payload", {}).get("call_control_id")
        
        logger.info(f"Received webhook event: {event_type} (Call Control ID: {call_control_id})")
        
        if event_type == "call.answered":
            host = request.headers.get("host")
            stream_url = f"wss://{host}/media-stream"
            
            logger.info(f"Call answered. Directing Telnyx media stream to: {stream_url}")
            
            telnyx_api_key = os.environ.get("TELNYX_API_KEY")
            url = f"https://api.telnyx.com/v2/calls/{call_control_id}/actions/streaming_start"
            headers = {
                "Authorization": f"Bearer {telnyx_api_key}",
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
                    logger.info(f"Telnyx media stream start response: {response.status_code} - {response.text}")
                    
                    if response.status_code == 200:
                        logger.info("✅ Telnyx media stream started successfully!")
                        break
                    elif response.status_code == 422 and attempt < 3:
                        logger.info("⚠️ Got 422, waiting 1.5 seconds before retrying...")
                        await asyncio.sleep(1.5)
                    else:
                        logger.error(f"❌ Failed to start media stream after multiple attempts: {response.status_code}")
                        break
            
    except Exception as e:
        logger.error(f"Error handling webhook: {repr(e)}")
        
    return Response(status_code=200)

@app.websocket("/media-stream")
async def media_stream_endpoint(websocket: WebSocket):
    """
    Handles non-blocking bidirectional WebSockets between Telnyx Media Stream and Gemini Live API.
    Logs all metadata and events returned by Gemini to diagnose response dropout.
    """
    await websocket.accept()
    logger.info("Telnyx Media Stream connected. Handshake complete.")
    
    audio_queue = asyncio.Queue()
    gemini_url = f"wss://generativelanguage.googleapis.com/ws/google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContent?key={GEMINI_API_KEY}"
    
    async def read_from_telnyx():
        to_gemini_state = None
        try:
            while True:
                message = await websocket.receive_text()
                data = json.loads(message)
                event = data.get("event")
                
                if event == "media":
                    payload_b64 = data["media"]["payload"]
                    ulaw_audio = base64.b64decode(payload_b64)
                    
                    pcm_8khz = audioop.ulaw2lin(ulaw_audio, 2)
                    pcm_16khz, to_gemini_state = audioop.ratecv(
                        pcm_8khz, 2, 1, 8000, 16000, to_gemini_state
                    )
                    await audio_queue.put(pcm_16khz)
        except Exception as e:
            logger.info(f"Telnyx connection closed or read error: {repr(e)}")

    telnyx_reader = asyncio.create_task(read_from_telnyx())
    
    try:
        async with websockets.connect(gemini_url) as gemini_ws:
            logger.info("Connected to Gemini Live API.")
            
            setup_message = {
                "setup": {
                  "model": gemini_model_selector(GEMINI_MODEL),
                  "generation_config": {
                    "response_modalities": ["AUDIO"],
                    "speech_config": {
                      "voice_config": {
                        "prebuilt_voice_config": {
                          "voice_name": "Kore"
                        }
                      }
                    }
                  },
                  "system_instruction": {
                    "parts": [{"text": PERSONA_INSTRUCTIONS}]
                  }
                }
            }
            await gemini_ws.send(json.dumps(setup_message))
            
            setup_confirmed = False
            for _ in range(10):
                try:
                    msg = await asyncio.wait_for(gemini_ws.recv(), timeout=3.0)
                    data = json.loads(msg)
                    if "setupComplete" in data:
                        setup_confirmed = True
                        logger.info("✅ Gemini session setup confirmed (setupComplete received).")
                        break
                except asyncio.TimeoutError:
                    break
            
            if not setup_confirmed:
                logger.error("❌ Never received setupComplete from Gemini. Aborting session.")
                return

            from_gemini_state = None
            packets_to_gemini = 0
            packets_from_gemini = 0

            async def handle_telnyx_to_gemini():
                nonlocal packets_to_gemini
                try:
                    while True:
                        pcm_16khz = await audio_queue.get()
                        gemini_payload = {
                            "realtime_input": {
                                "audio": {
                                    "mime_type": "audio/pcm;rate=16000",
                                    "data": base64.b64encode(pcm_16khz).decode("utf-8")
                                }
                            }
                        }
                        await gemini_ws.send(json.dumps(gemini_payload))
                        packets_to_gemini += 1
                        if packets_to_gemini % 100 == 0:
                            logger.info(f"🎤 Forwarded {packets_to_gemini} audio packets to Gemini")
                except Exception as e:
                    logger.error(f"Error forwarding to Gemini: {repr(e)}")

            async def handle_gemini_to_telnyx():
                nonlocal from_gemini_state, packets_from_gemini
                try:
                    async for message in gemini_ws:
                        response_data = json.loads(message)
                        
                        # LOG EVERYTHING FROM GEMINI (Excluding raw audio content bytes for log cleaniness)
                        debug_log_data = json.loads(message)
                        if "serverContent" in debug_log_data:
                            model_turn = debug_log_data["serverContent"].get("modelTurn", {})
                            for part in model_turn.get("parts", []):
                                if "inlineData" in part:
                                    part["inlineData"]["data"] = f"...<{len(part['inlineData']['data'])} bytes of base64 audio>..."
                            logger.info(f"🔮 Gemini ServerContent: {json.dumps(debug_log_data)}")
                        else:
                            logger.info(f"🔮 Gemini Other Event: {message}")
                        
                        server_content = response_data.get("serverContent", response_data.get("server_content", {}))
                        model_turn = server_content.get("modelTurn", server_content.get("model_turn", {}))
                        parts = model_turn.get("parts", [])
                        
                        for part in parts:
                            inline_data = part.get("inlineData", part.get("inline_data", {}))
                            mime = inline_data.get("mimeType", inline_data.get("mime_type", ""))
                            if "audio/pcm" in mime:
                                raw_gemini_audio = base64.b64decode(inline_data["data"])
                                
                                pcm_8khz, from_gemini_state = audioop.ratecv(
                                    raw_gemini_audio, 2, 1, 24000, 8000, from_gemini_state
                                )
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
                    logger.error(f"Error in Gemini -> Telnyx stream: {repr(e)}")

            telnyx_to_gemini_task = asyncio.create_task(handle_telnyx_to_gemini())
            gemini_to_telnyx_task = asyncio.create_task(handle_gemini_to_telnyx())
            
            done, pending = await asyncio.wait(
                [telnyx_to_gemini_task, gemini_to_telnyx_task],
                return_when=asyncio.FIRST_COMPLETED
            )
            for task in pending:
                task.cancel()
            
    except Exception as e:
        logger.error(f"Bridge connection error: {repr(e)}")
    finally:
        logger.info("Closing media stream connection.")
        telnyx_reader.cancel()
        try:
            await websocket.close()
        except:
            pass

def gemini_model_selector(model_id):
    if "/" not in model_id:
        return f"models/{model_id}"
    return model_id

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8001)
