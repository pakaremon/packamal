# Package Dynamic Analysis

A comprehensive tool for analyzing packages from various open source ecosystems using dynamic analysis techniques. This project performs runtime analysis of packages to detect potentially malicious behavior, track system calls, monitor network activity, and analyze file operations.

## Overview

Package Dynamic Analysis is designed to analyze packages in isolated sandbox environments, monitoring their behavior during installation, import, and execution phases. The analysis captures:

- **System Calls**: File operations, command executions, and system interactions via `strace`
- **Network Activity**: DNS queries and network connections via packet capture
- **File Operations**: Reads, writes, and deletions
- **Execution Logs**: Module execution and symbol tracking

## Supported Ecosystems

The following package ecosystems are currently supported:

- **PyPI** (`pypi`) - Python packages
- **npm** (`npm`) - Node.js packages
- **RubyGems** (`rubygems`) - Ruby packages
- **Packagist** (`packagist`) - PHP packages (Composer)
- **Crates.io** (`crates.io`) - Rust packages
- **Maven** (`maven`) - Java packages
- **Wolfi** (`wolfi`) - Wolfi Linux packages

## Architecture

The project consists of several key components:

### Components

1. **Analysis Image** (`cmd/analyze/`) - Main analysis runner that orchestrates static and dynamic analysis
2. **Sandboxes** (`sandboxes/`) - Containerized environments for safe package execution
   - `dynamicanalysis/` - Dynamic analysis sandbox with monitoring tools
   - `staticanalysis/` - Static analysis sandbox
3. **Scheduler** (`cmd/scheduler/`) - Kubernetes service that schedules analysis jobs from package feeds
4. **Worker** (`cmd/worker/`) - Processes analysis jobs from the queue

### Analysis Phases

Dynamic analysis runs through several phases:

1. **Install** - Downloads and installs the package using the ecosystem's package manager
2. **Import** - Attempts to import/load the package modules (where applicable)
3. **Execute** - Runs additional execution phases as defined per ecosystem

## Building Images

### Prerequisites

- Docker
- Make
- Go 1.23.1+ (for building Go components)

### Build Dynamic Analysis Sandbox

Build the dynamic analysis sandbox image:

```bash
cd dynamic-analysis
make build/sandbox/dynamic_analysis
```

Or use the sync command to build and sync with local podman:

```bash
make sync/sandbox/dynamic_analysis
```

### Build Analysis Image

Build the main analysis image that orchestrates the analysis:

```bash
make build/image/analysis
```

### Build All Images

Build all sandbox and analysis images:

```bash
make build
```

This builds:
- Dynamic analysis sandbox
- Static analysis sandbox
- Analysis image
- Scheduler image

### Using Custom Tags

To build images with a specific tag:

```bash
RELEASE_TAG=v1.0.0 make build/sandbox/dynamic_analysis
```

By default, images are tagged as `latest` if no `RELEASE_TAG` is specified.

### Docker Registry

By default, images are tagged with the `pakaremon` registry prefix. To push images to Docker Hub:

```bash
# Push dynamic analysis sandbox
make push/sandbox/dynamic_analysis

# Push analysis image
make push/image/analysis

# Push all production images
make push
```

For production releases:

```bash
RELEASE_TAG=v1.0.0 make cloudbuild
```

## Running Analysis

### Quick Start

The easiest way to run analysis is using the `run_analysis.sh` script:

```bash
./scripts/run_analysis.sh -mode dynamic -ecosystem pypi -package requests
```

### Using the Analysis Script

The `run_analysis.sh` script provides a convenient wrapper around the analysis Docker container.

#### Basic Usage

```bash
./scripts/run_analysis.sh [script-options] -mode <mode> -ecosystem <ecosystem> -package <package> [analysis-options]
```

#### Script Options

- `-dryrun` - Print the command that would be executed without running it
- `-fully-offline` - Completely disable network access for the container (requires `-local` and `-nopull`)
- `-nointeractive` - Disable TTY input (useful for CI/CD)

#### Analysis Modes

- `-mode dynamic` - Run dynamic analysis only
- `-mode static` - Run static analysis only
- `-mode dynamic,static` - Run both analyses

#### Examples

**Analyze a PyPI package (latest version):**
```bash
./scripts/run_analysis.sh -mode dynamic -ecosystem pypi -package requests
```

**Analyze a specific version:**
```bash
./scripts/run_analysis.sh -mode dynamic -ecosystem npm -package express -version 4.18.2
```

**Analyze a local package file:**
```bash
./scripts/run_analysis.sh -mode dynamic -ecosystem pypi -package mypackage -local /path/to/package.tar.gz
```

**Run both static and dynamic analysis:**
```bash
./scripts/run_analysis.sh -mode dynamic,static -ecosystem pypi -package requests
```

**Use locally built sandbox images (without pulling from registry):**
```bash
./scripts/run_analysis.sh -mode dynamic -ecosystem pypi -package requests -nopull
```

**Offline analysis (no network access):**
```bash
./scripts/run_analysis.sh -fully-offline -mode dynamic -ecosystem pypi -package mypackage -local /path/to/package.tar.gz -nopull
```

