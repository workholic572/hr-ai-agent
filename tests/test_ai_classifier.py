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
from modules.ai_classifier import AIClassifier

# Setup Logging
logging.config.dictConfig(get_logging_config())
logger = logging.getLogger("test_ai_classifier")

def run_tests():
    # Setup test database
    test_dir = Path(__file__).resolve().parent / "temp_test_data"
    test_dir.mkdir(exist_ok=True)
    
    db_path = test_dir / "test_hr.db"
    if db_path.exists():
        db_path.unlink()
        
    db_helper = DBHelper(db_path=str(db_path))
    classifier = AIClassifier(db_helper=db_helper)
    
    # 1. Test Rule-based Classifier matching accuracy
    test_cases = [
        ("Got new job at higher rank", "Better Career Opportunity"),
        ("Better package and car", "Compensation & Benefits"),
        ("Moving abroad to US", "Relocation"),
        ("Marriage and family shift", "Family Reasons"),
        ("Health issues and surgery", "Health Reasons"),
        ("Going for higher studies in Germany", "Education"),
        ("Supervisor rude behavior", "Supervisor / Management Issue"),
        ("Working environment was toxic", "Working Environment"),
        ("High work pressure and workload", "Workload"),
        ("Poor attendance and warnings", "Attendance / Discipline"),
        ("His contract completed", "Contract Completion"),
        ("Was terminated due to rules", "Termination"),
        ("Personal reasons", "Personal Reasons"),
        ("Unknown text which doesn't match anything", "Other")
    ]
    
    logger.info("=== Testing Rule-Based Classifications ===")
    for reason, expected in test_cases:
        actual = classifier.classify_with_rules(reason)
        assert actual == expected, f"Rule Match Fail! Reason: '{reason}', Expected: '{expected}', Got: '{actual}'"
        logger.info(f"Verified: '{reason}' -> '{actual}'")
        
    # 2. Test batch database updates
    # Seed 3 leavers with null category
    leaver_1 = {
        "employee_id": "EMP1", "employee_name": "E1", "project": "Monal Murree",
        "department": "F&B", "position": "Waiter", "date_of_joining": "2025-01-01",
        "date_of_leaving": "2026-05-10", "length_of_service_months": 16.3,
        "original_reason": "Got new job", "record_month": "2026-05"
    }
    leaver_2 = {
        "employee_id": "EMP2", "employee_name": "E2", "project": "Monal Lahore",
        "department": "Kitchen", "position": "Chef", "date_of_joining": "2024-06-01",
        "date_of_leaving": "2026-05-15", "length_of_service_months": 23.5,
        "original_reason": "Better package", "record_month": "2026-05"
    }
    leaver_3 = {
        "employee_id": "EMP3", "employee_name": "E3", "project": "Monal Lahore",
        "department": "HR", "position": "Officer", "date_of_joining": "2025-03-01",
        "date_of_leaving": "2026-05-20", "length_of_service_months": 14.6,
        "original_reason": "Moving abroad", "record_month": "2026-05"
    }
    
    db_helper.insert_leaver(leaver_1)
    db_helper.insert_leaver(leaver_2)
    db_helper.insert_leaver(leaver_3)
    
    # Run batch processing (which will fallback to rules because Ollama is mock/unavailable here)
    processed = classifier.classify_unprocessed_leavers()
    assert processed == 3, f"Expected 3 records processed, got {processed}"
    
    # Assert database values were updated
    leavers_summary = db_helper.get_leavers_summary()
    by_id = {l["employee_id"]: l["ai_category"] for l in leavers_summary}
    assert by_id["EMP1"] == "Better Career Opportunity"
    assert by_id["EMP2"] == "Compensation & Benefits"
    assert by_id["EMP3"] == "Relocation"
    logger.info("Batch classification successfully updated SQLite databases via fallbacks!")
    
    # 3. Test Ollama API Mocking Integration
    logger.info("=== Testing Mocked Ollama AI Client ===")
    with patch('requests.post') as mock_post:
        # Mock successful Ollama response returning 'Compensation & Benefits'
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"response": "  Compensation & Benefits  "}
        mock_post.return_value = mock_response
        
        result_ai = classifier.classify_reason("Some complex reason")
        assert result_ai == "Compensation & Benefits", f"Expected 'Compensation & Benefits', got '{result_ai}'"
        logger.info(f"Ollama mock client successfully parsed: {result_ai}")
        
    with patch('requests.post') as mock_post:
        # Mock Ollama timeout / network error
        mock_post.side_effect = requests.exceptions.Timeout("Connection timed out")
        
        result_fallback = classifier.classify_reason("better salary package")
        assert result_fallback == "Compensation & Benefits", f"Expected fallback 'Compensation & Benefits', got '{result_fallback}'"
        logger.info("Ollama client handled timeout gracefully, successfully falling back to rule-based parser!")

    # Clean up temp test data
    db_path.unlink()
    test_dir.rmdir()
    logger.info("Cleanup completed successfully. All AI Classifier tests passed!")

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
