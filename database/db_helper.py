import sqlite3
import logging
from typing import List, Dict, Any, Optional
from config.settings import DB_PATH

logger = logging.getLogger(__name__)

class DBHelper:
    def __init__(self, db_path: str = str(DB_PATH)):
        self.db_path = db_path
        self.init_db()

    def get_connection(self) -> sqlite3.Connection:
        """Returns a connection to the SQLite database with row factory enabled."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        # Enable foreign key support
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    def init_db(self) -> None:
        """Initializes database schema if tables do not exist."""
        logger.info("Initializing database schema...")
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                # Create projects table
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS projects (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        name TEXT NOT NULL UNIQUE
                    )
                """)
                
                # Create headcount history table
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS headcount_history (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        project_id INTEGER NOT NULL,
                        record_month TEXT NOT NULL, -- Format: YYYY-MM
                        headcount INTEGER NOT NULL CHECK (headcount >= 0),
                        FOREIGN KEY (project_id) REFERENCES projects (id) ON DELETE CASCADE,
                        UNIQUE (project_id, record_month)
                    )
                """)
                
                # Create leavers table
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS leavers (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        employee_id TEXT NOT NULL UNIQUE,
                        employee_name TEXT NOT NULL,
                        project_id INTEGER NOT NULL,
                        department TEXT NOT NULL,
                        position TEXT NOT NULL,
                        date_of_joining TEXT NOT NULL, -- ISO YYYY-MM-DD
                        date_of_leaving TEXT NOT NULL, -- ISO YYYY-MM-DD
                        length_of_service_months REAL NOT NULL,
                        status TEXT,
                        original_reason TEXT,
                        ai_category TEXT,
                        record_month TEXT NOT NULL, -- Format: YYYY-MM
                        FOREIGN KEY (project_id) REFERENCES projects (id) ON DELETE RESTRICT
                    )
                """)
                
                conn.commit()
                logger.info("Database initialized successfully.")
        except sqlite3.Error as e:
            logger.error(f"Error initializing database: {e}", exc_info=True)
            raise

    def get_or_create_project(self, project_name: str) -> int:
        """Retrieves project ID by name, creating it if it doesn't exist."""
        project_name_clean = project_name.strip()
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT id FROM projects WHERE name = ?", (project_name_clean,))
                row = cursor.fetchone()
                if row:
                    return row["id"]
                
                cursor.execute("INSERT INTO projects (name) VALUES (?)", (project_name_clean,))
                conn.commit()
                return cursor.lastrowid
        except sqlite3.Error as e:
            logger.error(f"Database error getting/creating project '{project_name}': {e}", exc_info=True)
            raise

    def employee_id_exists(self, employee_id: str) -> bool:
        """Checks if employee_id already exists in the leavers database."""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT 1 FROM leavers WHERE employee_id = ?", (employee_id.strip(),))
                return cursor.fetchone() is not None
        except sqlite3.Error as e:
            logger.error(f"Database error checking employee ID '{employee_id}': {e}", exc_info=True)
            raise
            
    def get_projects(self) -> List[Dict[str, Any]]:
        """Retrieves all projects."""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM projects ORDER BY name")
                return [dict(row) for row in cursor.fetchall()]
        except sqlite3.Error as e:
            logger.error(f"Error fetching projects: {e}", exc_info=True)
            raise
            
    def insert_headcount(self, project_name: str, record_month: str, headcount: int) -> None:
        """Inserts or updates headcount for a project and month."""
        try:
            project_id = self.get_or_create_project(project_name)
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO headcount_history (project_id, record_month, headcount)
                    VALUES (?, ?, ?)
                    ON CONFLICT(project_id, record_month) DO UPDATE SET headcount = excluded.headcount
                """, (project_id, record_month, headcount))
                conn.commit()
        except sqlite3.Error as e:
            logger.error(f"Database error inserting headcount: {e}", exc_info=True)
            raise

    def insert_leaver(self, leaver_data: Dict[str, Any]) -> None:
        """Inserts a leaver record into the database."""
        try:
            project_id = self.get_or_create_project(leaver_data["project"])
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO leavers (
                        employee_id, employee_name, project_id, department, position,
                        date_of_joining, date_of_leaving, length_of_service_months,
                        status, original_reason, ai_category, record_month
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(employee_id) DO UPDATE SET
                        employee_name = excluded.employee_name,
                        project_id = excluded.project_id,
                        department = excluded.department,
                        position = excluded.position,
                        date_of_joining = excluded.date_of_joining,
                        date_of_leaving = excluded.date_of_leaving,
                        length_of_service_months = excluded.length_of_service_months,
                        status = excluded.status,
                        original_reason = excluded.original_reason,
                        ai_category = excluded.ai_category,
                        record_month = excluded.record_month
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
                conn.commit()
        except sqlite3.Error as e:
            logger.error(f"Database error inserting leaver: {e}", exc_info=True)
            raise

    def get_headcount_history(self, project_name: Optional[str] = None, start_month: Optional[str] = None, end_month: Optional[str] = None) -> List[Dict[str, Any]]:
        """Retrieves historical headcount records, optionally filtered by project and month range."""
        try:
            query = """
                SELECT p.name as project_name, h.record_month, h.headcount
                FROM headcount_history h
                JOIN projects p ON h.project_id = p.id
                WHERE 1=1
            """
            params = []
            if project_name:
                query += " AND p.name = ?"
                params.append(project_name.strip())
            if start_month:
                query += " AND h.record_month >= ?"
                params.append(start_month)
            if end_month:
                query += " AND h.record_month <= ?"
                params.append(end_month)
            
            query += " ORDER BY h.record_month ASC, p.name ASC"
            
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(query, params)
                return [dict(row) for row in cursor.fetchall()]
        except sqlite3.Error as e:
            logger.error(f"Database error getting headcount history: {e}", exc_info=True)
            raise

    def get_average_headcount(self, project_name: Optional[str] = None, start_month: Optional[str] = None, end_month: Optional[str] = None) -> float:
        """Calculates the average headcount (across months) for a project or all projects."""
        try:
            query = """
                SELECT AVG(h.headcount) as avg_hc
                FROM headcount_history h
                JOIN projects p ON h.project_id = p.id
                WHERE 1=1
            """
            params = []
            if project_name:
                query += " AND p.name = ?"
                params.append(project_name.strip())
            if start_month:
                query += " AND h.record_month >= ?"
                params.append(start_month)
            if end_month:
                query += " AND h.record_month <= ?"
                params.append(end_month)
                
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(query, params)
                row = cursor.fetchone()
                return float(row["avg_hc"]) if row and row["avg_hc"] is not None else 0.0
        except sqlite3.Error as e:
            logger.error(f"Database error getting average headcount: {e}", exc_info=True)
            raise

    def get_project_averages(self, start_month: Optional[str] = None, end_month: Optional[str] = None) -> List[Dict[str, Any]]:
        """Calculates historical average headcount for each project."""
        try:
            query = """
                SELECT p.name as project_name, AVG(h.headcount) as avg_hc
                FROM headcount_history h
                JOIN projects p ON h.project_id = p.id
                WHERE 1=1
            """
            params = []
            if start_month:
                query += " AND h.record_month >= ?"
                params.append(start_month)
            if end_month:
                query += " AND h.record_month <= ?"
                params.append(end_month)
                
            query += " GROUP BY p.id ORDER BY avg_hc DESC"
            
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(query, params)
                return [dict(row) for row in cursor.fetchall()]
        except sqlite3.Error as e:
            logger.error(f"Database error getting project headcount averages: {e}", exc_info=True)
            raise

    def get_leavers_summary(self, project_name: Optional[str] = None, start_month: Optional[str] = None, end_month: Optional[str] = None) -> List[Dict[str, Any]]:
        """Retrieves raw leavers records with details, optionally filtered by project name and month range."""
        try:
            query = """
                SELECT l.*, p.name as project_name
                FROM leavers l
                JOIN projects p ON l.project_id = p.id
                WHERE 1=1
            """
            params = []
            if project_name:
                query += " AND p.name = ?"
                params.append(project_name.strip())
            if start_month:
                query += " AND l.record_month >= ?"
                params.append(start_month)
            if end_month:
                query += " AND l.record_month <= ?"
                params.append(end_month)
                
            query += " ORDER BY l.record_month ASC, l.date_of_leaving ASC"
            
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(query, params)
                return [dict(row) for row in cursor.fetchall()]
        except sqlite3.Error as e:
            logger.error(f"Database error getting leavers summary: {e}", exc_info=True)
            raise

    def get_leavers_count_by_project_month(self, start_month: Optional[str] = None, end_month: Optional[str] = None) -> List[Dict[str, Any]]:
        """Returns the count of leavers grouped by project and record_month."""
        try:
            query = """
                SELECT p.name as project_name, l.record_month, COUNT(l.id) as leaver_count
                FROM leavers l
                JOIN projects p ON l.project_id = p.id
                WHERE 1=1
            """
            params = []
            if start_month:
                query += " AND l.record_month >= ?"
                params.append(start_month)
            if end_month:
                query += " AND l.record_month <= ?"
                params.append(end_month)
                
            query += " GROUP BY p.id, l.record_month ORDER BY l.record_month ASC"
            
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(query, params)
                return [dict(row) for row in cursor.fetchall()]
        except sqlite3.Error as e:
            logger.error(f"Database error getting leavers count by project and month: {e}", exc_info=True)
            raise

    def get_unclassified_leavers(self) -> List[Dict[str, Any]]:
        """Retrieves leavers records where AI classification is missing."""
        try:
            query = """
                SELECT l.*, p.name as project_name
                FROM leavers l
                JOIN projects p ON l.project_id = p.id
                WHERE l.ai_category IS NULL OR l.ai_category = '' OR l.ai_category = 'Other'
            """
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(query)
                return [dict(row) for row in cursor.fetchall()]
        except sqlite3.Error as e:
            logger.error(f"Database error getting unclassified leavers: {e}", exc_info=True)
            raise

    def update_leaver_ai_category(self, employee_id: str, ai_category: str) -> None:
        """Updates the AI category for a specific employee ID."""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    UPDATE leavers
                    SET ai_category = ?
                    WHERE employee_id = ?
                """, (ai_category.strip(), employee_id.strip()))
                conn.commit()
        except sqlite3.Error as e:
            logger.error(f"Database error updating AI category for employee {employee_id}: {e}", exc_info=True)
            raise
