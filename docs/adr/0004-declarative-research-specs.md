# ADR 0004: Declarative research specifications

**Status:** accepted, 2026-11-17

## Context

The mandate asks for a research workbench usable from the UI, but the public site must never run
untrusted code, and confirmatory studies must be fixed before results are seen.

## Decision

A study is a YAML document validated by a strict Pydantic model (`workbench/spec.py`,
`spec_version: ma-research-spec/1`, unknown keys rejected). Beyond types, `coherence_problems`
enforces scientific rules: confirmatory studies need hypotheses, a multiplicity method, robustness
checks and negative controls; descriptive studies cannot be confirmatory; country bootstraps need at
least five countries; causal studies are rejected because no identified estimator exists. The
canonical JSON of the parsed spec is hashed (`spec_hash`).

`research freeze` records the spec hash, git commit (refusing a dirty tree for confirmatory work),
the selected groups and series, and the hash of every input snapshot. `research run` refuses to run
a confirmatory spec whose freeze does not match.

The API exposes only `POST /api/v1/workbench/validate` (64 KB cap, `yaml.safe_load`, no file or
network access) and read-only study endpoints.

## Alternatives rejected

- **Notebook or Python plug-ins:** arbitrary code execution; not reviewable as a protocol.
- **Server-side runs from the browser:** memory (the descriptive study peaked at 1.7 GB locally) and
  abuse risk on a free instance.

## Consequences

- New model families or estimators require code changes and a new spec version, by design.
- The UI builder writes YAML that the same validator checks; the CLI is the only executor.
