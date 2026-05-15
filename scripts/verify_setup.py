"""End-to-end setup check. Run this after every setup step to confirm you're
on track. Prints a friendly pass/fail summary with exact next-step guidance."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT / ".env"

OK = "[ OK ]"
FAIL = "[FAIL]"
WARN = "[WARN]"


def banner(s: str) -> None:
    print()
    print("=" * 64)
    print("  " + s)
    print("=" * 64)


def main() -> int:
    banner("polybot setup check")
    failures: list[str] = []
    warnings: list[str] = []

    # ---- 1: .env exists -----------------------------------------------------
    if not ENV_PATH.exists():
        print(f"{FAIL} .env not found")
        print("        -> run: .venv/bin/python scripts/generate_wallet.py")
        return 1
    print(f"{OK} .env exists")

    from dotenv import dotenv_values
    env = dotenv_values(ENV_PATH)

    required = ["PRIVATE_KEY", "WALLET_ADDRESS", "FUNDER_ADDRESS", "SIGNATURE_TYPE",
                "CHAIN_ID", "POLYGON_RPC_URL", "CLOB_HOST", "GAMMA_HOST"]
    missing = [k for k in required if not env.get(k)]
    if missing:
        print(f"{FAIL} .env missing required keys: {missing}")
        return 1
    print(f"{OK} .env has required base fields")

    # ---- 2: dependencies importable ----------------------------------------
    try:
        from py_clob_client_v2.client import ClobClient  # noqa: F401
        from web3 import Web3  # noqa: F401
    except ImportError as e:
        print(f"{FAIL} python deps missing: {e}")
        print("        -> run: .venv/bin/pip install -r requirements.txt")
        return 1
    print(f"{OK} python deps importable")

    # ---- 3: on-chain wallet balances ---------------------------------------
    import requests
    rpc = env["POLYGON_RPC_URL"]
    wallet = env["WALLET_ADDRESS"]

    def eth_call(to: str, data: str) -> str:
        r = requests.post(rpc, json={
            "jsonrpc": "2.0", "id": 1, "method": "eth_call",
            "params": [{"to": to, "data": data}, "latest"]
        }, timeout=10).json()
        return r.get("result") or "0x0"

    def balance_pol(addr: str) -> float:
        r = requests.post(rpc, json={
            "jsonrpc": "2.0", "id": 1, "method": "eth_getBalance",
            "params": [addr, "latest"]
        }, timeout=10).json()
        return int(r["result"], 16) / 1e18

    def balance_erc20(token: str, owner: str, decimals: int = 6) -> float:
        padded = owner.lower().replace("0x", "").rjust(64, "0")
        raw = eth_call(token, "0x70a08231" + padded)
        return int(raw, 16) / (10 ** decimals)

    USDC_E = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"
    PUSD = "0xC011a7E12a19f7B1f670d46F03B03f3342E82DFB"

    eoa_pol = balance_pol(wallet)
    eoa_usdc = balance_erc20(USDC_E, wallet)
    eoa_pusd = balance_erc20(PUSD, wallet)

    print(f"{OK} bot EOA: {wallet}")
    print(f"        POL:    {eoa_pol:.4f}")
    print(f"        USDC.e: {eoa_usdc:.4f}")
    print(f"        pUSD:   {eoa_pusd:.4f}")
    if eoa_pol < 0.05:
        warnings.append("EOA has very little POL; orders may fail when bot needs gas. "
                        "Send ~1 POL/MATIC to WALLET_ADDRESS.")

    # ---- 4: signature type 3 + deposit wallet ------------------------------
    sig_type = env.get("SIGNATURE_TYPE", "0")
    funder = env.get("FUNDER_ADDRESS", "")
    if sig_type != "3" or funder.lower() == wallet.lower():
        print(f"{FAIL} not configured for V2 deposit wallet")
        print(f"        SIGNATURE_TYPE={sig_type}, FUNDER_ADDRESS={funder}")
        print("        -> register your EOA on polymarket.com (it deploys the deposit")
        print("           wallet), then run:")
        print("           .venv/bin/python scripts/migrate_to_deposit_wallet.py 0xYOUR_DEPOSIT")
        failures.append("deposit wallet not configured")
    else:
        # check deposit wallet has contract code AND its owner() == our EOA
        from web3 import Web3
        from web3.middleware import ExtraDataToPOAMiddleware
        w3 = Web3(Web3.HTTPProvider(rpc))
        w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
        deposit = Web3.to_checksum_address(funder)

        code = w3.eth.get_code(deposit)
        if len(code) == 0:
            print(f"{FAIL} FUNDER_ADDRESS {deposit} has no contract code")
            print("        That address isn't a real deposit wallet. Recheck step 5 of README.")
            failures.append("deposit wallet has no code")
        else:
            owner_raw = eth_call(deposit, "0x8da5cb5b")
            owner = "0x" + owner_raw[-40:]
            if owner.lower() != wallet.lower():
                print(f"{FAIL} deposit wallet {deposit} is owned by {owner}")
                print(f"        That is NOT your bot EOA ({wallet}).")
                print("        You signed into polymarket.com with the wrong MetaMask account.")
                print("        Withdraw funds from polymarket.com, re-do step 5 (using BOT wallet),")
                print("        then re-run scripts/migrate_to_deposit_wallet.py with the NEW address.")
                failures.append("deposit wallet owner mismatch")
            else:
                print(f"{OK} deposit wallet: {deposit}")
                dep_pusd = balance_erc20(PUSD, deposit)
                print(f"        pUSD: {dep_pusd:.4f}")
                if dep_pusd < 5.0:
                    warnings.append(f"deposit wallet has only {dep_pusd:.2f} pUSD; "
                                    "send funds or rewrap.")

    # ---- 5: L2 API credentials ---------------------------------------------
    creds_ok = all(env.get(k) for k in ["CLOB_API_KEY", "CLOB_API_SECRET", "CLOB_API_PASSPHRASE"])
    if not creds_ok:
        print(f"{FAIL} L2 API credentials missing in .env")
        print("        -> run: .venv/bin/python scripts/derive_api_creds.py")
        failures.append("L2 creds missing")
    else:
        try:
            from py_clob_client_v2.client import ClobClient
            from py_clob_client_v2.clob_types import ApiCreds, BalanceAllowanceParams, AssetType
            c = ClobClient(
                env["CLOB_HOST"], chain_id=int(env["CHAIN_ID"]), key=env["PRIVATE_KEY"],
                creds=ApiCreds(env["CLOB_API_KEY"], env["CLOB_API_SECRET"], env["CLOB_API_PASSPHRASE"]),
                signature_type=int(env.get("SIGNATURE_TYPE", "0")),
                funder=env.get("FUNDER_ADDRESS"),
            )
            ba = c.get_balance_allowance(BalanceAllowanceParams(asset_type=AssetType.COLLATERAL))
            bal = int(ba["balance"]) / 1e6
            print(f"{OK} CLOB sees pUSD balance: {bal:.4f}")
            allowances = ba.get("allowances") or {}
            ok_allowances = sum(1 for v in allowances.values() if int(v) > 10**30)
            if ok_allowances < 3:
                print(f"{WARN} only {ok_allowances}/3 exchange allowances set; "
                      f"some markets may be unfundable.")
                warnings.append("not all exchange allowances are set")
            else:
                print(f"{OK} exchange allowances set on all 3 V2 contracts")
        except Exception as e:
            print(f"{FAIL} CLOB auth check failed: {e}")
            failures.append("CLOB auth failed")

    # ---- summary -----------------------------------------------------------
    banner("summary")
    if not failures:
        print("ALL CHECKS PASSED. you're ready to trade.")
        print()
        print("Start dashboard:  scripts/run_dashboard.sh   (then open http://127.0.0.1:5173)")
        print("Start bot:        scripts/run_live.sh")
        print("Stop bot:         scripts/stop_live.sh")
        if warnings:
            print()
            print("Warnings:")
            for w in warnings:
                print(f"  - {w}")
        return 0
    else:
        print(f"{len(failures)} check(s) failed:")
        for f in failures:
            print(f"  - {f}")
        print()
        print("Fix the failures above, then re-run this script.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
