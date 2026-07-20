# 💼 Monal Group — HR AI Analytics Dashboard

AI-Powered Turnover Analytics & Talent Insights Dashboard for The Monal Group.

## Features

- 📊 **Executive Summary** — AI-generated insights with PDF export
- 📉 **Turnover Dashboard** — Trends, rolling 12-month metrics, headcount analysis
- 🏢 **Projects Analytics** — Project-wise turnover breakdown
- 👥 **Departments & Positions** — Vulnerability analysis by department/position
- 💬 **Resignation Reasons** — AI-classified HR category analysis
- ⏳ **Length of Service** — Tenure bracket analysis & early turnover detection
- 🔍 **Employee Explorer** — Searchable employee database
- 📅 **Monthly Comparison** — Period-vs-period comparison reports
- 📥 **Data Ingestion** — Excel upload with validation & AI classification
- ⚙️ **System Configuration** — Standards registry management

## Tech Stack

- **Frontend:** Streamlit
- **Data:** Pandas, Plotly
- **Database:** SQLite
- **AI Engine:** Ollama / Llama 3.1 (with rule-based fallback)
- **Reports:** ReportLab PDF Generator

## Quick Start

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Deployment

This app is deployed on [Streamlit Community Cloud](https://share.streamlit.io).
