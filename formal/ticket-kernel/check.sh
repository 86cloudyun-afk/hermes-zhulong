#!/bin/sh
set -eu
HERMES_PROOF_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec "${HERMES_PROOF_PYTHON:-python3}" -I "$HERMES_PROOF_DIR/verify.py" "$@"
