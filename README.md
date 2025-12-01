# BlendAI

**Automate Geometry Nodes creation in Blender using AI agents.**

This project leverages the **Google Agent Development Kit (ADK)** and the **Model Context Protocol (MCP)** to turn natural language prompts into 3D procedural geometry. Instead of manually wiring nodes, simply ask the AI to create a "Geometry Node Setup" you want and watch it building the node tree in real-time directly inside Blender.

---

## 📺 Video Tutorial
For a visual guide on setup and usage, check out this video:
[Watch the Video Tutorial on YouTube](https://www.youtube.com/watch?v=YOUR_VIDEO_ID_HERE)

---

## 🚀 How It Works
The system uses a **Multi-Agent Architecture** to ensure high-quality, functional node trees:

1.  **🧠 The Architect Agent:** Analyzes your request and the current scene context to plan the node logic.
2.  **💻 The Developer Agent:** Writes the Python code (`bpy`) to physically build and link the node tree.
3.  **🔄 Self-Correction Loop:** If the generated code fails (e.g., incorrect socket names), the agent reads the error trace, researches the correct Blender API, and automatically fixes its own code.

---

## 🛠️ Installation Guide
### Prerequisites
*   **Blender 4.0+** (Installed and accessible)
*   **Python 3.10+** (Installed on your system)
*   A **Google Gemini API Key**

---

### Step 1: Clone the Repository
```
git clone https://github.com/SV005/BlendAI.git
cd BlendAI
```

### Step 2: Create a viruel python environment.
To install the dependencies create a seperate python virtual environment (venv). 

**Windows:**
```
python -m venv venv
```
Then Activate it.
```
.\venv\Scripts\activate
```

### Step 3: Install Dependencies
Install the required libraries from requirements.txt file.
```
pip install -r requirements.txt
```

### Step 4: Configure API Key
1.  Create a file named `.env` in the root directory.
2.  Add your Gemini API key:
    ```
    GEMINI_API_KEY=your_actual_api_key_here
    ```

### Step 5: Setup Blender Add-on
1.  Open Blender.
2.  Go to **Edit** -> **Preferences** -> **Add-ons**.
3.  Click **Install...** and select the `addon.zip` zipped folder from this repo.
4.  Enable the add-on by checking the box.
5.  Open the **Sidebar (N-Panel)** in the 3D Viewport and find the **"AI Agent"** tab.
6.  Click the **Start Server** button to initialize the Blender-side socket listener.

---

## ⚡ Usage

### 1. Run the Agent Server
Open your new cmd terminal in VS Code, ensure your virtual environment is active, and run the agent service:
```
python -m agent_service.src.main
```
*This starts the backend that communicates between the AI and Blender.*

### 2. Ask AI in Blender
1.  Select a Mesh object in the 3D Viewport.
2.  Go to the **AI Agent** panel.
3.  Type your prompt.
    *   *Example:* `"Add a Sphere and Extrude it's faces with Offset 1."`
4.  Click **Ask**.

After a moment of processing, the AI will create a new Geometry Nodes modifier on your object with the requested node setup!

---


## 📂 Project Structure
*   **`agent_service/src/agents_adk.py`** - **The Brain.** Defines the AI agents (Architect & Developer) and the orchestration logic.
*   **`agent_service/mcp_server.py`** - **The Bridge.** An MCP server that exposes Blender tools to the AI agents.
*   **`addon/tools.py`** - **The Hands.** Python functions injected into Blender to execute scripts, inspect scenes, and manage nodes.
*   **`requirements.txt`** - List of Python dependencies.

---

## 🤝 Contributing
Contributions are welcome! Please feel free to submit a Pull Request.

## 📄 License
This project is licensed under the **Apache 2.0 License**.