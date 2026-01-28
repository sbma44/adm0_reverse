"""
Quadtree serialization module.

This module handles serialization of the quadtree to a compact binary format
suitable for embedding in C++ headers.

Binary Format:
- Tree is serialized in preorder traversal
- Each node starts with a tag byte:
  - 0x00 = Internal node (followed by 4 child presence bits, then children)
  - 0x01-0xFF = Leaf node with country_id (1 byte for small IDs)
  - For larger country IDs, we use a variable-length encoding

The format is designed for simple decoding in C++ without complex parsing.
"""

from typing import List, Tuple, Dict, Optional
import struct
import zlib

from .quadtree import QuadTreeNode, LeafNode, InternalNode, QuadTree, Rectangle


# Node type tags
TAG_INTERNAL = 0x00
TAG_LEAF_BASE = 0x01  # Leaf tags are 0x01 + country_id for small IDs


class TreeSerializer:
    """Serializes a quadtree to compact binary format."""

    def __init__(self, use_varint: bool = True):
        """
        Args:
            use_varint: Use variable-length integer encoding for country IDs
        """
        self.use_varint = use_varint

    def serialize(self, tree: QuadTree) -> bytes:
        """
        Serialize a quadtree to bytes.

        Args:
            tree: The quadtree to serialize

        Returns:
            Serialized bytes
        """
        buffer = bytearray()
        self._serialize_node(tree.root, buffer)
        return bytes(buffer)

    def _encode_varint(self, value: int) -> bytes:
        """Encode an integer using variable-length encoding."""
        result = bytearray()
        while value >= 0x80:
            result.append((value & 0x7F) | 0x80)
            value >>= 7
        result.append(value)
        return bytes(result)

    def _serialize_node(self, node: QuadTreeNode, buffer: bytearray) -> None:
        """Recursively serialize a node."""
        if node.is_leaf():
            assert isinstance(node, LeafNode)
            country_id = node.country_id

            if self.use_varint:
                # Tag byte indicates leaf
                buffer.append(TAG_LEAF_BASE)
                # Country ID as varint
                buffer.extend(self._encode_varint(country_id))
            else:
                # Simple encoding: tag includes small country IDs
                if country_id < 255:
                    buffer.append(TAG_LEAF_BASE + country_id)
                else:
                    # Extended format for large IDs
                    buffer.append(0xFF)
                    buffer.extend(struct.pack("<H", country_id))
        else:
            assert isinstance(node, InternalNode)
            # Internal node tag
            buffer.append(TAG_INTERNAL)

            # Child presence bits (4 bits packed into 1 byte)
            presence = 0
            for i, child in enumerate(node.children):
                if child is not None:
                    presence |= (1 << i)
            buffer.append(presence)

            # Serialize non-null children in order
            for child in node.children:
                if child is not None:
                    self._serialize_node(child, buffer)


class TreeDeserializer:
    """Deserializes a quadtree from binary format."""

    def __init__(self, use_varint: bool = True):
        self.use_varint = use_varint
        self._data: bytes = b""
        self._pos: int = 0

    def deserialize(self, data: bytes, bounds: Rectangle, precision: int) -> QuadTree:
        """
        Deserialize a quadtree from bytes.

        Args:
            data: Serialized tree bytes
            bounds: Bounding rectangle for the tree
            precision: Quantization precision

        Returns:
            Deserialized QuadTree
        """
        self._data = data
        self._pos = 0
        root = self._deserialize_node()
        return QuadTree(root, bounds, precision)

    def _read_byte(self) -> int:
        """Read a single byte."""
        if self._pos >= len(self._data):
            raise ValueError("Unexpected end of data")
        b = self._data[self._pos]
        self._pos += 1
        return b

    def _read_varint(self) -> int:
        """Read a variable-length integer."""
        result = 0
        shift = 0
        while True:
            b = self._read_byte()
            result |= (b & 0x7F) << shift
            if (b & 0x80) == 0:
                break
            shift += 7
        return result

    def _deserialize_node(self) -> QuadTreeNode:
        """Recursively deserialize a node."""
        tag = self._read_byte()

        if tag == TAG_INTERNAL:
            # Internal node
            presence = self._read_byte()
            children: List[Optional[QuadTreeNode]] = []

            for i in range(4):
                if presence & (1 << i):
                    child = self._deserialize_node()
                    children.append(child)
                else:
                    children.append(None)

            return InternalNode(children)
        else:
            # Leaf node
            if self.use_varint:
                country_id = self._read_varint()
            else:
                if tag == 0xFF:
                    # Extended format
                    lo = self._read_byte()
                    hi = self._read_byte()
                    country_id = lo | (hi << 8)
                else:
                    country_id = tag - TAG_LEAF_BASE

            return LeafNode(country_id)


