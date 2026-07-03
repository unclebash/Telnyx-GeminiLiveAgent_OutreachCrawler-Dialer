"""
Tier 2 Sandbox Test: Audio-In → Audio-Out via Gemini Live API

This test simulates exactly what happens on a real phone call:
1. Reads a pre-recorded WAV file (16kHz, 16-bit, mono PCM)
2. Connects to Gemini Live API WebSocket
3. Sends setup config and WAITS for setup_complete
4. Streams the audio in small real-time-like chunks
5. Captures the audio response
6. Saves it to a playable WAV file
"""

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

INPUT_WAV = "/tmp/hello_16k.wav"
OUTPUT_WAV = "gemini_tier2_response.wav"

PERSONA = (
    "You are Kore, a warm and professional outreach specialist from "
    "The SocialSolidarity Foundation. When someone speaks to you, "
    "respond naturally and briefly."
)

# Gemini Live input: 16kHz 16-bit mono
# Gemini Live output: 24kHz 16-bit mono
INPUT_RATE = 16000
OUTPUT_RATE = 24000
CHUNK_DURATION_MS = 100  # send 100ms chunks to simulate real-time
CHUNK_SIZE = INPUT_RATE * 2 * (CHUNK_DURATION_MS // 1000) or (INPUT_RATE * 2 * CHUNK_DURATION_MS) // 1000
# 16000 samples/sec * 2 bytes/sample * 0.1 sec = 3200 bytes per chunk


async def run_tier2_test():
    print("=" * 60)
    print("🧪 TIER 2 SANDBOX: Audio-In → Audio-Out")
    print("=" * 60)

    if not GEMINI_API_KEY:
        print("🔴 GEMINI_API_KEY not set in .env")
        return

    # --- Step 1: Load the input audio ---
    print(f"[1] Loading input audio from {INPUT_WAV}...")
    with wave.open(INPUT_WAV, "rb") as wf:
        assert wf.getnchannels() == 1, "Must be mono"
        assert wf.getsampwidth() == 2, "Must be 16-bit"
        assert wf.getframerate() == INPUT_RATE, f"Must be {INPUT_RATE}Hz"
        raw_pcm = wf.readframes(wf.getnframes())
    duration = len(raw_pcm) / (INPUT_RATE * 2)
    print(f"    ✅ Loaded {len(raw_pcm)} bytes ({duration:.2f}s) of PCM audio.")

    # --- Step 2: Connect to Gemini ---
    model = GEMINI_MODEL if "/" in GEMINI_MODEL else f"models/{GEMINI_MODEL}"
    url = (
        "wss://generativelanguage.googleapis.com/ws/"
        "google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContent"
        f"?key={GEMINI_API_KEY}"
    )

    setup_msg = {
        "setup": {
            "model": model,
            "generation_config": {
                "response_modalities": ["AUDIO"],
                "speech_config": {
                    "voice_config": {
                        "prebuilt_voice_config": {"voice_name": "Kore"}
                    }
                },
            },
            "system_instruction": {"parts": [{"text": PERSONA}]},
        }
    }

    audio_out_chunks = []

    print("[2] Connecting to Gemini Live API...")
    async with websockets.connect(url) as ws:
        print("    ✅ WebSocket connected.")

        # --- Step 3: Send setup and WAIT for setup_complete ---
        print("[3] Sending setup message...")
        await ws.send(json.dumps(setup_msg))

        print("    Waiting for setup_complete acknowledgment...")
        setup_confirmed = False
        for _ in range(10):  # up to 10 messages or 5 seconds
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=5.0)
                data = json.loads(msg)
                print(f"    ← {json.dumps(data)[:150]}")
                if "setupComplete" in data or "setup_complete" in json.dumps(data):
                    setup_confirmed = True
                    print("    ✅ setup_complete received!")
                    break
            except asyncio.TimeoutError:
                break

        if not setup_confirmed:
            print("🔴 FAILURE: Never received setup_complete from Gemini. Aborting.")
            return

        # --- Step 4: Stream audio in chunks ---
        num_chunks = (len(raw_pcm) + CHUNK_SIZE - 1) // CHUNK_SIZE
        print(f"[4] Streaming {num_chunks} audio chunks ({CHUNK_DURATION_MS}ms each)...")

        for i in range(0, len(raw_pcm), CHUNK_SIZE):
            chunk = raw_pcm[i : i + CHUNK_SIZE]
            msg = {
                "realtime_input": {
                    "audio": {
                        "mime_type": f"audio/pcm;rate={INPUT_RATE}",
                        "data": base64.b64encode(chunk).decode("utf-8"),
                    }
                }
            }
            await ws.send(json.dumps(msg))
            # Pace it to approximate real-time delivery
            await asyncio.sleep(CHUNK_DURATION_MS / 1000.0)

        print(f"    ✅ Finished streaming all {num_chunks} chunks.")

        # Signal end of user's turn so Gemini knows to respond
        print("[4b] Sending turn_complete signal...")
        await ws.send(json.dumps({
            "client_content": {
                "turns": [
                    {
                        "role": "user",
                        "parts": [{"text": "Hello, can you hear me? Please introduce yourself."}]
                    }
                ],
                "turn_complete": True
            }
        }))

        # --- Step 5: Listen for audio response ---
        print("[5] Listening for Gemini audio response...")
        silence_count = 0
        while silence_count < 3:  # stop after 3 consecutive timeouts (~7.5s of silence)
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=2.5)
                data = json.loads(msg)
                silence_count = 0  # reset on any message

                sc = data.get("serverContent", data.get("server_content", {}))
                mt = sc.get("modelTurn", sc.get("model_turn", {}))
                parts = mt.get("parts", [])

                for part in parts:
                    inline = part.get("inlineData", part.get("inline_data", {}))
                    mime = inline.get("mimeType", inline.get("mime_type", ""))
                    if "audio/pcm" in mime:
                        pcm = base64.b64decode(inline["data"])
                        audio_out_chunks.append(pcm)
                        print(f"    🔊 Audio chunk received: {len(pcm)} bytes")

                # Check for turn_complete
                turn_complete = sc.get("turnComplete", sc.get("turn_complete", False))
                if turn_complete:
                    print("    ✅ Gemini signaled turn_complete.")
                    break

            except asyncio.TimeoutError:
                silence_count += 1
                if audio_out_chunks:
                    print(f"    ⏳ Silence timeout {silence_count}/3...")

    # --- Step 6: Save and report ---
    print("=" * 60)
    if audio_out_chunks:
        combined = b"".join(audio_out_chunks)
        with wave.open(OUTPUT_WAV, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(OUTPUT_RATE)
            wf.writeframes(combined)

        out_duration = len(combined) / (OUTPUT_RATE * 2)
        print(f"🟢 SUCCESS!")
        print(f"   Input:  {duration:.2f}s of spoken audio sent to Gemini")
        print(f"   Output: {out_duration:.2f}s of spoken audio received back")
        print(f"   Chunks: {len(audio_out_chunks)} audio frames captured")
        print(f"   Saved:  {OUTPUT_WAV}")
        print(f"\n   ▶  Play it:  afplay {OUTPUT_WAV}")
    else:
        print("🔴 FAILURE: Gemini connected and received audio, but sent no audio back.")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(run_tier2_test())
