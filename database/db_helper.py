import os
import logging
from contextlib import contextmanager
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)


def _detect_db_mode():
    """
    Returns ('postgres', url) when a Supabase URL is configured,
    otherwise ('sqlite', None) for local SQLite usage.
    Detection order: st.secrets → SUPABASE_URL env var → SQLite fallback.
    """
    try:
        import streamlit as st
        url = st.secrets.get("supabase_url", "")
        if url:
            logger.info("Supabase URL found in st.secrets — using PostgreSQL mode.")
            return "postgres", url
    except Exception:
        pass

    url = os.environ.get("SUPABASE_URL", "")
    if url:
        logger.info("Supabase URL found in environment — using PostgreSQL mode.")
        return "postgres", url

    logger.info("No Supabase URL configured — falling back to local SQLite mode.")
    return "sqlite", None


class DBHelper:
    def __init__(self, db_path: str = None):
        from config.settings import DB_PATH as _DB_PATH
        self._mode, self._pg_url = _detect_db_mode()
        self._sqlite_path = db_path or str(_DB_PATH)
        logger.info(f"DBHelper initialised in '{self._mode}' mode.")
        self.init_db()

    # ------------------------------------------------------------------ #
    #  Connection helpers
    # ------------------------------------------------------------------ #

    @contextmanager
    def get_connection(self):
        """
        Context manager yielding an open DB connection.
        Commits on clean exit, rolls back on exception, always closes.
        """
        if self._mode == "postgres":
            import psycopg2
            url = self._pg_url.strip().strip("'\"")
            
            # Mask password for safe logging/display
            masked_url = url
            try:
                if "@" in url:
                    parts = url.split("@")
                    credentials = parts[0].split(":")
                    if len(credentials) > 2:
                        masked_url = f"{credentials[0]}:{credentials[1]}:****@{parts[1]}"
            except Exception:
                pass

            try:
                conn = psycopg2.connect(url)
                yield conn
                conn.commit()
            except Exception as e:
                logger.error(f"Failed to connect to PostgreSQL database using {masked_url}: {e}")
                # Raise a cleaner error showing the target host and port to help user debug firewall blocks
                raise RuntimeError(
                    f"PostgreSQL connection failed to {masked_url.split('@')[-1] if '@' in masked_url else masked_url}. "
                    f"Error: {e}"
                ) from e
            finally:
                try:
                    conn.close()
                except Exception:
                    pass
        else:
            import sqlite3
            conn = sqlite3.connect(self._sqlite_path)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON;")
            try:
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()

    def _cursor(self, conn):
        """Returns a RealDictCursor for PostgreSQL or a standard cursor for SQLite."""
        if self._mode == "postgres":
            import psycopg2.extras
            return conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        return conn.cursor()

    def _p(self) -> str:
        """SQL placeholder: %s (PostgreSQL) or ? (SQLite)."""
        return "%s" if self._mode == "postgres" else "?"

    def _rows(self, rows) -> List[Dict[str, Any]]:
        """Convert cursor fetchall result to a list of plain dicts."""
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------ #
    #  Schema initialisation
    # ------------------------------------------------------------------ #

    def init_db(self) -> None:
        """Creates all tables if they do not already exist."""
        logger.info("Initialising database schema...")
        try:
            with self.get_connection() as conn:
                cur = self._cursor(conn)

                if self._mode == "postgres":
                    cur.execute("""
                        CREATE TABLE IF NOT EXISTS projects (
                            id   SERIAL PRIMARY KEY,
                            name TEXT   NOT NULL UNIQUE
                        )
                    """)
                    cur.execute("""
                        CREATE TABLE IF NOT EXISTS headcount_history (
                            id           SERIAL  PRIMARY KEY,
                            project_id   INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                            record_month TEXT    NOT NULL,
                            headcount    INTEGER NOT NULL CHECK (headcount >= 0),
                            UNIQUE (project_id, record_month)
                        )
                    """)
                    cur.execute("""
                        CREATE TABLE IF NOT EXISTS leavers (
                            id                       SERIAL  PRIMARY KEY,
                            employee_id              TEXT    NOT NULL UNIQUE,
                            employee_name            TEXT    NOT NULL,
                            project_id               INTEGER NOT NULL REFERENCES projects(id) ON DELETE RESTRICT,
                            department               TEXT    NOT NULL,
                            position                 TEXT    NOT NULL,
                            date_of_joining          TEXT    NOT NULL,
                            date_of_leaving          TEXT    NOT NULL,
                            length_of_service_months REAL    NOT NULL,
                            status                   TEXT,
                            original_reason          TEXT,
                            ai_category              TEXT,
                            record_month             TEXT    NOT NULL
                        )
                    """)
                else:
                    cur.execute("""
                        CREATE TABLE IF NOT EXISTS projects (
                            id   INTEGER PRIMARY KEY AUTOINCREMENT,
                            name TEXT    NOT NULL UNIQUE
                        )
                    """)
                    cur.execute("""
                        CREATE TABLE IF NOT EXISTS headcount_history (
                            id           INTEGER PRIMARY KEY AUTOINCREMENT,
                            project_id   INTEGER NOT NULL,
                            record_month TEXT    NOT NULL,
                            headcount    INTEGER NOT NULL CHECK (headcount >= 0),
                            FOREIGN KEY (project_id) REFERENCES projects (id) ON DELETE CASCADE,
                            UNIQUE (project_id, record_month)
                        )
                    """)
                    cur.execute("""
                        CREATE TABLE IF NOT EXISTS leavers (
                            id                       INTEGER PRIMARY KEY AUTOINCREMENT,
                            employee_id              TEXT    NOT NULL UNIQUE,
                            employee_name            TEXT    NOT NULL,
                            project_id               INTEGER NOT NULL,
                            department               TEXT    NOT NULL,
                            position                 TEXT    NOT NULL,
                            date_of_joining          TEXT    NOT NULL,
                            date_of_leaving          TEXT    NOT NULL,
                            length_of_service_months REAL    NOT NULL,
                            status                   TEXT,
                            original_reason          TEXT,
                            ai_category              TEXT,
                            record_month             TEXT    NOT NULL,
                            FOREIGN KEY (project_id) REFERENCES projects (id) ON DELETE RESTRICT
                        )
                    """)

            logger.info("Database schema initialised successfully.")
        except Exception as e:
            logger.error(f"Error initialising database: {e}", exc_info=True)
            raise

    # ------------------------------------------------------------------ #
    #  Projects
    # ------------------------------------------------------------------ #

    def get_or_create_project(self, project_name: str) -> int:
        """Returns the project ID for the given name, inserting it if necessary."""
        name = project_name.strip()
        p = self._p()
        try:
            with self.get_connection() as conn:
                cur = self._cursor(conn)
                if self._mode == "postgres":
                    cur.execute(
                        f"INSERT INTO projects (name) VALUES ({p}) ON CONFLICT (name) DO NOTHING",
                        (name,)
                    )
                    cur.execute(f"SELECT id FROM projects WHERE name = {p}", (name,))
                else:
                    cur.execute(f"INSERT OR IGNORE INTO projects (name) VALUES ({p})", (name,))
                    cur.execute(f"SELECT id FROM projects WHERE name = {p}", (name,))
                row = cur.fetchone()
                return dict(row)["id"]
        except Exception as e:
            logger.error(f"Database error getting/creating project '{project_name}': {e}", exc_info=True)
            raise

    def get_projects(self) -> List[Dict[str, Any]]:
        """Returns all projects ordered by name."""
        try:
            with self.get_connection() as conn:
                cur = self._cursor(conn)
                cur.execute("SELECT * FROM projects ORDER BY name")
                return self._rows(cur.fetchall())
        except Exception as e:
            logger.error(f"Error fetching projects: {e}", exc_info=True)
            raise

    # ------------------------------------------------------------------ #
    #  Headcount
    # ------------------------------------------------------------------ #

    def insert_headcount(self, project_name: str, record_month: str, headcount: int) -> None:
        """Inserts or updates the headcount for a project/month pair."""
        p = self._p()
        try:
            project_id = self.get_or_create_project(project_name)
            with self.get_connection() as conn:
                cur = self._cursor(conn)
                cur.execute(f"""
                    INSERT INTO headcount_history (project_id, record_month, headcount)
                    VALUES ({p}, {p}, {p})
                    ON CONFLICT (project_id, record_month)
                    DO UPDATE SET headcount = EXCLUDED.headcount
                """, (project_id, record_month, headcount))
        except Exception as e:
            logger.error(f"Database error inserting headcount: {e}", exc_info=True)
            raise

    def get_headcount_history(
        self,
        project_name: Optional[str] = None,
        start_month: Optional[str] = None,
        end_month: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Retrieves headcount records, optionally filtered by project and month range."""
        p = self._p()
        try:
            query = """
                SELECT p.name AS project_name, h.record_month, h.headcount
                FROM headcount_history h
                JOIN projects p ON h.project_id = p.id
                WHERE 1=1
            """
            params: list = []
            if project_name:
                query += f" AND p.name = {p}"
                params.append(project_name.strip())
            if start_month:
                query += f" AND h.record_month >= {p}"
                params.append(start_month)
            if end_month:
                query += f" AND h.record_month <= {p}"
                params.append(end_month)
            query += " ORDER BY h.record_month ASC, p.name ASC"

            with self.get_connection() as conn:
                cur = self._cursor(conn)
                cur.execute(query, params)
                return self._rows(cur.fetchall())
        except Exception as e:
            logger.error(f"Database error getting headcount history: {e}", exc_info=True)
            raise

    def get_average_headcount(
        self,
        project_name: Optional[str] = None,
        start_month: Optional[str] = None,
        end_month: Optional[str] = None
    ) -> float:
        """Returns the average headcount across months for a project or all projects."""
        p = self._p()
        try:
            query = """
                SELECT AVG(h.headcount) AS avg_hc
                FROM headcount_history h
                JOIN projects p ON h.project_id = p.id
                WHERE 1=1
            """
            params: list = []
            if project_name:
                query += f" AND p.name = {p}"
                params.append(project_name.strip())
            if start_month:
                query += f" AND h.record_month >= {p}"
                params.append(start_month)
            if end_month:
                query += f" AND h.record_month <= {p}"
                params.append(end_month)

            with self.get_connection() as conn:
                cur = self._cursor(conn)
                cur.execute(query, params)
                row = cur.fetchone()
                val = dict(row)["avg_hc"] if row else None
                return float(val) if val is not None else 0.0
        except Exception as e:
            logger.error(f"Database error getting average headcount: {e}", exc_info=True)
            raise

    def get_project_averages(
        self,
        start_month: Optional[str] = None,
        end_month: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Returns average headcount per project over the specified period."""
        p = self._p()
        try:
            query = """
                SELECT p.name AS project_name, AVG(h.headcount) AS avg_hc
                FROM headcount_history h
                JOIN projects p ON h.project_id = p.id
                WHERE 1=1
            """
            params: list = []
            if start_month:
                query += f" AND h.record_month >= {p}"
                params.append(start_month)
            if end_month:
                query += f" AND h.record_month <= {p}"
                params.append(end_month)
            query += " GROUP BY p.id, p.name ORDER BY avg_hc DESC"

            with self.get_connection() as conn:
                cur = self._cursor(conn)
                cur.execute(query, params)
                return self._rows(cur.fetchall())
        except Exception as e:
            logger.error(f"Database error getting project headcount averages: {e}", exc_info=True)
            raise

    # ------------------------------------------------------------------ #
    #  Leavers
    # ------------------------------------------------------------------ #

    def employee_id_exists(self, employee_id: str) -> bool:
        """Returns True if the employee ID already exists in the leavers table."""
        p = self._p()
        try:
            with self.get_connection() as conn:
                cur = self._cursor(conn)
                cur.execute(f"SELECT 1 FROM leavers WHERE employee_id = {p}", (employee_id.strip(),))
                return cur.fetchone() is not None
        except Exception as e:
            logger.error(f"Database error checking employee ID '{employee_id}': {e}", exc_info=True)
            raise

    def insert_leaver(self, leaver_data: Dict[str, Any]) -> None:
        """Inserts or updates a leaver record."""
        p = self._p()
        try:
            project_id = self.get_or_create_project(leaver_data["project"])
            with self.get_connection() as conn:
                cur = self._cursor(conn)
                cur.execute(f"""
                    INSERT INTO leavers (
                        employee_id, employee_name, project_id, department, position,
                        date_of_joining, date_of_leaving, length_of_service_months,
                        status, original_reason, ai_category, record_month
                    ) VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p})
                    ON CONFLICT (employee_id) DO UPDATE SET
                        employee_name            = EXCLUDED.employee_name,
                        project_id               = EXCLUDED.project_id,
                        department               = EXCLUDED.department,
                        position                 = EXCLUDED.position,
                        date_of_joining          = EXCLUDED.date_of_joining,
                        date_of_leaving          = EXCLUDED.date_of_leaving,
                        length_of_service_months = EXCLUDED.length_of_service_months,
                        status                   = EXCLUDED.status,
                        original_reason          = EXCLUDED.original_reason,
                        ai_category              = EXCLUDED.ai_category,
                        record_month             = EXCLUDED.record_month
                """, (
                    leaver_data["employee_id"],
                    leaver_data["employee_name"],
                    project_id,
                    leaver_data["department"],
                    leaver_data["position"],
                    leaver_data["date_of_joining"],
                    leaver_data["date_of_leaving"],
                    leaver_data["length_of_service_months"],
                    leaver_data.get("status"),
                    leaver_data.get("original_reason"),
                    leaver_data.get("ai_category"),
                    leaver_data["record_month"]
                ))
        except Exception as e:
            logger.error(f"Database error inserting leaver: {e}", exc_info=True)
            raise

    def get_leavers_summary(
        self,
        project_name: Optional[str] = None,
        start_month: Optional[str] = None,
        end_month: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Returns all leaver records with project name, optionally filtered."""
        p = self._p()
        try:
            query = """
                SELECT l.*, p.name AS project_name
                FROM leavers l
                JOIN projects p ON l.project_id = p.id
                WHERE 1=1
            """
            params: list = []
            if project_name:
                query += f" AND p.name = {p}"
                params.append(project_name.strip())
            if start_month:
                query += f" AND l.record_month >= {p}"
                params.append(start_month)
            if end_month:
                query += f" AND l.record_month <= {p}"
                params.append(end_month)
            query += " ORDER BY l.record_month ASC, l.date_of_leaving ASC"

            with self.get_connection() as conn:
                cur = self._cursor(conn)
                cur.execute(query, params)
                return self._rows(cur.fetchall())
        except Exception as e:
            logger.error(f"Database error getting leavers summary: {e}", exc_info=True)
            raise

    def get_leavers_count_by_project_month(
        self,
        start_month: Optional[str] = None,
        end_month: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Returns leaver counts grouped by project and month."""
        p = self._p()
        try:
            query = """
                SELECT p.name AS project_name, l.record_month, COUNT(l.id) AS leaver_count
                FROM leavers l
                JOIN projects p ON l.project_id = p.id
                WHERE 1=1
            """
            params: list = []
            if start_month:
                query += f" AND l.record_month >= {p}"
                params.append(start_month)
            if end_month:
                query += f" AND l.record_month <= {p}"
                params.append(end_month)
            query += " GROUP BY p.id, p.name, l.record_month ORDER BY l.record_month ASC"

            with self.get_connection() as conn:
                cur = self._cursor(conn)
                cur.execute(query, params)
                return self._rows(cur.fetchall())
        except Exception as e:
            logger.error(f"Database error getting leavers count by project/month: {e}", exc_info=True)
            raise

    def get_unclassified_leavers(self) -> List[Dict[str, Any]]:
        """Returns leavers where AI classification is missing or generic."""
        try:
            query = """
                SELECT l.*, p.name AS project_name
                FROM leavers l
                JOIN projects p ON l.project_id = p.id
                WHERE l.ai_category IS NULL OR l.ai_category = '' OR l.ai_category = 'Other'
            """
            with self.get_connection() as conn:
                cur = self._cursor(conn)
                cur.execute(query)
                return self._rows(cur.fetchall())
        except Exception as e:
            logger.error(f"Database error getting unclassified leavers: {e}", exc_info=True)
            raise

    def update_leaver_ai_category(self, employee_id: str, ai_category: str) -> None:
        """Updates the AI-classified reason for a specific leaver."""
        p = self._p()
        try:
            with self.get_connection() as conn:
                cur = self._cursor(conn)
                cur.execute(
                    f"UPDATE leavers SET ai_category = {p} WHERE employee_id = {p}",
                    (ai_category.strip(), employee_id.strip())
                )
        except Exception as e:
            logger.error(f"Database error updating AI category for employee {employee_id}: {e}", exc_info=True)
            raise


class CachedDBHelper(DBHelper):
    """
    Subclass of DBHelper that caches read queries using Streamlit's cache_data.
    Uses _self to bypass hashing of the helper class instance itself (which is not hashable).
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def get_projects(self) -> List[Dict[str, Any]]:
        import streamlit as st
        @st.cache_data(ttl=600)
        def _cached_get_projects(_self_db):
            return DBHelper.get_projects(_self_db)
        return _cached_get_projects(self)

    def get_headcount_history(
        self,
        project_name: Optional[str] = None,
        start_month: Optional[str] = None,
        end_month: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        import streamlit as st
        @st.cache_data(ttl=600)
        def _cached_get_headcount_history(_self_db, project_name, start_month, end_month):
            return DBHelper.get_headcount_history(_self_db, project_name, start_month, end_month)
        return _cached_get_headcount_history(self, project_name, start_month, end_month)

    def get_average_headcount(
        self,
        project_name: Optional[str] = None,
        start_month: Optional[str] = None,
        end_month: Optional[str] = None
    ) -> float:
        import streamlit as st
        @st.cache_data(ttl=600)
        def _cached_get_average_headcount(_self_db, project_name, start_month, end_month):
            return DBHelper.get_average_headcount(_self_db, project_name, start_month, end_month)
        return _cached_get_average_headcount(self, project_name, start_month, end_month)

    def get_project_averages(
        self,
        start_month: Optional[str] = None,
        end_month: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        import streamlit as st
        @st.cache_data(ttl=600)
        def _cached_get_project_averages(_self_db, start_month, end_month):
            return DBHelper.get_project_averages(_self_db, start_month, end_month)
        return _cached_get_project_averages(self, start_month, end_month)

    def get_leavers_summary(
        self,
        project_name: Optional[str] = None,
        start_month: Optional[str] = None,
        end_month: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        import streamlit as st
        @st.cache_data(ttl=600)
        def _cached_get_leavers_summary(_self_db, project_name, start_month, end_month):
            return DBHelper.get_leavers_summary(_self_db, project_name, start_month, end_month)
        return _cached_get_leavers_summary(self, project_name, start_month, end_month)

    def get_leavers_count_by_project_month(
        self,
        start_month: Optional[str] = None,
        end_month: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        import streamlit as st
        @st.cache_data(ttl=600)
        def _cached_get_leavers_count_by_project_month(_self_db, start_month, end_month):
            return DBHelper.get_leavers_count_by_project_month(_self_db, start_month, end_month)
        return _cached_get_leavers_count_by_project_month(self, start_month, end_month)



