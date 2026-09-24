from __future__ import annotations

from typing import Dict

from app.models.schemas import AnalysisResult


analysis_store: Dict[str, AnalysisResult] = {}
latest_analysis_by_instrument: Dict[str, AnalysisResult] = {}
