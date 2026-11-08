#!/usr/bin/env bash
# Compatibility entrypoint: the former Variant B deploy now uses TWAP.
set -euo pipefail
exec bash "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/deploy_twap_oracle.sh" "$@"
