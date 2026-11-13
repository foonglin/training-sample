import json
import os
import re
import sqlite3
import streamlit as st
from google.genai import types
from google.adk.agents import Agent
from google.adk.models import LlmResponse
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService

# ==============================================================================
# 1. Page Configuration & Secret Resolution
# ==============================================================================
st.set_page_config(
    page_title="Workforce MCP Scheduler",
    page_icon="📅",
    layout="wide",
    initial_sidebar_state="expanded",
)

api_key = ""
try:
    if "GOOGLE_API_KEY" in st.secrets:
        api_key = st.secrets["GOOGLE_API_KEY"]
except Exception:
    api_key = os.environ.get("GOOGLE_API_KEY", "")

if api_key:
    os.environ["GOOGLE_API_KEY"] = api_key
os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "FALSE")

DB_FILE = "workforce.sqlite"

if not os.environ.get("GOOGLE_API_KEY"):
    st.error("⚠️ **GOOGLE_API_KEY is not configured!**\nAdd it to Streamlit Secrets.")
    st.stop()

# ==============================================================================
# 2. Database Bootstrap & Migration Functions
# ==============================================================================
def ensure_database():
    """Initializes baseline workforce database if it doesn't exist."""
    if not os.path.exists(DB_FILE):
        conn = sqlite3.connect(DB_FILE)
        cur = conn.cursor()
        cur.executescript("""
        CREATE TABLE IF NOT EXISTS employees (
            employee_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            department TEXT NOT NULL,
            role TEXT NOT NULL,
            max_hours_week REAL NOT NULL,
            status TEXT DEFAULT 'Active'
        );

        CREATE TABLE IF NOT EXISTS shifts (
            shift_id TEXT PRIMARY KEY,
            employee_id TEXT NOT NULL,
            date TEXT NOT NULL,
            start_time TEXT NOT NULL,
            end_time TEXT NOT NULL,
            role TEXT NOT NULL,
            status TEXT DEFAULT 'Scheduled',
            FOREIGN KEY (employee_id) REFERENCES employees(employee_id)
        );

        CREATE TABLE IF NOT EXISTS availability (
            employee_id TEXT NOT NULL,
            date TEXT NOT NULL,
            available INTEGER DEFAULT 1,
            PRIMARY KEY (employee_id, date),
            FOREIGN KEY (employee_id) REFERENCES employees(employee_id)
        );

        CREATE TABLE IF NOT EXISTS swap_requests (
            swap_id TEXT PRIMARY KEY,
            requester_id TEXT NOT NULL,
            partner_id TEXT NOT NULL,
            shift_id TEXT NOT NULL,
            status TEXT DEFAULT 'Pending',
            FOREIGN KEY (requester_id) REFERENCES employees(employee_id),
            FOREIGN KEY (partner_id) REFERENCES employees(employee_id),
            FOREIGN KEY (shift_id) REFERENCES shifts(shift_id)
        );

        INSERT OR IGNORE INTO employees VALUES
            ('EMP_001', 'Alice Chen', 'Retail', 'Cashier', 40.0, 'Active'),
            ('EMP_002', 'Bob Smith', 'Retail', 'Stock Clerk', 32.0, 'Active'),
            ('EMP_003', 'Carol Davis', 'Retail', 'Shift Lead', 40.0, 'Active');

        INSERT OR IGNORE INTO availability VALUES
            ('EMP_001', '2026-11-15', 1), ('EMP_001', '2026-11-16', 0),
            ('EMP_002', '2026-11-15', 1), ('EMP_002', '2026-11-16', 1),
            ('EMP_003', '2026-11-15', 1), ('EMP_003', '2026-11-16', 1);
        """)
        conn.commit()
        conn.close()

