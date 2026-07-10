"""
Hidden OpenAI client for demo mode.

This module is the only place in the app that talks to OpenAI directly. It
intentionally hides the provider from callers and from end users: agents
call ``call_openai_complete`` exactly like they would call a Cortex
completion helper, and get back either a filtered analysis string or a
generic "service unavailable" message. It never raises, so a bad key, a
network blip, or a moderation/rate-limit error on OpenAI's side can never
surface an SDK stack trace (and the "OpenAI" name) to a demo user.
"""

_GENERIC_UNAVAILABLE = "The analysis service is temporarily unavailable. Please try again shortly."


def call_openai_complete(
    prompt: str,
    model: str | None = None,
    temperature: float = 0.2,
    max_tokens: int = 4096,
) -> str:
    """Call OpenAI chat completions and return guardrail-filtered text.

    Never raises: any failure (missing/invalid API key, network error, SDK
    exception, empty response) is caught and converted into a generic,
    provider-agnostic message so it's safe to surface directly in the UI.
    """
    try:
        from openai import OpenAI

        from config import OPENAI_API_KEY, OPENAI_MODEL
        from guardrails import HARDENED_SYSTEM_PROMPT, filter_output

        client = OpenAI(api_key=OPENAI_API_KEY)
        response = client.chat.completions.create(
            model=model or OPENAI_MODEL,
            temperature=temperature,
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": HARDENED_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
        )
        text = response.choices[0].message.content
        if not text:
            return _GENERIC_UNAVAILABLE
        return filter_output(text)
    except Exception as exc:
        # Log the exception class only — never the message, which can
        # include provider-identifying details (e.g. "OpenAI" in an
        # AuthenticationError string) or key fragments.
        print(f"[openai_client] {type(exc).__name__}", flush=True)
        return _GENERIC_UNAVAILABLE
