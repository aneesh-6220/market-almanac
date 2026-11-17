from __future__ import annotations

import httpx
import pytest

from shocktrace.http import ProviderHTTPError, backoff_delay, parse_retry_after
from shocktrace.logging import redact
from tests.conftest import run

URL = "https://api.worldbank.org/v2/x"


def test_retries_then_succeeds(make_http):
    calls = {"n": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(503) if calls["n"] < 3 else httpx.Response(200, json={"ok": True})

    client, rec, sleeps = make_http(handler, retries=3)
    assert run(client.get_json(URL)) == {"ok": True}
    assert len(rec.requests) == 3
    assert len(sleeps) == 2


def test_retry_after_header_is_respected(make_http):
    calls = {"n": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(429, headers={"Retry-After": "7"}) if calls["n"] == 1 else httpx.Response(200, json=[])

    client, _, sleeps = make_http(handler)
    run(client.get_json(URL))
    assert sleeps == [7.0]


def test_non_retryable_error_raises_immediately(make_http):
    client, rec, _ = make_http(lambda r: httpx.Response(404))
    with pytest.raises(ProviderHTTPError) as e:
        run(client.get_json(URL))
    assert e.value.status_code == 404
    assert len(rec.requests) == 1


def test_network_failure_after_retries(make_http):
    def handler(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom")

    client, rec, _ = make_http(handler, retries=2)
    with pytest.raises(ProviderHTTPError) as e:
        run(client.get_json(URL))
    assert e.value.retryable
    assert len(rec.requests) == 3


def test_disallowed_host_rejected(make_http):
    client, rec, _ = make_http(lambda r: httpx.Response(200))
    with pytest.raises(ProviderHTTPError, match="not allowed"):
        run(client.get_json("https://evil.example.com/steal"))
    assert rec.requests == []


def test_malformed_json(make_http):
    client, _, _ = make_http(lambda r: httpx.Response(200, text="<html>"))
    with pytest.raises(ProviderHTTPError, match="Malformed JSON"):
        run(client.get_json(URL))


def test_cache_hit_and_secret_excluded_from_cache_key(make_http, tmp_path):
    client, rec, _ = make_http(lambda r: httpx.Response(200, json={"v": 1}), cache=True)
    run(client.get_json(URL, params={"a": 1}, secret_headers={"X-Key": "SECRET123"}))
    run(client.get_json(URL, params={"a": 1}, secret_headers={"X-Key": "OTHER"}))
    assert len(rec.requests) == 1  # second served from cache
    assert rec.requests[0].headers["X-Key"] == "SECRET123"
    for f in tmp_path.rglob("*.json"):
        assert "SECRET123" not in f.read_text()


def test_retry_after_http_date_and_backoff_bounds():
    assert parse_retry_after("Wed, 21 Oct 2015 07:28:00 GMT", now=1445412480.0) == pytest.approx(0.0)
    assert parse_retry_after(None) is None
    assert parse_retry_after("garbage") is None
    for a in range(6):
        assert 0 <= backoff_delay(a, 1.0, 10.0) <= 10.0


def test_redaction():
    s = redact("https://x?app_identifier=abc123&y=1 Authorization: Bearer eyJabc.def postgresql://u:pw@h/db")
    assert "abc123" not in s and "eyJabc" not in s and ":pw@" not in s
