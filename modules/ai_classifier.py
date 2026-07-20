import logging
import requests
import json
import re
from typing import Dict, Any, List, Optional

from config.settings import STANDARD_CATEGORIES
from database.db_helper import DBHelper

logger = logging.getLogger(__name__)

class AIClassifier:
    """
    AIClassifier leverages an Ollama-hosted Llama 3.1 model to categorize employee
    resignation reasons into standard HR categories, with a robust rule-based fallback.
    """
    def __init__(self, db_helper: Optional[DBHelper] = None, ollama_url: str = "http://localhost:11434"):
        self.db_helper = db_helper or DBHelper()
        self.ollama_url = ollama_url
        self.model_name = "llama3.1"
        self.timeout_seconds = 3.0

    def classify_with_rules(self, reason: str) -> str:
        """
        Rule-based keyword fallback classifier.
        Matches common text cues to assign standard HR categories.
        """
        reason_lower = str(reason).lower().strip()
        
        if not reason_lower or reason_lower in ["not specified", "none", "n/a", "other"]:
            return "Other"

        # Define keyword mappings — ordered from most specific to most general
        rules = [
            # Left Without Notice — must come before Attendance/Discipline
            (r"\blwn\b|left without notice|left without information|absconded|abscond|awol|abandoned post|no show|disappeared|left without warning", "Left Without Notice"),
            (r"salary|package|pay|increment|money|compensation|benefit|bonus|wage", "Compensation & Benefits"),
            (r"opportunity|job|career|grow|better prospects|new role|hired|join|offer|promotion|future", "Better Career Opportunity"),
            (r"family|marriage|child|parent|home|domestic|husband|wife|wedding|spouse|pregnant|maternity", "Family Reasons"),
            (r"health|sick|medical|illness|disease|treatment|accident|physical|mental|therapy|doctor", "Health Reasons"),
            (r"study|education|studies|higher|college|university|degree|course|exam", "Education"),
            (r"relocat|abroad|country|move|moving|shift|transfer|visa|travel", "Relocation"),
            (r"supervisor|manager|boss|behavior|attitude|management|conflict|treatment|harass|rude|colleague", "Supervisor / Management Issue"),
            (r"environment|culture|politics|toxic|atmosphere|office|distance|commute|commuting", "Working Environment"),
            (r"workload|pressure|stress|hours|night shift|shift timing|overtime|burnout|exhaust", "Workload"),
            (r"discipline|absent|attendance|violation|policy|misconduct|warning", "Attendance / Discipline"),
            (r"terminate|fire|fired|dismiss|layoff|laid off|redundant", "Termination"),
            (r"contract|expire|completion|complete|period|end date|project end", "Contract Completion"),
            (r"personal", "Personal Reasons")
        ]
        
        for pattern, category in rules:
            if re.search(pattern, reason_lower):
                return category
                
        return "Other"

    def classify_with_ollama(self, reason: str) -> Optional[str]:
        """
        Queries the local Ollama instance running Llama 3.1 to classify the reason.
        Returns the category name if successful, else None.
        """
        categories_str = "\n- ".join(STANDARD_CATEGORIES)
        prompt = (
            f"You are an expert HR Analyst.\n"
            f"Classify this employee resignation reason into exactly one of the following categories:\n"
            f"- {categories_str}\n\n"
            f"Rules:\n"
            f"1. Output ONLY the exact category name from the list above.\n"
            f"2. Do NOT write introductory words, explanations, quote marks, or punctuation.\n"
            f"3. If the reason is ambiguous, match the closest category or output 'Other'.\n\n"
            f"Employee Resignation Reason: \"{reason}\"\n"
            f"Selected Category:"
        )

        payload = {
            "model": self.model_name,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": 0.0
            }
        }

        try:
            response = requests.post(
                f"{self.ollama_url}/api/generate",
                json=payload,
                timeout=self.timeout_seconds
            )
            if response.status_code == 200:
                result = response.json().get("response", "").strip()
                # Clean quotes or punctuation from model response
                result_clean = re.sub(r"^['\"\-\s]+|['\"\-\s\.]+$", "", result)
                
                # Check for exact case-insensitive match
                for cat in STANDARD_CATEGORIES:
                    if cat.lower() == result_clean.lower():
                        return cat
                        
                # Check for substring match
                for cat in STANDARD_CATEGORIES:
                    if cat.lower() in result_clean.lower():
                        return cat
                        
                logger.warning(f"Ollama returned non-standard category: '{result}' for reason '{reason}'.")
            else:
                logger.warning(f"Ollama returned status code {response.status_code}.")
        except requests.exceptions.RequestException as e:
            logger.debug(f"Ollama connection skipped/failed: {e}")
            
        return None

    def classify_reason(self, reason: str) -> str:
        """
        Classifies a single resignation reason, trying Ollama first,
        falling back to keyword rules if Ollama is unavailable or returns invalid category.
        """
        # Try Ollama first
        ollama_cat = self.classify_with_ollama(reason)
        if ollama_cat:
            logger.info(f"Classified via AI: '{reason}' -> '{ollama_cat}'")
            return ollama_cat
            
        # Fallback to rules
        rule_cat = self.classify_with_rules(reason)
        logger.info(f"Classified via Rules: '{reason}' -> '{rule_cat}'")
        return rule_cat

    def classify_unprocessed_leavers(self) -> int:
        """
        Retrieves all leavers without a valid AI category and classifies them in batch.
        Updates the database for each. Returns the count of processed records.
        """
        unclassified = self.db_helper.get_unclassified_leavers()
        if not unclassified:
            logger.info("No unclassified leavers records found.")
            return 0
            
        logger.info(f"Found {len(unclassified)} unclassified leavers records. Beginning batch classification...")
        processed_count = 0
        
        for leaver in unclassified:
            reason = leaver.get("original_reason", "")
            emp_id = leaver["employee_id"]
            
            try:
                category = self.classify_reason(reason)
                self.db_helper.update_leaver_ai_category(emp_id, category)
                processed_count += 1
            except Exception as e:
                logger.error(f"Error classifying/updating employee {emp_id}: {e}", exc_info=True)
                
        logger.info(f"Batch classification complete. Processed {processed_count}/{len(unclassified)} records.")
        return processed_count
