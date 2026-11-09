import json
import re
import psycopg2
import mysql.connector
import ollama
import os
from dotenv import load_dotenv

load_dotenv()

TARGET_MODEL = "qwen2.5-coder:1.5b"
ALLOWED_DATABASES = ["Company", "community_mca", "testdb"]

# ==========================================================
# CREATE CONNECTION (Dynamic DBMS Support)
# ==========================================================

def create_connection(dbms_type, host, port, user, password, dbname):
    dbms_type = dbms_type.lower().strip()
    
    if dbms_type == "postgresql":
        return psycopg2.connect(
            host=host,
            port=port,
            user=user,
            password=password,
            dbname=dbname
        )
    elif dbms_type == "mysql":
        return mysql.connector.connect(
            host=host,
            port=int(port) if port else 3306,
            user=user,
            password=password,
            database=dbname if dbname else None
        )
    else:
        raise ValueError(f"Unsupported DBMS type: {dbms_type}")


# ==========================================================
# DISCOVER DATABASES
# ==========================================================

def get_available_databases(dbms_type, host, port, user, password):
    try:
        dbms_type = dbms_type.lower().strip()
        if dbms_type == "postgresql":
            conn = create_connection(dbms_type, host, port, user, password, "postgres")
            cursor = conn.cursor()
            cursor.execute("""
                SELECT datname
                FROM pg_database
                WHERE datallowconn = true
                  AND datistemplate = false
                ORDER BY datname;
            """)
            databases = [row[0] for row in cursor.fetchall()]
            cursor.close()
            conn.close()
            return databases
        elif dbms_type == "mysql":
            conn = create_connection(dbms_type, host, port, user, password, "")
            cursor = conn.cursor()
            cursor.execute("SHOW DATABASES;")
            databases = [row[0] for row in cursor.fetchall() if row[0] not in ['information_schema', 'performance_schema', 'mysql', 'sys']]
            cursor.close()
            conn.close()
            return databases
        return []
    except Exception as e:
        print(f"\n❌ Database discovery error: {e}")
        return []


# ==========================================================
# GET DATABASE TABLE/COLUMN METADATA
# ==========================================================

def get_database_metadata(dbms_type, host, port, user, password, database):
    try:
        conn = create_connection(dbms_type, host, port, user, password, database)
        cursor = conn.cursor()

        if dbms_type.lower() == "postgresql":
            cursor.execute("""
                SELECT table_name, column_name, data_type
                FROM information_schema.columns
                WHERE table_schema = 'public'
                ORDER BY table_name, ordinal_position;
            """)
        elif dbms_type.lower() == "mysql":
            cursor.execute(f"""
                SELECT TABLE_NAME, COLUMN_NAME, DATA_TYPE
                FROM INFORMATION_SCHEMA.COLUMNS
                WHERE TABLE_SCHEMA = '{database}'
                ORDER BY TABLE_NAME, ORDINAL_POSITION;
            """)

        rows = cursor.fetchall()
        cursor.close()
        conn.close()

        if not rows:
            return f"DATABASE: {database}\nNo tables found."

        lines = [f"DATABASE: {database}"]
        current_table = None

        for table_name, column_name, data_type in rows:
            if table_name != current_table:
                current_table = table_name
                lines.append("")
                lines.append(f"TABLE: {table_name}")
                lines.append("COLUMNS:")
            lines.append(f"- {column_name} ({data_type})")

        return "\n".join(lines)
    except Exception as e:
        return f"DATABASE: {database}\nMetadata error: {e}"


def get_all_database_metadata(dbms_type, host, port, user, password, databases):
    all_metadata = []
    for database in databases:
        metadata = get_database_metadata(dbms_type, host, port, user, password, database)
        all_metadata.append(metadata)
    return "\n\n".join(all_metadata)


# ==========================================================
# CHOOSE DATABASE
# ==========================================================

def choose_database(user_query, database_metadata, model_name=TARGET_MODEL):
    print(f"\n🤖 Database Selection Model: {model_name}")
    system_prompt = f"""
You are an expert SQL database selection assistant.
Your job is to understand the user's question and determine which database contains the required information.

AVAILABLE DATABASES AND THEIR TABLES:
{database_metadata}

Return ONLY valid JSON:
{{
    "database": "exact_database_name"
}}
Do not output markdown, explanations, or reasoning.
"""
    try:
        response = ollama.chat(
            model=model_name,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_query}
            ]
        )
        raw_response = response["message"]["content"].strip().replace("```json", "").replace("```", "").strip()
        match = re.search(r"\{.*\}", raw_response, re.DOTALL)
        if not match:
            return None, "LLM did not return valid JSON."
        data = json.loads(match.group(0))
        return data.get("database"), None
    except Exception as e:
        return None, f"LLM Error: {e}"


# ==========================================================
# GET SCHEMA & RELATIONSHIPS
# ==========================================================

