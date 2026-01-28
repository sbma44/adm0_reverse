"""Tests for quadtree data structures."""

import pytest
from adm0_reverse.quadtree import (
    Rectangle,
    LeafNode,
    InternalNode,
    QuadTree,
)


class TestRectangle:
    """Tests for Rectangle class."""

    def test_basic_creation(self):
        """Test basic rectangle creation."""
        r = Rectangle(0, 10, 0, 10)
        assert r.x0 == 0
        assert r.x1 == 10
        assert r.y0 == 0
        assert r.y1 == 10

    def test_invalid_rectangle(self):
        """Test that invalid rectangles raise errors."""
        with pytest.raises(ValueError):
            Rectangle(10, 0, 0, 10)  # x0 > x1

        with pytest.raises(ValueError):
            Rectangle(0, 10, 10, 0)  # y0 > y1

    def test_width_height(self):
        """Test width and height properties."""
        r = Rectangle(0, 9, 0, 19)
        assert r.width == 10
        assert r.height == 20

    def test_point_count(self):
        """Test point count calculation."""
        r = Rectangle(0, 9, 0, 9)
        assert r.point_count == 100

        r2 = Rectangle(5, 5, 5, 5)
        assert r2.point_count == 1

    def test_is_single_point(self):
        """Test single point detection."""
        r1 = Rectangle(5, 5, 5, 5)
        assert r1.is_single_point()

        r2 = Rectangle(0, 10, 0, 10)
        assert not r2.is_single_point()

    def test_contains(self):
        """Test point containment."""
        r = Rectangle(0, 10, 0, 10)
        assert r.contains(5, 5)
        assert r.contains(0, 0)
        assert r.contains(10, 10)
        assert not r.contains(11, 5)
        assert not r.contains(5, 11)
        assert not r.contains(-1, 5)

    def test_midpoints(self):
        """Test midpoint calculation."""
        r = Rectangle(0, 10, 0, 20)
        xm, ym = r.midpoints()
        assert xm == 5
        assert ym == 10

    def test_subdivide_basic(self):
        """Test basic subdivision."""
        r = Rectangle(0, 10, 0, 10)
        children = r.subdivide()

        assert len(children) == 4

        # NW: (0..5, 6..10)
        assert children[0] == Rectangle(0, 5, 6, 10)
        # NE: (6..10, 6..10)
        assert children[1] == Rectangle(6, 10, 6, 10)
        # SW: (0..5, 0..5)
        assert children[2] == Rectangle(0, 5, 0, 5)
        # SE: (6..10, 0..5)
        assert children[3] == Rectangle(6, 10, 0, 5)

    def test_subdivide_single_point_fails(self):
        """Test that subdividing a single point raises error."""
        r = Rectangle(5, 5, 5, 5)
        with pytest.raises(ValueError):
            r.subdivide()

    def test_child_index_for_point(self):
        """Test child index determination."""
        r = Rectangle(0, 10, 0, 10)

        # NW quadrant
        assert r.child_index_for_point(2, 8) == 0
        # NE quadrant
        assert r.child_index_for_point(8, 8) == 1
        # SW quadrant
        assert r.child_index_for_point(2, 2) == 2
        # SE quadrant
        assert r.child_index_for_point(8, 2) == 3

    def test_child_index_on_midpoint(self):
        """Test child index when point is on midpoint."""
        r = Rectangle(0, 10, 0, 10)
        xm, ym = r.midpoints()

        # On xm, should go to left (NW or SW)
        assert r.child_index_for_point(xm, ym + 1) == 0  # NW
        assert r.child_index_for_point(xm, ym) == 2  # SW

    def test_iter_points(self):
        """Test point iteration."""
        r = Rectangle(0, 2, 0, 2)
        points = list(r.iter_points())
        assert len(points) == 9
        assert (0, 0) in points
        assert (2, 2) in points
        assert (1, 1) in points

    def test_sample_points(self):
        """Test sample point generation."""
        r = Rectangle(0, 100, 0, 100)
        samples = r.sample_points(20, seed=42)

        assert len(samples) <= 20
        # All samples should be within rectangle
        for x, y in samples:
            assert r.contains(x, y)

        # Should include corners
        assert (0, 0) in samples
        assert (100, 100) in samples

    def test_sample_points_deterministic(self):
        """Test that sampling is deterministic."""
        r = Rectangle(0, 100, 0, 100)
        samples1 = r.sample_points(20, seed=42)
        samples2 = r.sample_points(20, seed=42)
        assert samples1 == samples2


