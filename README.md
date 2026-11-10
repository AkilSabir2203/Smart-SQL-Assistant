# Smart SQL Assistant

Smart SQL Assistant is a Streamlit application that lets users ask natural-language questions about PostgreSQL or MySQL databases. It uses a locally hosted Ollama language model to select the most relevant database, understand the database schema, generate a SQL query, validate the generated SQL, and display the query results.

The application is designed for read-only exploration. Generated statements are restricted to a single `SELECT` query and are parsed with `sqlglot` before they are sent to the database.

## Features

- Natural-language database queries through a Streamlit chat interface.
- PostgreSQL and MySQL connection support.
- Database discovery using the configured database credentials.
- Automatic database selection based on database and table metadata.
- Schema and primary-key/foreign-key relationship extraction.
- Local LLM support through Ollama.
- Model selection from the Streamlit sidebar:
  - `qwen2.5-coder:1.5b`
  - `llama3.2`
- SQL code display before execution.
- SQL syntax validation using the target database dialect:
  - PostgreSQL
  - MySQL
- Read-only enforcement that blocks data-definition and data-modification statements.
- Query results displayed as a table through pandas and Streamlit.
- Conversation history retained in the current Streamlit session.

## How It Works

For each user question, the application follows this flow:

1. Connects to the selected DBMS and discovers accessible databases.
2. Loads table and column metadata for the available databases.
3. Asks the Ollama model to select the database most likely to contain the requested information.
4. Extracts the selected database schema and key relationships.
5. Asks the model to generate a raw SQL query using the user question and schema context.
6. Parses the generated SQL with `sqlglot` using the selected DBMS dialect.
7. Rejects empty, malformed, unsupported, or multiple SQL statements.
8. Checks that the query is read-only and starts with `SELECT`.
9. Executes the query against the selected database.
10. Displays the generated SQL and returned rows in the chat interface.

The application performs validation both in the user-interface flow and inside `execute_sql`. The second check protects the database execution boundary even if `execute_sql` is called from another module.

## Project Structure

```text
smart-sql-assistant/
├── app.py              # Streamlit user interface and request workflow
├── llm_engine.py       # Database access, metadata extraction, LLM calls, SQL validation
├── schema_extractor.py # Standalone PostgreSQL schema extraction utility
├── requirements.txt    # Python dependencies
├── .env.example        # Example environment variable names
└── README.md           # Project documentation
```

### Main modules

#### `app.py`

Defines the Streamlit application:

- DBMS selector and connection fields.
- Ollama model selector.
- Database status and schema inspection sidebar.
- Chat history and chat input.
- SQL validation and read-only checks.
- Query execution and result rendering.

#### `llm_engine.py`

Contains the application logic for:

- Creating PostgreSQL and MySQL connections.
- Discovering databases.
- Reading table and column metadata.
- Reading key relationships.
- Selecting a database with Ollama.
- Generating SQL with Ollama.
- Validating SQL syntax with `sqlglot`.
- Executing validated read-only SQL.

#### `schema_extractor.py`

Provides a separate PostgreSQL-only schema extraction script. It is useful for manually inspecting a local PostgreSQL database, but the Streamlit application uses the reusable schema functions in `llm_engine.py`.

## Requirements

Before running the application, install:

- Python 3.10 or newer.
- PostgreSQL and/or MySQL access.
- Ollama.
- An Ollama model supported by the application.
- Network or local access to the target database server.

The Python dependencies are pinned in [`requirements.txt`](requirements.txt), including:

- Streamlit
- pandas
- `psycopg2-binary`
- `mysql-connector-python`
- Ollama's Python client
- `sqlglot`
- `python-dotenv`

## Installation

### 1. Clone the repository

```bash
git clone https://github.com/AkilSabir2203/Smart-SQL-Assistant.git
cd Smart-SQL-Assistant
```

### 2. Create and activate a virtual environment

