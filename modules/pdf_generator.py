import os
import logging
from datetime import datetime
import pandas as pd
from typing import Dict, Any, List, Optional
from pathlib import Path

from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, 
    PageBreak, KeepTogether, HRFlowable, ListFlowable, ListItem
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
from reportlab.pdfgen import canvas
from reportlab.graphics.shapes import Drawing, Rect, String, Line, Circle, Wedge
from reportlab.graphics.charts.piecharts import Pie
from reportlab.graphics.charts.legends import Legend

from config.settings import PDF_REPORTS_DIR
from database.db_helper import DBHelper
from modules.turnover_engine import TurnoverEngine
from modules.resignation_analytics import ResignationAnalytics

from dateutil.relativedelta import relativedelta

logger = logging.getLogger(__name__)

# ─── CORPORATE COLOR PALETTE ───────────────────────────────────────────
BRAND_PRIMARY     = "#0B3D54"   # Deep navy teal
BRAND_SECONDARY   = "#1A7A8A"   # Bright teal accent
BRAND_ACCENT      = "#F5A623"   # Gold accent for highlights
BRAND_DARK        = "#0A1929"   # Near-black for headings
BRAND_TEXT         = "#2D3748"   # Body text
BRAND_TEXT_LIGHT   = "#718096"   # Secondary text
BRAND_BG_LIGHT    = "#F7FAFC"   # Light background
BRAND_BG_ALT      = "#EBF4F8"   # Alternate row / section bg
BRAND_BORDER      = "#CBD5E0"   # Subtle borders
BRAND_SUCCESS      = "#276749"   # Green for positive
BRAND_DANGER       = "#C53030"   # Red for negative / risk
BRAND_WHITE        = "#FFFFFF"

CHART_PALETTE = [
    "#0B3D54", "#1A7A8A", "#2B6CB0", "#6B46C1", 
    "#C05621", "#276749", "#9B2C2C", "#744210",
    "#553C9A", "#285E61", "#702459", "#1A365D",
    "#9C4221", "#4A5568"
]


