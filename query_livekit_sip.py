import os
import asyncio
from dotenv import load_dotenv
from livekit import api

# Load environment variables
if os.path.exists(".env"):
    load_dotenv(".env")
else:
    load_dotenv()

async def query_livekit_sip():
    lk_url = os.environ.get("LIVEKIT_URL")
    lk_api_key = os.environ.get("LIVEKIT_API_KEY")
    lk_api_secret = os.environ.get("LIVEKIT_API_SECRET")
    
    if not lk_url or not lk_api_key or not lk_api_secret:
        print("Error: Missing LiveKit environment variables.")
        return
        
    api_url = lk_url.replace("wss://", "https://").replace("ws://", "http://")
    print(f"Connecting to LiveKit Cloud: {api_url}")
    
    async with api.LiveKitAPI(url=api_url, api_key=lk_api_key, api_secret=lk_api_secret) as lkapi:
        # Fetch SIP Inbound Trunks
        print("\n--- Configured SIP Inbound Trunks ---")
        try:
            inbound_resp = await lkapi.sip.list_inbound_trunk(api.ListSIPInboundTrunkRequest())
            trunks = inbound_resp.items
            if not trunks:
                print("No SIP inbound trunks found.")
            for i, trunk in enumerate(trunks):
                print(f"Inbound Trunk #{i+1}:")
                print(f"  SIP Trunk ID: {trunk.sip_trunk_id}")
                print(f"  Inbound Address: {trunk.inbound_addresses}")
                print(f"  Supported Numbers: {trunk.numbers}")
        except Exception as e:
            print(f"Error fetching SIP Inbound Trunks: {repr(e)}")
            
        # Fetch SIP Outbound Trunks
        print("\n--- Configured SIP Outbound Trunks ---")
        try:
            outbound_resp = await lkapi.sip.list_outbound_trunk(api.ListSIPOutboundTrunkRequest())
            trunks = outbound_resp.items
            if not trunks:
                print("No SIP outbound trunks found.")
            for i, trunk in enumerate(trunks):
                print(f"Outbound Trunk #{i+1}:")
                print(f"  SIP Trunk ID: {trunk.sip_trunk_id}")
                print(f"  Outbound Address: {trunk.address}")
                print(f"  Outbound Username: {trunk.auth_username}")
                print(f"  Supported Numbers: {trunk.numbers}")
        except Exception as e:
            print(f"Error fetching SIP Outbound Trunks: {repr(e)}")
            
        # Fetch SIP Dispatch Rules
        print("\n--- Configured SIP Dispatch Rules ---")
        try:
            rules_resp = await lkapi.sip.list_dispatch_rule(api.ListSIPDispatchRuleRequest())
            rules = rules_resp.items
            if not rules:
                print("No SIP dispatch rules found.")
            for i, rule in enumerate(rules):
                print(f"Rule #{i+1}:")
                print(f"  Rule ID: {rule.sip_dispatch_rule_id}")
                print(f"  Rule Name: {rule.name}")
                print(f"  Trunk IDs: {rule.sip_trunk_ids}")
                print(f"  Rule Spec: {rule.rule}")
        except Exception as e:
            print(f"Error fetching SIP Dispatch Rules: {repr(e)}")

if __name__ == "__main__":
    asyncio.run(query_livekit_sip())
