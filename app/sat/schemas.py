"""Request and response models for the SAT blacklist endpoint."""

from __future__ import annotations

import datetime as dt
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.config import get_settings
from app.sat.normalization import is_valid_rfc, normalize_rfc

MatchType = Literal["rfc", "rfc_and_name", "name_exact", "name_fuzzy"]

_MAX_NAME_LENGTH = 600  # longest name in the source dataset is 587 characters


class CompanyQuery(BaseModel):
    """One company to look up, identified by RFC, name, or both."""

    model_config = ConfigDict(extra="forbid")

    rfc: Annotated[str | None, Field(default=None, max_length=64)] = None
    name: Annotated[str | None, Field(default=None, max_length=_MAX_NAME_LENGTH)] = None

    @model_validator(mode="after")
    def check_identifiers(self) -> Self:
        """Require at least one usable identifier, and a well-formed RFC if given."""
        rfc = (self.rfc or "").strip()
        name = (self.name or "").strip()

        if not rfc and not name:
            raise ValueError("Provide at least one of 'rfc' or 'name'.")

        if rfc and not is_valid_rfc(normalize_rfc(rfc)):
            raise ValueError(
                "Invalid RFC format. Expected 12 characters for a company or 13 for "
                "an individual: 3-4 letters, 6 digits (YYMMDD) and a 3-character "
                "homoclave."
            )

        # Store the trimmed values so the echoed query and the normalization
        # downstream both see the same thing. Blank becomes None: a company
        # given as {"rfc": "...", "name": "  "} is an RFC-only lookup.
        self.rfc = rfc or None
        self.name = name or None

        return self


def _max_companies() -> int:
    return get_settings().blacklist_max_companies_per_request


class BlacklistCheckRequest(BaseModel):
    """Payload for a bulk blacklist check."""

    model_config = ConfigDict(extra="forbid")

    companies: Annotated[list[CompanyQuery], Field(min_length=1)]

    @model_validator(mode="after")
    def check_batch_size(self) -> Self:
        """Cap the batch so one request cannot force an unbounded amount of work."""
        limit = _max_companies()
        if len(self.companies) > limit:
            raise ValueError(
                f"Too many companies in one request: {len(self.companies)} (maximum {limit})."
            )
        return self


class BlacklistRecord(BaseModel):
    """A matched row of the SAT listing, with the source fields preserved."""

    id: int
    rfc: str
    name: str
    situacion: str
    is_cleared: bool

    presuncion_sat_oficio: str | None = None
    presuncion_sat_publicacion: dt.date | None = None
    presuncion_dof_oficio: str | None = None
    presuncion_dof_publicacion: dt.date | None = None
    desvirtuado_sat_oficio: str | None = None
    desvirtuado_sat_publicacion: dt.date | None = None
    desvirtuado_dof_oficio: str | None = None
    desvirtuado_dof_publicacion: dt.date | None = None
    definitivo_sat_oficio: str | None = None
    definitivo_sat_publicacion: dt.date | None = None
    definitivo_dof_oficio: str | None = None
    definitivo_dof_publicacion: dt.date | None = None
    sentencia_sat_oficio: str | None = None
    sentencia_sat_publicacion: dt.date | None = None
    sentencia_dof_oficio: str | None = None
    sentencia_dof_publicacion: dt.date | None = None


class CompanyResult(BaseModel):
    """The outcome for a single requested company."""

    query: CompanyQuery
    blacklisted: bool = Field(
        description="True when the company appears anywhere in the SAT 69-B listing."
    )
    match_type: MatchType | None = None
    similarity: float | None = Field(
        default=None,
        description="Trigram similarity, present only when match_type is 'name_fuzzy'.",
    )
    effective_situacion: str | None = Field(
        default=None,
        description=(
            "Most severe status across all matches, ordered "
            "Definitivo > Presunto > Desvirtuado > Sentencia Favorable."
        ),
    )
    cleared: bool | None = Field(
        default=None,
        description=(
            "True when every match is 'Desvirtuado' or 'Sentencia Favorable', i.e. "
            "the taxpayer rebutted the presumption. Null when there is no match."
        ),
    )
    match: BlacklistRecord | None = Field(
        default=None, description="The most severe matching record."
    )
    matches: list[BlacklistRecord] = Field(
        default_factory=list,
        description=(
            "Every matching record. An RFC can hold more than one procedure, so "
            "this may contain several entries."
        ),
    )
    match_count: int = 0


class BlacklistCheckResponse(BaseModel):
    """One result per requested company, in request order."""

    results: list[CompanyResult]