Windows PowerShell:

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
```

Windows Command Prompt:

```bat
python -m venv venv
venv\Scripts\activate
```

macOS/Linux:

```bash
python3 -m venv venv
source venv/bin/activate
```

### 3. Install Python dependencies

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

### 4. Install and start Ollama

Install Ollama from [ollama.com](https://ollama.com/), then make sure the Ollama service is running.

Pull at least one model used by the application:

```bash
ollama pull qwen2.5-coder:1.5b
ollama pull llama3.2
```

The default model is `qwen2.5-coder:1.5b`. You can select another installed model from the application sidebar.

## Configuration

The application collects database connection values in the Streamlit sidebar:

| Setting | PostgreSQL default | MySQL default |
|---|---:|---:|
| DBMS | PostgreSQL | MySQL |
| Host | `localhost` | `localhost` |
| Port | `5432` | `3306` |
| Username | `postgres` | `root` |
| Password | Empty | Empty |

The repository includes [`.env.example`](.env.example) as a reference for common database variables:

```dotenv
DB_HOST=localhost
DB_PORT=5432
DB_USER=postgres
DB_PASSWORD=your_postgres_password
DB_NAME=your_db_name
```

Copy it to `.env` if you want a local environment file for future configuration:

```powershell
Copy-Item .env.example .env
```

Do not commit `.env` or real credentials. Use a database account with the minimum permissions required for read-only queries.

## Running the Application

From the project directory and with the virtual environment activated:

```bash
streamlit run app.py
```

Streamlit normally opens the application in a browser. If it does not, open the URL printed in the terminal, usually:

```text
http://localhost:8501
```

### Typical usage

1. Select PostgreSQL or MySQL.
2. Enter the database host, port, username, and password.
3. Select an installed Ollama model.
4. Confirm that the sidebar reports accessible databases.
5. Optionally expand **Inspect Database Schemas** to review discovered tables and columns.
6. Enter a question such as:

   ```text
   Show the top 5 employees by salary.
   ```

7. Review the generated SQL.
8. If it passes validation and the read-only check, view the query results.

## SQL Safety and Validation

The application does not send every model response directly to the database.

### Syntax validation

`sqlglot` parses generated SQL using the selected dialect:

- `PostgreSQL` uses the `postgres` parser dialect.
- `MySQL` uses the `mysql` parser dialect.

Execution is stopped when:

- The generated SQL is empty.
- The SQL cannot be parsed.
- More than one statement is returned.
- The DBMS type is unsupported.

Syntax validation confirms that the statement is structurally valid for the selected dialect. It does not confirm that every table, column, function, or permission exists in the target database; those checks remain the responsibility of the database server.

### Read-only enforcement

The application also blocks queries that:

- Do not begin with `SELECT`.
- Contain prohibited command keywords such as `INSERT`, `UPDATE`, `DELETE`, `DROP`, `ALTER`, `TRUNCATE`, `CREATE`, `GRANT`, `REVOKE`, `REPLACE`, or `MERGE`.

This is a defense-in-depth measure, not a replacement for database permissions. For production use, configure the database credentials with read-only privileges and apply database-level statement timeouts and resource limits where appropriate.

## Database Support

### PostgreSQL

The application:

- Connects through `psycopg2`.
- Discovers databases from the PostgreSQL server catalog.
- Reads public-schema columns from `information_schema.columns`.
- Reads primary-key and foreign-key relationships from PostgreSQL information-schema views.

The default PostgreSQL port is `5432`.

### MySQL

The application:

- Connects through `mysql-connector-python`.
- Discovers databases with `SHOW DATABASES`.
- Excludes system schemas such as `information_schema`, `performance_schema`, `mysql`, and `sys`.
- Reads table and column metadata from `INFORMATION_SCHEMA.COLUMNS`.

The default MySQL port is `3306`.

## Error Handling

Common messages and their meanings:

| Message | Meaning |
|---|---|
| `No accessible databases found` | The application could not discover databases with the supplied credentials. |
| `LLM did not return valid JSON` | The database-selection model did not return the required JSON shape. |
| `SQL syntax validation failed` | `sqlglot` rejected the generated SQL for the selected dialect. |
| `exactly one SQL statement is required` | The model returned multiple SQL statements. |
| `BLOCKED: Only SELECT queries are allowed` | The generated SQL failed the read-only policy. |
| `Database Execution Error` | The database rejected the query or the connection failed. |

## Troubleshooting

### Ollama connection or model errors

Confirm that Ollama is running and that the selected model is installed:

```bash
ollama list
ollama run qwen2.5-coder:1.5b
```

If a model is not listed, pull it before launching Streamlit.

### No databases are displayed

Check:

- Database host and port.
- Username and password.
- Firewall and network access.
- Whether the user can list databases.
- Whether the PostgreSQL or MySQL server is running.

For PostgreSQL, the application initially connects to the `postgres` database to discover other databases. Ensure the account can connect to that database.

### Schema extraction fails

Ensure that the configured user can connect to the selected database and read metadata from `information_schema`. Also confirm that the database contains tables in the schemas inspected by the application.

### Generated SQL is syntactically valid but fails during execution

`sqlglot` validates SQL syntax, not database semantics. The query may still fail because:

- A table or column does not exist.
- The model inferred the wrong relationship.
- A function is unavailable in the selected database version.
- The user lacks permission to read a table.
- The generated SQL uses a valid but unsupported feature for the installed server version.

Review the displayed SQL and the database error before retrying with a more specific question.

## Development and Validation

### Metrics dashboard

Run the SQL evaluation dashboard separately from the main assistant:

```powershell
.\venv\Scripts\streamlit.exe run metrics.py
```

Run prompts normally in `app.py`; each completed prompt records only anonymized telemetry in `.metrics_history.json`, which is ignored by Git. No prompt, generated SQL, database name, result rows, or raw database error is stored. The dashboard displays:

- Total and successful query counts.
- Success, syntax-validity, and execution-success rates.
- Llama versus Qwen comparison bar charts.
- Latency charts and anonymized chat activity.

The chat activity table contains only the iteration number, model, outcome flags, latency, processing stage, and an error category.

Compile the Python modules:

```powershell
.\venv\Scripts\python.exe -m py_compile app.py llm_engine.py schema_extractor.py
```

Run a focused SQL validation check:

```powershell
.\venv\Scripts\python.exe -c "from llm_engine import validate_sql_syntax; print(validate_sql_syntax('SELECT 1', 'PostgreSQL'))"
```

Expected output for valid SQL is `None`.

Example invalid-query check:

```powershell
.\venv\Scripts\python.exe -c "from llm_engine import validate_sql_syntax; print(validate_sql_syntax('SELECT name FROM', 'PostgreSQL'))"
```

The application currently does not include a dedicated automated test suite. When extending the SQL pipeline, test both:

- Valid PostgreSQL and MySQL `SELECT` statements.
- Malformed statements.
- Multiple statements.
- Non-read-only statements.
- Database execution failures.

## Security Recommendations

For local development:

- Keep credentials out of source control.
- Use `.env` only for local secrets and verify it is ignored by Git.
- Use a read-only database account.
- Avoid using production credentials during development.

For production deployment, additionally consider:

- Centralized secrets management.
- Database-level read-only roles.
- Query timeouts and row limits.
- Audit logging.
- Authentication and authorization for the Streamlit application.
- Restricting database network access.
- Rate limiting and model-output monitoring.

## Limitations

- SQL generation quality depends on the selected Ollama model and the quality of extracted schema metadata.
- Only PostgreSQL and MySQL are supported by the connection layer.
- The interface currently expects credentials to be entered in the sidebar.
- SQL syntax validation does not guarantee semantic correctness.
- The current read-only keyword policy is intentionally conservative and should be complemented by database permissions.
- Conversation history is stored in the active Streamlit session and is not a persistent application database.

## License

No license file is currently included in this repository. Add an appropriate license before distributing the project.
