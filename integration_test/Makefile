# Makefile for integration test
# Usage: make HEADER=path/to/country_lookup.hpp TARGET=country_lookup_p0

CXX ?= clang++
CXXFLAGS ?= -std=c++17 -O2 -Wall -Wextra

# Header file path (required)
HEADER ?=

# Output binary name (can include precision, e.g., country_lookup_p0)
TARGET ?= country_lookup_test

# Whether to link zlib (set to 0 for no compression)
WITH_ZLIB ?= 1

ifeq ($(WITH_ZLIB),1)
LDFLAGS ?= -lz
else
LDFLAGS ?=
endif

.PHONY: all clean check

all: $(TARGET)

$(TARGET): main.cpp $(HEADER)
	@if [ -z "$(HEADER)" ]; then \
		echo "Error: HEADER not specified. Use: make HEADER=path/to/header.hpp"; \
		exit 1; \
	fi
	$(CXX) $(CXXFLAGS) -I$(dir $(HEADER)) -include $(HEADER) -o $@ main.cpp $(LDFLAGS)

clean:
	rm -f country_lookup_test country_lookup_p*

check:
	@echo "Checking toolchain..."
	@$(CXX) --version | head -1
	@echo "Toolchain OK"
