import streamlit as st
import pandas as pd
import time

from llm_engine import (
    get_available_databases,
    get_all_database_metadata,
    choose_database,
    get_database_schema,
    get_database_relationships,
    generate_sql,
    is_read_only_query,
    validate_sql_syntax,
    execute_sql
)
from metrics import record_model_outcome


st.set_page_config(
    page_title="Smart SQL Assistant",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown("""
    <style>
    .stChatMessage {
        border-radius: 10px;
        padding: 10px;
    }
    </style>
""", unsafe_allow_html=True)

st.sidebar.title("⚙️ Connection Settings")

dbms_choice = st.sidebar.selectbox(
    "🗄️ Select DBMS",
    options=["PostgreSQL", "MySQL"],
    index=0
)

db_host = st.sidebar.text_input("Host", value="localhost")
db_port = st.sidebar.text_input("Port", value="5432" if dbms_choice == "PostgreSQL" else "3306")
db_user = st.sidebar.text_input("Username", value="postgres" if dbms_choice == "PostgreSQL" else "root")
db_password = st.sidebar.text_input("Password", type="password", value="")

selected_model = st.sidebar.selectbox(
    "🤖 Select LLM Model",
    options=["qwen2.5-coder:1.5b", "llama3.2"],
    index=0
)

st.sidebar.divider()
st.sidebar.subheader("📊 Database Status")

available_dbs = get_available_databases(dbms_choice, db_host, db_port, db_user, db_password)

if available_dbs:
    st.sidebar.success(f"Connected! Found {len(available_dbs)} DB(s):")
    for db in available_dbs:
        st.sidebar.write(f"• `{db}`")
else:
    st.sidebar.warning("⚠️ Enter valid credentials and password above to connect.")

with st.sidebar.expander("🔍 Inspect Database Schemas"):
    if available_dbs:
        for db in available_dbs:
            st.markdown(f"**Database: `{db}`**")
            schema_text, err = get_database_schema(dbms_choice, db_host, db_port, db_user, db_password, db)
            if schema_text:
                st.code(schema_text, language="text")
            else:
                st.caption(err)


st.title("🤖 Smart SQL Assistant")
st.caption(f"Connected to **{dbms_choice}** database server. Ask natural language questions to query your data securely.")

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

if prompt := st.chat_input("e.g., Top 5 salaries of Employees"):
    request_start = time.perf_counter()
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.write(prompt)

    with st.chat_message("assistant"):
        if not available_dbs:
            err_msg = "No accessible databases found. Please verify your DBMS credentials and password in the sidebar."
            st.error(err_msg)
            st.session_state.messages.append({
                "role": "assistant",
                "error": err_msg
            })
        else:
            with st.spinner("Analyzing schema & choosing target database..."):
                all_metadata = get_all_database_metadata(dbms_choice, db_host, db_port, db_user, db_password, available_dbs)
                selected_db, db_err = choose_database(prompt, all_metadata, selected_model)

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
                    selected_schema, schema_err = get_database_schema(dbms_choice, db_host, db_port, db_user, db_password, selected_db)
                    relationship_text = get_database_relationships(dbms_choice, db_host, db_port, db_user, db_password, selected_db)
                    
                    if schema_err:
                        generated_sql = f"Error: {schema_err}"
                    else:
                        generated_sql = generate_sql(
                            prompt,
                            selected_db,
                            selected_schema,
                            relationship_text,
                            selected_model
                        )

                st.subheader("Generated SQL Query")
                st.code(generated_sql, language="sql")

                syntax_error = validate_sql_syntax(generated_sql, dbms_choice)
                if syntax_error:
                    err_msg = syntax_error
                    st.error(f"🚫 {err_msg}")
                    st.session_state.messages.append({
                        "role": "assistant",
                        "selected_db": selected_db,
                        "sql": generated_sql,
                        "error": err_msg
                    })
                    record_model_outcome(
                        selected_model, False, time.perf_counter() - request_start,
                        False, False, "sql_generation", "syntax_validation"
                    )
                elif not is_read_only_query(generated_sql):
                    err_msg = "BLOCKED: Only SELECT queries are allowed."
                    st.error(f"🚫 {err_msg}")
                    st.session_state.messages.append({
                        "role": "assistant",
                        "selected_db": selected_db,
                        "sql": generated_sql,
                        "error": err_msg
                    })
                    record_model_outcome(
                        selected_model, False, time.perf_counter() - request_start,
                        True, False, "read_only_policy", "read_only_block"
                    )
                else:
                    with st.spinner("Executing query on database..."):
                        columns, results, exec_err = execute_sql(
                            dbms_choice, db_host, db_port, db_user, db_password, selected_db, generated_sql
                        )

                    if exec_err:
                        st.error(f"❌ {exec_err}")
                        st.session_state.messages.append({
                            "role": "assistant",
                            "selected_db": selected_db,
                            "sql": generated_sql,
                            "error": exec_err
                        })
                        record_model_outcome(
                            selected_model, False, time.perf_counter() - request_start,
                            True, False, "database_execution", "database_execution"
                        )
                    else:
                        st.subheader("Query Results")
                        df = pd.DataFrame(results, columns=columns) if results else pd.DataFrame(columns=columns)
                        
                        if df.empty:
                            st.info("No records found.")
                        else:
                            st.dataframe(df, use_container_width=True)

                        st.session_state.messages.append({
                            "role": "assistant",
                            "selected_db": selected_db,
                            "sql": generated_sql,
                            "df": df
                        })
                        record_model_outcome(
                            selected_model, True, time.perf_counter() - request_start,
                            True, True, "database_execution"
                        )