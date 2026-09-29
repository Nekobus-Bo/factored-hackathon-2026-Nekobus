from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from typing import Any

import numpy as np
import psutil
from pydantic import BaseModel


class BenchmarkResult(BaseModel):
    """Latency and resource consumption metrics."""

    p95_latency_ms: float
    peak_ram_mb: float
    avg_latency_ms: float = 0.0
    p50_latency_ms: float = 0.0


def benchmark_cpu_inference(
    infer_fn: Callable[[Any], Any],
    items: Sequence[Any],
    warmup: int = 1,
    baseline_ram_mb: float | None = None,
) -> BenchmarkResult:
    """Benchmark single-item CPU latency (p95 ms) and peak RAM (MB)."""
    if not items:
        return BenchmarkResult(p95_latency_ms=0.0, peak_ram_mb=0.0)

    process = psutil.Process()
    current_ram = process.memory_info().rss / (1024 * 1024)
    initial_ram = baseline_ram_mb if baseline_ram_mb is not None else current_ram
    peak_ram = current_ram

    # Warmup
    for item in items[: min(warmup, len(items))]:
        _ = infer_fn(item)

    latencies_ms: list[float] = []

    for item in items:
        start_time = time.perf_counter()
        _ = infer_fn(item)
        duration_ms = (time.perf_counter() - start_time) * 1000.0
        latencies_ms.append(duration_ms)

        current_ram = process.memory_info().rss / (1024 * 1024)
        if current_ram > peak_ram:
            peak_ram = current_ram

    p95 = float(np.percentile(latencies_ms, 95)) if latencies_ms else 0.0
    p50 = float(np.percentile(latencies_ms, 50)) if latencies_ms else 0.0
    avg = float(np.mean(latencies_ms)) if latencies_ms else 0.0

    ram_delta = max(0.0, peak_ram - initial_ram)

    return BenchmarkResult(
        p95_latency_ms=round(p95, 2),
        peak_ram_mb=round(ram_delta, 1),
        avg_latency_ms=round(avg, 2),
        p50_latency_ms=round(p50, 2),
    )
