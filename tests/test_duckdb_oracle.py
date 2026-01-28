"""Tests for DuckDB oracle."""

import pytest
from pathlib import Path

from adm0_reverse.duckdb_oracle import DuckDBOracle, create_oracle_from_natural_earth
from adm0_reverse.quantize import quantize


# Path to test data
DATA_DIR = Path(__file__).parent.parent / "data"
SHAPEFILE = "ne_10m_admin_0_countries_tlc.shp"


@pytest.fixture
def oracle():
    """Create oracle fixture for tests."""
    if not (DATA_DIR / SHAPEFILE).exists():
        pytest.skip("Shapefile not found - run tests with data available")

    oracle = create_oracle_from_natural_earth(DATA_DIR, precision=2, filename=SHAPEFILE)
    yield oracle
    oracle.close()


class TestDuckDBOracle:
    """Tests for DuckDBOracle class."""

    def test_country_count(self, oracle):
        """Test that oracle loads expected number of countries."""
        count = oracle.get_country_count()
        # Natural Earth has ~250 countries
        assert 200 <= count <= 300

    def test_lookup_japan(self, oracle):
        """Test lookup for Tokyo, Japan."""
        lat, lon = 35.6762, 139.6503
        ilat, ilon = quantize(lat, lon, oracle.precision)
        country_id = oracle.lookup(ilat, ilon)

        codes = oracle.get_country_codes()
        iso = codes.get(country_id, "???")
        assert iso == "JPN"

    def test_lookup_france(self, oracle):
        """Test lookup for Paris, France."""
        lat, lon = 48.8566, 2.3522
        ilat, ilon = quantize(lat, lon, oracle.precision)
        country_id = oracle.lookup(ilat, ilon)

        codes = oracle.get_country_codes()
        iso = codes.get(country_id, "???")
        assert iso == "FRA"

    def test_lookup_usa(self, oracle):
        """Test lookup for New York, USA."""
        lat, lon = 40.7128, -74.0060
        ilat, ilon = quantize(lat, lon, oracle.precision)
        country_id = oracle.lookup(ilat, ilon)

        codes = oracle.get_country_codes()
        iso = codes.get(country_id, "???")
        assert iso == "USA"

    def test_lookup_australia(self, oracle):
        """Test lookup for Sydney, Australia."""
        lat, lon = -33.8688, 151.2093
        ilat, ilon = quantize(lat, lon, oracle.precision)
        country_id = oracle.lookup(ilat, ilon)

        codes = oracle.get_country_codes()
        iso = codes.get(country_id, "???")
        assert iso == "AUS"

    def test_lookup_ocean(self, oracle):
        """Test lookup for ocean point (Gulf of Guinea)."""
        lat, lon = 0.0, 0.0
        ilat, ilon = quantize(lat, lon, oracle.precision)
        country_id = oracle.lookup(ilat, ilon)

        # Ocean should return ID 0
        assert country_id == 0

    def test_lookup_caching(self, oracle):
        """Test that repeated lookups use cache."""
        lat, lon = 35.6762, 139.6503
        ilat, ilon = quantize(lat, lon, oracle.precision)

        # First lookup
        result1 = oracle.lookup(ilat, ilon)

        # Second lookup should hit cache
        result2 = oracle.lookup(ilat, ilon)

        assert result1 == result2

    def test_country_codes_mapping(self, oracle):
        """Test that country codes mapping is valid."""
        codes = oracle.get_country_codes()

        # Should have entries
        assert len(codes) > 0

        # ID 0 should map to ocean/unknown
        assert 0 in codes

        # All values should be 3-character strings
        for country_id, iso in codes.items():
            assert isinstance(country_id, int)
            assert isinstance(iso, str)
            assert len(iso) == 3 or iso == "---"

    def test_lookup_batch(self, oracle):
        """Test batch lookup returns same results as individual lookups."""
        # Test several known locations
        locations = [
            (35.6762, 139.6503),   # Tokyo
            (48.8566, 2.3522),     # Paris
            (40.7128, -74.0060),   # New York
            (-33.8688, 151.2093),  # Sydney
            (0.0, 0.0),            # Ocean
        ]

        # Convert to grid coordinates
        points = [quantize(lat, lon, oracle.precision) for lat, lon in locations]

        # Get results via individual lookups
        individual_results = [oracle.lookup(ilat, ilon) for ilat, ilon in points]

        # Clear cache to ensure batch lookup actually queries
        oracle._cache.clear()

        # Get results via batch lookup
        batch_results = oracle.lookup_batch(points)

        # Results should match
        assert individual_results == batch_results

    def test_lookup_batch_performance(self, oracle):
        """Test that batch lookup is faster than individual lookups."""
        import time

        # Generate 100 random points
        import random
        random.seed(42)
        points = [
            quantize(random.uniform(-60, 60), random.uniform(-150, 150), oracle.precision)
            for _ in range(100)
        ]

        # Clear cache
        oracle._cache.clear()

        # Time individual lookups
        start = time.time()
        for ilat, ilon in points:
            oracle.lookup(ilat, ilon)
        individual_time = time.time() - start

        # Clear cache
        oracle._cache.clear()

        # Time batch lookup
        start = time.time()
        oracle.lookup_batch(points)
        batch_time = time.time() - start

        # Batch should be at least 2x faster (typically 10-50x)
        print(f"\n  Individual: {individual_time:.3f}s, Batch: {batch_time:.3f}s")
        print(f"  Speedup: {individual_time / batch_time:.1f}x")
        assert batch_time < individual_time / 2


class TestCreateOracleFromNaturalEarth:
    """Tests for create_oracle_from_natural_earth function."""

    def test_creates_oracle(self):
        """Test that function creates a valid oracle."""
        if not (DATA_DIR / SHAPEFILE).exists():
            pytest.skip("Shapefile not found")

        oracle = create_oracle_from_natural_earth(DATA_DIR, precision=0, filename=SHAPEFILE)
        try:
            assert oracle.get_country_count() > 0
        finally:
            oracle.close()

    def test_missing_file_raises(self):
        """Test that missing file raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            create_oracle_from_natural_earth(DATA_DIR, precision=0, filename="nonexistent.shp")
