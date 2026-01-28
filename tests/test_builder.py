"""Tests for quadtree builder."""

import pytest
from adm0_reverse.builder import (
    QuadTreeBuilder,
    BuilderConfig,
    build_quadtree,
)
from adm0_reverse.oracle import (
    MockSimpleOracle,
    MockCircleOracle,
    MockRectangleOracle,
    FunctionOracle,
    OCEAN_ID,
)
from adm0_reverse.quantize import quantize, get_grid_dimensions


class TestBuilderConfig:
    """Tests for BuilderConfig."""

    def test_default_config(self):
        """Test default configuration values."""
        config = BuilderConfig(precision=2)
        assert config.precision == 2
        assert config.sample_k == 16
        assert config.brute_force_threshold == 16384
        assert config.max_depth == 64
        assert config.seed == 42

    def test_custom_config(self):
        """Test custom configuration values."""
        config = BuilderConfig(
            precision=3,
            sample_k=32,
            brute_force_threshold=8192,
            max_depth=32,
            seed=12345,
        )
        assert config.precision == 3
        assert config.sample_k == 32
        assert config.brute_force_threshold == 8192
        assert config.max_depth == 32
        assert config.seed == 12345

    def test_invalid_precision(self):
        """Test that negative precision raises error."""
        with pytest.raises(ValueError):
            BuilderConfig(precision=-1)

    def test_invalid_sample_k(self):
        """Test that sample_k < 1 raises error."""
        with pytest.raises(ValueError):
            BuilderConfig(precision=2, sample_k=0)


class TestQuadTreeBuilder:
    """Tests for QuadTreeBuilder."""

    def test_uniform_oracle(self):
        """Test building with a completely uniform oracle."""
        # Oracle that always returns the same country
        oracle = FunctionOracle(
            lambda ilat, ilon: 1,
            country_codes={1: "XX"}
        )
        config = BuilderConfig(
            precision=0,  # Very coarse for fast testing
            brute_force_threshold=70000,  # Must cover full grid (361*181 = 65341 points)
        )
        builder = QuadTreeBuilder(oracle, config)
        tree = builder.build()

        # Should produce a single leaf since entire grid is uniform
        assert tree.leaf_count == 1
        assert tree.node_count == 1

        # Lookup should always return 1
        assert tree.lookup(0, 0) == 1
        assert tree.lookup(90, 180) == 1

    def test_two_region_oracle(self):
        """Test building with a simple two-region oracle."""
        # North/South division at equator
        def oracle_func(ilat, ilon):
            mid = 90  # For precision 0, ilat ranges 0-180
            return 1 if ilat > mid else 2

        oracle = FunctionOracle(oracle_func, {1: "NO", 2: "SO"})
        config = BuilderConfig(
            precision=0,
            brute_force_threshold=100,
        )
        builder = QuadTreeBuilder(oracle, config)
        tree = builder.build()

        # Should have refined to separate north and south
        assert tree.leaf_count > 1

        # Check north/south lookup
        # At precision 0, ilat=135 should be north (lat ~45)
        # ilat=45 should be south (lat ~-45)
        max_ilon, max_ilat = get_grid_dimensions(0)
        assert tree.lookup(max_ilat - 10, 180) == 1  # North
        assert tree.lookup(10, 180) == 2  # South

    def test_mock_simple_oracle(self):
        """Test building with MockSimpleOracle."""
        oracle = MockSimpleOracle(precision=0)
        tree, stats = build_quadtree(
            oracle,
            precision=0,
            brute_force_threshold=500,
        )

        # Should have multiple leaves (north, south, ocean)
        assert tree.leaf_count >= 2

        # Stats should be populated
        assert stats.nodes_created > 0
        assert stats.oracle_calls > 0

    def test_mock_rectangle_oracle(self):
        """Test building with MockRectangleOracle."""
        # Use precision 0 for fast testing
        oracle = MockRectangleOracle(precision=0)
        tree, stats = build_quadtree(
            oracle,
            precision=0,
            sample_k=8,
            brute_force_threshold=200,
        )

        # Should build successfully
        assert tree.node_count > 0
        assert tree.leaf_count > 0

    def test_determinism(self):
        """Test that builds are deterministic."""
        oracle = MockSimpleOracle(precision=0)

        tree1, stats1 = build_quadtree(oracle, precision=0, seed=42)
        tree2, stats2 = build_quadtree(oracle, precision=0, seed=42)

        # Same seed should produce identical trees
        assert tree1.node_count == tree2.node_count
        assert tree1.leaf_count == tree2.leaf_count
        assert stats1.oracle_calls == stats2.oracle_calls

    def test_different_seeds(self):
        """Test that different seeds can produce different trees."""
        oracle = MockCircleOracle(precision=0)

        # Different seeds may result in different sampling patterns
        # (though the final correctness should be the same)
        tree1, _ = build_quadtree(oracle, precision=0, seed=42)
        tree2, _ = build_quadtree(oracle, precision=0, seed=12345)

        # Both should be valid trees
        assert tree1.node_count > 0
        assert tree2.node_count > 0


class TestBuilderCorrectness:
    """Tests for builder correctness."""

    def test_correctness_simple_oracle(self):
        """Verify builder output matches oracle for all points."""
        oracle = MockSimpleOracle(precision=0)
        tree, _ = build_quadtree(
            oracle,
            precision=0,
            brute_force_threshold=500,
        )

        max_ilon, max_ilat = get_grid_dimensions(0)

        # Check a grid of points
        errors = 0
        for ilat in range(0, max_ilat + 1, 10):
            for ilon in range(0, max_ilon + 1, 20):
                expected = oracle.lookup(ilat, ilon)
                actual = tree.lookup(ilat, ilon)
                if expected != actual:
                    errors += 1

        assert errors == 0, f"Found {errors} mismatches"

    def test_correctness_rectangle_oracle(self):
        """Verify builder output matches oracle for rectangle regions."""
        oracle = MockRectangleOracle(precision=0)
        tree, _ = build_quadtree(
            oracle,
            precision=0,
            sample_k=8,
            brute_force_threshold=200,
        )

        max_ilon, max_ilat = get_grid_dimensions(0)

        # Check a grid of points
        errors = 0
        for ilat in range(0, max_ilat + 1, 5):
            for ilon in range(0, max_ilon + 1, 10):
                expected = oracle.lookup(ilat, ilon)
                actual = tree.lookup(ilat, ilon)
                if expected != actual:
                    errors += 1

        assert errors == 0, f"Found {errors} mismatches"


class TestBuilderStats:
    """Tests for builder statistics."""

    def test_stats_populated(self):
        """Test that statistics are properly collected."""
        oracle = MockSimpleOracle(precision=0)
        _, stats = build_quadtree(oracle, precision=0)

        assert stats.nodes_created > 0
        assert stats.leaves_created > 0
        assert stats.oracle_calls > 0

    def test_stats_relationship(self):
        """Test relationships between statistics."""
        oracle = MockSimpleOracle(precision=0)
        _, stats = build_quadtree(oracle, precision=0)

        # Total nodes = leaves + internal
        assert stats.nodes_created == stats.leaves_created + stats.internal_nodes_created
