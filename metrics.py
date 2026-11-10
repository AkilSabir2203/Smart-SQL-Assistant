"""Evaluation metrics for generated SQL queries."""

from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

import sqlglot
from sqlglot.errors import ParseError

HISTORY_FILE = Path(__file__).with_name(".metrics_history.json")


class SQLMetricsEvaluator:
    """Evaluate generated SQL against a gold-standard query."""

    def evaluate(
        self,
        generated_sql: str,
        ground_truth_sql: str,
        start_time: float,
        end_time: float,
        extractor: Any,
    ) -> dict:
        """Return SQL quality and performance metrics.

        ``extractor.execute_query`` may return rows directly or a
        ``(columns, rows)`` pair, matching the database helpers used by the
        application. Exceptions from either query are returned in ``error``
        instead of being raised so evaluation results remain structured.
        """
        result = {
            "exact_match": int(
                self._normalize_sql(generated_sql)
                == self._normalize_sql(ground_truth_sql)
            ),
            "syntax_valid": False,
            "execution_accuracy": 0,
            "latency_seconds": float(end_time - start_time),
            "error": None,
        }

        try:
            generated_rows = self._execute(extractor, generated_sql)
            result["syntax_valid"] = True
        except Exception as error:
            result["error"] = str(error)
            return result

        try:
            ground_truth_rows = self._execute(extractor, ground_truth_sql)
            result["execution_accuracy"] = int(
                self._rows_match(generated_rows, ground_truth_rows)
            )
        except Exception as error:
            result["error"] = str(error)

        return result

    @staticmethod
    def _normalize_sql(sql: str) -> str:
        """Normalize SQL into a canonical representation for exact matching."""
        if not isinstance(sql, str) or not sql.strip():
            return ""
        try:
            return sqlglot.parse_one(sql).sql(dialect="")
        except ParseError:
            return " ".join(sql.strip().rstrip(";").split()).lower()

    @classmethod
    def _execute(cls, extractor: Any, sql: str) -> Any:
        """Validate and execute one query through the supplied extractor."""
        if not isinstance(sql, str) or not sql.strip():
            raise ValueError("SQL query is empty.")
        sqlglot.parse_one(sql)
        execute_query = getattr(extractor, "execute_query", None)
        if not callable(execute_query):
            raise AttributeError("Extractor must provide an execute_query method.")
        return execute_query(sql)

    @classmethod
    def _rows_match(cls, left: Any, right: Any) -> bool:
        """Compare result datasets as unordered multisets of unordered rows."""
        return Counter(cls._row_signature(row) for row in cls._rows(left)) == Counter(
            cls._row_signature(row) for row in cls._rows(right)
        )

    @classmethod
    def _rows(cls, result: Any) -> list[Any]:
        """Extract rows from common extractor result formats."""
        if result is None:
            return []
        if isinstance(result, dict):
            for key in ("rows", "data", "results"):
                if key in result:
                    return cls._rows(result[key])
            return [result]
        if hasattr(result, "to_dict"):
            return cls._rows(result.to_dict(orient="records"))
        if isinstance(result, tuple) and len(result) == 2:
            columns, rows = result
            if isinstance(columns, (list, tuple)) and isinstance(rows, (list, tuple)):
                return list(rows)
        if isinstance(result, (list, tuple)):
            return list(result)
        return [result]

    @classmethod
    def _row_signature(cls, row: Any) -> tuple:
        """Create a hashable signature independent of aliases and column order."""
        if isinstance(row, dict):
            values = row.values()
        elif isinstance(row, (list, tuple)):
            values = row
        else:
            values = (row,)
        return tuple(sorted(cls._value_signature(value) for value in values))

    @classmethod
    def _value_signature(cls, value: Any) -> tuple:
        """Represent values safely even when database values are unorderable."""
        if isinstance(value, dict):
            return ("dict", tuple(sorted(
                (str(key), cls._value_signature(item))
                for key, item in value.items()
            )))
        if isinstance(value, (list, tuple)):
            return ("sequence", tuple(cls._value_signature(item) for item in value))
        return (type(value).__name__, repr(value))


class DatabaseExtractor:
    """Adapter that exposes the project's database connection as execute_query."""

    def __init__(
        self,
        dbms_type: str,
        host: str,
        port: str,
        user: str,
        password: str,
        database: str,
    ) -> None:
        self.dbms_type = dbms_type
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.database = database

    def execute_query(self, sql: str) -> tuple[list[str], list[Any]]:
        from llm_engine import create_connection

        connection = create_connection(
            self.dbms_type,
            self.host,
            self.port,
            self.user,
            self.password,
            self.database,
        )
        cursor = connection.cursor()
        try:
            cursor.execute(sql)
            columns = [description[0] for description in cursor.description]
            return columns, cursor.fetchall()
        finally:
            cursor.close()
            connection.close()


def load_history(history_file: Path = HISTORY_FILE) -> list[dict[str, Any]]:
    """Load prior evaluation iterations, returning an empty history if absent."""
    if not history_file.exists():
        return []
    try:
        with history_file.open("r", encoding="utf-8") as file:
            history = json.load(file)
        if not isinstance(history, list):
            raise ValueError("Metrics history must contain a JSON list.")
        return history
    except (OSError, json.JSONDecodeError, ValueError) as error:
        raise RuntimeError(f"Unable to read metrics history: {error}") from error


