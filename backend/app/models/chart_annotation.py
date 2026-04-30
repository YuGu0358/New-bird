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


class ChartAnnotationResponse(BaseModel):
    symbol: str
    range: str
    annotations: list[ChartAnnotation]
