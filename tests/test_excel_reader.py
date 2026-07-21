import os
import sys
from pathlib import Path
import pandas as pd
import logging
import logging.config
from datetime import datetime

# Adjust Python path to import from workspace root
sys.path.append(str(Path(__file__).resolve().parent.parent))

from config.settings import get_logging_config
from modules.excel_reader import ExcelReader
from database.db_helper import DBHelper

# Setup Logging
logging.config.dictConfig(get_logging_config())
logger = logging.getLogger("test_excel_reader")

def generate_mock_data():
    """Generates mock headcount and leavers dataframes."""
    # Valid headcount
    df_hc_valid = pd.DataFrame([
        {"Project": "Monal Murree", "Headcount": 350},
        {"Project": "Monal Imarat", "Headcount": 520},
        {"Project": "Monal Lahore", "Headcount": 280}
    ])

    # Invalid headcount (missing values, negative headcount)
    df_hc_invalid = pd.DataFrame([
        {"Project": "Monal Murree", "Headcount": 350},
        {"Project": "", "Headcount": 100},  # Empty Project
        {"Project": "Monal Lahore", "Headcount": -10},  # Negative Headcount
        {"Project": "Monal Rawalpindi", "Headcount": "Ten"}  # Non-integer Headcount
    ])

    # Valid leavers
    df_lv_valid = pd.DataFrame([
        {
            "Employee ID": "EMP001",
            "Employee Name": "Ali Ahmed",
            "Project": "Monal Murree",
            "Department": "F&B",
            "Position": "Waiter",
            "Date of Joining": "2024-01-15",
            "Date of Leaving": "2026-06-15",
            "Length of Service": 29.0,
            "Status": "Resigned",
            "Reason": "Got new job"
        },
        {
            "Employee ID": "EMP002",
            "Employee Name": "Sana Khan",
            "Project": "Monal Lahore",
            "Department": "Kitchen",
            "Position": "Chef",
            "Date of Joining": "2025-03-01",
            "Date of Leaving": "2026-06-01",
            "Length of Service": 15.0,
            "Status": "Resigned",
            "Reason": "Personal reasons"
        }
    ])

    # Invalid leavers
    df_lv_invalid = pd.DataFrame([
        {
            "Employee ID": "EMP001",  # Valid
            "Employee Name": "Ali Ahmed",
            "Project": "Monal Murree",
            "Department": "F&B",
            "Position": "Waiter",
            "Date of Joining": "2024-01-15",
            "Date of Leaving": "2026-06-15",
            "Length of Service": 29.0,
            "Status": "Resigned",
            "Reason": "Better package"
        },
        {
            "Employee ID": "EMP001",  # Duplicate Employee ID within file
            "Employee Name": "Duplicate Ali",
            "Project": "Monal Murree",
            "Department": "F&B",
            "Position": "Waiter",
            "Date of Joining": "2024-01-15",
            "Date of Leaving": "2026-06-15",
            "Length of Service": 29.0,
            "Status": "Resigned",
            "Reason": "Same ID"
        },
        {
            "Employee ID": "EMP003",
            "Employee Name": "Zahid Malik",
            "Project": "Monal Lahore",
            "Department": "",  # Missing Department
            "Position": "Manager",
            "Date of Joining": "2025-05-01",
            "Date of Leaving": "2024-05-01",  # Date of Leaving before Joining
            "Length of Service": -12.0,  # Negative service
            "Status": "Resigned",
            "Reason": ""
        }
    ])

    return df_hc_valid, df_hc_invalid, df_lv_valid, df_lv_invalid

