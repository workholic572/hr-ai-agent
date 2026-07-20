import os
import json
from pathlib import Path

# Base Paths
BASE_DIR = Path(__file__).resolve().parent.parent

# Subdirectories
DATA_DIR = BASE_DIR / "data"
HEADCOUNT_DIR = DATA_DIR / "headcount"
LEAVERS_DIR = DATA_DIR / "leavers"
PROCESSED_DIR = DATA_DIR / "processed"
LOGS_DIR = BASE_DIR / "logs"
REPORTS_DIR = BASE_DIR / "reports"
PDF_REPORTS_DIR = REPORTS_DIR / "pdf"
EXCEL_REPORTS_DIR = REPORTS_DIR / "excel"

# Ensure directories exist
for path in [DATA_DIR, HEADCOUNT_DIR, LEAVERS_DIR, PROCESSED_DIR, LOGS_DIR, REPORTS_DIR, PDF_REPORTS_DIR, EXCEL_REPORTS_DIR]:
    path.mkdir(parents=True, exist_ok=True)

# Database Configurations
DB_PATH = PROCESSED_DIR / "hr_analytics.db"

# Logging Configuration
LOG_FILE = LOGS_DIR / "hr_agent.log"
LOG_LEVEL = "INFO"

# File Schema Definitions
EXPECTED_HEADCOUNT_COLUMNS = [
    "Project",
    "Headcount"
]

EXPECTED_LEAVERS_COLUMNS = [
    "Employee ID",
    "Employee Name",
    "Project",
    "Department",
    "Position",
    "Date of Joining",
    "Date of Leaving",
    "Length of Service",
    "Status",
    "Reason"
]

# AI Classification Reason Categories
STANDARD_CATEGORIES = [
    "Better Career Opportunity",
    "Compensation & Benefits",
    "Personal Reasons",
    "Family Reasons",
    "Relocation",
    "Health Reasons",
    "Education",
    "Supervisor / Management Issue",
    "Working Environment",
    "Workload",
    "Attendance / Discipline",
    "Termination",
    "Contract Completion",
    "Left Without Notice",
    "Other"
]

def load_standards_registry():
    registry_path = BASE_DIR / "config" / "standards_registry.json"
    if registry_path.exists():
        try:
            with open(registry_path, "r") as f:
                return json.load(f)
        except Exception as e:
            print(f"Error loading standards registry: {e}")
    return {"departments": [], "positions": [], "projects": []}

def save_standards_registry(registry_data):
    registry_path = BASE_DIR / "config" / "standards_registry.json"
    try:
        with open(registry_path, "w") as f:
            json.dump(registry_data, f, indent=2)
    except Exception as e:
        print(f"Error saving standards registry: {e}")

STANDARDS_REGISTRY = load_standards_registry()

# Logging configuration setup utility
def get_logging_config():
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "standard": {
                "format": "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                "datefmt": "%Y-%m-%d %H:%M:%S"
            },
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "formatter": "standard",
                "level": "DEBUG",
            },
            "file": {
                "class": "logging.FileHandler",
                "filename": str(LOG_FILE),
                "formatter": "standard",
                "level": "INFO",
                "encoding": "utf-8",
            },
        },
        "root": {
            "handlers": ["console", "file"],
            "level": "INFO",
        },
    }
