"""Order placement via py-clob-client-v2. FOK only: fill at the listed price or fail."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from py_clob_client_v2.client import ClobClient
from py_clob_client_v2.clob_types import (
    ApiCreds,
    OrderArgsV2,
    OrderType,
    PartialCreateOrderOptions,
)
from py_clob_client_v2.order_builder.constants import BUY

from strategy.config import Config


@dataclass(frozen=True)
class OrderResult:
    order_id: Optional[str]
    status: str
    filled_size: float
    error: Optional[str]


def build_client(cfg: Config) -> ClobClient:
    creds = ApiCreds(
        api_key=cfg.api_key,
        api_secret=cfg.api_secret,
        api_passphrase=cfg.api_passphrase,
    )
    return ClobClient(
        cfg.clob_host,
        chain_id=cfg.chain_id,
        key=cfg.private_key,
        creds=creds,
        signature_type=cfg.signature_type,
        funder=cfg.funder_address,
    )


def place_buy_fok(
    client: ClobClient,
    *,
    token_id: str,
    price: float,
    size: float,
    tick_size: float,
    neg_risk: bool,
) -> OrderResult:
    """Fill-or-kill BUY: take exactly `size` at <=`price` now, or do nothing."""
    args = OrderArgsV2(token_id=token_id, price=price, size=size, side=BUY)
    opts = PartialCreateOrderOptions(tick_size=str(tick_size), neg_risk=neg_risk)
    try:
        signed = client.create_order(args, opts)
        resp = client.post_order(signed, order_type=OrderType.FOK)
    except Exception as e:
        return OrderResult(order_id=None, status="error", filled_size=0.0, error=str(e))

    return OrderResult(
        order_id=resp.get("orderID") or resp.get("orderId"),
        status=str(resp.get("status") or "unknown"),
        filled_size=float(resp.get("makingAmount") or resp.get("filled") or 0.0),
        error=resp.get("errorMsg") or None,
    )
