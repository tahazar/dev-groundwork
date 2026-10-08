#!/usr/bin/env bash
# Spike for skill-evals research: which plugins and skills a headless run
# loads under --safe-mode and --setting-sources, with and without
# --plugin-dir. One cheap turn each ("Reply OK."), no tools.
# Usage: isolation_spike.sh <plugin-dir> <out-dir>
set -uo pipefail
plugin="$(cd "$1" && pwd)"
out="$(mkdir -p "$2" && cd "$2" && pwd)"
work="$(mktemp -d)"
git -C "$work" init -q
cd "$work"
run() {
  local name="$1"; shift
  claude -p 'Reply OK.' --output-format stream-json --verbose --model haiku \
    --max-turns 1 --tools "" --no-session-persistence "$@" \
    < /dev/null > "$out/$name.jsonl" 2> "$out/$name.err"
  echo "$name exit $?" >> "$out/exit.txt"
}
run safe-without --safe-mode
run safe-with --safe-mode --plugin-dir "$plugin"
run nosources-without --setting-sources ""
run nosources-with --setting-sources "" --plugin-dir "$plugin"
rm -rf "$work"
