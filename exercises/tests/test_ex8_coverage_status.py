import itertools

from exercises.ex8_coverage_status import coverage_status
from market_almanac.globaldata.registry import classify


def test_examples():
    kw = dict(discovered=True, stored=True, validated=True, evaluated=False, last_attempt_failed=False)
    assert coverage_status(eligible_series=9, **kw) == "validated"
    assert coverage_status(eligible_series=10, **kw) == "research_eligible"
    assert (
        coverage_status(
            discovered=False,
            stored=False,
            validated=False,
            eligible_series=0,
            evaluated=False,
            last_attempt_failed=False,
        )
        == "unsupported"
    )


def test_matches_the_registry_for_every_combination():
    for d, s, v, ev, f in itertools.product([False, True], repeat=5):
        for n in (0, 9, 10, 250):
            kw = dict(discovered=d, stored=s, validated=v, eligible_series=n, evaluated=ev, last_attempt_failed=f)
            assert coverage_status(**kw) == classify(**kw), kw