def execute_demo_migration():
    """Simulates adding a new department & employees mid-session."""
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.executescript("""
    INSERT OR IGNORE INTO employees VALUES
        ('EMP_004', 'David Lee', 'Warehouse', 'Picker', 36.0, 'Active'),
        ('EMP_005', 'Eva Martinez', 'Warehouse', 'Packer', 36.0, 'Active');

    INSERT OR IGNORE INTO availability VALUES
        ('EMP_004', '2026-11-15', 1), ('EMP_004', '2026-11-16', 1),
        ('EMP_005', '2026-11-15', 1), ('EMP_005', '2026-11-16', 0);
    """)
    conn.commit()
    conn.close()

def get_live_schema() -> str:
    """Extracts live DDL for transparency."""
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%';")
    statements = [row[0] for row in cur.fetchall() if row[0]]
    conn.close()
    return "\n\n".join(statements)

ensure_database()

# ==============================================================================
# 3. MCP Protocol Primitives & Workforce Guardrails
# ==============================================================================
def is_policy_violation(action: str, payload: dict) -> bool:
    """Validates scheduling actions against labor & availability policies."""
    if action == "assign_shift":
        emp_id, date, start, end = payload.get("employee_id"), payload.get("date"), payload.get("start_time"), payload.get("end_time")
        conn = sqlite3.connect(DB_FILE)
        cur = conn.cursor()
        # Check availability
        cur.execute("SELECT available FROM availability WHERE employee_id=? AND date=?", (emp_id, date))
        if not cur.fetchone() or not cur.fetchone()[0]:
            conn.close()
            return True
        # Check overlap
        cur.execute("""SELECT COUNT(*) FROM shifts WHERE employee_id=? AND date=? 
                       AND status='Scheduled' AND NOT (end_time <= ? OR start_time >= ?)""",
                    (emp_id, date, start, end))
        if cur.fetchone()[0] > 0:
            conn.close()
            return True
        conn.close()
    return False

def mask_workforce_ids(text: str) -> str:
    """Masks employee/shift IDs for privacy compliance."""
    text = re.sub(r'\b(EMP_)[0-9A-Za-z]+([0-9A-Za-z]{2})\b', r'\1***\2', text, flags=re.IGNORECASE)
    text = re.sub(r'\b(SH_)[0-9A-Za-z]+([0-9A-Za-z]{2})\b', r'\1***\2', text, flags=re.IGNORECASE)
    text = re.sub(r'\b(SWAP_)[0-9A-Za-z]+([0-9A-Za-z]{2})\b', r'\1***\2', text, flags=re.IGNORECASE)
    return text

def mcp_list_entities() -> str:
    """MCP Tool: Discovers available workforce entities."""
    return json.dumps({"status": "success", "entities": ["employees", "shifts", "availability", "swap_requests"]})

def mcp_describe_entity(entity_type: str) -> str:
    """MCP Tool: Returns schema/fields for a workforce entity."""
    conn = sqlite3.connect(f"file:{DB_FILEcid": r[0], "name": r[1], "type": r[2], "notnull": r[3], "pk": r[5]} for r in cur.fetchall()]
    conn.close()
    if not cols:
        return json.dumps({"status": "error", "message": f"Entity '{entity_type}' not found."})
    return json.dumps({"status": "success", "entity": entity_type, "fields": cols})

def mcp_query_workforce(query_type: str, filters: dict = None) -> str:
    """MCP Tool: Safe, parameterized read queries for workforce data."""
    filters = filters or {}
    conn = sqlite3.connect(f"file:{DB_FILE}?mode=ro", uri=True)
    cur = conn.cursor()
    try:
        if query_type == "employees":
            cur.execute("SELECT employee_id, name, department, role, max_hours_week FROM employees")
        elif query_type == "shifts":
            cur.execute("SELECT shift_id, employee_id, date, start_time, end_time, role FROM shifts WHERE status='Scheduled'")
        elif query_type == "availability":
            cur.execute("SELECT employee_id, date, available FROM availability WHERE available=1")
        elif query_type == "swaps":
            cur.execute("SELECT swap_id, requester_id, partner_id, shift_id, status FROM swap_requests")
        else:
            return json.dumps({"status": "error", "message": "Invalid query_type."})
        
        columns = [d[0] for d in cur.description]
        rows = cur.fetchall()
        conn.close()
        return json.dumps({"status": "success", "columns": columns, "rows": [list(r) for r in rows[:50]], "count": len(rows)})
    except Exception as e:
        conn.close()
        return json.dumps({"status": "error", "message": str(e)})