def save_history(history: list[dict[str, Any]], history_file: Path = HISTORY_FILE) -> None:
    """Persist evaluation iterations as readable JSON."""
    temporary_file = history_file.with_suffix(".tmp")
    try:
        with temporary_file.open("w", encoding="utf-8") as file:
            json.dump(history, file, indent=2)
            file.write("\n")
        temporary_file.replace(history_file)
    except OSError as error:
        if temporary_file.exists():
            temporary_file.unlink()
        raise RuntimeError(f"Unable to save metrics history: {error}") from error


def record_model_outcome(
    model: str,
    success: bool,
    latency_seconds: float,
    syntax_valid: bool,
    execution_success: bool,
    stage: str,
    error_category: str | None = None,
    history_file: Path = HISTORY_FILE,
) -> None:
    """Append non-sensitive aggregate telemetry for one model-generated query.

    This intentionally stores no prompt, SQL, database name, result rows, or raw
    exception text. The record is sufficient to compare model performance.
    """
    history = load_history(history_file)
    history.append({
        "iteration": len(history) + 1,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "model": model,
        "success": bool(success),
        "syntax_valid": bool(syntax_valid),
        "execution_success": bool(execution_success),
        "latency_seconds": round(max(0.0, latency_seconds), 6),
        "stage": stage,
        "error_category": error_category,
    })
    save_history(history, history_file)


def _aggregate_model_history(history: list[dict[str, Any]]) -> Any:
    import pandas as pd

    if not history:
        return pd.DataFrame(
            columns=[
                "model", "queries", "successful_queries", "success_rate",
                "syntax_valid_rate", "execution_success_rate", "avg_latency_seconds",
            ]
        )
    frame = pd.DataFrame(history)
    if "model" not in frame:
        frame["model"] = "Unknown"
    for column in ("success", "syntax_valid", "execution_success"):
        if column not in frame:
            frame[column] = False
        frame[column] = frame[column].fillna(False).astype(bool)
    if "latency_seconds" not in frame:
        frame["latency_seconds"] = 0.0
    grouped = frame.groupby("model", dropna=False)
    summary = grouped.agg(
        queries=("success", "size"),
        successful_queries=("success", "sum"),
        syntax_valid_rate=("syntax_valid", "mean"),
        execution_success_rate=("execution_success", "mean"),
        avg_latency_seconds=("latency_seconds", "mean"),
    ).reset_index()
    summary["success_rate"] = summary["successful_queries"] / summary["queries"]
    return summary[
        [
            "model", "queries", "successful_queries", "success_rate",
            "syntax_valid_rate", "execution_success_rate", "avg_latency_seconds",
        ]
    ]


def _run_dashboard() -> None:
    import pandas as pd
    import streamlit as st

    st.set_page_config(page_title="SQL Metrics Dashboard", page_icon="📊")
    st.title("📊 SQL Metrics Dashboard")
    st.caption("Track anonymized query outcomes from the main Smart SQL Assistant.")

    try:
        history = load_history()
    except RuntimeError as error:
        st.error(str(error))
        history = []

    if not history:
        st.info("No query outcomes recorded yet. Run prompts in app.py first.")
        return

    summary = _aggregate_model_history(history)
    totals = {
        "queries": int(summary["queries"].sum()),
        "successful": int(summary["successful_queries"].sum()),
    }
    columns = st.columns(4)
    columns[0].metric("Total queries", totals["queries"])
    columns[1].metric("Successful queries", totals["successful"])
    columns[2].metric(
        "Overall success rate",
        f"{totals['successful'] / totals['queries']:.1%}",
    )
    columns[3].metric(
        "Average latency",
        f"{pd.DataFrame(history)['latency_seconds'].mean():.3f}s",
    )

    st.subheader("Llama vs Qwen comparison")
    comparison = (
        summary.set_index("model")
        .reindex(["llama3.2", "qwen2.5-coder:1.5b"], fill_value=0)
        .reset_index()
    )
    comparison["success_rate"] *= 100
    comparison["syntax_valid_rate"] *= 100
    comparison["execution_success_rate"] *= 100
    st.bar_chart(
        comparison.set_index("model")[["successful_queries", "queries"]],
        y_label="Number of queries",
    )
    st.bar_chart(
        comparison.set_index("model")[
            ["success_rate", "syntax_valid_rate", "execution_success_rate"]
        ],
        y_label="Percentage",
    )
    st.dataframe(
        comparison.style.format({
            "success_rate": "{:.1f}%",
            "syntax_valid_rate": "{:.1f}%",
            "execution_success_rate": "{:.1f}%",
            "avg_latency_seconds": "{:.3f}s",
        }),
        use_container_width=True,
        hide_index=True,
    )

    timeline = pd.DataFrame(history).sort_values("iteration").set_index("iteration")
    st.subheader("Performance across chat iterations")
    st.line_chart(
        timeline[["success", "syntax_valid", "execution_success"]].astype(float),
        y_label="Outcome",
    )
    st.line_chart(timeline["latency_seconds"], y_label="Seconds")

    st.subheader("Chat activity")
    st.caption("Only anonymized outcomes are shown; prompts and SQL are never persisted.")
    display_columns = [
        "iteration", "timestamp", "model", "success", "syntax_valid",
        "execution_success", "latency_seconds", "stage", "error_category",
    ]
    activity = pd.DataFrame(history)
    for column in display_columns:
        if column not in activity:
            activity[column] = None
    st.dataframe(
        activity[display_columns].sort_values("iteration", ascending=False),
        use_container_width=True,
        hide_index=True,
    )


if __name__ == "__main__":
    _run_dashboard()
