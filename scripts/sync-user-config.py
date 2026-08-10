#!/usr/bin/env python3
"""Sync user settings between config.yaml/.env and the SQLite user_settings table.

Usage:
    # Push: write config.yaml + .env values into a user's DB record
    uv run --project backend python scripts/sync-user-config.py push <user_email>

    # Pull: read a user's DB record and overwrite config.yaml + .env
    uv run --project backend python scripts/sync-user-config.py pull <user_email>

    # Dry-run: preview changes without writing
    uv run --project backend python scripts/sync-user-config.py push <user_email> --dry-run
    uv run --project backend python scripts/sync-user-config.py pull <user_email> --dry-run

Both directions support --dry-run to preview changes without writing.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path

# ── Resolve project root ──
PROJECT_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = PROJECT_ROOT / "backend"


def find_config_yaml() -> Path | None:
    """Find config.yaml (looks in project root and backend/)."""
    candidates = [
        PROJECT_ROOT / "config.yaml",
        BACKEND_DIR / "config.yaml",
    ]
    for p in candidates:
        if p.exists():
            return p
    return None


def find_env_file() -> Path | None:
    """Find .env file."""
    p = PROJECT_ROOT / ".env"
    return p if p.exists() else None


def find_db() -> Path | None:
    """Find competition SQLite DB."""
    for p in (PROJECT_ROOT / ".ci-agent" / "competition.db",
              BACKEND_DIR / ".ci-agent" / "competition.db"):
        if p.exists():
            return p
    return None


def read_config(path: Path) -> dict:
    """Read config.yaml and extract competition settings."""
    import yaml
    cfg = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    comp = cfg.get("competition") or {}
    active = comp.get("active_group") or "groupA"
    groups = comp.get("groups") or {}
    group = groups.get(active, {})

    settings: dict = {
        "active_group": active,
        "default_model": group.get("default_model", ""),
    }

    # Per-agent configs
    agent_configs: dict[str, dict] = {}
    for agent in ("orchestrator", "collector", "analyst", "reviewer", "writer"):
        ac = group.get(agent) or {}
        entry: dict = {}
        if ac.get("model"):
            entry["model"] = ac["model"]
        if ac.get("timeout_seconds"):
            entry["timeout_seconds"] = ac["timeout_seconds"]
        if ac.get("max_turns"):
            entry["max_turns"] = ac["max_turns"]
        if entry:
            agent_configs[agent] = entry
    settings["agent_configs"] = agent_configs

    # Search toggles
    search = group.get("search") or {}
    settings["search_toggles"] = {
        "provider_search": search.get("provider_search", True),
        "tavily": search.get("tavily", True),
        "ddg": search.get("ddg", True),
        "jina": search.get("jina", True),
    }

    return settings


def read_env(path: Path) -> dict:
    """Read .env and extract provider keys + feishu config."""
    env: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        env[key] = value

    provider_keys: dict[str, str] = {}
    for prov, env_var in [
        ("doubao", "DOUBAO_API_KEY"),
        ("deepseek", "DEEPSEEK_API_KEY"),
        ("qwen", "QWEN_API_KEY"),
        ("tavily", "TAVILY_API_KEY"),
        ("jina", "JINA_API_KEY"),
    ]:
        if env.get(env_var) and env[env_var] not in ("your-" + prov + "-api-key", ""):
            provider_keys[prov] = env[env_var]

    feishu_config: dict[str, str] = {}
    for key, env_var in [
        ("app_id", "FEISHU_APP_ID"),
        ("app_secret", "FEISHU_APP_SECRET"),
        ("notify_open_id", "FEISHU_NOTIFY_OPEN_ID"),
        ("tenant", "FEISHU_TENANT"),
    ]:
        val = env.get(env_var, "")
        if val and not val.startswith("your-"):
            feishu_config[key] = val

    return {"provider_keys": provider_keys, "feishu_config": feishu_config}


def ensure_db_initialized(db_path: Path) -> sqlite3.Connection:
    """Open competition DB and ensure user_settings table exists."""
    conn = sqlite3.connect(str(db_path))
    # Use the competition init_db pattern directly
    sys.path.insert(0, str(BACKEND_DIR / "packages" / "competition"))
    try:
        from competition.db import init_db
        init_db()
    except ImportError:
        # Fallback: create table manually
        conn.execute("""
            CREATE TABLE IF NOT EXISTS user_settings (
                user_id TEXT PRIMARY KEY,
                active_group TEXT DEFAULT 'groupA',
                default_model TEXT DEFAULT '',
                provider_keys TEXT DEFAULT '{}',
                agent_configs TEXT DEFAULT '{}',
                search_toggles TEXT DEFAULT '{}',
                feishu_config TEXT DEFAULT '{}',
                updated_at TEXT
            );
        """)
        conn.commit()
    return conn


def resolve_user_id(email: str, conn: sqlite3.Connection) -> str | None:
    # Resolve the user created by the standalone FastAPI auth service.
    for auth_path in (BACKEND_DIR / ".ci-agent" / "auth.db",
                      PROJECT_ROOT / ".ci-agent" / "auth.db"):
        if auth_path.exists():
            ac = sqlite3.connect(str(auth_path))
            row = ac.execute(
                "SELECT id FROM users WHERE email = ?", (email,)
            ).fetchone()
            ac.close()
            if row:
                return str(row[0])
    # Fallback: use email as user_id directly
    return email


def get_user_settings(user_id: str, conn: sqlite3.Connection) -> dict | None:
    """Read current user_settings from DB."""
    row = conn.execute(
        "SELECT active_group, default_model, provider_keys, agent_configs, "
        "search_toggles, feishu_config FROM user_settings WHERE user_id = ?",
        (user_id,),
    ).fetchone()
    if row is None:
        return None
    return {
        "active_group": row[0] or "groupA",
        "default_model": row[1] or "",
        "provider_keys": json.loads(row[2]) if row[2] else {},
        "agent_configs": json.loads(row[3]) if row[3] else {},
        "search_toggles": json.loads(row[4]) if row[4] else {},
        "feishu_config": json.loads(row[5]) if row[5] else {},
    }


def write_user_settings(user_id: str, settings: dict, conn: sqlite3.Connection) -> None:
    """Upsert user_settings row."""
    from datetime import UTC, datetime
    now = datetime.now(UTC).isoformat()
    conn.execute(
        """INSERT INTO user_settings
           (user_id, active_group, default_model, provider_keys, agent_configs,
            search_toggles, feishu_config, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(user_id) DO UPDATE SET
             active_group=excluded.active_group,
             default_model=excluded.default_model,
             provider_keys=excluded.provider_keys,
             agent_configs=excluded.agent_configs,
             search_toggles=excluded.search_toggles,
             feishu_config=excluded.feishu_config,
             updated_at=excluded.updated_at""",
        (
            user_id,
            settings.get("active_group", "groupA"),
            settings.get("default_model", ""),
            json.dumps(settings.get("provider_keys", {}), ensure_ascii=False),
            json.dumps(settings.get("agent_configs", {}), ensure_ascii=False),
            json.dumps(settings.get("search_toggles", {}), ensure_ascii=False),
            json.dumps(settings.get("feishu_config", {}), ensure_ascii=False),
            now,
        ),
    )
    conn.commit()


def write_env(path: Path, provider_keys: dict, feishu_config: dict, dry_run: bool) -> list[str]:
    """Update .env file with provider keys and feishu config. Returns list of changed keys."""
    env_map = {"provider_keys": provider_keys, "feishu_config": feishu_config}
    key_mapping = {
        "doubao": "DOUBAO_API_KEY",
        "deepseek": "DEEPSEEK_API_KEY",
        "qwen": "QWEN_API_KEY",
        "tavily": "TAVILY_API_KEY",
        "jina": "JINA_API_KEY",
        "app_id": "FEISHU_APP_ID",
        "app_secret": "FEISHU_APP_SECRET",
        "notify_open_id": "FEISHU_NOTIFY_OPEN_ID",
        "tenant": "FEISHU_TENANT",
    }

    lines = path.read_text(encoding="utf-8").splitlines()
    changed: list[str] = []

    for key_name, env_var in key_mapping.items():
        # Find value: first in provider_keys, then feishu_config
        value = provider_keys.get(key_name) or feishu_config.get(key_name, "")
        if not value:
            continue
        found = False
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith(f"{env_var}=") or stripped.startswith(f"# {env_var}="):
                lines[i] = f"{env_var}={value}"
                found = True
                changed.append(env_var)
                break
        if not found:
            lines.append(f"{env_var}={value}")
            changed.append(env_var)

    if not dry_run:
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return changed


def write_config_yaml(path: Path, settings: dict, dry_run: bool) -> list[str]:
    """Update config.yaml with active_group, default_model, search toggles, agent configs."""
    import yaml
    cfg = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    comp = cfg.setdefault("competition", {})

    active_group = settings.get("active_group", "groupA")
    comp["active_group"] = active_group

    groups = comp.setdefault("groups", {})
    group = groups.setdefault(active_group, {})

    changed: list[str] = []

    default_model = settings.get("default_model", "")
    if default_model and group.get("default_model") != default_model:
        group["default_model"] = default_model
        changed.append(f"groups.{active_group}.default_model")

    # Search toggles
    toggles = settings.get("search_toggles", {})
    if toggles:
        group.setdefault("search", {})
        for k in ("provider_search", "tavily", "ddg", "jina"):
            if k in toggles and group["search"].get(k) != toggles[k]:
                group["search"][k] = toggles[k]
                changed.append(f"groups.{active_group}.search.{k}")

    # Agent configs
    agent_configs = settings.get("agent_configs", {})
    for agent, ac in agent_configs.items():
        if not ac:
            continue
        group.setdefault(agent, {})
        for field, value in ac.items():
            if group[agent].get(field) != value:
                group[agent][field] = value
                changed.append(f"groups.{active_group}.{agent}.{field}")

    if not dry_run and changed:
        cfg["config_version"] = cfg.get("config_version", 1)
        path.write_text(yaml.dump(cfg, default_flow_style=False, allow_unicode=True), encoding="utf-8")
    return changed


def cmd_push(args) -> int:
    """Push: config.yaml + .env → user DB."""
    config_path = find_config_yaml()
    env_path = find_env_file()
    db_path = find_db()

    if not config_path or not config_path.exists():
        print("❌ config.yaml not found", file=sys.stderr)
        return 1
    if not db_path:
        print("❌ competition.db not found at .ci-agent/competition.db", file=sys.stderr)
        return 1

    config_settings = read_config(config_path)
    env_data = read_env(env_path) if env_path else {}
    merged = {**config_settings, **env_data}

    conn = ensure_db_initialized(db_path)
    user_id = resolve_user_id(args.email, conn)

    if args.dry_run:
        print(f"🔍 DRY RUN — would push to user_id={user_id} (email={args.email})")
        print(f"\n   config.yaml → {config_path}")
        for k, v in config_settings.items():
            if isinstance(v, dict):
                print(f"     {k}: {json.dumps(v, ensure_ascii=False)}")
            else:
                print(f"     {k}: {v}")
        if env_data:
            print(f"\n   .env → {env_path}")
            for k, v in env_data.items():
                if isinstance(v, dict):
                    for kk, vv in v.items():
                        if vv:
                            print(f"     {k}.{kk}: {'***' if 'secret' in kk or 'key' in k.lower() else vv}")
        return 0

    write_user_settings(user_id, merged, conn)
    conn.close()
    print(f"✅ Pushed config + env → user_id={user_id} (email={args.email})")
    return 0


def cmd_pull(args) -> int:
    """Pull: user DB → config.yaml + .env."""
    db_path = find_db()
    config_path = find_config_yaml()
    env_path = find_env_file()

    if not db_path:
        print("❌ competition.db not found at .ci-agent/competition.db", file=sys.stderr)
        return 1
    if not config_path:
        print("❌ config.yaml not found", file=sys.stderr)
        return 1

    conn = ensure_db_initialized(db_path)
    user_id = resolve_user_id(args.email, conn)
    settings = get_user_settings(user_id, conn)
    conn.close()

    if settings is None:
        print(f"❌ No settings found for user_id={user_id} (email={args.email})", file=sys.stderr)
        return 1

    if args.dry_run:
        print(f"🔍 DRY RUN — would pull from user_id={user_id} (email={args.email})")
        print(f"\n   → config.yaml ({config_path})")
        for k, v in sorted(settings.items()):
            if k == "provider_keys":
                for pk, pv in sorted(v.items()):
                    print(f"     provider_key.{pk}: {'***' if pv else '(empty)'}")
            elif isinstance(v, dict):
                print(f"     {k}: {json.dumps(v, ensure_ascii=False)}")
            else:
                print(f"     {k}: {v}")
        return 0

    # Write config.yaml
    config_changed = write_config_yaml(config_path, settings, dry_run=False)
    # Write .env
    env_changed: list[str] = []
    if env_path:
        env_changed = write_env(
            env_path,
            settings.get("provider_keys", {}),
            settings.get("feishu_config", {}),
            dry_run=False,
        )

    print(f"✅ Pulled settings from user_id={user_id} (email={args.email})")
    if config_changed:
        print(f"   config.yaml updated: {', '.join(config_changed)}")
    if env_changed:
        print(f"   .env updated: {', '.join(env_changed)}")
    if not config_changed and not env_changed:
        print("   (no changes)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Sync user settings between config.yaml/.env and competition DB",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = parser.add_subparsers(dest="command", required=True)
    for cmd_name, handler in [("push", cmd_push), ("pull", cmd_pull)]:
        p = sub.add_parser(cmd_name, help=f"{cmd_name}: {'config+env → DB' if cmd_name == 'push' else 'DB → config+env'}")
        p.add_argument("email", help="User email (matches gateway auth DB)")
        p.add_argument("--dry-run", action="store_true", help="Preview without writing")
        p.set_defaults(handler=handler)

    args = parser.parse_args()
    return args.handler(args)


if __name__ == "__main__":
    sys.exit(main())
