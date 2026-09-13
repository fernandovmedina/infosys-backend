# TASK #1 — SAT Blacklist Search Endpoint

## MAIN OBJECTIVE

Implement an API endpoint that checks whether one or multiple Mexican companies appear in the SAT blacklist.

The endpoint must accept one or more companies identified by:

* RFC
* Company/legal name (`razon_social`)
* A combination of both

The endpoint must efficiently search the SAT blacklist and return the status and matching information for every requested company.

The reference dataset is:

`black_list.csv`

The dataset contains approximately 15,000 records, but the implementation should be designed to remain efficient as the dataset grows.

---

## DATABASE SETUP

Before implementing the endpoint, create the following database structure:

```text
database/
├── database.sql
├── exec.sql
└── alter.sql
```

### `database/database.sql`

This file must contain the complete database schema required by the project.

Create an appropriate table for storing SAT blacklist records.

Use proper:

* Primary keys
* Data types
* Constraints
* Indexes
* Unique constraints where appropriate
* Timestamps if useful

Design the schema specifically for fast RFC and company-name lookups.

### `database/exec.sql`

This file must contain the SQL required to initialize/seed the database with the data the project needs to start.

Do not manually write the ~15,000 blacklist records into this file.

Instead, create a reusable import/seeding mechanism that reads `black_list.csv` and inserts or upserts the records into the database.

The import must:

* Parse the CSV safely
* Normalize RFC values
* Normalize company names
* Handle duplicate records
* Handle malformed/empty rows gracefully
* Use batch/bulk inserts instead of one INSERT per row when possible
* Be safe to run multiple times without creating duplicates
* Report how many records were inserted, updated, skipped, or failed

### `database/alter.sql`

This file will contain future schema migrations/alterations required as the project evolves.

For now, create the file and document its intended purpose. Do not duplicate the initial schema from `database.sql`.

---

## SEARCH DESIGN

Do NOT load and iterate over all ~15,000 records for every request.

Implement an efficient database-backed search strategy.

### RFC Search

RFC searches should prioritize exact matching.

Normalize RFC input before searching:

* Trim whitespace
* Convert to uppercase
* Handle formatting inconsistencies when appropriate

Create an index or unique index on the normalized RFC column.

Expected lookup complexity should effectively be index-based rather than a full table scan.

### Company Name Search

Company names may contain differences in:

* Upper/lowercase
* Accents
* Extra whitespace
* Punctuation
* Corporate suffixes

Create a normalized/searchable representation of the company name.

Choose an appropriate database search strategy based on the database engine already used by the project.

Possible approaches include:

* Indexed normalized names
* Full-text search
* Trigram indexes
* Fuzzy similarity search

Do not introduce unnecessary complexity if a simpler indexed solution satisfies the requirements.

Document the selected approach and why it was chosen.

---

## API ENDPOINT

Create one endpoint capable of checking multiple companies in a single request.

Use the project's existing API conventions. If no convention exists, use something similar to:

```http
POST /api/v1/sat/blacklist/check
```

Example request:

```json
{
  "companies": [
    {
      "rfc": "ABC123456XYZ"
    },
    {
      "name": "EMPRESA EJEMPLO SA DE CV"
    },
    {
      "rfc": "XYZ987654ABC",
      "name": "OTRA EMPRESA SA DE CV"
    }
  ]
}
```

The endpoint must support `N` companies in one request without executing unnecessary queries.

Prefer bulk database queries over performing one independent query per company.

Add a reasonable request-size limit to prevent abuse or accidental oversized requests.

---

## RESPONSE

Return one result per requested company.

Example:

```json
{
  "results": [
    {
      "query": {
        "rfc": "ABC123456XYZ"
      },
      "blacklisted": true,
      "match_type": "rfc",
      "match": {
        "rfc": "ABC123456XYZ",
        "name": "EMPRESA EJEMPLO SA DE CV"
      }
    },
    {
      "query": {
        "name": "EMPRESA LIMPIA SA DE CV"
      },
      "blacklisted": false,
      "match_type": null,
      "match": null
    }
  ]
}
```

Preserve additional relevant SAT blacklist fields from `black_list.csv` in the database and response when useful.

Do not discard useful source information simply to match the example above.

---

