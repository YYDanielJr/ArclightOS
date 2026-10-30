#!/bin/bash
# Preserve the real command status through tee.
set -euo pipefail
repo=$(cd "$(dirname "$0")/.." && pwd)
work=${ARCLIGHT_WORK:-${YYDANIEL_WORK:-$(dirname "$repo")}}
log=$1
shift
[[ $log != */* && $log == *.log ]]
mkdir -p "$work/logs"
"$@" 2>&1 | tee "$work/logs/$log"
