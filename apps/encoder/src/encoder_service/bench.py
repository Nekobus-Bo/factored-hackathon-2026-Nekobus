"""Measure the configured backend on CPU: build time, p50/p95 latency, peak RAM.

    ENCODER_BACKEND=tfidf_lr python -m encoder_service.bench \
        --data data/eval/synthetic/decision.validation.jsonl

Latency is per message, single-threaded, backend.analyze only (no HTTP). RAM is
the process peak RSS, and the delta over the RSS before the backend was built.
Prints to stdout; it never writes into reports/.
"""

from __future__ import annotations

import argparse
import json
import resource
import statistics
import sys
import time
from pathlib import Path

from encoder_service.config import get_backend_settings
from encoder_service.model_backends import build_backend


def peak_rss_mb() -> float:
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    # ru_maxrss is bytes on macOS and KiB on Linux.
    return peak / (1024 * 1024) if sys.platform == "darwin" else peak / 1024


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data", type=Path, required=True, help="Decision JSONL")
    parser.add_argument("--warmup", type=int, default=5)
    args = parser.parse_args()

    rows = [json.loads(line) for line in args.data.read_text("utf-8").splitlines()]
    texts = [r["text"] for r in rows if r.get("text")]
    if not texts:
        sys.exit(f"bench: no texts in {args.data}")

    settings = get_backend_settings()
    rss_before = peak_rss_mb()
    started = time.perf_counter()
    backend = build_backend(settings)
    build_s = time.perf_counter() - started
    if backend is None:
        sys.exit("bench: set ENCODER_BACKEND (tfidf_lr or gliner)")

    for text in texts[: args.warmup]:
        backend.analyze(text)
    latencies_ms = []
    for text in texts:
        t0 = time.perf_counter()
        backend.analyze(text)
        latencies_ms.append((time.perf_counter() - t0) * 1000.0)

    p95 = statistics.quantiles(latencies_ms, n=100, method="inclusive")[94]
    peak = peak_rss_mb()
    print(f"backend        {backend.model_id}")
    print(f"data           {args.data} ({len(texts)} messages)")
    print(f"build          {build_s:.2f} s")
    print(f"latency p50    {statistics.median(latencies_ms):.2f} ms")
    print(f"latency p95    {p95:.2f} ms")
    print(f"peak RSS       {peak:.0f} MB (+{peak - rss_before:.0f} MB for the backend)")


if __name__ == "__main__":
    main()
