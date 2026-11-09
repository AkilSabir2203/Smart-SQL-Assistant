import json
import re
import psycopg2
import ollama
import os
from dotenv import load_dotenv


# ==========================================================
# DATABASE CONFIGURATION
# ==========================================================

load_dotenv()

DB_CONFIG = {
    # "host": "localhost",
    # "port": "5432",
    # "user": "postgres",
    # "password": "@kiL2207"
    "host": os.getenv("DB_HOST"),
    "port": os.getenv("DB_PORT"),
    "user": os.getenv("DB_USER"),
    "password": os.getenv("DB_PASSWORD"),
    "dbname": os.getenv("DB_NAME")
}

# Used only for discovering available databases
ADMIN_DB = "postgres"

# Databases allowed to be accessed
ALLOWED_DATABASES = [
    "Company",
    "community_mca"
]

TARGET_MODEL = "qwen2.5-coder:1.5b"


# ==========================================================
# CREATE CONNECTION
# ==========================================================

def create_connection(dbname):
    return psycopg2.connect(
        host=DB_CONFIG["host"],
        port=DB_CONFIG["port"],
        user=DB_CONFIG["user"],
        password=DB_CONFIG["password"],
        dbname=dbname
    )


# ==========================================================
# DISCOVER DATABASES
# ==========================================================

def get_available_databases():

    conn = None
    cursor = None

    try:

        conn = create_connection(ADMIN_DB)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT datname
            FROM pg_database
            WHERE datallowconn = true
              AND datistemplate = false
            ORDER BY datname;
        """)

        databases = [
            row[0]
            for row in cursor.fetchall()
            if row[0] in ALLOWED_DATABASES
        ]

        return databases

    except Exception as e:

        print(f"\n❌ Database discovery error: {e}")
        return []

    finally:

        if cursor:
            cursor.close()

        if conn:
            conn.close()


# ==========================================================
# GET DATABASE TABLE/COLUMN METADATA
# ==========================================================

def get_database_metadata(database):

    conn = None
    cursor = None

    try:

        conn = create_connection(database)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT
                table_name,
                column_name,
                data_type
            FROM information_schema.columns
            WHERE table_schema = 'public'
            ORDER BY table_name, ordinal_position;
        """)

        rows = cursor.fetchall()

        if not rows:
            return f"DATABASE: {database}\nNo tables found."

        lines = [
            f"DATABASE: {database}"
        ]

        current_table = None

        for table_name, column_name, data_type in rows:

            if table_name != current_table:

                current_table = table_name

                lines.append("")
                lines.append(f"TABLE: {table_name}")
                lines.append("COLUMNS:")

            lines.append(
                f"- {column_name} ({data_type})"
            )

        return "\n".join(lines)

    except Exception as e:

        return (
            f"DATABASE: {database}\n"
            f"Metadata error: {e}"
        )

    finally:

        if cursor:
            cursor.close()

        if conn:
            conn.close()


# ==========================================================
# GET METADATA FROM ALL DATABASES
# ==========================================================

def get_all_database_metadata(databases):

    all_metadata = []

    for database in databases:

        print(
            f"   Reading metadata from: {database}"
        )

        metadata = get_database_metadata(
            database
        )

        all_metadata.append(metadata)

    return "\n\n".join(all_metadata)


# ==========================================================
# CHOOSE DATABASE
# ==========================================================

def choose_database(
    user_query,
    database_metadata
):

    system_prompt = f"""
You are an expert PostgreSQL database selection assistant.

Your job is to understand the user's question and determine
which database contains the information required to answer it.

AVAILABLE DATABASES AND THEIR TABLES:

{database_metadata}


==========================================================
DATABASE SELECTION RULES
==========================================================

1. Carefully analyze the user's question.

2. Inspect ALL databases, tables and columns provided.

3. Select the database containing the information required
   to answer the question.

4. Use the database whose tables and columns best match
   the user's question.

5. Never invent a database.

6. Never invent a table.

7. Never invent a column.

8. The selected database MUST exactly match one of the
   databases provided above.

9. Do not generate SQL.

10. Think internally, but do not output your reasoning.


==========================================================
OUTPUT FORMAT
==========================================================

Return ONLY valid JSON:

{{
    "database": "exact_database_name"
}}

Do not output markdown.
Do not output explanations.
Do not output reasoning.
"""


    try:

        response = ollama.chat(
            model=TARGET_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": system_prompt
                },
                {
                    "role": "user",
                    "content": user_query
                }
            ]
        )

        raw_response = (
            response["message"]["content"]
            .strip()
        )

        raw_response = (
            raw_response
            .replace("```json", "")
            .replace("```", "")
            .strip()
        )

        match = re.search(
            r"\{.*\}",
            raw_response,
            re.DOTALL
        )

        if not match:

            return None, (
                "LLM did not return valid JSON."
            )

        data = json.loads(
            match.group(0)
        )

        database = data.get(
            "database"
        )

        if not database:

            return None, (
                "LLM did not select a database."
            )

        return database, None

    except json.JSONDecodeError:

        return None, (
            "LLM returned invalid JSON."
        )

    except Exception as e:

        return None, (
            f"LLM Error: {e}"
        )


