# Evaluator-only collaboration contract

This directory is private to generator evaluation. It may describe causal
attribution, held-out configurations, expected findings, and evaluator checks.
It must not be imported by `app/estate_generator`, the FastAPI application, or
the deployed investigator.

Reviewers may inspect and recommend changes here. The orchestrator owns any
implementation in this directory until an evaluation-harness owner is assigned.
