"""Tests for quadtree serialization."""

import pytest
from adm0_reverse.serialize import (
    TreeSerializer,
    TreeDeserializer,
    serialize_tree,
    deserialize_tree,
    serialize_country_table,
    bytes_to_cpp_array,
)
from adm0_reverse.quadtree import (
    Rectangle,
    LeafNode,
    InternalNode,
    QuadTree,
)
from adm0_reverse.builder import build_quadtree
from adm0_reverse.oracle import MockSimpleOracle


class TestTreeSerializer:
    """Tests for TreeSerializer."""

    def test_serialize_leaf(self):
        """Test serializing a single leaf node."""
        leaf = LeafNode(country_id=5)
        bounds = Rectangle(0, 100, 0, 100)
        tree = QuadTree(leaf, bounds, precision=2)

        serializer = TreeSerializer(use_varint=True)
        data = serializer.serialize(tree)

        # Should be: tag (0x01) + varint(5)
        assert len(data) == 2
        assert data[0] == 0x01  # Leaf tag
        assert data[1] == 5  # Varint for 5

    def test_serialize_internal(self):
        """Test serializing an internal node."""
        children = [
            LeafNode(1),
            LeafNode(2),
            LeafNode(3),
            LeafNode(4),
        ]
        root = InternalNode(children)
        bounds = Rectangle(0, 100, 0, 100)
        tree = QuadTree(root, bounds, precision=2)

        serializer = TreeSerializer(use_varint=True)
        data = serializer.serialize(tree)

        # Should start with internal tag and presence byte
        assert data[0] == 0x00  # Internal tag
        assert data[1] == 0x0F  # All 4 children present (binary: 1111)

    def test_serialize_with_none_children(self):
        """Test serializing internal node with None children."""
        children = [
            LeafNode(1),
            None,
            LeafNode(3),
            None,
        ]
        root = InternalNode(children)
        bounds = Rectangle(0, 100, 0, 100)
        tree = QuadTree(root, bounds, precision=2)

        serializer = TreeSerializer(use_varint=True)
        data = serializer.serialize(tree)

        assert data[0] == 0x00  # Internal tag
        assert data[1] == 0x05  # Children 0 and 2 present (binary: 0101)


class TestTreeDeserializer:
    """Tests for TreeDeserializer."""

    def test_round_trip_leaf(self):
        """Test serialize/deserialize round trip for leaf."""
        leaf = LeafNode(country_id=42)
        bounds = Rectangle(0, 100, 0, 100)
        tree = QuadTree(leaf, bounds, precision=2)

        serializer = TreeSerializer(use_varint=True)
        data = serializer.serialize(tree)

        deserializer = TreeDeserializer(use_varint=True)
        restored = deserializer.deserialize(data, bounds, precision=2)

        assert restored.lookup(50, 50) == 42

    def test_round_trip_internal(self):
        """Test serialize/deserialize round trip for internal node."""
        # Children order: NW=0, NE=1, SW=2, SE=3
        children = [
            LeafNode(1),  # NW: high lat, low lon
            LeafNode(2),  # NE: high lat, high lon
            LeafNode(3),  # SW: low lat, low lon
            LeafNode(4),  # SE: low lat, high lon
        ]
        root = InternalNode(children)
        bounds = Rectangle(0, 100, 0, 100)
        tree = QuadTree(root, bounds, precision=2)

        serializer = TreeSerializer(use_varint=True)
        data = serializer.serialize(tree)

        deserializer = TreeDeserializer(use_varint=True)
        restored = deserializer.deserialize(data, bounds, precision=2)

        # Check each quadrant (ilat, ilon)
        assert restored.lookup(75, 25) == 1  # NW: high lat, low lon
        assert restored.lookup(75, 75) == 2  # NE: high lat, high lon
        assert restored.lookup(25, 25) == 3  # SW: low lat, low lon
        assert restored.lookup(25, 75) == 4  # SE: low lat, high lon

    def test_round_trip_with_compression(self):
        """Test round trip with compression."""
        # Children order: NW=0, NE=1, SW=2, SE=3
        children = [
            LeafNode(10),  # NW: high lat, low lon
            LeafNode(20),  # NE: high lat, high lon
            LeafNode(30),  # SW: low lat, low lon
            LeafNode(40),  # SE: low lat, high lon
        ]
        root = InternalNode(children)
        bounds = Rectangle(0, 100, 0, 100)
        tree = QuadTree(root, bounds, precision=2)

        data = serialize_tree(tree, compress=True)
        restored = deserialize_tree(data, bounds, precision=2, compressed=True)

        # Check each quadrant (ilat, ilon)
        assert restored.lookup(75, 25) == 10  # NW: high lat, low lon
        assert restored.lookup(75, 75) == 20  # NE: high lat, high lon
        assert restored.lookup(25, 25) == 30  # SW: low lat, low lon
        assert restored.lookup(25, 75) == 40  # SE: low lat, high lon


