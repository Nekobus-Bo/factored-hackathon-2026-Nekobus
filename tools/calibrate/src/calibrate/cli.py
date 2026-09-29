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
        choices=["decision", "embedding", "decision-points"],
        required=True,
        help="Task to calibrate (decision, embedding or decision-points)",
    )
    parser.add_argument(
        "--config",
        "-c",
        type=str,
        default=None,
        help="Path to YAML configuration file",
    )
    parser.add_argument(
        "--dp",
        type=str,
        default=None,
        help="decision-points only: comma-separated decision point ids "
        "(default: every DP of the config)",
    )
    parser.add_argument(
        "--artifact",
        type=str,
        default=None,
        help="decision-points only: artifact file to merge into "
        "(default: the committed one for OUT=reports, else OUT/decision_points.json)",
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

    if (args.dp or args.artifact) and args.task != "decision-points":
        print(
            "Error: DP= and ARTIFACT= only apply to TASK=decision-points",
            file=sys.stderr,
        )
        sys.exit(1)

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    if args.task == "decision-points":
        from calibrate.dp import RunError, run_decision_points_calibration

        config_path = args.config or "tools/calibrate/configs/decision_points.yaml"
        if not Path(config_path).is_file():
            print(f"Error: Config file not found at {config_path}", file=sys.stderr)
            sys.exit(1)
        wanted = (
            [d.strip() for d in args.dp.split(",") if d.strip()] if args.dp else None
        )
        try:
            run = run_decision_points_calibration(
                config_path, args.out, dp_ids=wanted, artifact_path=args.artifact
            )
        except (RunError, NotImplementedError, ValueError) as exc:
            print(f"Error: {exc}", file=sys.stderr)
            sys.exit(1)
        kind = "official" if run.official else "dev"
        print(
            f"\n[OK] Decision points calibrated ({kind} run {run.run_id}): "
            f"{', '.join(run.dp_ids)}\n"
            f"  report:   {run.report_path}\n"
            f"  artifact: {run.artifact_path} ({run.artifact_id})\n"
        )
        return
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
