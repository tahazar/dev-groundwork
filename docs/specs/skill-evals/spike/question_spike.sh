#!/usr/bin/env bash
# Spike for skill-evals research: what a headless run does when the agent
# asks the user a question, and whether a second message reaches it by
# (a) --resume <session> -p <reply> and (b) stream-json input.
# Usage: question_spike.sh <out-dir>
set -uo pipefail
out="$(mkdir -p "$1" && cd "$1" && pwd)"
work="$(mktemp -d)"
git -C "$work" init -q
cd "$work"
ask='Ask me which colour I prefer, using the AskUserQuestion tool if you have it, otherwise as plain text. Then stop and wait for my answer.'
# (a) one-shot, then resume with the reply
claude -p "$ask" --output-format stream-json --verbose --model haiku \
  --max-turns 3 < /dev/null > "$out/ask.jsonl" 2> "$out/ask.err"
echo "ask exit $?" >> "$out/exit.txt"
sid="$(python3 -c 'import json,sys
for l in open(sys.argv[1]):
    m=json.loads(l)
    if m.get("type")=="result": print(m["session_id"])' "$out/ask.jsonl")"
echo "session $sid" >> "$out/exit.txt"
claude -p 'Blue. Reply with the colour I chose, in one word.' --resume "$sid" \
  --output-format stream-json --verbose --model haiku --max-turns 2 \
  < /dev/null > "$out/resume.jsonl" 2> "$out/resume.err"
echo "resume exit $?" >> "$out/exit.txt"
# (b) stream-json input: two user messages on stdin
python3 - "$ask" > "$work/in.jsonl" <<'PY'
import json, sys
for text in (sys.argv[1], "Green. Reply with the colour I chose, in one word."):
    print(json.dumps({"type": "user", "message": {"role": "user", "content": text}}))
PY
claude -p --input-format stream-json --output-format stream-json --verbose \
  --model haiku --max-turns 3 --no-session-persistence \
  < "$work/in.jsonl" > "$out/stdin.jsonl" 2> "$out/stdin.err"
echo "stdin exit $?" >> "$out/exit.txt"
rm -rf "$work"
