import os
import asyncio
from dotenv import load_dotenv
from livekit import api

if os.path.exists(".env"):
    load_dotenv(".env")
else:
    load_dotenv()

async def get_participant_status(room_name, participant_identity):
    lk_url = os.environ.get("LIVEKIT_URL")
    lk_api_key = os.environ.get("LIVEKIT_API_KEY")
    lk_api_secret = os.environ.get("LIVEKIT_API_SECRET")
    
    api_url = lk_url.replace("wss://", "https://").replace("ws://", "http://")
    
    async with api.LiveKitAPI(url=api_url, api_key=lk_api_key, api_secret=lk_api_secret) as lkapi:
        try:
            print(f"Retrieving participant info for {participant_identity} in room {room_name}...")
            resp = await lkapi.room.get_participant(
                api.RoomParticipantIdentity(room=room_name, identity=participant_identity)
            )
            print("\n--- Participant Info ---")
            print(f"Identity: {resp.identity}")
            print(f"State: {resp.state}") # 0 = JOINED, 1 = RECONNECTING, etc.
            print(f"Name: {resp.name}")
            print(f"Metadata: {resp.metadata}")
            print(f"Attributes: {resp.attributes}")
        except Exception as e:
            print(f"Error retrieving participant info: {repr(e)}")

if __name__ == "__main__":
    import sys
    room = sys.argv[1] if len(sys.argv) > 1 else "ai-outbound-1782824730"
    identity = sys.argv[2] if len(sys.argv) > 2 else "phone_15624477303"
    asyncio.run(get_participant_status(room, identity))
