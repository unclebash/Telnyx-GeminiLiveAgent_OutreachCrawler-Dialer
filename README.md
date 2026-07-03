# Real-Time Non-Profit Fundraiser Voice Agent & Dialer

An autonomous voice outreach system that combines **Telnyx Call Control**, **Google Gemini Live API (WebSockets)**, and automated **Gmail OAuth2 dispatching** to dial prospects, hold conversation, greet them by name, and automatically send brand-aligned donation payment emails when requested.

## System Architecture

```
                                  +----------------------+
                                  |                      |
                                  |     Telnyx VoIP      |
                                  |                      |
                                  +----------+-----------+
                                             |
                                  Call Webhooks (HTTP POST)
                                  Media stream (WSS)
                                             |
                                             v
+--------------------------+      +----------+-----------+
|                          |      |                      |
|       Uvicorn / FastAPI  | <--->|      GCE VM Bridge   |
|       (Local VM Stack)   |      |                      |
|                          |      +----------+-----------+
+--------------------------+                 |
                                             | WebSocket Connection
                                             | (Audio / PCM)
                                             v
                                  +----------+-----------+
                                  |                      |
                                  |  Gemini Live API     |
                                  |                      |
                                  +----------------------+
```

1. **Paced Outbound Dialer (`run_campaign_dialer.py`)**: Runs an asynchronous worker queue dialing contacts sequentially with custom concurrency pacing and safety breathers to prevent VoIP threshold locks.
2. **GCE Media Bridge Server (`gce_bridge_v3.py`)**: Accepts real-time media streams from Telnyx, converts audio encoding, and bridges full-duplex communication with Gemini Live. 
3. **Answering Machine Detection (AMD)**: Dropping voicemail machines instantly within 3 seconds of connection, preserving account funds.
4. **Outreach Emailer (`gmail_sender.py`)**: Automatically registers leads and dispatches custom-styled brand templates containing Stripe checkout links directly via the Gmail API.

---

## ⚠️ Important VoIP & SMS Notice: 10DLC Registration

> [!WARNING]
> Automated outreach systems dialing US numbers are subject to strict regulations. To run campaigns over carriers without having numbers blocked, filtered, or flagged as "Potential Spam", you **must** register your Brand and Campaign under **10DLC (10-Digit Long Code)** guidelines inside your Telnyx Mission Control Portal. 
> - SMS messaging requires an approved 10DLC Campaign TCR registration.
> - Voice calls require STIR/SHAKEN attestation and CNAM branding matching your registered 501(c)(3) entity.

---

## Getting Started

### 1. Configuration
Copy `.env.example` to `.env` and fill out your variables:
```ini
TELNYX_API_KEY=your_telnyx_key_here
TELNYX_PUBLIC_KEY=your_telnyx_public_key_here
GEMINI_API_KEY=your_gemini_key_here
```

### 2. Deploy Bridge Server
Deploy to Google Compute Engine (or any public server with a static IP and SSL certificate):
```bash
./deploy_vm.sh
```

### 3. Run Dialer Campaign
```bash
python3 run_campaign_dialer.py
```

## Non-Dialer Email Pack
If you want to bypass voice outreach entirely and run simple automated HTML email updates from your Gmail account, see the standalone package in the `/no_dial_email_pack` directory.