## VALIDATION & ERROR HANDLING

Validate all incoming data.

Handle at least:

* Empty request
* Missing RFC and name
* Invalid RFC format
* Duplicate companies in the same request
* Excessive number of companies
* Database errors
* Import errors
* Malformed CSV rows

Use appropriate HTTP status codes and the project's existing error-response format.

---

## PERFORMANCE

Performance is an important requirement.

The endpoint must:

* Avoid full-table scans whenever possible
* Use database indexes
* Avoid N+1 queries
* Support bulk searches
* Use parameterized queries
* Avoid SQL injection
* Return results efficiently for large batches

After implementation, inspect the generated query plan if the database supports it (`EXPLAIN`, `EXPLAIN ANALYZE`, etc.) and verify that indexes are actually being used.

---

## TESTING

Add tests covering at least:

1. Existing RFC
2. Non-existing RFC
3. Exact company name
4. Company name with different capitalization
5. Company name with accents/normalization differences
6. Multiple companies in one request
7. Mixed RFC + name searches
8. Duplicate input
9. Empty input
10. Invalid RFC
11. Large batch request
12. Database/import failure where practical

Use records from `black_list.csv` for realistic test cases.

---

## IMPLEMENTATION ORDER

Follow this order:

1. Inspect the existing project architecture and database configuration.
2. Inspect `black_list.csv` and understand its columns and data quality.
3. Design the blacklist database schema.
4. Create `database/database.sql`.
5. Create `database/exec.sql`.
6. Create `database/alter.sql`.
7. Implement the CSV import/seeding mechanism.
8. Import and verify the blacklist data.
9. Add the required indexes/search strategy.
10. Implement the blacklist service/repository logic.
11. Implement the API endpoint.
12. Add validation and error handling.
13. Add tests.
14. Run the project's formatter, linter, type checker, and test suite.
15. Fix all failures.
16. Verify query performance and indexes.
17. Document the endpoint and import process.

Do not modify unrelated functionality.

---

## REFERENCE

Primary data source:

```text
black_list.csv
```

Treat this file as the source of truth for the initial SAT blacklist dataset.

---

## IMPORTANT

Do not guess the CSV structure. Inspect `black_list.csv` before designing the final schema.
Reuse the project's existing architecture, naming conventions, database layer, validation libraries, and error-handling patterns whenever possible.
Keep the implementation modular so that the SAT blacklist dataset can later be refreshed automatically without changing the endpoint.
If an implementation detail can be reasonably determined from the existing project, make the decision yourself and continue.
If there is a genuine architectural or product decision that cannot be determined from the existing codebase or requirements, ask me through the Claude Code terminal before proceeding.

# TASK #2 — Build the Project Context

I'm participating in the **HACKMTY 2026 Hackathon**. Our challenge is provided by **Infosys** and focuses on detecting financial fraud, suspicious financial behavior, anomalies, and potentially fraudulent activity within companies.

Your task is to create or completely rewrite the root-level `CONTEXT.md` file so that it becomes the **single source of truth for the entire project**.

## 1. Understand the Challenge

First, read:

`/public/material/challenge.md`

Use this file as the **primary source of truth for the official challenge**.

Extract and understand:

* The problem statement
* Challenge objectives
* Expected solution
* Business context
* Technical requirements
* Constraints
* Evaluation criteria
* Expected deliverables
* Important terminology
* Fraud-related concepts mentioned
* Any requirements or recommendations from Infosys

Do not invent requirements that are not present in the source material.

## 2. Inspect All Project Material

Recursively inspect and read **every relevant file** inside:

`/public/material/`

Do not only inspect filenames. Read and analyze their contents.

This may include:

* Markdown
* CSV
* JSON
* TXT
* XML
* SQL
* PDFs or extracted PDF content
* Documentation
* Datasets
* Examples
* Technical references
* Challenge resources
* Research material
* Any other relevant files

For each file, determine:

1. What it contains
2. Why it exists
3. How it relates to the challenge
4. Whether it contains requirements, datasets, examples, references, or implementation-relevant information
5. What another AI agent or developer needs to know about it

## 3. Understand the Existing Project

After analyzing `/public/material/`, inspect the existing repository structure and relevant source files.

Understand what has already been implemented and how it relates to the challenge.