def serialize_tree(tree: QuadTree, compress: bool = True) -> bytes:
    """
    Serialize a quadtree to bytes, optionally with compression.

    Args:
        tree: QuadTree to serialize
        compress: Whether to apply zlib compression

    Returns:
        Serialized (and optionally compressed) bytes
    """
    serializer = TreeSerializer(use_varint=True)
    data = serializer.serialize(tree)

    if compress:
        data = zlib.compress(data, level=9)

    return data


def deserialize_tree(
    data: bytes,
    bounds: Rectangle,
    precision: int,
    compressed: bool = True
) -> QuadTree:
    """
    Deserialize a quadtree from bytes.

    Args:
        data: Serialized tree bytes
        bounds: Bounding rectangle
        precision: Quantization precision
        compressed: Whether data is zlib compressed

    Returns:
        Deserialized QuadTree
    """
    if compressed:
        data = zlib.decompress(data)

    deserializer = TreeDeserializer(use_varint=True)
    return deserializer.deserialize(data, bounds, precision)


def serialize_country_table(country_codes: Dict[int, str], code_length: int = 3) -> bytes:
    """
    Serialize country code mapping to bytes.

    Format:
    - 1 byte: code length (2 or 3)
    - 2 bytes: number of entries (little-endian)
    - For each entry:
      - 2 bytes: country_id (little-endian)
      - N bytes: ISO code as ASCII characters (padded with spaces if needed)

    Args:
        country_codes: Mapping from country_id to ISO code
        code_length: Length of ISO codes (2 for alpha-2, 3 for alpha-3)

    Returns:
        Serialized bytes
    """
    if code_length not in (2, 3):
        raise ValueError("code_length must be 2 or 3")

    buffer = bytearray()

    # Code length
    buffer.append(code_length)

    # Number of entries
    buffer.extend(struct.pack("<H", len(country_codes)))

    # Entries sorted by ID
    for country_id in sorted(country_codes.keys()):
        code = country_codes[country_id]
        # Pad or truncate to exact length
        code = code[:code_length].ljust(code_length)

        buffer.extend(struct.pack("<H", country_id))
        buffer.extend(code.encode("ascii"))

    return bytes(buffer)


def bytes_to_cpp_array(data: bytes, name: str, line_width: int = 80) -> str:
    """
    Convert bytes to C++ array literal.

    Args:
        data: Bytes to convert
        name: Variable name
        line_width: Maximum line width

    Returns:
        C++ code as string
    """
    lines = []
    lines.append(f"static constexpr unsigned char {name}[] = {{")

    # Convert bytes to hex strings
    hex_values = [f"0x{b:02x}" for b in data]

    # Group into lines
    current_line = "    "
    for i, hv in enumerate(hex_values):
        addition = hv + ("," if i < len(hex_values) - 1 else "")
        if len(current_line) + len(addition) + 1 > line_width:
            lines.append(current_line)
            current_line = "    " + addition
        else:
            if current_line.strip():
                current_line += " " + addition
            else:
                current_line += addition

    if current_line.strip():
        lines.append(current_line)

    lines.append("};")
    lines.append(f"static constexpr size_t {name}_size = {len(data)};")

    return "\n".join(lines)
