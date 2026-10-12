#!/usr/bin/env bash
# Spike for skill-evals research: observe what `claude -p --output-format
# stream-json` records, with and without the plugin loaded by --plugin-dir.
# One-line prompt, cheapest model, turn limit 2, in a throwaway git repo.
# Usage: headless_spike.sh <plugin-dir> <out-dir>
set -euo pipefail
plugin="$(cd "$1" && pwd)"
out="$(mkdir -p "$2" && cd "$2" && pwd)"
work="$(mktemp -d)"
git -C "$work" init -q
echo "hello" > "$work/a.txt"
git -C "$work" add a.txt
git -C "$work" -c user.name=spike -c user.email=spike@example.com commit -qm baseline
cd "$work"
prompt='Read a.txt with the Read tool and reply with its first word only.'
common=(-p "$prompt" --output-format stream-json --verbose
        --model haiku --max-turns 2 --permission-mode dontAsk
        --allowedTools Read --no-session-persistence)
claude "${common[@]}" --plugin-dir "$plugin" > "$out/with-plugin.jsonl" 2> "$out/with-plugin.err" || echo "with-plugin exit $?" >> "$out/exit.txt"
claude "${common[@]}" > "$out/without-plugin.jsonl" 2> "$out/without-plugin.err" || echo "without-plugin exit $?" >> "$out/exit.txt"
rm -rf "$work"
