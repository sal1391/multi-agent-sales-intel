"""Abuse protection for the demo email gate.

Two layers apply to this Streamlit gate:

1. Per-IP rate limiting — in-memory, per-process (resets on deploy, which is an
   acceptable tradeoff for a low-traffic demo, per the anti-bot handoff).
2. Cloudflare Turnstile — env-gated and OFF unless both TURNSTILE_SITE_KEY and
   TURNSTILE_SECRET_KEY are set. ``verify_turnstile`` returns True while disabled
   so the gate keeps working until keys are provisioned in Railway.

The honeypot layer from the handoff is intentionally omitted here: Streamlit
submits only its own widget values over a websocket, so an injected hidden HTML
input never reaches Python. The websocket + JS requirement already blocks the
naive HTTP bots a honeypot targets.
"""
from __future__ import annotations

import json
import os
import threading
import time
import urllib.parse
import urllib.request

# --- Rate limiting -----------------------------------------------------------
RATE_LIMIT_MAX = int(os.getenv("DEMO_RATE_LIMIT_MAX", "5"))
RATE_LIMIT_WINDOW_SEC = int(os.getenv("DEMO_RATE_LIMIT_WINDOW_SEC", str(60 * 60)))

_lock = threading.Lock()
_hits: dict[str, list[float]] = {}


def _now() -> float:
    return time.time()


def is_rate_limited(ip: str) -> bool:
    """True if this IP has used up its allowance in the window.

    Does not record the attempt — call ``record_attempt`` once a submission is
    accepted. An empty IP (caller unidentifiable) is never blocked.
    """
    if not ip:
        return False
    cutoff = _now() - RATE_LIMIT_WINDOW_SEC
    with _lock:
        recent = [t for t in _hits.get(ip, []) if t >= cutoff]
        _hits[ip] = recent
        return len(recent) >= RATE_LIMIT_MAX


def record_attempt(ip: str) -> None:
    """Record an accepted submission timestamp for this IP."""
    if not ip:
        return
    cutoff = _now() - RATE_LIMIT_WINDOW_SEC
    with _lock:
        recent = [t for t in _hits.get(ip, []) if t >= cutoff]
        recent.append(_now())
        _hits[ip] = recent


def reset() -> None:
    """Test hook — clear all recorded attempts."""
    with _lock:
        _hits.clear()


# --- Client IP (Streamlit) ---------------------------------------------------
def get_client_ip() -> str:
    """Best-effort client IP from Railway's X-Forwarded-For header."""
    try:
        import streamlit as st

        headers = st.context.headers or {}
        fwd = headers.get("X-Forwarded-For") or headers.get("x-forwarded-for")
        if fwd:
            return fwd.split(",")[0].strip()
    except Exception:
        pass
    return ""


# --- Cloudflare Turnstile (env-gated, OFF by default) ------------------------
_SITEVERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"


def turnstile_enabled() -> bool:
    return bool(os.getenv("TURNSTILE_SITE_KEY") and os.getenv("TURNSTILE_SECRET_KEY"))


def verify_turnstile(token: str, ip: str = "") -> bool:
    """Verify a Turnstile token. Returns True when Turnstile is disabled so the
    gate keeps working until keys are provisioned."""
    if not turnstile_enabled():
        return True
    data = urllib.parse.urlencode(
        {
            "secret": os.getenv("TURNSTILE_SECRET_KEY", ""),
            "response": token or "",
            "remoteip": ip or "",
        }
    ).encode()
    try:
        with urllib.request.urlopen(_SITEVERIFY_URL, data=data, timeout=5) as resp:
            payload = json.loads(resp.read().decode())
        return bool(payload.get("success"))
    except Exception:
        return False


def render_turnstile_widget() -> None:
    """Render the Turnstile challenge when enabled (no-op otherwise).

    NOTE: passing the solved token back into Streamlit requires a custom
    component (e.g. streamlit-turnstile). Until keys are provisioned this is a
    no-op; the render is here so enabling the env vars surfaces the widget.
    """
    if not turnstile_enabled():
        return
    try:
        import streamlit.components.v1 as components

        site_key = os.getenv("TURNSTILE_SITE_KEY", "")
        components.html(
            '<script src="https://challenges.cloudflare.com/turnstile/v0/api.js" '
            'async defer></script>'
            f'<div class="cf-turnstile" data-sitekey="{site_key}"></div>',
            height=80,
        )
    except Exception:
        pass
