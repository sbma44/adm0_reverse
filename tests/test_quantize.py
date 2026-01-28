"""Tests for quantization module."""

import pytest
from adm0_reverse.quantize import (
    clamp_coords,
    quantize,
    dequantize,
    get_grid_dimensions,
    _round_half_away_from_zero,
)


class TestClampCoords:
    """Tests for coordinate clamping."""

    def test_within_bounds(self):
        """Test coordinates within valid range are unchanged."""
        lat, lon = clamp_coords(45.0, -90.0)
        assert lat == 45.0
        assert lon == -90.0

    def test_clamp_latitude_high(self):
        """Test latitude clamping at north pole."""
        lat, lon = clamp_coords(100.0, 0.0)
        assert lat == 90.0
        assert lon == 0.0

    def test_clamp_latitude_low(self):
        """Test latitude clamping at south pole."""
        lat, lon = clamp_coords(-100.0, 0.0)
        assert lat == -90.0
        assert lon == 0.0

    def test_clamp_longitude_high(self):
        """Test longitude clamping at dateline."""
        lat, lon = clamp_coords(0.0, 200.0)
        assert lat == 0.0
        assert lon == 180.0

    def test_clamp_longitude_low(self):
        """Test longitude clamping at negative dateline."""
        lat, lon = clamp_coords(0.0, -200.0)
        assert lat == 0.0
        assert lon == -180.0

    def test_extreme_values(self):
        """Test extreme values are clamped correctly."""
        lat, lon = clamp_coords(1000.0, -1000.0)
        assert lat == 90.0
        assert lon == -180.0


class TestRounding:
    """Tests for round-half-away-from-zero."""

    def test_positive_half(self):
        """Test rounding 0.5 away from zero (positive)."""
        assert _round_half_away_from_zero(0.5) == 1
        assert _round_half_away_from_zero(1.5) == 2
        assert _round_half_away_from_zero(2.5) == 3

    def test_negative_half(self):
        """Test rounding -0.5 away from zero (negative)."""
        assert _round_half_away_from_zero(-0.5) == -1
        assert _round_half_away_from_zero(-1.5) == -2
        assert _round_half_away_from_zero(-2.5) == -3

    def test_positive_round_down(self):
        """Test rounding down for positive values."""
        assert _round_half_away_from_zero(0.4) == 0
        assert _round_half_away_from_zero(1.4) == 1

    def test_positive_round_up(self):
        """Test rounding up for positive values."""
        assert _round_half_away_from_zero(0.6) == 1
        assert _round_half_away_from_zero(1.6) == 2


class TestGridDimensions:
    """Tests for grid dimension calculation."""

    def test_precision_0(self):
        """Test precision 0 (integer coordinates)."""
        max_ilon, max_ilat = get_grid_dimensions(0)
        assert max_ilon == 360
        assert max_ilat == 180

    def test_precision_1(self):
        """Test precision 1 (one decimal place)."""
        max_ilon, max_ilat = get_grid_dimensions(1)
        assert max_ilon == 3600
        assert max_ilat == 1800

    def test_precision_2(self):
        """Test precision 2 (two decimal places)."""
        max_ilon, max_ilat = get_grid_dimensions(2)
        assert max_ilon == 36000
        assert max_ilat == 18000


class TestQuantize:
    """Tests for coordinate quantization."""

    def test_origin(self):
        """Test quantization at origin (0, 0)."""
        ilat, ilon = quantize(0.0, 0.0, 2)
        # lat=0 -> ilat = round((0+90)*100) = 9000
        # lon=0 -> ilon = round((0+180)*100) = 18000
        assert ilat == 9000
        assert ilon == 18000

    def test_south_pole(self):
        """Test quantization at south pole."""
        ilat, ilon = quantize(-90.0, 0.0, 2)
        # lat=-90 -> ilat = round((-90+90)*100) = 0
        assert ilat == 0
        assert ilon == 18000

    def test_north_pole(self):
        """Test quantization at north pole."""
        ilat, ilon = quantize(90.0, 0.0, 2)
        # lat=90 -> ilat = round((90+90)*100) = 18000
        assert ilat == 18000
        assert ilon == 18000

    def test_dateline_west(self):
        """Test quantization at western dateline."""
        ilat, ilon = quantize(0.0, -180.0, 2)
        # lon=-180 -> ilon = round((-180+180)*100) = 0
        assert ilon == 0
        assert ilat == 9000

    def test_dateline_east(self):
        """Test quantization at eastern dateline."""
        ilat, ilon = quantize(0.0, 180.0, 2)
        # lon=180 -> ilon = round((180+180)*100) = 36000
        assert ilon == 36000
        assert ilat == 9000

    def test_precision_consistency(self):
        """Test that different precisions scale correctly."""
        lat, lon = 45.67, -123.45

        ilat1, ilon1 = quantize(lat, lon, 1)
        ilat2, ilon2 = quantize(lat, lon, 2)

        # Precision 2 should have 10x the resolution
        assert abs(ilat2 - ilat1 * 10) <= 5
        assert abs(ilon2 - ilon1 * 10) <= 5


class TestDequantize:
    """Tests for coordinate dequantization."""

    def test_origin(self):
        """Test dequantization at grid origin."""
        lat, lon = dequantize(9000, 18000, 2)
        assert lat == 0.0
        assert lon == 0.0

    def test_south_pole(self):
        """Test dequantization at south pole."""
        lat, lon = dequantize(0, 18000, 2)
        assert lat == -90.0
        assert lon == 0.0

    def test_north_pole(self):
        """Test dequantization at north pole."""
        lat, lon = dequantize(18000, 18000, 2)
        assert lat == 90.0
        assert lon == 0.0

    def test_round_trip(self):
        """Test quantize -> dequantize round trip."""
        original_lat, original_lon = 45.67, -123.45

        ilat, ilon = quantize(original_lat, original_lon, 2)
        recovered_lat, recovered_lon = dequantize(ilat, ilon, 2)

        # Should be within half a grid cell
        assert abs(recovered_lat - original_lat) <= 0.005
        assert abs(recovered_lon - original_lon) <= 0.005


class TestEdgeCases:
    """Tests for edge cases and boundary conditions."""

    def test_exactly_on_boundary(self):
        """Test coordinates exactly on grid boundaries."""
        # At precision 2, grid cells are 0.01 degrees
        ilat, ilon = quantize(45.005, -123.005, 2)
        # These should round to exact grid points
        lat, lon = dequantize(ilat, ilon, 2)
        assert abs(lat - 45.01) < 1e-9 or abs(lat - 45.00) < 1e-9
        assert abs(lon - (-123.01)) < 1e-9 or abs(lon - (-123.00)) < 1e-9

    def test_very_small_values(self):
        """Test very small coordinate values."""
        ilat, ilon = quantize(0.001, 0.001, 3)
        lat, lon = dequantize(ilat, ilon, 3)
        assert abs(lat - 0.001) < 0.001
        assert abs(lon - 0.001) < 0.001
