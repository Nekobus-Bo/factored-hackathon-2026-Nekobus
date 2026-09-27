from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from calibrate.runner import run_decision_calibration, run_embedding_calibration


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Unified calibration harness for decision and embedding models",
    )
    parser.add_argument(
        "--task",
        "-t",
        choices=["decision", "embedding"],
        required=True,
        help="Task to calibrate (decision or embedding)",
    )
    parser.add_argument(
        "--config",
        "-c",
        type=str,
        default=None,
        help="Path to YAML configuration file",
    )
    parser.add_argument(
        "--out",
        "-o",
        type=str,
        default="reports",
        help="Directory to save generated markdown report",
    )
    parser.add_argument(
        "--log-level",
        type=str,
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level",
    )

    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    if args.task == "decision":
        config_path = args.config or "tools/calibrate/configs/decision.yaml"
        if not Path(config_path).is_file():
            print(f"Error: Config file not found at {config_path}", file=sys.stderr)
            sys.exit(1)
        report_path = run_decision_calibration(config_path, args.out)
    elif args.task == "embedding":
        config_path = args.config or "tools/calibrate/configs/embedding.yaml"
        if not Path(config_path).is_file():
            print(f"Error: Config file not found at {config_path}", file=sys.stderr)
            sys.exit(1)
        report_path = run_embedding_calibration(config_path, args.out)
    else:
        print(f"Unknown task: {args.task}", file=sys.stderr)
        sys.exit(1)

    print(f"\n[OK] Calibration complete. Report generated at:\n{report_path}\n")
    print(report_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
