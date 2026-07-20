import logging
import pandas as pd
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime
from dateutil.relativedelta import relativedelta

from database.db_helper import DBHelper

logger = logging.getLogger(__name__)

class TurnoverEngine:
    """
    TurnoverEngine calculates overall and project-specific turnover rates,
    annual trends, monthly comparisons, and rolling 12-month metrics.
    """
    def __init__(self, db_helper: Optional[DBHelper] = None):
        self.db_helper = db_helper or DBHelper()

    def get_previous_month(self, month_str: str) -> str:
        """Helper to get previous YYYY-MM month string."""
        try:
            dt = datetime.strptime(month_str, "%Y-%m")
            prev_dt = dt - relativedelta(months=1)
            return prev_dt.strftime("%Y-%m")
        except ValueError:
            return month_str

    def _get_months_in_range(self, start_month: str, end_month: str) -> List[str]:
        """Helper to get list of YYYY-MM strings in a range inclusive."""
        months = []
        try:
            start_date = datetime.strptime(start_month, "%Y-%m")
            end_date = datetime.strptime(end_month, "%Y-%m")
        except ValueError:
            return [start_month]
            
        curr = start_date
        while curr <= end_date:
            months.append(curr.strftime("%Y-%m"))
            curr += relativedelta(months=1)
        return months

    def get_adjusted_headcount(self, start_month: Optional[str] = None, end_month: Optional[str] = None) -> pd.DataFrame:
        """
        Fetches headcount history and returns adjusted headcount for each project and month.
        For month M and project P:
        Adjusted headcount = (Headcount(M, P) + Headcount(M-1, P)) / 2.0.
        If Headcount(M-1, P) does not exist in the database, it defaults to Headcount(M, P).
        """
        fetch_start = start_month
        if start_month:
            fetch_start = self.get_previous_month(start_month)
            
        raw_records = self.db_helper.get_headcount_history(start_month=fetch_start, end_month=end_month)
        if not raw_records:
            return pd.DataFrame(columns=["project_name", "record_month", "headcount"])
            
        df_raw = pd.DataFrame(raw_records)
        if df_raw.empty:
            return pd.DataFrame(columns=["project_name", "record_month", "headcount"])
        
        if start_month:
            target_months = self._get_months_in_range(start_month, end_month or start_month)
        else:
            target_months = sorted(df_raw["record_month"].unique())
            
        adjusted_rows = []
        projects = df_raw["project_name"].unique()
        
        for proj in projects:
            df_proj = df_raw[df_raw["project_name"] == proj]
            hc_map = dict(zip(df_proj["record_month"], df_proj["headcount"]))
            
            for m in target_months:
                if m in hc_map:
                    curr_hc = hc_map[m]
                    prev_m = self.get_previous_month(m)
                    if prev_m in hc_map:
                        prev_hc = hc_map[prev_m]
                        adj_hc = (curr_hc + prev_hc) / 2.0
                    else:
                        adj_hc = float(curr_hc)
                    
                    adjusted_rows.append({
                        "project_name": proj,
                        "record_month": m,
                        "headcount": adj_hc
                    })
        if not adjusted_rows:
            return pd.DataFrame(columns=["project_name", "record_month", "headcount"])
        return pd.DataFrame(adjusted_rows)

    def get_aggregated_data(self, start_month: Optional[str] = None, end_month: Optional[str] = None) -> Tuple[pd.DataFrame, pd.DataFrame]:
        """
        Fetches headcounts and leavers as DataFrames for the given period.
        """
        hc_records = self.db_helper.get_headcount_history(start_month=start_month, end_month=end_month)
        lv_records = self.db_helper.get_leavers_summary(start_month=start_month, end_month=end_month)
        
        df_hc = pd.DataFrame(hc_records)
        df_lv = pd.DataFrame(lv_records)
        
        # Ensure minimum columns if empty
        if df_hc.empty:
            df_hc = pd.DataFrame(columns=["project_name", "record_month", "headcount"])
        if df_lv.empty:
            df_lv = pd.DataFrame(columns=["project_name", "record_month", "employee_id"])
            
        return df_hc, df_lv

    def calculate_overall_turnover(self, start_month: Optional[str] = None, end_month: Optional[str] = None) -> float:
        """
        Calculates the overall turnover rate for a period:
        (Total Leavers / Mean of Total Adjusted Headcount) * 100
        """
        df_hc = self.get_adjusted_headcount(start_month, end_month)
        _, df_lv = self.get_aggregated_data(start_month, end_month)
        
        if df_hc.empty:
            return 0.0
            
        # Sum headcount by month to get total monthly headcount, then take the average across the months
        monthly_total_hc = df_hc.groupby("record_month")["headcount"].sum()
        avg_headcount = monthly_total_hc.mean()
        
        if avg_headcount <= 0:
            return 0.0
            
        total_leavers = len(df_lv)
        
        turnover_rate = (total_leavers / avg_headcount) * 100
        return round(turnover_rate, 2)

    def calculate_project_turnover(self, project_name: str, start_month: Optional[str] = None, end_month: Optional[str] = None) -> float:
        """
        Calculates turnover rate for a specific project:
        (Project Leavers / Mean of Project Adjusted Headcount) * 100
        """
        df_hc = self.get_adjusted_headcount(start_month, end_month)
        _, df_lv = self.get_aggregated_data(start_month, end_month)
        
        if "project_name" not in df_hc.columns:
            return 0.0
            
        df_hc_proj = df_hc[df_hc["project_name"] == project_name]
        df_lv_proj = df_lv[df_lv["project_name"] == project_name] if "project_name" in df_lv.columns else pd.DataFrame()
        
        if df_hc_proj.empty:
            return 0.0
            
        # Average headcount for the project over the selected months
        avg_headcount = df_hc_proj["headcount"].mean()
        if avg_headcount <= 0:
            return 0.0
            
        total_leavers = len(df_lv_proj)
        
        turnover_rate = (total_leavers / avg_headcount) * 100
        return round(turnover_rate, 2)

    def get_monthly_comparison(self, current_month: str, compare_month: str) -> Dict[str, Any]:
        """
        Compares overall and project-wise turnover rates between two months.
        """
        current_overall = self.calculate_overall_turnover(current_month, current_month)
        compare_overall = self.calculate_overall_turnover(compare_month, compare_month)
        
        diff = round(current_overall - compare_overall, 2)
        
        # Calculate comparison per project
        projects = self.db_helper.get_projects()
        project_comparison = {}
        for p in projects:
            proj_name = p["name"]
            curr_proj = self.calculate_project_turnover(proj_name, current_month, current_month)
            comp_proj = self.calculate_project_turnover(proj_name, compare_month, compare_month)
            project_comparison[proj_name] = {
                "current": curr_proj,
                "compare": comp_proj,
                "difference": round(curr_proj - comp_proj, 2)
            }
            
        return {
            "current_month": current_month,
            "compare_month": compare_month,
            "current_overall": current_overall,
            "compare_overall": compare_overall,
            "difference": diff,
            "projects": project_comparison
        }

    def get_annual_trend(self, year: str) -> List[Dict[str, Any]]:
        """
        Calculates monthly turnover rates for all months in a given year.
        """
        trend = []
        for month in range(1, 13):
            month_str = f"{year}-{month:02d}"
            overall_rate = self.calculate_overall_turnover(month_str, month_str)
            
            # Fetch headcount & leavers counts to return alongside rate
            df_hc = self.get_adjusted_headcount(month_str, month_str)
            _, df_lv = self.get_aggregated_data(month_str, month_str)
            headcount = int(df_hc["headcount"].sum()) if not df_hc.empty else 0
            leavers = len(df_lv)
            
            trend.append({
                "month": month_str,
                "headcount": headcount,
                "leavers": leavers,
                "turnover_rate": overall_rate
            })
        return trend

    def calculate_rolling_12_month_turnover(self, end_month: str) -> Dict[str, Any]:
        """
        Calculates rolling 12-month turnover ending on the specified month.
        Format: YYYY-MM
        """
        try:
            end_date = datetime.strptime(end_month, "%Y-%m")
        except ValueError:
            raise ValueError(f"Invalid date format for end_month: '{end_month}'. Expected YYYY-MM.")
            
        start_date = end_date - relativedelta(months=11)
        start_month = start_date.strftime("%Y-%m")
        
        df_hc = self.get_adjusted_headcount(start_month, end_month)
        _, df_lv = self.get_aggregated_data(start_month, end_month)
        
        # Calculate overall 12M rate
        monthly_hc = df_hc.groupby("record_month")["headcount"].sum()
        avg_headcount = monthly_hc.mean() if not monthly_hc.empty else 0.0
        total_leavers = len(df_lv)
        
        overall_rate = round((total_leavers / avg_headcount) * 100, 2) if avg_headcount > 0 else 0.0
        
        # Calculate by project
        projects = self.db_helper.get_projects()
        project_rates = {}
        for p in projects:
            p_name = p["name"]
            df_hc_p = df_hc[df_hc["project_name"] == p_name]
            df_lv_p = df_lv[df_lv["project_name"] == p_name]
            
            p_avg_hc = df_hc_p["headcount"].mean() if not df_hc_p.empty else 0.0
            p_leavers = len(df_lv_p)
            p_rate = round((p_leavers / p_avg_hc) * 100, 2) if p_avg_hc > 0 else 0.0
            
            project_rates[p_name] = {
                "leavers_count": p_leavers,
                "avg_headcount": round(p_avg_hc, 2),
                "turnover_rate": p_rate
            }
            
        return {
            "period": f"{start_month} to {end_month}",
            "avg_headcount": round(avg_headcount, 2),
            "leavers_count": total_leavers,
            "turnover_rate": overall_rate,
            "projects": project_rates
        }
