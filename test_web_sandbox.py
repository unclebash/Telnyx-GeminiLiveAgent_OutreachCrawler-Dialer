import os
import asyncio
import urllib.parse
from dotenv import load_dotenv
from livekit import api

# Load environment variables
load_dotenv()

async def generate_sandbox_link():
    lk_url = os.environ.get("LIVEKIT_URL")
    lk_api_key = os.environ.get("LIVEKIT_API_KEY")
    lk_api_secret = os.environ.get("LIVEKIT_API_SECRET")

    if not lk_url or not lk_api_key or not lk_api_secret:
        print("Error: Missing LiveKit Cloud credentials in .env file.")
        return

    room_name = "ai-outbound-room"
    participant_identity = "web_tester"

    print("=" * 60)
    print("🌐 GENERATING WEB SANDBOX CONNECTION LINK")
    print(f"  LiveKit URL  : {lk_url}")
    print(f"  Room Name    : {room_name}")
    print("=" * 60)

    # Convert WebSocket URL to HTTP/HTTPS for API client
    api_url = lk_url.replace("wss://", "https://").replace("ws://", "http://")
    
    async with api.LiveKitAPI(url=api_url, api_key=lk_api_key, api_secret=lk_api_secret) as lkapi:
        # Create the room if it doesn't exist
        try:
            print("Ensuring room exists...")
            await lkapi.room.create_room(api.CreateRoomRequest(name=room_name))
        except Exception as e:
            # Room might already exist, which is fine
            pass

        # Create connection token for the browser client
        token = api.AccessToken(lk_api_key, lk_api_secret) \
            .with_identity(participant_identity) \
            .with_name("Web Tester") \
            .with_grants(api.VideoGrants(
                room_join=True,
                room=room_name,
                can_publish=True,
                can_subscribe=True,
                can_publish_data=True
            ))
            
        jwt_token = token.to_jwt()

        # Build the official LiveKit Agents Playground URL
        encoded_url = urllib.parse.quote(lk_url)
        encoded_token = urllib.parse.quote(jwt_token)
        playground_url = f"https://agents-playground.livekit.io/?url={encoded_url}&token={encoded_token}"

        print("\n🎉 SANDBOX READY!")
        print("Copy and paste the following link into your web browser:")
        print("-" * 80)
        print(playground_url)
        print("-" * 80)
        print("Once you open this link, click 'Connect' to talk directly to your agent via your mic/speakers!")

if __name__ == "__main__":
    asyncio.run(generate_sandbox_link())
