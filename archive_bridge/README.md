# FASTAPI BRIDGE ARCHIVE (SUMMARY)

### 1. Goal
Provide a real-time bidirectional audio bridge between Telnyx PSTN phone calls and Google's Gemini Live API (WebSocket-to-WebSocket).

### 2. Pipeline Layout
```
Telnyx Carrier (G.711 PCMU 8kHz) 
  <-- WebSocket Secure (WSS) --> 
FastAPI Bridge Server (Transcoder: audioop G.711 <-> L16 PCM 16kHz)
  <-- WebSocket Secure (WSS) --> 
Gemini Live API (v1beta bidiGenerateContent; gemini-3.1-flash-live-preview)
```

### 3. Critical Learnings
* **DNS Caching Failure:** Carrier media servers (Telnyx) aggressively cache DNS. Tunnels (Ngrok, Cloudflare) and dynamic IP platforms (default Cloud Run `*.run.app`) frequently fail with error `90046 (Media Streaming failed: Failed to connect to destination)` due to cache mismatches.
* **Solution Requirements:** The bridge server *must* bind to a permanent, static external IP address (e.g., Compute Engine VM) to avoid DNS routing errors.
* **API Details:** Gemini Live requires `gemini-3.1-flash-live-preview` or `gemini-2.0-flash` on `v1beta` with camelCase JSON schemas. Telnyx requires `stream_bidirectional_mode="rtp"` and `stream_bidirectional_codec="PCMU"` in `streaming_start` payload.
