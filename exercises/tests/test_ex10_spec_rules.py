from exercises.ex10_spec_rules import coherence_problems

GOOD = {
    "study_type": "predictive",
    "evidence_class": "confirmatory",
    "countries": ["ETH", "RWA", "SDN", "TZA", "UGA"],
    "hypotheses": ["H1", "H2"],
    "multiplicity": "holm",
    "negative_controls": ["weather_time_shift_60"],
    "bootstrap": "two_way_country_month",
}


def has(problems, word):
    return any(word in p for p in problems)


def test_coherent_spec_passes():
    assert coherence_problems(GOOD) == []


def test_each_rule():
    assert has(coherence_problems({**GOOD, "study_type": "causal"}), "causal")
    assert has(coherence_problems({**GOOD, "study_type": "descriptive"}), "descriptive")
    assert has(coherence_problems({**GOOD, "hypotheses": []}), "hypothes")
    assert has(coherence_problems({**GOOD, "multiplicity": "none"}), "multiplicity")
    assert has(coherence_problems({**GOOD, "negative_controls": []}), "negative control")
    assert has(coherence_problems({**GOOD, "countries": ["ETH", "UGA"]}), "5 countries")


def test_exploratory_is_lenient_but_bootstrap_rule_still_applies():
    exp = {**GOOD, "evidence_class": "exploratory", "hypotheses": [], "negative_controls": [], "multiplicity": "none"}
    assert coherence_problems(exp) == []
    assert has(coherence_problems({**exp, "countries": ["ETH"]}), "5 countries")