def run_tests():
    # Setup test workspace
    test_dir = Path(__file__).resolve().parent / "temp_test_data"
    test_dir.mkdir(exist_ok=True)
    
    db_path = test_dir / "test_hr.db"
    if db_path.exists():
        db_path.unlink()
        
    db_helper = DBHelper(db_path=str(db_path))
    reader = ExcelReader(db_helper=db_helper)
    
    # Generate mock DataFrames
    df_hc_valid, df_hc_invalid, df_lv_valid, df_lv_invalid = generate_mock_data()
    
    # Write to Excel files
    hc_valid_path = test_dir / "headcount_2026_06.xlsx"
    hc_invalid_path = test_dir / "headcount_2026_06_invalid.xlsx"
    lv_valid_path = test_dir / "leavers_2026_06.xlsx"
    lv_invalid_path = test_dir / "leavers_2026_06_invalid.xlsx"
    
    df_hc_valid.to_excel(hc_valid_path, index=False)
    df_hc_invalid.to_excel(hc_invalid_path, index=False)
    df_lv_valid.to_excel(lv_valid_path, index=False)
    df_lv_invalid.to_excel(lv_invalid_path, index=False)
    
    logger.info("Mock files generated successfully.")
    
    # Run Validations
    logger.info("=== Testing Valid Headcount File ===")
    hc_valid_report = reader.parse_and_validate_headcount(hc_valid_path)
    assert hc_valid_report["is_valid"] is True, "Valid headcount failed verification"
    assert len(hc_valid_report["errors"]) == 0, "Valid headcount reported errors"
    assert hc_valid_report["valid_rows_count"] == 3, "Valid headcount row count mismatch"
    logger.info("Valid headcount validation passed!")
    
    logger.info("=== Testing Invalid Headcount File ===")
    hc_invalid_report = reader.parse_and_validate_headcount(hc_invalid_path)
    assert hc_invalid_report["is_valid"] is False, "Invalid headcount bypassed validation"
    assert len(hc_invalid_report["errors"]) == 3, f"Expected 3 errors, got {len(hc_invalid_report['errors'])}"
    logger.info("Invalid headcount validation caught all expected errors!")
    for err in hc_invalid_report["errors"]:
        logger.info(f"Row {err.get('row')}, Column '{err.get('column')}': {err.get('message')}")
        
    logger.info("=== Testing Valid Leavers File ===")
    lv_valid_report = reader.parse_and_validate_leavers(lv_valid_path)
    assert lv_valid_report["is_valid"] is True, "Valid leavers failed verification"
    assert len(lv_valid_report["errors"]) == 0, "Valid leavers reported errors"
    assert lv_valid_report["valid_rows_count"] == 2, "Valid leavers row count mismatch"
    logger.info("Valid leavers validation passed!")

    logger.info("=== Testing Invalid Leavers File ===")
    lv_invalid_report = reader.parse_and_validate_leavers(lv_invalid_path)
    assert lv_invalid_report["is_valid"] is False, "Invalid leavers bypassed validation"
    # Expected errors:
    # 1. Duplicate Employee ID (EMP001) in file
    # 2. Empty Department
    # 3. Date of Leaving before Joining
    # 4. Negative Length of Service
    # Note: Empty Reason yields a warning, not an error.
    logger.info(f"Errors found: {len(lv_invalid_report['errors'])}")
    for err in lv_invalid_report["errors"]:
        logger.info(f"Row {err.get('row')}, Column '{err.get('column')}': {err.get('message')}")
    
    assert len(lv_invalid_report["errors"]) >= 4, f"Expected at least 4 errors, got {len(lv_invalid_report['errors'])}"
    logger.info("Invalid leavers validation caught all expected errors!")
    
    # Clean up temp test data
    for file in [hc_valid_path, hc_invalid_path, lv_valid_path, lv_invalid_path]:
        file.unlink(missing_ok=True)
    db_path.unlink(missing_ok=True)
    import shutil
    shutil.rmtree(test_dir, ignore_errors=True)
    logger.info("Cleanup completed successfully. All tests passed!")

if __name__ == "__main__":
    try:
        run_tests()
        sys.exit(0)
    except AssertionError as e:
        logger.error(f"Test assertion failed: {e}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Unexpected error running tests: {e}", exc_info=True)
        sys.exit(2)
