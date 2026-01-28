"""
DuckDB-based oracle for country lookup using Natural Earth shapefile data.

This module implements a real oracle that uses DuckDB's spatial extension
to perform point-in-polygon queries against Natural Earth ADM0 boundaries.
"""

from pathlib import Path
from typing import Dict, List, Optional, Tuple
import zipfile
import tempfile
import shutil

import duckdb

from .oracle import Oracle, OCEAN_ID
from .quantize import dequantize


class DuckDBOracle(Oracle):
    """
    Oracle implementation using DuckDB spatial extension.

    Loads Natural Earth ADM0 shapefile and performs point-in-polygon
    queries to determine country membership using an R-tree spatial index.
    """

    def __init__(
        self,
        shapefile_path: Path,
        precision: int,
        iso_field: str = "ADM0_ISO",
        cache_size: int = 10000,
    ):
        """
        Initialize the DuckDB oracle.

        Args:
            shapefile_path: Path to shapefile (.shp) or zip containing shapefile
            precision: Quantization precision for coordinate conversion
            iso_field: Name of the field containing ISO country codes
            cache_size: LRU cache size for query results
        """
        self.precision = precision
        self.iso_field = iso_field
        self._cache: Dict[tuple, int] = {}
        self._cache_size = cache_size

        # Handle zip files
        self._temp_dir: Optional[Path] = None
        if shapefile_path.suffix == ".zip":
            self._temp_dir = Path(tempfile.mkdtemp())
            with zipfile.ZipFile(shapefile_path, "r") as zf:
                zf.extractall(self._temp_dir)
            # Find the .shp file
            shp_files = list(self._temp_dir.glob("*.shp"))
            if not shp_files:
                raise ValueError(f"No .shp file found in {shapefile_path}")
            shapefile_path = shp_files[0]

        self._shapefile_path = shapefile_path

        # Initialize DuckDB connection
        self._con = duckdb.connect(":memory:")
        self._con.install_extension("spatial")
        self._con.load_extension("spatial")

        # Load shapefile and build country code mapping
        self._load_shapefile()
        self._build_country_mapping()

    def _load_shapefile(self) -> None:
        """Load shapefile into DuckDB."""
        self._con.execute(f"""
            CREATE TABLE countries AS
            SELECT * FROM st_read('{self._shapefile_path}')
        """)

        # Create spatial index for faster queries
        self._con.execute("""
            CREATE INDEX countries_geom_idx ON countries USING RTREE (geom)
        """)

    def _build_country_mapping(self) -> None:
        """Build mapping from ISO codes to integer IDs."""
        # Get all unique ISO codes
        result = self._con.execute(f"""
            SELECT DISTINCT {self.iso_field}
            FROM countries
            WHERE {self.iso_field} IS NOT NULL AND {self.iso_field} != '-99'
            ORDER BY {self.iso_field}
        """).fetchall()

        # Build bidirectional mapping
        # ID 0 is reserved for ocean/unknown
        self._iso_to_id: Dict[str, int] = {}
        self._id_to_iso: Dict[int, str] = {OCEAN_ID: "---"}  # Ocean/unknown

        for i, (iso_code,) in enumerate(result, start=1):
            self._iso_to_id[iso_code] = i
            self._id_to_iso[i] = iso_code

        # Handle special cases (disputed territories, etc.)
        # Assign them to a special "unknown" category or give them unique IDs
        self._iso_to_id["-99"] = OCEAN_ID  # Map unrecognized to ocean

    def _query_point(self, lat: float, lon: float) -> Optional[str]:
        """
        Query the ISO code for a point.

        Args:
            lat: Latitude in degrees
            lon: Longitude in degrees

        Returns:
            ISO code or None if not in any country
        """
        result = self._con.execute(f"""
            SELECT {self.iso_field}
            FROM countries
            WHERE ST_Contains(geom, ST_Point(?, ?))
            LIMIT 1
        """, [lon, lat]).fetchone()

        if result:
            return result[0]
        return None

    def lookup(self, ilat: int, ilon: int) -> int:
        """
        Look up the country ID for a quantized grid point.

        Args:
            ilat: Latitude index
            ilon: Longitude index

        Returns:
            Country ID (0 = ocean/no country)
        """
        # Check cache
        cache_key = (ilat, ilon)
        if cache_key in self._cache:
            return self._cache[cache_key]

        # Convert to lat/lon
        lat, lon = dequantize(ilat, ilon, self.precision)

        # Query the shapefile
        iso_code = self._query_point(lat, lon)

        # Map to ID
        if iso_code is None or iso_code == "-99":
            country_id = OCEAN_ID
        else:
            country_id = self._iso_to_id.get(iso_code, OCEAN_ID)

        # Cache result (simple LRU approximation)
        if len(self._cache) >= self._cache_size:
            # Remove oldest entries (first 10%)
            keys_to_remove = list(self._cache.keys())[: self._cache_size // 10]
            for k in keys_to_remove:
                del self._cache[k]

        self._cache[cache_key] = country_id
        return country_id

    def lookup_batch(self, points: List[Tuple[int, int]]) -> List[int]:
        """
        Look up country IDs for multiple quantized grid points in a single query.

        This is much faster than calling lookup() repeatedly due to reduced
        Python<->DuckDB round-trip overhead.

        Args:
            points: List of (ilat, ilon) tuples

        Returns:
            List of country IDs in the same order as input points
        """
        if not points:
            return []

        # Separate cached and uncached points
        results = [None] * len(points)
        uncached_indices = []
        uncached_coords = []  # (lat, lon) pairs for query

        for i, (ilat, ilon) in enumerate(points):
            cache_key = (ilat, ilon)
            if cache_key in self._cache:
                results[i] = self._cache[cache_key]
            else:
                uncached_indices.append(i)
                lat, lon = dequantize(ilat, ilon, self.precision)
                uncached_coords.append((lat, lon, i))  # Include original index

        if not uncached_coords:
            return results

        # Build batch query using a CTE with row numbers to preserve order
        # Query all uncached points in a single SQL statement
        values_list = ", ".join(
            f"({lon}, {lat}, {idx})" for lat, lon, idx in uncached_coords
        )

        query = f"""
            WITH points AS (
                SELECT col0 as lon, col1 as lat, col2 as idx
                FROM (VALUES {values_list})
            )
            SELECT p.idx, c.{self.iso_field}
            FROM points p
            LEFT JOIN countries c ON ST_Contains(c.geom, ST_Point(p.lon, p.lat))
            ORDER BY p.idx
        """

        query_results = self._con.execute(query).fetchall()

        # Build a map from idx to iso_code
        idx_to_iso = {row[0]: row[1] for row in query_results}

        # Fill in uncached results
        for i, (ilat, ilon) in enumerate(points):
            if results[i] is None:
                iso_code = idx_to_iso.get(i)
                if iso_code is None or iso_code == "-99":
                    country_id = OCEAN_ID
                else:
                    country_id = self._iso_to_id.get(iso_code, OCEAN_ID)

                results[i] = country_id

                # Cache the result
                cache_key = (ilat, ilon)
                if len(self._cache) < self._cache_size:
                    self._cache[cache_key] = country_id

        return results

    def get_country_codes(self) -> Dict[int, str]:
        """
        Get mapping from country IDs to ISO codes.

        Returns:
            Dictionary mapping country_id -> ISO 3166-1 alpha-3 code
        """
        return self._id_to_iso.copy()

    def get_country_count(self) -> int:
        """Get the number of countries (excluding ocean)."""
        return len(self._id_to_iso) - 1  # Exclude ocean

    def close(self) -> None:
        """Close the database connection and clean up temporary files."""
        if self._con:
            self._con.close()
            self._con = None

        if self._temp_dir and self._temp_dir.exists():
            shutil.rmtree(self._temp_dir)
            self._temp_dir = None

    def __del__(self):
        """Cleanup on garbage collection."""
        self.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False


def create_oracle_from_natural_earth(
    data_dir: Path,
    precision: int,
    filename: str = "ne_10m_admin_0_countries_tlc.zip",
) -> DuckDBOracle:
    """
    Convenience function to create an oracle from Natural Earth data.

    Args:
        data_dir: Directory containing the shapefile or zip
        precision: Quantization precision
        filename: Name of the shapefile or zip file

    Returns:
        Configured DuckDBOracle instance
    """
    shapefile_path = data_dir / filename

    # Try zip first, then unzipped shp
    if not shapefile_path.exists():
        shp_path = data_dir / filename.replace(".zip", ".shp")
        if shp_path.exists():
            shapefile_path = shp_path
        else:
            raise FileNotFoundError(
                f"Could not find {filename} or corresponding .shp in {data_dir}"
            )

    return DuckDBOracle(shapefile_path, precision)
