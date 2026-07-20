import os
import sys
from pathlib import Path
import logging
import logging.config
from unittest.mock import patch, MagicMock
import requests

# Adjust Python path to import from workspace root
sys.path.append(str(Path(__file__).resolve().parent.parent))

from config.settings import get_logging_config
from database.db_helper import DBHelper
from modules.turnover_engine import TurnoverEngine
from modules.resignation_analytics import ResignationAnalytics
from modules.summary_generator import SummaryGenerator

# Setup Logging
logging.config.dictConfig(get_logging_config())
logger = logging.getLogger("test_summary_generator")

def run_tests():
    # Setup test database
    test_dir = Path(__file__).resolve().parent / "temp_test_data"
    test_dir.mkdir(exist_ok=True)
    
    db_path = test_dir / "test_hr.db"
    if db_path.exists():
        db_path.unlink()
        
    db_helper = DBHelper(db_path=str(db_path))
    turnover_engine = TurnoverEngine(db_helper=db_helper)
    resignation_analytics = ResignationAnalytics(db_helper=db_helper)
    
    generator = SummaryGenerator(
        db_helper=db_helper,
        turnover_engine=turnover_engine,
        resignation_analytics=resignation_analytics
    )
    
    # 1. Test empty database scenario
    empty_summary = generator.generate_summary("2026-06")
    assert "No headcount or departure records" in empty_summary
    logger.info("Empty database scenario handled cleanly.")
    
    # Seed data
    # May: HC=300. Leavers=3. Turnover=1.0%
    # June: HC=300. Leavers=3 (2 in F&B Waiters at Murree, 1 in Kitchen Chef at Lahore). Turnover=1.0%
    # Two of June leavers are early turnover (< 6 Months).
    
    db_helper.insert_headcount("Monal Murree", "2026-05", 100)
    db_helper.insert_headcount("Monal Lahore", "2026-05", 200)
    db_helper.insert_headcount("Monal Murree", "2026-06", 100)
    db_helper.insert_headcount("Monal Lahore", "2026-06", 200)
    
    leavers_data = [
        # May leavers (to establish history)
        {
            "employee_id": "EMP1", "employee_name": "E1", "project": "Monal Murree",
            "department": "F&B", "position": "Waiter", "date_of_joining": "2024-01-01",
            "date_of_leaving": "2026-05-10", "length_of_service_months": 28.3,
            "original_reason": "Better package", "record_month": "2026-05"
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
        # June leavers
        {
            "employee_id": "EMP4", "employee_name": "E4", "project": "Monal Murree",
            "department": "F&B", "position": "Waiter", "date_of_joining": "2026-03-01",
            "date_of_leaving": "2026-06-10", "length_of_service_months": 3.3,  # Early turnover
            "original_reason": "Supervisor behavior", "record_month": "2026-06"
        },
        {
            "employee_id": "EMP5", "employee_name": "E5", "project": "Monal Murree",
            "department": "F&B", "position": "Waiter", "date_of_joining": "2026-04-01",
            "date_of_leaving": "2026-06-15", "length_of_service_months": 2.5,  # Early turnover
            "original_reason": "Supervisor behavior", "record_month": "2026-06"
        },
        {
            "employee_id": "EMP6", "employee_name": "E6", "project": "Monal Lahore",
            "department": "Kitchen", "position": "Chef", "date_of_joining": "2024-01-01",
            "date_of_leaving": "2026-06-25", "length_of_service_months": 29.8,
            "original_reason": "Better package", "record_month": "2026-06"
        }
    ]
    for l in leavers_data:
        db_helper.insert_leaver(l)
        
    # Classify reasons so they populate AI category (using fallback rules)
    # EMP4 & EMP5 should classify as Supervisor / Management Issue
    # EMP6 should classify as Compensation & Benefits
    from modules.ai_classifier import AIClassifier
    classifier = AIClassifier(db_helper=db_helper)
    classifier.classify_unprocessed_leavers()
    
    # 2. Test metrics compilation
    metrics = generator.compile_metrics("2026-06")
    
    # Assert compiled results
    assert metrics["current_month"] == "2026-06"
    assert metrics["previous_month"] == "2026-05"
    assert metrics["current_turnover"] == 1.0
    assert metrics["previous_turnover"] == 1.0
    assert metrics["total_departures"] == 3
    assert metrics["highest_turnover_project"] == "Monal Murree"  # Murree turnover: 2/100=2.0%. Lahore: 1/200=0.5%.
    assert metrics["highest_dept"] == "F&B"
    assert metrics["highest_dept_count"] == 2
    assert metrics["most_common_reason"] == "Supervisor / Management Issue"
    assert metrics["most_common_reason_count"] == 2
    assert metrics["early_turnover_count"] == 2
    logger.info("Monthly executive summary KPIs compiled correctly!")
    
    # 3. Test Fallback template generation
    fallback_summary = generator.generate_fallback_summary(metrics)
    assert "# Executive Summary - 2026-06" in fallback_summary
    assert "Monal Murree" in fallback_summary
    assert "F&B" in fallback_summary
    assert "Supervisor / Management Issue" in fallback_summary
    assert f"**{metrics['early_turnover_count']}** early departures" in fallback_summary
    logger.info("Fallback executive summary formatted correctly!")
    
    # 4. Test Ollama AI summary generation (with Mock)
    with patch('requests.post') as mock_post:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"response": "# Custom Executive Summary from Llama 3.1\nObservations..."}
        mock_post.return_value = mock_response
        
        ai_summary = generator.generate_summary("2026-06")
        assert "# Custom Executive Summary from Llama 3.1" in ai_summary
        logger.info("Executive summary successfully generated via Mocked Llama 3.1!")

    # Clean up temp test data
    db_path.unlink()
    test_dir.rmdir()
    logger.info("Cleanup completed successfully. All Summary Generator tests passed!")

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