# ==========================================================
# GET SELECTED DATABASE SCHEMA
# ==========================================================

def get_database_schema(database):

    conn = None
    cursor = None

    try:

        print(
            f"\n🔌 Connecting to selected database: "
            f"{database}"
        )

        conn = create_connection(
            database
        )

        cursor = conn.cursor()

        cursor.execute("""
            SELECT
                table_name,
                column_name,
                data_type
            FROM information_schema.columns
            WHERE table_schema = 'public'
            ORDER BY table_name, ordinal_position;
        """)

        rows = cursor.fetchall()

        if not rows:

            return None, (
                "No tables found."
            )

        lines = [
            f"DATABASE: {database}"
        ]

        current_table = None

        for table_name, column_name, data_type in rows:

            if table_name != current_table:

                current_table = table_name

                lines.append("")
                lines.append(
                    f"TABLE: {table_name}"
                )
                lines.append(
                    "COLUMNS:"
                )

            lines.append(
                f"- {column_name} ({data_type})"
            )

        return "\n".join(lines), None

    except Exception as e:

        return None, (
            f"Schema extraction error: {e}"
        )

    finally:

        if cursor:
            cursor.close()

        if conn:
            conn.close()


# ==========================================================
# GET RELATIONSHIPS
# ==========================================================

def get_database_relationships(database):

    conn = None
    cursor = None

    try:

        conn = create_connection(
            database
        )

        cursor = conn.cursor()

        cursor.execute("""
            SELECT
                tc.table_name,
                kcu.column_name,
                tc.constraint_type,
                ccu.table_name,
                ccu.column_name
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
                ON tc.constraint_name = kcu.constraint_name
                AND tc.table_schema = kcu.table_schema
            LEFT JOIN information_schema.constraint_column_usage ccu
                ON tc.constraint_name = ccu.constraint_name
                AND tc.table_schema = ccu.table_schema
            WHERE tc.table_schema = 'public'
              AND tc.constraint_type IN (
                  'PRIMARY KEY',
                  'FOREIGN KEY'
              )
            ORDER BY tc.table_name;
        """)

        rows = cursor.fetchall()

        if not rows:

            return "No primary or foreign keys found."

        relationships = []

        for row in rows:

            (
                table_name,
                column_name,
                constraint_type,
                foreign_table,
                foreign_column
            ) = row

            if constraint_type == "PRIMARY KEY":

                relationships.append(
                    f"{table_name}.{column_name} "
                    f"-> PRIMARY KEY"
                )

            elif constraint_type == "FOREIGN KEY":

                relationships.append(
                    f"{table_name}.{column_name} "
                    f"-> FOREIGN KEY -> "
                    f"{foreign_table}.{foreign_column}"
                )

        return "\n".join(
            relationships
        )

    except Exception as e:

        return (
            f"Relationship extraction error: {e}"
        )

    finally:

        if cursor:
            cursor.close()

        if conn:
            conn.close()


# ==========================================================
# GENERATE SQL
# ==========================================================

