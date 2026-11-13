import os
import asyncio
import streamlit as st
from google.genai import types
from google.adk.models import LlmResponse
from google.adk.agents import Agent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.tools.mcp_tool.mcp_toolset import McpToolset, StdioServerParameters
import db_manager
import sys
import re

# Patterns from Lab 7 [3]
EMAIL_PAT = re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b')
PHONE_PAT = re.compile(r'\b(?:\+?\d{1,3}[- ]?)?\(?\d{2,4}\)?[- ]?\d{3,4}[- ]?\d{3,4}\b')
CARD_PAT  = re.compile(r'\b(?:\d{4}[- ]?){3}\d{4}\b')
INJECTION_PATS = ["ignore previous instructions", "reveal system prompt", "bypass auth", "act as dan", "drop table"]

STATS = {"prompt_tokens": 0, "output_tokens": 0, "calls": 0}

def before_model_guardrail(callback_context, llm_request):
    # 1. PII Redaction
    for content in (llm_request.contents or []):
        for part in (content.parts or []):
            if getattr(part, "text", None):
                t = EMAIL_PAT.sub("[REDACTED_EMAIL]", part.text)
                t = PHONE_PAT.sub("[REDACTED_PHONE]", t)
                part.text = CARD_PAT.sub("[REDACTED_CARD]", t)
    # 2. Injection Block
    last = ""
    if llm_request.contents and llm_request.contents[-1].parts:
        last = (llm_request.contents[-1].parts[0].text or "").lower()
    if any(k in last for k in INJECTION_PATS):
        return LlmResponse(content=types.Content(role="model", parts=[types.Part(text="🛡️ [GUARDRAIL]: Request blocked by safety policy.")]))
    return None

def after_model_guardrail(callback_context, llm_response):
    # Cost tracking [3]
    u = getattr(llm_response, "usage_metadata", None)
    if u:
        STATS["prompt_tokens"] += getattr(u, "prompt_token_count", 0) or 0
        STATS["output_tokens"] += getattr(u, "candidates_token_count", 0) or 0
        STATS["calls"] += 1
    # AI Disclaimer
    if llm_response.content and llm_response.content.parts:
        for p in llm_response.content.parts:
            if hasattr(p, "text") and p.text:
                p.text += "\n\n⚠️ *AI-generated analysis. Verify with official docs.*"
    return None

# 1. Secrets & Model Config
st.set_page_config(page_title="GitHub Repo Architect Analyzer", layout="wide")
api_key = st.secrets.get("GOOGLE_API_KEY", os.environ.get("GOOGLE_API_KEY", ""))
model_name = st.secrets.get("MODEL_NAME", os.environ.get("MODEL_NAME", "gemini-3.5-flash"))

if api_key: os.environ["GOOGLE_API_KEY"] = api_key
os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "FALSE")
if not api_key:
    st.error("⚠️ GOOGLE_API_KEY missing in Streamlit Secrets.")
    st.stop()

db_manager.init_db()
db_manager.cleanup_expired()  # Auto-remove expired records

# 2. MCP Connection
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MCP_SCRIPT = os.path.join(BASE_DIR, "mcp_github_server.py")

async def run_analysis(prompt: str, history: list) -> tuple[str, list[str]]:
    mcp_toolset = McpToolset(
        connection_params=StdioServerParameters(command=sys.executable, args=[MCP_SCRIPT]),
        tool_filter=["fetch_repo_metadata", "search_architecture_insights"]
    )
agent = Agent(
    name="github_architect_analyst",
    model=model_name,
    instruction="Analyze GitHub repos using MCP tools. Output structured architecture reports.",
    tools=[mcp_toolset],
    before_model_callback=before_model_guardrail,
    after_model_callback=after_model_guardrail
)
    session_service = InMemorySessionService()
    session_id = "repo_session"
    await session_service.create_session(app_name="github_app", user_id="user", session_id=session_id)
    runner = Runner(agent=agent, app_name="github_app", session_service=session_service, auto_create_session=True)
    
    msg = types.Content(role="user", parts=[types.Part.from_text(text=prompt)])
    reply_parts, tools_called = [], []
    async for event in runner.run_async(user_id="user", session_id=session_id, new_message=msg):
        if hasattr(event, "content") and event.content:
            for p in event.content.parts:
                if getattr(p, "function_call", None): tools_called.append(p.function_call.name)
                elif getattr(p, "text", None): reply_parts.append(p.text)
    await mcp_toolset.close()
    return "".join(reply_parts), tools_called

# 3. Streamlit UI
if "messages" not in st.session_state: st.session_state.messages = []

with st.sidebar:
    st.title("🔍 Repo Architect Analyzer")
    repo_url = st.text_input("GitHub URL:", placeholder="https://github.com/owner/repo")
    if st.button("🚀 Analyze & Save"):
        if repo_url:
            st.session_state.pending = f"Analyze: {repo_url}"
            st.rerun()
    st.divider()
    if st.button("📤 Export All to JSON"):
        data = db_manager.export_to_json()
        st.download_button("Download JSON", data, file_name="analyses.json", mime="application/json")
    if st.button("🗑️ Permanently Delete Last"):
        if st.session_state.messages:
            last_url = st.session_state.messages[-2]["content"].split("Analyze: ")[-1] if "Analyze: " in st.session_state.messages[-2]["content"] else ""
            if last_url and db_manager.delete_permanently(last_url):
                st.success("Permanently deleted.")
                st.rerun()

st.title("📊 GitHub Repository Architect Analyzer")
for m in st.session_state.messages:
    with st.chat_message(m["role"]):
        st.markdown(m["content"])

prompt = st.session_state.pop("pending", None) or st.chat_input("Ask about architecture...")
if prompt:
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"): st.markdown(prompt)
    with st.chat_message("assistant"):
        with st.spinner("Analyzing via True MCP..."):
            reply, tools = asyncio.run(run_analysis(prompt, st.session_state.messages[:-1]))
            st.markdown(reply)
            # Save/Revise logic
            url = prompt.split("Analyze: ")[-1].strip() if "Analyze: " in prompt else ""
            if url:
                if not db_manager.revise_analysis(url, reply):
                    db_manager.save_analysis(url, reply)
            st.session_state.messages.append({"role": "assistant", "content": reply})
