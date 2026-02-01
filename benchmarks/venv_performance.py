"""
Performance benchmarks for DevEnv MCP venv discovery and process listing.

This script measures the performance improvement from parallel execution
in venv discovery and compares process listing with different filters.

Run with: uv run python benchmarks/venv_performance.py
"""

import asyncio
import shutil
import statistics
import sys
import tempfile
import time
from pathlib import Path

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import psutil

from devenv_mcp.tools.process import DEV_PROCESS_NAMES, _get_process_info, _is_dev_process
from devenv_mcp.tools.venv import _get_venv_info, _is_valid_venv
from devenv_mcp.utils import PlatformHelper, run_command


# =============================================================================
# Benchmark Utilities
# =============================================================================


def format_time(seconds: float) -> str:
    """Format time in human-readable format."""
    if seconds < 0.001:
        return f"{seconds * 1_000_000:.1f}µs"
    elif seconds < 1:
        return f"{seconds * 1000:.1f}ms"
    else:
        return f"{seconds:.2f}s"


def print_header(title: str) -> None:
    """Print a section header."""
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print(f"{'=' * 60}\n")


def print_stats(times: list[float], label: str) -> None:
    """Print statistics for a list of timing measurements."""
    mean = statistics.mean(times)
    stdev = statistics.stdev(times) if len(times) > 1 else 0
    print(f"  {label}:")
    print(f"    Mean:   {format_time(mean)}")
    print(f"    Stdev:  {format_time(stdev)}")
    print(f"    Min:    {format_time(min(times))}")
    print(f"    Max:    {format_time(max(times))}")


# =============================================================================
# Venv Creation Helper
# =============================================================================


async def create_test_venvs(base_dir: Path, count: int) -> list[Path]:
    """
    Create test virtual environments for benchmarking.

    Args:
        base_dir: Directory to create venvs in
        count: Number of venvs to create

    Returns:
        List of paths to created venvs
    """
    print(f"  Creating {count} test venv(s)...")
    venv_paths = []

    # Create venvs in parallel for speed
    async def create_venv(name: str) -> Path:
        venv_path = base_dir / name
        result = await run_command(
            [sys.executable, "-m", "venv", str(venv_path)],
            timeout=120.0,
        )
        if result.success:
            return venv_path
        raise RuntimeError(f"Failed to create venv {name}: {result.stderr}")

    tasks = [create_venv(f"venv_{i:02d}") for i in range(count)]
    venv_paths = await asyncio.gather(*tasks)

    print(f"  Created {len(venv_paths)} venv(s)")
    return list(venv_paths)


# =============================================================================
# Benchmark: Venv Discovery Latency (Sequential vs Parallel)
# =============================================================================


async def gather_venv_info_sequential(venv_paths: list[Path]) -> list:
    """Gather venv info sequentially (one at a time)."""
    results = []
    for path in venv_paths:
        info = await _get_venv_info(path)
        results.append(info)
    return results


async def gather_venv_info_parallel(venv_paths: list[Path]) -> list:
    """Gather venv info in parallel using asyncio.gather."""
    return await asyncio.gather(*[_get_venv_info(path) for path in venv_paths])


async def benchmark_venv_discovery_latency(venv_paths: list[Path], iterations: int = 5) -> dict:
    """
    Benchmark sequential vs parallel venv info gathering.

    Args:
        venv_paths: List of venv paths to analyze
        iterations: Number of iterations to run

    Returns:
        Dictionary with benchmark results
    """
    print_header(f"Test 1: Venv Discovery Latency ({len(venv_paths)} venvs, {iterations} iterations)")

    sequential_times = []
    parallel_times = []

    for i in range(iterations):
        print(f"  Iteration {i + 1}/{iterations}...")

        # Sequential benchmark
        start = time.perf_counter()
        await gather_venv_info_sequential(venv_paths)
        elapsed = time.perf_counter() - start
        sequential_times.append(elapsed)

        # Parallel benchmark
        start = time.perf_counter()
        await gather_venv_info_parallel(venv_paths)
        elapsed = time.perf_counter() - start
        parallel_times.append(elapsed)

    print()
    print_stats(sequential_times, "Sequential")
    print_stats(parallel_times, "Parallel")

    speedup = statistics.mean(sequential_times) / statistics.mean(parallel_times)
    print(f"\n  Speedup: {speedup:.2f}x faster with parallel execution")

    return {
        "sequential_times": sequential_times,
        "parallel_times": parallel_times,
        "speedup": speedup,
    }


# =============================================================================
# Benchmark: Scaling Behavior
# =============================================================================


