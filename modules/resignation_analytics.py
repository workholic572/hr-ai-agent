import logging
import pandas as pd
from typing import Dict, Any, List, Optional

from database.db_helper import DBHelper

logger = logging.getLogger(__name__)

class ResignationAnalytics:
    """
    ResignationAnalytics aggregates leavers data to identify departure patterns,
    distribution across departments/projects/positions, service length brackets, and reasons.
    """
    def __init__(self, db_helper: Optional[DBHelper] = None):
        self.db_helper = db_helper or DBHelper()

    def get_leavers_dataframe(
        self,
        project_name: Optional[str] = None,
        department: Optional[str] = None,
        position: Optional[str] = None,
        start_month: Optional[str] = None,
        end_month: Optional[str] = None
    ) -> pd.DataFrame:
        """
        Retrieves leavers records from DB and returns them as a Pandas DataFrame.
        Applies filter conditions on projects, departments, positions, and months.
        """
        records = self.db_helper.get_leavers_summary(
            project_name=project_name,
            start_month=start_month,
            end_month=end_month
        )
        df = pd.DataFrame(records)
        
        # Ensure minimum structure if empty
        if df.empty:
            return pd.DataFrame(columns=[
                "id", "employee_id", "employee_name", "project_id", "department",
                "position", "date_of_joining", "date_of_leaving",
                "length_of_service_months", "original_reason", "ai_category",
                "record_month", "project_name"
            ])
            
        # Apply local filters if set
        if department:
            df = df[df["department"].str.strip().str.lower() == department.strip().lower()]
        if position:
            df = df[df["position"].str.strip().str.lower() == position.strip().lower()]
            
        return df

    @staticmethod
    def get_service_bracket(months: float) -> str:
        """Categorizes service length in months into standard brackets."""
        if pd.isna(months) or months < 0:
            return "Unknown"
        if months < 3:
            return "< 3 Months"
        elif months < 6:
            return "3 - 6 Months"
        elif months < 12:
            return "6 - 12 Months"
        elif months < 24:
            return "1 - 2 Years"
        else:
            return "> 2 Years"

    def get_summary_metrics(self, df: pd.DataFrame) -> Dict[str, Any]:
        """
        Computes general resignation metrics:
        Total resignations, average length of service, and count distributions.
        """
        if df.empty:
            return {
                "total_resignations": 0,
                "average_service_length_months": 0.0,
                "project_wise": {},
                "department_wise": {},
                "position_wise": {},
                "reasons_wise": {},
                "service_bracket_wise": {},
                "monthly_trend": {}
            }

        # Calculate distributions
        project_wise = df["project_name"].value_counts().to_dict()
        department_wise = df["department"].value_counts().to_dict()
        position_wise = df["position"].value_counts().to_dict()
        
        # Reasons: handle original reason frequency
        reasons_wise = df["original_reason"].value_counts().to_dict()
        
        # Service length brackets
        brackets = df["length_of_service_months"].apply(self.get_service_bracket)
        bracket_order = ["< 3 Months", "3 - 6 Months", "6 - 12 Months", "1 - 2 Years", "> 2 Years", "Unknown"]
        service_bracket_counts = brackets.value_counts().to_dict()
        
        # Sort service brackets in biological sequence
        service_bracket_wise = {
            b: service_bracket_counts.get(b, 0) for b in bracket_order if b in service_bracket_counts or service_bracket_counts.get(b, 0) > 0
        }
        
        # Monthly departure count trend
        monthly_trend = df["record_month"].value_counts().sort_index().to_dict()
        
        # Average length of service
        avg_service = float(df["length_of_service_months"].mean())
        
        return {
            "total_resignations": len(df),
            "average_service_length_months": round(avg_service, 2),
            "project_wise": project_wise,
            "department_wise": department_wise,
            "position_wise": position_wise,
            "reasons_wise": reasons_wise,
            "service_bracket_wise": service_bracket_wise,
            "monthly_trend": monthly_trend
        }

    def get_top_affected_areas(self, df: pd.DataFrame, top_n: int = 3) -> Dict[str, Any]:
        """
        Returns top affected departments, positions, and resignation reasons.
        """
        if df.empty:
            return {
                "departments": [],
                "positions": [],
                "reasons": []
            }
            
        def get_top(col: str) -> List[Dict[str, Any]]:
            counts = df[col].value_counts()
            total = len(df)
            return [
                {
                    "name": name,
                    "count": int(count),
                    "percentage": round((count / total) * 100, 2)
                }
                for name, count in counts.head(top_n).items()
            ]
            
        # Top AI categories if populated, else original reason
        reason_col = "ai_category" if "ai_category" in df.columns and df["ai_category"].notna().any() else "original_reason"
        
        return {
            "departments": get_top("department"),
            "positions": get_top("position"),
            "reasons": get_top(reason_col)
        }

    def get_early_turnover_details(self, df: pd.DataFrame) -> List[Dict[str, Any]]:
        """
        Identifies 'early turnover' leavers (length of service < 6 months).
        Returns list of detail records for management review.
        """
        if df.empty:
            return []
            
        early_df = df[df["length_of_service_months"] < 6.0]
        
        # Return fields useful for analysis
        return early_df[[
            "employee_id", "employee_name", "project_name", "department",
            "position", "length_of_service_months", "original_reason"
        ]].to_dict(orient="records")
