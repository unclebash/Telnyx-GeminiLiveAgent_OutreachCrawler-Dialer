import os
import sys
import sqlite3
import asyncio
import logging
from dotenv import load_dotenv
from livekit import api

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("automated-dialer")

# Load environment variables
# Check local directory first, then fallback to parent if needed
if os.path.exists(".env"):
    load_dotenv(".env")
else:
    load_dotenv()

DB_PATH = "fundraiser.db"

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

async def dial_lead(lead_id: int):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM organizations WHERE id = ?", (lead_id,))
    lead = cursor.fetchone()
    
    if not lead:
        logger.error(f"Lead ID {lead_id} not found in database.")
        conn.close()
        return False
        
    phone_number = lead["phone"]
    company_name = lead["name"]
    
    if not phone_number:
        logger.error(f"Lead '{company_name}' (ID: {lead_id}) has no phone number.")
        cursor.execute("UPDATE organizations SET status = 'No Phone' WHERE id = ?", (lead_id,))
        conn.commit()
        conn.close()
        return False

    # Clean target phone number
    clean_number = "".join(filter(str.isdigit, phone_number))
    if len(clean_number) == 10:
        clean_number = "1" + clean_number
        
    if not clean_number or len(clean_number) < 10:
        logger.error(f"Invalid phone number '{phone_number}' for lead '{company_name}'.")
        cursor.execute("UPDATE organizations SET status = 'Invalid Phone' WHERE id = ?", (lead_id,))
        conn.commit()
        conn.close()
        return False

    # Load and clean Caller ID / DID number
    from_number = os.environ.get("VOIPMS_DID_NUMBER")
    if not from_number:
        logger.error("Missing VOIPMS_DID_NUMBER in environment variables.")
        conn.close()
        return False
        
    clean_from = "".join(filter(str.isdigit, from_number))
    if len(clean_from) == 10:
        clean_from = "1" + clean_from

    lk_url = os.environ.get("LIVEKIT_URL")
    lk_api_key = os.environ.get("LIVEKIT_API_KEY")
    lk_api_secret = os.environ.get("LIVEKIT_API_SECRET")
    sip_trunk_id = os.environ.get("LIVEKIT_SIP_TRUNK_ID", "ST_R9UjM4JGhhfR")

    if not lk_url or not lk_api_key or not lk_api_secret:
        logger.error("Missing LiveKit API credentials (URL, Key, Secret) in environment.")
        conn.close()
        return False

    import time
    room_name = f"gemini-call-{lead_id}-{int(time.time())}"

    logger.info(f"☎️ Dialing Lead: {company_name} ({clean_number})")
    logger.info(f"   Trunk: {sip_trunk_id} | Caller ID: {clean_from} | Room: {room_name}")

    api_url = lk_url.replace("wss://", "https://").replace("ws://", "http://")
    
    try:
        async with api.LiveKitAPI(url=api_url, api_key=lk_api_key, api_secret=lk_api_secret) as lkapi:
            request = api.CreateSIPParticipantRequest(
                sip_trunk_id=sip_trunk_id,
                sip_number=clean_from,
                sip_call_to=clean_number,
                room_name=room_name,
                participant_identity=f"phone_{clean_number}",
                participant_name=company_name[:60]
            )
            
            logger.info("Sending SIP Invite request via LiveKit...")
            participant = await lkapi.sip.create_sip_participant(request)
            
            logger.info(f"✅ SIP Call initiated successfully!")
            logger.info(f"   Participant ID: {participant.participant_id}")
            logger.info(f"   SIP Call ID: {participant.sip_call_id}")
            
            # Update database
            cursor.execute("UPDATE organizations SET status = 'Called' WHERE id = ?", (lead_id,))
            cursor.execute(
                "INSERT INTO outbound_calls (organization_id, outcome, notes) VALUES (?, 'Initiated', ?)",
                (lead_id, f"LiveKit Room: {room_name}, Call ID: {participant.sip_call_id}")
            )
            conn.commit()
            conn.close()
            return True
            
    except Exception as e:
        logger.error(f"❌ Failed to initiate SIP call: {repr(e)}")
        conn.close()
        return False

async def dial_next_pending():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, name FROM organizations WHERE status = 'Pending' LIMIT 1")
    row = cursor.fetchone()
    conn.close()
    
    if not row:
        logger.info("🎉 No pending leads remaining in the database!")
        return False
        
    lead_id = row["id"]
    return await dial_lead(lead_id)

if __name__ == "__main__":
    if len(sys.argv) > 1:
        if sys.argv[1].isdigit():
            lead_id = int(sys.argv[1])
            asyncio.run(dial_lead(lead_id))
        else:
            print("Usage: python3 automated_dialer.py [lead_id]")
            print("Omit lead_id to dial the next pending lead in the database.")
    else:
        asyncio.run(dial_next_pending())
