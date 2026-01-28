"""
Integration tests for C++ header generation and usage.

These tests:
1. Check for C++ toolchain availability
2. Generate headers at various precisions
3. Build the C++ test program
4. Run consistency checks against the Python oracle
5. Measure performance and binary sizes

Environment variables:
- ADM0_TEST_PRECISION: Comma-separated list of precisions to test (default: "0")
  Example: ADM0_TEST_PRECISION=0,1,2 pytest tests/test_integration.py -v
"""

import os
import pytest
import random
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from dataclasses import dataclass
from typing import List, Tuple

from adm0_reverse.duckdb_oracle import create_oracle_from_natural_earth
from adm0_reverse.builder import build_quadtree
from adm0_reverse.codegen import generate_cpp_header
from adm0_reverse.quantize import quantize


# Paths
PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR = PROJECT_ROOT / "data"
INTEGRATION_DIR = PROJECT_ROOT / "integration_test"
SHAPEFILE = "ne_10m_admin_0_countries_tlc.shp"


def get_test_precisions() -> List[int]:
    """Get precisions to test from environment variable or default to [0]."""
    env_val = os.environ.get("ADM0_TEST_PRECISION", "0")
    return [int(p.strip()) for p in env_val.split(",") if p.strip()]


@dataclass
class BuildResult:
    """Result of building and testing at a specific precision."""
    precision: int
    header_size: int
    binary_size: int
    build_time: float
    tree_nodes: int
    tree_leaves: int
    tree_depth: int
    oracle_calls: int


@dataclass
class ConsistencyResult:
    """Result of running consistency tests."""
    precision: int
    num_tests: int
    num_passed: int
    num_failed: int
    failed_points: List[Tuple[float, float, int, int]]  # (lat, lon, expected, actual)
    total_time: float
    avg_lookup_time_ns: float


