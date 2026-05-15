"""Print POL (gas) and USDC.e (Polymarket collateral) balances for WALLET_ADDRESS."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT / ".env"

# Polymarket settles in USDC.e (bridged USDC) on Polygon.
USDC_E = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"
ERC20_BALANCE_OF = "0x70a08231"  # balanceOf(address) selector


def load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    for line in ENV_PATH.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip()
    return env


def rpc(url: str, method: str, params: list) -> str:
    r = requests.post(
        url,
        json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
        timeout=10,
    )
    r.raise_for_status()
    body = r.json()
    if "error" in body:
        raise RuntimeError(body["error"])
    return body["result"]


def main() -> int:
    env = load_env()
    address = env["WALLET_ADDRESS"]
    rpc_url = env.get("POLYGON_RPC_URL", "https://polygon-rpc.com")

    pol_wei = int(rpc(rpc_url, "eth_getBalance", [address, "latest"]), 16)
    pol = pol_wei / 1e18

    padded_addr = address.lower().replace("0x", "").rjust(64, "0")
    data = ERC20_BALANCE_OF + padded_addr
    usdc_raw = int(
        rpc(rpc_url, "eth_call", [{"to": USDC_E, "data": data}, "latest"]),
        16,
    )
    usdc = usdc_raw / 1e6  # USDC.e has 6 decimals

    print(f"address: {address}")
    print(f"POL  (gas):       {pol:.6f}")
    print(f"USDC.e (collat):  {usdc:.6f}")

    if pol < 0.1 or usdc < 1.0:
        print()
        print("WALLET NOT YET FUNDED.")
        print("  Send to the address above on POLYGON network:")
        print("    - MATIC (POL) for gas:  ~1 is plenty")
        print("    - USDC.e for trading:   $30+ recommended")
        print(f"    USDC.e contract: {USDC_E}")
        print()
        print("  How to fund: withdraw from a centralized exchange (Coinbase,")
        print("  Kraken, Binance, etc) selecting Polygon network. Or bridge")
        print("  from Ethereum via app.polygon.technology if you already hold")
        print("  USDC.e elsewhere.")
        return 1

    print()
    print("Funded! NEXT STEP: wrap your USDC.e to pUSD:")
    print("  .venv/bin/python scripts/wrap_to_pusd.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
