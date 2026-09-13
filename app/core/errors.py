"""Project-wide error-response format and exception handlers.

Every failure -- validation, not-found, database outage -- leaves the API in the
same envelope, so clients only ever parse one error shape:

    {"error": {"code": "validation_error", "message": "...", "details": [...]}}
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)


class AppError(Exception):
    """Base class for errors that map onto a known HTTP response."""

    status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR
    code: str = "internal_error"
    message: str = "An unexpected error occurred."

    def __init__(self, message: str | None = None, details: Any = None) -> None:
        super().__init__(message or self.message)
        if message:
            self.message = message
        self.details = details


class DatabaseUnavailableError(AppError):
    """The database could not be reached or a query failed."""

    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    code = "database_unavailable"
    message = "The database is currently unavailable. Please retry shortly."


class EmailAlreadyRegisteredError(AppError):
    """Registration was attempted with an email already on file."""

    status_code = status.HTTP_409_CONFLICT
    code = "email_already_registered"
    message = "An account with this email already exists."


class InvalidCredentialsError(AppError):
    """Login failed: unknown email or wrong password."""

    status_code = status.HTTP_401_UNAUTHORIZED
    code = "invalid_credentials"
    message = "Invalid email or password."


class NotAuthenticatedError(AppError):
    """No valid session cookie was present on a request that requires one."""

    status_code = status.HTTP_401_UNAUTHORIZED
    code = "not_authenticated"
    message = "You must be signed in to do this."


class UploadRejectedError(AppError):
    """An uploaded dataset cannot be used at all (wrong format, unreadable, no tables).

    The code varies with the reason, so the frontend can explain each case; the
    message is user-facing Spanish.
    """

    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    code = "upload_rejected"

    def __init__(
        self, code: str, message: str, *, details: Any = None, status_code: int | None = None
    ) -> None:
        super().__init__(message, details)
        self.code = code
        if status_code is not None:
            self.status_code = status_code


class RunNotFoundError(AppError):
    """The run does not exist or belongs to another account."""

    status_code = status.HTTP_404_NOT_FOUND
    code = "run_not_found"
    message = "No encontramos esta corrida."


class ValidationBlockedError(AppError):
    """The dataset diagnostics have blocking errors, so the run cannot start."""

    status_code = status.HTTP_409_CONFLICT
    code = "validation_blocked"
    message = "El diagnóstico tiene errores bloqueantes; corrige el dataset y vuelve a subirlo."


class InvalidRunStateError(AppError):
    """The run is not in a state that allows the requested transition."""

    status_code = status.HTTP_409_CONFLICT
    code = "invalid_state"
    message = "La corrida no está en un estado que permita esta acción."


class RunResultNotAvailableError(AppError):
    """The run has no fraud analysis yet (not started, still running, or failed)."""

    status_code = status.HTTP_409_CONFLICT
    code = "result_not_available"
    message = "La corrida todavía no tiene resultados de la investigación."


class RecordNotFoundError(AppError):
    """The run's dataset has no record with that table and id."""

    status_code = status.HTTP_404_NOT_FOUND
    code = "record_not_found"
    message = "No encontramos ese registro en el dataset de la corrida."


class EntityNotFoundError(AppError):
    """The run's case file has no entity with that id."""

    status_code = status.HTTP_404_NOT_FOUND
    code = "entity_not_found"
    message = "No encontramos esa entidad en la corrida."


class FraudDatasetInvalidError(AppError):
    """The estate CSVs sent to the fraud engine do not match the estate schema.

    `details` lists every problem as `{"file", "column", "message"}`.
    """

    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    code = "invalid_dataset"
    message = "Los CSV no cumplen el esquema del estate."


class FraudEngineOutputInvalidError(AppError):
    """The engine's submission did not pass the official format validator, so it is withheld.

    `details` carries the validator's error messages.
    """

    status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
    code = "engine_output_invalid"
    message = "El resultado del motor no pasó el validador oficial; no se entrega."


def error_response(
    *, status_code: int, code: str, message: str, details: Any = None
) -> JSONResponse:
    """Build a response in the project's error envelope."""
    payload: dict[str, Any] = {"code": code, "message": message}
    if details is not None:
        payload["details"] = details
    return JSONResponse(status_code=status_code, content={"error": payload})


def register_exception_handlers(app: FastAPI) -> None:
    """Attach the handlers that normalize every error into one shape."""

    @app.exception_handler(AppError)
    async def handle_app_error(_: Request, exc: AppError) -> JSONResponse:
        if exc.status_code >= status.HTTP_500_INTERNAL_SERVER_ERROR:
            logger.exception("Application error: %s", exc.message, exc_info=exc)
        return error_response(
            status_code=exc.status_code,
            code=exc.code,
            message=exc.message,
            details=exc.details,
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        # Drop the pydantic `ctx` key: it can hold non-serializable objects.
        details = [
            {k: v for k, v in error.items() if k in ("loc", "msg", "type")}
            for error in exc.errors()
        ]
        return error_response(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            code="validation_error",
            message="The request payload failed validation.",
            details=details,
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_exception(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        return error_response(
            status_code=exc.status_code,
            code="http_error",
            message=str(exc.detail),
        )

    @app.exception_handler(Exception)
    async def handle_unexpected(_: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled error", exc_info=exc)
        return error_response(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            code="internal_error",
            message="An unexpected error occurred.",
        )
