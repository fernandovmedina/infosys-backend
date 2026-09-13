"""Fraud-detection engine, ported from the motor-agente-forense repository.

`engine/` is the deterministic agent (rules runner, assembler, submission,
case file, official validator gate) and `rules/` the SQL detectors it runs over
an in-memory DuckDB estate. `service.py` adapts both to this API.
"""
