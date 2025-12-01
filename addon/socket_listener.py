# addon/socket_listener.py
import bpy
import socket
import threading
import json
import queue
import traceback
import struct
from . import tools  # Access the tools.py registry

# --- Configuration ---
HOST = '127.0.0.1'
PORT = 8081

# --- Global State ---
server_thread = None
running = False
task_queue = queue.Queue()

def handle_client_connection(conn, addr):
    """
    Handles the socket communication for a single request.
    Protocol: 
      1. Receive 4-byte Big-Endian Integer (Message Length)
      2. Receive N bytes (JSON Body)
      3. Process
      4. Send 4-byte Big-Endian Integer (Response Length)
      5. Send M bytes (JSON Response)
    """
    print(f"[Blender-MCP] Connected by {addr}")
    try:
        # --- 1. Read Message Length ---
        raw_len = conn.recv(4)
        if not raw_len: 
            return
        msg_len = struct.unpack('>I', raw_len)[0]

        # --- 2. Read Message Body ---
        # Loop until we have all bytes
        chunks = []
        bytes_recd = 0
        while bytes_recd < msg_len:
            chunk = conn.recv(min(msg_len - bytes_recd, 4096))
            if not chunk:
                raise RuntimeError("Socket connection broken")
            chunks.append(chunk)
            bytes_recd += len(chunk)
        
        message_str = b''.join(chunks).decode('utf-8')
        request = json.loads(message_str)

        # --- 3. Process Request (Thread-Safe) ---
        # We cannot run bpy tools here (background thread).
        # We must pass it to the Main Thread via task_queue.
        
        result_container = {}
        event = threading.Event()

        def task_runner():
            try:
                tool_name = request.get("tool")
                params = request.get("params", {})

                # Route to tools.py
                if tool_name in tools.TOOL_REGISTRY:
                    func = tools.TOOL_REGISTRY[tool_name]
                    # Execute
                    res = func(**params)
                    result_container['data'] = res
                elif tool_name == "list_tools":
                    result_container['data'] = tools.get_tool_spec()
                else:
                    result_container['data'] = {"ok": False, "error": f"Unknown tool: {tool_name}"}
            except Exception as e:
                traceback.print_exc()
                result_container['data'] = {"ok": False, "error": f"Internal Error: {str(e)}"}
            finally:
                # Signal the background thread that we are done
                event.set()

        # Put the task on the queue
        task_queue.put(task_runner)
        
        # Wait for Main Thread to finish (Timeout 30s)
        completed = event.wait(timeout=30.0)
        
        if not completed:
            response = {"ok": False, "error": "Timeout: Blender Main Thread is busy."}
        else:
            response = result_container.get('data', {"ok": False, "error": "No result returned."})

        # --- 4. Send Response ---
        response_bytes = json.dumps(response).encode('utf-8')
        # Prefix with 4-byte length
        conn.sendall(struct.pack('>I', len(response_bytes)))
        conn.sendall(response_bytes)

    except Exception as e:
        print(f"[Blender-MCP] Error handling client: {e}")
        traceback.print_exc()
    finally:
        conn.close()

def server_loop():
    """
    The infinite loop running in a background thread.
    Accepts new connections.
    """
    global running
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((HOST, PORT))
            s.listen()
            s.settimeout(1.0) # Timeout to allow checking 'running' flag
            print(f"[Blender-MCP] Listening on {HOST}:{PORT}")
            
            while running:
                try:
                    conn, addr = s.accept()
                    # Handle one request at a time (blocking) or spawn thread
                    # For simplicity/safety with Blender state, we handle sequentially here,
                    # but the 'handle_client' waits for the main thread anyway.
                    handle_client_connection(conn, addr)
                except socket.timeout:
                    continue # Check running flag again
                except Exception as e:
                    print(f"[Blender-MCP] Accept Error: {e}")
                    
        except OSError as e:
            print(f"[Blender-MCP] Bind failed: {e}")

def queue_processor():
    """
    Runs on the Main Thread every 0.1 seconds.
    Executes tasks waiting in the queue.
    """
    while not task_queue.empty():
        try:
            task = task_queue.get_nowait()
            task() # Run the function (accesses bpy)
        except queue.Empty:
            break
    return 0.1 # Schedule next run

def start():
    """Called by __init__.py to start the server"""
    global running, server_thread
    if running:
        return
    
    running = True
    server_thread = threading.Thread(target=server_loop, daemon=True)
    server_thread.start()
    
    if not bpy.app.timers.is_registered(queue_processor):
        bpy.app.timers.register(queue_processor)
    
    print("[Blender-MCP] Server Started")

def stop():
    """Called by __init__.py to stop the server"""
    global running
    running = False
    if server_thread:
        server_thread.join(timeout=2.0)
    
    if bpy.app.timers.is_registered(queue_processor):
        bpy.app.timers.unregister(queue_processor)
        
    print("[Blender-MCP] Server Stopped")
