# tools.py
# Blender-side tools module for AI agent control of Geometry Nodes (no images).
# This file is designed to be imported and called by the MCP socket server running inside Blender.

from __future__ import annotations

import bpy
import fnmatch
import json
from typing import Any, Dict, List, Optional, Tuple, Union

# ------------------------------
# Response helpers (uniform envelope)
# ------------------------------

def _ok(data: Any) -> Dict[str, Any]:
    return {"ok": True, "data": data}

def _err(msg: str) -> Dict[str, Any]:
    return {"ok": False, "error": msg}

# ------------------------------
# Serialization helpers
# ------------------------------

def _to_json_value(v: Any) -> Any:
    """
    Convert Blender/mathutils types to JSON-serializable primitives.
    - Vectors/Colors/Quaternions -> list/tuple
    - IDs -> name
    - Fallback: return as-is if already primitive
    """
    try:
        # mathutils types often expose to_tuple or to_list
        if hasattr(v, "to_list"):
            return v.to_list()
        if hasattr(v, "to_tuple"):
            return tuple(v.to_tuple())
    except Exception:
        pass

    # Blender ID datablocks: prefer names for compactness
    if isinstance(v, bpy.types.ID):
        return v.name

    # Built-ins are fine
    if isinstance(v, (str, int, float, bool)) or v is None:
        return v

    # Lists / tuples: convert elements
    if isinstance(v, (list, tuple)):
        return [_to_json_value(x) for x in v]

    # Dict: convert values
    if isinstance(v, dict):
        return {k: _to_json_value(x) for k, x in v.items()}

    # Fallback to string representation
    return str(v)

def _safe_get_default(socket: bpy.types.NodeSocket) -> Any:
    """
    Safely read default_value for unlinked sockets when available.
    """
    if not hasattr(socket, "default_value"):
        return None
    try:
        raw = socket.default_value
        return _to_json_value(raw)
    except Exception:
        return None

# ------------------------------
# 1) Introspection tools (no images)
# ------------------------------

def search_node_types(query: str) -> Dict[str, Any]:
    """
    Search Geometry Node classes by ID or label.
    Returns top-N matches with id/label/description.
    Agent uses `id` for nodes.new(id), `label`/`description` for context.
    """
    if not isinstance(query, str) or not query.strip():
        return _err("Query must be a non-empty string.")
    q = query.lower()
    matches: List[Dict[str, Any]] = []

    for name in dir(bpy.types):
        if "GeometryNode" in name:
            cls = getattr(bpy.types, name)
            label = getattr(cls, "bl_label", name)
            desc = getattr(cls, "bl_description", "")
            if q in name.lower() or q in str(label).lower():
                matches.append({
                    "id": name,
                    "label": label,
                    "description": desc
                })
    # Limit to 5 to keep context compact
    return _ok(matches[:5])

def get_node_details(node_internal_id: str) -> Dict[str, Any]:
    """
    Inspect a specific Geometry Node by internal ID, returning:
    - id, label, description
    - inputs: [{name, identifier, type, default}]
    - outputs: [{name, identifier, type}]
    - parameters: non-socket RNA properties (ENUM options included)
    Uses a temporary GeometryNodeTree to safely spawn and introspect the node.
    """
    if not isinstance(node_internal_id, str) or not node_internal_id.strip():
        return _err("node_internal_id must be a non-empty string.")

    temp_tree_name = "MCP_Inspector_Temp"
    if temp_tree_name in bpy.data.node_groups:
        try:
            bpy.data.node_groups.remove(bpy.data.node_groups[temp_tree_name])
        except Exception:
            pass

    temp_tree = bpy.data.node_groups.new(temp_tree_name, 'GeometryNodeTree')
    result: Dict[str, Any] = {}
    try:
        node = temp_tree.nodes.new(node_internal_id)
        node_cls = getattr(bpy.types, node_internal_id, None)
        description = getattr(node_cls, "bl_description", "No description available.")

        result = {
            "id": node_internal_id,
            "label": node.label if node.label else node.name,
            "description": description,
            "inputs": [],
            "outputs": [],
            # "parameters": []
        }

        # Inputs
        for sock in node.inputs:
            result["inputs"].append({
                "name": sock.name,
                "identifier": sock.identifier,
                "type": sock.bl_idname,
                "default": _safe_get_default(sock)
            })

        # Outputs
        for sock in node.outputs:
            result["outputs"].append({
                "name": sock.name,
                "identifier": sock.identifier,
                "type": sock.bl_idname
            })

        # Non-socket RNA properties
        ignored = {
            'rna_type', 'name', 'label', 'location', 'width', 'height',
            'parent', 'use_custom_color', 'color', 'select', 'show_options',
            'mute', 'hide', 'inputs', 'outputs', 'dimensions', 'internal_links'
        }
        for prop_id in node.bl_rna.properties.keys():
            if prop_id in ignored:
                continue
            prop = node.bl_rna.properties[prop_id]
            entry = {
                "name": prop.name,
                "identifier": prop.identifier,
                "type": prop.type,
                "description": prop.description
            }
            if prop.type == 'ENUM':
                try:
                    entry["options"] = [item.identifier for item in prop.enum_items]
                    # Human-friendly docs if available
                    entry["option_docs"] = {
                        item.identifier: getattr(item, "description", "") for item in prop.enum_items
                    }
                except Exception:
                    entry["options"] = []
            result["parameters"].append(entry)

        return _ok(result)
    except Exception as e:
        return _err(f"Failed to inspect '{node_internal_id}': {e}")
    finally:
        try:
            bpy.data.node_groups.remove(temp_tree)
        except Exception:
            pass


