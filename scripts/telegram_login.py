#!/usr/bin/env python3
"""
Interactive Telegram session bootstrapper for Ainara.

Creates/updates:
  - apis.messaging.telegram.api_id
  - apis.messaging.telegram.api_hash
  - apis.messaging.telegram.session_path
and finally produces an authenticated Telethon session file.
"""

import asyncio
import sys
from pathlib import Path

import yaml
from telethon import TelegramClient

# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------
CONFIG_PATHS = [
    Path.home() / ".config" / "ainara" / "ainara.yaml",
]


def find_config() -> Path:
    for p in CONFIG_PATHS:
        if p.exists():
            return p
    # default to the first one
    return CONFIG_PATHS[0]


def load_config(path: Path) -> dict:
    if not path.exists():
        return {}
    with path.open() as fh:
        return yaml.safe_load(fh) or {}


def save_config(path: Path, cfg: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as fh:
        yaml.safe_dump(cfg, fh, default_flow_style=False, sort_keys=False)
    print(f"✏️  Config written to {path}")


# ------------------------------------------------------------------
# ------------------------------------------------------------------
# ------------------------------------------------------------------
# ------------------------------------------------------------------
# Interactive part
# ------------------------------------------------------------------
async def main():
    print("=== Ainara Telegram Connector Setup ===\n")

    cfg_path = find_config()
    cfg = load_config(cfg_path)

    # Ensure we have the required section skeleton
    telegram_cfg = cfg.setdefault("apis", {}).setdefault("messaging", {}).setdefault("telegram", {})

    # Ask for API credentials
    api_id = telegram_cfg.get("api_id") or input("Telegram api_id: ").strip()
    print(f"api_id:'{api_id}'")

    # if not api_id.isdigit():
    #     print("api_id must be numeric.")
    #     return 1
    api_id = int(api_id)

    api_hash = telegram_cfg.get("api_hash") or input("Telegram api_hash: ").strip()
    if not api_hash:
        print("api_hash cannot be empty.")
        return 1

    # Choose session file location
    default_session = Path.home() / ".local" / "share" / "ainara" / "telegram.session"
    session_path = telegram_cfg.get("session_path") or str(default_session)
    session_path = Path(input(f"Session file path [{session_path}]: ").strip() or session_path)
    session_path = session_path.expanduser().resolve()
    session_path.parent.mkdir(parents=True, exist_ok=True)

    # Persist the three keys right now so the connector can find them
    telegram_cfg.update({"api_id": api_id, "api_hash": api_hash, "session_path": str(session_path)})
    save_config(cfg_path, cfg)

    # Log-in / authorise
    print("\nConnecting to Telegram…")
    async with TelegramClient(session_path, api_id, api_hash) as client:
        if not await client.is_user_authorized():
            print("Sending code request…")
            await client.send_code_request(input("Phone (international format, e.g. +1234567890): ").strip())
            await client.sign_in(input("Code: ").strip())
        me = await client.get_me()
        print(f"✅ Authorised as {me.first_name} (@{me.username})")

    print(f"\nSession file created: {session_path}")
    print("You can now start Ainara; the Telegram connector will use these credentials.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
