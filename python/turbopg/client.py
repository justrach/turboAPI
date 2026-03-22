"""
TurboPG Database client — Python wrapper around the Zig-native pg.zig layer.

Provides a clean Python API for the Zig connection pool, query execution,
and result serialization. Can be used standalone without TurboAPI.
"""



class Database:
    """Zig-native Postgres connection pool.

    Usage:
        db = Database("postgres://user:pass@localhost/mydb", pool_size=16)

        # Single row
        user = db.query_one("SELECT * FROM users WHERE id = $1", [42])

        # Multiple rows
        users = db.query("SELECT * FROM users WHERE age > $1 LIMIT $2", [18, 10])

        # Execute (no result)
        affected = db.execute("DELETE FROM users WHERE id = $1", [42])

        # With context manager
        with Database("postgres://...") as db:
            db.query("SELECT 1")
    """

    def __init__(self, conn_string: str, pool_size: int = 16):
        self.conn_string = conn_string
        self.pool_size = pool_size
        self._native = None
        self._connect()

    def _connect(self):
        """Initialize connection. Checks for Zig native raw query path first."""
        self._native = None
        self._native_raw = False
        self._native_exec_many = False
        self._fallback_engine = None

        # Try Zig native pool + raw query path
        try:
            from turboapi import turbonet

            if hasattr(turbonet, "_db_configure"):
                turbonet._db_configure(self.conn_string, self.pool_size)
                self._native = turbonet
                self._native_raw = hasattr(turbonet, "_db_query_raw")
                self._native_exec_many = hasattr(turbonet, "_db_exec_many_raw")
        except (ImportError, Exception):
            pass

        # Set up Python fallback for standalone query()/execute()
        pg_conn_str = self.conn_string.replace("postgres://", "postgresql://")
        try:
            import psycopg2  # noqa: F401

            self._fallback_engine = "psycopg2"
            self._fallback_conn_str = pg_conn_str
        except ImportError:
            try:
                import psycopg  # noqa: F401

                self._fallback_engine = "psycopg"
                self._fallback_conn_str = self.conn_string
            except ImportError:
                if not self._native:
                    raise ImportError(
                        "TurboPG requires turboapi (Zig) or psycopg2-binary. "
                        "Install: pip install psycopg2-binary"
                    )

    def query(self, sql: str, params: list | None = None) -> list[dict]:
        """Execute a query and return all rows as a list of dicts.

        Args:
            sql: SQL query with $1, $2, ... parameter placeholders
            params: List of parameter values

        Returns:
            List of dicts, one per row
        """
        if self._native:
            return self._query_native(sql, params or [])
        return self._query_fallback(sql, params or [])

    def query_one(self, sql: str, params: list | None = None) -> dict | None:
        """Execute a query and return the first row as a dict, or None.

        Args:
            sql: SQL query with $1, $2, ... parameter placeholders
            params: List of parameter values

        Returns:
            Dict for the first row, or None if no results
        """
        rows = self.query(sql, params)
        return rows[0] if rows else None

    def execute(self, sql: str, params: list | None = None) -> int:
        """Execute a statement (INSERT/UPDATE/DELETE) and return affected row count.

        Args:
            sql: SQL statement with $1, $2, ... parameter placeholders
            params: List of parameter values

        Returns:
            Number of affected rows
        """
        if self._native:
            return self._execute_native(sql, params or [])
        return self._execute_fallback(sql, params or [])

    def execute_many(self, sql: str, rows: list[list] | None = None) -> int:
        """Execute the same statement for many rows and return affected row count."""
        rows = rows or []
        if self._native and self._native_exec_many:
            return self._native._db_exec_many_raw(sql, rows)
        total = 0
        for row in rows:
            total += self.execute(sql, row)
        return total

    def _query_native(self, sql: str, params: list) -> list[dict]:
        """Query via Zig-native pg.zig directly (no JSON, returns Python dicts)."""
        if self._native_raw:
            return self._native._db_query_raw(sql, params)
        if self._fallback_engine:
            return self._query_fallback(sql, params)
        raise NotImplementedError(
            "Standalone TurboPG queries require psycopg2-binary. "
            "Install it: pip install psycopg2-binary\n"
            "For zero-overhead queries, use TurboAPI's db_query/db_get decorators instead."
        )
    def _execute_native(self, sql: str, params: list) -> int:
        if self._fallback_engine:
            return self._execute_fallback(sql, params)
        raise NotImplementedError(
            "Standalone TurboPG execute requires psycopg2-binary. "
            "Install it: pip install psycopg2-binary"
        )
    def _query_fallback(self, sql: str, params: list) -> list[dict]:
        """Query via Python DB driver (psycopg2/psycopg)."""
        # Convert $1, $2, ... to %s for psycopg2
        converted_sql = sql
        for i in range(len(params), 0, -1):
            converted_sql = converted_sql.replace(f"${i}", "%s")

        if self._fallback_engine == "psycopg2":
            import psycopg2

            conn = psycopg2.connect(self._fallback_conn_str)
            try:
                cur = conn.cursor()
                cur.execute(converted_sql, params)
                if cur.description:
                    columns = [desc[0] for desc in cur.description]
                    rows = cur.fetchall()
                    return [
                        {col: self._serialize_value(val) for col, val in zip(columns, row, strict=False)}
                        for row in rows
                    ]
                return []
            finally:
                conn.close()
        else:
            import psycopg

            conn = psycopg.connect(self._fallback_conn_str)
            try:
                cur = conn.cursor()
                cur.execute(converted_sql, params)
                if cur.description:
                    columns = [desc.name for desc in cur.description]
                    rows = cur.fetchall()
                    return [
                        {col: self._serialize_value(val) for col, val in zip(columns, row, strict=False)}
                        for row in rows
                    ]
                return []
            finally:
                conn.close()

    def _execute_fallback(self, sql: str, params: list) -> int:
        converted_sql = sql
        for i in range(len(params), 0, -1):
            converted_sql = converted_sql.replace(f"${i}", "%s")

        if self._fallback_engine == "psycopg2":
            import psycopg2

            conn = psycopg2.connect(self._fallback_conn_str)
            try:
                cur = conn.cursor()
                cur.execute(converted_sql, params)
                conn.commit()
                return cur.rowcount
            finally:
                conn.close()
        else:
            import psycopg

            conn = psycopg.connect(self._fallback_conn_str)
            try:
                cur = conn.cursor()
                cur.execute(converted_sql, params)
                conn.commit()
                return cur.rowcount
            finally:
                conn.close()

    @staticmethod
    def _serialize_value(val):
        """Convert DB values to JSON-safe types."""
        from datetime import date, datetime
        from decimal import Decimal

        if isinstance(val, Decimal):
            return float(val)
        if isinstance(val, (datetime, date)):
            return val.isoformat()
        if isinstance(val, memoryview):
            return bytes(val).decode("utf-8", errors="replace")
        return val

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def __repr__(self):
        return f"Database({self.conn_string!r}, pool_size={self.pool_size})"