def generate_sql(
    user_query,
    selected_database,
    schema_text,
    relationship_text
):

    system_prompt = f"""
You are an expert PostgreSQL SQL generator.

The correct database has already been selected.

DATABASE:
{selected_database}


==========================================================
DATABASE SCHEMA
==========================================================

{schema_text}


==========================================================
TABLE RELATIONSHIPS
==========================================================

{relationship_text}


==========================================================
TASK
==========================================================

Convert the user's natural language question into
a correct PostgreSQL SELECT query.


==========================================================
INTERNAL REASONING
==========================================================

Think internally:

1. Understand the user's question.

2. Inspect the complete schema.

3. Select the correct table or tables.

4. Select the exact columns.

5. Check table relationships.

6. Use JOIN when necessary.

7. Determine WHERE conditions.

8. Determine ORDER BY.

9. Determine GROUP BY or aggregation.

10. Determine LIMIT or OFFSET.

11. Generate the final SELECT query.

Do NOT output your reasoning.


==========================================================
TABLE RULES
==========================================================

1. Use EXACT table names from the schema.

2. Do NOT pluralize table names.

3. Use EXACT column names.

4. Never invent tables.

5. Never invent columns.

6. Use JOIN only when required.

7. Use valid relationships only.


==========================================================
WHERE RULES
==========================================================

1. Use WHERE when the user provides a condition.

2. Use exact column names.

3. Use the values provided by the user.

4. Do not add unnecessary conditions.

5. Text values use single quotes.

6. Numeric values do not use quotes.


==========================================================
SQL SAFETY
==========================================================

ONLY SELECT queries are allowed.

Never generate:

INSERT
UPDATE
DELETE
DROP
ALTER
TRUNCATE
CREATE
GRANT
REVOKE
MERGE
REPLACE

Never modify database data.

Never modify database structure.


==========================================================
OUTPUT
==========================================================

Return ONLY raw SQL.

Do not output:

- reasoning
- explanation
- markdown
- ```sql
- comments
- conversational text

Return only the SELECT query.
"""


    try:

        response = ollama.chat(
            model=TARGET_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": system_prompt
                },
                {
                    "role": "user",
                    "content": user_query
                }
            ]
        )

        raw_sql = (
            response["message"]["content"]
            .strip()
        )

        if raw_sql.startswith(
            "```sql"
        ):

            raw_sql = raw_sql[6:]

        elif raw_sql.startswith(
            "```"
        ):

            raw_sql = raw_sql[3:]

        if raw_sql.endswith(
            "```"
        ):

            raw_sql = raw_sql[:-3]

        return raw_sql.strip()

    except Exception as e:

        return f"LLM Error: {e}"


# ==========================================================
# READ-ONLY VALIDATION
# ==========================================================

def is_read_only_query(sql_query):

    if not sql_query:

        return False

    sql = (
        sql_query
        .strip()
        .lower()
    )

    sql = (
        sql
        .rstrip(";")
        .strip()
    )

    if not sql.startswith(
        "select"
    ):

        return False

    forbidden_commands = [
        "insert ",
        "update ",
        "delete ",
        "drop ",
        "alter ",
        "truncate ",
        "create ",
        "grant ",
        "revoke ",
        "replace ",
        "merge "
    ]

    for command in forbidden_commands:

        if command in sql:

            return False

    return True


# ==========================================================
# EXECUTE SQL
# ==========================================================

def execute_sql(
    selected_database,
    sql_query
):

    if not is_read_only_query(
        sql_query
    ):

        return None, (
            "BLOCKED: Only SELECT queries are allowed."
        )

    conn = None
    cursor = None

    try:

        print(
            f"\n🔌 Connecting to: "
            f"{selected_database}"
        )

        conn = create_connection(
            selected_database
        )

        cursor = conn.cursor()

        # --------------------------------------------------
        # Verify actual database
        # --------------------------------------------------

        cursor.execute("""
            SELECT
                current_database(),
                current_user,
                inet_server_addr(),
                inet_server_port();
        """)

        db_info = cursor.fetchone()

        print(
            "\n-----------------------------------------------"
        )

        print(
            "DATABASE CONNECTION"
        )

        print(
            "-----------------------------------------------"
        )

        print(
            f"Database : {db_info[0]}"
        )

        print(
            f"User     : {db_info[1]}"
        )

        print(
            f"Server   : {db_info[2]}"
        )

        print(
            f"Port     : {db_info[3]}"
        )

        # --------------------------------------------------
        # Execute SQL
        # --------------------------------------------------

        print(
            "\nSQL being executed:"
        )

        print(
            sql_query
        )

        cursor.execute(
            sql_query
        )

        column_names = [
            description[0]
            for description in cursor.description
        ]

        records = cursor.fetchall()

        return (
            column_names,
            records
        )

    except Exception as e:

        return None, (
            f"Database Execution Error: {e}"
        )

    finally:

        if cursor:
            cursor.close()

        if conn:
            conn.close()


