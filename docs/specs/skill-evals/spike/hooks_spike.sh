#!/usr/bin/env bash
# Spike for skill-evals research: do the plugin's PreToolUse hooks (the test
# lock guard) run in a headless --plugin-dir run with no user settings, and
# what does the transcript record when a hook denies a tool call?
# Usage: hooks_spike.sh <plugin-dir> <out-dir>
set -uo pipefail
plugin="$(cd "$1" && pwd)"
out="$(mkdir -p "$2" && cd "$2" && pwd)"
work="$(mktemp -d)"
git -C "$work" init -q
mkdir -p "$work/.groundwork/state" "$work/tests"
echo '{"testGlobs": ["tests/**"]}' > "$work/.groundwork/config.json"
touch "$work/.groundwork/state/tests-locked"
echo "def test_a(): pass" > "$work/tests/test_a.py"
cd "$work"
claude -p 'Run exactly this Bash command once: rm tests/test_a.py ; then reply with what happened in one sentence.' \
  --output-format stream-json --verbose --include-hook-events --model haiku \
  --max-turns 3 --permission-mode dontAsk --allowedTools Bash \
  --setting-sources "" --plugin-dir "$plugin" --no-session-persistence \
  < /dev/null > "$out/guard.jsonl" 2> "$out/guard.err"
echo "guard exit $?" >> "$out/exit.txt"
if [ -e tests/test_a.py ]; then echo "tests/test_a.py still exists" >> "$out/exit.txt"; else echo "tests/test_a.py deleted" >> "$out/exit.txt"; fi
rm -rf "$work"
