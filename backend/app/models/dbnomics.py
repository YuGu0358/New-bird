"""Pydantic schemas for the DBnomics adapter."""
from __future__ import annotations

from datetime import date as _date
from datetime import datetime

from pydantic import BaseModel


class DBnomicsObservationModel(BaseModel):
    period: str
    # Field name shadows the imported `date` type, so we keep the alias above
    # and annotate against it here.
    date: _date | None = None
    value: float | None = None


class DBnomicsSeriesResponse(BaseModel):
    provider_code: str
    dataset_code: str
    series_code: str
    series_name: str | None = None
    frequency: str | None = None
    indexed_at: str | None = None
    observations: list[DBnomicsObservationModel]
    generated_at: datetime
    as_of: datetime | None = None
