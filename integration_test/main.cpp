/**
 * Integration test program for country lookup.
 *
 * Usage:
 *   ./country_lookup_test <lat> <lon>           - Single lookup
 *   ./country_lookup_test --batch               - Batch mode (reads lat,lon pairs from stdin)
 *   ./country_lookup_test --benchmark <count>   - Benchmark mode
 *
 * Output format:
 *   Single: <country_id> <iso_code>
 *   Batch:  <country_id> per line
 */

#include <iostream>
#include <sstream>
#include <string>
#include <chrono>
#include <random>
#include <cstdlib>

// The header is included via -include flag in Makefile
// It provides: adm0::country_id(lat, lon) and adm0::country_iso(lat, lon)

int main(int argc, char* argv[]) {
    if (argc < 2) {
        std::cerr << "Usage: " << argv[0] << " <lat> <lon>" << std::endl;
        std::cerr << "       " << argv[0] << " --batch" << std::endl;
        std::cerr << "       " << argv[0] << " --benchmark <count>" << std::endl;
        return 1;
    }

    std::string mode = argv[1];

    if (mode == "--batch") {
        // Batch mode: read lat,lon pairs from stdin, output country_id
        std::string line;
        while (std::getline(std::cin, line)) {
            double lat, lon;
            char comma;
            std::istringstream iss(line);
            if (iss >> lat >> comma >> lon) {
                uint16_t id = adm0::country_id(lat, lon);
                std::cout << id << std::endl;
            }
        }
        return 0;
    }

    if (mode == "--benchmark") {
        if (argc < 3) {
            std::cerr << "Usage: " << argv[0] << " --benchmark <count>" << std::endl;
            return 1;
        }

        int count = std::atoi(argv[2]);
        if (count <= 0) {
            std::cerr << "Invalid count" << std::endl;
            return 1;
        }

        // Generate random points
        std::mt19937 rng(42);  // Fixed seed for reproducibility
        std::uniform_real_distribution<double> lat_dist(-90.0, 90.0);
        std::uniform_real_distribution<double> lon_dist(-180.0, 180.0);

        // Warmup
        for (int i = 0; i < 1000; ++i) {
            adm0::country_id(lat_dist(rng), lon_dist(rng));
        }

        // Reset RNG for actual benchmark
        rng.seed(42);

        // Benchmark
        auto start = std::chrono::high_resolution_clock::now();

        volatile uint16_t result = 0;  // Prevent optimization
        for (int i = 0; i < count; ++i) {
            double lat = lat_dist(rng);
            double lon = lon_dist(rng);
            result = adm0::country_id(lat, lon);
        }

        auto end = std::chrono::high_resolution_clock::now();
        auto duration = std::chrono::duration_cast<std::chrono::microseconds>(end - start);

        double total_ms = duration.count() / 1000.0;
        double per_lookup_ns = (duration.count() * 1000.0) / count;

        std::cout << "Lookups: " << count << std::endl;
        std::cout << "Total time: " << total_ms << " ms" << std::endl;
        std::cout << "Per lookup: " << per_lookup_ns << " ns" << std::endl;
        std::cout << "Throughput: " << (count / (total_ms / 1000.0)) << " lookups/sec" << std::endl;

        return 0;
    }

    // Single lookup mode
    if (argc < 3) {
        std::cerr << "Usage: " << argv[0] << " <lat> <lon>" << std::endl;
        return 1;
    }

    double lat = std::atof(argv[1]);
    double lon = std::atof(argv[2]);

    uint16_t id = adm0::country_id(lat, lon);
    std::string_view iso = adm0::country_iso(lat, lon);

    std::cout << id << " " << (iso.empty() ? "---" : std::string(iso)) << std::endl;

    return 0;
}
