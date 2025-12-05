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
from google.adk.tools import exit_loop 

# Enable for Debugging Logs.
  # from google.adk.plugins.logging_plugin import LoggingPlugin
  # logging.basicConfig(
  #     level=logging.DEBUG,  # <--- This is the key switch
  #     format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
  # )
  # logging.getLogger('google.adk').setLevel(logging.DEBUG)


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

# --- 2. DEFINE AGENTS ---

# Agent 1: Architect output JSON structured plan.
# Role: Analyzes scene, creates plan, does NOT write code.
architect_agent = LlmAgent(
    name="Architect",
    model=MODEL_NAME,
    generate_content_config= types.GenerateContentConfig(
    max_output_tokens=5000,
    temperature=0.3,
    ),

    instruction="""
    You are an Expert Architect/Planner for creating a Blender Geometry Node Setup.
    Goal: Analyze the user request and create a technical plan for it.
    
    Steps:
    1. CALL 'get_current_context' tool to understand the active object and it's current state.
    2. If, don't find any applied Gometry Node Modifier on the active object:
        - Then, only CALL 'ensure_geo_modifier' tool.
    3. CALL 'get_node_tree_json' tool with active object name to understand it's current node tree structure.
    4. Based on the user request and results of Step 1, 2, and 3. DESIGN a step-by-step plan in JSON to implement the required Geometry Nodes setup. .
    
     JSON Structure:
    {
      "objective": "Brief summary of plan",
      "details": ["object_name", "geometry_node_modifier_name", "node_tree_name"],
      "required_nodes": ["List_Of_Node_Names", "..."],
      "plan_steps": ["plan_step 1 logic", "plan_step 2 logic", "..."]
    }

    Only do this, when you have no other choice:
       - If you unsure of node names, their parameters, and details that you need to add, then CALL 'search_node_types' and 'get_node_details' tools to get the list of nodes and their parameters.
    
    Constraints:
    - Just output the JSON plan as per the structure above.
    - Do NOT write any code here.
    """,
    tools=[blender_mcp_toolset],
    output_key="technical_plan"
)

# Agent 2: Developer (Combines Scripter, Executor, and Debugger)
# Role: Writes code, Runs it, Fixes it.
developer_agent = LlmAgent(
    name="Developer",
    model=MODEL_NAME,
    generate_content_config= types.GenerateContentConfig(
    max_output_tokens=5000,
    temperature=0.3,
    ),
    instruction="""
    You are an Expert Python script developer for Blender geometry node setup "only".
    
    Steps:
      1. Read this json 'technical plan'- {technical_plan}.
      2. WRITE a python script based on the plan.
      3. IMMEDIATELY call the 'execute_script' tool with the script.
      4. ANALYZE the result:
         - If return is "Success".
             - Call 'exit_loop' tool.
         - If return is an Error (e.g., AttributeError, NameError):
             - Then, try to solve the error in the next response iteration.

    Constraints:
    - Don't add any dangerous imports (os, subprocess) and other (unsafe code and unuseful code).
    - Don't add code which can break or crash the blender.
    - Focus only on Geometry Nodes related code.
    """,
    output_key="Script",
    tools=[blender_mcp_toolset, exit_loop],
)

# --- 3. PIPELINE SETUP ---

# The Developer talks to itself (and the tools) until it succeeds or hits the limit.
coding_loop = LoopAgent(
    name="DevLoop",
    sub_agents=[developer_agent],
    max_iterations=3  # Allow 3 attempts to fix bugs
)

# Linear flow: Plan -> Build
main_pipeline = SequentialAgent(
    name="FastBlenderPipeline",
    sub_agents=[architect_agent, coding_loop]
)

# --- 4. RUNNER ---
session_service = InMemorySessionService()
runner = Runner(
    agent=main_pipeline,
    app_name="BlenderAgentService",
    session_service=session_service, 
    # plugins=[LoggingPlugin()],   # Enable for Debugging Logs.
)

# --- 5. PUBLIC API ---

async def run_blender_pipeline(user_prompt: str):
    """
    Entry point for the FastAPI server or UI.
    """
    try:
        # Construct the initial prompt
        full_prompt = f"""
        User Request: {user_prompt}
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
                "text": "Task finished.", 
                "code": None, 
                "status": "COMPLETED"
            }
            
    except Exception as e:
        logger.error(f"Pipeline Error: {e}", exc_info=True)
        return {"text": f"Critical Error: {str(e)}", "status": "ERROR"}
