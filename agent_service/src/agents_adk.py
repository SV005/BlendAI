# agent_service/src/agents_adk.py

import os
import logging
import sys
from typing import Dict

# ADK Imports
from google.adk.agents import LlmAgent, SequentialAgent, LoopAgent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.tools import FunctionTool
from google.adk.tools.tool_context import ToolContext
from google.genai import types

# MCP Integration
from google.adk.tools.mcp_tool.mcp_toolset import McpToolset
from google.adk.tools.mcp_tool.mcp_session_manager import StdioConnectionParams
from mcp import StdioServerParameters

# --- CONFIG & LOGGING ---
MODEL_NAME = "gemini-2.5-flash"
logger = logging.getLogger(__name__)

# Path to your mcp_server.py (assumed to be one level up)
MCP_SERVER_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "mcp_server.py"))

# --- 1. SETUP MCP TOOLSET ---
logger.info(f"Initializing MCP Toolset pointing to: {MCP_SERVER_PATH}")

blender_mcp_toolset = McpToolset(
    connection_params=StdioConnectionParams(
        server_params=StdioServerParameters(
            command=sys.executable,
            args=[MCP_SERVER_PATH],
            env=os.environ.copy()
        ),
        timeout=60,
    )
)

# --- 2. DEFINE SPECIAL TOOLS ---

def finish_task(tool_context: ToolContext) -> Dict:
    """
    Call this tool ONLY when the script has executed successfully 
    and the geometry nodes are working as requested.
    """
    # Signals the loop to stop
    tool_context.actions.escalate = True
    return {"status": "Task Completed Successfully"}

finish_tool = FunctionTool(finish_task)

# --- 3. DEFINE AGENTS ---

# Agent 1: Architect (Optimized for JSON Output)
# Role: Analyzes scene, creates plan, does NOT write code.
architect_agent = LlmAgent(
    name="Architect",
    model=MODEL_NAME,
    instruction="""
    You are a Senior Blender Solutions Architect.
    
    Goal: Analyze the user request and create a technical execution plan.
    
    Steps:
    1. CALL 'get_current_context' to understand the active object.
    2. CALL 'ensure_geo_modifier' to make sure a node tree exists.
    3. Output a plan in STRICT JSON format. Do NOT chat.
    
    JSON Structure:
    {
      "objective": "Brief summary",
      "required_nodes": ["List", "Of", "Node", "Names"],
      "steps": ["Step 1 logic", "Step 2 logic"]
    }
    """,
    tools=[blender_mcp_toolset],
    output_key="technical_plan"
)

# Agent 2: Developer (Combines Scripter, Executor, and Debugger)
# Role: Writes code, Runs it, Fixes it.
developer_agent = LlmAgent(
    name="Developer",
    model=MODEL_NAME,
    instruction="""
    You are an Expert Blender Python Developer.
    
    Input: Read the 'technical_plan'.
    Goal: Create valid Geometry Nodes using the 'bpy' Python API.
    
    Operational Loop:
    1. WRITE & EXECUTE: 
       - Generate the full Python script.
       - IMMEDIATELY call the 'execute_script' tool with this script content.
    
    2. ANALYZE RESULT:
       - If the tool returns "Success":
         - Output the final code in a markdown block.
         - Call 'finish_task'.
       - If the tool returns an Error (e.g., AttributeError, NameError):
         - Use 'search_node_types' if you guessed the wrong node class name.
         - Rewrite the script to fix the bug.
         - Call 'execute_script' again.
         
    Constraints:
    - Use 'bpy.data.node_groups' to find the tree.
    - Always clear default nodes before adding new ones.
    - Link nodes correctly using 'tree.links.new()'.
    """,
    tools=[blender_mcp_toolset, finish_tool],
    output_key="execution_result"
)

# --- 4. PIPELINE SETUP ---

# The Developer talks to itself (and the tools) until it succeeds or hits the limit.
coding_loop = LoopAgent(
    name="DevLoop",
    sub_agents=[developer_agent],
    max_iterations=5  # Allow 5 attempts to fix bugs
)

# Linear flow: Plan -> Build
main_pipeline = SequentialAgent(
    name="FastBlenderPipeline",
    sub_agents=[architect_agent, coding_loop]
)

# --- 5. RUNNER ---
session_service = InMemorySessionService()
runner = Runner(
    agent=main_pipeline,
    app_name="BlenderAgentService",
    session_service=session_service
)

# --- 6. PUBLIC API ---

async def run_blender_pipeline(user_prompt: str):
    """
    Entry point for the FastAPI server or UI.
    """
    try:
        # Construct the initial prompt
        full_prompt = f"""
        User Request: {user_prompt}
        
        System Note: 
        - Check 'get_current_context' first.
        - If the user asks for something complex, break it down in the plan.
        """
        
        message = types.Content(role="user", parts=[types.Part(text=full_prompt)])
        
        # Create a fresh session
        session = await session_service.create_session(
            app_name=runner.app_name,
            user_id="local_user",
            session_id=f"session-{os.urandom(4).hex()}"
        )
        
        last_script = None
        final_text = ""
        
        logger.info(f"Starting Pipeline for session: {session.id}")
        
        async for event in runner.run_async(
            user_id=session.user_id,
            session_id=session.id,
            new_message=message
        ):
            # Capture output streaming
            if event.content and event.content.parts:
                for part in event.content.parts:
                    if part.text:
                        text_chunk = part.text
                        final_text = text_chunk
                        
                        # Simple heuristic to grab the final code block
                        if "import bpy" in text_chunk:
                            last_script = text_chunk

        # Return the result
        if last_script:
            return {
                "text": "Task Completed Successfully.", 
                "code": last_script, 
                "status": "SUCCESS"
            }
        else:
            return {
                "text": final_text or "Task finished (no code detected).", 
                "code": None, 
                "status": "COMPLETED"
            }
            
    except Exception as e:
        logger.error(f"Pipeline Error: {e}", exc_info=True)
        return {"text": f"Critical Error: {str(e)}", "status": "ERROR"}
