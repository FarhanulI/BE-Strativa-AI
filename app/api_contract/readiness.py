from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

DependencyStatus = Literal["ok", "unavailable", "not_configured"]


class ReadinessResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["ready", "not_ready"]
    database: DependencyStatus
    redis: DependencyStatus


