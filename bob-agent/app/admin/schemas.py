"""Pydantic schemas for the Admin API."""

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel


class SiteCreate(BaseModel):
    group_id: str
    name: Optional[str] = None
    training_phase: str = ""
    context: dict[str, Any] = {}
    logo_url: Optional[str] = None


class SiteUpdate(BaseModel):
    name: Optional[str] = None
    training_phase: Optional[str] = None
    context: Optional[dict[str, Any]] = None
    logo_url: Optional[str] = None


class SiteResponse(BaseModel):
    id: int
    group_id: str
    name: Optional[str]
    training_phase: str
    context: dict[str, Any]
    logo_url: Optional[str]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