Do not modify implementation files as part of this task.

## 4. Create `CONTEXT.md`

Create or completely rewrite:

`CONTEXT.md`

The document should provide enough context that **another Claude Code session or AI coding agent can read only `CONTEXT.md` and quickly understand what this project is, what problem it solves, what resources are available, and how the current implementation approaches the challenge.**

Structure it approximately as:

# Project Context
## Hackathon
## Challenge Provider
## Problem Statement
## Challenge Objectives
## Business Context
## Fraud Detection Context
## Expected Solution
## Functional Requirements
## Technical Requirements
## Constraints
## Evaluation Criteria
## Expected Deliverables
## Available Materials
## Dataset / Data Sources
## Important Domain Concepts
## Existing Project Architecture
## Current Implementation
## Important Files and Directories
## Key Technical Decisions
## Assumptions
## Open Questions
## Current Project Status

Add or reorganize sections when doing so improves clarity.

## 5. Document the Materials

Include a section describing the important files found under:

`/public/material/`

For each important file, document its path and a concise explanation of what information it provides and why it matters.

Do not blindly copy entire files into `CONTEXT.md`. Summarize them while preserving important technical details, requirements, schemas, rules, thresholds, examples, and constraints.

## 6. Preserve Traceability

Whenever an important requirement or fact comes from the challenge material, mention the source file when useful.

Example:

`Source: /public/material/challenge.md`

This should make it easy for future agents to verify information against the original material.

## 7. Rules

* Read the source material **before writing `CONTEXT.md`**.
* Recursively inspect `/public/material/`.
* Do not hallucinate missing requirements.
* Clearly distinguish between **official challenge requirements**, **project decisions**, and **assumptions**.
* Preserve important numbers, thresholds, formats, schemas, and constraints exactly.
* Do not modify files other than `CONTEXT.md`.
* Do not implement features during this task.
* Prefer concise but complete documentation.
* Avoid unnecessary repetition.
* Make the document optimized for both **developers and AI coding agents**.
* If information conflicts between files, document the conflict instead of silently choosing one version.
* If something important is unclear, add it to `Open Questions`.

Before finishing, verify that `CONTEXT.md` accurately represents both the **official Infosys challenge** and the **current state of the project**.

**# TASK #3 — INTEGRATE FRAUD DETECTION ENGINE**

## MAIN TASK

There is another repository loaded in the same Claude Code session that already contains the fraud-detection engine, including:

* Fraud detection rules.
* Heuristics.
* Indicators and clues.
* Detection logic.
* Rule evaluation logic.
* Fraud classification logic.
* Supporting utilities.
* Existing endpoints related to the fraud engine.
* Any models, schemas, constants, configuration, or helper functions required by the engine.

Your goal is to integrate that existing fraud-detection engine into this repository.

The reference repository is already working, so the behavior implemented there must continue working correctly after being integrated into this project.

The most important component is the engine that evaluates transactions/data against the different rules and determines whether fraud indicators, suspicious patterns, anomalies, or other relevant signals exist.

Do not recreate the fraud engine from scratch unless absolutely necessary.

Instead:

1. Understand how the existing engine works.
2. Identify all required dependencies.
3. Identify the entry points used by the existing endpoints.
4. Identify the rule evaluation flow.
5. Identify the input and output schemas.
6. Identify any database dependencies.
7. Port and adapt the required code into this repository.
8. Expose the required functionality through this project's API.
9. Verify that the results are equivalent to the original implementation.

The final implementation must belong to this repository and must not depend on the other repository being present at runtime.

---

## WHAT TO DO

### 1. Analyze the Existing Fraud Engine

Before modifying this repository, inspect:

`/Users/froot/Documents/workspace/fernandovmedina/web/motor-agente-forense`

Understand the complete architecture of the fraud engine.

Identify at minimum:

* Main engine entry point.
* Fraud rules.
* Rule categories.
* Heuristics.
* Scoring logic.
* Thresholds.
* Pattern-detection logic.
* Fraud types.
* Input models.
* Output models.
* API endpoints.
* Services.
* Repositories/data-access code.
* Database tables used by the engine.
* Utility functions.
* Configuration.
* Environment variables.
* Python dependencies.
* External dependencies.
* Tests, if available.

