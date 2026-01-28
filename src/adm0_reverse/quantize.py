"""
Quantization module for converting between WGS84 coordinates and integer grid indices.

This module handles the conversion between continuous (lat, lon) coordinates
and discrete (ilat, ilon) integer indices at a given precision p.

Precision p means decimal places, so Q = 10^p.
- ilon is in [0, 360*Q] representing longitude in [-180, +180]
- ilat is in [0, 180*Q] representing latitude in [-90, +90]

Quantization uses round-half-away-from-zero rounding.
"""

from typing import Tuple


def clamp_coords(lat: float, lon: float) -> Tuple[float, float]:
    """
    Clamp latitude and longitude to valid WGS84 ranges.

    Args:
        lat: Latitude in degrees
        lon: Longitude in degrees

    Returns:
        Tuple of (clamped_lat, clamped_lon)
    """
    clamped_lat = max(-90.0, min(90.0, lat))
    clamped_lon = max(-180.0, min(180.0, lon))
    return clamped_lat, clamped_lon


def _round_half_away_from_zero(x: float) -> int:
    """
    Round to nearest integer, with ties going away from zero.

    This matches the behavior of C's round() function and ensures
    consistency between Python builder and C++ runtime.
    """
    if x >= 0:
        return int(x + 0.5)
    else:
        return int(x - 0.5)


def get_grid_dimensions(precision: int) -> Tuple[int, int]:
    """
    Get the maximum grid dimensions for a given precision.

    Args:
        precision: Number of decimal places (p)

    Returns:
        Tuple of (max_ilon, max_ilat) - the maximum valid indices
    """
    q = 10 ** precision
    max_ilon = 360 * q
    max_ilat = 180 * q
    return max_ilon, max_ilat


def quantize(lat: float, lon: float, precision: int) -> Tuple[int, int]:
    """
    Convert WGS84 coordinates to quantized integer grid indices.

    Args:
        lat: Latitude in degrees [-90, 90]
        lon: Longitude in degrees [-180, 180]
        precision: Number of decimal places (p)

    Returns:
        Tuple of (ilat, ilon) as integer indices

    The quantization formula is:
        ilon = round((lon + 180) * Q)
        ilat = round((lat + 90) * Q)
    where Q = 10^precision
    """
    # Clamp to valid ranges
    lat, lon = clamp_coords(lat, lon)

    q = 10 ** precision
    max_ilon, max_ilat = get_grid_dimensions(precision)

    # Quantize using round-half-away-from-zero
    ilon = _round_half_away_from_zero((lon + 180.0) * q)
    ilat = _round_half_away_from_zero((lat + 90.0) * q)

    # Clamp indices to valid range (handles floating point edge cases)
    ilon = max(0, min(max_ilon, ilon))
    ilat = max(0, min(max_ilat, ilat))

    return ilat, ilon


def dequantize(ilat: int, ilon: int, precision: int) -> Tuple[float, float]:
    """
    Convert quantized integer grid indices back to WGS84 coordinates.

    Args:
        ilat: Latitude index
        ilon: Longitude index
        precision: Number of decimal places (p)

    Returns:
        Tuple of (lat, lon) as floating point degrees

    Note: This returns the center of the quantized cell, which may not
    exactly match the original input due to quantization.
    """
    q = 10 ** precision

    lon = (ilon / q) - 180.0
    lat = (ilat / q) - 90.0

    return lat, lon


def quantize_to_cell(lat: float, lon: float, precision: int) -> Tuple[Tuple[int, int], Tuple[float, float]]:
    """
    Quantize coordinates and return both the indices and the cell center.

    Args:
        lat: Latitude in degrees
        lon: Longitude in degrees
        precision: Number of decimal places

    Returns:
        Tuple of ((ilat, ilon), (center_lat, center_lon))
    """
    ilat, ilon = quantize(lat, lon, precision)
    center_lat, center_lon = dequantize(ilat, ilon, precision)
    return (ilat, ilon), (center_lat, center_lon)
