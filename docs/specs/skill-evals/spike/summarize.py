"""Summarize the spikes' stream-json files into results.txt lines.

Usage: python3 summarize.py <out-dir>...  (prints to stdout)
"""

import json
import sys
from pathlib import Path


def summarize(path: Path) -> None:
    print(f"== {path.parent.name}/{path.name}")
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        m = json.loads(line)
        kind = m.get("type")
        if kind == "system" and m.get("subtype") == "init":
            skills = m.get("skills", [])
            ours = sorted(s for s in skills if s.startswith("dev-groundwork:"))
            print(
                f"init: model={m.get('model')} claude_code_version="
                f"{m.get('claude_code_version')} permissionMode="
                f"{m.get('permissionMode')} apiKeySource={m.get('apiKeySource')}"
            )
            print(f"init: plugins={[p.get('source') for p in m.get('plugins', [])]}")
            print(f"init: skills={len(skills)} dev-groundwork skills={ours}")
            print(
                f"init: tools={len(m.get('tools', []))} AskUserQuestion in tools="
                f"{'AskUserQuestion' in m.get('tools', [])}"
            )
            print(f"init: mcp_servers={m.get('mcp_servers')}")
        elif kind == "assistant":
            for block in m["message"].get("content", []):
                if block.get("type") == "tool_use":
                    print(f"assistant tool_use: name={block['name']} input={json.dumps(block['input'])[:200]}")
                elif block.get("type") == "text":
                    print(f"assistant text: {block['text'][:200]!r}")
        elif kind == "user":
            content = m["message"].get("content")
            if isinstance(content, str):
                print(f"user text: {content[:200]!r}")
                continue
            for block in content:
                if block.get("type") == "tool_result":
                    body = block.get("content")
                    if isinstance(body, list):
                        body = " ".join(b.get("text", "") for b in body)
                    print(f"user tool_result: is_error={block.get('is_error')} content={str(body)[:200]!r}")
                elif block.get("type") == "text":
                    print(f"user text: {block['text'][:200]!r}")
        elif kind == "result":
            print(
                f"result: subtype={m.get('subtype')} is_error={m.get('is_error')} "
                f"num_turns={m.get('num_turns')} total_cost_usd="
                f"{m.get('total_cost_usd')} duration_ms={m.get('duration_ms')} "
                f"terminal_reason={m.get('terminal_reason')} "
                f"permission_denials={json.dumps(m.get('permission_denials'))[:300]}"
            )
            print(f"result: modelUsage models={list(m.get('modelUsage', {}))}")
            print(f"result: result={str(m.get('result'))[:200]!r}")


for d in sys.argv[1:]:
    for p in sorted(Path(d).glob("*.jsonl")):
        summarize(p)
