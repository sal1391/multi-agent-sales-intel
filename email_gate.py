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
        if st.button("Start demo"):
            if is_valid_email(email):
                st.session_state["demo_email"] = email
                guardrails.log_event("entries", {
                    "ts": datetime.now(timezone.utc).isoformat(),
                    "email": email,
                })
                st.rerun()
            else:
                st.error("Please enter a valid email address.")

    st.stop()