async def benchmark_scaling_behavior(base_dir: Path, venv_counts: list[int]) -> dict:
    """
    Measure how latency scales with venv count.

    Args:
        base_dir: Directory to create venvs in
        venv_counts: List of venv counts to test

    Returns:
        Dictionary with scaling results
    """
    print_header("Test 2: Scaling Behavior")

    results = {"venv_counts": venv_counts, "sequential": [], "parallel": [], "speedups": []}

    for count in venv_counts:
        print(f"\n  Testing with {count} venv(s)...")

        # Create venvs
        test_dir = base_dir / f"scaling_{count}"
        test_dir.mkdir(parents=True, exist_ok=True)
        venv_paths = await create_test_venvs(test_dir, count)

        # Run benchmarks (3 iterations each)
        sequential_times = []
        parallel_times = []

        for _ in range(3):
            # Sequential
            start = time.perf_counter()
            await gather_venv_info_sequential(venv_paths)
            sequential_times.append(time.perf_counter() - start)

            # Parallel
            start = time.perf_counter()
            await gather_venv_info_parallel(venv_paths)
            parallel_times.append(time.perf_counter() - start)

        seq_mean = statistics.mean(sequential_times)
        par_mean = statistics.mean(parallel_times)
        speedup = seq_mean / par_mean if par_mean > 0 else 0

        results["sequential"].append(seq_mean)
        results["parallel"].append(par_mean)
        results["speedups"].append(speedup)

        print(f"    Sequential: {format_time(seq_mean)}")
        print(f"    Parallel:   {format_time(par_mean)}")
        print(f"    Speedup:    {speedup:.2f}x")

    # Print summary table
    print("\n  Summary Table:")
    print("  " + "-" * 50)
    print(f"  {'Venvs':>6} | {'Sequential':>12} | {'Parallel':>12} | {'Speedup':>8}")
    print("  " + "-" * 50)
    for i, count in enumerate(venv_counts):
        print(
            f"  {count:>6} | {format_time(results['sequential'][i]):>12} | "
            f"{format_time(results['parallel'][i]):>12} | {results['speedups'][i]:>7.2f}x"
        )
    print("  " + "-" * 50)

    return results


# =============================================================================
# Benchmark: Process Listing Latency
# =============================================================================


def list_processes_dev_only() -> list:
    """List only development-related processes."""
    processes = []
    for proc in psutil.process_iter():
        try:
            if _is_dev_process(proc.name()):
                info = _get_process_info(proc)
                if info:
                    processes.append(info)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return processes


def list_processes_all() -> list:
    """List all processes."""
    processes = []
    for proc in psutil.process_iter():
        try:
            info = _get_process_info(proc)
            if info:
                processes.append(info)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return processes


def benchmark_process_listing(iterations: int = 10) -> dict:
    """
    Benchmark process listing with different filters.

    Args:
        iterations: Number of iterations to run

    Returns:
        Dictionary with benchmark results
    """
    print_header(f"Test 3: Process Listing Latency ({iterations} iterations)")

    dev_only_times = []
    all_times = []
    dev_counts = []
    all_counts = []

    for i in range(iterations):
        print(f"  Iteration {i + 1}/{iterations}...")

        # Dev-only benchmark
        start = time.perf_counter()
        dev_procs = list_processes_dev_only()
        dev_only_times.append(time.perf_counter() - start)
        dev_counts.append(len(dev_procs))

        # All processes benchmark
        start = time.perf_counter()
        all_procs = list_processes_all()
        all_times.append(time.perf_counter() - start)
        all_counts.append(len(all_procs))

    print()
    print_stats(dev_only_times, "Dev-only (filter_dev_only=True)")
    print(f"    Avg processes found: {statistics.mean(dev_counts):.0f}")

    print()
    print_stats(all_times, "All processes (filter_dev_only=False)")
    print(f"    Avg processes found: {statistics.mean(all_counts):.0f}")

    overhead = statistics.mean(all_times) / statistics.mean(dev_only_times) if statistics.mean(dev_only_times) > 0 else 0
    print(f"\n  All processes takes {overhead:.2f}x longer than dev-only filter")

    return {
        "dev_only_times": dev_only_times,
        "all_times": all_times,
        "dev_counts": dev_counts,
        "all_counts": all_counts,
    }


# =============================================================================
# Main
# =============================================================================


async def main():
    """Run all benchmarks."""
    print("\n" + "=" * 60)
    print("  DevEnv MCP Performance Benchmarks")
    print("=" * 60)
    print(f"\n  Platform: {PlatformHelper.get_platform()}")
    print(f"  Python: {sys.version.split()[0]}")
    print(f"  CPU cores: {psutil.cpu_count()}")

    # Create temp directory for test venvs
    temp_dir = Path(tempfile.mkdtemp(prefix="devenv_bench_"))
    print(f"  Temp dir: {temp_dir}")

    try:
        # Test 1: Venv Discovery Latency
        print("\n  Setting up test venvs for Test 1...")
        test1_venvs = await create_test_venvs(temp_dir / "test1", count=10)
        test1_results = await benchmark_venv_discovery_latency(test1_venvs, iterations=5)

        # Test 2: Scaling Behavior
        test2_results = await benchmark_scaling_behavior(
            temp_dir / "test2",
            venv_counts=[1, 5, 10, 20],
        )

        # Test 3: Process Listing Latency
        test3_results = benchmark_process_listing(iterations=10)

        # Final Summary
        print_header("Summary")
        print(f"  Venv Discovery (10 venvs):")
        print(f"    Parallel execution is {test1_results['speedup']:.2f}x faster than sequential")
        print()
        print(f"  Scaling:")
        print(f"    Best speedup: {max(test2_results['speedups']):.2f}x at {test2_results['venv_counts'][test2_results['speedups'].index(max(test2_results['speedups']))]} venvs")
        print()
        print(f"  Process Listing:")
        avg_dev = statistics.mean(test3_results['dev_only_times'])
        avg_all = statistics.mean(test3_results['all_times'])
        print(f"    Dev-only filter: {format_time(avg_dev)} ({int(statistics.mean(test3_results['dev_counts']))} processes)")
        print(f"    All processes:   {format_time(avg_all)} ({int(statistics.mean(test3_results['all_counts']))} processes)")

    finally:
        # Cleanup
        print(f"\n  Cleaning up temp directory...")
        shutil.rmtree(temp_dir, ignore_errors=True)
        print("  Done!")


if __name__ == "__main__":
    asyncio.run(main())