def check_toolchain() -> Tuple[bool, str]:
    """Check if C++ toolchain is available."""
    # Try clang++ first, then g++
    for compiler in ["clang++", "g++"]:
        try:
            result = subprocess.run(
                [compiler, "--version"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                version = result.stdout.split("\n")[0]
                return True, f"{compiler}: {version}"
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue

    return False, "No C++ compiler found (tried clang++, g++)"


def check_zlib() -> bool:
    """Check if zlib development headers are available."""
    # Try to compile a simple program that uses zlib
    with tempfile.TemporaryDirectory() as tmpdir:
        test_file = Path(tmpdir) / "test_zlib.cpp"
        test_file.write_text("""
#include <zlib.h>
int main() { return 0; }
""")
        try:
            result = subprocess.run(
                ["clang++", "-o", "/dev/null", str(test_file), "-lz"],
                capture_output=True,
                timeout=30,
            )
            return result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False


@pytest.fixture(scope="module")
def toolchain_available():
    """Fixture to check toolchain availability."""
    available, info = check_toolchain()
    if not available:
        pytest.skip(f"C++ toolchain not available: {info}")
    return info


@pytest.fixture(scope="module")
def shapefile_available():
    """Fixture to check shapefile availability."""
    if not (DATA_DIR / SHAPEFILE).exists():
        pytest.skip("Natural Earth shapefile not found")
    return DATA_DIR / SHAPEFILE


def build_header(precision: int, output_path: Path, compress: bool = False) -> Tuple[int, float, dict]:
    """
    Build a header file at the specified precision.

    Returns:
        Tuple of (header_size, build_time, stats_dict)
    """
    start = time.time()

    # Adjust thresholds based on precision for faster testing
    # Higher precision = more points, so use smaller threshold to avoid long brute-force
    thresholds = {
        0: 16384,  # ~65K total points - can verify larger regions
        1: 2048,   # ~6.5M total points - need to split more
        2: 512,    # ~650M total points - split aggressively
    }
    brute_force_threshold = thresholds.get(precision, 512)

    oracle = create_oracle_from_natural_earth(DATA_DIR, precision, SHAPEFILE)
    try:
        tree, stats = build_quadtree(
            oracle=oracle,
            precision=precision,
            sample_k=16,
            brute_force_threshold=brute_force_threshold,
            seed=42,
        )

        header = generate_cpp_header(
            tree=tree,
            country_codes=oracle.get_country_codes(),
            precision=precision,
            oracle_source=f"Natural Earth ({SHAPEFILE})",
            namespace="adm0",
            include_iso_lookup=True,
            compress=compress,
        )

        output_path.write_text(header)
        build_time = time.time() - start

        stats_dict = {
            "nodes": stats.nodes_created,
            "leaves": stats.leaves_created,
            "depth": stats.max_depth_reached,
            "oracle_calls": stats.oracle_calls,
        }

        return len(header), build_time, stats_dict
    finally:
        oracle.close()


def compile_binary(
    header_path: Path, output_path: Path, precision: int, compress: bool = False
) -> Tuple[int, float]:
    """
    Compile the test binary.

    Args:
        header_path: Path to the generated header file
        output_path: Path where the binary should be placed
        precision: Precision level (embedded in target name)
        compress: Whether to link with zlib

    Returns:
        Tuple of (binary_size, compile_time)
    """
    start = time.time()

    makefile_dir = INTEGRATION_DIR
    target = f"country_lookup_p{precision}"
    with_zlib = "1" if compress else "0"

    # Clean first
    subprocess.run(
        ["make", "-C", str(makefile_dir), "clean"],
        capture_output=True,
    )

    # Build with precision-specific target name
    env = os.environ.copy()
    result = subprocess.run(
        [
            "make", "-C", str(makefile_dir),
            f"TARGET={target}",
            f"HEADER={header_path}",
            f"WITH_ZLIB={with_zlib}",
        ],
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
    )

    if result.returncode != 0:
        raise RuntimeError(f"Compilation failed:\n{result.stderr}\n{result.stdout}")

    compile_time = time.time() - start

    # Copy binary to output path
    built_binary = makefile_dir / target
    shutil.copy(built_binary, output_path)

    binary_size = output_path.stat().st_size

    return binary_size, compile_time


def run_consistency_test(
    binary_path: Path,
    precision: int,
    num_samples: int = 5000,
    seed: int = 12345,
) -> ConsistencyResult:
    """
    Run consistency test comparing C++ output with Python oracle.

    Args:
        binary_path: Path to compiled binary
        precision: Precision level
        num_samples: Number of random points to test
        seed: Random seed for reproducibility

    Returns:
        ConsistencyResult with statistics
    """
    oracle = create_oracle_from_natural_earth(DATA_DIR, precision, SHAPEFILE)

    try:
        # Generate random test points
        random.seed(seed)
        test_points = []
        for _ in range(num_samples):
            lat = random.uniform(-90, 90)
            lon = random.uniform(-180, 180)
            test_points.append((lat, lon))

        # Prepare batch input
        batch_input = "\n".join(f"{lat},{lon}" for lat, lon in test_points)

        # Run C++ binary in batch mode
        start = time.time()
        result = subprocess.run(
            [str(binary_path), "--batch"],
            input=batch_input,
            capture_output=True,
            text=True,
            timeout=300,
        )
        cpp_time = time.time() - start

        if result.returncode != 0:
            raise RuntimeError(f"Binary execution failed:\n{result.stderr}")

        cpp_results = [int(line.strip()) for line in result.stdout.strip().split("\n") if line.strip()]

        if len(cpp_results) != len(test_points):
            raise RuntimeError(
                f"Result count mismatch: got {len(cpp_results)}, expected {len(test_points)}"
            )

        # Compare with Python oracle
        failed_points = []
        num_passed = 0

        for i, (lat, lon) in enumerate(test_points):
            ilat, ilon = quantize(lat, lon, precision)
            expected = oracle.lookup(ilat, ilon)
            actual = cpp_results[i]

            if expected == actual:
                num_passed += 1
            else:
                failed_points.append((lat, lon, expected, actual))

        avg_lookup_ns = (cpp_time * 1_000_000_000) / num_samples

        return ConsistencyResult(
            precision=precision,
            num_tests=num_samples,
            num_passed=num_passed,
            num_failed=len(failed_points),
            failed_points=failed_points[:10],  # Keep only first 10 failures
            total_time=cpp_time,
            avg_lookup_time_ns=avg_lookup_ns,
        )
    finally:
        oracle.close()


class TestIntegration:
    """Integration tests for C++ header generation."""

    def test_toolchain_check(self, toolchain_available):
        """Test that toolchain check works."""
        assert toolchain_available is not None
        print(f"\nToolchain: {toolchain_available}")

    @pytest.mark.parametrize("precision", get_test_precisions())
    def test_build_and_verify(self, toolchain_available, shapefile_available, precision, tmp_path):
        """Test building and verifying headers at different precisions."""
        print(f"\n{'='*60}")
        print(f"Testing precision {precision}")
        print(f"{'='*60}")

        # Paths
        header_path = tmp_path / f"country_lookup_p{precision}.hpp"
        binary_path = tmp_path / f"country_lookup_p{precision}"

        # Build header (without compression for simpler testing)
        print(f"\nBuilding header...")
        header_size, build_time, stats = build_header(precision, header_path, compress=False)
        print(f"  Header size: {header_size:,} bytes")
        print(f"  Build time: {build_time:.2f} seconds")
        print(f"  Tree nodes: {stats['nodes']:,}")
        print(f"  Tree leaves: {stats['leaves']:,}")
        print(f"  Tree depth: {stats['depth']}")
        print(f"  Oracle calls: {stats['oracle_calls']:,}")

        # Compile binary
        print(f"\nCompiling binary...")
        binary_size, compile_time = compile_binary(header_path, binary_path, precision, compress=False)
        print(f"  Binary size: {binary_size:,} bytes ({binary_size/1024:.1f} KB)")
        print(f"  Compile time: {compile_time:.2f} seconds")

        # Run consistency test
        num_samples = 5000 if precision <= 1 else 2000  # Fewer samples for higher precision
        print(f"\nRunning consistency test ({num_samples} samples)...")
        test_result = run_consistency_test(binary_path, precision, num_samples)

        print(f"  Passed: {test_result.num_passed}/{test_result.num_tests}")
        print(f"  Failed: {test_result.num_failed}")
        print(f"  Total time: {test_result.total_time:.3f} seconds")
        print(f"  Avg lookup: {test_result.avg_lookup_time_ns:.0f} ns")

        if test_result.failed_points:
            print(f"  Sample failures:")
            for lat, lon, expected, actual in test_result.failed_points[:5]:
                print(f"    ({lat:.4f}, {lon:.4f}): expected {expected}, got {actual}")

        # Assertions
        assert test_result.num_failed == 0, f"Consistency test failed with {test_result.num_failed} mismatches"

    def test_benchmark(self, toolchain_available, shapefile_available, tmp_path):
        """Run benchmark at precision 0."""
        print(f"\n{'='*60}")
        print("Running benchmark (precision 0)")
        print(f"{'='*60}")

        header_path = tmp_path / "country_lookup_p0_benchmark.hpp"
        binary_path = tmp_path / "country_lookup_p0_benchmark"

        # Build
        header_size, _, _ = build_header(0, header_path, compress=False)
        binary_size, _ = compile_binary(header_path, binary_path, precision=0, compress=False)

        # Run benchmark
        result = subprocess.run(
            [str(binary_path), "--benchmark", "100000"],
            capture_output=True,
            text=True,
            timeout=60,
        )

        assert result.returncode == 0
        print(f"\n{result.stdout}")


class TestIntegrationSummary:
    """Summary test that runs all precisions and reports results."""

    def test_full_summary(self, toolchain_available, shapefile_available, tmp_path):
        """Run full integration test with summary.

        Tests all precisions specified by ADM0_TEST_PRECISION env var (default: 0).
        """
        precisions = get_test_precisions()

        print(f"\n{'='*70}")
        print(f"FULL INTEGRATION TEST SUMMARY (precisions: {precisions})")
        print(f"{'='*70}")

        results = []

        for precision in precisions:
            print(f"\n--- Precision {precision} ---")

            header_path = tmp_path / f"country_lookup_p{precision}.hpp"
            binary_path = tmp_path / f"country_lookup_p{precision}"

            # Build
            header_size, build_time, stats = build_header(precision, header_path, compress=False)
            binary_size, compile_time = compile_binary(header_path, binary_path, precision, compress=False)

            # Test
            num_samples = 3000
            test_result = run_consistency_test(binary_path, precision, num_samples)

            results.append({
                "precision": precision,
                "header_size": header_size,
                "binary_size": binary_size,
                "build_time": build_time,
                "compile_time": compile_time,
                "tree_nodes": stats["nodes"],
                "tree_leaves": stats["leaves"],
                "tree_depth": stats["depth"],
                "num_tests": test_result.num_tests,
                "num_passed": test_result.num_passed,
                "avg_lookup_ns": test_result.avg_lookup_time_ns,
            })

            assert test_result.num_failed == 0

        # Print summary table
        print(f"\n{'='*70}")
        print("SUMMARY TABLE")
        print(f"{'='*70}")
        print(f"{'Precision':<10} {'Header':<12} {'Binary':<12} {'Nodes':<10} {'Leaves':<10} {'Depth':<6} {'Lookup':<12}")
        print(f"{'':<10} {'(KB)':<12} {'(KB)':<12} {'':<10} {'':<10} {'':<6} {'(ns)':<12}")
        print("-" * 70)

        for r in results:
            print(
                f"{r['precision']:<10} "
                f"{r['header_size']/1024:<12.1f} "
                f"{r['binary_size']/1024:<12.1f} "
                f"{r['tree_nodes']:<10,} "
                f"{r['tree_leaves']:<10,} "
                f"{r['tree_depth']:<6} "
                f"{r['avg_lookup_ns']:<12.0f}"
            )

        print("-" * 70)
        print(f"\nAll {sum(r['num_tests'] for r in results)} consistency checks passed!")
