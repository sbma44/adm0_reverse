# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Build & Development Commands

```bash
# Install dependencies
uv sync --dev

# Run tests
uv run python -m pytest tests/ -v

# Run a single test file
uv run python -m pytest tests/test_quantize.py -v

# Run a specific test
uv run python -m pytest tests/test_builder.py::TestQuadTreeBuilder::test_uniform_oracle -v

# Generate a test header (precision 0 for fast build)
uv run python -m adm0_reverse.cli build -p 0 -o output.hpp

# Generate with mock oracle (no shapefile needed)
uv run python -m adm0_reverse.cli build -p 0 --mock-oracle rectangle -o output.hpp

# Show grid statistics
uv run python -m adm0_reverse.cli stats -p 2

# Run the CLI
uv run python main.py
```

## Architecture

The project generates header-only C++ files for country lookup using a sparse quadtree.

### Core Modules (`src/adm0_reverse/`)

- **quantize.py**: Converts WGS84 (lat, lon) to integer grid indices (ilat, ilon) at a given precision
- **quadtree.py**: Rectangle, LeafNode, InternalNode, and QuadTree data structures
- **oracle.py**: Oracle protocol and mock implementations (MockRectangleOracle, MockCircleOracle, etc.)
- **duckdb_oracle.py**: Real oracle using DuckDB spatial extension with Natural Earth shapefiles
- **builder.py**: Builds quadtree using prove-or-split strategy with sampling and brute-force verification
- **serialize.py**: Binary serialization/deserialization of quadtree, zlib compression support
- **codegen.py**: Generates C++ header files with embedded quadtree and lookup functions
- **cli.py**: Command-line interface (build, stats, test commands)

### Key Concepts

- **Precision (p)**: Decimal places. Q = 10^p. Grid has 360×Q longitude points and 180×Q latitude points
- **Quadtree children order**: NW (0), NE (1), SW (2), SE (3)
- **Oracle**: Function(ilat, ilon) → country_id. Real oracle uses DuckDB with Natural Earth ADM0 shapefile; mock oracles available for testing

### Coordinate System

- `ilat`: Latitude index, range [0, 180×Q], where 0 = south pole, 180×Q = north pole
- `ilon`: Longitude index, range [0, 360×Q], where 0 = -180°, 360×Q = +180°
- QuadTree.lookup(ilat, ilon) takes latitude index first

---

# Design Doc: Header-Only Country Lookup for Quantized Lat/Lon Using a Sparse Quadtree

1. Overview

Goal

Produce a python project capable of producing a header-only C++ include that maps a WGS84 (lat, lon) point to a country identifier (e.g., ISO-3166 code) with correctness defined at a specified decimal precision p (e.g., 2 or 4). Each generated header supports exactly one precision.

Tools

An oracle will be made available at a later date (see below) but is not presently ready. Build the tests and project code necessary to create a reusable Python tool that builds header-only C++ library files to achieve the tasks described in this file, while allowing for its input parameters (e.g. precision) to be adjusted with each run.

Use the `uv` package manager for all relevant python-related tasks.

Key idea

Convert (lat, lon) into a quantized integer grid point at precision p and answer the country query for that discrete point using a sparse refinement quadtree over the integer grid. The quadtree refines only near borders/coastlines.

Non-goals
	•	Multiple projections or datums (WGS84 only)
	•	Multiple precisions in one file
	•	Sub-country admin levels (ADM0 only)
	•	“True continuous geometry” exactness; correctness is on the quantized lattice only

⸻

2. Definitions

Precision and quantization

Let p be decimal places and Q = 10^p.

Define quantization to integer indices:
	•	ilon ∈ [0, 360*Q] representing longitude in [-180, +180]
	•	ilat ∈ [0, 180*Q] representing latitude in [-90, +90]

Quantization rule (must be consistent between build and runtime):
	•	ilon = round((lon + 180) * Q)
	•	ilat = round((lat + 90)  * Q)

Clamping:
	•	Clamp lon to [-180, 180], lat to [-90, 90] before quantizing
	•	Clamp ilon and ilat into range endpoints afterward

Correctness contract

For a generated header at precision p:

lookup(lat, lon) returns the country for the quantized point (ilat, ilon) exactly matching the offline oracle on that grid.

This is the only correctness claim.

⸻

3. High-Level Architecture

Components
	1.	Offline Builder (Python/C++ tooling)
	•	Inputs: authoritative ADM0 oracle function oracle(ilat, ilon) -> countryId
	•	Output: a single C++ header containing:
	•	compressed quadtree blob
	•	minimal decoder + query function
	•	countryId → ISO code table (optional, or return integer ID)
	2.	Runtime Header (C++ header-only)
	•	country_id lookup(double lat, double lon)
	•	std::string_view lookup_iso(double lat, double lon) (optional)

