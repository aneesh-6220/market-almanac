"""Exercise 10: scientific coherence rules for a research specification.

See docs/adr/0004-declarative-research-specs.md.
"""

from typing import Any


def coherence_problems(spec: dict[str, Any]) -> list[str]:
    """Return a list of problems (empty if coherent) for a minimal spec dictionary with keys
    ``study_type``, ``evidence_class``, ``countries`` (list), ``hypotheses`` (list),
    ``multiplicity`` (str), ``negative_controls`` (list) and ``bootstrap`` (str).

    Rules (one message per broken rule; wording is up to you, but each message must contain the
    quoted keyword):
    1. study_type "causal" is not supported                                  -> "causal"
    2. a descriptive study cannot be confirmatory                            -> "descriptive"
    3. a confirmatory predictive study needs at least one hypothesis         -> "hypothes"
    4. a confirmatory study with 2+ hypotheses needs multiplicity != "none"  -> "multiplicity"
    5. a confirmatory predictive study needs at least one negative control   -> "negative control"
    6. bootstrap "two_way_country_month" or "country_cluster" needs 5+ countries -> "5 countries"
    """
    raise NotImplementedError
