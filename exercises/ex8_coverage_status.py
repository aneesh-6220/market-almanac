"""Exercise 8: coverage status rules of the registry.

See docs/SYSTEMS_WALKTHROUGH.md, section 3.
"""


def coverage_status(
    *,
    discovered: bool,
    stored: bool,
    validated: bool,
    eligible_series: int,
    evaluated: bool,
    last_attempt_failed: bool,
    min_eligible: int = 10,
) -> str:
    """Return one of: unsupported, discoverable, temporarily_unavailable, ingested, validated,
    research_eligible, forecast_evaluated.

    - nothing stored: ``unsupported`` if no provider lists the country; otherwise
      ``temporarily_unavailable`` if the last attempt failed, else ``discoverable``;
    - stored but QC not passed: ``ingested``;
    - validated with fewer than ``min_eligible`` eligible series: ``validated``;
    - otherwise ``forecast_evaluated`` if evaluated, else ``research_eligible``.
    """
    raise NotImplementedError
