"""
Quadtree data structures for country lookup.

This module defines the quadtree nodes and rectangle representation
used for spatial indexing of country boundaries on the quantized grid.
"""

from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Tuple, List, Optional, Iterator


@dataclass(frozen=True)
class Rectangle:
    """
    An axis-aligned rectangle in integer grid coordinates.

    Represents inclusive ranges [x0, x1] and [y0, y1] where:
    - x corresponds to longitude index (ilon)
    - y corresponds to latitude index (ilat)
    """
    x0: int  # min longitude index
    x1: int  # max longitude index
    y0: int  # min latitude index
    y1: int  # max latitude index

    def __post_init__(self):
        if self.x0 > self.x1 or self.y0 > self.y1:
            raise ValueError(
                f"Invalid rectangle: x0={self.x0}, x1={self.x1}, y0={self.y0}, y1={self.y1}"
            )

    @property
    def width(self) -> int:
        """Width of rectangle (number of points along x-axis)."""
        return self.x1 - self.x0 + 1

    @property
    def height(self) -> int:
        """Height of rectangle (number of points along y-axis)."""
        return self.y1 - self.y0 + 1

    @property
    def point_count(self) -> int:
        """Total number of lattice points in the rectangle."""
        return self.width * self.height

    def is_single_point(self) -> bool:
        """Check if rectangle contains exactly one point."""
        return self.x0 == self.x1 and self.y0 == self.y1

    def contains(self, x: int, y: int) -> bool:
        """Check if point (x, y) is within this rectangle."""
        return self.x0 <= x <= self.x1 and self.y0 <= y <= self.y1

    def midpoints(self) -> Tuple[int, int]:
        """
        Calculate midpoint indices for subdivision.

        Returns:
            Tuple of (xm, ym) where:
            - xm = (x0 + x1) // 2
            - ym = (y0 + y1) // 2
        """
        xm = (self.x0 + self.x1) // 2
        ym = (self.y0 + self.y1) // 2
        return xm, ym

    def subdivide(self) -> List[Optional[Rectangle]]:
        """
        Subdivide rectangle into 4 children (quadrants).

        Child order (fixed for consistency): NW, NE, SW, SE
        - NW: (x0..xm, ym+1..y1) - upper left
        - NE: (xm+1..x1, ym+1..y1) - upper right
        - SW: (x0..xm, y0..ym) - lower left
        - SE: (xm+1..x1, y0..ym) - lower right

        Returns:
            List of 4 Rectangle objects (some may be None if degenerate).
        """
        if self.is_single_point():
            raise ValueError("Cannot subdivide a single-point rectangle")

        xm, ym = self.midpoints()
        children: List[Optional[Rectangle]] = []

        # NW: upper left (x0..xm, ym+1..y1)
        if ym + 1 <= self.y1:
            children.append(Rectangle(self.x0, xm, ym + 1, self.y1))
        else:
            children.append(None)

        # NE: upper right (xm+1..x1, ym+1..y1)
        if xm + 1 <= self.x1 and ym + 1 <= self.y1:
            children.append(Rectangle(xm + 1, self.x1, ym + 1, self.y1))
        else:
            children.append(None)

        # SW: lower left (x0..xm, y0..ym)
        children.append(Rectangle(self.x0, xm, self.y0, ym))

        # SE: lower right (xm+1..x1, y0..ym)
        if xm + 1 <= self.x1:
            children.append(Rectangle(xm + 1, self.x1, self.y0, ym))
        else:
            children.append(None)

        return children

    def child_index_for_point(self, x: int, y: int) -> int:
        """
        Determine which child quadrant contains point (x, y).

        Args:
            x: Longitude index
            y: Latitude index

        Returns:
            Child index (0=NW, 1=NE, 2=SW, 3=SE)
        """
        if not self.contains(x, y):
            raise ValueError(f"Point ({x}, {y}) not in rectangle {self}")

        xm, ym = self.midpoints()

        # Determine quadrant
        if y > ym:  # Upper half
            if x <= xm:
                return 0  # NW
            else:
                return 1  # NE
        else:  # Lower half
            if x <= xm:
                return 2  # SW
            else:
                return 3  # SE

    def iter_points(self) -> Iterator[Tuple[int, int]]:
        """Iterate over all lattice points in the rectangle."""
        for y in range(self.y0, self.y1 + 1):
            for x in range(self.x0, self.x1 + 1):
                yield x, y

    def sample_points(self, count: int, seed: int) -> List[Tuple[int, int]]:
        """
        Generate deterministic sample points within the rectangle.

        Args:
            count: Number of sample points to generate
            seed: Random seed for deterministic sampling

        Returns:
            List of (x, y) tuples
        """
        import random
        rng = random.Random(seed)

        # Always include corners and center
        points = [
            (self.x0, self.y0),  # SW corner
            (self.x1, self.y0),  # SE corner
            (self.x0, self.y1),  # NW corner
            (self.x1, self.y1),  # NE corner
        ]

        # Add center
        xm, ym = self.midpoints()
        points.append((xm, ym))

        # Add stratified points (1/3 and 2/3)
        if self.width > 2:
            x_third = self.x0 + self.width // 3
            x_two_thirds = self.x0 + (2 * self.width) // 3
            points.append((x_third, ym))
            points.append((x_two_thirds, ym))

        if self.height > 2:
            y_third = self.y0 + self.height // 3
            y_two_thirds = self.y0 + (2 * self.height) // 3
            points.append((xm, y_third))
            points.append((xm, y_two_thirds))

        # Add random samples if needed
        remaining = count - len(points)
        if remaining > 0 and self.point_count > len(points):
            # Generate random points within bounds
            for _ in range(remaining):
                x = rng.randint(self.x0, self.x1)
                y = rng.randint(self.y0, self.y1)
                points.append((x, y))

        # Remove duplicates while preserving order
        seen = set()
        unique_points = []
        for p in points:
            if p not in seen:
                seen.add(p)
                unique_points.append(p)

        return unique_points[:count]


