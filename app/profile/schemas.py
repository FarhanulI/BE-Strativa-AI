from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.core import CursorPage, ProblemDetails


class ProfileType(StrEnum):
    CREATOR = "creator"
    BUSINESS = "business"
    PERSONAL_BRAND = "personal_brand"
    EXPERT = "expert"
    COACH = "coach"
    STARTUP = "startup"
    LOCAL_BUSINESS = "local_business"
    ECOMMERCE_BRAND = "ecommerce_brand"


class GoalType(StrEnum):
    GROWTH = "growth"
    AUTHORITY = "authority"
    LEAD_GEN = "lead_gen"
    SALES = "sales"


class MaturityStage(StrEnum):
    COLD_START = "cold_start"
    EARLY_GROWTH = "early_growth"
    MATURE = "mature"


class ProfileItemType(StrEnum):
    PRODUCT = "products"
    SERVICE = "services"
    OFFER = "offers"


class ProfileGoal(BaseModel):
    type: GoalType
    priority: int = Field(ge=1)
    description: str = Field(min_length=1, max_length=1000)


class ProfileCreateRequest(BaseModel):
    type: ProfileType
    name: str = Field(min_length=1, max_length=160)
    positioning: str = Field(default="", max_length=4000)
    topics: list[str] = Field(default_factory=list, max_length=100)
    expertise: list[str] = Field(default_factory=list, max_length=100)
    goals: list[ProfileGoal] = Field(default_factory=list, max_length=100)


class ProfilePatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=160)
    positioning: str | None = Field(default=None, max_length=4000)
    topics: list[str] | None = Field(default=None, max_length=100)
    expertise: list[str] | None = Field(default=None, max_length=100)
    goals: list[ProfileGoal] | None = Field(default=None, max_length=100)


class ProfileResponse(BaseModel):
    id: UUID
    workspace_id: UUID
    type: ProfileType
    name: str
    positioning: str
    topics: list[str]
    expertise: list[str]
    goals: list[ProfileGoal]
    maturity_stage: MaturityStage
    verified_performance_count: int
    version: int
    archived_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ProfileVersionConflictProblemDetails(ProblemDetails):
    current: ProfileResponse


class ProfileSummary(BaseModel):
    id: UUID
    workspace_id: UUID
    type: ProfileType
    name: str
    positioning: str
    topics: list[str]
    expertise: list[str]
    goals: list[ProfileGoal]
    maturity_stage: MaturityStage
    verified_performance_count: int
    version: int
    created_at: datetime
    updated_at: datetime


class ProfilePage(CursorPage[ProfileSummary]):
    pass


class ProfileMaturityResponse(BaseModel):
    profile_id: UUID
    workspace_id: UUID
    stage: MaturityStage
    verified_performance_count: int
    version: int


class BusinessContextRequest(BaseModel):
    commercial_objectives: list[dict[str, Any]] = Field(default_factory=list, max_length=100)


class BusinessContextResponse(BaseModel):
    profile_id: UUID
    workspace_id: UUID
    commercial_objectives: list[dict[str, Any]]
    created_at: datetime
    updated_at: datetime


class ProfileItemCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=4000)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ProfileItemPatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=4000)
    metadata: dict[str, Any] | None = None


class ProfileItemResponse(BaseModel):
    id: UUID
    workspace_id: UUID
    profile_id: UUID
    name: str
    description: str
    metadata: dict[str, Any]
    archived_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ProfileItemPage(CursorPage[ProfileItemResponse]):
    pass