def get_database_schema(dbms_type, host, port, user, password, database):
    try:
        conn = create_connection(dbms_type, host, port, user, password, database)
        cursor = conn.cursor()

        if dbms_type.lower() == "postgresql":
            cursor.execute("""
                SELECT table_name, column_name, data_type
                FROM information_schema.columns
                WHERE table_schema = 'public'
                ORDER BY table_name, ordinal_position;
            """)
        elif dbms_type.lower() == "mysql":
            cursor.execute(f"""
                SELECT TABLE_NAME, COLUMN_NAME, DATA_TYPE
                FROM INFORMATION_SCHEMA.COLUMNS
                WHERE TABLE_SCHEMA = '{database}'
                ORDER BY TABLE_NAME, ORDINAL_POSITION;
            """)

        rows = cursor.fetchall()
        cursor.close()
        conn.close()

        if not rows:
            return None, "No tables found."

        lines = [f"DATABASE: {database}"]
        current_table = None
        for table_name, column_name, data_type in rows:
            if table_name != current_table:
                current_table = table_name
                lines.append("")
                lines.append(f"TABLE: {table_name}")
                lines.append("COLUMNS:")
            lines.append(f"- {column_name} ({data_type})")

        return "\n".join(lines), None
    except Exception as e:
        return None, f"Schema extraction error: {e}"


def get_database_relationships(dbms_type, host, port, user, password, database):
    try:
        conn = create_connection(dbms_type, host, port, user, password, database)
        cursor = conn.cursor()

        if dbms_type.lower() == "postgresql":
            cursor.execute("""
                SELECT tc.table_name, kcu.column_name, tc.constraint_type, ccu.table_name, ccu.column_name
                FROM information_schema.table_constraints tc
                JOIN information_schema.key_column_usage kcu
                    ON tc.constraint_name = kcu.constraint_name AND tc.table_schema = kcu.table_schema
                LEFT JOIN information_schema.constraint_column_usage ccu
                    ON tc.constraint_name = ccu.constraint_name AND tc.table_schema = ccu.table_schema
                WHERE tc.table_schema = 'public' AND tc.constraint_type IN ('PRIMARY KEY', 'FOREIGN KEY')
                ORDER BY tc.table_name;
            """)
            rows = cursor.fetchall()
            cursor.close()
            conn.close()

            if not rows:
                return "No primary or foreign keys found."

            relationships = []
            for row in rows:
                table_name, column_name, constraint_type, foreign_table, foreign_column = row
                if constraint_type == "PRIMARY KEY":
                    relationships.append(f"{table_name}.{column_name} -> PRIMARY KEY")
                elif constraint_type == "FOREIGN KEY":
                    relationships.append(f"{table_name}.{column_name} -> FOREIGN KEY -> {foreign_table}.{foreign_column}")
            return "\n".join(relationships)
        else:
            return "Relationships checked via schema."
    except Exception as e:
        return f"Relationship extraction error: {e}"


# ==========================================================
# GENERATE & EXECUTE SQL
# ==========================================================

def generate_sql(user_query, selected_database, schema_text, relationship_text, model_name=TARGET_MODEL):
    system_prompt = f"""
You are an expert SQL generator. Convert the user's natural language question into a correct SELECT query.

DATABASE: {selected_database}
SCHEMA:
{schema_text}

RELATIONSHIPS:
{relationship_text}

ONLY SELECT queries are allowed. Return ONLY raw SQL without markdown or explanation.
"""
    try:
        response = ollama.chat(
            model=model_name,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_query}
            ]
        )
        raw_sql = response["message"]["content"].strip()
        if raw_sql.startswith("```sql"):
            raw_sql = raw_sql[6:]
        elif raw_sql.startswith("```"):
            raw_sql = raw_sql[3:]
        if raw_sql.endswith("```"):
            raw_sql = raw_sql[:-3]
        return raw_sql.strip()
    except Exception as e:
        return f"LLM Error: {e}"


def is_read_only_query(sql_query):
    if not sql_query:
        return False
    sql = sql_query.strip().lower().rstrip(";").strip()
    if not sql.startswith("select"):
        return False
    forbidden = ["insert ", "update ", "delete ", "drop ", "alter ", "truncate ", "create ", "grant ", "revoke ", "replace ", "merge "]
    for cmd in forbidden:
        if cmd in sql:
            return False
    return True


def execute_sql(dbms_type, host, port, user, password, selected_database, sql_query):
    if not is_read_only_query(sql_query):
        return None, None, "BLOCKED: Only SELECT queries are allowed."
    try:
        conn = create_connection(dbms_type, host, port, user, password, selected_database)
        cursor = conn.cursor()
        cursor.execute(sql_query)
        
        # Extract column descriptions
        column_names = [desc[0] for desc in cursor.description]
        records = cursor.fetchall()
        
        cursor.close()
        conn.close()
        return column_names, records, None
    except Exception as e:
        return None, None, f"Database Execution Error: {e}"