class QuadTreeNode(ABC):
    """Abstract base class for quadtree nodes."""

    @abstractmethod
    def is_leaf(self) -> bool:
        """Return True if this is a leaf node."""
        pass

    @abstractmethod
    def lookup(self, x: int, y: int, rect: Rectangle) -> int:
        """
        Look up the country ID for point (x, y).

        Args:
            x: Longitude index
            y: Latitude index
            rect: The rectangle this node represents

        Returns:
            Country ID for the point
        """
        pass

    @abstractmethod
    def node_count(self) -> int:
        """Return total number of nodes in this subtree."""
        pass

    @abstractmethod
    def leaf_count(self) -> int:
        """Return number of leaf nodes in this subtree."""
        pass

    @abstractmethod
    def max_depth(self) -> int:
        """Return maximum depth of this subtree."""
        pass


@dataclass
class LeafNode(QuadTreeNode):
    """
    A leaf node representing a uniform region.

    All points in the associated rectangle map to the same country ID.
    """
    country_id: int

    def is_leaf(self) -> bool:
        return True

    def lookup(self, x: int, y: int, rect: Rectangle) -> int:
        return self.country_id

    def node_count(self) -> int:
        return 1

    def leaf_count(self) -> int:
        return 1

    def max_depth(self) -> int:
        return 0


@dataclass
class InternalNode(QuadTreeNode):
    """
    An internal node with up to 4 children.

    Children are ordered: NW, NE, SW, SE (indices 0-3).
    Some children may be None for degenerate rectangles.
    """
    children: List[Optional[QuadTreeNode]]

    def __post_init__(self):
        if len(self.children) != 4:
            raise ValueError("InternalNode must have exactly 4 children slots")

    def is_leaf(self) -> bool:
        return False

    def lookup(self, x: int, y: int, rect: Rectangle) -> int:
        child_idx = rect.child_index_for_point(x, y)
        child = self.children[child_idx]

        if child is None:
            raise ValueError(
                f"No child at index {child_idx} for point ({x}, {y}) in rect {rect}"
            )

        child_rects = rect.subdivide()
        child_rect = child_rects[child_idx]

        if child_rect is None:
            raise ValueError(f"Child rectangle is None at index {child_idx}")

        return child.lookup(x, y, child_rect)

    def node_count(self) -> int:
        count = 1  # This node
        for child in self.children:
            if child is not None:
                count += child.node_count()
        return count

    def leaf_count(self) -> int:
        count = 0
        for child in self.children:
            if child is not None:
                count += child.leaf_count()
        return count

    def max_depth(self) -> int:
        max_child_depth = 0
        for child in self.children:
            if child is not None:
                max_child_depth = max(max_child_depth, child.max_depth())
        return 1 + max_child_depth


class QuadTree:
    """
    A sparse quadtree for country lookup on a quantized grid.
    """

    def __init__(self, root: QuadTreeNode, bounds: Rectangle, precision: int):
        """
        Initialize a quadtree.

        Args:
            root: The root node of the tree
            bounds: The bounding rectangle for the entire tree
            precision: The quantization precision used
        """
        self.root = root
        self.bounds = bounds
        self.precision = precision

    def lookup(self, ilat: int, ilon: int) -> int:
        """
        Look up country ID for quantized coordinates.

        Args:
            ilat: Latitude index
            ilon: Longitude index

        Returns:
            Country ID
        """
        if not self.bounds.contains(ilon, ilat):
            raise ValueError(
                f"Point ({ilon}, {ilat}) outside tree bounds {self.bounds}"
            )
        return self.root.lookup(ilon, ilat, self.bounds)

    def lookup_coords(self, lat: float, lon: float) -> int:
        """
        Look up country ID for WGS84 coordinates.

        Args:
            lat: Latitude in degrees
            lon: Longitude in degrees

        Returns:
            Country ID
        """
        from .quantize import quantize
        ilat, ilon = quantize(lat, lon, self.precision)
        return self.lookup(ilat, ilon)

    @property
    def node_count(self) -> int:
        """Total number of nodes in the tree."""
        return self.root.node_count()

    @property
    def leaf_count(self) -> int:
        """Number of leaf nodes in the tree."""
        return self.root.leaf_count()

    @property
    def depth(self) -> int:
        """Maximum depth of the tree."""
        return self.root.max_depth()
