#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
CCACHE_DISABLE=1 cmake -S . -B build
CCACHE_DISABLE=1 cmake --build build -j
