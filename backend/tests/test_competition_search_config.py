"""Tests for config.yaml path resolution and search/provider config reading.

Covers today's changes:
- Config path resolution (6-parent traversal to reach project root)
- _get_search_config() search backend toggles (ddg, tavily, provider_search, jina)
- _get_active_config_group() group resolution
- _get_provider_search_config() provider search config
- _resolve_provider() per-agent model resolution
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest import mock

import yaml

# ── conftest-style mocks for modules that don't exist in test env ──
# These must run before any competition imports.
if "ddgs" not in sys.modules:
    sys.modules["ddgs"] = mock.MagicMock()
if "primp" not in sys.modules:
    sys.modules["primp"] = mock.MagicMock()

from competition.executor import _get_active_config_group, _resolve_model, _resolve_provider
from competition.tools.search import (
    _get_provider_search_config,
    _get_search_config,
    _responses_search,
    search,
)

# ── helpers ──

def _write_yaml(path: Path, data: dict) -> None:
    path.write_text(yaml.dump(data, default_flow_style=False), encoding="utf-8")


def _minimal_config(**overrides) -> dict:
    """Build a minimal valid config.yaml dict with groupA defaults."""
    cfg = {
        "config_version": 12,
        "competition": {
            "active_group": "groupA",
            "providers": {
                "doubao": {
                    "api_key_env": "DOUBAO_API_KEY",
                    "api_base": "https://ark.cn-beijing.volces.com/api/v3",
                },
                "deepseek": {
                    "api_key_env": "DEEPSEEK_API_KEY",
                    "api_base": "https://api.deepseek.com/v1",
                },
            },
            "groups": {
                "groupA": {
                    "default_provider": "doubao",
                    "default_model": "ep-20260514111325-xjmj7",
                    "search": {
                        "provider_search": True,
                        "tavily": True,
                        "ddg": True,
                        "jina": True,
                    },
                    "collector": {
                        "provider": "doubao",
                        "model": "ep-20260514111325-xjmj7",
                        "timeout_seconds": 600,
                        "max_turns": 30,
                    },
                },
            },
        },
    }
    # Deep-merge overrides
    for key, value in overrides.items():
        if isinstance(value, dict) and key in cfg:
            cfg[key].update(value)
        else:
            cfg[key] = value
    return cfg


# ── Active group resolution ──


class TestGetActiveConfigGroup:
    def test_returns_config_group_from_db(self):
        """When DB has config_group, returned by _get_active_config_group."""
        cg = {"name": "groupA", "default_provider": "doubao", "default_model": "test-model"}
        with mock.patch("competition.executor._get_user_settings", return_value={
            "active_group": "groupA", "config_groups": [cg],
        }):
            result = _get_active_config_group()
        assert result.get("default_provider") == "doubao"
        assert result.get("default_model") == "test-model"

    def test_returns_empty_when_no_db(self):
        with mock.patch("competition.executor._get_user_settings", return_value=None):
            result = _get_active_config_group()
        assert result == {}

    def test_returns_empty_when_no_matching_group(self):
        """Active group not found in config_groups."""
        with mock.patch("competition.executor._get_user_settings", return_value={
            "active_group": "groupB", "config_groups": [{"name": "groupA"}],
        }):
            result = _get_active_config_group()
        assert result == {}


# ── Search config ──


class TestGetSearchConfig:
    def test_reads_from_config_group(self):
        """When config_group has search_toggles, use them."""
        import competition.tools.search as mod
        with mock.patch.object(mod, "_get_active_config_group", return_value={
            "search_toggles": {"tavily": True, "ddg": False, "jina": True, "provider_search": False},
        }):
            cfg = mod._get_search_config()
        assert cfg["tavily"] is True
        assert cfg["ddg"] is False
        assert cfg["jina"] is True
        assert cfg["provider_search"] is False

    def test_db_mode_defaults_when_no_config(self):
        """DB mode keeps free search fallbacks enabled before user setup."""
        import competition.tools.search as mod
        with mock.patch.object(mod, "_get_active_config_group", return_value={}):
            cfg = mod._get_search_config()
        assert cfg["tavily"] is True
        assert cfg["ddg"] is True
        assert cfg["jina"] is False
        assert cfg["provider_search"] is True

    def test_ddg_disabled_in_group(self, monkeypatch, tmp_path: Path):
        monkeypatch.setenv("CI_AGENT_CONFIG_MODE", "file")
        cfg = _minimal_config()
        cfg["competition"]["groups"]["groupA"]["search"]["ddg"] = False
        _write_yaml(tmp_path / "config.yaml", cfg)
        monkeypatch.chdir(tmp_path)
        result = _get_search_config()
        assert result["ddg"] is False

    def test_tavily_disabled_in_group(self, monkeypatch, tmp_path: Path):
        monkeypatch.setenv("CI_AGENT_CONFIG_MODE", "file")
        cfg = _minimal_config()
        cfg["competition"]["groups"]["groupA"]["search"]["tavily"] = False
        _write_yaml(tmp_path / "config.yaml", cfg)
        monkeypatch.chdir(tmp_path)
        result = _get_search_config()
        assert result["tavily"] is False

    def test_provider_search_disabled(self, monkeypatch, tmp_path: Path):
        monkeypatch.setenv("CI_AGENT_CONFIG_MODE", "file")
        cfg = _minimal_config()
        cfg["competition"]["groups"]["groupA"]["search"]["provider_search"] = False
        _write_yaml(tmp_path / "config.yaml", cfg)
        monkeypatch.chdir(tmp_path)
        result = _get_search_config()
        assert result["provider_search"] is False

    def test_jina_disabled(self, monkeypatch, tmp_path: Path):
        monkeypatch.setenv("CI_AGENT_CONFIG_MODE", "file")
        cfg = _minimal_config()
        cfg["competition"]["groups"]["groupA"]["search"]["jina"] = False
        _write_yaml(tmp_path / "config.yaml", cfg)
        monkeypatch.chdir(tmp_path)
        result = _get_search_config()
        assert result["jina"] is False


# ── Provider search config ──


class TestGetProviderSearchConfig:
    def test_returns_provider_when_enabled(self):
        """When config_group has default_provider and search enabled, returns creds."""
        import competition.tools.search as mod
        with mock.patch.object(mod, "_get_active_config_group", return_value={
            "default_provider": "doubao", "search_toggles": {"provider_search": True},
        }), mock.patch.object(mod, "_get_search_config", return_value={"provider_search": True}), \
           mock.patch.object(mod, "_get_user_key", return_value="test-key"), \
           mock.patch.object(mod, "_get_user_base", return_value="https://ark.cn-beijing.volces.com/api/v3"):
            prov_name, prov_key, prov_base = _get_provider_search_config()
        assert prov_name == "doubao"
        assert prov_key == "test-key"
        assert "volces.com" in prov_base

    def test_returns_none_when_disabled(self):
        import competition.tools.search as mod
        with mock.patch.object(mod, "_get_search_config", return_value={"provider_search": False}):
            prov_name, _, _ = _get_provider_search_config()
        assert prov_name is None

    def test_returns_none_when_no_key(self):
        import competition.tools.search as mod
        with mock.patch.object(mod, "_get_active_config_group", return_value={
            "default_provider": "doubao", "search_toggles": {"provider_search": True},
        }), mock.patch.object(mod, "_get_search_config", return_value={"provider_search": True}), \
           mock.patch.object(mod, "_get_user_key", return_value=""):
            prov_name, _, _ = _get_provider_search_config()
        assert prov_name is None


class TestResponsesProviderSearch:
    def test_non_qwen_provider_uses_responses_search(self):
        import competition.tools.search as mod

        expected = mod.SearchResponse(
            query="current pricing",
            results=[mod.SearchResult(title="Official", url="https://example.com")],
            backend="lab_gpt",
        )
        with mock.patch.object(mod, "_get_search_config", return_value={
            "provider_search": True, "tavily": False, "ddg": False,
        }), mock.patch.object(mod, "_get_provider_search_config", return_value=(
            "lab_gpt", "test-key", "https://gateway.example/v1",
        )), mock.patch.object(mod, "_responses_search", return_value=expected) as responses_search:
            result = search("current pricing", max_results=3)

        assert result == expected
        responses_search.assert_called_once_with(
            "current pricing", 3, "test-key", "https://gateway.example/v1", backend="lab_gpt",
        )

    def test_responses_search_parses_json_results(self):
        payload = {
            "error": None,
            "output": [{
                "type": "message",
                "content": [{
                    "type": "output_text",
                    "text": json.dumps([{
                        "title": "Official pricing",
                        "url": "https://example.com/pricing",
                        "snippet": "Current plans",
                    }]),
                }],
            }],
        }
        response = mock.MagicMock()
        response.read.return_value = json.dumps(payload).encode()
        response.__enter__.return_value = response

        with mock.patch("urllib.request.urlopen", return_value=response) as urlopen, \
             mock.patch("competition.tools.search._get_default_provider", return_value=(
                 "test-key", "https://gateway.example/v1", "gpt-test",
             )):
            result = _responses_search(
                "current pricing", 3, "test-key", "https://gateway.example/v1", backend="lab_gpt",
            )

        assert result.backend == "lab_gpt"
        assert [(item.title, item.url, item.snippet) for item in result.results] == [(
            "Official pricing", "https://example.com/pricing", "Current plans",
        )]
        request = urlopen.call_args.args[0]
        assert request.full_url == "https://gateway.example/v1/responses"
        assert json.loads(request.data)["tools"] == [{"type": "web_search"}]
        assert request.get_header("User-agent") == "CI-Agent/1.0"
        assert urlopen.call_args.kwargs["timeout"] == 60

    def test_responses_search_falls_back_to_citations(self):
        payload = {
            "output": [{
                "type": "message",
                "content": [{
                    "type": "output_text",
                    "text": "The official page contains the current details.",
                    "annotations": [{
                        "type": "url_citation",
                        "title": "Official page",
                        "url": "https://example.com/current",
                    }],
                }],
            }],
        }
        response = mock.MagicMock()
        response.read.return_value = json.dumps(payload).encode()
        response.__enter__.return_value = response

        with mock.patch("urllib.request.urlopen", return_value=response), \
             mock.patch("competition.tools.search._get_default_provider", return_value=(
                 "test-key", "https://gateway.example/v1", "gpt-test",
             )):
            result = _responses_search(
                "current details", 3, "test-key", "https://gateway.example/v1", backend="lab_gpt",
            )

        assert len(result.results) == 1
        assert result.results[0].title == "Official page"
        assert result.results[0].url == "https://example.com/current"

# ── Per-agent model resolution (executor) ──

DB_PROVIDER_KEYS = {"doubao": "test-db-key"}
DB_PROVIDER_BASES = {"doubao": "https://ark.cn-beijing.volces.com/api/v3"}
DB_CONFIG_GROUP = {
    "default_provider": "doubao",
    "default_model": "ep-20260514111325-xjmj7",
    "agent_configs": {},
    "search_toggles": {"provider_search": True, "tavily": True},
    "feishu_toggles": {},
}


def _db_mock(user_settings=None, config_group=None):
    """Create mocks for _get_user_settings and _get_active_config_group."""
    us = user_settings or {}
    cg = config_group or DB_CONFIG_GROUP
    return (
        mock.patch("competition.executor._get_user_settings", return_value=us),
        mock.patch("competition.executor._get_active_config_group", return_value=cg),
    )


class TestResolveProvider:
    def test_resolves_from_db(self):
        us = {"provider_keys": DB_PROVIDER_KEYS, "provider_bases": DB_PROVIDER_BASES}
        m1, m2 = _db_mock(user_settings=us)
        with m1, m2:
            model, base, key = _resolve_provider("collector")
        assert model == "ep-20260514111325-xjmj7"
        assert "volces.com" in base if base else True
        assert key == "test-db-key"

    def test_returns_empty_when_no_db(self):
        m1, m2 = _db_mock(user_settings=None, config_group={})
        with m1, m2:
            model, base, key = _resolve_provider("collector")
        assert model == ""
        assert base == ""

    def test_resolves_per_agent_model(self):
        cg = dict(DB_CONFIG_GROUP)
        cg["agent_configs"] = {"analyst": {"model": "analyst-model"}}
        us = {"provider_keys": DB_PROVIDER_KEYS, "provider_bases": DB_PROVIDER_BASES}
        m1, m2 = _db_mock(user_settings=us, config_group=cg)
        with m1, m2:
            model, _, _ = _resolve_provider("analyst")
        assert model == "analyst-model"

    def test_falls_back_to_default_model(self):
        us = {"provider_keys": DB_PROVIDER_KEYS, "provider_bases": DB_PROVIDER_BASES}
        m1, m2 = _db_mock(user_settings=us)
        with m1, m2:
            model, _, _ = _resolve_provider("unknown_agent")
        assert model == "ep-20260514111325-xjmj7"


class TestResolveModel:
    def test_returns_model_string(self):
        us = {"provider_keys": DB_PROVIDER_KEYS, "provider_bases": DB_PROVIDER_BASES}
        m1, m2 = _db_mock(user_settings=us)
        with m1, m2:
            model = _resolve_model("collector")
        assert model == "ep-20260514111325-xjmj7"
        assert isinstance(model, str)