# ==========================================================
# DISPLAY RESULTS
# ==========================================================

def display_results(
    columns,
    results
):

    print(
        "\n=================================================="
    )

    print(
        "QUERY RESULTS"
    )

    print(
        "=================================================="
    )

    if columns is None:

        print(
            results
        )

        return

    if len(results) == 0:

        print(
            "No records found."
        )

        return

    formatted_rows = []

    for row in results:

        formatted_row = []

        for value in row:

            if value is None:

                formatted_row.append(
                    "NULL"
                )

            else:

                formatted_row.append(
                    str(value)
                )

        formatted_rows.append(
            formatted_row
        )

    widths = []

    for i, column in enumerate(
        columns
    ):

        max_width = len(
            column
        )

        for row in formatted_rows:

            max_width = max(
                max_width,
                len(row[i])
            )

        max_width = min(
            max_width,
            40
        )

        widths.append(
            max_width
        )

    header = " | ".join(
        column[:widths[i]].ljust(
            widths[i]
        )
        for i, column in enumerate(
            columns
        )
    )

    print(
        header
    )

    separator = "-+-".join(
        "-" * width
        for width in widths
    )

    print(
        separator
    )

    for row in formatted_rows:

        row_text = " | ".join(
            row[i][:widths[i]].ljust(
                widths[i]
            )
            for i in range(
                len(columns)
            )
        )

        print(
            row_text
        )

    print(
        "=================================================="
    )


# ==========================================================
# MAIN
# ==========================================================

if __name__ == "__main__":

    print("\n")

    print(
        "=================================================="
    )

    print(
        "🤖 SMART SQL ASSISTANT"
    )

    print(
        "=================================================="
    )

    # ======================================================
    # STEP 1: GET AVAILABLE DATABASES
    # ======================================================

    print(
        "\n🔍 Discovering available databases..."
    )

    available_databases = (
        get_available_databases()
    )

    if not available_databases:

        print(
            "\n❌ No allowed databases found."
        )

        exit()

    print(
        "\n✅ Available databases:"
    )

    for database in available_databases:

        print(
            f"   • {database}"
        )


    # ======================================================
    # STEP 2: GET DATABASE METADATA
    # ======================================================

    print(
        "\n🔍 Reading database metadata..."
    )

    database_metadata = (
        get_all_database_metadata(
            available_databases
        )
    )

    print(
        "\n✅ Database metadata loaded."
    )


    # ======================================================
    # TERMINAL
    # ======================================================
    if __name__ == "__main__":
        print("\n")
        print(
            "\n=================================================="
        )

        print(
            "🤖 Welcome to Smart SQL Assistant"
        )

        print(
            "=================================================="
        )

        print(
            "\nType 'exit' or 'quit' to close.\n"
        )


        # ======================================================
        # INTERACTIVE LOOP
        # ======================================================

    while True:

        user_question = input("📝 Enter your request: ")

        if user_question.lower().strip() in ["exit", "quit"]:
            break

        # 1. Get database + table metadata
        database_metadata = get_all_database_metadata(
            available_databases
        )

        # 2. LLM chooses database FOR THIS QUESTION
        selected_database, error = choose_database(
            user_question,
            database_metadata
        )

        if error:
            print(error)
            continue

        print(f"🤖 Selected database: {selected_database}")

        # 3. Validate selected database
        if selected_database not in available_databases:
            print("🚫 Invalid database selected.")
            continue

        # 4. Connect ONLY to selected database
        selected_schema, schema_error = get_database_schema(
            selected_database
        )

        if schema_error:
            print(schema_error)
            continue

        # 5. Get relationships from selected database
        relationship_text = get_database_relationships(
            selected_database
        )

        # 6. Generate SQL using selected database schema
        generated_sql = generate_sql(
            user_question,
            selected_database,
            selected_schema,
            relationship_text
        )

        print(f"\n🤖 Generated SQL:\n{generated_sql}")

        # 7. Validate SQL
        if not is_read_only_query(generated_sql):
            print("🚫 Query blocked!")
            continue

        # 8. Connect to selected database and execute
        columns, results = execute_sql(
            selected_database,
            generated_sql
        )

        # 9. Display results
        display_results(
            columns,
            results
        )