Do not start copying files blindly.

First understand how the execution flow works from:

`API request -> validation -> fraud engine -> rules -> result -> API response`

---

### 2. Determine What Must Be Ported

Determine which parts of the other repository are actually required for the fraud engine to work.

Port only what is necessary.

This may include:

* Rule engine.
* Fraud rules.
* Detection services.
* Scoring functions.
* Models.
* Schemas.
* Enums.
* Constants.
* Helpers.
* Database repositories.
* SQL queries.
* Configuration.
* Required libraries.

Avoid importing unrelated functionality from the reference repository.

The objective is to integrate the fraud engine cleanly into the current architecture, not to merge both repositories completely.

---

### 3. Preserve Existing Fraud-Detection Behavior

The fraud detection logic from the reference repository must remain functionally equivalent.

Do not arbitrarily modify:

* Thresholds.
* Fraud rules.
* Detection criteria.
* Scoring formulas.
* Risk weights.
* Classification logic.
* Heuristic behavior.

If architectural adaptations are necessary, preserve the existing business logic.

When a behavioral change is unavoidable, document:

* What changed.
* Why it changed.
* Original behavior.
* New behavior.

---

### 4. Integrate the Engine Into the Current Architecture

Adapt the fraud engine to the architecture of this repository.

Follow the existing project conventions for:

* Routers/controllers.
* Services.
* Models.
* Schemas.
* Database access.
* Configuration.
* Dependency injection.
* Error handling.
* Logging.
* Response formats.

Do not create a completely separate application inside this repository.

The fraud engine should behave as a native module of the current backend.

Prefer a clear separation similar to:

```text
app/
  api/
  services/
  fraud/
    engine/
    rules/
    models/
    schemas/
    scoring/
  database/
```

Only use this structure if it is compatible with the architecture already present in this repository.

Existing project structure takes priority.

---

### 5. Integrate Existing Fraud Endpoints

Inspect all fraud-related endpoints available in the reference repository.

Determine which endpoints are necessary for this project's functionality.

Recreate/adapt those endpoints in this backend.

For each endpoint preserve, when appropriate:

* HTTP method.
* Purpose.
* Input data.
* Validation.
* Fraud evaluation behavior.
* Response data.
* Error behavior.

The implementation does not need to preserve the exact URL structure if this repository already has a clear API convention.

Prefer consistency with the current API.

---

### 6. Create a Main Fraud Analysis Endpoint

There should be a clear endpoint capable of receiving normalized financial/accounting data and running the fraud engine against it.

Conceptually:

```http
POST /api/v1/fraud/analyze
```

The endpoint should:

1. Validate the request.
2. Normalize the input if necessary.
3. Execute all applicable fraud rules.
4. Collect triggered indicators.
5. Calculate scores/risk values if supported by the engine.
6. Return a structured result.

The response should expose enough information for the frontend or future investigation engine to understand why something was flagged.

Prefer a response conceptually similar to:

```json
{
  "status": "completed",
  "risk_level": "high",
  "risk_score": 82,
  "rules_evaluated": 24,
  "rules_triggered": 6,
  "findings": [
    {
      "rule": "round_tripping",
      "category": "transaction_pattern",
      "severity": "high",
      "score": 20,
      "triggered": true,
      "description": "Potential circular transaction pattern detected",
      "evidence": {}
    }
  ]
}
```

Do NOT force this exact response if the reference engine already has a better or more complete data model.

Preserve useful existing information.

---

### 7. Rule Execution

The engine should allow rules to be executed independently whenever possible.

Avoid one giant function containing all fraud checks.

Each rule should ideally:

* Have a unique identifier.
* Have a name.
* Belong to a category.
* Receive clearly defined input.
* Return a deterministic result.
* Explain whether it was triggered.
* Return supporting evidence.
* Return severity or score where applicable.

The rule engine should then aggregate those results.

If the reference repository already uses a clean rule architecture, preserve it.

---

### 8. Fraud Evidence

When a rule is triggered, return the evidence that caused the rule to trigger whenever possible.

Examples:

```json
{
  "transaction_ids": ["tx_102", "tx_141"],
  "amount": 950000,
  "threshold": 500000,
  "difference_seconds": 35
}
```