class TestFullTreeRoundTrip:
    """Tests for full tree serialization round trips."""

    def test_built_tree_round_trip(self):
        """Test round trip for a tree built from oracle."""
        oracle = MockSimpleOracle(precision=0)
        tree, _ = build_quadtree(
            oracle,
            precision=0,
            brute_force_threshold=500,
        )

        # Serialize and deserialize
        data = serialize_tree(tree, compress=True)
        restored = deserialize_tree(
            data,
            tree.bounds,
            tree.precision,
            compressed=True,
        )

        # Verify lookups match
        for ilat in range(0, 181, 20):
            for ilon in range(0, 361, 40):
                expected = tree.lookup(ilat, ilon)
                actual = restored.lookup(ilat, ilon)
                assert expected == actual


class TestCountryTableSerialization:
    """Tests for country table serialization."""

    def test_serialize_country_table_2char(self):
        """Test country table serialization with 2-char codes."""
        codes = {1: "US", 2: "CA", 3: "MX"}
        data = serialize_country_table(codes, code_length=2)

        # Format: 1 byte code_len + 2 bytes count + (2+2) bytes per entry
        assert len(data) == 1 + 2 + 4 * 3

        # Code length should be 2
        assert data[0] == 2

        # Count should be 3
        count = data[1] | (data[2] << 8)
        assert count == 3

    def test_serialize_country_table_3char(self):
        """Test country table serialization with 3-char codes."""
        codes = {1: "USA", 2: "CAN", 3: "MEX"}
        data = serialize_country_table(codes, code_length=3)

        # Format: 1 byte code_len + 2 bytes count + (2+3) bytes per entry
        assert len(data) == 1 + 2 + 5 * 3

        # Code length should be 3
        assert data[0] == 3

        # Count should be 3
        count = data[1] | (data[2] << 8)
        assert count == 3

    def test_serialize_country_table_order(self):
        """Test that country table is sorted by ID."""
        codes = {3: "MX", 1: "US", 2: "CA"}
        data = serialize_country_table(codes, code_length=2)

        # First entry should be ID 1 (starts at byte 3)
        first_id = data[3] | (data[4] << 8)
        assert first_id == 1

    def test_code_padding(self):
        """Test that short codes are padded."""
        codes = {1: "US"}
        data = serialize_country_table(codes, code_length=3)

        # Code should be "US " (padded with space)
        code_bytes = data[5:8]
        assert code_bytes == b"US "


class TestBytesToCppArray:
    """Tests for C++ array generation."""

    def test_basic_conversion(self):
        """Test basic bytes to C++ array conversion."""
        data = bytes([0x01, 0x02, 0x03])
        result = bytes_to_cpp_array(data, "test_data")

        assert "test_data[]" in result
        assert "0x01" in result
        assert "0x02" in result
        assert "0x03" in result
        assert "test_data_size = 3" in result

    def test_empty_data(self):
        """Test conversion of empty data."""
        data = bytes()
        result = bytes_to_cpp_array(data, "empty")

        assert "empty[]" in result
        assert "empty_size = 0" in result
