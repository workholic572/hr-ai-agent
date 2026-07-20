import logging
import requests
from typing import Dict, Any, List, Optional
from datetime import datetime
from dateutil.relativedelta import relativedelta

from database.db_helper import DBHelper
from modules.turnover_engine import TurnoverEngine
from modules.resignation_analytics import ResignationAnalytics

logger = logging.getLogger(__name__)

class SummaryGenerator:
    """
    SummaryGenerator compiles historical and monthly metrics to draft dynamic
    management executive summaries, either using Llama 3.1 on Ollama or a fallback template.
    Supports single-month and multi-month (quarterly, semi-annual, annual, custom) periods.
    """
    def __init__(
        self,
        db_helper: Optional[DBHelper] = None,
        turnover_engine: Optional[TurnoverEngine] = None,
        resignation_analytics: Optional[ResignationAnalytics] = None,
        ollama_url: str = "http://localhost:11434"
    ):
        self.db_helper = db_helper or DBHelper()
        self.turnover_engine = turnover_engine or TurnoverEngine(db_helper=self.db_helper)
        self.resignation_analytics = resignation_analytics or ResignationAnalytics(db_helper=self.db_helper)
        self.ollama_url = ollama_url
        self.model_name = "llama3.1"
        self.timeout_seconds = 8.0  # Slightly longer timeout for large generation tasks

    def _calculate_previous_range(self, start_month: str, end_month: str):
        """
        Given a current period [start_month, end_month], calculates the immediately
        preceding period of the same length.
        E.g., Q2 2026 (Apr-Jun) -> previous is Q1 2026 (Jan-Mar).
        """
        try:
            start_dt = datetime.strptime(start_month, "%Y-%m")
            end_dt = datetime.strptime(end_month, "%Y-%m")
        except ValueError:
            return start_month, end_month

        # Number of months in the period (inclusive)
        period_months = (end_dt.year - start_dt.year) * 12 + (end_dt.month - start_dt.month) + 1

        prev_end_dt = start_dt - relativedelta(months=1)
        prev_start_dt = prev_end_dt - relativedelta(months=period_months - 1)

        return prev_start_dt.strftime("%Y-%m"), prev_end_dt.strftime("%Y-%m")

    def compile_metrics(self, start_month: str, end_month: Optional[str] = None) -> Dict[str, Any]:
        """
        Gathers KPIs from the database, turnover engine, and resignation analytics
        to prepare a structured context dictionary for the summary.
        Supports both single-month (start_month only) and multi-month range analysis.
        """
        if not end_month:
            end_month = start_month

        # Calculate the previous comparison range of the same length
        prev_start, prev_end = self._calculate_previous_range(start_month, end_month)

        # 1. Turnover rates for current and previous period
        current_turnover = self.turnover_engine.calculate_overall_turnover(start_month, end_month)
        previous_turnover = self.turnover_engine.calculate_overall_turnover(prev_start, prev_end)
        diff = round(current_turnover - previous_turnover, 2)

        # Project-level turnover for the current period
        projects_list = self.db_helper.get_projects()
        project_comparison = {}
        for p in projects_list:
            proj_name = p["name"]
            curr_proj = self.turnover_engine.calculate_project_turnover(proj_name, start_month, end_month)
            comp_proj = self.turnover_engine.calculate_project_turnover(proj_name, prev_start, prev_end)
            project_comparison[proj_name] = {
                "current": curr_proj,
                "compare": comp_proj,
                "difference": round(curr_proj - comp_proj, 2)
            }

        # 2. Resignation metrics (current period)
        df_curr = self.resignation_analytics.get_leavers_dataframe(start_month=start_month, end_month=end_month)
        summary_metrics = self.resignation_analytics.get_summary_metrics(df_curr)
        top_areas = self.resignation_analytics.get_top_affected_areas(df_curr, top_n=3)
        early_leavers = self.resignation_analytics.get_early_turnover_details(df_curr)

        # Identify highest turnover project
        highest_project_name = "None"
        highest_project_rate = 0.0

        for name, rates in project_comparison.items():
            if rates["current"] > highest_project_rate:
                highest_project_rate = rates["current"]
                highest_project_name = name

        # Top affected areas details
        top_dept = top_areas["departments"][0]["name"] if top_areas["departments"] else "N/A"
        top_dept_count = top_areas["departments"][0]["count"] if top_areas["departments"] else 0

        top_reason = top_areas["reasons"][0]["name"] if top_areas["reasons"] else "N/A"
        top_reason_count = top_areas["reasons"][0]["count"] if top_areas["reasons"] else 0

        # Build a display-friendly period label
        if start_month == end_month:
            period_label = start_month
            prev_period_label = prev_end
        else:
            period_label = f"{start_month} to {end_month}"
            prev_period_label = f"{prev_start} to {prev_end}"

        return {
            "current_month": period_label,
            "previous_month": prev_period_label,
            "current_turnover": current_turnover,
            "previous_turnover": previous_turnover,
            "difference": diff,
            "total_departures": summary_metrics["total_resignations"],
            "average_service_length_months": summary_metrics["average_service_length_months"],
            "highest_turnover_project": highest_project_name,
            "highest_turnover_project_rate": highest_project_rate,
            "highest_dept": top_dept,
            "highest_dept_count": top_dept_count,
            "most_common_reason": top_reason,
            "most_common_reason_count": top_reason_count,
            "early_turnover_count": len(early_leavers),
            "early_leavers": early_leavers,
            "all_projects": list(project_comparison.keys())
        }

    def generate_fallback_summary(self, metrics: Dict[str, Any]) -> str:
        """
        Creates a high-quality Markdown summary using parameter interpolation when
        the AI model is not accessible.
        """
        diff = metrics["difference"]
        trend_str = f"an increase of **+{diff}%**" if diff > 0 else (f"a decrease of **{diff}%**" if diff < 0 else "no change")

        recommendations = [
            f"1. **Audit Operations in {metrics['highest_dept']}**: Since the '{metrics['highest_dept']}' department accounts for the highest volume of departures ({metrics['highest_dept_count']}), conduct stay-interviews and verify working environment standards.",
            f"2. **Address '{metrics['most_common_reason']}'**: With '{metrics['most_common_reason']}' highlighted as the primary resignation driver, review internal policies, wage fairness, and professional growth tracks relative to this factor."
        ]

        if metrics["early_turnover_count"] > 0:
            recommendations.append(
                f"3. **Onboarding Checks & Early Safeguards**: Since {metrics['early_turnover_count']} employees left within 6 months, refine onboarding processes and run mandatory manager check-ins at 30, 60, and 90 days."
            )
        else:
            recommendations.append(
                "3. **Sustain Employee Engagement**: Continue current onboarding protocols and introduce regular feedback checkpoints for tenured staff to sustain high retention."
            )

        rec_text = "\n".join(recommendations)

        summary = (
            f"# Executive Summary - {metrics['current_month']}\n\n"
            f"## Strategic Overview\n"
            f"During **{metrics['current_month']}**, the Monal Group registered a total headcount departure of **{metrics['total_departures']}** employees. "
            f"The overall turnover rate for this period was **{metrics['current_turnover']}%**, representing {trend_str} compared to "
            f"the previous period ({metrics['previous_month']} at **{metrics['previous_turnover']}%**).\n\n"
            f"## Key Observations\n"
            f"- **Highest Turnover Project**: **{metrics['highest_turnover_project']}** recorded the highest turnover rate of **{metrics['highest_turnover_project_rate']}%**.\n"
            f"- **Most Affected Department**: The **{metrics['highest_dept']}** department witnessed the highest resignation activity, with **{metrics['highest_dept_count']}** departures.\n"
            f"- **Top Resignation Reason**: The leading driver behind resignations was **'{metrics['most_common_reason']}'** ({metrics['most_common_reason_count']} departures).\n"
            f"- **Early Attrition Risk**: There were **{metrics['early_turnover_count']}** early departures (employees leaving in < 6 months), which represents an operational risk in onboarding or selection.\n"
            f"- **Average Tenancy**: Departing employees had an average length of service of **{metrics['average_service_length_months']} months**.\n\n"
            f"## Actionable Recommendations\n"
            f"{rec_text}\n"
        )
        return summary

    def generate_ai_summary(self, metrics: Dict[str, Any]) -> Optional[str]:
        """
        Asks local Ollama / Llama 3.1 to generate a customized management report based
        on compiled metrics. Returns None if skipped/failed.
        """
        early_details = ""
        if metrics["early_turnover_count"] > 0:
            early_details = "\n".join([
                f"- {e['employee_name']} ({e['position']} at {e['project_name']}) left after {e['length_of_service_months']} months due to '{e['original_reason']}'"
                for e in metrics["early_leavers"]
            ])

        prompt = (
            f"You are a Senior HR Director and AI Analytics Consultant for The Monal Group (a hospitality company).\n"
            f"Write a professional, corporate-ready Executive Summary based on the following HR metrics for this period.\n\n"
            f"METRICS:\n"
            f"- Period: {metrics['current_month']} (compared to previous period: {metrics['previous_month']})\n"
            f"- Turnover Rate: {metrics['current_turnover']}% (previous period was {metrics['previous_turnover']}%)\n"
            f"- Total Departures: {metrics['total_departures']}\n"
            f"- Highest Turnover Project: {metrics['highest_turnover_project']} ({metrics['highest_turnover_project_rate']}%)\n"
            f"- Highest Resignation Department: {metrics['highest_dept']} ({metrics['highest_dept_count']} departures)\n"
            f"- Top Resignation Reason: {metrics['most_common_reason']} ({metrics['most_common_reason_count']} departures)\n"
            f"- Early Turnover (departing in < 6 months): {metrics['early_turnover_count']} employees\n"
            f"Early Turnover Details:\n{early_details}\n"
            f"- Average length of service of leavers: {metrics['average_service_length_months']} months\n\n"
            f"FORMAT REQUIREMENT:\n"
            f"Draft in Markdown format with the following headings:\n"
            f"# Executive Summary - {metrics['current_month']}\n"
            f"## Strategic Overview\n"
            f"## Key Observations\n"
            f"## Actionable Recommendations (provide 3 customized, highly practical retention tactics for Monal Group)\n\n"
            f"Do not write any introductory or chat meta-text (like 'Here is the summary...'). Start directly with the Markdown headings."
        )

        payload = {
            "model": self.model_name,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": 0.3
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
                if result:
                    return result
            logger.warning(f"Ollama returned status code {response.status_code}.")
        except requests.exceptions.RequestException as e:
            logger.debug(f"Ollama connection skipped/failed: {e}")

        return None

    def generate_summary(self, start_month: str, end_month: Optional[str] = None) -> str:
        """
        Main entrypoint. Compiles metrics, attempts AI summary via Ollama,
        and falls back to rule-based template generation on failure.
        Supports single-month and multi-month ranges.
        """
        if not end_month:
            end_month = start_month

        period_label = start_month if start_month == end_month else f"{start_month} to {end_month}"
        logger.info(f"Generating Executive Summary for period {period_label}...")
        metrics = self.compile_metrics(start_month, end_month)

        # If there are no departures or headcounts, we handle gracefully
        if metrics["total_departures"] == 0 and metrics["current_turnover"] == 0.0:
            return (
                f"# Executive Summary - {period_label}\n\n"
                f"No headcount or departure records were found for the period **{period_label}**. "
                f"Please ensure headcount and leavers Excel files are loaded for this period before generating a summary."
            )

        # Try AI summary
        ai_summary = self.generate_ai_summary(metrics)
        if ai_summary:
            logger.info("Executive Summary generated via Llama 3.1 AI.")
            return ai_summary

        # Fallback
        logger.info("Executive Summary generated via fallback template.")
        return self.generate_fallback_summary(metrics)
