import re
import difflib
import pandas as pd
import logging
from pathlib import Path
from typing import Dict, Any, List, Tuple, Optional
from datetime import datetime

from config.settings import EXPECTED_HEADCOUNT_COLUMNS, EXPECTED_LEAVERS_COLUMNS, load_standards_registry
from database.db_helper import DBHelper

logger = logging.getLogger(__name__)


def normalize_field_values(values: List[str], standards: List[str] = None, cutoff: float = 0.78) -> Tuple[Dict[str, str], Dict[str, str]]:
    """
    Fuzzy-clusters a list of string values against a list of standard canonical names.
    Returns: mapping {original_value -> canonical_value}
    
    Strategy:
    1. If standards exist, check against them first.
    2. Then fuzzy cluster the remaining items dynamically.
    """
    if not values:
        return {}

    standards = standards or []
    
    # Step 1: basic clean
    cleaned_map: Dict[str, str] = {}
    for v in values:
        cleaned = " ".join(str(v).strip().split()).title()
        cleaned_map[v] = cleaned

    # Hardcoded known aliases and abbreviations
    ALIASES = {
        "hr": "Human Resources",
        "human resource": "Human Resources",
        "hr dept": "Human Resources",
        "hr depart": "Human Resources",
        "admin": "Administration",
        "acct": "Accounts",
        "account": "Accounts",
        "it": "Information Technology",
        "house keeping": "Housekeeping",
        "chines & thai": "Chinese & Thai",
        "front desk": "Front Office"
    }

    canonicals = list(standards)
    cleaned_to_canonical: Dict[str, str] = {}
    unique_cleaned = list(dict.fromkeys(cleaned_map.values()))

    for val in unique_cleaned:
        val_lower = val.lower()
        
        # 0. Check exact case-insensitive match against standards
        exact_match = None
        for std in standards:
            if std.lower() == val_lower:
                exact_match = std
                break
        if exact_match:
            cleaned_to_canonical[val] = exact_match
            continue
            
        # 1. Check exact aliases first
        if val_lower in ALIASES:
            cleaned_to_canonical[val] = ALIASES[val_lower]
            continue
            
        # 2. Check substring/prefix match against standards (e.g. "Admin" in "Administration")
        prefix_matched = False
        for std in standards:
            if std.lower().startswith(val_lower) and len(val_lower) >= 4:
                cleaned_to_canonical[val] = std
                prefix_matched = True
                break
        if prefix_matched:
            continue

        # 3. Fallback to fuzzy matching
        matches = difflib.get_close_matches(val, canonicals, n=1, cutoff=cutoff)
        if matches:
            canonical = matches[0]
            if canonical not in standards and len(val) > len(canonical):
                for k in list(cleaned_to_canonical.keys()):
                    if cleaned_to_canonical[k] == canonical:
                        cleaned_to_canonical[k] = val
                canonicals.remove(canonical)
                canonicals.append(val)
                canonical = val
            cleaned_to_canonical[val] = canonical
        else:
            canonicals.append(val)
            cleaned_to_canonical[val] = val

    final_mapping: Dict[str, str] = {}
    for original, cleaned in cleaned_map.items():
        final_mapping[original] = cleaned_to_canonical.get(cleaned, cleaned)

    return final_mapping