Data model
	•	A quadtree over the integer coordinate rectangle:
	•	X axis: ilon in [0..Xmax], where Xmax = 360*Q
	•	Y axis: ilat in [0..Ymax], where Ymax = 180*Q
	•	Each leaf stores exactly one countryId.

Encoding strategy

The header embeds a compact serialized tree blob. The runtime decoder traverses the tree directly from the blob (no pointers). Compression is applied offline.

⸻

4. Quadtree Design

Node semantics

Each node represents a rectangle in integer coordinates:
	•	[x0, x1] inclusive on longitude index
	•	[y0, y1] inclusive on latitude index

Node types:
	•	Leaf: all points in the rectangle map to a single countryId
	•	Internal: subdivides into 4 children (quadrants)

Child order: fixed and consistent between builder and decoder (e.g., NW, NE, SW, SE). The exact order is implementation-defined but must be stable.

Subdivision rule

Given rectangle (x0..x1, y0..y1):
	•	If x0 == x1 and y0 == y1, it must be a leaf (single point).
	•	Otherwise define midpoints:
	•	xm = (x0 + x1) // 2
	•	ym = (y0 + y1) // 2
	•	Children rectangles are:
	•	(x0..xm, ym+1..y1), (xm+1..x1, ym+1..y1),
	•	(x0..xm, y0..ym), (xm+1..x1, y0..ym)
	•	Handle empty ranges when xm == x1 or ym == y1 by suppressing or defining degenerate children consistently (preferred: ensure builder/decoder follow the same “degenerate split” convention, typically by making the rectangle split only when the axis length > 0).

Recommendation: only split along axes that have length > 0, but preserve a deterministic structure (e.g., still emit 4 children, some marked as empty and treated as inheriting/ignored). Alternatively, constrain rectangles so both dimensions always split until singletons; simplest is to always split both axes and allow 1-point-wide strips to produce degenerate children.

⸻

5. Builder Algorithm

Inputs
	•	Precision p (integer)
	•	Oracle function:
	•	oracle(ilat, ilon) -> countryId
	•	This oracle must match the desired ADM0 definition (e.g., Natural Earth / OSM-derived / proprietary).
	•	Tuning parameters (per precision):
	•	SAMPLE_K : number of interior samples (e.g., 8–32)
	•	BRUTE_FORCE_THRESHOLD : maximum number of lattice points in a rectangle to brute force (e.g., 4096–65536)
	•	MAX_DEPTH : safety cap (should be ≥ log2(max dimension)+a bit)
	•	RNG seed for sampling determinism

Core routine: build_node(rect) -> node

The builder uses a “prove-or-split” strategy.

Step A: Fast inconsistency detection (sampling)
	1.	Evaluate oracle at a deterministic set of points in the rectangle:
	•	corners (up to 4)
	•	center
	•	a few stratified points (e.g., at 1/3 and 2/3)
	•	optional: K pseudo-random points generated deterministically from rect coords
	2.	If any sampled points disagree in countryId, mark as mixed ⇒ split.

Step B: Proving uniformity
If all samples agree (candidate c):
	•	If rectangle point count N = (x1-x0+1)*(y1-y0+1) <= BRUTE_FORCE_THRESHOLD:
	•	brute force all lattice points in the rectangle; if all == c, emit leaf; else split.
	•	Else:
	•	Do not trust samples alone; split (conservative) OR apply additional heuristics:
	•	Optional heuristic: if rectangle is entirely far from borders (not available unless oracle can provide border distance), skip.
	•	Recommended baseline: split when above threshold even if samples agree, to maintain correctness.

This ensures correctness because leaves are only emitted when uniformity has been verified exhaustively for that region’s lattice points.

Step C: Recursion
Split into children, recursively build each child.

Termination and safety
	•	Always terminate at single lattice point rectangles (guaranteed leaf).
	•	Include MAX_DEPTH guard:
	•	If exceeded (should not happen), fallback to brute forcing at current rectangle (or split until singleton).
	•	Keep deterministic output:
	•	deterministic sampling
	•	stable child ordering
	•	stable tie-handling at quantization

⸻

6. Expected Complexity

Runtime
	•	O(depth) node visits, typically ~16–24 for p=2..4 depending on refinement.
	•	Bitstream read and midpoint comparisons only.

