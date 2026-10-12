#!/usr/bin/env bash
# Spike for skill-evals research: (1) what the result says when the turn
# limit is hit; (2) whether --resume keeps the earlier conversation (the
# reply does not repeat the fact the agent must remember).
# Usage: limits_spike.sh <out-dir>
set -uo pipefail
out="$(mkdir -p "$1" && cd "$1" && pwd)"
work="$(mktemp -d)"
git -C "$work" init -q
echo "hello" > "$work/a.txt"
cd "$work"
claude -p 'Read a.txt, then read it again, then reply DONE.' \
  --output-format stream-json --verbose --model haiku --max-turns 1 \
  --permission-mode dontAsk --allowedTools Read --no-session-persistence \
  < /dev/null > "$out/maxturns.jsonl" 2> "$out/maxturns.err"
echo "maxturns exit $?" >> "$out/exit.txt"
sid="$(python3 -c 'import uuid; print(uuid.uuid4())')"
claude -p 'The secret word is PELICAN. Ask me whether I am ready, as plain text, then stop.' \
  --session-id "$sid" --output-format stream-json --verbose --model haiku \
  --max-turns 1 --tools "" < /dev/null > "$out/remember1.jsonl" 2> "$out/remember1.err"
echo "remember1 exit $?" >> "$out/exit.txt"
claude -p 'Yes. What was the secret word? One word.' --resume "$sid" \
  --output-format stream-json --verbose --model haiku --max-turns 1 --tools "" \
  < /dev/null > "$out/remember2.jsonl" 2> "$out/remember2.err"
echo "remember2 exit $?" >> "$out/exit.txt"
rm -rf "$work"
