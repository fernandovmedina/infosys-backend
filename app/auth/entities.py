"""Domain objects used by authentication services and persistence."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class User:
    """An application user without private authentication data."""

    id: int
    name: str
    email: str


@dataclass(frozen=True, slots=True)
class UserWithPassword(User):
    """A user record loaded specifically for password verification."""

    password_hash: str


@dataclass(frozen=True, slots=True)
class IssuedSession:
    """A newly issued browser session and its expiration time."""

    token: str
    expires_at: dt.datetime
