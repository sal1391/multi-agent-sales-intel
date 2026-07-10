"""
Unit tests for demo-mode research: baked-file lookup, offline OpenAI
stand-in, and the guarantee that Perplexity is never called at demo
runtime. Fully offline — no API keys, no network.
"""
import pytest

from agents import researcher, contextualizer


# ---------------------------------------------------------------------------
# _slug
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "raw, expected",
    [
        ("Hapag-Lloyd", "hapag-lloyd"),
        ("MSC ", "msc"),
        (" MSC ", "msc"),
        ('"K" Line', "k-line"),
        ("Maersk", "maersk"),
        ("  A.P. Moller-Maersk  ", "a-p-moller-maersk"),
    ],
)
def test_slug(raw, expected):
    assert researcher._slug(raw) == expected


# ---------------------------------------------------------------------------
# agent_researcher — baked path
# ---------------------------------------------------------------------------

def test_agent_researcher_returns_baked_file_verbatim(tmp_path, monkeypatch):
    monkeypatch.setattr(researcher, "DEPLOY_MODE", "demo")
    monkeypatch.setattr(researcher, "DEMO_RESEARCH_DIR", str(tmp_path))

    baked_text = "## Baked Maersk Report\n\nSome pre-baked content.\n"
    (tmp_path / "maersk.md").write_text(baked_text, encoding="utf-8")

    def _boom(company_name):
        raise AssertionError("_standin_research must not run for a baked company")

    monkeypatch.setattr(researcher, "_standin_research", _boom)

    def _no_perplexity(*args, **kwargs):
        raise AssertionError("_call_perplexity must never be called in demo mode")

    monkeypatch.setattr(researcher, "_call_perplexity", _no_perplexity)

    result = researcher.agent_researcher(None, "Maersk")
    assert result == baked_text


def test_agent_researcher_baked_lookup_is_slug_insensitive(tmp_path, monkeypatch):
    monkeypatch.setattr(researcher, "DEPLOY_MODE", "demo")
    monkeypatch.setattr(researcher, "DEMO_RESEARCH_DIR", str(tmp_path))

    baked_text = "## Baked Hapag-Lloyd Report\n"
    (tmp_path / "hapag-lloyd.md").write_text(baked_text, encoding="utf-8")
    monkeypatch.setattr(
        researcher, "_standin_research",
        lambda name: (_ for _ in ()).throw(AssertionError("stand-in must not run")),
    )

    result = researcher.agent_researcher(None, " Hapag-Lloyd ")
    assert result == baked_text


def test_agent_researcher_missing_baked_file_falls_back_to_standin(tmp_path, monkeypatch):
    monkeypatch.setattr(researcher, "DEPLOY_MODE", "demo")
    monkeypatch.setattr(researcher, "DEMO_RESEARCH_DIR", str(tmp_path))  # empty dir

    called = {}

    def _fake_standin(company_name):
        called["company"] = company_name
        return "stand-in output"

    monkeypatch.setattr(researcher, "_standin_research", _fake_standin)

    result = researcher.agent_researcher(None, "Some Random Line")
    assert result == "stand-in output"
    assert called["company"] == "Some Random Line"


def test_agent_researcher_local_mode_uses_live_pipeline(monkeypatch):
    monkeypatch.setattr(researcher, "DEPLOY_MODE", "local")

    def _fake_live(session, company_name):
        return f"live:{company_name}"

    def _boom(*args, **kwargs):
        raise AssertionError("baked/stand-in path must not run outside demo mode")

    monkeypatch.setattr(researcher, "_run_live_research", _fake_live)
    monkeypatch.setattr(researcher, "_load_baked", _boom)
    monkeypatch.setattr(researcher, "_standin_research", _boom)

    result = researcher.agent_researcher(None, "Maersk")
    assert result == "live:Maersk"


# ---------------------------------------------------------------------------
# agent_researcher — offline stand-in path (no baked file, no Perplexity)
# ---------------------------------------------------------------------------

