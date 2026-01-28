"""
Oracle interface for country lookup.

This module defines the oracle protocol and provides mock implementations
for testing until the real oracle is available.
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Tuple, Callable, Optional
import math


# Special country IDs
OCEAN_ID = 0  # Points not in any country (ocean/international waters)


class Oracle(ABC):
    """
    Abstract base class for country lookup oracles.

    An oracle provides ground truth for what country a given grid point
    belongs to. The builder uses the oracle to construct the quadtree.
    """

    @abstractmethod
    def lookup(self, ilat: int, ilon: int) -> int:
        """
        Look up the country ID for a quantized grid point.

        Args:
            ilat: Latitude index
            ilon: Longitude index

        Returns:
            Country ID (0 = ocean/no country)
        """
        pass

    def lookup_batch(self, points: List[Tuple[int, int]]) -> List[int]:
        """
        Look up country IDs for multiple points.

        Default implementation calls lookup() for each point.
        Subclasses may override for better performance (e.g., batch SQL queries).

        Args:
            points: List of (ilat, ilon) tuples

        Returns:
            List of country IDs in the same order as input points
        """
        return [self.lookup(ilat, ilon) for ilat, ilon in points]

    @abstractmethod
    def get_country_codes(self) -> Dict[int, str]:
        """
        Get mapping from country IDs to ISO codes.

        Returns:
            Dictionary mapping country_id -> ISO 3166-1 alpha-2 code
        """
        pass


class FunctionOracle(Oracle):
    """
    Oracle wrapper for a simple function.

    Wraps a callable (ilat, ilon) -> country_id with optional country codes.
    """

    def __init__(
        self,
        func: Callable[[int, int], int],
        country_codes: Optional[Dict[int, str]] = None
    ):
        self._func = func
        self._codes = country_codes or {}

    def lookup(self, ilat: int, ilon: int) -> int:
        return self._func(ilat, ilon)

    def get_country_codes(self) -> Dict[int, str]:
        return self._codes


class MockSimpleOracle(Oracle):
    """
    Simple mock oracle for testing.

    Creates a world divided into simple geometric regions.
    """

    def __init__(self, precision: int):
        self.precision = precision
        self.q = 10 ** precision
        # Country codes: 0=Ocean, 1=North, 2=South, 3=East, 4=West
        self._codes = {
            0: "OC",  # Ocean
            1: "NO",  # North hemisphere (simplified)
            2: "SO",  # South hemisphere (simplified)
        }

    def lookup(self, ilat: int, ilon: int) -> int:
        # Simple division: north hemisphere = 1, south = 2
        # Ocean in a band around the equator
        mid_lat = 90 * self.q  # ilat for equator

        # Ocean band around equator (10% of height)
        ocean_band = int(5 * self.q)
        if abs(ilat - mid_lat) < ocean_band:
            return OCEAN_ID

        if ilat > mid_lat:
            return 1  # North
        else:
            return 2  # South

    def get_country_codes(self) -> Dict[int, str]:
        return self._codes


class MockCircleOracle(Oracle):
    """
    Mock oracle with circular countries for testing.

    Creates several circular "countries" at different locations,
    useful for testing border refinement.
    """

    def __init__(self, precision: int):
        self.precision = precision
        self.q = 10 ** precision
        self.max_ilon = 360 * self.q
        self.max_ilat = 180 * self.q

        # Define some circular regions (center_ilon, center_ilat, radius, country_id)
        # Using grid coordinates
        self.circles: List[Tuple[int, int, int, int]] = [
            # A circle in the "Atlantic" (roughly)
            (int(150 * self.q), int(120 * self.q), int(20 * self.q), 1),
            # A circle in "Europe" region
            (int(190 * self.q), int(135 * self.q), int(15 * self.q), 2),
            # A circle in "Asia" region
            (int(280 * self.q), int(125 * self.q), int(25 * self.q), 3),
            # A circle in "South America"
            (int(130 * self.q), int(60 * self.q), int(18 * self.q), 4),
            # A circle in "Australia"
            (int(310 * self.q), int(55 * self.q), int(12 * self.q), 5),
        ]

        self._codes = {
            0: "OC",  # Ocean
            1: "C1",  # Circle 1
            2: "C2",  # Circle 2
            3: "C3",  # Circle 3
            4: "C4",  # Circle 4
            5: "C5",  # Circle 5
        }

    def lookup(self, ilat: int, ilon: int) -> int:
        # Check each circle
        for cx, cy, r, country_id in self.circles:
            dx = ilon - cx
            dy = ilat - cy
            dist_sq = dx * dx + dy * dy
            if dist_sq <= r * r:
                return country_id

        return OCEAN_ID  # Not in any circle = ocean

    def get_country_codes(self) -> Dict[int, str]:
        return self._codes


class MockGridOracle(Oracle):
    """
    Mock oracle with a checkerboard pattern.

    Divides the world into a grid of alternating countries.
    Useful for stress testing the quadtree builder.
    """

    def __init__(self, precision: int, grid_size: int = 10):
        """
        Args:
            precision: Quantization precision
            grid_size: Number of grid cells per degree
        """
        self.precision = precision
        self.q = 10 ** precision
        self.cell_size = self.q // grid_size

        # Just two alternating countries
        self._codes = {
            1: "A1",
            2: "A2",
        }

    def lookup(self, ilat: int, ilon: int) -> int:
        if self.cell_size == 0:
            return 1

        cell_x = ilon // self.cell_size
        cell_y = ilat // self.cell_size

        # Checkerboard pattern
        if (cell_x + cell_y) % 2 == 0:
            return 1
        else:
            return 2

    def get_country_codes(self) -> Dict[int, str]:
        return self._codes


class MockRectangleOracle(Oracle):
    """
    Mock oracle with rectangular countries.

    Simple rectangular regions representing countries,
    useful for testing and verification.
    """

    def __init__(self, precision: int):
        self.precision = precision
        self.q = 10 ** precision

        # Define rectangular countries as (x0, y0, x1, y1, country_id)
        # Coordinates are in grid units
        self.rectangles: List[Tuple[int, int, int, int, int]] = [
            # "USA" - roughly
            (int(60 * self.q), int(100 * self.q), int(120 * self.q), int(140 * self.q), 1),
            # "Brazil" - roughly
            (int(110 * self.q), int(50 * self.q), int(150 * self.q), int(90 * self.q), 2),
            # "Europe" - roughly
            (int(170 * self.q), int(115 * self.q), int(210 * self.q), int(160 * self.q), 3),
            # "China" - roughly
            (int(255 * self.q), int(100 * self.q), int(300 * self.q), int(140 * self.q), 4),
            # "Australia" - roughly
            (int(290 * self.q), int(40 * self.q), int(330 * self.q), int(75 * self.q), 5),
        ]

        self._codes = {
            0: "OC",
            1: "US",
            2: "BR",
            3: "EU",
            4: "CN",
            5: "AU",
        }

    def lookup(self, ilat: int, ilon: int) -> int:
        for x0, y0, x1, y1, country_id in self.rectangles:
            if x0 <= ilon <= x1 and y0 <= ilat <= y1:
                return country_id
        return OCEAN_ID

    def get_country_codes(self) -> Dict[int, str]:
        return self._codes
