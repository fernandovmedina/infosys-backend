#!/usr/bin/env bash

# Generate a reproducible fixture matrix for detector development.
# Run from anywhere; paths are resolved relative to the backend repository.
set -Eeuo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$repo_root"
matrix_root="$repo_root/app/estate_generator/output/fixture_matrix"

if [[ "${SKIP_UV_SYNC:-0}" != "1" ]]; then
  uv sync --all-groups
fi

generate() {
  local category="$1"
  local label="$2"
  shift 2
  local run_output run_path
  echo
  echo "=== ${label} ==="
  echo "+ uv run python -m evaluation.estate_generator.cli $*"
  run_output="$(uv run python -m evaluation.estate_generator.cli "$@")"
  printf '%s\n' "$run_output"
  run_path="$(printf '%s\n' "$run_output" | sed -n 's/^Generated .* estate run at \(.*\); private sidecars:.*$/\1/p')"
  if [[ -z "$run_path" || ! -d "$run_path" ]]; then
    echo "Could not locate generated run directory for ${label}" >&2
    exit 1
  fi
  mkdir -p "$matrix_root/$category"
  mv "$run_path" "$matrix_root/$category/"
  echo "Categorized fixture: $matrix_root/$category/$(basename "$run_path")"
}

# Clean baseline: no planted schemes and no decoys.
generate "clean/no_schemes" "clean" \
  --seed 1001 \
  --scheme-count 0 \
  --decoy-count 0

# Clean business activity with realistic suspicious-looking controls/events,
# but no planted fraud. The decoys are labeled only in the private sidecar.
generate "clean/with_decoys" "clean-with-decoys" \
  --seed 1002 \
  --scheme-count 0 \
  --decoy-count 5

# One fixture per fraud family, with no decoys. This isolates each detector
# behavior and makes failures easy to diagnose.
generate "isolated/phantom_vendor" "phantom-vendor" \
  --seed 1101 \
  --scheme-type phantom_vendor \
  --decoy-count 0
generate "isolated/kickback" "kickback" \
  --seed 1102 \
  --scheme-type kickback \
  --decoy-count 0
generate "isolated/round_tripping" "round-tripping" \
  --seed 1103 \
  --scheme-type round_tripping \
  --decoy-count 0
generate "isolated/threshold_splitting" "threshold-splitting" \
  --seed 1104 \
  --scheme-type threshold_splitting \
  --decoy-count 0
generate "isolated/revenue_inflation" "revenue-inflation" \
  --seed 1105 \
  --scheme-type revenue_inflation \
  --decoy-count 0

# Mixed fixture: the seed-driven default selects a deterministic 0..5 scheme
# subset. Use an explicit count when you need the exact number of schemes.
generate "mixed/seed_driven" "mixed-seed-driven" \
  --seed 1204 \
  --decoy-count 5

generate "mixed/three_schemes_with_decoys" "mixed-three-schemes-with-decoys" \
  --seed 1202 \
  --scheme-count 3 \
  --decoy-count 5

# Maximum challenge density: all five schemes plus decoys.
generate "all_five/with_decoys" "all-five-with-decoys" \
  --seed 1301 \
  --all-five \
  --decoy-count 5

echo
echo "Fixture matrix generation complete. See $matrix_root/."
