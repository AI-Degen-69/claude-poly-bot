"""One-time L1 -> L2 auth. Derive API credentials from PRIVATE_KEY and save to .env.

Refuses to overwrite if CLOB_API_KEY is already set, to avoid clobbering a known-good
credential set.
"""
from __future__ import annotations

import sys
from pathlib import Path

from dotenv import dotenv_values
from py_clob_client.client import ClobClient

ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT / ".env"


def upsert_env(updates: dict[str, str]) -> None:
    lines = ENV_PATH.read_text().splitlines() if ENV_PATH.exists() else []
    keys = set(updates)
    out: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            out.append(line)
            continue
        k = stripped.split("=", 1)[0].strip()
        if k in keys:
            out.append(f"{k}={updates[k]}")
            keys.discard(k)
        else:
            out.append(line)
    if keys:
        if out and out[-1].strip():
            out.append("")
        out.append("# L2 API credentials (derived via L1 signature)")
        for k in keys:
            out.append(f"{k}={updates[k]}")
    ENV_PATH.write_text("\n".join(out) + "\n")


def main() -> int:
    env = dotenv_values(ENV_PATH)
    if env.get("CLOB_API_KEY"):
        print("CLOB_API_KEY already set in .env — refusing to overwrite", file=sys.stderr)
        return 1

    pk = env["PRIVATE_KEY"]
    host = env.get("CLOB_HOST", "https://clob.polymarket.com")
    chain_id = int(env.get("CHAIN_ID", "137"))

    client = ClobClient(host, key=pk, chain_id=chain_id)
    creds = client.create_or_derive_api_creds()

    upsert_env(
        {
            "CLOB_API_KEY": creds.api_key,
            "CLOB_API_SECRET": creds.api_secret,
            "CLOB_API_PASSPHRASE": creds.api_passphrase,
        }
    )
    ENV_PATH.chmod(0o600)
    print("L2 credentials derived and saved to .env (chmod 600)")
    print()
    print("NEXT STEP:")
    print("  Verify everything end-to-end:   .venv/bin/python scripts/verify_setup.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
