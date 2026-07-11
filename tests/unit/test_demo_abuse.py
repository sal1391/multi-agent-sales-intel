"""Rate limiter + Turnstile scaffold for the demo email gate."""
import demo_abuse


def setup_function():
    demo_abuse.reset()


def test_allows_up_to_max_then_blocks():
    ip = "1.2.3.4"
    for _ in range(demo_abuse.RATE_LIMIT_MAX):
        assert not demo_abuse.is_rate_limited(ip)
        demo_abuse.record_attempt(ip)
    assert demo_abuse.is_rate_limited(ip)


def test_per_ip_isolation():
    for _ in range(demo_abuse.RATE_LIMIT_MAX):
        demo_abuse.record_attempt("9.9.9.9")
    assert demo_abuse.is_rate_limited("9.9.9.9")
    assert not demo_abuse.is_rate_limited("8.8.8.8")


def test_window_expiry(monkeypatch):
    ip = "5.5.5.5"
    clock = [1000.0]
    monkeypatch.setattr(demo_abuse, "_now", lambda: clock[0])
    for _ in range(demo_abuse.RATE_LIMIT_MAX):
        demo_abuse.record_attempt(ip)
    assert demo_abuse.is_rate_limited(ip)
    clock[0] += demo_abuse.RATE_LIMIT_WINDOW_SEC + 1
    assert not demo_abuse.is_rate_limited(ip)


def test_empty_ip_never_blocks():
    for _ in range(demo_abuse.RATE_LIMIT_MAX * 2):
        assert not demo_abuse.is_rate_limited("")
        demo_abuse.record_attempt("")


def test_turnstile_disabled_passes(monkeypatch):
    monkeypatch.delenv("TURNSTILE_SITE_KEY", raising=False)
    monkeypatch.delenv("TURNSTILE_SECRET_KEY", raising=False)
    assert demo_abuse.turnstile_enabled() is False
    assert demo_abuse.verify_turnstile("anything", "1.2.3.4") is True
