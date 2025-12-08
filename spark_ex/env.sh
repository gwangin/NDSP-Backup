#!/usr/bin/env bash
set -euo pipefail
if [[ -z "${SPARK_HOME:-}" ]]; then
  if command -v spark-submit >/dev/null 2>&1; then
    export SPARK_HOME="$(readlink -f "$(dirname "$(dirname "$(command -v spark-submit)")")")"
  elif [[ -x "$HOME/spark-3.5.6-bin-hadoop3/bin/spark-submit" ]]; then
    export SPARK_HOME="$HOME/spark-3.5.6-bin-hadoop3"
  elif [[ -x "$HOME/spark/bin/spark-submit" ]]; then
    export SPARK_HOME="$HOME/spark"
  else
    echo "ERROR: spark-submit not found" >&2
  fi
fi
export PATH="$SPARK_HOME/bin:$PATH"
