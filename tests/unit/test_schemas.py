"""Unit tests for the Perplexity JSON-schema builders (no network needed)."""
import json

import pytest

from agents.schemas import (
    latest_news_partnerships,
    market_position,
    operational_profile,
    strategic_profile,
    sustainability_esg,
)

ALL_MODULES = [
    latest_news_partnerships,
    market_position,
    operational_profile,
    strategic_profile,
    sustainability_esg,
]


@pytest.mark.parametrize("module", ALL_MODULES, ids=lambda m: m.__name__.split(".")[-1])
def test_get_schema_returns_valid_response_format(module):
    fmt = module.get_schema("Acme Aviation")

    assert fmt["type"] == "json_schema"
    schema = fmt["json_schema"]["schema"]
    assert schema["type"] == "object"
    assert isinstance(schema["required"], list) and schema["required"]
    assert isinstance(schema["properties"], dict) and schema["properties"]
    # every required key must be defined in properties
    for key in schema["required"]:
        assert key in schema["properties"], f"required key {key!r} missing from properties"


@pytest.mark.parametrize("module", ALL_MODULES, ids=lambda m: m.__name__.split(".")[-1])
def test_get_schema_is_json_serializable(module):
    fmt = module.get_schema("Acme Aviation")
    # Perplexity receives this over the wire — it must serialize cleanly
    json.dumps(fmt)


def test_company_name_is_pinned_in_market_position_schema():
    fmt = market_position.get_schema("Acme Aviation")
    props = fmt["json_schema"]["schema"]["properties"]
    assert props["company"]["const"] == "Acme Aviation"
