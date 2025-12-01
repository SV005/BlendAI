# agent_service/src/main.py
import os
import logging
import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from dotenv import load_dotenv

# Import the Google ADK Agent Pipeline
# Ensure 'agent_service/src/agents_adk.py' exists!
from .agents_adk import run_blender_pipeline

# Load environment variables (e.g. GOOGLE_API_KEY from .env)
load_dotenv()

# Configure Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("BlenderAgentService")

# Initialize FastAPI
app = FastAPI(title="Blender AI Agent Service")

# --- Data Models ---
class ChatRequest(BaseModel):
    prompt: str
    history: list = []  # Optional conversation history

class ChatResponse(BaseModel):
    text: str
    code: str | None = None
    status: str | None = None

# --- Routes ---

@app.get("/health")
async def health_check():
    """Check if the service is running and API key is present."""
    has_key = bool(os.environ.get("GEMINI_API_KEY"))
    return {
        "status": "active", 
        "agent_framework": "google-adk", 
        "api_key_set": has_key
    }

@app.post("/chat", response_model=ChatResponse)
async def chat_endpoint(request: ChatRequest):
    """
    Main Endpoint: Blender Addon -> FastAPI -> Google ADK Agent -> Blender Bridge
    """
    logger.info(f"Received Request: {request.prompt}")
    
    # 1. Security Check
    if not os.environ.get("GEMINI_API_KEY"):
        logger.error("GEMINI_API_KEY is missing!")
        raise HTTPException(
            status_code=500, 
            detail="Server Error: GEMINI_API_KEY not found in environment."
        )

    try:
        # 2. Run the ADK Agent Pipeline (Sequential + Loop)
        # This function (from agents_adk.py) handles Planning -> Researching -> Coding -> Execution
        result = await run_blender_pipeline(request.prompt)
        
        # 3. Return Result
        return {
            "text": result.get("text", "Task completed."),
            "code": result.get("code"),
            "status": result.get("status", "SUCCESS")
        }

    except Exception as e:
        logger.error(f"Agent Pipeline Failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    # Run the server
    print("--- Starting Blender AI Agent Service (ADK Powered) ---")
    print("Listening on http://127.0.0.1:8000")
    uvicorn.run(app, host="127.0.0.1", port=8000)
