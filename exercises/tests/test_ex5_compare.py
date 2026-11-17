from exercises.ex5_compare import comparability


def s(**kw):
    base = {"commodity_name": "Millet", "price_type": "Retail", "unit": "KG", "currency": "XOF"}
    return {**base, **kw}


def test_rules():
    assert comparability([s()]) == "invalid"
    assert comparability([s(), s(unit="100 KG")]) == "invalid"
    assert comparability([s(), s(price_type="Wholesale")]) == "invalid"
    assert comparability([s(), s(currency="NGN")]) == "indexed_only"
    assert comparability([s(), s()]) == "absolute_and_indexed"


def test_case_and_whitespace_ignored():
    assert comparability([s(), s(commodity_name=" millet ", unit="kg")]) == "absolute_and_indexed"