### Results Directories

By default, results are stored in the following directories:

- **Dynamic analysis results**: `/tmp/results`
- **Static analysis results**: `/tmp/staticResults`
- **File write results**: `/tmp/writeResults`
- **Analyzed packages**: `/tmp/analyzedPackages`
- **Debug logs**: `/tmp/dockertmp`
- **Strace logs**: `/tmp/straceLogs`

You can customize these by setting environment variables:

```bash
RESULTS_DIR=/custom/results STATIC_RESULTS_DIR=/custom/static ./scripts/run_analysis.sh ...
```

### Running Directly with Docker

You can also run the analysis container directly:

```bash
docker run --rm --privileged -it \
  --cgroupns=host \
  -v /var/lib/containers:/var/lib/containers \
  -v /tmp/results:/results \
  -v /tmp/staticResults:/staticResults \
  -v /tmp/writeResults:/writeResults \
  -v /tmp/analyzedPackages:/analyzedPackages \
  pakaremon/analysis:latest \
  analyze \
  -mode dynamic \
  -ecosystem pypi \
  -package requests \
  -dynamic-bucket file:///results/ \
  -static-bucket file:///staticResults/ \
  -file-writes-bucket file:///writeResults/ \
  -analyzed-pkg-bucket file:///analyzedPackages/
```

### Interactive Shell in Sandbox

To get an interactive shell in the dynamic analysis sandbox for debugging:

```bash
docker run --rm --privileged -it --entrypoint /bin/sh -v "$PWD":/app pakaremon/dynamic-analysis:latest
```

## Development

### Running Tests

**Go unit tests:**
```bash
make test_go
```

**Dynamic analysis integration tests:**
```bash
make test_dynamic_analysis
```

This tests analysis across multiple ecosystems:
- npm
- PyPI
- Packagist
- Crates.io
- RubyGems

**Static analysis integration tests:**
```bash
make test_static_analysis
```

### Testing Sandbox Changes

To test local changes to sandboxes:

1. Build and sync the sandbox locally:
   ```bash
   make sync/sandbox/dynamic_analysis
   ```

2. Run analysis with `-nopull` to use local images:
   ```bash
   ./scripts/run_analysis.sh -mode dynamic -ecosystem pypi -package requests -nopull
   ```


## Project Structure

```
dynamic-analysis/
├── cmd/                    # Main application binaries
│   ├── analyze/           # Analysis orchestrator
│   ├── scheduler/         # Job scheduler service
│   ├── worker/            # Analysis worker
│   └── downloader/        # Package downloader utility
├── sandboxes/             # Analysis sandbox environments
│   ├── dynamicanalysis/   # Dynamic analysis sandbox
│   └── staticanalysis/    # Static analysis sandbox
├── internal/              # Internal packages
│   ├── analysis/          # Analysis mode definitions
│   ├── dynamicanalysis/   # Dynamic analysis logic
│   ├── staticanalysis/    # Static analysis logic
│   ├── pkgmanager/        # Package manager implementations
│   ├── sandbox/           # Sandbox management
│   ├── strace/            # System call tracing
│   ├── packetcapture/     # Network packet capture
│   └── dnsanalyzer/       # DNS query analysis
├── pkg/                   # Public packages
│   └── api/               # API definitions
├── scripts/               # Utility scripts
│   ├── run_analysis.sh    # Main analysis runner script
│   └── ...
├── configs/               # Configuration files
├── test/                  # Test files
├── examples/              # Example configurations
└── tools/                 # Additional tools
```

## Configuration

### Environment Variables

- `LOGGER_ENV` - Logger environment (e.g., `production`, `development`)
- `RESULTS_DIR` - Directory for dynamic analysis results (default: `/tmp/results`)
- `STATIC_RESULTS_DIR` - Directory for static analysis results (default: `/tmp/staticResults`)
- `FILE_WRITE_RESULTS_DIR` - Directory for file write results (default: `/tmp/writeResults`)
- `ANALYZED_PACKAGES_DIR` - Directory for saved analyzed packages (default: `/tmp/analyzedPackages`)
- `LOGS_DIR` - Directory for debug logs (default: `/tmp/dockertmp`)
- `STRACE_LOGS_DIR` - Directory for strace logs (default: `/tmp/straceLogs`)
- `CONTAINER_DIR_OVERRIDE` - Override container mount directory (useful in special environments)

### Analysis Options

For a full list of analysis command options:

```bash
docker run --rm pakaremon/analysis:latest analyze -help
```

Key options include:
- `-mode` - Analysis modes to run (static, dynamic, or both)
- `-ecosystem` - Package ecosystem
- `-package` - Package name
- `-version` - Package version (optional)
- `-local` - Path to local package file
- `-nopull` - Don't pull sandbox images from registry
- `-offline` - Disable sandbox network access
- `-sandbox-image` - Override default sandbox image
- `-analysis-command` - Override default analysis script path

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines on contributing to this project.

## License

See [LICENSE](LICENSE) for license information.

## Additional Resources

- [Sandboxes README](sandboxes/README.md) - Detailed information about sandbox environments
- [Examples](examples/README.md) - Example configurations and use cases
