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

# TASK #2
