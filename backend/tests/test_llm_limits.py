"""Rate-limit handling: report the provider's real reset time, not a guess."""
from __future__ import annotations

import pytest

from app.services.llm import _describe_wait, _parse_duration, _retry_delay


class FakeResponse:
    def __init__(self, headers: dict) -> None:
        self.headers = headers


# ---------- duration parsing ----------
@pytest.mark.parametrize(
    "value,expected",
    [
        ("53.28s", 53.28),
        ("1m26.4s", 86.4),
        ("2m", 120.0),
        ("577ms", 0.577),
        ("1h2m", 3720.0),
        ("30", 30.0),  # bare retry-after seconds
    ],
)
def test_groq_duration_formats(value: str, expected: float) -> None:
    assert _parse_duration(value) == pytest.approx(expected, rel=1e-3)


def test_unparseable_duration_is_none() -> None:
    assert _parse_duration(None) is None
    assert _parse_duration("") is None
    assert _parse_duration("soon") is None


# ---------- header preference ----------
def test_retry_after_wins_over_reset_headers() -> None:
    resp = FakeResponse({"retry-after": "5", "x-ratelimit-reset-tokens": "60s"})
    assert _retry_delay(resp) == 5.0


def test_falls_back_to_token_reset() -> None:
    """The token budget is the limit that actually bites, so prefer it over requests."""
    resp = FakeResponse({"x-ratelimit-reset-tokens": "12s", "x-ratelimit-reset-requests": "9m"})
    assert _retry_delay(resp) == 12.0


def test_no_headers_means_no_estimate() -> None:
    assert _retry_delay(FakeResponse({})) is None


# ---------- user-facing wording ----------
def test_wait_message_uses_real_numbers() -> None:
    assert "12 seconds" in _describe_wait(12)
    assert "1 minute" in _describe_wait(65)


def test_wait_message_without_an_estimate_does_not_invent_one() -> None:
    """The old message promised "a few seconds" for what could be a minute."""
    message = _describe_wait(None)
    assert "second" not in message
    assert "minute" in message


def test_short_waits_round_up_to_at_least_one_second() -> None:
    assert "1 seconds" in _describe_wait(0.2)


# ---------- automatic retry ----------
class _FakeResp:
    def __init__(self, status, headers=None, payload=None):
        self.status_code = status
        self.headers = headers or {}
        self._payload = payload or {}
        self.text = "fake"

    def json(self):
        return self._payload


class _FakeClient:
    """Returns a queued sequence of responses, recording how many calls happened."""

    def __init__(self, responses):
        self.responses = responses
        self.calls = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, *a, **kw):
        self.calls += 1
        return self.responses.pop(0)


OK = _FakeResp(
    200,
    {"x-ratelimit-remaining-tokens": "5000"},
    {"choices": [{"message": {"content": '{"ok": true}'}}], "usage": {"total_tokens": 10}},
)


@pytest.fixture
def patched(monkeypatch):
    """Give the client a key and a stubbed transport."""
    import app.config as config
    import app.services.llm as llm_mod

    config.get_settings.cache_clear()
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    config.get_settings.cache_clear()

    def install(responses):
        client = _FakeClient(responses)
        monkeypatch.setattr(llm_mod.httpx, "AsyncClient", lambda **kw: client)
        return client

    yield install
    config.get_settings.cache_clear()


@pytest.mark.asyncio
async def test_short_rate_limit_is_retried_automatically(patched, monkeypatch) -> None:
    import app.services.llm as llm_mod

    slept: list[float] = []

    async def fake_sleep(s):
        slept.append(s)

    monkeypatch.setattr(llm_mod.asyncio, "sleep", fake_sleep)
    client = patched([_FakeResp(429, {"x-ratelimit-reset-tokens": "3s"}), OK])

    result = await llm_mod.complete("sys", "user")

    assert result == '{"ok": true}'
    assert client.calls == 2, "should have retried once"
    assert slept and slept[0] == pytest.approx(3.5, rel=0.1)


@pytest.mark.asyncio
async def test_long_rate_limit_is_reported_not_waited_out(patched, monkeypatch) -> None:
    """A two-minute wait must surface as a message, not a two-minute hang."""
    import app.services.llm as llm_mod

    async def must_not_sleep(_):
        raise AssertionError("should not wait out a long limit")

    monkeypatch.setattr(llm_mod.asyncio, "sleep", must_not_sleep)
    client = patched([_FakeResp(429, {"x-ratelimit-reset-tokens": "2m"})])

    with pytest.raises(llm_mod.RateLimited) as err:
        await llm_mod.complete("sys", "user")

    assert client.calls == 1
    assert err.value.retry_after == pytest.approx(120.0)
    assert "2 minute" in str(err.value)


@pytest.mark.asyncio
async def test_retry_happens_only_once(patched, monkeypatch) -> None:
    """Two 429s in a row must give up rather than loop."""
    import app.services.llm as llm_mod

    async def no_sleep(_):
        # Patching llm_mod.asyncio patches the asyncio module itself, so this must
        # not call asyncio.sleep or it recurses into its own stub.
        return None

    monkeypatch.setattr(llm_mod.asyncio, "sleep", no_sleep)
    headers = {"x-ratelimit-reset-tokens": "2s"}
    client = patched([_FakeResp(429, headers), _FakeResp(429, headers)])

    with pytest.raises(llm_mod.RateLimited):
        await llm_mod.complete("sys", "user")

    assert client.calls == 2
