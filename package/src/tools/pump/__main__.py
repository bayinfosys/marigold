"""
Marigold pump.

Usage:
    python3 -m tools.pump pump  [--once] [--interval N] [--concurrency N]
                                [--types a,b] [--skip-types a,b]

    python3 -m tools.pump audit [--date YYYY-MM-DD] [--days N]
                                [--force] [--poll] [--report]

    # no subcommand runs pump for backwards compatibility
    python3 -m tools.pump --once
"""
import argparse

from .pump  import cmd_pump
from .audit import cmd_audit


def main():
    p = argparse.ArgumentParser(
        description="Marigold pump",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = p.add_subparsers(dest="cmd")

    pp = sub.add_parser("pump",  help="submit jobs to the inference API")
    pp.add_argument("--interval",   type=int, default=30)
    pp.add_argument("--jitter",     type=int, default=2)
    pp.add_argument("--concurrency",    type=int, default=64)
    pp.add_argument("--once",       action="store_true")
    pp.add_argument("--types",      type=str, default="")
    pp.add_argument("--skip-types", type=str, default="")
    pp.add_argument("--rounds", type=int, default=0, help="number of rounds to run (default: 0 = unlimited, --once overrides)")
    pp.add_argument("--requests", type=int, default=1, help="number of requests per model per round (default: 1)")
    pp.add_argument("--models", default="", help="comma-separated model names to include")
    pp.add_argument("--order", default="grouped", choices=["grouped", "random", "interleaved"], help="job submission order")

    ap = sub.add_parser("audit", help="poll and report results from history")
    ap.add_argument("--date",   type=str, default="")
    ap.add_argument("--days",   type=int, default=1)
    ap.add_argument("--force",  action="store_true")
    ap.add_argument("--poll",   action="store_true", default=True)
    ap.add_argument("--report", action="store_true", default=True)

    args = p.parse_args()

    if args.cmd == "audit":
        cmd_audit(args)
    else:
        cmd_pump(args)


if __name__ == "__main__":
    main()
