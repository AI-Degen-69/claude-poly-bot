"""One-time on-chain setup for trading on Polymarket V2.

Steps performed:
  1. USDC.e.approve(CollateralOnramp, MAX) if not already
  2. CollateralOnramp.wrap(USDC.e, wallet, balance)  -> mints pUSD 1:1
  3. pUSD.approve(exchange, MAX) for each of the 3 V2 exchange contracts

Idempotent: skips any step whose result is already in place.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

from dotenv import dotenv_values
from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware

ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT / ".env"

USDC_E = Web3.to_checksum_address("0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174")
PUSD = Web3.to_checksum_address("0xC011a7E12a19f7B1f670d46F03B03f3342E82DFB")
COLLATERAL_ONRAMP = Web3.to_checksum_address("0x93070a847efEf7F70739046A929D47a521F5B8ee")
EXCHANGES = [
    Web3.to_checksum_address("0xE111180000d2663C0091e4f400237545B87B996B"),  # CTF Exchange
    Web3.to_checksum_address("0xd91E80cF2E7be2e162c6513ceD06f1dD0dA35296"),  # NegRisk Adapter (?)
    Web3.to_checksum_address("0xe2222d279d744050d28e00520010520000310F59"),  # NegRisk CTF Exchange
]
MAX_UINT = 2**256 - 1

ERC20_ABI = [
    {"name": "approve", "type": "function", "stateMutability": "nonpayable",
     "inputs": [{"name": "spender", "type": "address"}, {"name": "amount", "type": "uint256"}],
     "outputs": [{"type": "bool"}]},
    {"name": "allowance", "type": "function", "stateMutability": "view",
     "inputs": [{"name": "owner", "type": "address"}, {"name": "spender", "type": "address"}],
     "outputs": [{"type": "uint256"}]},
    {"name": "balanceOf", "type": "function", "stateMutability": "view",
     "inputs": [{"name": "owner", "type": "address"}],
     "outputs": [{"type": "uint256"}]},
]

ONRAMP_ABI = [
    {"name": "wrap", "type": "function", "stateMutability": "nonpayable",
     "inputs": [
         {"name": "_asset", "type": "address"},
         {"name": "_to", "type": "address"},
         {"name": "_amount", "type": "uint256"},
     ],
     "outputs": []},
]


def send(w3: Web3, acct, tx_fn, nonce: Optional[int] = None) -> str:
    # Polygon base fee swings wildly; pull live and pad heavily.
    base = w3.eth.get_block("latest")["baseFeePerGas"]
    priority = w3.to_wei(35, "gwei")
    # Pull priority hint from fee history; fall back to 35 gwei.
    try:
        hist = w3.eth.fee_history(5, "latest", [50])
        med = max(int(r[0]) for r in hist["reward"])
        priority = max(priority, med + w3.to_wei(5, "gwei"))
    except Exception:
        pass
    max_fee = base * 2 + priority

    base_tx = tx_fn.build_transaction(
        {
            "from": acct.address,
            "nonce": nonce if nonce is not None else w3.eth.get_transaction_count(acct.address, "pending"),
            "chainId": 137,
            "gas": 250000,
            "maxFeePerGas": max_fee,
            "maxPriorityFeePerGas": priority,
        }
    )
    signed = acct.sign_transaction(base_tx)
    raw = getattr(signed, "raw_transaction", None) or signed.rawTransaction
    h = w3.eth.send_raw_transaction(raw)
    receipt = w3.eth.wait_for_transaction_receipt(h, timeout=180)
    if receipt.status != 1:
        raise RuntimeError(f"tx reverted: {h.hex()}")
    return h.hex()


def main() -> int:
    env = dotenv_values(ENV_PATH)
    w3 = Web3(Web3.HTTPProvider(env["POLYGON_RPC_URL"]))
    w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
    acct = w3.eth.account.from_key(env["PRIVATE_KEY"])
    print(f"acting as {acct.address}")

    usdc = w3.eth.contract(address=USDC_E, abi=ERC20_ABI)
    pusd = w3.eth.contract(address=PUSD, abi=ERC20_ABI)
    onramp = w3.eth.contract(address=COLLATERAL_ONRAMP, abi=ONRAMP_ABI)

    # Step 1: approve onramp to spend USDC.e
    cur = usdc.functions.allowance(acct.address, COLLATERAL_ONRAMP).call()
    if cur < 2**128:
        print("  approving USDC.e -> CollateralOnramp...")
        tx = send(w3, acct, usdc.functions.approve(COLLATERAL_ONRAMP, MAX_UINT))
        print(f"    {tx}")
    else:
        print("  USDC.e->onramp allowance already set")

    # Step 2: wrap full USDC.e balance to pUSD
    usdc_bal = usdc.functions.balanceOf(acct.address).call()
    if usdc_bal > 0:
        print(f"  wrapping {usdc_bal/1e6:.6f} USDC.e -> pUSD...")
        tx = send(w3, acct, onramp.functions.wrap(USDC_E, acct.address, usdc_bal))
        print(f"    {tx}")
    else:
        print("  no USDC.e to wrap")

    pusd_bal = pusd.functions.balanceOf(acct.address).call()
    print(f"  pUSD balance now: {pusd_bal/1e6:.6f}")

    # Step 3: approve each exchange contract to spend pUSD
    for ex in EXCHANGES:
        cur = pusd.functions.allowance(acct.address, ex).call()
        if cur < 2**128:
            print(f"  approving pUSD -> {ex[:10]}...")
            tx = send(w3, acct, pusd.functions.approve(ex, MAX_UINT))
            print(f"    {tx}")
        else:
            print(f"  pUSD->{ex[:10]} already approved")

    print("done.")
    print()
    print("NEXT STEP:")
    print("  1. Import your private key into MetaMask (Add account -> Import).")
    print("     Confirm the imported address matches WALLET_ADDRESS in .env.")
    print("  2. Log into https://polymarket.com with that MetaMask account.")
    print("     Polymarket auto-deploys a 'deposit wallet' contract for you.")
    print("  3. On polymarket.com -> avatar -> Wallet, copy the deposit address")
    print("     (starts with 0x, DIFFERENT from your EOA).")
    print("  4. Run:  .venv/bin/python scripts/migrate_to_deposit_wallet.py 0xYOUR_DEPOSIT_ADDR")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
