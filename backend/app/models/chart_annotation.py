from __future__ import annotations
from typing import Literal
from pydantic import BaseModel, Field


class ChartAnnotationPoint(BaseModel):
    timestamp: int = Field(..., description="ms since epoch")
    price: float


class ChartAnnotation(BaseModel):
    kind: Literal["support", "resistance", "trendline", "note"]
    label: str
    points: list[ChartAnnotationPoint]
    group_id: str = "ai-annotation"


class ChartAnnotationResponse(BaseModel):
    symbol: str
    range: str
    annotations: list[ChartAnnotation]


class ChartAnnotateRequest(BaseModel):
    range: str = "3mo"
    image_base64: str  # data URL form: "data:image/png;base64,..."
