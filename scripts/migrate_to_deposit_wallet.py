"""Migrate funds and config to a Polymarket V2 deposit wallet (sig_type 3).

Usage:
    .venv/bin/python scripts/migrate_to_deposit_wallet.py 0xDEPOSIT_WALLET_ADDR

Steps:
  1. Verify deposit wallet exists on-chain (has code) — refuses to send funds to
     an EOA by mistake.
  2. Transfer the full pUSD balance from EOA -> deposit wallet.
  3. Upsert DEPOSIT_WALLET_ADDRESS, set FUNDER_ADDRESS = deposit, SIGNATURE_TYPE = 3.

Idempotent: skips transfer if balance is already 0.
"""
from __future__ import annotations

import sys
from pathlib import Path

from dotenv import dotenv_values
from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware

ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT / ".env"

PUSD = Web3.to_checksum_address("0xC011a7E12a19f7B1f670d46F03B03f3342E82DFB")

ERC20_ABI = [
    {"name": "transfer", "type": "function", "stateMutability": "nonpayable",
     "inputs": [{"name": "to", "type": "address"}, {"name": "amount", "type": "uint256"}],
     "outputs": [{"type": "bool"}]},
    {"name": "balanceOf", "type": "function", "stateMutability": "view",
     "inputs": [{"name": "owner", "type": "address"}],
     "outputs": [{"type": "uint256"}]},
]


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
        out.append("# V2 deposit wallet")
        for k in keys:
            out.append(f"{k}={updates[k]}")
    ENV_PATH.write_text("\n".join(out) + "\n")
    ENV_PATH.chmod(0o600)


def send(w3: Web3, acct, tx_fn) -> str:
    base = w3.eth.get_block("latest")["baseFeePerGas"]
    priority = w3.to_wei(60, "gwei")
    try:
        hist = w3.eth.fee_history(5, "latest", [50])
        med = max(int(r[0]) for r in hist["reward"])
        priority = max(priority, med + w3.to_wei(10, "gwei"))
    except Exception:
        pass
    tx = tx_fn.build_transaction(
        {
            "from": acct.address,
            "nonce": w3.eth.get_transaction_count(acct.address, "pending"),
            "chainId": 137,
            "gas": 120000,
            "maxFeePerGas": base * 3 + priority,
            "maxPriorityFeePerGas": priority,
        }
    )
    signed = acct.sign_transaction(tx)
    raw = getattr(signed, "raw_transaction", None) or signed.rawTransaction
    h = w3.eth.send_raw_transaction(raw)
    receipt = w3.eth.wait_for_transaction_receipt(h, timeout=240)
    if receipt.status != 1:
        raise RuntimeError(f"tx reverted: {h.hex()}")
    return h.hex()


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: migrate_to_deposit_wallet.py 0xDEPOSIT_ADDR", file=sys.stderr)
        return 2

    deposit = Web3.to_checksum_address(sys.argv[1])
    env = dotenv_values(ENV_PATH)
    w3 = Web3(Web3.HTTPProvider(env["POLYGON_RPC_URL"]))
    w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
    acct = w3.eth.account.from_key(env["PRIVATE_KEY"])

    # Safety: make sure target has contract code — never send funds to an EOA address by mistake.
    code = w3.eth.get_code(deposit)
    if len(code) == 0:
        print(f"FATAL: {deposit} has no contract code; not a deployed deposit wallet", file=sys.stderr)
        print("Did you log into polymarket.com with this EOA yet?", file=sys.stderr)
        return 1
    print(f"deposit wallet {deposit} verified (code bytes: {len(code)})")

    pusd = w3.eth.contract(address=PUSD, abi=ERC20_ABI)
    bal = pusd.functions.balanceOf(acct.address).call()
    if bal > 0:
        print(f"transferring {bal/1e6:.6f} pUSD: EOA -> deposit wallet")
        tx = send(w3, acct, pusd.functions.transfer(deposit, bal))
        print(f"  {tx}")
    else:
        print("EOA pUSD balance is 0; nothing to transfer")

    new_dep_bal = pusd.functions.balanceOf(deposit).call()
    print(f"deposit wallet pUSD balance now: {new_dep_bal/1e6:.6f}")

    upsert_env(
        {
            "DEPOSIT_WALLET_ADDRESS": deposit,
            "FUNDER_ADDRESS": deposit,
            "SIGNATURE_TYPE": "3",
        }
    )
    print("env updated: FUNDER_ADDRESS=<deposit>, SIGNATURE_TYPE=3")
    print()
    print("NEXT STEP:")
    print("  1. Derive L2 API credentials:   .venv/bin/python scripts/derive_api_creds.py")
    print("  2. Verify everything works:     .venv/bin/python scripts/verify_setup.py")
    print("  3. Launch dashboard:            scripts/run_dashboard.sh")
    print("  4. (When ready) launch bot:     scripts/run_live.sh")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
