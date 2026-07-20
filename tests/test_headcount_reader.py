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
from modules.headcount_reader import HeadcountReader

# Setup Logging
logging.config.dictConfig(get_logging_config())
logger = logging.getLogger("test_headcount_reader")

def run_tests():
    # Setup test workspace
    test_dir = Path(__file__).resolve().parent / "temp_test_data"
    test_dir.mkdir(exist_ok=True)
    
    db_path = test_dir / "test_hr.db"
    if db_path.exists():
        db_path.unlink()
        
    db_helper = DBHelper(db_path=str(db_path))
    processor = HeadcountReader(db_helper=db_helper)
    
    # 1. Create mock data for month 1 (2026-05)
    df_m1 = pd.DataFrame([
        {"Project": "Monal Murree", "Headcount": 300},
        {"Project": "Monal Lahore", "Headcount": 200},
        {"Project": "Monal Imarat", "Headcount": 500}
    ])
    
    # 2. Create mock data for month 2 (2026-06)
    df_m2 = pd.DataFrame([
        {"Project": "Monal Murree", "Headcount": 350},
        {"Project": "Monal Lahore", "Headcount": 220},
        {"Project": "Monal Imarat", "Headcount": 520}
    ])
    
    hc_m1_path = test_dir / "headcount_2026_05.xlsx"
    hc_m2_path = test_dir / "headcount_2026_06.xlsx"
    
    df_m1.to_excel(hc_m1_path, index=False)
    df_m2.to_excel(hc_m2_path, index=False)
    
    # Process files
    report_m1 = processor.process_file(hc_m1_path)
    assert report_m1["is_valid"] is True, "Month 1 processing failed"
    
    report_m2 = processor.process_file(hc_m2_path)
    assert report_m2["is_valid"] is True, "Month 2 processing failed"
    
    # Verify Database Insertion & History Fetching
    history = processor.get_history()
    assert len(history) == 6, f"Expected 6 records in history, got {len(history)}"
    
    # Verify Averages
    # Murree: 300 and 350 -> avg 325
    # Lahore: 200 and 220 -> avg 210
    # Imarat: 500 and 520 -> avg 510
    
    # Overall Average: (300+200+500+350+220+520) / 6 = 2090 / 6 = 348.33
    overall_avg = processor.get_average_headcount()
    assert abs(overall_avg - 348.33) < 0.1, f"Expected overall average ~348.33, got {overall_avg}"
    logger.info(f"Overall average headcount verified: {overall_avg:.2f}")
    
    # Project-specific Averages
    murree_avg = processor.get_average_headcount(project_name="Monal Murree")
    assert murree_avg == 325.0, f"Expected Murree average 325, got {murree_avg}"
    logger.info(f"Monal Murree average headcount verified: {murree_avg}")
    
    project_averages = processor.get_project_averages()
    averages_dict = {p["project_name"]: p["avg_hc"] for p in project_averages}
    
    assert averages_dict["Monal Imarat"] == 510.0
    assert averages_dict["Monal Murree"] == 325.0
    assert averages_dict["Monal Lahore"] == 210.0
    logger.info("Project-wise headcount averages verified successfully!")
    
    # Test ON CONFLICT (upsert update) behavior
    # Re-import month 1 with updated headcount
    df_m1_update = pd.DataFrame([
        {"Project": "Monal Murree", "Headcount": 310},  # Was 300
        {"Project": "Monal Lahore", "Headcount": 200},
        {"Project": "Monal Imarat", "Headcount": 500}
    ])
    df_m1_update.to_excel(hc_m1_path, index=False)
    
    report_m1_update = processor.process_file(hc_m1_path)
    assert report_m1_update["is_valid"] is True
    
    # New Murree Avg: 310 and 350 -> avg 330
    new_murree_avg = processor.get_average_headcount(project_name="Monal Murree")
    assert new_murree_avg == 330.0, f"Expected updated Murree average 330, got {new_murree_avg}"
    logger.info("Database ON CONFLICT updates headcount correctly upon re-import!")

    # Clean up temp test data
    hc_m1_path.unlink()
    hc_m2_path.unlink()
    db_path.unlink()
    test_dir.rmdir()
    logger.info("Cleanup completed successfully. All Headcount Reader tests passed!")

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