class ExcelReader:
    """
    ExcelReader handles reading, validating, and generating quality reports
    for Headcount and Leavers Excel files.
    """
    def __init__(self, db_helper: Optional[DBHelper] = None):
        self.db_helper = db_helper or DBHelper()

    @staticmethod
    def extract_month_from_filename(filename: str) -> str:
        """
        Extracts month from filename matching patterns like YYYY_MM or YYYY-MM.
        e.g., 'headcount_2026_06.xlsx' -> '2026-06'
        """
        match = re.search(r"(\d{4})[-_](\d{2})", filename)
        if not match:
            raise ValueError(
                f"Could not extract month (YYYY-MM) from filename '{filename}'. "
                f"Please ensure file name contains year and month (e.g., headcount_2026_06.xlsx)."
            )
        year, month = match.groups()
        # Validate month range
        if not (1 <= int(month) <= 12):
            raise ValueError(f"Invalid month extracted: {month} from file {filename}")
        return f"{year}-{month}"

    def parse_and_validate_headcount(self, file_path: Path) -> Dict[str, Any]:
        """
        Reads and validates a Headcount Excel file.
        Returns a Data Quality Report dictionary.
        """
        file_path = Path(file_path)
        report = {
            "file_path": str(file_path),
            "file_name": file_path.name,
            "file_type": "headcount",
            "record_month": None,
            "is_valid": True,
            "errors": [],
            "warnings": [],
            "total_rows": 0,
            "valid_rows_count": 0,
            "data": []
        }

        # 1. Extract Month
        try:
            record_month = self.extract_month_from_filename(file_path.name)
            report["record_month"] = record_month
        except ValueError as e:
            report["is_valid"] = False
            report["errors"].append({"row": None, "column": "Filename", "message": str(e)})
            logger.error(f"Filename validation failed for {file_path.name}: {e}")
            return report

        # 2. Read Excel File
        try:
            df = pd.read_excel(file_path)
            report["total_rows"] = len(df)
        except Exception as e:
            report["is_valid"] = False
            report["errors"].append({"row": None, "column": "File", "message": f"Failed to read Excel file: {e}"})
            logger.error(f"Failed to read file {file_path}: {e}", exc_info=True)
            return report

        # 3. Validate Columns
        actual_cols = [str(c).strip() for c in df.columns]
        missing_cols = [col for col in EXPECTED_HEADCOUNT_COLUMNS if col not in actual_cols]
        if missing_cols:
            report["is_valid"] = False
            report["errors"].append({
                "row": None,
                "column": "Columns",
                "message": f"Missing expected columns: {', '.join(missing_cols)}"
            })
            logger.error(f"Column validation failed for {file_path.name}. Missing: {missing_cols}")
            return report

        # Re-index to ensure correct columns and strip string data
        df.columns = actual_cols
        df = df[EXPECTED_HEADCOUNT_COLUMNS]

        valid_rows = []
        for idx, row in df.iterrows():
            row_num = idx + 2  # Excel row is 1-indexed and has header row
            project = row["Project"]
            headcount = row["Headcount"]
            row_has_error = False

            # Check Project Name
            if pd.isna(project) or str(project).strip() == "":
                report["errors"].append({
                    "row": row_num,
                    "column": "Project",
                    "value": str(project),
                    "message": "Project name cannot be empty."
                })
                row_has_error = True
            else:
                project = str(project).strip()

            # Check Headcount
            if pd.isna(headcount):
                report["errors"].append({
                    "row": row_num,
                    "column": "Headcount",
                    "value": str(headcount),
                    "message": "Headcount cannot be null."
                })
                row_has_error = True
            else:
                try:
                    hc_val = float(headcount)
                    if not hc_val.is_integer() or hc_val < 0:
                        report["errors"].append({
                            "row": row_num,
                            "column": "Headcount",
                            "value": str(headcount),
                            "message": f"Headcount must be a non-negative integer. Found: {headcount}"
                        })
                        row_has_error = True
                    else:
                        headcount = int(hc_val)
                except (ValueError, TypeError):
                    report["errors"].append({
                        "row": row_num,
                        "column": "Headcount",
                        "value": str(headcount),
                        "message": f"Headcount must be a number. Found: {headcount}"
                    })
                    row_has_error = True

            if not row_has_error:
                valid_rows.append({
                    "project": project,
                    "record_month": record_month,
                    "headcount": headcount
                })

        import streamlit as st
        st.write(f"🔍 Debug Info: parsed valid_rows count: {len(valid_rows)}")

        # ── FUZZY NORMALISATION & STRICT VALIDATION of Project ───────────────────
        _registry = load_standards_registry()  # Re-read from disk each time
        raw_projects = [r["project"] for r in valid_rows]
        project_standards = _registry.get("projects", [])
        st.write(f"🔍 Debug Info: STANDARDS_REGISTRY projects: {project_standards}")
        proj_map = normalize_field_values(raw_projects, standards=project_standards)
        
        final_valid_rows = []
        for rec in valid_rows:
            orig = rec["project"]
            canon = proj_map[orig]
            rec["project"] = canon
            
            # Strict validation check
            if canon not in project_standards:
                report["errors"].append({
                    "row": None,  # Applies to all rows with this value
                    "column": "Project",
                    "value": str(orig),
                    "message": f"Unrecognized Project '{orig}'. Please correct the Excel file, or add this project to System Configurations."
                })
            else:
                final_valid_rows.append(rec)
                
            if orig != canon and canon in project_standards:
                report["warnings"].append({
                    "row": None,
                    "column": "Project",
                    "value": str(orig),
                    "message": f"Auto-corrected to '{canon}'"
                })

        st.write(f"🔍 Debug Info: final_valid_rows count: {len(final_valid_rows)} | errors count: {len(report['errors'])}")
        report["valid_rows_count"] = len(final_valid_rows)
        report["data"] = final_valid_rows

        # If there are any blocking errors, mark document as invalid
        if len(report["errors"]) > 0:
            report["is_valid"] = False

        return report

    def parse_and_validate_leavers(self, file_path: Path) -> Dict[str, Any]:
        """
        Reads and validates a Leavers Excel file.
        Applies fuzzy normalization on Department and Position fields before returning.
        Returns a Data Quality Report dictionary.
        """
        file_path = Path(file_path)
        report = {
            "file_path": str(file_path),
            "file_name": file_path.name,
            "file_type": "leavers",
            "record_month": None,
            "is_valid": True,
            "errors": [],
            "warnings": [],
            "normalizations": [],  # NEW: tracks auto-corrected dept/position names
            "total_rows": 0,
            "valid_rows_count": 0,
            "data": []
        }

        # 1. Extract Month
        try:
            record_month = self.extract_month_from_filename(file_path.name)
            report["record_month"] = record_month
        except ValueError as e:
            report["is_valid"] = False
            report["errors"].append({"row": None, "column": "Filename", "message": str(e)})
            logger.error(f"Filename validation failed for {file_path.name}: {e}")
            return report

        # 2. Read Excel File
        try:
            df = pd.read_excel(file_path)
            report["total_rows"] = len(df)
        except Exception as e:
            report["is_valid"] = False
            report["errors"].append({"row": None, "column": "File", "message": f"Failed to read Excel file: {e}"})
            logger.error(f"Failed to read file {file_path}: {e}", exc_info=True)
            return report

        # 3. Validate Columns
        actual_cols = [str(c).strip() for c in df.columns]
        missing_cols = [col for col in EXPECTED_LEAVERS_COLUMNS if col not in actual_cols]
        if missing_cols:
            report["is_valid"] = False
            report["errors"].append({
                "row": None,
                "column": "Columns",
                "message": f"Missing expected columns: {', '.join(missing_cols)}"
            })
            logger.error(f"Column validation failed for {file_path.name}. Missing: {missing_cols}")
            return report

        # Re-index to ensure correct columns
        df.columns = actual_cols
        df = df[EXPECTED_LEAVERS_COLUMNS]

        seen_emp_ids = set()
        valid_rows = []

        for idx, row in df.iterrows():
            row_num = idx + 2
            row_has_error = False

            # Extract fields
            emp_id = row["Employee ID"]
            emp_name = row["Employee Name"]
            project = row["Project"]
            department = row["Department"]
            position = row["Position"]
            doj = row["Date of Joining"]
            dol = row["Date of Leaving"]
            length_of_service = row["Length of Service"]
            status = row.get("Status", "Resigned")
            reason = row["Reason"]

            # Validate Employee ID
            if pd.isna(emp_id) or str(emp_id).strip() == "":
                report["errors"].append({
                    "row": row_num,
                    "column": "Employee ID",
                    "value": str(emp_id),
                    "message": "Employee ID cannot be empty."
                })
                row_has_error = True
            else:
                emp_id = str(emp_id).strip()
                # Check for duplicates in current file
                if emp_id in seen_emp_ids:
                    report["errors"].append({
                        "row": row_num,
                        "column": "Employee ID",
                        "value": emp_id,
                        "message": f"Duplicate Employee ID within file: {emp_id}"
                    })
                    row_has_error = True
                else:
                    seen_emp_ids.add(emp_id)
                    
                # Check duplicate against DB
                try:
                    if self.db_helper.employee_id_exists(emp_id):
                        report["warnings"].append({
                            "row": row_num,
                            "column": "Employee ID",
                            "value": emp_id,
                            "message": f"Employee ID {emp_id} already exists in DB. Importing will update the record."
                        })
                except Exception as e:
                    logger.warning(f"Failed database check for Employee ID duplicate: {e}")

            # Validate Employee Name, Project, Department, Position
            for col_name, val in [("Employee Name", emp_name), ("Project", project), ("Department", department), ("Position", position)]:
                if pd.isna(val) or str(val).strip() == "":
                    report["errors"].append({
                        "row": row_num,
                        "column": col_name,
                        "value": str(val),
                        "message": f"{col_name} cannot be empty."
                    })
                    row_has_error = True

            # Validate Dates
            parsed_doj, parsed_dol = None, None
            
            # Helper to parse date
            def parse_date(date_val: Any, col_name: str) -> Optional[datetime]:
                if pd.isna(date_val):
                    report["errors"].append({
                        "row": row_num,
                        "column": col_name,
                        "value": str(date_val),
                        "message": f"{col_name} is missing."
                    })
                    return None
                if isinstance(date_val, datetime):
                    return date_val
                if isinstance(date_val, pd.Timestamp):
                    return date_val.to_pydatetime()
                # Try parsing string
                date_str = str(date_val).strip()
                for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%Y/%m/%d", "%d-%m-%Y"):
                    try:
                        return datetime.strptime(date_str, fmt)
                    except ValueError:
                        continue
                report["errors"].append({
                    "row": row_num,
                    "column": col_name,
                    "value": str(date_val),
                    "message": f"Could not parse {col_name} as date. Recommended format: YYYY-MM-DD"
                })
                return None

            parsed_doj = parse_date(doj, "Date of Joining")
            parsed_dol = parse_date(dol, "Date of Leaving")

            if parsed_doj is None or parsed_dol is None:
                row_has_error = True
            else:
                if parsed_dol < parsed_doj:
                    report["errors"].append({
                        "row": row_num,
                        "column": "Date of Leaving",
                        "value": f"DOJ: {parsed_doj.strftime('%Y-%m-%d')}, DOL: {parsed_dol.strftime('%Y-%m-%d')}",
                        "message": "Date of Leaving cannot be before Date of Joining."
                    })
                    row_has_error = True

            # Validate Length of Service
            parsed_service_months = None
            if pd.isna(length_of_service):
                report["warnings"].append({
                    "row": row_num,
                    "column": "Length of Service",
                    "value": str(length_of_service),
                    "message": "Length of Service is empty. It will be auto-calculated."
                })
                # Calculated value if dates are valid
                if parsed_doj and parsed_dol:
                    delta_days = (parsed_dol - parsed_doj).days
                    parsed_service_months = round(delta_days / 30.4375, 2)
            else:
                try:
                    parsed_service_months = float(length_of_service)
                    if parsed_service_months < 0:
                        report["errors"].append({
                            "row": row_num,
                            "column": "Length of Service",
                            "value": str(length_of_service),
                            "message": "Length of Service cannot be negative."
                        })
                        row_has_error = True
                    # Cross verify value with date difference (warn if different by > 1 month)
                    if parsed_doj and parsed_dol:
                        expected_months = (parsed_dol - parsed_doj).days / 30.4375
                        if abs(parsed_service_months - expected_months) > 1.5:
                            report["warnings"].append({
                                "row": row_num,
                                "column": "Length of Service",
                                "value": f"Reported: {parsed_service_months}, Expected: {expected_months:.2f}",
                                "message": f"Reported service length significantly differs from date interval."
                            })
                except (ValueError, TypeError):
                    report["errors"].append({
                        "row": row_num,
                        "column": "Length of Service",
                        "value": str(length_of_service),
                        "message": f"Length of Service must be a number. Found: {length_of_service}"
                    })
                    row_has_error = True

            # Reason Validation (warn if missing/empty)
            clean_reason = ""
            if pd.isna(reason) or str(reason).strip() == "":
                report["warnings"].append({
                    "row": row_num,
                    "column": "Reason",
                    "value": str(reason),
                    "message": "Resignation reason is empty."
                })
                clean_reason = "Not Specified"
            else:
                clean_reason = str(reason).strip()

            if not row_has_error:
                # Store dates in ISO format for DB
                iso_doj = parsed_doj.strftime("%Y-%m-%d")
                iso_dol = parsed_dol.strftime("%Y-%m-%d")
                
                valid_rows.append({
                    "employee_id": emp_id,
                    "employee_name": str(emp_name).strip(),
                    "project": str(project).strip(),
                    "department": str(department).strip(),
                    "position": str(position).strip(),
                    "date_of_joining": iso_doj,
                    "date_of_leaving": iso_dol,
                    "length_of_service_months": parsed_service_months,
                    "status": str(status).strip() if pd.notna(status) else "Resigned",
                    "original_reason": clean_reason,
                    "record_month": record_month
                })

        report["valid_rows_count"] = len(valid_rows)
        report["data"] = valid_rows
        
        # ── FUZZY NORMALISATION & STRICT VALIDATION ───────────────────
        raw_projects = [r["project"] for r in valid_rows]
        raw_depts = [r["department"] for r in valid_rows]
        raw_positions = [r["position"] for r in valid_rows]

        _registry = load_standards_registry()  # Re-read from disk each time
        proj_standards = _registry.get("projects", [])
        dept_standards = _registry.get("departments", [])
        pos_standards = _registry.get("positions", [])

        proj_map = normalize_field_values(raw_projects, standards=proj_standards)
        dept_map = normalize_field_values(raw_depts, standards=dept_standards)
        pos_map = normalize_field_values(raw_positions, standards=pos_standards)

        final_valid_rows = []
        for rec in valid_rows:
            orig_proj = rec["project"]
            canon_proj = proj_map.get(orig_proj, orig_proj)
            rec["project"] = canon_proj
            
            orig_dept = rec["department"]
            canon_dept = dept_map.get(orig_dept, orig_dept)
            rec["department"] = canon_dept

            orig_pos = rec["position"]
            canon_pos = pos_map.get(orig_pos, orig_pos)
            rec["position"] = canon_pos

            # Validation checks
            is_row_valid = True
            
            if canon_proj not in proj_standards:
                report["errors"].append({
                    "row": None, "column": "Project", "value": orig_proj,
                    "message": f"Unrecognized Project '{orig_proj}'. Please correct or add to System Standards."
                })
                is_row_valid = False
                
            if canon_dept not in dept_standards:
                report["errors"].append({
                    "row": None, "column": "Department", "value": orig_dept,
                    "message": f"Unrecognized Department '{orig_dept}'. Please correct or add to System Standards."
                })
                is_row_valid = False
                
            if canon_pos not in pos_standards:
                report["errors"].append({
                    "row": None, "column": "Position", "value": orig_pos,
                    "message": f"Unrecognized Position '{orig_pos}'. Please correct or add to System Standards."
                })
                is_row_valid = False

            if is_row_valid:
                final_valid_rows.append(rec)

            # Log warnings/normalizations
            if canon_proj != orig_proj and canon_proj in proj_standards:
                report["warnings"].append({"row": None, "column": "Project", "value": orig_proj, "message": f"Auto-corrected to '{canon_proj}'"})
            if canon_dept != orig_dept and canon_dept in dept_standards:
                report["warnings"].append({"row": None, "column": "Department", "value": orig_dept, "message": f"Auto-corrected to '{canon_dept}'"})
            if canon_pos != orig_pos and canon_pos in pos_standards:
                report["warnings"].append({"row": None, "column": "Position", "value": orig_pos, "message": f"Auto-corrected to '{canon_pos}'"})

        report["valid_rows_count"] = len(final_valid_rows)
        report["data"] = final_valid_rows

        # If there are any blocking errors, mark document as invalid
        if len(report["errors"]) > 0:
            report["is_valid"] = False

        return report
