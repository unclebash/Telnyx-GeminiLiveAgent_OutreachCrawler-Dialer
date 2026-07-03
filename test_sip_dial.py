import os
import sys
import asyncio
from dotenv import load_dotenv
from livekit import api

# Load environment variables
load_dotenv()

async def make_sip_call(phone_number: str):
    lk_url = os.environ.get("LIVEKIT_URL")
    lk_api_key = os.environ.get("LIVEKIT_API_KEY")
    lk_api_secret = os.environ.get("LIVEKIT_API_SECRET")
    voipms_username = os.environ.get("VOIPMS_API_USERNAME")
    voipms_password = os.environ.get("VOIPMS_API_PASSWORD")
    voipms_host = os.environ.get("VOIPMS_POP_SERVER")
    from_number = os.environ.get("VOIPMS_DID_NUMBER")

    if not lk_url or not lk_api_key or not lk_api_secret or not voipms_username or not voipms_password or not voipms_host or not from_number:
        print("Error: Missing credentials in .env file.")
        return

    # Clean the Caller ID DID number (for VoIP.ms outbound, format as 11 digits starting with 1 to match DID settings)
    clean_from = "".join(filter(str.isdigit, from_number))
    if len(clean_from) == 10:
        clean_from = "1" + clean_from

    # Clean the target phone number
    clean_number = "".join(filter(str.isdigit, phone_number))
    if not clean_number:
        print("Error: Invalid phone number.")
        return

    # Format destination for VoIP.ms (11 digits starting with 1, no plus sign)
    if len(clean_number) == 10:
        clean_number = "1" + clean_number

    # Generate a dynamic room name using a timestamp to prevent conflicts with old, hung room sessions
    import time
    room_name = f"ai-outbound-{int(time.time())}"

    print("=" * 60)
    print("📞 OUTBOUND SIP DIALER (FROM SCRATCH)")
    print(f"  Target Number : {clean_number}")
    print("  Trunk Type    : Inline Trunk")
    print(f"  LiveKit Room  : {room_name}")
    print("=" * 60)
    # Initialize the LiveKit API client
    # LiveKitAPI url expects http/https endpoint (converts wss:// to https:// automatically)
    # Initialize the LiveKit API client
    # LiveKitAPI url expects http/https endpoint (converts wss:// to https:// automatically)
    api_url = lk_url.replace("wss://", "https://").replace("ws://", "http://")
    
    async with api.LiveKitAPI(url=api_url, api_key=lk_api_key, api_secret=lk_api_secret) as lkapi:
        # Build the SIP call request using the registered Outbound Trunk ID and sub-account username
        request = api.CreateSIPParticipantRequest(
            sip_trunk_id="ST_R9UjM4JGhhfR",
            sip_number=clean_from,
            sip_call_to=clean_number,
            room_name=room_name,
            participant_identity=f"phone_{clean_number}",
            participant_name="Donor Caller"
        )

        try:
            print("Initiating call through LiveKit Cloud...")
            participant = await lkapi.sip.create_sip_participant(request)
            print(f"✅ Call requested successfully!")
            print(f"  Participant ID: {participant.participant_id}")
            print(f"  Room Name     : {participant.room_name}")
            print(f"  SIP Call ID   : {participant.sip_call_id}")
        except Exception as e:
            print(f"❌ Failed to place call: {repr(e)}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 test_sip_dial.py <target_phone_number>")
        sys.exit(1)
    
    asyncio.run(make_sip_call(sys.argv[1]))
