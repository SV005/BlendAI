# addon/__init__.py

bl_info = {
    "name": "Blender AI Agent",
    "author": "Your Name",
    "version": (0, 4, 1),
    "blender": (4, 2, 0),
    "location": "View3D > Sidebar > AI Agent",
    "description": "AI Assistant for Geometry Nodes",
    "category": "System",
}

import bpy
import requests
import json
import threading
from . import socket_listener
from . import tools

# --- Constants ---
AGENT_API_URL = "http://127.0.0.1:8000/chat"

# --- Properties ---

class ChatMessage(bpy.types.PropertyGroup):
    role: bpy.props.StringProperty() # "user" or "ai"
    content: bpy.props.StringProperty()

class AgentProperties(bpy.types.PropertyGroup):
    chat_input: bpy.props.StringProperty(
        name="Input",
        description="Type request...",
        default=""
    )
    chat_history: bpy.props.CollectionProperty(type=ChatMessage)
    is_processing: bpy.props.BoolProperty(default=False)
    status_message: bpy.props.StringProperty(default="")

# --- GLOBAL HANDLERS (Crash Proof) ---

def handle_success(data):
    try:
        scene = bpy.context.scene
        if not scene: 
            if bpy.data.scenes: scene = bpy.data.scenes[0]
            else: return

        props = scene.agent_props
        props.is_processing = False
        props.status_message = ""
        
        # Add Response
        msg = props.chat_history.add()
        msg.role = "ai"
        msg.content = data.get("text", "")
        
        if data.get("code"):
            msg.content += "\n\n[CODE EXECUTED]"
            
        # Force Redraw
        for win in bpy.context.window_manager.windows:
            for area in win.screen.areas:
                if area.type == 'VIEW_3D':
                    area.tag_redraw()
    except Exception as e:
        print(f"[Blender-MCP] Error in success handler: {e}")

def handle_error(error_msg):
    try:
        scene = bpy.context.scene
        if not scene:
             if bpy.data.scenes: scene = bpy.data.scenes[0]
             else: return

        props = scene.agent_props
        props.is_processing = False
        props.status_message = "Error!"
        
        msg = props.chat_history.add()
        msg.role = "ai"
        msg.content = f"Error: {error_msg}"
        
        for win in bpy.context.window_manager.windows:
            for area in win.screen.areas:
                if area.type == 'VIEW_3D':
                    area.tag_redraw()
    except Exception as e:
         print(f"[Blender-MCP] Error in error handler: {e}")

# --- Operators ---

class MCP_OT_SendChat(bpy.types.Operator):
    """Send message to AI Agent"""
    bl_idname = "mcp.send_chat"
    bl_label = "Ask"

    def execute(self, context):
        scene = context.scene
        props = scene.agent_props
        user_text = props.chat_input
        
        if not user_text.strip():
            return {'CANCELLED'}

        # Add User Message
        msg = props.chat_history.add()
        msg.role = "user"
        msg.content = user_text
        
        # Update UI
        props.chat_input = ""
        props.is_processing = True
        props.status_message = "Thinking..."
        context.area.tag_redraw()
        
        history_payload = [{"role": m.role, "text": m.content} for m in props.chat_history[-10:]]
        
        def send_request():
            try:
                payload = {"prompt": user_text, "history": history_payload}
                response = requests.post(AGENT_API_URL, json=payload, timeout=120)
                
                if response.status_code == 200:
                    data = response.json()
                    bpy.app.timers.register(lambda: handle_success(data))
                else:
                    err = f"HTTP {response.status_code}: {response.reason}"
                    bpy.app.timers.register(lambda: handle_error(err))
            except Exception as e:
                bpy.app.timers.register(lambda: handle_error(str(e)))

        threading.Thread(target=send_request, daemon=True).start()
        return {'FINISHED'}

class MCP_OT_ClearChat(bpy.types.Operator):
    """Clear Chat History"""
    bl_idname = "mcp.clear_chat"
    bl_label = "Clear"
    def execute(self, context):
        context.scene.agent_props.chat_history.clear()
        return {'FINISHED'}

class MCP_OT_StartServer(bpy.types.Operator):
    bl_idname = "mcp.start_server"
    bl_label = "Start Server"
    def execute(self, context):
        socket_listener.start()
        return {'FINISHED'}

class MCP_OT_StopServer(bpy.types.Operator):
    bl_idname = "mcp.stop_server"
    bl_label = "Stop Server"
    def execute(self, context):
        socket_listener.stop()
        return {'FINISHED'}

# --- UI Panel ---

class MCP_PT_MainPanel(bpy.types.Panel):
    bl_label = "AI Agent"
    bl_idname = "MCP_PT_main_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "AI Agent"

    def draw(self, context):
        layout = self.layout
        props = context.scene.agent_props
        
        # 1. Server Controls (Top)
        # Kept the clean box look you liked
        box = layout.box()
        row = box.row()
        if socket_listener.running:
            row.label(text="Socket: RUNNING", icon='CHECKBOX_HLT')
            row.operator("mcp.stop_server", text="", icon='PAUSE')
        else:
            row.label(text="Socket: STOPPED", icon='CHECKBOX_DEHLT')
            row.operator("mcp.start_server", text="", icon='PLAY')

        layout.separator()

        # 2. Chat History (Scrollable-ish Box)
        chat_box = layout.box()
        if not props.chat_history:
            chat_box.label(text="Ready to help.", icon='INFO')
        
        # Show last 5 messages
        start = max(0, len(props.chat_history) - 5)
        for i in range(start, len(props.chat_history)):
            msg = props.chat_history[i]
            col = chat_box.column(align=True)
            
            # Role Header
            row = col.row()
            if msg.role == "user":
                row.alignment = 'RIGHT'
                row.label(text="You", icon='USER')
            else:
                row.alignment = 'LEFT'
                row.label(text="Agent", icon='SHADERFX')
            
            # Message Text (Split lines)
            sub = col.column()
            for line in msg.content.split('\n'):
                if line.strip():
                    sub.label(text=line)
            col.separator()

        # 3. Status
        if props.is_processing:
            row = layout.row()
            row.label(text=props.status_message, icon='TIME')

        # 4. Input Area (Bottom)
        layout.separator()
        col = layout.column(align=True)
        col.prop(props, "chat_input", text="")
        
        row = col.row(align=True)
        row.scale_y = 1.4
        row.operator("mcp.send_chat", icon='TRIA_RIGHT')
        
        # Clear Button
        row = layout.row()
        row.alignment = 'RIGHT'
        row.operator("mcp.clear_chat", text="Clear", icon='TRASH', emboss=False)

# --- Registration ---

classes = (
    ChatMessage,
    AgentProperties,
    MCP_OT_SendChat,
    MCP_OT_ClearChat,
    MCP_OT_StartServer,
    MCP_OT_StopServer,
    MCP_PT_MainPanel,
)

def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    
    bpy.types.Scene.agent_props = bpy.props.PointerProperty(type=AgentProperties)
    print("[Blender-MCP] Addon Registered")

def unregister():
    del bpy.types.Scene.agent_props
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
        
    if socket_listener.running:
        socket_listener.stop()

if __name__ == "__main__":
    register()
