"""
Quadtree builder using prove-or-split strategy.

This module implements the offline builder that constructs a sparse
quadtree from an oracle function. The builder uses sampling to detect
mixed regions quickly and brute-force verification for uniform regions.
"""

from dataclasses import dataclass, field
from typing import Optional, Set, Callable
import hashlib

from .quadtree import QuadTreeNode, LeafNode, InternalNode, Rectangle, QuadTree
from .oracle import Oracle
from .quantize import get_grid_dimensions


@dataclass
class BuilderConfig:
    """Configuration for the quadtree builder."""

    precision: int
    """Number of decimal places for quantization."""

    sample_k: int = 16
    """Number of sample points to check per rectangle."""

    brute_force_threshold: int = 16384
    """Maximum points in a rectangle to brute force verify."""

    max_depth: int = 64
    """Maximum tree depth (safety limit)."""

    seed: int = 42
    """Random seed for deterministic sampling."""

    batch_size: int = 10000
    """Batch size for oracle queries (larger = fewer round trips)."""

    def __post_init__(self):
        if self.precision < 0:
            raise ValueError("precision must be non-negative")
        if self.sample_k < 1:
            raise ValueError("sample_k must be at least 1")
        if self.brute_force_threshold < 1:
            raise ValueError("brute_force_threshold must be at least 1")
        if self.max_depth < 1:
            raise ValueError("max_depth must be at least 1")
        if self.batch_size < 1:
            raise ValueError("batch_size must be at least 1")


@dataclass
class BuilderStats:
    """Statistics collected during tree building."""

    nodes_created: int = 0
    leaves_created: int = 0
    internal_nodes_created: int = 0
    oracle_calls: int = 0
    brute_force_verifications: int = 0
    max_depth_reached: int = 0
    sampling_detected_mixed: int = 0
    brute_force_detected_mixed: int = 0