class TestLeafNode:
    """Tests for LeafNode class."""

    def test_creation(self):
        """Test leaf node creation."""
        leaf = LeafNode(country_id=5)
        assert leaf.country_id == 5
        assert leaf.is_leaf()

    def test_lookup(self):
        """Test leaf lookup returns country ID."""
        leaf = LeafNode(country_id=42)
        r = Rectangle(0, 10, 0, 10)
        assert leaf.lookup(5, 5, r) == 42

    def test_counts(self):
        """Test node and leaf counts."""
        leaf = LeafNode(country_id=1)
        assert leaf.node_count() == 1
        assert leaf.leaf_count() == 1
        assert leaf.max_depth() == 0


class TestInternalNode:
    """Tests for InternalNode class."""

    def test_creation(self):
        """Test internal node creation."""
        children = [
            LeafNode(1),
            LeafNode(2),
            LeafNode(3),
            LeafNode(4),
        ]
        node = InternalNode(children)
        assert not node.is_leaf()

    def test_invalid_children_count(self):
        """Test that wrong number of children raises error."""
        with pytest.raises(ValueError):
            InternalNode([LeafNode(1), LeafNode(2)])

    def test_lookup(self):
        """Test internal node lookup routes to correct child."""
        children = [
            LeafNode(1),  # NW
            LeafNode(2),  # NE
            LeafNode(3),  # SW
            LeafNode(4),  # SE
        ]
        node = InternalNode(children)
        r = Rectangle(0, 10, 0, 10)

        # NW quadrant
        assert node.lookup(2, 8, r) == 1
        # NE quadrant
        assert node.lookup(8, 8, r) == 2
        # SW quadrant
        assert node.lookup(2, 2, r) == 3
        # SE quadrant
        assert node.lookup(8, 2, r) == 4

    def test_counts_with_all_children(self):
        """Test counts with all children present."""
        children = [
            LeafNode(1),
            LeafNode(2),
            LeafNode(3),
            LeafNode(4),
        ]
        node = InternalNode(children)
        assert node.node_count() == 5
        assert node.leaf_count() == 4
        assert node.max_depth() == 1

    def test_counts_with_none_children(self):
        """Test counts with some None children."""
        children = [
            LeafNode(1),
            None,
            LeafNode(3),
            None,
        ]
        node = InternalNode(children)
        assert node.node_count() == 3
        assert node.leaf_count() == 2


class TestQuadTree:
    """Tests for QuadTree class."""

    def test_simple_tree(self):
        """Test a simple uniform tree."""
        root = LeafNode(country_id=5)
        bounds = Rectangle(0, 100, 0, 100)
        tree = QuadTree(root, bounds, precision=2)

        assert tree.lookup(50, 50) == 5
        assert tree.node_count == 1
        assert tree.leaf_count == 1

    def test_two_level_tree(self):
        """Test a two-level tree."""
        # Children order: NW=0, NE=1, SW=2, SE=3
        # NW: high lat (y), low lon (x)
        # NE: high lat (y), high lon (x)
        # SW: low lat (y), low lon (x)
        # SE: low lat (y), high lon (x)
        children = [
            LeafNode(1),  # NW: ilat > 50, ilon <= 50
            LeafNode(2),  # NE: ilat > 50, ilon > 50
            LeafNode(3),  # SW: ilat <= 50, ilon <= 50
            LeafNode(4),  # SE: ilat <= 50, ilon > 50
        ]
        root = InternalNode(children)
        bounds = Rectangle(0, 100, 0, 100)
        tree = QuadTree(root, bounds, precision=2)

        # Check each quadrant (ilat, ilon)
        assert tree.lookup(75, 25) == 1  # NW: high lat, low lon
        assert tree.lookup(75, 75) == 2  # NE: high lat, high lon
        assert tree.lookup(25, 25) == 3  # SW: low lat, low lon
        assert tree.lookup(25, 75) == 4  # SE: low lat, high lon

    def test_lookup_coords(self):
        """Test coordinate-based lookup."""
        root = LeafNode(country_id=42)
        bounds = Rectangle(0, 36000, 0, 18000)  # Full grid at precision 2
        tree = QuadTree(root, bounds, precision=2)

        # Any coordinate should return 42
        assert tree.lookup_coords(0.0, 0.0) == 42
        assert tree.lookup_coords(45.0, -90.0) == 42

    def test_out_of_bounds(self):
        """Test that out of bounds lookup raises error."""
        root = LeafNode(country_id=1)
        bounds = Rectangle(0, 100, 0, 100)
        tree = QuadTree(root, bounds, precision=2)

        with pytest.raises(ValueError):
            tree.lookup(200, 50)
