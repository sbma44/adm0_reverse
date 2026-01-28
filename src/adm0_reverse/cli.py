"""
Command-line interface for adm0-reverse.

Provides commands for building country lookup headers.
"""

import argparse
import sys
from pathlib import Path
from typing import Optional

from .builder import build_quadtree, BuilderConfig
from .oracle import Oracle, MockRectangleOracle, MockCircleOracle, MockSimpleOracle
from .duckdb_oracle import DuckDBOracle, create_oracle_from_natural_earth
from .codegen import generate_cpp_header


# Default data directory (relative to package)
DEFAULT_DATA_DIR = Path(__file__).parent.parent.parent / "data"


def create_parser() -> argparse.ArgumentParser:
    """Create the argument parser."""
    parser = argparse.ArgumentParser(
        prog="adm0-reverse",
        description="Generate header-only C++ country lookup files",
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Build command
    build_parser = subparsers.add_parser(
        "build",
        help="Build a country lookup header",
    )
    build_parser.add_argument(
        "-p", "--precision",
        type=int,
        default=2,
        help="Decimal precision (default: 2)",
    )
    build_parser.add_argument(
        "-o", "--output",
        type=Path,
        help="Output file path (default: country_lookup_p{precision}.hpp)",
    )
    build_parser.add_argument(
        "--sample-k",
        type=int,
        default=16,
        help="Number of sample points per rectangle (default: 16)",
    )
    build_parser.add_argument(
        "--brute-force-threshold",
        type=int,
        default=16384,
        help="Max points to brute force verify (default: 16384)",
    )
    build_parser.add_argument(
        "--max-depth",
        type=int,
        default=64,
        help="Maximum tree depth (default: 64)",
    )
    build_parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for sampling (default: 42)",
    )
    build_parser.add_argument(
        "--no-compress",
        action="store_true",
        help="Disable zlib compression of tree blob",
    )
    build_parser.add_argument(
        "--namespace",
        type=str,
        default="adm0",
        help="C++ namespace (default: adm0)",
    )
    build_parser.add_argument(
        "--mock-oracle",
        type=str,
        choices=["rectangle", "circle", "simple"],
        default=None,
        help="Use a mock oracle instead of real data (for testing)",
    )
    build_parser.add_argument(
        "--data-dir",
        type=Path,
        default=None,
        help="Directory containing Natural Earth shapefile (default: data/)",
    )
    build_parser.add_argument(
        "--shapefile",
        type=str,
        default="ne_10m_admin_0_countries_tlc.shp",
        help="Shapefile name (default: ne_10m_admin_0_countries_tlc.shp)",
    )

    # Stats command
    stats_parser = subparsers.add_parser(
        "stats",
        help="Show statistics for a given precision",
    )
    stats_parser.add_argument(
        "-p", "--precision",
        type=int,
        default=2,
        help="Decimal precision (default: 2)",
    )

    # Test command
    test_parser = subparsers.add_parser(
        "test",
        help="Generate a test header with mock data",
    )
    test_parser.add_argument(
        "-p", "--precision",
        type=int,
        default=1,
        help="Decimal precision (default: 1 for fast testing)",
    )
    test_parser.add_argument(
        "-o", "--output",
        type=Path,
        help="Output file path",
    )

    return parser


def cmd_build(args: argparse.Namespace) -> int:
    """Handle the build command."""
    print(f"Building country lookup header with precision {args.precision}...")

    oracle: Oracle
    oracle_source: str

    # Select oracle
    if args.mock_oracle:
        # Use mock oracle
        if args.mock_oracle == "rectangle":
            oracle = MockRectangleOracle(args.precision)
        elif args.mock_oracle == "circle":
            oracle = MockCircleOracle(args.precision)
        else:
            oracle = MockSimpleOracle(args.precision)
        oracle_source = f"Mock{args.mock_oracle.title()}Oracle"
        print(f"Using mock oracle: {args.mock_oracle}")
    else:
        # Use real DuckDB oracle with Natural Earth data
        data_dir = args.data_dir or DEFAULT_DATA_DIR
        shapefile = args.shapefile

        print(f"Loading shapefile from: {data_dir / shapefile}")
        try:
            oracle = create_oracle_from_natural_earth(
                data_dir, args.precision, shapefile
            )
            oracle_source = f"Natural Earth ({shapefile})"
            print(f"Loaded {oracle.get_country_count()} countries")
        except FileNotFoundError as e:
            print(f"Error: {e}")
            print("Use --mock-oracle for testing without real data")
            return 1

    # Build the tree
    print("Building quadtree...")
    tree, stats = build_quadtree(
        oracle=oracle,
        precision=args.precision,
        sample_k=args.sample_k,
        brute_force_threshold=args.brute_force_threshold,
        max_depth=args.max_depth,
        seed=args.seed,
    )

    # Print stats
    print(f"\nBuild statistics:")
    print(f"  Nodes created: {stats.nodes_created}")
    print(f"  Leaf nodes: {stats.leaves_created}")
    print(f"  Internal nodes: {stats.internal_nodes_created}")
    print(f"  Oracle calls: {stats.oracle_calls}")
    print(f"  Brute force verifications: {stats.brute_force_verifications}")
    print(f"  Max depth reached: {stats.max_depth_reached}")
    print(f"  Sampling detected mixed: {stats.sampling_detected_mixed}")
    print(f"  Brute force detected mixed: {stats.brute_force_detected_mixed}")

    # Generate header
    print("\nGenerating C++ header...")
    header = generate_cpp_header(
        tree=tree,
        country_codes=oracle.get_country_codes(),
        precision=args.precision,
        oracle_source=oracle_source,
        namespace=args.namespace,
        include_iso_lookup=True,
        compress=not args.no_compress,
    )

    # Clean up oracle if it's a DuckDB oracle
    if isinstance(oracle, DuckDBOracle):
        oracle.close()

    # Write output
    output_path = args.output or Path(f"country_lookup_p{args.precision}.hpp")
    output_path.write_text(header)
    print(f"Wrote {len(header)} bytes to {output_path}")

    return 0


def cmd_stats(args: argparse.Namespace) -> int:
    """Handle the stats command."""
    p = args.precision
    q = 10 ** p

    print(f"Grid statistics for precision {p}:")
    print(f"  Q = 10^{p} = {q}")
    print(f"  Max longitude index: {360 * q}")
    print(f"  Max latitude index: {180 * q}")
    print(f"  Total grid points: {360 * q * 180 * q:,}")
    print(f"  Grid cell size: {1.0 / q} degrees")

    return 0


def cmd_test(args: argparse.Namespace) -> int:
    """Handle the test command."""
    from .codegen import generate_test_header

    print(f"Generating test header with precision {args.precision}...")

    header = generate_test_header(precision=args.precision)

    if args.output:
        args.output.write_text(header)
        print(f"Wrote test header to {args.output}")
    else:
        print(header)

    return 0


def main(argv: Optional[list[str]] = None) -> int:
    """Main entry point."""
    parser = create_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return 1

    if args.command == "build":
        return cmd_build(args)
    elif args.command == "stats":
        return cmd_stats(args)
    elif args.command == "test":
        return cmd_test(args)
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())