Build time
	•	Dominated by oracle calls near borders.
	•	Worst-case brute force is bounded by BRUTE_FORCE_THRESHOLD times number of “near-border” rectangles that reach that size.

Size
	•	Tree size scales with border complexity, not global area.
	•	Secondary compression typically yields large gains because subtrees repeat and leaf IDs are low-entropy.

⸻

7. Data Serialization (Conceptual)

Tree blob

Serialized quadtree in a compact format suitable for inclusion in a header, plus optional compression.

Conceptually stored data:
	•	Node structure in preorder:
	•	tag: leaf vs internal
	•	if leaf: countryId
	•	if internal: children nodes

Country table
	•	countryId -> ISO_A2 or ISO numeric code
	•	Embedded as a compact string table (e.g., concatenated 2-char codes) or array of structs.

Compression choice
	•	Offline compress tree blob and embed compressed bytes.
	•	Runtime decompression into a static buffer or decode-on-the-fly.
	•	If decode-on-the-fly is complex, decompress once into a static buffer on first use.

⸻

8. C++ Header Runtime Design

Public API
	•	uint16_t country_id(double lat, double lon);
	•	Optional: std::string_view country_iso2(double lat, double lon);

Steps at runtime
	1.	Clamp and quantize (lat, lon) to (ilat, ilon) using the defined rules.
	2.	Ensure tree blob is available (decompressed if necessary).
	3.	Traverse quadtree from root using (ilat, ilon):
	•	At internal node, compute midpoints for the current rect and choose child.
	•	Continue until leaf; return leaf countryId.

Memory model
	•	Header-only, no external resources.
	•	Decompression buffer as static storage with one-time init (thread-safe).
	•	Alternatively, embed uncompressed blob for minimal runtime code at cost of larger header.

⸻

9. Validation Plan

Unit tests (offline and C++)
	•	Quantization edge cases:
	•	poles, dateline, rounding boundaries
	•	Spot checks against oracle:
	•	random points across globe
	•	dense sampling near known borders
	•	Determinism tests:
	•	same inputs produce identical header bytes across runs (given same seed/oracle)

Correctness verification (offline)
	•	For each leaf rectangle emitted, store builder-time assertion:
	•	leaf was produced only after exhaustive verification within threshold
	•	End-to-end verification:
	•	Sample millions of random lat/lon, compare runtime lookup vs oracle after quantization

⸻

10. Risk / Edge Cases

Dateline and longitude wrap
	•	Decide whether lon=180 maps to ilon=Xmax and lon=-180 maps to 0, and keep consistent.
	•	Some datasets treat dateline borders specially; correctness is only with respect to the oracle after quantization.

Micro-polygons / tiny islands
	•	At higher precision, small islands can force deeper refinement.
	•	Mitigation: increase BRUTE_FORCE_THRESHOLD modestly; let refinement continue to singleton where necessary.

Disputed territories / definitions
	•	The oracle defines the truth. The system encodes whatever oracle returns.
	•	Document the oracle dataset version in header comments.

⸻

11. Builder Implementation Notes

Deterministic sampling

For large rectangles, pick pseudo-random sample points using a PRNG seeded from (x0,y0,x1,y1,globalSeed) to ensure reproducibility.

Brute force threshold tuning
	•	p=2: threshold can be larger (fewer total points)
	•	p=4: threshold should remain moderate to avoid huge brute-force calls; rely on splitting more.

Parallelism

Building can be parallelized by subdividing top-level quadrants and merging serialized subtrees.

⸻

12. Deliverables

For each precision p:
	•	country_lookup_p{p}.hpp
	•	contains:
	•	metadata: oracle source/version, build date, precision
	•	compressed quadtree blob
	•	runtime lookup API
	•	optional ISO code mapping

Offline tools:
	•	build_country_header.py (or C++ tool)
	•	takes p, oracle dataset path, thresholds, seed
	•	outputs header and validation report

⸻

13. Acceptance Criteria
	•	Correctness: For any (lat, lon), lookup(lat, lon) matches oracle(round(lat,p), round(lon,p)) exactly.
	•	Single-header: No external files at runtime.
	•	Size: Header remains within agreed limits per precision (target to be determined).
	•	Performance: Lookup runs in microseconds with predictable runtime (no polygon scanning).

⸻

14. Open Implementation Choices (to finalize during implementation)
	•	Exact rounding convention (round half away from zero vs banker’s rounding) — must be fixed.
	•	Handling of degenerate splits (rectangles with width or height = 0) — must be consistent.
	•	Compression choice and decompressor footprint (LZ4 vs none vs miniz).
	•	Return type: integer ID only vs ISO string mapping.