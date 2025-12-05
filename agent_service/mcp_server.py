# agent_service/mcp_server.py

import socket
import json
import struct
from mcp.server.fastmcp import FastMCP

# Configuration
BLENDER_HOST = "127.0.0.1"
BLENDER_PORT = 8081

# Initialize FastMCP Server
mcp = FastMCP("Blender-Agent")

def send_to_blender(tool_name: str, params: dict = None) -> dict:
    """
    Helper to send JSON commands to the internal Blender socket server.
    """
    if params is None:
        params = {}
        
    payload = {
        "tool": tool_name,
        "params": params
    }
    
    # Prepare Message
    json_str = json.dumps(payload)
    msg_bytes = json_str.encode('utf-8')
    # Big-Endian 4-byte length prefix
    prefix = struct.pack('>I', len(msg_bytes))
    
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(10.0) # 10s timeout for connection
            s.connect((BLENDER_HOST, BLENDER_PORT))
            
            # Send
            s.sendall(prefix)
            s.sendall(msg_bytes)
            
            # Receive Length
            raw_len = s.recv(4)
            if not raw_len:
                return {"ok": False, "error": "Blender closed connection unexpectedly"}
            resp_len = struct.unpack('>I', raw_len)[0]
            
            # Receive Body
            chunks = []
            bytes_recd = 0
            while bytes_recd < resp_len:
                chunk = s.recv(min(resp_len - bytes_recd, 4096))
                if not chunk:
                    break
                chunks.append(chunk)
                bytes_recd += len(chunk)
                
            response_str = b''.join(chunks).decode('utf-8')
            return json.loads(response_str)
            
    except ConnectionRefusedError:
        return {"ok": False, "error": "Blender is not running or Server is stopped."}
    except Exception as e:
        return {"ok": False, "error": str(e)}

# --- Define MCP Tools ---

@mcp.tool()
def get_node_tree_json() -> str:
    """
    Get the current Geometry Node tree structure (Nodes, Links, Interface).
    Returns a JSON string representation.
    """
    result = send_to_blender("get_node_tree_json")
    return json.dumps(result, indent=2)

@mcp.tool()
def search_node_types(query: str) -> str:
    """
    Search for Blender Geometry Node types by name.
    Args:
        query: The search term (e.g., "noise", "merge").
    """
    result = send_to_blender("search_node_types", {"query": query})
    return json.dumps(result, indent=2)

@mcp.tool()
def get_node_details(node_internal_id: str) -> str:
    """
    Get details about a specific node type (inputs, outputs, parameters).
    Args:
        node_internal_id: The Blender ID (e.g., 'GeometryNodeMath').
    """
    result = send_to_blender("get_node_details", {"node_internal_id": node_internal_id})
    return json.dumps(result, indent=2)

@mcp.tool()
def get_current_context() -> str:
    """
    Get information about the currently active object and modifiers.
    """
    result = send_to_blender("get_current_context")
    return json.dumps(result, indent=2)

@mcp.tool()
def execute_script(script_content: str) -> str:
    """
    Execute a Python script inside Blender. 
    The script has access to 'bpy', 'math', 'random'.
    Dangerous imports (os, subprocess) are blocked.
    """
    result = send_to_blender("execute_script", {"script_content": script_content})
    return json.dumps(result, indent=2)

@mcp.tool()
def ensure_geo_modifier(object_name: str = None) -> str:
    """
    Ensure the specified (or active) object has a Geometry Nodes modifier.
    Args:
        object_name: Optional name of the object.
    """
    result = send_to_blender("ensure_geo_modifier", {"object_name": object_name})
    return json.dumps(result, indent=2)

if __name__ == "__main__":
    # This starts the MCP server on stdio by default
    mcp.run()
