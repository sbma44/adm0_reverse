"""Tests for C++ code generation."""

import pytest
from adm0_reverse.codegen import generate_cpp_header, generate_test_header
from adm0_reverse.builder import build_quadtree
from adm0_reverse.oracle import MockRectangleOracle, MockSimpleOracle


class TestGenerateCppHeader:
    """Tests for generate_cpp_header function."""

    def test_basic_header_generation(self):
        """Test basic header generation."""
        oracle = MockSimpleOracle(precision=0)
        tree, _ = build_quadtree(
            oracle,
            precision=0,
            brute_force_threshold=500,
        )

        header = generate_cpp_header(
            tree=tree,
            country_codes=oracle.get_country_codes(),
            precision=0,
            oracle_source="test",
            namespace="test_ns",
            include_iso_lookup=True,
            compress=False,
        )

        # Check header structure
        assert "#ifndef ADM0_COUNTRY_LOOKUP_P0_HPP" in header
        assert "#define ADM0_COUNTRY_LOOKUP_P0_HPP" in header
        assert "namespace test_ns" in header
        assert "country_id(double lat, double lon)" in header
        assert "country_iso(double lat, double lon)" in header
        assert "#endif" in header

    def test_header_contains_metadata(self):
        """Test that header contains metadata comments."""
        oracle = MockSimpleOracle(precision=1)
        tree, _ = build_quadtree(
            oracle,
            precision=1,
            brute_force_threshold=100,
        )

        header = generate_cpp_header(
            tree=tree,
            country_codes=oracle.get_country_codes(),
            precision=1,
            oracle_source="TestOracle",
        )

        assert "Precision: 1" in header
        assert "TestOracle" in header
        assert "Tree statistics:" in header

    def test_header_with_compression(self):
        """Test header generation with compression."""
        oracle = MockSimpleOracle(precision=0)
        tree, _ = build_quadtree(oracle, precision=0)

        header = generate_cpp_header(
            tree=tree,
            country_codes=oracle.get_country_codes(),
            precision=0,
            compress=True,
        )

        assert "#include <zlib.h>" in header
        assert "ensure_decompressed" in header

    def test_header_without_compression(self):
        """Test header generation without compression."""
        oracle = MockSimpleOracle(precision=0)
        tree, _ = build_quadtree(oracle, precision=0)

        header = generate_cpp_header(
            tree=tree,
            country_codes=oracle.get_country_codes(),
            precision=0,
            compress=False,
        )

        assert "#include <zlib.h>" not in header
        assert "ensure_decompressed" not in header

    def test_header_without_iso_lookup(self):
        """Test header generation without ISO lookup."""
        oracle = MockSimpleOracle(precision=0)
        tree, _ = build_quadtree(oracle, precision=0)

        header = generate_cpp_header(
            tree=tree,
            country_codes=oracle.get_country_codes(),
            precision=0,
            include_iso_lookup=False,
        )

        assert "country_id(double lat, double lon)" in header
        assert "country_iso2" not in header

    def test_quantization_constants(self):
        """Test that quantization constants are correct."""
        # Use precision=0 for fast test, but verify the constants are correct
        # for precision=2 by checking the formula in the generated header
        oracle = MockSimpleOracle(precision=0)
        tree, _ = build_quadtree(oracle, precision=0, brute_force_threshold=500)

        # Generate header at precision 2 using the same tree structure
        # (the constants are derived from precision, not the tree)
        header = generate_cpp_header(
            tree=tree,
            country_codes=oracle.get_country_codes(),
            precision=2,  # Use precision 2 for constants check
        )

        assert "PRECISION = 2" in header
        assert "Q = 100" in header
        assert "MAX_ILON = 36000" in header
        assert "MAX_ILAT = 18000" in header

    def test_header_valid_cpp(self):
        """Test that generated header has valid C++ structure."""
        oracle = MockRectangleOracle(precision=0)
        tree, _ = build_quadtree(oracle, precision=0)

        header = generate_cpp_header(
            tree=tree,
            country_codes=oracle.get_country_codes(),
            precision=0,
        )

        # Check basic syntax elements
        assert header.count("{") == header.count("}")
        assert "static constexpr" in header
        assert "inline" in header


class TestGenerateTestHeader:
    """Tests for generate_test_header function."""

    def test_generates_valid_header(self):
        """Test that test header generation works."""
        header = generate_test_header(precision=0)

        assert "#ifndef" in header
        assert "#define" in header
        assert "#endif" in header
        assert "country_id" in header

    def test_precision_parameter(self):
        """Test that precision parameter is respected."""
        header = generate_test_header(precision=0)
        assert "PRECISION = 0" in header

    def test_namespace_parameter(self):
        """Test that namespace parameter is respected."""
        header = generate_test_header(precision=0, namespace="my_ns")
        assert "namespace my_ns" in header
