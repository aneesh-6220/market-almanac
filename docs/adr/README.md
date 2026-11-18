# Architecture decision records

One record per subsystem decision taken during the global expansion (November 2026). Each states
the context, the decision, the alternatives rejected and the consequences, so a maintainer can tell
which constraints are deliberate.

| ADR | Decision |
|---|---|
| [0001](0001-country-partitioned-lake.md) | Country-partitioned, immutable price lake beside the existing single-snapshot lake |
| [0002](0002-resumable-ingestion-run-log.md) | Resumable ingestion driven by a JSON run log, not a queue or database |
| [0003](0003-materialized-coverage-registry.md) | Coverage registry materialized offline and served as a small JSON document |
| [0004](0004-declarative-research-specs.md) | Research studies as validated, hashed specifications; no code execution on the server |
| [0005](0005-country-balanced-two-way-inference.md) | Country-balanced estimand with month-level tests and a two-way bootstrap |
| [0006](0006-local-execution-published-summaries.md) | Studies run locally; production serves packaged summaries |
