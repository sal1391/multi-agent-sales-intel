"""
Local (demo) data session — DuckDB-backed stand-in for a Snowpark Session.

DEPLOY_MODE=demo never opens a real Snowflake connection. Instead this module
loads the committed demo CSV into an in-memory DuckDB database, provisioned
under the same fully-qualified "<database>"."<schema>"."<table>" path that
the rest of the app's SQL already assumes (built from config.SNOWFLAKE_CONNECTION
and config.SNOWFLAKE_TABLE), so snowflake_client.py's query functions work
unmodified against either backend.
"""
import os

import duckdb

from config import SNOWFLAKE_CONNECTION, SNOWFLAKE_TABLE

DEMO_CSV = os.path.join(os.path.dirname(os.path.abspath(__file__)), "demo_data", "sales_actuals.csv")


class _LocalResult:
    """Thin wrapper giving a DuckDB query result the Snowpark Session.sql(...) API surface."""

    def __init__(self, df):
        self._df = df

    def to_pandas(self):
        return self._df

    def collect(self):
        # Parity with Snowpark's Session.sql(...).collect(); nothing in this
        # codebase currently calls it, but callers may expect row tuples.
        return list(self._df.itertuples(index=False, name=None))


class LocalSession:
    """DuckDB-backed session that mimics the subset of Snowpark's Session API used here."""

    def __init__(self, csv_path: str = DEMO_CSV):
        if not os.path.isfile(csv_path):
            raise RuntimeError(f"Demo CSV not found at {csv_path!r}. Cannot start local session.")

        self._con = duckdb.connect(":memory:")

        db = SNOWFLAKE_CONNECTION.get("database", "SANDBOX")
        sch = SNOWFLAKE_CONNECTION.get("schema", "ANALYTICS")
        table = SNOWFLAKE_TABLE

        self._con.execute(f'ATTACH \':memory:\' AS "{db}"')
        self._con.execute(f'CREATE SCHEMA "{db}"."{sch}"')
        self._con.execute(
            f"""
            CREATE TABLE "{db}"."{sch}"."{table}" AS
            SELECT * REPLACE (CAST(DELIVERY_DATE AS DATE) AS DELIVERY_DATE)
            FROM read_csv(?, header=true)
            """,
            [csv_path],
        )

    def sql(self, query: str) -> _LocalResult:
        # DuckDB connections aren't thread-safe; agents/orchestrator.py runs
        # queries concurrently via ThreadPoolExecutor, so use a fresh cursor
        # per call.
        cur = self._con.cursor()
        return _LocalResult(cur.execute(query).df())


_SESSION = None


def get_local_session() -> LocalSession:
    """Module-level singleton so the demo dataset is loaded into DuckDB only once
    per process, and survives Streamlit reruns (which re-execute the script but
    not the process)."""
    global _SESSION
    if _SESSION is None:
        _SESSION = LocalSession()
    return _SESSION