def test_standin_research_uses_openai_and_never_perplexity(tmp_path, monkeypatch):
    monkeypatch.setattr(researcher, "DEPLOY_MODE", "demo")
    monkeypatch.setattr(researcher, "DEMO_RESEARCH_DIR", str(tmp_path))  # no baked files

    def _no_perplexity(*args, **kwargs):
        raise AssertionError("_call_perplexity must never be called in demo stand-in mode")

    monkeypatch.setattr(researcher, "_call_perplexity", _no_perplexity)

    def _no_client(*args, **kwargs):
        raise AssertionError("_get_client must never be called in demo stand-in mode")

    monkeypatch.setattr(researcher, "_get_client", _no_client)

    import openai_client

    def _canned_openai(prompt, model=None, temperature=0.2, max_tokens=4096):
        return "CANNED SYNTHESIS TEXT"

    monkeypatch.setattr(openai_client, "call_openai_complete", _canned_openai)

    # call_cortex_complete's demo branch lazily imports call_openai_complete
    # from the openai_client module at call time, so patching the module
    # attribute above is what actually takes effect.
    import snowflake_client
    monkeypatch.setattr(snowflake_client, "DEPLOY_MODE", "demo")

    result = researcher.agent_researcher(None, "Unknown Shipping Co")

    assert "CANNED SYNTHESIS TEXT" in result
    assert "Data Freshness: built-in knowledge base" in result
    assert "Confidence Score: Medium (offline knowledge, no live web research)" in result


def test_standin_research_prompts_never_reveal_provider(tmp_path, monkeypatch):
    """The stand-in prompts themselves must never let an OpenAI response
    that echoes back prompt fragments mention a provider name."""
    for builder in (
        researcher._standin_esg_prompt,
        researcher._standin_market_prompt,
        researcher._standin_profile_prompt,
        researcher._standin_news_prompt,
    ):
        prompt = builder("Test Shipping Co")
        assert "perplexity" not in prompt.lower()
        assert "openai" not in prompt.lower()


# ---------------------------------------------------------------------------
# Contextualizer — demo new-account never touches Perplexity
# ---------------------------------------------------------------------------

def test_contextualizer_new_account_demo_mode_skips_perplexity(monkeypatch):
    monkeypatch.setattr(contextualizer, "DEPLOY_MODE", "demo")

    def _no_perplexity_client(*args, **kwargs):
        raise AssertionError("_get_client must never be called in demo mode")

    monkeypatch.setattr(contextualizer, "_get_client", _no_perplexity_client)

    def _no_perplexity_research(*args, **kwargs):
        raise AssertionError("_research_operational_profile must never be called in demo mode")

    monkeypatch.setattr(contextualizer, "_research_operational_profile", _no_perplexity_research)

    import openai_client

    def _canned_openai(prompt, model=None, temperature=0.2, max_tokens=4096):
        return "### SOURCE: BUILT-IN KNOWLEDGE (Maritime Profile)\n- Operational Overview: Not available\n"

    monkeypatch.setattr(openai_client, "call_openai_complete", _canned_openai)

    import snowflake_client
    monkeypatch.setattr(snowflake_client, "DEPLOY_MODE", "demo")

    result = contextualizer.agent_contextualizer(
        None, "Some New Prospect Co", None, researcher_output="Agent 1 output"
    )

    assert "BUILT-IN KNOWLEDGE" in result


def test_contextualizer_existing_account_untouched_in_demo_mode(monkeypatch):
    """raw_data present -> the existing-account branch must not even look at
    the demo/Perplexity seam (it never did)."""
    monkeypatch.setattr(contextualizer, "DEPLOY_MODE", "demo")

    def _boom(*args, **kwargs):
        raise AssertionError("existing-account branch must not touch research seams")

    monkeypatch.setattr(contextualizer, "_get_client", _boom)
    monkeypatch.setattr(contextualizer, "_research_operational_profile", _boom)
    monkeypatch.setattr(contextualizer, "_standin_operational_profile", _boom)

    import openai_client

    monkeypatch.setattr(
        openai_client, "call_openai_complete",
        lambda prompt, model=None, temperature=0.2, max_tokens=4096: "existing-account synthesis",
    )
    import snowflake_client
    monkeypatch.setattr(snowflake_client, "DEPLOY_MODE", "demo")

    raw_data = {
        "periods": {"prior_year": "Prior Year 2025", "ytd": "YTD 2026"},
        "customer_metrics": {"prior_year": {}, "ytd": {}},
        "top5_ports": {"prior_year": [], "ytd": []},
    }
    result = contextualizer.agent_contextualizer(None, "Maersk", raw_data)
    assert result == "existing-account synthesis"


# ---------------------------------------------------------------------------
# _get_client() must never raise, even with no key (module-load safety is
# additionally verified out-of-process: see the "Verify" step in the task
# that runs `python -c "... PERPLEXITY_API_KEY=''; from agents import
# researcher, contextualizer"`).
# ---------------------------------------------------------------------------

def test_researcher_get_client_survives_missing_key(monkeypatch):
    monkeypatch.setattr(researcher, "PERPLEXITY_API_KEY", "")
    researcher._get_client()  # must not raise


def test_contextualizer_get_client_survives_missing_key(monkeypatch):
    monkeypatch.setattr(contextualizer, "PERPLEXITY_API_KEY", "")
    contextualizer._get_client()  # must not raise