class NumberedCanvas(canvas.Canvas):
    """
    Two-pass canvas for corporate headers, footers with page numbers,
    and a branded cover page with decorative elements.
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_page_decorations(num_pages)
            super().showPage()
        super().save()

    def draw_page_decorations(self, page_count):
        self.saveState()
        w, h = letter
        
        primary = colors.HexColor(BRAND_PRIMARY)
        secondary = colors.HexColor(BRAND_SECONDARY)
        accent = colors.HexColor(BRAND_ACCENT)
        text_color = colors.HexColor(BRAND_TEXT_LIGHT)
        
        if self._pageNumber == 1:
            # ─── COVER PAGE DESIGN ───
            # Top accent bar (full width)
            self.setFillColor(primary)
            self.rect(0, h - 8, w, 8, fill=True, stroke=False)
            
            # Bottom accent bar
            self.setFillColor(secondary)
            self.rect(0, 0, w, 4, fill=True, stroke=False)
            
            # Left side accent strip
            self.setFillColor(accent)
            self.rect(0, 0, 5, h, fill=True, stroke=False)
            
            # Footer on cover
            self.setFont("Helvetica", 7.5)
            self.setFillColor(text_color)
            self.drawString(54, 28, f"Generated on: {datetime.now().strftime('%B %d, %Y at %H:%M')}")
            self.drawRightString(w - 54, 28, "CONFIDENTIAL — For Internal Management Use Only")
        else:
            # ─── INNER PAGES ───
            # Top thin accent bar
            self.setFillColor(primary)
            self.rect(0, h - 4, w, 4, fill=True, stroke=False)
            
            # Header text
            self.setFont("Helvetica-Bold", 7)
            self.setFillColor(primary)
            self.drawString(54, h - 22, "MONAL GROUP  |  TURNOVER REPORT")
            self.drawRightString(w - 54, h - 22, "CONFIDENTIAL")
            
            # Header line
            self.setStrokeColor(colors.HexColor(BRAND_BORDER))
            self.setLineWidth(0.5)
            self.line(54, h - 28, w - 54, h - 28)
            
            # Footer line
            self.line(54, 46, w - 54, 46)
            
            # Footer text
            self.setFont("Helvetica", 7.5)
            self.setFillColor(text_color)
            self.drawString(54, 32, f"Generated: {datetime.now().strftime('%Y-%m-%d')}")
            
            # Page number (centered)
            page_str = f"— {self._pageNumber} / {page_count} —"
            self.setFont("Helvetica", 8)
            self.setFillColor(primary)
            self.drawCentredString(w / 2, 32, page_str)
            
            self.drawRightString(w - 54, 32, "Monal Group HR Analytics")

        self.restoreState()


class PDFReportGenerator:
    """
    Generates premium, executive-grade PDF reports for Monal Group management.
    Includes branded cover page, executive summary, project analysis,
    attrition drivers, and visual charts.
    """
    def __init__(self, db_helper: Optional[DBHelper] = None):
        self.db_helper = db_helper or DBHelper()
        self.turnover_engine = TurnoverEngine(db_helper=self.db_helper)
        self.resignation_analytics = ResignationAnalytics(db_helper=self.db_helper)
        
        # Color objects
        self.c_primary = colors.HexColor(BRAND_PRIMARY)
        self.c_secondary = colors.HexColor(BRAND_SECONDARY)
        self.c_accent = colors.HexColor(BRAND_ACCENT)
        self.c_dark = colors.HexColor(BRAND_DARK)
        self.c_text = colors.HexColor(BRAND_TEXT)
        self.c_text_light = colors.HexColor(BRAND_TEXT_LIGHT)
        self.c_bg = colors.HexColor(BRAND_BG_LIGHT)
        self.c_bg_alt = colors.HexColor(BRAND_BG_ALT)
        self.c_border = colors.HexColor(BRAND_BORDER)
        self.c_success = colors.HexColor(BRAND_SUCCESS)
        self.c_danger = colors.HexColor(BRAND_DANGER)

    # ─── CHART BUILDERS ─────────────────────────────────────────────────

    def _build_horizontal_bar_chart(self, labels, values, title="", width=480, 
                                     bar_height=20, max_label_width=130):
        """Premium horizontal bar chart with gradient-like multi-tone bars."""
        # Safe limit to prevent Flowable too large error on PDF generation
        if len(labels) > 15:
            labels = labels[:15]
            values = values[:15]
            title += " (Top 15)"

        spacing = 6
        chart_height = len(labels) * (bar_height + spacing) + 55
        d = Drawing(width, chart_height)
        
        # Background card
        d.add(Rect(0, 0, width, chart_height, 
                   fillColor=colors.HexColor("#FAFBFC"), strokeColor=colors.HexColor("#E8EDF2"),
                   strokeWidth=0.5, rx=4))
        
        # Title
        d.add(String(width / 2, chart_height - 18, title,
                     textAnchor='middle', fontName='Helvetica-Bold', fontSize=10,
                     fillColor=self.c_dark))
        
        # Subtle title underline
        d.add(Line(width/2 - 80, chart_height - 22, width/2 + 80, chart_height - 22,
                   strokeColor=self.c_accent, strokeWidth=1.5))
        
        max_val = max(values) if values and max(values) > 0 else 1
        bar_area_width = width - max_label_width - 70
        
        palette = [colors.HexColor(c) for c in CHART_PALETTE]
        y_start = chart_height - 42
        
        for i, (label, val) in enumerate(zip(labels, values)):
            y = y_start - i * (bar_height + spacing)
            bar_w = max((val / max_val) * bar_area_width, 2) if max_val > 0 else 2
            c = palette[i % len(palette)]
            
            display_label = label if len(str(label)) <= 20 else str(label)[:18] + ".."
            
            # Subtle row background for even rows
            if i % 2 == 0:
                d.add(Rect(max_label_width - 5, y - 2, bar_area_width + 75, bar_height + 4,
                           fillColor=colors.HexColor("#F0F4F8"), strokeColor=None))
            
            # Label
            d.add(String(max_label_width - 8, y + bar_height / 2 - 4, str(display_label),
                         textAnchor='end', fontName='Helvetica', fontSize=8,
                         fillColor=self.c_text))
            
            # Bar shadow
            d.add(Rect(max_label_width + 1, y - 1, bar_w, bar_height,
                       fillColor=colors.HexColor("#D4D4D4"), strokeColor=None))
            
            # Main bar
            d.add(Rect(max_label_width, y, bar_w, bar_height,
                       fillColor=c, strokeColor=None))
            
            # Highlight strip on bar (top 3px lighter effect)
            lighter = colors.HexColor(CHART_PALETTE[i % len(CHART_PALETTE)])
            d.add(Rect(max_label_width, y + bar_height - 3, bar_w, 3,
                       fillColor=colors.Color(lighter.red, lighter.green, lighter.blue, 0.5),
                       strokeColor=None))
            
            # Value label with unit
            val_str = f"{val:,.1f}%" if isinstance(val, float) else str(val)
            d.add(String(max_label_width + bar_w + 8, y + bar_height / 2 - 4, val_str,
                         textAnchor='start', fontName='Helvetica-Bold', fontSize=8.5,
                         fillColor=self.c_dark))
        
        return d

    def _build_donut_chart(self, labels, values, title="", width=480, height=220):
        """Premium donut chart with legend panel."""
        d = Drawing(width, height)
        
        # Background card
        d.add(Rect(0, 0, width, height,
                   fillColor=colors.HexColor("#FAFBFC"), strokeColor=colors.HexColor("#E8EDF2"),
                   strokeWidth=0.5, rx=4))
        
        # Title
        d.add(String(width / 2, height - 16, title,
                     textAnchor='middle', fontName='Helvetica-Bold', fontSize=10,
                     fillColor=self.c_dark))
        d.add(Line(width/2 - 80, height - 20, width/2 + 80, height - 20,
                   strokeColor=self.c_accent, strokeWidth=1.5))
        
        # Donut chart
        pie = Pie()
        pie.x = 50
        pie.y = 20
        pie.width = 140
        pie.height = 140
        pie.data = values
        pie.labels = None
        pie.simpleLabels = 0
        pie.sideLabels = 0
        pie.innerRadiusFraction = 0.45  # Donut hole
        
        palette = [colors.HexColor(c) for c in CHART_PALETTE]
        for i in range(len(values)):
            pie.slices[i].fillColor = palette[i % len(palette)]
            pie.slices[i].strokeColor = colors.white
            pie.slices[i].strokeWidth = 2
            pie.slices[i].popout = 2 if i == 0 else 0  # Slightly pop the largest
        
        d.add(pie)
        
        # Center total label
        total = sum(values)
        d.add(String(120, 95, str(total), textAnchor='middle',
                     fontName='Helvetica-Bold', fontSize=16, fillColor=self.c_dark))
        d.add(String(120, 82, "Total", textAnchor='middle',
                     fontName='Helvetica', fontSize=8, fillColor=self.c_text_light))
        
        # Legend panel
        legend = Legend()
        legend.x = 240
        legend.y = height - 45
        legend.dx = 10
        legend.dy = 10
        legend.deltax = 0
        legend.deltay = 16
        legend.fontName = 'Helvetica'
        legend.fontSize = 8
        legend.alignment = 'right'
        legend.columnMaximum = 10
        
        legend_items = []
        for i, (lbl, val) in enumerate(zip(labels, values)):
            c = palette[i % len(palette)]
            pct = round(val / total * 100, 1) if total > 0 else 0
            display = str(lbl) if len(str(lbl)) <= 22 else str(lbl)[:20] + ".."
            legend_items.append((c, f"{display}  —  {val} ({pct}%)"))
        
        legend.colorNamePairs = legend_items
        d.add(legend)
        
        return d

    def _build_kpi_card_row(self, kpis, width=480):
        """Builds a row of KPI metric cards as a Drawing."""
        card_count = len(kpis)
        card_w = (width - (card_count - 1) * 8) / card_count
        card_h = 60
        d = Drawing(width, card_h + 10)
        
        palette = [self.c_primary, self.c_secondary, colors.HexColor("#6B46C1"), 
                   self.c_danger, self.c_success]
        
        for i, kpi in enumerate(kpis):
            x = i * (card_w + 8)
            c = palette[i % len(palette)]
            
            # Card background
            d.add(Rect(x, 0, card_w, card_h,
                       fillColor=colors.white, strokeColor=self.c_border, strokeWidth=0.5))
            
            # Top accent line
            d.add(Rect(x, card_h - 3, card_w, 3, fillColor=c, strokeColor=None))
            
            # Value
            d.add(String(x + card_w / 2, card_h - 25, str(kpi["value"]),
                         textAnchor='middle', fontName='Helvetica-Bold', fontSize=16,
                         fillColor=c))
            
            # Label
            d.add(String(x + card_w / 2, 10, kpi["label"],
                         textAnchor='middle', fontName='Helvetica', fontSize=7,
                         fillColor=self.c_text_light))
        
        return d

    # ─── SECTION DIVIDER ─────────────────────────────────────────────────

    def _section_divider(self):
        """Creates a branded section divider line."""
        d = Drawing(480, 12)
        d.add(Line(0, 6, 480, 6, strokeColor=self.c_border, strokeWidth=0.4))
        d.add(Rect(0, 4, 60, 4, fillColor=self.c_accent, strokeColor=None))
        return d

    # ─── HELPER ──────────────────────────────────────────────────────────

    def _calculate_previous_range(self, start_month: str, end_month: str):
        try:
            start_dt = datetime.strptime(start_month, "%Y-%m")
            end_dt = datetime.strptime(end_month, "%Y-%m")
        except ValueError:
            return start_month, end_month

        period_months = (end_dt.year - start_dt.year) * 12 + (end_dt.month - start_dt.month) + 1
        prev_end_dt = start_dt - relativedelta(months=1)
        prev_start_dt = prev_end_dt - relativedelta(months=period_months - 1)
        return prev_start_dt.strftime("%Y-%m"), prev_end_dt.strftime("%Y-%m")

    @staticmethod
    def _clean_text(text: str) -> str:
        """Escape XML entities and convert markdown bold (**) to <b> tags."""
        escaped = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        parts = escaped.split("**")
        res = []
        for idx, part in enumerate(parts):
            if idx % 2 == 1:
                res.append(f"<b>{part}</b>")
            else:
                res.append(part)
        return "".join(res)

    # ─── MAIN REPORT GENERATOR ───────────────────────────────────────────

    def generate_report(
        self, 
        start_month: str, 
        end_month: str, 
        period_label: str,
        exec_summary_text: str,
        output_filename: Optional[str] = None
    ) -> Path:
        """Creates the premium PDF report and saves it in reports/pdf."""
        if not output_filename:
            clean_label = period_label.replace(" ", "_").replace("→", "to").replace("/", "_")
            output_filename = f"Monal_Turnover_Report_{clean_label}.pdf"

        pdf_path = PDF_REPORTS_DIR / output_filename
        
        doc = SimpleDocTemplate(
            str(pdf_path),
            pagesize=letter,
            leftMargin=54,
            rightMargin=54,
            topMargin=50,
            bottomMargin=60
        )

        styles = getSampleStyleSheet()
        
        # ─── STYLE DEFINITIONS ────────────────────────────────────────────
        
        cover_title = ParagraphStyle(
            "CoverTitle", parent=styles["Title"],
            fontName="Helvetica-Bold", fontSize=30, leading=36,
            textColor=self.c_primary, alignment=TA_LEFT, spaceAfter=6
        )
        
        cover_subtitle = ParagraphStyle(
            "CoverSubtitle", parent=styles["Normal"],
            fontName="Helvetica", fontSize=13, leading=17,
            textColor=self.c_secondary, spaceAfter=4
        )
        
        cover_meta = ParagraphStyle(
            "CoverMeta", parent=styles["Normal"],
            fontName="Helvetica", fontSize=10, leading=14,
            textColor=self.c_text_light, spaceAfter=3
        )

        h1 = ParagraphStyle(
            "H1", parent=styles["Heading1"],
            fontName="Helvetica-Bold", fontSize=17, leading=22,
            textColor=self.c_primary, spaceBefore=12, spaceAfter=8
        )

        h2 = ParagraphStyle(
            "H2", parent=styles["Heading2"],
            fontName="Helvetica-Bold", fontSize=12, leading=16,
            textColor=self.c_dark, spaceBefore=10, spaceAfter=5
        )

        h3 = ParagraphStyle(
            "H3", parent=styles["Heading3"],
            fontName="Helvetica-Bold", fontSize=10, leading=13,
            textColor=self.c_secondary, spaceBefore=8, spaceAfter=4
        )

        body = ParagraphStyle(
            "Body", parent=styles["BodyText"],
            fontName="Helvetica", fontSize=9.5, leading=14,
            textColor=self.c_text, spaceAfter=7
        )

        body_small = ParagraphStyle(
            "BodySmall", parent=body,
            fontSize=8.5, leading=12, spaceAfter=4,
            textColor=self.c_text_light
        )
        
        list_item_style = ParagraphStyle(
            "ListItem", parent=body,
            leftIndent=16, spaceAfter=3
        )

        numbered_style = ParagraphStyle(
            "NumberedItem", parent=body,
            leftIndent=16, spaceAfter=3
        )
        
        callout_style = ParagraphStyle(
            "Callout", parent=body,
            fontName="Helvetica-Oblique", fontSize=9, leading=13,
            textColor=self.c_secondary, leftIndent=10,
            borderColor=self.c_secondary, borderWidth=0,
            spaceBefore=6, spaceAfter=8
        )

        th = ParagraphStyle(
            "TH", parent=styles["Normal"],
            fontName="Helvetica-Bold", fontSize=8.5, leading=11,
            textColor=colors.white, alignment=TA_LEFT
        )

        td = ParagraphStyle(
            "TD", parent=styles["Normal"],
            fontName="Helvetica", fontSize=8, leading=11,
            textColor=self.c_text
        )

        td_bold = ParagraphStyle(
            "TDBold", parent=td,
            fontName="Helvetica-Bold"
        )

        td_danger = ParagraphStyle(
            "TDDanger", parent=td,
            textColor=self.c_danger, fontName="Helvetica-Bold"
        )

        td_success = ParagraphStyle(
            "TDSuccess", parent=td,
            textColor=self.c_success, fontName="Helvetica-Bold"
        )

        # Table style template
        base_table_style = TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), self.c_primary),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('TOPPADDING', (0, 0), (-1, -1), 6),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
            ('LEFTPADDING', (0, 0), (-1, -1), 8),
            ('RIGHTPADDING', (0, 0), (-1, -1), 8),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor(BRAND_BG_ALT)]),
            ('LINEBELOW', (0, 0), (-1, 0), 1.5, self.c_accent),
            ('GRID', (0, 1), (-1, -1), 0.4, self.c_border),
            ('LINEBELOW', (0, -1), (-1, -1), 0.8, self.c_primary),
        ])

        story = []

        # ═══════════════════════════════════════════════════════════════════
        # PAGE 1: COVER PAGE
        # ═══════════════════════════════════════════════════════════════════
        story.append(Spacer(1, 100))
        
        # Branded accent line
        accent_drawing = Drawing(480, 6)
        accent_drawing.add(Rect(0, 0, 80, 4, fillColor=self.c_accent, strokeColor=None))
        accent_drawing.add(Rect(84, 0, 396, 1, fillColor=self.c_border, strokeColor=None))
        story.append(accent_drawing)
        story.append(Spacer(1, 18))
        
        story.append(Paragraph("MONAL GROUP", ParagraphStyle(
            "CoverOrg", parent=cover_meta, fontName="Helvetica-Bold", 
            fontSize=11, textColor=self.c_text_light, letterSpacing=3
        )))
        story.append(Spacer(1, 6))
        story.append(Paragraph("Turnover Report", cover_title))
        story.append(Paragraph("Workforce Attrition Analysis &amp; Strategic HR Insights", cover_subtitle))
        
        story.append(Spacer(1, 30))
        
        # Cover metadata block
        meta_data = [
            ["Reporting Period:", period_label],
            ["Report Type:", "Corporate Turnover & Attrition Analysis"],
            ["Prepared By:", "Moazzam Baig"],
            ["Date Generated:", datetime.now().strftime("%B %d, %Y")],
            ["Classification:", "Confidential"]
        ]
        
        for label, value in meta_data:
            story.append(Paragraph(
                f"<b>{label}</b> &nbsp;&nbsp;{self._clean_text(value)}", cover_meta
            ))
        
        story.append(Spacer(1, 50))
        
        # Bottom accent on cover
        bottom_accent = Drawing(480, 6)
        bottom_accent.add(Rect(0, 2, 480, 1, fillColor=self.c_border, strokeColor=None))
        bottom_accent.add(Rect(0, 0, 80, 4, fillColor=self.c_accent, strokeColor=None))
        story.append(bottom_accent)
        
        story.append(Spacer(1, 20))
        story.append(Paragraph(
            "<i>This report contains corporate turnover analysis for the Monal Group. "
            "All figures are derived from uploaded headcount and leavers data. "
            "Charts and insights reflect the selected reporting period.</i>",
            body_small
        ))

        story.append(PageBreak())

        # ═══════════════════════════════════════════════════════════════════
        # COMPUTE ALL DATA UPFRONT
        # ═══════════════════════════════════════════════════════════════════
        all_projects = [p["name"] for p in self.db_helper.get_projects()]
        prev_start, prev_end = self._calculate_previous_range(start_month, end_month)
        label_curr = period_label
        label_prev = f"{prev_start} → {prev_end}" if start_month != end_month else prev_end
        
        leavers_raw = self.db_helper.get_leavers_summary(start_month=start_month, end_month=end_month)
        df_lv = pd.DataFrame(leavers_raw)
        
        hc_data = self.db_helper.get_headcount_history()
        df_hc = pd.DataFrame(hc_data)
        
        tot_dep = len(df_lv) if not df_lv.empty else 0
        
        # Overall turnover
        overall_turnover = self.turnover_engine.calculate_overall_turnover(start_month, end_month)
        prev_turnover = self.turnover_engine.calculate_overall_turnover(prev_start, prev_end)
        turnover_change = round(overall_turnover - prev_turnover, 2)
        
        # Headcount
        total_headcount = int(df_hc[df_hc["record_month"].between(start_month, end_month)]["headcount"].sum()) if not df_hc.empty else 0

        # ═══════════════════════════════════════════════════════════════════
        # PAGE 2: EXECUTIVE SUMMARY
        # ═══════════════════════════════════════════════════════════════════
        story.append(Paragraph("1 &nbsp;&nbsp; Executive Summary", h1))
        story.append(self._section_divider())
        story.append(Spacer(1, 6))
        
        # KPI Cards
        change_str = f"+{turnover_change}%" if turnover_change > 0 else f"{turnover_change}%"
        kpi_cards = self._build_kpi_card_row([
            {"label": "TOTAL DEPARTURES", "value": str(tot_dep)},
            {"label": "TURNOVER RATE", "value": f"{overall_turnover}%"},
            {"label": "VS PREVIOUS PERIOD", "value": change_str},
            {"label": "PROJECTS ANALYZED", "value": str(len(all_projects))},
        ])
        story.append(kpi_cards)
        story.append(Spacer(1, 14))
        
        # AI narrative
        summary_lines = exec_summary_text.split("\n")
        for line in summary_lines:
            line_str = line.strip()
            if not line_str:
                continue
            
            if line_str.startswith("#"):
                clean_header = self._clean_text(line_str.lstrip("#").strip())
                if not (clean_header.lower().startswith("executive summary") or 
                        clean_header.lower().startswith("1.")):
                    story.append(Paragraph(clean_header, h2))
            elif line_str.startswith("-") or line_str.startswith("*"):
                clean_item = self._clean_text(line_str.lstrip("-*").strip())
                story.append(Paragraph(f"&#8226; &nbsp;{clean_item}", list_item_style))
            elif len(line_str) > 1 and line_str[0].isdigit() and line_str[1] == '.':
                clean_line = self._clean_text(line_str)
                story.append(Paragraph(clean_line, numbered_style))
            else:
                clean_line = self._clean_text(line_str)
                story.append(Paragraph(clean_line, body))

        story.append(Spacer(1, 10))
        story.append(PageBreak())

        # ═══════════════════════════════════════════════════════════════════
        # PAGE 3: HEADCOUNT & NET CHANGE ANALYSIS
        # ═══════════════════════════════════════════════════════════════════
        story.append(Paragraph("2 &nbsp;&nbsp; Turnover Dashboard", h1))
        story.append(self._section_divider())
        story.append(Spacer(1, 4))
        story.append(Paragraph(
            f"The following analysis compares the active headcount at the end of <b>{self._clean_text(label_curr)}</b> "
            f"against the preceding period (<b>{self._clean_text(label_prev)}</b>).",
            body
        ))
        story.append(Spacer(1, 6))

        df_hc_curr = df_hc[df_hc["record_month"] == end_month]
        df_hc_prev = df_hc[df_hc["record_month"] == prev_end]
        curr_hc = int(df_hc_curr["headcount"].sum()) if not df_hc_curr.empty else 0
        prev_hc = int(df_hc_prev["headcount"].sum()) if not df_hc_prev.empty else 0
        net_change = curr_hc - prev_hc
        pct_change = round((net_change / prev_hc * 100), 1) if prev_hc > 0 else 0.0
        change_str = f"+{net_change} ({pct_change}%)" if net_change > 0 else f"{net_change} ({pct_change}%)"

        kpi_hc = self._build_kpi_card_row([
            {"label": f"HEADCOUNT ({end_month})", "value": str(curr_hc)},
            {"label": f"HEADCOUNT ({prev_end})", "value": str(prev_hc)},
            {"label": "NET CHANGE", "value": change_str},
        ])
        story.append(kpi_hc)
        story.append(Spacer(1, 14))

        # Project Headcount Table
        hc_table_data = [[
            Paragraph("<b>Project</b>", th),
            Paragraph(f"<b>{prev_end} HC</b>", th),
            Paragraph(f"<b>{end_month} HC</b>", th),
            Paragraph("<b>Net Change</b>", th),
            Paragraph("<b>Variance (%)</b>", th)
        ]]

        for p in all_projects:
            c_val = int(df_hc_curr[df_hc_curr["project_name"] == p]["headcount"].sum()) if not df_hc_curr.empty else 0
            p_val = int(df_hc_prev[df_hc_prev["project_name"] == p]["headcount"].sum()) if not df_hc_prev.empty else 0
            n_change = c_val - p_val
            p_change = round((n_change / p_val * 100), 1) if p_val > 0 else 0.0
            
            n_str = f"+{n_change}" if n_change > 0 else str(n_change)
            p_str = f"+{p_change}%" if p_change > 0 else f"{p_change}%"
            
            hc_table_data.append([
                Paragraph(f"<b>{p}</b>", td_bold),
                Paragraph(str(p_val), td),
                Paragraph(str(c_val), td),
                Paragraph(n_str, td_success if n_change > 0 else (td_danger if n_change < 0 else td)),
                Paragraph(p_str, td_success if p_change > 0 else (td_danger if p_change < 0 else td))
            ])

        hc_table = Table(hc_table_data, colWidths=[2.0*inch, 1.2*inch, 1.2*inch, 1.1*inch, 1.5*inch])
        hc_table.setStyle(base_table_style)
        story.append(hc_table)
        story.append(PageBreak())

        # ═══════════════════════════════════════════════════════════════════
        # PAGE 4: PROJECT-WISE TURNOVER ANALYSIS
        # ═══════════════════════════════════════════════════════════════════
        story.append(Paragraph("3 &nbsp;&nbsp; Projects Analytics", h1))
        story.append(self._section_divider())
        story.append(Spacer(1, 4))
        story.append(Paragraph(
            f"The table below compares turnover rates for each project during <b>{self._clean_text(label_curr)}</b> "
            f"against the preceding period (<b>{self._clean_text(label_prev)}</b>). "
            f"Positive variance (shown in red) indicates an increase in attrition.",
            body
        ))
        story.append(Spacer(1, 6))

        # Project table
        proj_table_data = [[
            Paragraph("<b>Project</b>", th),
            Paragraph(f"<b>Current (%)</b>", th),
            Paragraph(f"<b>Previous (%)</b>", th),
            Paragraph("<b>Variance</b>", th),
            Paragraph("<b>Trend</b>", th)
        ]]

        proj_names = []
        proj_rates = []
        
        for p in all_projects:
            curr = self.turnover_engine.calculate_project_turnover(p, start_month, end_month)
            prev = self.turnover_engine.calculate_project_turnover(p, prev_start, prev_end)
            diff = round(curr - prev, 2)
            
            diff_str = f"+{diff}%" if diff > 0 else f"{diff}%"
            trend = "▲ Increase" if diff > 0 else ("▼ Decrease" if diff < 0 else "● Stable")
            trend_style = td_danger if diff > 0 else (td_success if diff < 0 else td)
            
            proj_table_data.append([
                Paragraph(f"<b>{p}</b>", td_bold),
                Paragraph(f"{curr}%", td),
                Paragraph(f"{prev}%", td),
                Paragraph(diff_str, td_danger if diff > 0 else td_success if diff < 0 else td),
                Paragraph(trend, trend_style)
            ])
            proj_names.append(p)
            proj_rates.append(curr)

        proj_table = Table(proj_table_data, colWidths=[2.0*inch, 1.2*inch, 1.2*inch, 1.1*inch, 1.5*inch])
        proj_table.setStyle(base_table_style)
        story.append(proj_table)
        story.append(Spacer(1, 14))

        # Chart: Project Turnover
        if proj_names:
            story.append(Paragraph("Project Turnover Rates Comparison", h3))
            chart = self._build_horizontal_bar_chart(
                proj_names, proj_rates,
                title=f"Turnover Rate (%) by Project — {label_curr}"
            )
            story.append(chart)
        
        story.append(PageBreak())

        # ═══════════════════════════════════════════════════════════════════
        # PAGE 4: ATTRITION DRIVERS
        # ═══════════════════════════════════════════════════════════════════
        story.append(Paragraph("4 &nbsp;&nbsp; Departments &amp; Positions", h1))
        story.append(self._section_divider())
        story.append(Spacer(1, 4))
        
        if df_lv.empty:
            story.append(Paragraph(
                "No departure records were found for the selected period. "
                "This section will populate once leavers data is uploaded.", body
            ))
        else:
            # ─── 3.1 Department Breakdown ──────────────────────────────────
            story.append(Paragraph("4.1 &nbsp;&nbsp; Department Attrition Breakdown", h2))
            story.append(Paragraph(
                f"The following table shows the distribution of <b>{tot_dep}</b> total departures "
                f"across organizational departments. Departments with higher departure counts "
                f"represent areas requiring focused retention strategies.", body
            ))
            story.append(Spacer(1, 4))
            
            dept_counts = df_lv["department"].value_counts().reset_index()
            dept_counts.columns = ["Department", "Departures"]
            dept_counts["Percentage"] = dept_counts["Departures"].apply(
                lambda x: f"{round(x / tot_dep * 100, 1)}%"
            )
            
            # Highlight top department
            top_dept = dept_counts.iloc[0]
            story.append(Paragraph(
                f"<i>&#9655; Highest attrition: <b>{top_dept['Department']}</b> with "
                f"{top_dept['Departures']} departures ({top_dept['Percentage']})</i>",
                callout_style
            ))
            
            dept_table_data = [[
                Paragraph("<b>Department</b>", th),
                Paragraph("<b>Departures</b>", th),
                Paragraph("<b>Share (%)</b>", th),
                Paragraph("<b>Risk Level</b>", th)
            ]]
            for _, row in dept_counts.iterrows():
                pct_val = round(row["Departures"] / tot_dep * 100, 1)
                risk = "🔴 High" if pct_val > 25 else ("🟡 Medium" if pct_val > 10 else "🟢 Low")
                dept_table_data.append([
                    Paragraph(str(row["Department"]), td_bold),
                    Paragraph(str(row["Departures"]), td),
                    Paragraph(str(row["Percentage"]), td),
                    Paragraph(risk, td)
                ])
                
            dept_table = Table(dept_table_data, colWidths=[2.5*inch, 1.4*inch, 1.3*inch, 1.8*inch])
            dept_table.setStyle(base_table_style)
            story.append(dept_table)
            story.append(Spacer(1, 10))
            
            # Chart: Department
            story.append(Paragraph("Department Departure Distribution", h3))
            chart_dept = self._build_horizontal_bar_chart(
                dept_counts["Department"].tolist(), 
                dept_counts["Departures"].tolist(),
                title="Departures by Department"
            )
            story.append(chart_dept)
            story.append(Spacer(1, 10))
            
            # ─── 4.2 Position Vulnerability ────────────────────────────────
            story.append(PageBreak())
            story.append(Paragraph("4.2 &nbsp;&nbsp; Position Vulnerability Breakdown", h2))
            story.append(Paragraph(
                f"The following chart outlines attrition distributed by specific job titles and positions.", body
            ))
            story.append(Spacer(1, 4))
            
            pos_counts = df_lv["position"].value_counts().reset_index()
            pos_counts.columns = ["Position", "Departures"]
            # Top 10 positions
            pos_counts = pos_counts.head(10)
            
            chart_pos = self._build_horizontal_bar_chart(
                pos_counts["Position"].tolist(), 
                pos_counts["Departures"].tolist(),
                title="Top 10 Departures by Position"
            )
            story.append(chart_pos)
            story.append(Spacer(1, 10))

            # ─── 4.3 Separation Reasons ────────────────────────────────────
            story.append(PageBreak())
            story.append(Paragraph("5 &nbsp;&nbsp; Resignation Reasons", h1))
            story.append(self._section_divider())
            story.append(Spacer(1, 4))
            story.append(Paragraph("5.1 &nbsp;&nbsp; Primary Attrition Reasons (AI Classified)", h2))
            story.append(Paragraph(
                "The AI classification engine categorizes each departure into standardized "
                "separation reasons. This helps identify systemic patterns vs. isolated incidents. "
                "The donut chart provides a quick visual of the separation category distribution.",
                body
            ))
            story.append(Spacer(1, 4))
            
            df_lv["ai_category"] = df_lv["ai_category"].fillna("Other / Unclassified")
            reason_counts = df_lv["ai_category"].value_counts().reset_index()
            reason_counts.columns = ["Category", "Departures"]
            reason_counts["Percentage"] = reason_counts["Departures"].apply(
                lambda x: f"{round(x / tot_dep * 100, 1)}%"
            )
            
            reason_table_data = [[
                Paragraph("<b>Separation Category</b>", th),
                Paragraph("<b>Departures</b>", th),
                Paragraph("<b>Share (%)</b>", th)
            ]]
            for _, row in reason_counts.iterrows():
                reason_table_data.append([
                    Paragraph(str(row["Category"]), td_bold),
                    Paragraph(str(row["Departures"]), td),
                    Paragraph(str(row["Percentage"]), td)
                ])
                
            reason_table = Table(reason_table_data, colWidths=[3.0*inch, 1.8*inch, 2.2*inch])
            reason_table.setStyle(base_table_style)
            story.append(reason_table)
            story.append(Spacer(1, 10))
            
            # Donut chart: Reasons
            story.append(Paragraph("Separation Category Distribution", h3))
            chart_reason = self._build_donut_chart(
                reason_counts["Category"].tolist(), 
                reason_counts["Departures"].tolist(),
                title="Turnover by Classified Separation Categories"
            )
            story.append(chart_reason)
            story.append(Spacer(1, 10))
            
            # ─── 4.4 Voluntary vs Involuntary ─────────────────────────────
            if "status" in df_lv.columns:
                story.append(Paragraph("5.2 &nbsp;&nbsp; Voluntary vs. Involuntary Separation", h2))
                story.append(Paragraph(
                    "Departures are classified as <b>Voluntary</b> (resignations initiated by the employee) "
                    "or <b>Involuntary</b> (terminations initiated by the organization). This distinction "
                    "is critical for understanding controllable vs. uncontrollable attrition.", body
                ))
                story.append(Spacer(1, 4))
                
                vol_map = df_lv["status"].fillna("Resigned").apply(
                    lambda x: "Involuntary (Terminated)" if str(x).strip().lower() == "terminated" else "Voluntary (Resigned)"
                )
                vol_counts = vol_map.value_counts().reset_index()
                vol_counts.columns = ["Type", "Count"]
                vol_counts["Percentage"] = vol_counts["Count"].apply(
                    lambda x: f"{round(x / tot_dep * 100, 1)}%"
                )
                
                vol_table_data = [[
                    Paragraph("<b>Separation Type</b>", th),
                    Paragraph("<b>Count</b>", th),
                    Paragraph("<b>Share (%)</b>", th)
                ]]
                for _, row in vol_counts.iterrows():
                    style = td_danger if "Involuntary" in str(row["Type"]) else td_bold
                    vol_table_data.append([
                        Paragraph(str(row["Type"]), style),
                        Paragraph(str(row["Count"]), td),
                        Paragraph(str(row["Percentage"]), td)
                    ])
                
                vol_table = Table(vol_table_data, colWidths=[3.0*inch, 1.8*inch, 2.2*inch])
                vol_table.setStyle(base_table_style)
                story.append(vol_table)
                story.append(Spacer(1, 10))
                
                # Donut chart for Vol vs Invol
                chart_vol = self._build_donut_chart(
                    vol_counts["Type"].tolist(),
                    vol_counts["Count"].tolist(),
                    title="Voluntary vs. Involuntary Separation"
                )
                story.append(chart_vol)
                story.append(Spacer(1, 10))

            # ─── 3.4 Tenure Bracket Analysis ──────────────────────────────
            story.append(PageBreak())
            story.append(Paragraph("6 &nbsp;&nbsp; Length of Service", h1))
            story.append(self._section_divider())
            story.append(Spacer(1, 4))
            story.append(Paragraph(
                "This section analyzes the tenure profile of departing employees. "
                "A high concentration in early brackets (&lt;3 months, 3-6 months) signals "
                "onboarding or early engagement issues. A high &gt;2 years bracket indicates "
                "loss of experienced talent requiring strategic retention interventions.", body
            ))
            story.append(Spacer(1, 4))
            
            brackets = df_lv["length_of_service_months"].apply(
                ResignationAnalytics.get_service_bracket
            )
            bracket_order = ["< 3 Months", "3 - 6 Months", "6 - 12 Months", "1 - 2 Years", "> 2 Years"]
            bracket_counts = brackets.value_counts().reindex(bracket_order, fill_value=0).reset_index()
            bracket_counts.columns = ["Service Bracket", "Departures"]
            bracket_counts["Percentage"] = bracket_counts["Departures"].apply(
                lambda x: f"{round(x / tot_dep * 100, 1)}%"
            )
            
            # Early attrition callout
            early_count = bracket_counts[bracket_counts["Service Bracket"].isin(
                ["< 3 Months", "3 - 6 Months"]
            )]["Departures"].sum()
            early_pct = round(early_count / tot_dep * 100, 1) if tot_dep > 0 else 0
            
            story.append(Paragraph(
                f"<i>&#9655; Early Attrition Alert: <b>{early_count}</b> employees ({early_pct}%) "
                f"left within their first 6 months — indicating potential onboarding gaps.</i>",
                callout_style
            ))
            
            bracket_table_data = [[
                Paragraph("<b>Tenure Bracket</b>", th),
                Paragraph("<b>Departures</b>", th),
                Paragraph("<b>Share (%)</b>", th),
                Paragraph("<b>Implication</b>", th)
            ]]
            implications = {
                "< 3 Months": "Onboarding failure risk",
                "3 - 6 Months": "Early disengagement",
                "6 - 12 Months": "Role misalignment",
                "1 - 2 Years": "Growth / career path gap",
                "> 2 Years": "Experienced talent loss"
            }
            for _, row in bracket_counts.iterrows():
                impl = implications.get(row["Service Bracket"], "—")
                bracket_table_data.append([
                    Paragraph(str(row["Service Bracket"]), td_bold),
                    Paragraph(str(row["Departures"]), td),
                    Paragraph(str(row["Percentage"]), td),
                    Paragraph(impl, body_small)
                ])
                
            bracket_table = Table(bracket_table_data, colWidths=[1.8*inch, 1.4*inch, 1.3*inch, 2.5*inch])
            bracket_table.setStyle(base_table_style)
            story.append(bracket_table)
            story.append(Spacer(1, 10))
            
            # Chart: Tenure
            story.append(Paragraph("Departures by Length of Service", h3))
            chart_tenure = self._build_horizontal_bar_chart(
                bracket_counts["Service Bracket"].tolist(), 
                bracket_counts["Departures"].tolist(),
                title="Tenure Profile of Departing Employees"
            )
            story.append(chart_tenure)

            # ─── 7 Employee Explorer ────────────────────────────────────
            story.append(PageBreak())
            story.append(Paragraph("7 &nbsp;&nbsp; Employee Explorer", h1))
            story.append(self._section_divider())
            story.append(Spacer(1, 4))
            story.append(Paragraph(
                "Below is a high-level snapshot of the 5 most recent departures in the selected period. "
                "Full employee rosters are maintained securely in the digital dashboard.", body
            ))
            story.append(Spacer(1, 6))
            
            if "date_of_leaving" in df_lv.columns:
                recent_leavers = df_lv.sort_values(by="date_of_leaving", ascending=False).head(5)
                
                emp_table_data = [[
                    Paragraph("<b>Employee Name</b>", th),
                    Paragraph("<b>Project</b>", th),
                    Paragraph("<b>Position</b>", th),
                    Paragraph("<b>Date of Leaving</b>", th),
                    Paragraph("<b>Status</b>", th)
                ]]
                
                for _, row in recent_leavers.iterrows():
                    emp_table_data.append([
                        Paragraph(str(row.get("employee_name", "N/A")), td_bold),
                        Paragraph(str(row.get("project_name", "N/A")), td),
                        Paragraph(str(row.get("position", "N/A")), td),
                        Paragraph(str(row.get("date_of_leaving", "N/A")), td),
                        Paragraph(str(row.get("status", "N/A")), td)
                    ])
                    
                emp_table = Table(emp_table_data, colWidths=[2.0*inch, 1.5*inch, 1.5*inch, 1.2*inch, 1.0*inch])
                emp_table.setStyle(base_table_style)
                story.append(emp_table)
            
            story.append(Spacer(1, 10))

            # ─── 4.6 Month-by-Month Trend (if multi-month) ────────────────
            story.append(PageBreak())
            story.append(Paragraph("8 &nbsp;&nbsp; Monthly Comparison", h1))
            story.append(self._section_divider())
            story.append(Spacer(1, 4))
            
            if start_month != end_month and not df_lv.empty and "date_of_leaving" in df_lv.columns:
                story.append(Paragraph(
                    "The following table tracks departure volume across individual months "
                    "within the reporting period, helping identify seasonal patterns or "
                    "specific months with anomalous attrition spikes.", body
                ))
                story.append(Spacer(1, 4))
                
                df_lv["departure_month"] = pd.to_datetime(
                    df_lv["date_of_leaving"], errors="coerce"
                ).dt.to_period("M").astype(str)
                
                monthly = df_lv["departure_month"].value_counts().sort_index().reset_index()
                monthly.columns = ["Month", "Departures"]
                
                month_table_data = [[
                    Paragraph("<b>Month</b>", th),
                    Paragraph("<b>Departures</b>", th),
                    Paragraph("<b>Share (%)</b>", th)
                ]]
                for _, row in monthly.iterrows():
                    pct = f"{round(row['Departures'] / tot_dep * 100, 1)}%"
                    month_table_data.append([
                        Paragraph(str(row["Month"]), td_bold),
                        Paragraph(str(row["Departures"]), td),
                        Paragraph(pct, td)
                    ])
                
                month_table = Table(month_table_data, colWidths=[2.5*inch, 2.0*inch, 2.5*inch])
                month_table.setStyle(base_table_style)
                story.append(month_table)
                story.append(Spacer(1, 10))
                
                # Chart
                story.append(Paragraph("Monthly Departure Volume", h3))
                chart_month = self._build_horizontal_bar_chart(
                    monthly["Month"].tolist(),
                    monthly["Departures"].tolist(),
                    title="Departure Count by Month"
                )
                story.append(chart_month)

        # ═══════════════════════════════════════════════════════════════════
        # FINAL PAGE: DISCLAIMER
        # ═══════════════════════════════════════════════════════════════════
        story.append(PageBreak())
        story.append(Spacer(1, 60))
        
        disclaimer_accent = Drawing(480, 6)
        disclaimer_accent.add(Rect(0, 0, 480, 1, fillColor=self.c_border, strokeColor=None))
        disclaimer_accent.add(Rect(200, 0, 80, 4, fillColor=self.c_accent, strokeColor=None))
        story.append(disclaimer_accent)
        story.append(Spacer(1, 20))
        
        story.append(Paragraph("Disclaimer &amp; Notes", ParagraphStyle(
            "DisclaimerTitle", parent=h2, alignment=TA_CENTER, textColor=self.c_text_light
        )))
        story.append(Spacer(1, 8))
        
        disclaimer_text = [
            "This report was prepared by <b>Moazzam Baig</b>, Monal Group.",
            "All turnover rates and analytical insights are derived from the uploaded headcount "
            "rosters and leavers files for the selected reporting period.",
            "Separation categories are based on pattern-matching of resignation reasons "
            "and may require human validation for edge cases.",
            "Turnover rates are computed using the standard formula: "
            "<i>(Departures / Average Headcount) x 100</i>.",
            "This document is classified as <b>CONFIDENTIAL</b> and intended for internal "
            "management use only. Do not distribute externally without authorization.",
        ]
        
        for line in disclaimer_text:
            story.append(Paragraph(f"&#8226; &nbsp;{line}", ParagraphStyle(
                "DisclaimerBody", parent=body_small, alignment=TA_LEFT,
                leftIndent=30, rightIndent=30, spaceBefore=2, spaceAfter=4
            )))
        
        story.append(Spacer(1, 30))
        story.append(Paragraph(
            f"— End of Report —", ParagraphStyle(
                "EndMark", parent=body_small, alignment=TA_CENTER,
                fontName="Helvetica-Oblique", textColor=self.c_text_light
            )
        ))

        # ═══════════════════════════════════════════════════════════════════
        # BUILD PDF
        # ═══════════════════════════════════════════════════════════════════
        doc.build(story, canvasmaker=NumberedCanvas)
        logger.info(f"PDF report generated at {pdf_path}")
        return pdf_path