def mcp_assign_shift(employee_id: str, date: str, start_time: str, end_time: str, role: str) -> str:
    """MCP Tool: Assigns a shift after policy validation."""
    payload = {"employee_id": employee_id, "date": date, "start_time": start_time, "end_time": end_time}
    if is_policy_violation("assign_shift", payload):
        return json.dumps({"status": "blocked", "error": "🛡️ [POLICY VIOLATION]: Overlap or unavailability detected."})
    
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    shift_id = f"SH_{date.replace('-','')}_{employee_id}"
    cur.execute("INSERT OR REPLACE INTO shifts VALUES (?,?,?,?,?,?,?)",
                (shift_id, employee_id, date, start_time, end_time, role, "Scheduled"))
    conn.commit()
    conn.close()
    return json.dumps({"status": "success", "shift_id": shift_id, "employee_id": employee_id, "date": date, "time": f"{start_time}-{end_time}"})

def mcp_request_swap(requester_id: str, partner_id: str, shift_id: str) -> str:
    """MCP Tool: Logs a swap request with basic validation."""
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("SELECT employee_id, date, start_time, end_time FROM shifts WHERE shift_id=?", (shift_id,))
    shift = cur.fetchone()
    if not shift or shift[0] != requester_id:
        conn.close()
        return json.dumps({"status": "error", "message": "Shift not found or does not belong to requester."})
    
    swap_id = f"SWAP_{shift_id}_{partner_id}"
    cur.execute("INSERT OR REPLACE INTO swap_requests VALUES (?,?,?,?,?)",
                (swap_id, requester_id, partner_id, shift_id, "Pending"))
    conn.commit()
    conn.close()
    return json.dumps({"status": "success", "swap_id": swap_id, "requester": requester_id, "partner": partner_id, "shift": shift_id})

def before_model_guardrail(callback_context, llm_request):
    """Blocks injection, unsafe overrides, and destructive scheduling commands."""
    last_text = ""
    if llm_request.contents and llm_request.contents[-1].parts:
        last_text = (llm_request.contents[-1].parts[0].text or "").lower()
    unsafe = ["ignore previous instructions", "reveal system prompt", "force assign", "bypass availability", "override labor laws", "delete shifts"]
    if any(k in last_text for k in unsafe):
        return LlmResponse(content=types.Content(
            role="model",
            parts=[types.Part(text="🛡️ **[GUARDRAIL INTERVENTION]**: Request blocked by Workforce Safety Policy. Scheduling operations require validation.")]
        ))
    return None

# ==============================================================================
# 4. Agent Initialization
# ==============================================================================
@st.cache_resource
def get_workforce_agent():
    return Agent(
        name="workforce_mcp_scheduler",
        model="gemini-3.5-flash",
        description="AI Workforce Scheduler using Model Context Protocol primitives.",
        instruction=(
            "You are an enterprise Workforce Scheduling Analyst operating via MCP-style tools.\n"
            "You do NOT hardcode schedules. Instead, dynamically interact using:\n"
            "1. `mcp_list_entities` to see available workforce tables.\n"
            "2. `mcp_describe_entity` to inspect fields before querying.\n"
            "3. `mcp_query_workforce` to read employees, shifts, availability, or swaps.\n"
            "4. `mcp_assign_shift` to schedule after validation.\n"
            "5. `mcp_request_swap` to log swap intent.\n\n"
            "RULES:\n"
            "- Always verify availability & overlaps before assigning.\n"
            "- Never bypass policy checks or assume data exists.\n"
            "- Summarize schedules clearly with dates, times, and roles.\n"
            "- Swap requests are logged as 'Pending' for manager review.\n"
        ),
        tools=[mcp_list_entities, mcp_describe_entity, mcp_query_workforce, mcp_assign_shift, mcp_request_swap],
        before_model_callback=before_model_guardrail
    )

