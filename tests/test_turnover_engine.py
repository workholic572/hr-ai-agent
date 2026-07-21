import os
import sys
from pathlib import Path
import pandas as pd
import logging
import logging.config

# Adjust Python path to import from workspace root
sys.path.append(str(Path(__file__).resolve().parent.parent))

from config.settings import get_logging_config
from database.db_helper import DBHelper
from modules.turnover_engine import TurnoverEngine

# Setup Logging
logging.config.dictConfig(get_logging_config())
logger = logging.getLogger("test_turnover_engine")

def run_tests():
    # Setup test workspace
    test_dir = Path(__file__).resolve().parent / "temp_test_data"
    test_dir.mkdir(exist_ok=True)
    
    db_path = test_dir / "test_hr.db"
    if db_path.exists():
        db_path.unlink()
        
    db_helper = DBHelper(db_path=str(db_path))
    engine = TurnoverEngine(db_helper=db_helper)
    
    # Seed data
    # Months: 2026-05 and 2026-06
    # Projects: Murree, Lahore
    
    # Headcounts:
    # 2026-05: Murree=100, Lahore=200. Total = 300
    # 2026-06: Murree=110, Lahore=190. Total = 300
    # Mean Headcount over 2 months: 300
    
    db_helper.insert_headcount("Monal Murree", "2026-05", 100)
    db_helper.insert_headcount("Monal Lahore", "2026-05", 200)
    db_helper.insert_headcount("Monal Murree", "2026-06", 110)
    db_helper.insert_headcount("Monal Lahore", "2026-06", 190)
    
    # Leavers:
    # 2026-05: Murree has 1 leaver, Lahore has 2 leavers. Total = 3.
    # 2026-06: Murree has 2 leavers, Lahore has 1 leaver. Total = 3.
    # Total Leavers in 2 months = 6.
    
    leavers_data = [
        # May Leavers
        {
            "employee_id": "EMP1", "employee_name": "E1", "project": "Monal Murree",
            "department": "F&B", "position": "Waiter", "date_of_joining": "2025-01-01",
            "date_of_leaving": "2026-05-10", "length_of_service_months": 16.3,
            "original_reason": "Career growth", "record_month": "2026-05"
        },
        {
            "employee_id": "EMP2", "employee_name": "E2", "project": "Monal Lahore",
            "department": "Kitchen", "position": "Chef", "date_of_joining": "2024-06-01",
            "date_of_leaving": "2026-05-15", "length_of_service_months": 23.5,
            "original_reason": "Better package", "record_month": "2026-05"
        },
        {
            "employee_id": "EMP3", "employee_name": "E3", "project": "Monal Lahore",
            "department": "HR", "position": "Officer", "date_of_joining": "2025-03-01",
            "date_of_leaving": "2026-05-20", "length_of_service_months": 14.6,
            "original_reason": "Health reasons", "record_month": "2026-05"
        },
        # June Leavers
        {
            "employee_id": "EMP4", "employee_name": "E4", "project": "Monal Murree",
            "department": "Kitchen", "position": "Helper", "date_of_joining": "2025-09-01",
            "date_of_leaving": "2026-06-05", "length_of_service_months": 9.1,
            "original_reason": "Moving abroad", "record_month": "2026-06"
        },
        {
            "employee_id": "EMP5", "employee_name": "E5", "project": "Monal Murree",
            "department": "F&B", "position": "Steward", "date_of_joining": "2026-01-01",
            "date_of_leaving": "2026-06-12", "length_of_service_months": 5.4,
            "original_reason": "Better opportunities", "record_month": "2026-06"
        },
        {
            "employee_id": "EMP6", "employee_name": "E6", "project": "Monal Lahore",
            "department": "F&B", "position": "Waiter", "date_of_joining": "2025-11-01",
            "date_of_leaving": "2026-06-25", "length_of_service_months": 7.8,
            "original_reason": "Personal reasons", "record_month": "2026-06"
        }
    ]
    
    for l in leavers_data:
        db_helper.insert_leaver(l)
        
    # Verify overall turnover rate
    # May: 3 leavers / 300 headcount = 1.0% (100%) -> wait, 3 / 300 * 100 = 1.0%
    # June: 3 leavers / 300 headcount = 1.0%
    # Overall period May-June: 6 leavers / 300 average headcount * 100 = 2.0%
    
    rate_overall = engine.calculate_overall_turnover("2026-05", "2026-06")
    assert rate_overall == 2.0, f"Expected overall period turnover 2.0%, got {rate_overall}%"
    logger.info("Overall period turnover verified successfully!")
    
    rate_may = engine.calculate_overall_turnover("2026-05", "2026-05")
    assert rate_may == 1.0, f"Expected May turnover 1.0%, got {rate_may}%"
    logger.info("May overall turnover rate verified successfully!")
    
    # Project-specific checks:
    # Murree headcount: May=100 (adj=100), June=110 (adj=105). Mean adj = 102.5. Leavers = 3. Turnover = 3 / 102.5 * 100 = 2.93%
    # Lahore headcount: May=200 (adj=200), June=190 (adj=195). Mean adj = 197.5. Leavers = 3. Turnover = 3 / 197.5 * 100 = 1.52%
    rate_murree = engine.calculate_project_turnover("Monal Murree", "2026-05", "2026-06")
    assert abs(rate_murree - 2.93) < 0.01, f"Expected Murree turnover ~2.93%, got {rate_murree}%"
    logger.info("Monal Murree turnover rate verified successfully!")
    
    rate_lahore = engine.calculate_project_turnover("Monal Lahore", "2026-05", "2026-06")
    assert abs(rate_lahore - 1.52) < 0.01, f"Expected Lahore turnover ~1.52%, got {rate_lahore}%"
    logger.info("Monal Lahore turnover rate verified successfully!")
    
    # Comparison check (June vs May)
    comp = engine.get_monthly_comparison("2026-06", "2026-05")
    # Overall June: 3/300 = 1.0%. May: 3/300 = 1.0%. Difference = 0.0
    assert comp["current_overall"] == 1.0
    assert comp["compare_overall"] == 1.0
    assert comp["difference"] == 0.0
    
    # Murree June: 2/105 = 1.90%. May: 1/100 = 1.0%. Diff = +0.90
    # Lahore June: 1/195 = 0.51%. May: 2/200 = 1.0%. Diff = -0.49
    assert abs(comp["projects"]["Monal Murree"]["difference"] - 0.90) < 0.01
    assert abs(comp["projects"]["Monal Lahore"]["difference"] - (-0.49)) < 0.01
    logger.info("Monthly comparisons and differences verified successfully!")
 
    # Rolling 12 Month check
    rolling_results = engine.calculate_rolling_12_month_turnover("2026-06")
    assert rolling_results["leavers_count"] == 6
    assert abs(rolling_results["avg_headcount"] - 300.0) < 0.01
    assert rolling_results["turnover_rate"] == 2.0
    assert rolling_results["projects"]["Monal Murree"]["leavers_count"] == 3
    logger.info("Rolling 12 Month turnover calculation verified successfully!")

    # Clean up temp test data
    db_path.unlink(missing_ok=True)
    import shutil
    shutil.rmtree(test_dir, ignore_errors=True)
    logger.info("Cleanup completed successfully. All Turnover Engine tests passed!")

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
