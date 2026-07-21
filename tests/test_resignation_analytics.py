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
from modules.resignation_analytics import ResignationAnalytics

# Setup Logging
logging.config.dictConfig(get_logging_config())
logger = logging.getLogger("test_resignation_analytics")

def run_tests():
    # Setup test workspace
    test_dir = Path(__file__).resolve().parent / "temp_test_data"
    test_dir.mkdir(exist_ok=True)
    
    db_path = test_dir / "test_hr.db"
    if db_path.exists():
        db_path.unlink()
        
    db_helper = DBHelper(db_path=str(db_path))
    analyzer = ResignationAnalytics(db_helper=db_helper)
    
    # Seed data
    # 4 Leavers with various service lengths, departments, positions
    leavers_data = [
        {
            "employee_id": "EMP1", "employee_name": "John Doe", "project": "Monal Murree",
            "department": "F&B", "position": "Waiter", "date_of_joining": "2026-04-01",
            "date_of_leaving": "2026-06-15", "length_of_service_months": 2.5,  # < 3 Months
            "original_reason": "Better package", "record_month": "2026-06"
        },
        {
            "employee_id": "EMP2", "employee_name": "Jane Smith", "project": "Monal Murree",
            "department": "Kitchen", "position": "Chef", "date_of_joining": "2026-01-01",
            "date_of_leaving": "2026-06-15", "length_of_service_months": 5.5,  # 3 - 6 Months
            "original_reason": "Moving abroad", "record_month": "2026-06"
        },
        {
            "employee_id": "EMP3", "employee_name": "Bob Johnson", "project": "Monal Lahore",
            "department": "F&B", "position": "Waiter", "date_of_joining": "2025-09-01",
            "date_of_leaving": "2026-06-15", "length_of_service_months": 9.5,  # 6 - 12 Months
            "original_reason": "Supervisor behavior", "record_month": "2026-06"
        },
        {
            "employee_id": "EMP4", "employee_name": "Alice Williams", "project": "Monal Imarat",
            "department": "HR", "position": "Manager", "date_of_joining": "2024-01-01",
            "date_of_leaving": "2026-06-15", "length_of_service_months": 29.5, # > 2 Years
            "original_reason": "Health reasons", "record_month": "2026-06"
        }
    ]
    
    for l in leavers_data:
        db_helper.insert_leaver(l)
        
    # Test DataFrame retrieval with filters
    df_all = analyzer.get_leavers_dataframe()
    assert len(df_all) == 4, f"Expected 4 records, got {len(df_all)}"
    
    df_fb = analyzer.get_leavers_dataframe(department="F&B")
    assert len(df_fb) == 2, f"Expected 2 F&B records, got {len(df_fb)}"
    assert all(df_fb["department"] == "F&B")
    
    df_murree = analyzer.get_leavers_dataframe(project_name="Monal Murree")
    assert len(df_murree) == 2, f"Expected 2 Murree records, got {len(df_murree)}"
    
    # Test Metrics aggregations
    metrics = analyzer.get_summary_metrics(df_all)
    assert metrics["total_resignations"] == 4
    
    # Mean service: (2.5 + 5.5 + 9.5 + 29.5) / 4 = 47.0 / 4 = 11.75
    assert metrics["average_service_length_months"] == 11.75
    
    # Service brackets checks:
    # 2.5 -> < 3 Months (1)
    # 5.5 -> 3 - 6 Months (1)
    # 9.5 -> 6 - 12 Months (1)
    # 29.5 -> > 2 Years (1)
    brackets = metrics["service_bracket_wise"]
    assert brackets["< 3 Months"] == 1
    assert brackets["3 - 6 Months"] == 1
    assert brackets["6 - 12 Months"] == 1
    assert brackets["> 2 Years"] == 1
    assert "1 - 2 Years" not in brackets or brackets.get("1 - 2 Years", 0) == 0
    logger.info("Service bracket classification verified successfully!")
    
    # Top Affected Areas
    top_areas = analyzer.get_top_affected_areas(df_all)
    # F&B department should be top (2 resignations)
    assert top_areas["departments"][0]["name"] == "F&B"
    assert top_areas["departments"][0]["count"] == 2
    assert top_areas["departments"][0]["percentage"] == 50.0
    
    # Waiter position should be top (2 resignations)
    assert top_areas["positions"][0]["name"] == "Waiter"
    assert top_areas["positions"][0]["count"] == 2
    logger.info("Top affected areas aggregated correctly!")
    
    # Early Turnover (length of service < 6 months)
    # John (2.5) and Jane (5.5) should be classified as early turnover
    early_turnover = analyzer.get_early_turnover_details(df_all)
    assert len(early_turnover) == 2
    early_names = [e["employee_name"] for e in early_turnover]
    assert "John Doe" in early_names
    assert "Jane Smith" in early_names
    logger.info("Early turnover details identified correctly!")

    # Clean up temp test data
    db_path.unlink(missing_ok=True)
    import shutil
    shutil.rmtree(test_dir, ignore_errors=True)
    logger.info("Cleanup completed successfully. All Resignation Analytics tests passed!")

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