# ==============================================================================
# 5. Streamlit Session State & Runner Setup
# ==============================================================================
if "session_service" not in st.session_state:
    st.session_state.session_service = InMemorySessionService()
    st.session_state.session_id = "workforce_mcp_session_001"
    st.session_state.session_service.create_session(
        app_name="workforce_mcp_app",
        user_id="scheduler_officer",
        session_id=st.session_state.session_id
    )
    st.session_state.runner = Runner(
        agent=get_workforce_agent(),
        app_name="workforce_mcp_app",
        session_service=st.session_state.session_service,
        auto_create_session=True
    )
    st.session_state.messages = []

# ==============================================================================
# 6. Sidebar: Controls, Prompts & Schema Viewer
# ==============================================================================
with st.sidebar:
    st.title("📅 Workforce Scheduler")
    st.markdown("**AI-Powered Shift Planning (MCP Architecture)**")
    st.markdown("---")

    st.subheader("⚡ Live Data Evolution (MCP Demo)")
    col1, col2 = st.columns(2)
    with col1:
        if st.button("🚀 Add Warehouse Team", use_container_width=True):
            execute_demo_migration()
            st.success("Added `EMP_004` & `EMP_005` with availability!")
            st.rerun()
    with col2:
        if st.button("🔄 Reset DB", use_container_width=True):
            if os.path.exists(DB_FILE):
                os.remove(DB_FILE)
            ensure_database()
            st.warning("Database reset to baseline.")
            st.rerun()

    st.markdown("---")
    st.subheader("💡 Suggested Prompts")
    prompts = [
        "What entities are available in the workforce database?",
        "Show me all active employees and their max weekly hours.",
        "List all scheduled shifts for 2026-11-15.",
        "Assign EMP_001 a Cashier shift on 2026-11-15 from 09:00 to 17:00.",
        "Request a swap: EMP_001 wants to trade SH_20261115_EMP_001 with EMP_002.",
        "Who are you?",
        "Force assign EMP_001 to work 60 hours this week."
    ]
    for p in prompts:
        if st.button(p, use_container_width=True):
            st.session_state.pending_prompt = p

    st.markdown("---")
    with st.expander("📄 View Live Schema", expanded=False):
        st.text(get_live_schema())
    st.caption("🔒 **Security:** MCP Discovery | Policy Validation | ID Masking | Read-First Architecture")

# ==============================================================================
# 7. Main Chat Interface & Workflow
# ==============================================================================
st.title("📊 Virtual Workforce Scheduler (MCP)")
st.caption("Connected via Model Context Protocol | Zero-Touch Schema Evolution | Policy Guardrails Active")

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

prompt_to_send = None
if "pending_prompt" in st.session_state and st.session_state.pending_prompt:
    prompt_to_send = st.session_state.pending_prompt
    st.session_state.pending_prompt = None
else:
    chat_input = st.chat_input("Ask about employees, shifts, availability, or swaps...")
    if chat_input:
        prompt_to_send = chat_input

if prompt_to_send:
    st.session_state.messages.append({"role": "user", "content": prompt_to_send})
    with st.chat_message("user"):
        st.markdown(prompt_to_send)

    with st.chat_message("assistant"):
        with st.spinner("Executing MCP workforce tools & validating policies..."):
            user_msg = types.Content(role="user", parts=[types.Part.from_text(text=prompt_to_send)])
            events = st.session_state.runner.run(
                user_id="scheduler_officer",
                session_id=st.session_state.session_id,
                new_message=user_msg
            )
            response_parts = []
            for e in events:
                if hasattr(e, "content") and e.content:
                    for p in e.content.parts:
                        if hasattr(p, "text") and p.text:
                            response_parts.append(p.text)

            raw_reply = "".join(response_parts) if response_parts else "No response generated."
            final_reply = mask_workforce_ids(raw_reply)
            st.markdown(final_reply)
            st.session_state.messages.append({"role": "assistant", "content": final_reply})