class QuadTreeBuilder:
    """
    Builder for sparse quadtrees using prove-or-split strategy.

    The builder constructs a quadtree by:
    1. Sampling points in a rectangle to quickly detect mixed regions
    2. Brute-forcing all points if the sample is uniform and region is small enough
    3. Splitting into quadrants if the region is too large or mixed
    """

    def __init__(self, oracle: Oracle, config: BuilderConfig):
        """
        Initialize the builder.

        Args:
            oracle: Oracle function for ground truth lookup
            config: Builder configuration
        """
        self.oracle = oracle
        self.config = config
        self.stats = BuilderStats()

        # Calculate bounds for the full grid
        max_ilon, max_ilat = get_grid_dimensions(config.precision)
        self.full_bounds = Rectangle(0, max_ilon, 0, max_ilat)

    def build(self) -> QuadTree:
        """
        Build the complete quadtree.

        Returns:
            QuadTree covering the entire grid
        """
        self.stats = BuilderStats()  # Reset stats
        root = self._build_node(self.full_bounds, depth=0)
        return QuadTree(root, self.full_bounds, self.config.precision)

    def _get_sample_seed(self, rect: Rectangle) -> int:
        """Generate deterministic seed for a rectangle."""
        # Hash the rectangle coordinates with the global seed
        data = f"{self.config.seed}:{rect.x0}:{rect.x1}:{rect.y0}:{rect.y1}"
        h = hashlib.md5(data.encode()).hexdigest()
        return int(h[:8], 16)

    def _sample_rectangle(self, rect: Rectangle) -> Set[int]:
        """
        Sample points in a rectangle and return unique country IDs.

        Args:
            rect: Rectangle to sample

        Returns:
            Set of country IDs found in the sample
        """
        seed = self._get_sample_seed(rect)
        points = rect.sample_points(self.config.sample_k, seed)

        # Convert to (ilat, ilon) format for oracle
        oracle_points = [(y, x) for x, y in points]
        self.stats.oracle_calls += len(oracle_points)

        # Use batch lookup
        country_ids = self.oracle.lookup_batch(oracle_points)
        return set(country_ids)

    def _brute_force_verify(self, rect: Rectangle, expected: int) -> bool:
        """
        Verify all points in rectangle have the expected country ID.

        Uses batch queries for efficiency.

        Args:
            rect: Rectangle to verify
            expected: Expected country ID

        Returns:
            True if all points match expected, False otherwise
        """
        self.stats.brute_force_verifications += 1

        # Collect points in batches and query
        batch = []
        for x, y in rect.iter_points():
            batch.append((y, x))  # Oracle takes (ilat, ilon)

            if len(batch) >= self.config.batch_size:
                self.stats.oracle_calls += len(batch)
                results = self.oracle.lookup_batch(batch)
                if any(r != expected for r in results):
                    return False
                batch = []

        # Process remaining points
        if batch:
            self.stats.oracle_calls += len(batch)
            results = self.oracle.lookup_batch(batch)
            if any(r != expected for r in results):
                return False

        return True

    def _build_node(self, rect: Rectangle, depth: int) -> QuadTreeNode:
        """
        Build a node for the given rectangle.

        Args:
            rect: Rectangle this node represents
            depth: Current depth in the tree

        Returns:
            QuadTreeNode (either Leaf or Internal)
        """
        self.stats.max_depth_reached = max(self.stats.max_depth_reached, depth)

        # Base case: single point is always a leaf
        if rect.is_single_point():
            country_id = self.oracle.lookup(rect.y0, rect.x0)
            self.stats.oracle_calls += 1
            self.stats.nodes_created += 1
            self.stats.leaves_created += 1
            return LeafNode(country_id)

        # Safety: max depth exceeded
        if depth >= self.config.max_depth:
            # Fallback: use the center point's country
            xm, ym = rect.midpoints()
            country_id = self.oracle.lookup(ym, xm)
            self.stats.oracle_calls += 1
            self.stats.nodes_created += 1
            self.stats.leaves_created += 1
            return LeafNode(country_id)

        # Step A: Sample to detect mixed regions quickly
        sample_ids = self._sample_rectangle(rect)

        if len(sample_ids) > 1:
            # Mixed region detected by sampling
            self.stats.sampling_detected_mixed += 1
            return self._split_node(rect, depth)

        # All samples agree on one country
        candidate = next(iter(sample_ids))

        # Step B: Verify uniformity
        if rect.point_count <= self.config.brute_force_threshold:
            # Small enough to brute force
            if self._brute_force_verify(rect, candidate):
                # Uniform region - create leaf
                self.stats.nodes_created += 1
                self.stats.leaves_created += 1
                return LeafNode(candidate)
            else:
                # Brute force found mixed region
                self.stats.brute_force_detected_mixed += 1
                return self._split_node(rect, depth)
        else:
            # Too large to brute force, conservatively split
            return self._split_node(rect, depth)

    def _split_node(self, rect: Rectangle, depth: int) -> InternalNode:
        """
        Split a rectangle into quadrants and build child nodes.

        Args:
            rect: Rectangle to split
            depth: Current depth

        Returns:
            InternalNode with children
        """
        child_rects = rect.subdivide()
        children = []

        for child_rect in child_rects:
            if child_rect is not None:
                child_node = self._build_node(child_rect, depth + 1)
                children.append(child_node)
            else:
                children.append(None)

        self.stats.nodes_created += 1
        self.stats.internal_nodes_created += 1
        return InternalNode(children)


def build_quadtree(
    oracle: Oracle,
    precision: int,
    sample_k: int = 16,
    brute_force_threshold: int = 16384,
    max_depth: int = 64,
    seed: int = 42,
    batch_size: int = 10000,
) -> tuple[QuadTree, BuilderStats]:
    """
    Convenience function to build a quadtree.

    Args:
        oracle: Oracle for country lookup
        precision: Quantization precision
        sample_k: Number of sample points per rectangle
        brute_force_threshold: Max points to brute force
        max_depth: Maximum tree depth
        seed: Random seed
        batch_size: Batch size for oracle queries

    Returns:
        Tuple of (QuadTree, BuilderStats)
    """
    config = BuilderConfig(
        precision=precision,
        sample_k=sample_k,
        brute_force_threshold=brute_force_threshold,
        max_depth=max_depth,
        seed=seed,
        batch_size=batch_size,
    )
    builder = QuadTreeBuilder(oracle, config)
    tree = builder.build()
    return tree, builder.stats
