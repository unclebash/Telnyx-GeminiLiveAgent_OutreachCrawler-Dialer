import os
import asyncio
from dotenv import load_dotenv
from livekit import api

if os.path.exists(".env"):
    load_dotenv(".env")
else:
    load_dotenv()

async def update_trunk_password():
    lk_url = os.environ.get("LIVEKIT_URL")
    lk_api_key = os.environ.get("LIVEKIT_API_KEY")
    lk_api_secret = os.environ.get("LIVEKIT_API_SECRET")
    voipms_password = os.environ.get("VOIPMS_API_PASSWORD")
    
    if not lk_url or not lk_api_key or not lk_api_secret or not voipms_password:
        print("Error: Missing credentials in environment variables.")
        return
        
    api_url = lk_url.replace("wss://", "https://").replace("ws://", "http://")
    
    async with api.LiveKitAPI(url=api_url, api_key=lk_api_key, api_secret=lk_api_secret) as lkapi:
        print("Fetching existing trunks...")
        outbound_resp = await lkapi.sip.list_outbound_trunk(api.ListSIPOutboundTrunkRequest())
        trunks = outbound_resp.items
        
        target_trunk = None
        for trunk in trunks:
            if trunk.sip_trunk_id == "ST_R9UjM4JGhhfR":
                target_trunk = trunk
                break
                
        if not target_trunk:
            print("❌ Error: Outbound Trunk ST_R9UjM4JGhhfR not found in LiveKit Cloud.")
            return
            
        print(f"Syncing password for trunk {target_trunk.sip_trunk_id}...")
        # Update the password field
        target_trunk.auth_password = voipms_password
        
        try:
            # According to signature: update_sip_outbound_trunk(trunk_id, trunk)
            res = await lkapi.sip.update_sip_outbound_trunk(target_trunk.sip_trunk_id, target_trunk)
            print(f"✅ Success! Outbound Trunk password synced in LiveKit Cloud.")
            print(f"   Trunk ID: {res.sip_trunk_id}")
            print(f"   Username: {res.auth_username}")
            print(f"   Address : {res.address}")
        except Exception as e:
            print(f"❌ Failed to update trunk: {repr(e)}")

if __name__ == "__main__":
    asyncio.run(update_trunk_password())
