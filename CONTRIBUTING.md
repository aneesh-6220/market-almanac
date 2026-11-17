# Contributing to ShockTrace

Thank you for helping. ShockTrace is research software: correctness and honesty about
uncertainty matter more than features.

## Getting started

See [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) for setup. In short: `make setup`, `make demo`,
`make dev`, and `make lint test test-web` before opening a pull request.

## What a good pull request includes

- A focused change with a clear description of what and why.
- Tests: unit tests for new code; a scientific-correctness test for anything that touches
  timing, features, targets, splits or evaluation.
- Documentation updates (methodology, data dictionary, API) when behaviour changes.
- No credentials, `.env` files, raw provider dumps or generated data in commits. Fixtures must be
  small, real, and stripped of credentials.

## Scientific ground rules

These are non-negotiable and enforced by `tests/scientific/`:

1. No look-ahead: every feature at origin *t* uses only information available by *t*.
2. Chronological evaluation only; preprocessing and tuning are fitted on training data.
3. Missing outcomes are missing, never negative events or zero changes.
4. Incompatible series (unit, currency, price type) are never merged.
5. Forecasts are never labelled validated without an out-of-sample evaluation.
6. Null and mixed results are reported as such; verdict rules are not tuned to produce findings.
7. No causal language for predictive results.
8. Live mode never falls back to synthetic data.

If you believe a rule is wrong, open an issue to discuss the methodology before changing code.

## Reporting bugs and data problems

Open an issue with steps to reproduce, the mode (demo/live), the experiment or snapshot ID, and
the output of `shocktrace doctor`. Never paste credentials or `.env` contents. For security
issues follow [SECURITY.md](SECURITY.md).

## Code of conduct

Participation is governed by [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).
