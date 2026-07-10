"""Unit tests for email_gate.is_valid_email — offline, no Streamlit runtime."""
import pytest

from email_gate import is_valid_email

VALID_EMAILS = [
    "a@b.co",
    "first.last+tag@sub.domain.io",
    " padded@x.io ",
]

INVALID_EMAILS = [
    "",
    "a@b",
    "no-at.com",
    "a b@c.io",
    "a@b.",
    "@x.io",
]


@pytest.mark.parametrize("email", VALID_EMAILS)
def test_is_valid_email_accepts_valid_addresses(email):
    assert is_valid_email(email) is True


@pytest.mark.parametrize("email", INVALID_EMAILS)
def test_is_valid_email_rejects_invalid_addresses(email):
    assert is_valid_email(email) is False
