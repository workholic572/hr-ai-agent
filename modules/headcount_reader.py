import logging
from pathlib import Path
from typing import Dict, Any, List, Optional

from database.db_helper import DBHelper
from modules.excel_reader import ExcelReader

logger = logging.getLogger(__name__)

class HeadcountReader:
    """
    HeadcountReader processes raw headcount Excel files, writes the validated
    records to the database, and provides query interfaces for headcount history.
    """
    def __init__(self, db_helper: Optional[DBHelper] = None, excel_reader: Optional[ExcelReader] = None):
        self.db_helper = db_helper or DBHelper()
        self.excel_reader = excel_reader or ExcelReader(db_helper=self.db_helper)

    def process_file(self, file_path: Path) -> Dict[str, Any]:
        """
        Parses and validates the headcount file, and inserts records into the database.
        Returns the data quality report from the validation engine.
        """
        logger.info(f"Processing headcount file: {file_path}")
        
        # 1. Parse and Validate
        report = self.excel_reader.parse_and_validate_headcount(file_path)
        
        # 2. If valid, insert into DB
        if report["is_valid"]:
            logger.info(f"Headcount file is valid. Inserting {len(report['data'])} records into database.")
            try:
                for record in report["data"]:
                    self.db_helper.insert_headcount(
                        project_name=record["project"],
                        record_month=record["record_month"],
                        headcount=record["headcount"]
                    )
                logger.info("Successfully imported headcount data into database.")
            except Exception as e:
                logger.error(f"Error importing headcount records to DB: {e}", exc_info=True)
                report["is_valid"] = False
                report["errors"].append({
                    "row": None,
                    "column": "Database",
                    "message": f"Failed to persist headcount records: {e}"
                })
        else:
            logger.warning(f"Headcount file validation failed with {len(report['errors'])} errors.")
            
        return report

    def get_history(self, project_name: Optional[str] = None, start_month: Optional[str] = None, end_month: Optional[str] = None) -> List[Dict[str, Any]]:
        """Retrieves history of headcount records, optionally filtered."""
        return self.db_helper.get_headcount_history(project_name, start_month, end_month)

    def get_average_headcount(self, project_name: Optional[str] = None, start_month: Optional[str] = None, end_month: Optional[str] = None) -> float:
        """Returns average headcount over the specified period/project."""
        return self.db_helper.get_average_headcount(project_name, start_month, end_month)

    def get_project_averages(self, start_month: Optional[str] = None, end_month: Optional[str] = None) -> List[Dict[str, Any]]:
        """Returns average headcount for each project over the specified period."""
        return self.db_helper.get_project_averages(start_month, end_month)
