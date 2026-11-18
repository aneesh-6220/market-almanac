import pandas as pd

from exercises.ex7_observation_hash import observation_hash

BASE = pd.DataFrame(
    {
        "market": ["Babile", "Jijiga"],
        "period": ["2026-09-01", "2026-09-01"],
        "price": [8000.0, 7600.0],
        "retrieved_at": ["2026-11-18T01:56:04Z", "2026-11-18T01:56:04Z"],
    }
)


def test_ignores_retrieval_time_and_order():
    later = BASE.assign(retrieved_at="2026-12-01T00:00:00Z").iloc[::-1][["price", "retrieved_at", "period", "market"]]
    assert observation_hash(BASE) == observation_hash(later)
    assert len(observation_hash(BASE)) == 64


def test_detects_a_revised_price():
    revised = BASE.copy()
    revised.loc[0, "price"] = 8100.0
    assert observation_hash(BASE) != observation_hash(revised)


def test_detects_a_removed_row():
    assert observation_hash(BASE) != observation_hash(BASE.iloc[:1])
