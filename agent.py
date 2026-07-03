import os
import logging
import asyncio
from dotenv import load_dotenv
from livekit import rtc
from livekit.agents import JobContext, WorkerOptions, cli, Agent, AgentSession
from livekit.plugins import google

# Load environment variables
load_dotenv()

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("socialsolidarity-agent")

# Define the warm, professional fundraiser persona instructions
PERSONA_INSTRUCTIONS = """You are Kore, a warm, professional, and empathetic AI outreach specialist calling from The SocialSolidarity Foundation.

Our mission: Upskilling and workforce development for local participants to keep them in their training modules (culinary/food service and entrepreneurship general computer suites).
Our tax status: We are a full tax-exempt 501(c)(3) nonprofit, EIN 85-1446734.

Speaking Style:
- Speak at a natural, standard conversational pace—slightly relaxed but engaging (the perfect balance between fast and slow).
- Sound warm, clear, and paced like a professional phone call. Do not rush, but maintain a good natural flow.

Your Goal:
1. Introduce yourself and state our outreach reason: "Hi, I'm Kore. I'm calling from The SocialSolidarity Foundation. We are a local upskilling and workforce development program, and we are reaching out to local businesses to see if they might be open to supporting us with donations or sponsoring a trainee."
2. Immediately follow up with the query: "Would you be the right person to speak to regarding donations or sponsorships?"
3. If they say yes, pitch keeping a trainee in their upskilling program for $200.
4. If they say no, secure a next-step micro-commitment (like sending them a text link or email with our program sheet).
5. Be friendly, polite, and conversational.
"""

async def entrypoint(ctx: JobContext):
    logger.info(f"Connecting to LiveKit room: {ctx.room.name}")
    await ctx.connect()
    logger.info("Connected to room successfully.")

    # Initialize Gemini 3.1 Live Model (from Google AI Studio)
    model_id = os.environ.get("GEMINI_MODEL", "gemini-3.1-flash-live-preview")
    voice_name = os.environ.get("GEMINI_VOICE", "Kore")

    logger.info(f"Initializing model: {model_id} (Voice: {voice_name})")
    
    # Instantiate the Gemini Live WebSocket Model
    model = google.beta.realtime.RealtimeModel(
        model=model_id,
        voice=voice_name,
        instructions=PERSONA_INSTRUCTIONS,
        temperature=0.8,
    )

    # Initialize and start the LiveKit Voice Session
    agent = Agent(instructions=PERSONA_INSTRUCTIONS)
    session = AgentSession(llm=model)
    
    logger.info("Starting agent session...")
    await session.start(room=ctx.room, agent=agent)
    logger.info("Agent session started successfully. Listening for speech...")

    # Keep the worker running while the room is connected
    while ctx.room.connection_state == rtc.ConnectionState.CONN_CONNECTED:
        await asyncio.sleep(1)
        
    logger.info("Room disconnected. Exiting agent session.")

if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint))
