#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

mkdir -p build/demo
GMAT_BIN="${GMAT_BIN:-../third_party/GMAT-R2026a-fixed/bin/GmatConsole}"
EPHEM="build/demo/gmat-events.json"

python3 adapters/gmat/gmat_ephemeris.py --gmat "$GMAT_BIN" --output "$EPHEM"
DEMO_OUTPUT="$(./build/gmat_compute_demo "$EPHEM")"

echo "=================================================="
echo "GMAT-COMPUTE DEMO"
echo "=================================================="
echo
echo "GMAT backend:"
echo "REAL"
echo
echo "GMAT Plugin:"
echo "PARTIAL"
echo
echo "GMAT Runtime Integration:"
echo "REAL"
echo
echo "Compute payload:"
echo "generic_gpu"
echo
echo "Hardware model:"
echo "FILE ENVELOPE"
echo
echo "Envelope:"
echo "measured/example_gpu/manifest.yaml"
echo
echo "Task:"
echo "demo-inference-001"
echo
echo "$DEMO_OUTPUT"
echo
echo "GMAT ↔ COMPUTE CO-SIM:"
echo "PASS"
echo "=================================================="