def get_current_context() -> Dict[str, Any]:
    """
    Return a compact snapshot of the active object and its modifiers, including
    any Geometry Nodes modifier with its node group name and node list.
    """
    obj = bpy.context.active_object
    if not obj:
        return _err("No active object selected.")

    data = {
        "active_object": obj.name,
        "type": obj.type,
        "modifiers": []
    }
    for mod in obj.modifiers:
        entry = {"name": mod.name, "type": mod.type}
        if mod.type == 'NODES' and getattr(mod, "node_group", None):
            entry["node_group"] = mod.node_group.name
            try:
                entry["nodes"] = [n.name for n in mod.node_group.nodes]
            except Exception:
                entry["nodes"] = []
        data["modifiers"].append(entry)
    return _ok(data)

# ------------------------------
# 2) Geometry node tree serialization (structure only)
# ------------------------------

def _serialize_interface(node_tree: bpy.types.GeometryNodeTree) -> Dict[str, Any]:
    """
    Serialize group interface sockets when available (INPUT/OUTPUT).
    Not all items are sockets; guard by type and attributes.
    """
    out = {"inputs": [], "outputs": []}
    try:
        iface = node_tree.interface  # NodeTreeInterface
        # Blender 4.x provides items_tree to traverse interface items
        items = getattr(iface, "items_tree", [])
        for item in items:
            if isinstance(item, bpy.types.NodeTreeInterfaceSocket):
                rec = {
                    "name": item.name,
                    "identifier": getattr(item, "identifier", item.name),
                    "socket_type": getattr(item, "socket_type", "DEFAULT"),
                    "in_out": getattr(item, "in_out", "INPUT")
                }
                if rec["in_out"] == 'INPUT':
                    out["inputs"].append(rec)
                else:
                    out["outputs"].append(rec)
    except Exception:
        pass
    return out

def _serialize_node(node: bpy.types.Node, include_values: bool) -> Dict[str, Any]:
    data = {
        "name": node.name,
        "type": node.bl_idname,
        "label": node.label or node.name,
        "location": _to_json_value(getattr(node, "location", None)),
        "width": _to_json_value(getattr(node, "width", None)),
        "height": _to_json_value(getattr(node, "height", None)),
        "mute": bool(getattr(node, "mute", False)),
        "hide": bool(getattr(node, "hide", False)),
        "inputs": [],
        "outputs": []
    }
    # Inputs
    for sock in node.inputs:
        sock_entry = {
            "name": sock.name,
            "identifier": sock.identifier,
            "type": sock.bl_idname,
            "is_linked": bool(getattr(sock, "is_linked", False))
        }
        if include_values and not sock_entry["is_linked"]:
            sock_entry["default"] = _safe_get_default(sock)
        data["inputs"].append(sock_entry)
    # Outputs
    for sock in node.outputs:
        data["outputs"].append({
            "name": sock.name,
            "identifier": sock.identifier,
            "type": sock.bl_idname,
            "is_linked": bool(getattr(sock, "is_linked", False))
        })
    return data

def _serialize_links(node_tree: bpy.types.GeometryNodeTree) -> List[Dict[str, Any]]:
    links_out: List[Dict[str, Any]] = []
    try:
        for link in node_tree.links:
            try:
                links_out.append({
                    "from": {
                        "node": link.from_node.name,
                        "socket": link.from_socket.identifier
                    },
                    "to": {
                        "node": link.to_node.name,
                        "socket": link.to_socket.identifier
                    }
                })
            except Exception:
                # Skip malformed links safely
                continue
    except Exception:
        pass
    return links_out

