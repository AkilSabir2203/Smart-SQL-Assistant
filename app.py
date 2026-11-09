import streamlit as st
import pandas as pd

# Import functions from your backend modules
from llm_engine import (
    get_available_databases,
    get_all_database_metadata,
    choose_database,
    get_database_schema,
    get_database_relationships,
    generate_sql,
    is_read_only_query,
    execute_sql,
    ALLOWED_DATABASES,
    TARGET_MODEL
)
from schema_extractor import get_database_schema as get_single_schema

# ==========================================================
# PAGE CONFIGURATION & STYLING
# ==========================================================

st.set_page_config(
    page_title="Smart SQL Assistant",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom styling for chat bubbles and layout
st.markdown("""
    <style>
    .stChatMessage {
        border-radius: 10px;
        padding: 10px;
    }
    [data-testid="stChatInput"] {
        border-radius: 30px !important;
        overflow: hidden !important;
    }

    [data-testid="stChatInput"] > div {
        border-radius: 50px !important;
    }

    [data-testid="stChatInput"] textarea {
        border-radius: 30px !important;
        padding: 14px 18px !important;
    }

    /* Circular send button */
    [data-testid="stChatInput"] button {
        border-radius: 50% !important;
    }
    </style>
""", unsafe_allow_html=True)


# ==========================================================
# SIDEBAR CONTROLS (Theme, Model Selection & DB Info)
# ==========================================================

st.sidebar.title("⚙️ Control Panel")

# Model Switcher Dropdown (Right upper corner option via sidebar)
selected_model = st.sidebar.selectbox(
    "🤖 Select LLM Model",
    options=[TARGET_MODEL, "qwen2.5-coder", "llama3.2", "llama3.1"],
    index=0
)

st.sidebar.divider()
st.sidebar.subheader("📊 Database Status")

available_dbs = get_available_databases()
if available_dbs:
    st.sidebar.success(f"Connected! Found {len(available_dbs)} DB(s):")
    for db in available_dbs:
        st.sidebar.write(f"• `{db}`")
else:
    st.sidebar.error("No allowed databases accessible. Check your `.env` credentials.")

# View database schemas in sidebar expander
with st.sidebar.expander("🔍 Inspect Database Schemas"):
    if available_dbs:
        for db in available_dbs:
            st.markdown(f"**Database: `{db}`**")
            schema_text, err = get_database_schema(db)
            if schema_text:
                st.code(schema_text, language="text")
            else:
                st.caption(err)


# ==========================================================
# MAIN CHAT INTERFACE
# ==========================================================

st.title("🤖 Smart SQL Assistant")
st.caption("Ask natural language questions to query your PostgreSQL database securely using local LLMs.")

# Initialize chat session history
if "messages" not in st.session_state:
    st.session_state.messages = []

# Display prior chat messages
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        if message["role"] == "user":
            st.write(message["content"])
        else:
            if "selected_db" in message:
                st.caption(f"📁 **Target Database:** `{message['selected_db']}`")
            if "sql" in message:
                st.subheader("Generated SQL Query")
                st.code(message["sql"], language="sql")
            if "df" in message and message["df"] is not None:
                st.subheader("Query Results")
                if message["df"].empty:
                    st.info("No records found.")
                else:
                    st.dataframe(message["df"], use_container_width=True)
            if "error" in message and message["error"]:
                st.error(message["error"])

# Chat Input Box
if prompt := st.chat_input("e.g., Top 5 salaries of Emplyees"):
    
    # 1. Append and display user message
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.write(prompt)

    # 2. Process Assistant Response
    with st.chat_message("assistant"):
        if not available_dbs:
            err_msg = "No accessible databases found. Please verify your PostgreSQL connection."
            st.error(err_msg)
            st.session_state.messages.append({
                "role": "assistant",
                "error": err_msg
            })
        else:
            with st.spinner("Analyzing schema & choosing target database..."):
                all_metadata = get_all_database_metadata(available_dbs)
                selected_db, db_err = choose_database(prompt, all_metadata)

            if db_err or not selected_db or selected_db not in available_dbs:
                err_msg = db_err if db_err else f"Invalid database chosen: `{selected_db}`"
                st.error(f"🚫 {err_msg}")
                st.session_state.messages.append({
                    "role": "assistant",
                    "error": err_msg
                })
            else:
                st.caption(f"📁 **Selected Database:** `{selected_db}`")

                with st.spinner("Generating SQL query..."):
                    selected_schema, schema_err = get_database_schema(selected_db)
                    relationship_text = get_database_relationships(selected_db)
                    
                    if schema_err:
                        generated_sql = f"Error: {schema_err}"
                    else:
                        generated_sql = generate_sql(
                            prompt,
                            selected_db,
                            selected_schema,
                            relationship_text
                        )

                st.subheader("Generated SQL Query")
                st.code(generated_sql, language="sql")

                # Validate Read-Only Safety Check
                if not is_read_only_query(generated_sql):
                    err_msg = "BLOCKED: Only SELECT queries are allowed."
                    st.error(f"🚫 {err_msg}")
                    st.session_state.messages.append({
                        "role": "assistant",
                        "selected_db": selected_db,
                        "sql": generated_sql,
                        "error": err_msg
                    })
                else:
                    with st.spinner("Executing query on database..."):
                        columns, results = execute_sql(selected_db, generated_sql)

                    if columns is None:
                        err_msg = results if isinstance(results, str) else "Database Execution Error."
                        st.error(f"❌ {err_msg}")
                        st.session_state.messages.append({
                            "role": "assistant",
                            "selected_db": selected_db,
                            "sql": generated_sql,
                            "error": err_msg
                        })
                    else:
                        st.subheader("Query Results")
                        df = pd.DataFrame(results, columns=columns) if results else pd.DataFrame(columns=columns)
                        
                        if df.empty:
                            st.info("No records found.")
                        else:
                            st.dataframe(df, use_container_width=True)

                        # Save interaction in session state history
                        st.session_state.messages.append({
                            "role": "assistant",
                            "selected_db": selected_db,
                            "sql": generated_sql,
                            "df": df
                        })