"""Privacy notice for the demo email gate.

Streamlit has no user-defined URL routes, so the notice is shown as an in-app
modal (st.dialog) opened from a link under the email input, rather than a real
``/privacy`` page. The canonical text below is the single source for this app and
is kept identical across all six demo apps — if it changes, update it everywhere.
"""
from __future__ import annotations

import streamlit as st

# One-line disclosure shown under the Start button on the gate.
GATE_SNIPPET = (
    "We record your IP address to prevent abuse of the demo — no marketing, no tracking."
)

PRIVACY_MD = """## Privacy Notice

Last updated: July 11, 2026

This site hosts a set of product demos. To limit abuse, we record basic technical
information when you use a demo. This page explains what.

### What we collect

- Your IP address and request timestamps, recorded when you start a demo, used to
  prevent abuse (e.g. rate-limiting, blocking bad actors).
- Standard hosting/request logs generated automatically by our hosting provider
  (Railway).

We do not ask for your email or any account details, and we do not use cookies,
analytics, or third-party tracking scripts on these demo pages.

### Why we collect it

Solely to prevent abuse and misuse of the demos. We do not use this information
for marketing.

### Sharing

We do not sell or share this information with third parties. It is used only for
the purpose described above.

### Retention

Abuse-prevention records (IP address and timestamps) are kept for 30 days, after
which they are deleted.

### These demos

These are demo/test environments, not production services. Please don't enter
real, sensitive, or production data into any of them.

### Your choices

You can ask us about or request deletion of the technical records tied to your IP
address at any time by contacting carlos.salgado30@yahoo.com.

### Contact

Questions about this notice: carlos.salgado30@yahoo.com
"""


@st.dialog("Privacy Notice", width="large")
def _privacy_dialog() -> None:
    st.markdown(PRIVACY_MD)


def render_privacy_notice(key: str = "privacy_link") -> None:
    """Render the one-line disclosure + a link that opens the full notice."""
    st.caption(GATE_SNIPPET)
    try:
        clicked = st.button("Privacy Notice", key=key, type="tertiary")
    except Exception:
        # Older Streamlit without the "tertiary" button type.
        clicked = st.button("Privacy Notice", key=key)
    if clicked:
        _privacy_dialog()