def get_node_tree_json(
    tree_name: Optional[str] = None,
    object_name: Optional[str] = None,
    include_values: bool = True,
    max_nodes: Optional[int] = None
) -> Dict[str, Any]:
    """
    Serialize a Geometry Node tree to JSON-like data:
    {
      "tree": {...meta...},
      "interface": {"inputs":[], "outputs":[]},
      "nodes": [ { ... }, ... ],
      "links": [ { "from": {...}, "to": {...} }, ... ]
    }

    Selection order:
    - If tree_name is provided and exists in bpy.data.node_groups, use it.
    - Else, if object_name provided, use its first NODES modifier's node_group.
    - Else, use active object's first NODES modifier's node_group.
    """
    node_tree: Optional[bpy.types.GeometryNodeTree] = None

    if tree_name and tree_name in bpy.data.node_groups:
        node_tree = bpy.data.node_groups[tree_name]
    elif object_name and object_name in bpy.data.objects:
        obj = bpy.data.objects[object_name]
        for mod in obj.modifiers:
            if mod.type == 'NODES' and getattr(mod, "node_group", None):
                node_tree = mod.node_group
                break
    else:
        obj = bpy.context.active_object
        if obj:
            for mod in obj.modifiers:
                if mod.type == 'NODES' and getattr(mod, "node_group", None):
                    node_tree = mod.node_group
                    break

    if node_tree is None:
        return _err("No Geometry Node tree found (provide tree_name or ensure an active object with a Nodes modifier).")

    # Basic meta
    out: Dict[str, Any] = {
        "tree": {
            "name": node_tree.name,
            "type": node_tree.bl_idname
        },
        "interface": _serialize_interface(node_tree),
        "nodes": [],
        "links": []
    }

    # Nodes with optional cap
    all_nodes = list(node_tree.nodes)
    if isinstance(max_nodes, int) and max_nodes > 0:
        all_nodes = all_nodes[:max_nodes]
    out["nodes"] = [_serialize_node(n, include_values) for n in all_nodes]

    # Links
    out["links"] = _serialize_links(node_tree)

    return _ok(out)

# ------------------------------
# 3) Minimal creation/attachment utilities (optional but useful)
# ------------------------------

