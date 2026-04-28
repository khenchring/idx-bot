#!/usr/bin/env python3
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import argparse
import threading


def parse_args():
    p = argparse.ArgumentParser(description="Indodax AI Trading Bot")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--live",    action="store_true")
    p.add_argument("--pair",    type=str)
    p.add_argument("--once",    action="store_true")
    p.add_argument("--port",    type=int, default=5000)
    p.add_argument("--no-ui",   action="store_true", help="Disable web dashboard")
    return p.parse_args()


def main():
    args = parse_args()

    if args.dry_run: os.environ["DRY_RUN"] = "true"
    if args.live:    os.environ["DRY_RUN"] = "false"
    if args.pair:    os.environ["TRADING_PAIR"] = args.pair.lower()

    from config import cfg
    from bot_logger import get_logger
    log = get_logger("main")

    try:
        cfg.validate()
    except ValueError as e:
        log.error(str(e))
        sys.exit(1)

    if cfg.DRY_RUN:
        log.warning("=== DRY RUN — no real orders ===")
    else:
        log.warning("=== LIVE TRADING — real orders WILL be sent ===")
        confirm = input("Type 'yes' to confirm: ").strip().lower()
        if confirm != "yes":
            log.info("Aborted.")
            sys.exit(0)

    # Start web dashboard in background thread
    if not args.no_ui:
        import server
        t = threading.Thread(target=server.run_server, kwargs={"port": args.port}, daemon=True)
        t.start()
        log.info(f"Dashboard running at http://localhost:{args.port}")

    from trader import Trader
    bot = Trader()

    if args.once:
        bot.run_cycle()
    else:
        bot.start()


if __name__ == "__main__":
    main()
