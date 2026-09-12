"""Offline synthetic-estate generation for the Forensic Auditor challenge.

This package is deliberately independent from FastAPI, PostgreSQL, and the SAT
lookup service. It generates only the public estate; private evaluation
artifacts live outside the application package.
"""

from app.estate_generator.config import EstateGeneratorConfig

__all__ = ["EstateGeneratorConfig"]
