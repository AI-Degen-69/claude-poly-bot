"""Centralized config loaded from .env. Strategy knobs live here too."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


@dataclass(frozen=True)
class Config:
    private_key: str
    wallet_address: str
    funder_address: str
    signature_type: int
    chain_id: int
    clob_host: str
    gamma_host: str
    polygon_rpc: str
    api_key: str
    api_secret: str
    api_passphrase: str

    series_slug: str = "btc-up-or-down-5m"
    max_entry_price: float = 0.98
    min_spot_offset_bps: float = 5.0
    seconds_before_close: int = 35     # only fire in last 35s of window
    min_t_remaining_sec: float = 8.0   # avoid races to resolution
    order_size_shares: int = 5
    max_open_positions: int = 1
    max_daily_loss_usd: float = 10_000.0  # effectively disabled (wallet only holds ~$20)
    consecutive_loss_kill: int = 3
    poll_interval_sec: float = 0.25


def load() -> Config:
    return Config(
        private_key=os.environ["PRIVATE_KEY"],
        wallet_address=os.environ["WALLET_ADDRESS"],
        funder_address=os.environ["FUNDER_ADDRESS"],
        signature_type=int(os.environ.get("SIGNATURE_TYPE", "0")),
        chain_id=int(os.environ.get("CHAIN_ID", "137")),
        clob_host=os.environ.get("CLOB_HOST", "https://clob.polymarket.com"),
        gamma_host=os.environ.get("GAMMA_HOST", "https://gamma-api.polymarket.com"),
        polygon_rpc=os.environ.get(
            "POLYGON_RPC_URL", "https://polygon-bor-rpc.publicnode.com"
        ),
        api_key=os.environ["CLOB_API_KEY"],
        api_secret=os.environ["CLOB_API_SECRET"],
        api_passphrase=os.environ["CLOB_API_PASSPHRASE"],
    )
