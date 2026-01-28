"""
adm0-reverse: Header-only C++ country lookup generator using sparse quadtree.

This package provides tools to generate header-only C++ files that map
WGS84 (lat, lon) coordinates to country identifiers using a sparse quadtree
over a quantized integer grid.
"""

__version__ = "0.1.0"

from .quantize import quantize, dequantize, clamp_coords
from .quadtree import QuadTreeNode, LeafNode, InternalNode, Rectangle
from .builder import QuadTreeBuilder, BuilderConfig
from .serialize import serialize_tree, deserialize_tree
from .codegen import generate_cpp_header
from .duckdb_oracle import DuckDBOracle, create_oracle_from_natural_earth

__all__ = [
    "quantize",
    "dequantize",
    "clamp_coords",
    "QuadTreeNode",
    "LeafNode",
    "InternalNode",
    "Rectangle",
    "QuadTreeBuilder",
    "BuilderConfig",
    "serialize_tree",
    "deserialize_tree",
    "generate_cpp_header",
    "DuckDBOracle",
    "create_oracle_from_natural_earth",
]
