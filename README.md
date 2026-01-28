# adm0-reverse

Generate header-only C++ files for fast country lookup from latitude/longitude coordinates using a sparse quadtree. Useful for integrating "what country am I in?" functionality into your app with no need for connectivity and minimal impact on storage.

## Overview

This tool produces a single C++ header file that maps WGS84 (lat, lon) coordinates to country identifiers (ISO 3166-1 alpha-3 codes). Correctness is defined at a specified decimal precision `p`, where the quantized grid has `360 × 10^p` longitude points and `180 × 10^p` latitude points.

Key features:
- **Header-only**: No external dependencies at runtime
- **Fast lookups**: O(log n) tree traversal, typically 5-10 microseconds per lookup
- **Compact**: Tree refines only near borders/coastlines, not over oceans or country interiors
- **Deterministic**: Same inputs produce identical output across runs

## Installation

```bash
# Install dependencies
uv sync --dev
```

### Data Setup

Download the Natural Earth ADM0 shapefile and place it in the `data/` directory:

```bash
mkdir -p data
cd data
curl -LO https://naciscdn.org/naturalearth/10m/cultural/ne_10m_admin_0_countries.zip
unzip ne_10m_admin_0_countries.zip
```

The tool expects `ne_10m_admin_0_countries_tlc.shp` by default, but you can specify a different file with `--shapefile`.

## Usage

### Generate a C++ Header

```bash
# Generate header at precision 2 (default)
uv run python -m adm0_reverse.cli build -p 2 -o country_lookup.hpp

# Generate with compression disabled (larger file, no zlib dependency)
uv run python -m adm0_reverse.cli build -p 2 -o country_lookup.hpp --no-compress

# Use a mock oracle for testing (no shapefile needed)
uv run python -m adm0_reverse.cli build -p 0 --mock-oracle simple -o test.hpp
```

### Show Grid Statistics

```bash
uv run python -m adm0_reverse.cli stats -p 2
```

### CLI Options

```
build options:
  -p, --precision       Decimal precision (0-4, default: 2)
  -o, --output          Output file path
  --no-compress         Disable zlib compression
  --sample-k            Sample points for uniformity check (default: 16)
  --brute-force-threshold  Max points to brute-force verify (default: 4096)
  --namespace           C++ namespace (default: adm0)
  --mock-oracle         Use mock oracle: rectangle, circle, or simple
  --data-dir            Directory containing shapefile
  --shapefile           Shapefile name
```

## Using the Generated Header

```cpp
#include "country_lookup.hpp"

int main() {
    // Get country ID (integer)
    uint16_t id = adm0::country_id(48.8566, 2.3522);  // Paris

    // Get ISO 3166-1 alpha-3 code
    std::string_view iso = adm0::country_iso(48.8566, 2.3522);  // "FRA"

    // Reverse lookup: ISO code to country ID
    uint16_t usa_id = adm0::country_id_from_iso("USA");

    return 0;
}
```

Compile with:
```bash
# With compression (default)
clang++ -std=c++17 -O2 -o myapp myapp.cpp -lz

# Without compression (if generated with --no-compress)
clang++ -std=c++17 -O2 -o myapp myapp.cpp
```

## Development

### Run Tests

```bash
# Run all unit tests
uv run python -m pytest tests/ -v

# Run a specific test file
uv run python -m pytest tests/test_builder.py -v

# Run a specific test
uv run python -m pytest tests/test_builder.py::TestQuadTreeBuilder::test_uniform_oracle -v
```

### Integration Tests

Integration tests build actual C++ binaries and verify consistency against the Python oracle.

```bash
# Run integration tests (precision 0 only, ~2 minutes)
uv run python -m pytest tests/test_integration.py -v

# Run with specific precisions (comma-separated)
ADM0_TEST_PRECISION=1 uv run python -m pytest tests/test_integration.py -v
ADM0_TEST_PRECISION=0,1,2 uv run python -m pytest tests/test_integration.py -v
```

**Note**: Higher precisions require significantly more time due to increased oracle calls:
- Precision 0: ~40 seconds build time
- Precision 1: Several minutes
- Precision 2+: May take considerable time

### Project Structure

```
src/adm0_reverse/
├── quantize.py      # WGS84 ↔ grid coordinate conversion
├── quadtree.py      # Rectangle, LeafNode, InternalNode, QuadTree
├── oracle.py        # Oracle protocol and mock implementations
├── duckdb_oracle.py # Real oracle using DuckDB spatial extension
├── builder.py       # Quadtree builder with prove-or-split strategy
├── serialize.py     # Binary serialization with zlib compression
├── codegen.py       # C++ header generation
└── cli.py           # Command-line interface

integration_test/
├── Makefile         # Build rules for test binary
└── main.cpp         # C++ test program (single, batch, benchmark modes)

tests/
├── test_quantize.py
├── test_quadtree.py
├── test_builder.py
├── test_serialize.py
├── test_codegen.py
├── test_duckdb_oracle.py
└── test_integration.py
```

## How It Works

### Quantization

Coordinates are mapped to integer grid indices:
- `ilon = round((lon + 180) × 10^p)` → range [0, 360 × 10^p]
- `ilat = round((lat + 90) × 10^p)` → range [0, 180 × 10^p]

### Quadtree Building

The builder uses a "prove-or-split" strategy:

1. **Sample**: Check corners, center, and random interior points
2. **If samples disagree**: Split into 4 children (NW, NE, SW, SE)
3. **If samples agree**: Brute-force verify all points if below threshold, otherwise split
4. **Emit leaf**: Only when uniformity is exhaustively verified

This ensures correctness while keeping the tree sparse—large uniform regions (oceans, country interiors) become single leaf nodes.

### Serialization

The quadtree is serialized to a compact binary format:
- Varint encoding for node tags and country IDs
- Optional zlib compression (typically 60-80% size reduction)
- Embedded as a C++ byte array in the header

## Precision Guidelines

| Precision | Grid Resolution | Total Points | Typical Use Case |
|-----------|-----------------|--------------|------------------|
| 0 | 1° | 65K | Coarse regional lookup |
| 1 | 0.1° (~11km) | 6.5M | City-level accuracy |
| 2 | 0.01° (~1.1km) | 650M | Neighborhood-level |
| 3 | 0.001° (~110m) | 65B | Street-level |

Higher precision increases build time and header size but provides finer resolution near borders.