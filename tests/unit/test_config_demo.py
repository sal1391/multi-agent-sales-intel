"""Demo-mode config defaults. Reloads config under controlled env vars."""
import importlib
import sys


def _fresh_config(monkeypatch, **env):
    for var in ("DEPLOY_MODE", "OPENAI_API_KEY", "OPENAI_MODEL", "AUTH0_ENABLED"):
        monkeypatch.delenv(var, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    sys.modules.pop("config", None)
    import config
    importlib.reload(config)
    return config


def test_demo_is_default_mode(monkeypatch):
    config = _fresh_config(monkeypatch)
    assert config.DEPLOY_MODE == "demo"
    assert config.AUTH0_ENABLED is False


def test_openai_model_default(monkeypatch):
    config = _fresh_config(monkeypatch)
    assert config.OPENAI_MODEL == "gpt-4o-mini"


def test_openai_model_env_override(monkeypatch):
    config = _fresh_config(monkeypatch, OPENAI_MODEL="gpt-4o")
    assert config.OPENAI_MODEL == "gpt-4o"


def test_local_mode_still_works(monkeypatch):
    config = _fresh_config(monkeypatch, DEPLOY_MODE="local")
    assert config.DEPLOY_MODE == "local"
    assert isinstance(config.SNOWFLAKE_CONNECTION, dict)


def test_demo_mode_table_fqn_inputs_present(monkeypatch):
    config = _fresh_config(monkeypatch)
    assert config.SNOWFLAKE_CONNECTION["database"] == "SANDBOX"
    assert config.SNOWFLAKE_CONNECTION["schema"] == "ANALYTICS"