def ensure_geo_modifier(
    object_name: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Simulate the manual workflow:
    - Select object
    - Add Geometry Nodes modifier (like Add Modifier > Geometry Nodes)
    - Create a new geometry node group (like pressing 'New')
    - Ensure Group Input/Output nodes with 'Geometry' sockets exist
      and their Geometry sockets are NOT directly connected.
    """

    # --- Resolve and activate object ---
    obj = bpy.data.objects.get(object_name) if object_name else bpy.context.active_object
    if obj is None:
        return {"ok": False, "error": "No active object and no object_name given."}

    if obj.type not in {"MESH", "CURVE", "CURVES", "POINTCLOUD", "VOLUME"}:
        return {"ok": False, "error": f"Object type '{obj.type}' cannot use Geometry Nodes."}

    # Make object active & selected for operators
    bpy.context.view_layer.objects.active = obj
    for o in bpy.context.selected_objects:
        o.select_set(False)
    obj.select_set(True)

    # --- Add a Geometry Nodes modifier like the UI does ---
    bpy.ops.object.modifier_add(type='NODES')
    mod = obj.modifiers[-1]

    # --- Create/assign a new geometry node group ---
    try:
        # This operator creates a new GeometryNodeTree with Group Input/Output and links them.
        bpy.ops.node.new_geometry_node_group_assign()
        node_group = mod.node_group
    except Exception:
        # Fallback if operator context fails (e.g. running headless)
        node_group = bpy.data.node_groups.new("AI_GeoTree", 'GeometryNodeTree')
        mod.node_group = node_group

    # --- Ensure interface & nodes look like your desired starting setup ---
    tree = node_group
    nodes = tree.nodes

    # 1) Interface sockets: make sure we have Geometry in/out (Blender 4.0+ API)
    # Check if "Geometry" exists in interface items
    
    # Input Socket
    has_geo_input = False
    for item in tree.interface.items_tree:
        if item.item_type == 'SOCKET' and item.in_out == 'INPUT' and item.name == "Geometry":
            has_geo_input = True
            break
    
    if not has_geo_input:
        # Create input socket: name="Geometry", in_out='INPUT', socket_type='NodeSocketGeometry'
        tree.interface.new_socket("Geometry", in_out='INPUT', socket_type='NodeSocketGeometry')

    # Output Socket
    has_geo_output = False
    for item in tree.interface.items_tree:
        if item.item_type == 'SOCKET' and item.in_out == 'OUTPUT' and item.name == "Geometry":
            has_geo_output = True
            break

    if not has_geo_output:
        # Create output socket: name="Geometry", in_out='OUTPUT', socket_type='NodeSocketGeometry'
        tree.interface.new_socket("Geometry", in_out='OUTPUT', socket_type='NodeSocketGeometry')

    # 2) Ensure Group Input / Group Output nodes exist
    group_input = None
    group_output = None
    for n in nodes:
        if n.bl_idname == "NodeGroupInput":
            group_input = n
        elif n.bl_idname == "NodeGroupOutput":
            group_output = n

    if group_input is None:
        group_input = nodes.new("NodeGroupInput")
        group_input.location = (-300, 0)

    if group_output is None:
        group_output = nodes.new("NodeGroupOutput")
        group_output.location = (300, 0)

    # 3) Make sure Geometry sockets are NOT linked between input and output
    # Note: We must look up sockets by name since indices can shift
    geo_out = group_input.outputs.get("Geometry")
    geo_in = group_output.inputs.get("Geometry")
    
    if geo_out and geo_in:
        for link in list(tree.links):
            if link.from_socket == geo_out and link.to_socket == geo_in:
                tree.links.remove(link)

    return {
        "ok": True,
        "object": obj.name,
        "modifier": mod.name,
        "node_group": tree.name,
    }

# ------------------------------
# 4) Script execution (sandboxed)
# ------------------------------

_FORBIDDEN_SNIPPETS = [
    "import os", "import sys", "import subprocess", "import shutil",
    "__import__('os')", "__import__(\"os\")"
]

def execute_script(script_content: str) -> Dict[str, Any]:
    """
    Execute a Python script in a minimal sandbox with bpy, math, random.
    Returns either success message or the exception text for self-correction.
    """
    if not isinstance(script_content, str) or not script_content.strip():
        return _err("script_content must be a non-empty string.")

    for ban in _FORBIDDEN_SNIPPETS:
        if ban in script_content:
            return _err(f"Security violation: '{ban}' is not allowed.")

    ctx = {
        "bpy": bpy,
        "math": __import__("math"),
        "random": __import__("random"),
    }
    try:
        exec(script_content, ctx)
        # attempt to refresh view layer if possible
        try:
            if bpy.context.active_object:
                bpy.context.active_object.update_tag()
            bpy.context.view_layer.update()
        except Exception:
            pass
        return _ok("Success.")
    except Exception as e:
        return _err(f"Python Execution Error: {e}")

# ------------------------------
# 5) Tool registry and specs
# ------------------------------

TOOL_REGISTRY: Dict[str, Any] = {
    # Introspection
    "search_node_types": search_node_types,
    "get_node_details": get_node_details,
    "get_current_context": get_current_context,
    # Serialization
    "get_node_tree_json": get_node_tree_json,
    # Scene wiring helpers
    "ensure_geo_modifier": ensure_geo_modifier,
    # Execution
    "execute_script": execute_script,
}

def get_tool_spec() -> Dict[str, Any]:
    """
    Lightweight tool signature spec for agent/MCP discovery.
    Only documents args that agents need to format calls properly.
    """
    return _ok({
        "search_node_types": {
            "args": {"query": "str"},
            "returns": "List[ {id, label, description} ]"
        },
        "get_node_details": {
            "args": {"node_internal_id": "str"},
            "returns": "{id, label, description, inputs[], outputs[], parameters[]}"
        },
        "get_current_context": {
            "args": {},
            "returns": "{active_object, type, modifiers[]}"
        },
        "get_node_tree_json": {
            "args": {
                "tree_name": "Optional[str]",
                "object_name": "Optional[str]",
                "include_values": "bool",
                "max_nodes": "Optional[int]"
            },
            "returns": "{tree, interface, nodes[], links[]}"
        },
        "ensure_geo_modifier": {
            "args": {
                "object_name": "Optional[str]",
                "group_name": "Optional[str]",
                "create_group_if_missing": "bool"
            },
            "returns": "{object, modifier, node_group}"
        },
        "execute_script": {
            "args": {"script_content": "str"},
            "returns": "str (status or error)"
        }
    })
