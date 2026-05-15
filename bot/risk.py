"""Risk caps. Returns (allowed, reason)."""
from __future__ import annotations

from bot.config import Config
from bot.store import consecutive_losses, open_positions_count, realized_pnl_today


def allowed_to_trade(cfg: Config, dry_run: bool) -> tuple[bool, str]:
    if open_positions_count(dry_run) >= cfg.max_open_positions:
        return False, f"max_open_positions ({cfg.max_open_positions}) reached"
    pnl = realized_pnl_today(dry_run)
    if pnl <= -cfg.max_daily_loss_usd:
        return False, f"daily loss ${pnl:.2f} <= -${cfg.max_daily_loss_usd}"
    streak = consecutive_losses(dry_run)
    if streak >= cfg.consecutive_loss_kill:
        return False, f"consecutive losses ({streak}) >= kill threshold"
    return True, "ok"
