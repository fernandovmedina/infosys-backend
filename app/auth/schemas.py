"""Request and response models for the auth endpoints."""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


def normalize_email(email: str) -> str:
    """Case-fold and trim an email so lookups don't depend on how it was typed."""
    return email.strip().lower()


class RegisterRequest(BaseModel):
    """Payload for `POST /auth/register`."""

    model_config = ConfigDict(extra="forbid")

    name: Annotated[str, Field(min_length=1, max_length=200)]
    email: EmailStr
    password: Annotated[str, Field(min_length=8, max_length=200)]

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Name cannot be blank.")
        return stripped


class LoginRequest(BaseModel):
    """Payload for `POST /auth/login`."""

    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    password: Annotated[str, Field(min_length=1, max_length=200)]


class UserPublic(BaseModel):
    """The user fields it is safe to hand back to the client."""

    id: int
    name: str
    email: str


class SessionResponse(BaseModel):
    """Response for endpoints that establish a session: register and login."""

    user: UserPublic
