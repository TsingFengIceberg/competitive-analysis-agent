"""Configuration mode selector.

CI_AGENT_CONFIG_MODE env var controls where config is read from:
  - "db"   (default): Database (user_settings table), no config.yaml/.env fallback
  - "file": config.yaml + .env, same as legacy behavior

Set before starting the gateway:
  CI_AGENT_CONFIG_MODE=file uv run uvicorn ...

Use `is_file_mode()` to check in any module that reads configuration.
"""

import os


def is_file_mode() -> bool:
    """Return True if config should be read from config.yaml + .env."""
    return os.environ.get("CI_AGENT_CONFIG_MODE", "db") == "file"