This system will eventually be used to explain findings to companies and auditors.

For that reason, fraud detections should be explainable and auditable.

Avoid returning only:

```json
{
  "fraud": true
}
```

when the engine already has enough information to explain the finding.

---

### 9. Database Integration

The database is PostgreSQL and is already running through Docker using the official PostgreSQL image.

Inspect the existing database integration in this repository before making changes.

If the fraud engine requires new tables:

* Add them to the existing database schema.
* Add seed/reference data when required.
* Add indexes when useful.
* Add foreign keys when appropriate.
* Keep naming conventions consistent.

Use the existing SQL files:

```text
database/database.sql
database/exec.sql
database/alter.sql
```

Use them as follows:

### `database/database.sql`

Contains the complete current database schema required to initialize the project from zero.

### `database/exec.sql`

Contains:

* Seed data.
* Initial fraud-rule data.
* Reference data.
* Required initialization data.

### `database/alter.sql`

Contains incremental schema changes introduced after the original database structure.

Do not duplicate tables that already exist.

---

### 10. Database Migrations / Adaptation

Compare the database requirements of:

* This repository.
* The reference fraud-engine repository.

If the reference engine relies on a different schema, adapt the engine to the current schema whenever reasonable.

Do not copy the entire database from the other repository without understanding its purpose.

If new tables are truly required, create them cleanly.

---

### 11. Performance

Fraud analysis may eventually process large numbers of:

* Transactions.
* Invoices.
* Companies.
* Accounts.
* Relationships.

Avoid obvious inefficient patterns.

Examples of things to avoid:

* One database query per transaction.
* Loading unnecessary entire tables into memory.
* Repeated parsing of the same data.
* Recomputing the same indexes/maps for every rule.

Prefer:

* Bulk queries.
* Indexed database lookups.
* Efficient in-memory maps.
* Precomputed aggregates.
* Batch rule execution.

Do not prematurely overengineer distributed processing.

Keep the implementation simple unless the existing engine requires otherwise.

---

### 12. Deterministic Rules

Fraud detection rules should be deterministic unless the original implementation explicitly uses probabilistic or ML-based logic.

Given the same:

* Input.
* Configuration.
* Database state.

The same rules should return the same results.

---

### 13. Do Not Break Existing Features

Before modifying shared components, understand what currently depends on them.

The integration must not break:

* Existing SAT blacklist endpoint.
* Existing database initialization.
* Existing APIs.
* Existing models.
* Existing Docker setup.
* Existing application startup.

---

### 14. Dependencies

Inspect the reference repository's dependency files.

Add only required packages to this project.

Examples may include:

* Data processing libraries.
* Graph libraries.
* Statistical libraries.
* Database drivers.

Do not copy dependencies that are unrelated to the fraud engine.

Make sure the current project's dependency management remains consistent.

If this repository uses `uv`, use `uv`.

---

### 15. Error Handling

Handle errors explicitly.

Examples:

* Invalid input.
* Missing required financial information.
* Unsupported transaction format.
* Database unavailable.
* Rule execution failure.
* Invalid rule configuration.

One broken rule should not necessarily crash the complete analysis if the engine architecture allows rules to be isolated.

If a rule fails independently, consider returning:

```json
{
  "rule": "rule_name",
  "status": "error",
  "error": "..."
}
```

while allowing the remaining rules to continue.

Only implement this behavior if it does not compromise the integrity of the analysis.

---

### 16. Logging

Add useful logging around:

* Fraud analysis requests.
* Analysis start/end.
* Number of records analyzed.
* Rules executed.
* Rules triggered.
* Rule failures.
* Database failures.

Do not log sensitive financial payloads unnecessarily.

---

### 17. Testing

Reuse tests from the reference repository whenever possible.

Create or adapt tests for the integrated implementation.

At minimum test:

* A valid request.
* A transaction that triggers a rule.
* A transaction that does not trigger a rule.
* Multiple rules executing together.
* Invalid input.
* Empty input.
* Database-dependent rules.
* Existing endpoints after the integration.

Compare representative outputs against the original repository.

The integrated engine should produce equivalent results.

---

### 18. Validate Against the Original Repository

Before considering the task complete, execute equivalent test cases in:

1. The original `motor-agente-forense` repository.
2. This repository.

