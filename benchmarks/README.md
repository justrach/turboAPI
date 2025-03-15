# Web Framework Performance Benchmark

A comprehensive benchmarking tool for comparing the performance of Python web frameworks, with a focus on validation and serialization operations.

## Overview

This tool allows you to compare the performance of multiple web frameworks including:
- TurboAPI (built on Starlette with Satya validation)
- FastAPI (built on Starlette with Pydantic validation)
- Starlette (raw, without validation)
- Flask (with manual validation)

The benchmark measures both request handling time and validation performance across different payload complexities, providing detailed metrics and visualizations to help you understand the performance characteristics of each framework. Recent benchmarks show that TurboAPI outperforms FastAPI by approximately 45-50% in common API scenarios.

## Features

- **Multi-Framework Support**: Benchmark any combination of TurboAPI, FastAPI, Starlette, and Flask
- **Configurable Test Scenarios**: Three complexity levels (small, medium, large) with nested data structures
- **Operation Types**: Tests both GET and POST operations
- **Comprehensive Metrics**: Measures average, median, minimum, maximum, and standard deviation of response times
- **Parallel Request Testing**: Configurable concurrency levels to simulate real-world load
- **Rich Visualizations**: Generate detailed bar charts, summary plots, and performance improvement visualizations
- **Data Export**: Save results as JSON and CSV for further analysis

## Installation

1. Clone the repository:
   ```bash
   git clone https://github.com/yourusername/tatsat.git
   cd tatsat
   ```

2. Install the package and dependencies:
   ```bash
   pip install -e .
   pip install starlette fastapi flask uvicorn aiohttp matplotlib pydantic
   ```

## Usage

Run the benchmark from the project root directory:

```bash
python examples/comprehensive_benchmark.py [OPTIONS]
```

Or run specific framework comparison benchmarks:

```bash
python examples/turboapi_fastapi_benchmark.py [OPTIONS]
```

### Command-line Options

| Option | Description | Default |
|--------|-------------|---------|
| `--iterations` | Number of iterations for each test | 200 |
| `--concurrency` | Number of concurrent requests | 10 |
| `--output-dir` | Directory for results and visualizations | "benchmarks/results" |
| `--no-plot` | Disable plot generation | False |
| `--no-save` | Disable saving results to file | False |
| `--frameworks` | Comma-separated list of frameworks to benchmark | "all" |

### Examples

1. Run a benchmark with default settings (all frameworks):
   ```bash
   python examples/comprehensive_benchmark.py
   ```

2. Compare just TurboAPI and FastAPI:
   ```bash
   python examples/turboapi_fastapi_benchmark.py
   ```

3. Run an intensive benchmark with high iteration count and concurrency:
   ```bash
   python examples/comprehensive_benchmark.py --iterations 1000 --concurrency 50
   ```

4. Run a quick test with no plots or saved results:
   ```bash
   python examples/comprehensive_benchmark.py --iterations 50 --no-plot --no-save
   ```

## Output

The benchmark produces:

1. **Console Output**: Shows progress and summary metrics
2. **Visualization Files**: 
   - Per-scenario comparison charts
   - Summary comparison across all scenarios
   - Performance improvement charts
3. **Data Files**:
   - `benchmark_results.json`: Complete benchmark data
   - `benchmark_summary.csv`: Tabular summary for spreadsheet analysis

All output files are saved in the directory specified by `--output-dir`.

## Interpreting Results

### Performance Metrics

For each framework, scenario, and operation type, the following metrics are calculated:

- **Average Time**: The mean response time across all iterations
- **Median Time**: The middle value of all response times (less affected by outliers)
- **Min/Max Time**: The fastest and slowest response times
- **Standard Deviation**: Indicates consistency of response times

### Visualization Types

1. **Bar Charts**: Compare metrics for each framework within a specific scenario
2. **Summary Plots**: Show average performance across all scenarios for each framework
3. **Improvement Charts**: Visualize TurboAPI's performance improvement (or regression) compared to other frameworks as percentages

## Test Scenarios

The benchmark includes three test scenarios with increasing complexity:

1. **Small Item**: Basic object with simple properties
2. **Medium Item**: Object with nested structures and arrays
3. **Large Item**: Complex object with deeply nested structures, arrays of objects, and varied data types

These scenarios test both serialization performance and validation capabilities.

## How It Works

The benchmark:

1. Initializes server instances for each framework
2. Sends HTTP requests with identical payloads to each server
3. Measures response times with microsecond precision
4. Runs a configurable number of warmup requests before actual benchmarking
5. Processes and analyzes the collected timing data
6. Generates visualizations and exports results

## Contributing

Contributions are welcome! If you'd like to add support for additional frameworks or enhance the benchmark:

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add some amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## License

This project is licensed under the MIT License - see the LICENSE file for details.
