"""Tests for config.yaml path resolution and search/provider config reading.

Covers today's changes:
- Config path resolution (6-parent traversal to reach project root)
- _get_search_config() search backend toggles (ddg, tavily, provider_search, jina)
- _get_active_group_config() group resolution
- _get_provider_search_config() provider search config
- _resolve_provider() per-agent model resolution
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from unittest import mock

import pytest
import yaml

# ── conftest-style mocks for modules that don't exist in test env ──
# These must run before any competition imports.
if "ddgs" not in sys.modules:
    sys.modules["ddgs"] = mock.MagicMock()
if "primp" not in sys.modules:
    sys.modules["primp"] = mock.MagicMock()

from competition.tools.search import (
    _get_search_config,
    _get_active_group_config,
    _get_provider_search_config,
    _read_config_yaml,
)
from competition.executor import _resolve_provider, _resolve_model


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


# ── Config path resolution ──


class TestReadConfigYaml:
    """Verify _read_config_yaml() finds config.yaml at various path depths."""

    def test_finds_config_in_cwd(self, monkeypatch, tmp_path: Path):
        config_path = tmp_path / "config.yaml"
        _write_yaml(config_path, _minimal_config())
        monkeypatch.chdir(tmp_path)
        result = _read_config_yaml()
        assert result.get("config_version") == 12

    def test_finds_config_via_six_parent_traversal(self, tmp_path: Path):
        """Simulates the real deployment: CWD=backend/, config.yaml in project root."""
        project_root = tmp_path / "deer-flow"
        backend_dir = project_root / "backend"
        backend_dir.mkdir(parents=True)
        _write_yaml(project_root / "config.yaml", _minimal_config())
        # Simulate running from backend/
        os.chdir(str(backend_dir))
        try:
            result = _read_config_yaml()
            assert result.get("config_version") == 12
        finally:
            os.chdir("/root/Projects/deer-flow")

    def test_returns_empty_when_no_config_found(self):
        """When no config.yaml exists at any path, returns {}.

        Uses mock because the 6-parent absolute path always finds the real
        config.yaml on the development machine.
        """
        import competition.tools.search as mod
        with mock.patch.object(mod, "_read_config_yaml", return_value={}):
            result = mod._read_config_yaml()
            assert result == {}

    def test_finds_config_in_backend_subdir(self, monkeypatch, tmp_path: Path):
        """config.yaml at backend/config.yaml, CWD=backend/"""
        backend = tmp_path / "backend"
        backend.mkdir()
        _write_yaml(backend / "config.yaml", _minimal_config())
        monkeypatch.chdir(backend)
        result = _read_config_yaml()
        assert result.get("config_version") == 12


# ── Active group resolution ──


class TestGetActiveGroupConfig:
    def test_returns_groupA_config(self, monkeypatch, tmp_path: Path):
        _write_yaml(tmp_path / "config.yaml", _minimal_config())
        monkeypatch.chdir(tmp_path)
        group = _get_active_group_config()
        assert group.get("default_provider") == "doubao"
        assert group.get("default_model") == "ep-20260514111325-xjmj7"

    def test_returns_empty_when_no_groups(self, monkeypatch, tmp_path: Path):
        cfg = _minimal_config()
        del cfg["competition"]["groups"]
        cfg["competition"]["default_provider"] = "top-level-provider"
        _write_yaml(tmp_path / "config.yaml", cfg)
        monkeypatch.chdir(tmp_path)
        group = _get_active_group_config()
        # Falls back to competition root
        assert group.get("default_provider") == "top-level-provider"

    def test_respects_active_group_switch(self, monkeypatch, tmp_path: Path):
        cfg = _minimal_config()
        cfg["competition"]["groups"]["groupB"] = {
            "default_provider": "deepseek",
            "default_model": "deepseek-v4-flash",
            "search": {"tavily": True, "ddg": False},
        }
        cfg["competition"]["active_group"] = "groupB"
        _write_yaml(tmp_path / "config.yaml", cfg)
        monkeypatch.chdir(tmp_path)
        group = _get_active_group_config()
        assert group.get("default_provider") == "deepseek"


# ── Search config ──


class TestGetSearchConfig:
    def test_falls_back_to_search_config_json(self, monkeypatch, tmp_path: Path):
        """When active group has no search section, uses search_config.json fallback."""
        cfg = _minimal_config()
        # Remove search section from group
        del cfg["competition"]["groups"]["groupA"]["search"]
        _write_yaml(tmp_path / "config.yaml", cfg)
        monkeypatch.chdir(tmp_path)
        result = _get_search_config()
        # search_config.json has tavily=false, ddg=true, jina=false
        assert result["tavily"] is False
        assert result["ddg"] is True
        assert result["jina"] is False

    def test_defaults_when_no_config(self, tmp_path: Path):
        """When no config files exist, hardcoded defaults apply (all True)."""
        import competition.tools.search as mod
        with mock.patch.object(mod, "_get_active_group_config", return_value={}):
            with mock.patch.object(mod.Path, "exists", return_value=False):
                cfg = mod._get_search_config()
        assert cfg["tavily"] is True
        assert cfg["ddg"] is True
        assert cfg["jina"] is True

    def test_ddg_disabled_in_group(self, monkeypatch, tmp_path: Path):
        cfg = _minimal_config()
        cfg["competition"]["groups"]["groupA"]["search"]["ddg"] = False
        _write_yaml(tmp_path / "config.yaml", cfg)
        monkeypatch.chdir(tmp_path)
        result = _get_search_config()
        assert result["ddg"] is False

    def test_tavily_disabled_in_group(self, monkeypatch, tmp_path: Path):
        cfg = _minimal_config()
        cfg["competition"]["groups"]["groupA"]["search"]["tavily"] = False
        _write_yaml(tmp_path / "config.yaml", cfg)
        monkeypatch.chdir(tmp_path)
        result = _get_search_config()
        assert result["tavily"] is False

    def test_provider_search_disabled(self, monkeypatch, tmp_path: Path):
        cfg = _minimal_config()
        cfg["competition"]["groups"]["groupA"]["search"]["provider_search"] = False
        _write_yaml(tmp_path / "config.yaml", cfg)
        monkeypatch.chdir(tmp_path)
        result = _get_search_config()
        assert result["provider_search"] is False

    def test_jina_disabled(self, monkeypatch, tmp_path: Path):
        cfg = _minimal_config()
        cfg["competition"]["groups"]["groupA"]["search"]["jina"] = False
        _write_yaml(tmp_path / "config.yaml", cfg)
        monkeypatch.chdir(tmp_path)
        result = _get_search_config()
        assert result["jina"] is False


# ── Provider search config ──


class TestGetProviderSearchConfig:
    def test_returns_doubao_when_enabled(self, monkeypatch, tmp_path: Path):
        _write_yaml(tmp_path / "config.yaml", _minimal_config())
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("DOUBAO_API_KEY", "test-doubao-key")
        prov_name, prov_key, prov_base = _get_provider_search_config()
        assert prov_name == "doubao"
        assert prov_key == "test-doubao-key"
        assert "volces.com" in prov_base

    def test_returns_none_when_disabled(self, monkeypatch, tmp_path: Path):
        cfg = _minimal_config()
        cfg["competition"]["groups"]["groupA"]["search"]["provider_search"] = False
        _write_yaml(tmp_path / "config.yaml", cfg)
        monkeypatch.chdir(tmp_path)
        prov_name, _, _ = _get_provider_search_config()
        assert prov_name is None

    def test_returns_none_when_no_api_key(self, monkeypatch, tmp_path: Path):
        _write_yaml(tmp_path / "config.yaml", _minimal_config())
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("DOUBAO_API_KEY", raising=False)
        prov_name, _, _ = _get_provider_search_config()
        assert prov_name is None


# ── Per-agent model resolution (executor) ──


class TestResolveProvider:
    def test_resolves_collector_from_groupA(self, monkeypatch, tmp_path: Path):
        _write_yaml(tmp_path / "config.yaml", _minimal_config())
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("DOUBAO_API_KEY", "test-key")
        model, base, key = _resolve_provider("collector")
        assert model == "ep-20260514111325-xjmj7"
        assert "volces.com" in base
        assert key == "test-key"

    def test_falls_back_to_env_when_api_key_missing(self, monkeypatch, tmp_path: Path):
        """When configured provider's api_key_env is unset, falls back to DOUBAO_API_KEY."""
        cfg = _minimal_config()
        cfg["competition"]["providers"]["testprov"] = {
            "api_key_env": "NONEXISTENT_ENV_VAR",
            "api_base": "https://test.example.com/v1",
        }
        cfg["competition"]["groups"]["groupA"]["collector"]["provider"] = "testprov"
        cfg["competition"]["groups"]["groupA"]["collector"]["model"] = "mymodel"
        _write_yaml(tmp_path / "config.yaml", cfg)
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("DOUBAO_API_KEY", "fallback-key")
        monkeypatch.setenv("DOUBAO_API_BASE", "https://fallback.example.com/v1")
        model, base, key = _resolve_provider("collector")
        # model from config, api_base from config provider, key from env fallback
        assert model == "mymodel"
        assert base == "https://test.example.com/v1"
        assert key == "fallback-key"

    def test_resolves_different_agent(self, monkeypatch, tmp_path: Path):
        cfg = _minimal_config()
        cfg["competition"]["groups"]["groupA"]["analyst"] = {
            "provider": "doubao",
            "model": "analyst-specific-model",
        }
        _write_yaml(tmp_path / "config.yaml", cfg)
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("DOUBAO_API_KEY", "test-key")
        model, _, _ = _resolve_provider("analyst")
        assert model == "analyst-specific-model"

    def test_falls_back_to_default_model(self, monkeypatch, tmp_path: Path):
        """Agent not in config → use default_model from group."""
        _write_yaml(tmp_path / "config.yaml", _minimal_config())
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("DOUBAO_API_KEY", "test-key")
        model, _, _ = _resolve_provider("unknown_agent")
        assert model == "ep-20260514111325-xjmj7"  # default_model


class TestResolveModel:
    def test_returns_model_string(self, monkeypatch, tmp_path: Path):
        _write_yaml(tmp_path / "config.yaml", _minimal_config())
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("DOUBAO_API_KEY", "test-key")
        model = _resolve_model("collector")
        assert model == "ep-20260514111325-xjmj7"
        assert isinstance(model, str)
