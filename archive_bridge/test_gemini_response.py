import os
import json
import asyncio
import base64
import wave
import websockets
from dotenv import load_dotenv

if os.path.exists(".env"):
    load_dotenv(".env")
else:
    load_dotenv()

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")

PERSONA_INSTRUCTIONS = """You are Kore, a warm, professional, and empathetic AI outreach specialist calling from The SocialSolidarity Foundation.
Our mission: Upskilling and workforce development.
"""

async def run_gemini_sandbox():
    print("=" * 60)
    print("🧪 GEMINI LIVE API AUDIO RESPONDER SANDBOX")
    print("=" * 60)
    
    if not GEMINI_API_KEY:
        print("🔴 ERROR: GEMINI_API_KEY not found in .env.")
        return

    model = GEMINI_MODEL
    if "/" not in model:
        model = f"models/{model}"

    url = f"wss://generativelanguage.googleapis.com/ws/google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContent?key={GEMINI_API_KEY}"
    
    setup_message = {
        "setup": {
          "model": model,
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

    # Text initiation to trigger a response
    initiate_message = {
        "client_content": {
            "turns": [
                {
                    "role": "user",
                    "parts": [
                        {
                            "text": "Hello! Can you introduce yourself?"
                        }
                    ]
                }
            ],
            "turn_complete": True
        }
    }

    audio_chunks = []
    
    try:
        print("[*] Connecting to Gemini Live API WebSocket...")
        async with websockets.connect(url) as ws:
            print("🟢 Connected! Sending setup configuration...")
            await ws.send(json.dumps(setup_message))
            
            # Wait a brief moment for setup to process
            await asyncio.sleep(0.5)
            
            print("[*] Sending conversation trigger text: 'Hello! Can you introduce yourself?'...")
            await ws.send(json.dumps(initiate_message))
            
            print("[*] Waiting for Gemini to reply with audio...")
            start_time = asyncio.get_event_loop().time()
            
            # Listen to capture the response
            while asyncio.get_event_loop().time() - start_time < 8:
                try:
                    # Timeout after 2 seconds if no message is received
                    message = await asyncio.wait_for(ws.recv(), timeout=2.5)
                    response_data = json.loads(message)
                    print(f"DEBUG: Received message from Gemini: {json.dumps(response_data)[:200]}...")
                    
                    if "error" in response_data:
                        print(f"🔴 ERROR from Gemini API: {response_data['error']}")
                        break
                        
                    server_content = response_data.get("server_content", {})
                    model_turn = server_content.get("model_turn", {})
                    parts = model_turn.get("parts", [])
                    
                    for part in parts:
                        inline_data = part.get("inline_data", {})
                        if inline_data.get("mime_type") == "audio/pcm":
                            raw_audio = base64.b64decode(inline_data["data"])
                            audio_chunks.append(raw_audio)
                            print(f"🔊 Received audio chunk: {len(raw_audio)} bytes")
                            
                except asyncio.TimeoutError:
                    if len(audio_chunks) > 0:
                        print("[*] Silence detected, response ended.")
                        break
                    continue
            
            if len(audio_chunks) > 0:
                print(f"🟢 SUCCESS: Received a total of {len(audio_chunks)} audio chunks from Gemini!")
                
                # Combine all raw PCM bytes (Gemini Live outputs 24kHz 16-bit Mono PCM)
                combined_pcm = b"".join(audio_chunks)
                output_filename = "gemini_response.wav"
                
                # Write to standard WAV format
                with wave.open(output_filename, "wb") as wav_file:
                    wav_file.setnchannels(1)       # Mono
                    wav_file.setsampwidth(2)      # 16-bit
                    wav_file.setframerate(24000)  # 24kHz
                    wav_file.writeframes(combined_pcm)
                
                print(f"💾 Saved response audio to: [gemini_response.wav](file://{os.path.abspath(output_filename)})")
                print("[*] You can play this WAV file on your Mac to hear Kore's actual voice!")
            else:
                print("🔴 FAILURE: Connected and triggered, but received no audio chunks from Gemini.")
                
    except Exception as e:
        print(f"🔴 ERROR: Connection failed: {repr(e)}")

if __name__ == "__main__":
    asyncio.run(run_gemini_sandbox())