Compare the results.

The objective is functional equivalence of the fraud detection engine.

---

### 19. Documentation

Document:

* Fraud engine architecture.
* Available rules.
* Fraud categories.
* How rules are executed.
* Main analysis endpoint.
* Request schema.
* Response schema.
* How to add a new fraud rule.
* Required environment variables.
* Database requirements.

If this repository already has project documentation files, update them instead of creating redundant documentation.

---

### 20. Keep Project Context Updated

After completing the implementation, update the relevant project context/documentation files with:

* What was integrated.
* What files were created.
* What files were modified.
* What endpoints were created.
* What database changes were introduced.
* What dependencies were added.
* Important architectural decisions.
* Known limitations.

This is important so future Claude Code sessions can continue without losing context.

---

## WHAT NOT TO DO

* Do NOT rewrite the fraud engine from scratch without first studying the existing implementation.
* Do NOT modify fraud rules just because another implementation looks cleaner.
* Do NOT silently change thresholds.
* Do NOT silently change scoring formulas.
* Do NOT silently remove fraud indicators.
* Do NOT invent new business rules unless required.
* Do NOT copy the entire reference repository.
* Do NOT introduce unrelated features.
* Do NOT duplicate existing database tables.
* Do NOT replace the existing project's architecture.
* Do NOT create another independent FastAPI application inside this project.
* Do NOT depend on files outside this repository at runtime.
* Do NOT hardcode absolute paths from the development machine.
* Do NOT expose sensitive financial data in logs.
* Do NOT remove existing endpoints.
* Do NOT break the SAT blacklist functionality.
* Do NOT use mock implementations when the real logic already exists.
* Do NOT return fake fraud results.
* Do NOT mark the task complete until the engine has actually been executed and validated.
* Do NOT stop after merely copying files; everything must be connected to the running application.
* Do NOT ask me questions that can be answered by inspecting either repository.
* Do NOT repeat completed work.

---

## REFERENCES

### Reference Fraud Engine Repository

```text
/Users/froot/Documents/workspace/fernandovmedina/web/motor-agente-forense
```

This repository is the source of truth for the existing fraud-detection rules and engine behavior.

### Current Repository

This repository is the application where the fraud engine must be integrated.

### Database

PostgreSQL is already running through Docker using the official PostgreSQL image.

Inspect the current Docker configuration and database configuration before modifying anything.

Relevant database files:

```text
database/database.sql
database/exec.sql
database/alter.sql
```

---

## IMPLEMENTATION ORDER

Follow this order:

1. Read the current repository architecture.
2. Read the current database schema.
3. Read the complete relevant fraud-engine code from `motor-agente-forense`.
4. Map the architecture and dependencies of the fraud engine.
5. Identify exactly which components need to be ported.
6. Identify database/schema differences.
7. Write a short internal integration plan.
8. Port the fraud engine.
9. Adapt it to the current architecture.
10. Integrate the database requirements.
11. Integrate the API endpoints.
12. Add/update tests.
13. Run the current project tests.
14. Run fraud-engine tests.
15. Compare behavior with the reference repository.
16. Fix incompatibilities.
17. Update documentation/context.
18. Perform one final end-to-end API test.

Do not skip directly to implementation before understanding the reference engine.

---

## COMPLETION CRITERIA

TASK #3 is complete only when:

* The required fraud rules from the reference repository exist in this repository.
* The fraud engine executes successfully.
* The engine no longer depends on the reference repository at runtime.
* Required API endpoints are available.
* PostgreSQL integration works.
* Required schema changes exist.
* Required dependencies are installed.
* Existing functionality still works.
* Representative fraud cases produce equivalent results to the reference implementation.
* Tests pass.
* The API can execute an end-to-end fraud analysis.
* Documentation/context has been updated.

---

## IMPORTANT
Inside the other repository loaded on this one session, inside the datasets/ folder, there is a README.md file with the rules and
context of this usage data that has to be used to check/test the engine

---

## FEEDBACK

If you encounter a genuine product or architectural decision that cannot be answered from:

* The current repository.
* The reference repository.
* Existing documentation.
* Existing database schema.

Then ask me through the Claude Code terminal.

Otherwise, make the most reasonable engineering decision and continue without interrupting the implementation.
