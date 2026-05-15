"""Replace the stuck tx at nonce 0 with a higher-gas USDC.e.approve to the onramp."""
from __future__ import annotations

from pathlib import Path

from dotenv import dotenv_values
from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware

ENV = dotenv_values(Path(__file__).resolve().parent.parent / ".env")

USDC_E = Web3.to_checksum_address("0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174")
COLLATERAL_ONRAMP = Web3.to_checksum_address("0x93070a847efEf7F70739046A929D47a521F5B8ee")
MAX_UINT = 2**256 - 1

ERC20_ABI = [
    {"name": "approve", "type": "function", "stateMutability": "nonpayable",
     "inputs": [{"name": "spender", "type": "address"}, {"name": "amount", "type": "uint256"}],
     "outputs": [{"type": "bool"}]},
]


def main() -> int:
    w3 = Web3(Web3.HTTPProvider(ENV["POLYGON_RPC_URL"]))
    w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
    acct = w3.eth.account.from_key(ENV["PRIVATE_KEY"])

    confirmed_nonce = w3.eth.get_transaction_count(acct.address, "latest")
    pending_nonce = w3.eth.get_transaction_count(acct.address, "pending")
    print(f"confirmed={confirmed_nonce} pending={pending_nonce}")
    if pending_nonce == confirmed_nonce:
        print("nothing pending; skip")
        return 0

    base = w3.eth.get_block("latest")["baseFeePerGas"]
    priority = w3.to_wei(80, "gwei")  # well above current ~127 priority observed
    max_fee = base * 3 + priority
    print(f"replacing nonce {confirmed_nonce}; baseFee={base/1e9:.0f} gwei, prio={priority/1e9:.0f}, max={max_fee/1e9:.0f}")

    usdc = w3.eth.contract(address=USDC_E, abi=ERC20_ABI)
    tx = usdc.functions.approve(COLLATERAL_ONRAMP, MAX_UINT).build_transaction(
        {
            "from": acct.address,
            "nonce": confirmed_nonce,
            "chainId": 137,
            "gas": 200000,
            "maxFeePerGas": max_fee,
            "maxPriorityFeePerGas": priority,
        }
    )
    signed = acct.sign_transaction(tx)
    raw = getattr(signed, "raw_transaction", None) or signed.rawTransaction
    h = w3.eth.send_raw_transaction(raw)
    print(f"replacement tx: {h.hex()}")
    receipt = w3.eth.wait_for_transaction_receipt(h, timeout=240)
    print(f"  status={receipt.status} block={receipt.blockNumber}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
