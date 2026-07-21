"""Copy-trade tracker loop: poll all accounts, resolve, repeat.

Read-only + simulate. Records each account's fills into follow_fills and marks
resolutions; never places a real order. Runs alongside (or instead of) the
bonereaper sim.
"""
from __future__ import annotations

import logging
import os
import time
from pathlib import Path

from follow import store, resolver
from follow.accounts import ACCOUNTS, SHADOW_ACCOUNT
from follow.poller import poll_account
from follow.shadow import run_shadow

log = logging.getLogger("follow")

POLL_SEC = float(os.environ.get("FOLLOW_POLL_SEC", "4"))
RESOLVE_SEC = float(os.environ.get("FOLLOW_RESOLVE_SEC", "30"))


def loop() -> None:
    ROOT = Path(__file__).resolve().parent.parent
    try:
        (ROOT / "follow.pid").write_text(str(os.getpid()))
    except Exception:
        pass

    log.info("follow tracker starting backend=%s accounts=%s",
             store.backend_name(), [a.key for a in ACCOUNTS])
    # Materialize schema.
    with store.db():
        pass

    last_resolve = 0.0
    while True:
        t0 = time.time()
        for a in ACCOUNTS:
            try:
                poll_account(a)
            except Exception as e:
                log.warning("%s poll error: %s", a.key, e)

        # Follower simulation: price the freshest un-attempted fills against the
        # real book. Runs right after polling so our latency stays honest --
        # any delay here shows up in the measured slippage, as it should.
        try:
            run_shadow(SHADOW_ACCOUNT, limit=60)
        except Exception as e:
            log.warning("shadow error: %s", e)

        if time.time() - last_resolve > RESOLVE_SEC:
            try:
                n = resolver.resolve_pending(limit=80)
                if n:
                    log.info("resolved %d markets", n)
            except Exception as e:
                log.warning("resolve error: %s", e)
            last_resolve = time.time()

        elapsed = time.time() - t0
        time.sleep(max(0.0, POLL_SEC - elapsed))


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )
    try:
        loop()
    except KeyboardInterrupt:
        log.info("shutdown")


if __name__ == "__main__":
    main()
