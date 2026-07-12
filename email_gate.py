"""
Email gate for the Sales Intel demo.

Blocks the rest of the app until the visitor supplies an email address. That
address is stored in session state and used to tag every guardrail
violation log for the remainder of the session.
"""
import base64
import os
import re
from datetime import datetime, timezone

import guardrails
from demo_abuse import (
    get_client_ip,
    is_rate_limited,
    record_attempt,
    render_turnstile_widget,
    verify_turnstile,
)
from privacy import render_privacy_notice

EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")


def is_valid_email(email: str) -> bool:
    return bool(EMAIL_RE.match(email.strip()))


def require_email() -> None:
    """Render an email-collection card and halt the script until answered."""
    import streamlit as st

    if st.session_state.get("demo_email"):
        return

    trident_b64 = None
    try:
        trident_path = os.path.join(os.path.dirname(__file__), "assets", "trident.png")
        with open(trident_path, "rb") as fh:
            trident_b64 = base64.b64encode(fh.read()).decode()
    except OSError:
        trident_b64 = None

    st.markdown(
        """
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;800&display=swap');
        .gate-card {
          font-family: 'Inter', sans-serif;
          text-align: center;
          padding: 32px 0 8px 0;
        }
        .gate-logo {
          height: 56px;
          width: auto;
          filter: drop-shadow(0 2px 4px rgba(65,105,225,0.3));
        }
        .gate-title {
          font-size: 32px;
          font-weight: 800;
          color: #1a1a2e;
          margin: 10px 0 0 0;
          letter-spacing: -0.5px;
        }
        div[data-testid="stButton"] button {
          background: linear-gradient(90deg, #4169E1 0%, #6495ED 100%);
          color: white;
          border: none;
          font-weight: 600;
          width: 100%;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    _, center, _ = st.columns([1, 2, 1])
    with center:
        logo_html = (
            f'<img class="gate-logo" src="data:image/png;base64,{trident_b64}" alt="trident">'
            if trident_b64
            else ""
        )
        st.markdown(
            f"""
            <div class="gate-card">
              {logo_html}
              <div class="gate-title">Sales Intel Demo</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.caption("Enter your email to start the demo.")
        email = st.text_input("Email")
        render_turnstile_widget()  # no-op unless Turnstile env vars are set
        if st.button("Start demo"):
            if not is_valid_email(email):
                st.error("Please enter a valid email address.")
            else:
                ip = get_client_ip()
                # 1. Turnstile (env-gated; passes through while disabled)
                token = st.session_state.get("cf_turnstile_token", "")
                if not verify_turnstile(token, ip):
                    st.error("Verification failed. Please try again.")
                # 2. Rate limit
                elif is_rate_limited(ip):
                    guardrails.log_event("rate_limited", {
                        "ts": datetime.now(timezone.utc).isoformat(),
                        "ip": ip,
                    })
                    st.error("Too many attempts from your network. "
                             "Please try again later.")
                # 3. Accept + log (unchanged logging, now with IP)
                else:
                    record_attempt(ip)
                    st.session_state["demo_email"] = email
                    guardrails.log_event("entries", {
                        "ts": datetime.now(timezone.utc).isoformat(),
                        "email": email,
                        "ip": ip,
                    })
                    st.rerun()

        render_privacy_notice()

    st.stop()
