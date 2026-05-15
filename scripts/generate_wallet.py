"""Generate a fresh EOA wallet for Polymarket trading and write it to .env.

Run once. Refuses to overwrite an existing .env so a funded key can't be lost.
"""
from __future__ import annotations

import secrets
import sys
from pathlib import Path

from eth_account import Account

Account.enable_unaudited_hdwallet_features()

ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT / ".env"
GITIGNORE_PATH = ROOT / ".gitignore"


def main() -> int:
    if ENV_PATH.exists():
        print(f"refusing to overwrite existing {ENV_PATH}", file=sys.stderr)
        return 1

    priv = "0x" + secrets.token_hex(32)
    acct = Account.from_key(priv)

    env = f"""# Polymarket trading wallet — KEEP SECRET. Never commit.
PRIVATE_KEY={priv}
WALLET_ADDRESS={acct.address}
FUNDER_ADDRESS={acct.address}
SIGNATURE_TYPE=0

# Network
CHAIN_ID=137
POLYGON_RPC_URL=https://polygon-bor-rpc.publicnode.com

# Polymarket endpoints
CLOB_HOST=https://clob.polymarket.com
GAMMA_HOST=https://gamma-api.polymarket.com
"""
    ENV_PATH.write_text(env)
    ENV_PATH.chmod(0o600)

    gi_lines = set()
    if GITIGNORE_PATH.exists():
        gi_lines = set(GITIGNORE_PATH.read_text().splitlines())
    for needed in (".env", ".env.*", "!.env.example"):
        gi_lines.add(needed)
    GITIGNORE_PATH.write_text("\n".join(sorted(gi_lines)) + "\n")

    print("wallet written to .env (chmod 600); address suppressed from stdout")
    print()
    print("NEXT STEP:")
    print("  1. Open .env, copy WALLET_ADDRESS, store the PRIVATE_KEY somewhere safe (1Password etc).")
    print("  2. Send a small amount of MATIC (~1) + USDC.e (>=$30) to WALLET_ADDRESS on Polygon.")
    print("  3. Verify with:  .venv/bin/python scripts/check_balance.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
