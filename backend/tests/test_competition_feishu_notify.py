"""Tests for File-mode Feishu notification configuration."""

from __future__ import annotations

import yaml


def test_file_mode_reads_active_group_notification_toggle(monkeypatch, tmp_path):
    import competition.feishu_notify as notify

    config = {
        "competition": {
            "active_group": "debug",
            "groups": {
                "debug": {
                    "feishu": {
                        "notify_enabled": True,
                        "doc_auto_export": False,
                    },
                },
            },
        },
    }
    (tmp_path / "config.yaml").write_text(yaml.safe_dump(config), encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CI_AGENT_CONFIG_MODE", "file")

    assert notify.is_notify_enabled() is True


def test_file_mode_defaults_to_disabled_without_config(monkeypatch, tmp_path):
    import competition.feishu_notify as notify

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CI_AGENT_CONFIG_MODE", "file")

    assert notify.is_notify_enabled() is False
