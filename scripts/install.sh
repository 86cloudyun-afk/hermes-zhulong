#!/usr/bin/env bash
# Install zhulong into the active Hermes profile's plugins directory.
set -euo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"
DEST="${HERMES_HOME:-$HOME/.hermes}/plugins/zhulong"
mkdir -p "$DEST"
for f in plugin.yaml __init__.py storage.py sensor.py commands.py calibrate.py reflect.py probes.py autonomy_store.py autonomy_checks.py hermes_runs.py self_model.py autonomy.py runtime_channel.py experience_store.py experience.py skill_store.py skill_evaluator.py skill_learning.py task_inputs.py skill_replay.py; do
  cp "$HERE/$f" "$DEST/$f"
done
echo "zhulong installed to $DEST"
echo "enable it with:  hermes plugins enable zhulong"
