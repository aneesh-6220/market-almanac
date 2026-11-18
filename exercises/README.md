# Exercises

Five self-contained exercises from [docs/ENGINEERING_LEARNING_GUIDE.md](../docs/ENGINEERING_LEARNING_GUIDE.md).
Implement the function in each `exN_*.py` (each currently raises `NotImplementedError`), then run:

```bash
uv run pytest exercises/tests -q              # all
uv run pytest exercises/tests/test_ex1_holm.py -q
```

These tests are not part of `make test`. They fail until you implement the stubs.

## Global platform exercises (6–10)

Added with the global expansion. Each one re-implements a small, load-bearing piece of the new
system; the tests compare your answer with hand-computed cases or with the project's own function.

| # | File | Concept | Read first |
|---|---|---|---|
| 6 | `ex6_country_balance.py` | country-balanced loss (the atlas estimand) | [RESEARCH_DESIGN_EXPLAINED §3](../docs/RESEARCH_DESIGN_EXPLAINED.md) |
| 7 | `ex7_observation_hash.py` | order-independent content hash that ignores retrieval time | [ADR 0001](../docs/adr/0001-country-partitioned-lake.md) |
| 8 | `ex8_coverage_status.py` | registry status rules (tested against `registry.classify`) | [SYSTEMS_WALKTHROUGH §3](../docs/SYSTEMS_WALKTHROUGH.md) |
| 9 | `ex9_hln.py` | Diebold–Mariano with Newey–West and the HLN correction (tested against `diebold_mariano`) | [RESEARCH_DESIGN_EXPLAINED §4](../docs/RESEARCH_DESIGN_EXPLAINED.md) |
| 10 | `ex10_spec_rules.py` | scientific coherence rules for a specification | [ADR 0004](../docs/adr/0004-declarative-research-specs.md) |
