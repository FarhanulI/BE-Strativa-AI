from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class RegisterRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=12, max_length=128)
    display_name: str = Field(min_length=1, max_length=160)
    workspace_name: str = Field(min_length=1, max_length=160)

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        normalized = value.strip().lower()
        if "@" not in normalized or "." not in normalized.rsplit("@", 1)[-1]:
            raise ValueError("A valid email address is required")
        return normalized

    @field_validator("display_name", "workspace_name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Value must contain a non-whitespace character")
        return normalized


class MePatchRequest(BaseModel):
    display_name: str = Field(min_length=1, max_length=160)

    @field_validator("display_name")
    @classmethod
    def normalize_display_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Display name must contain a non-whitespace character")
        return normalized


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=128)


class UserResponse(BaseModel):
    id: UUID
    email: str
    display_name: str


class RegisteredWorkspaceResponse(BaseModel):
    id: UUID
    name: str
    slug: str
    role: str


class AuthResponse(BaseModel):
    access_token: str
    expires_in: int = 900
    token_type: str = "Bearer"
    user: UserResponse
    workspace: RegisteredWorkspaceResponse | None = None


class MeResponse(BaseModel):
    user: UserResponse
    workspaces: list[RegisteredWorkspaceResponse]


class RefreshResponse(BaseModel):
    access_token: str
    expires_in: int = 900
    token_type: str = "Bearer"