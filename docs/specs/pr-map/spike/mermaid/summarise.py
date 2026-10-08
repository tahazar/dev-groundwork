"""Summarises escape-results.json: exact counts per strategy x version x htmlLabels, and each failure."""
import collections
import json
import sys

rows = json.load(open(sys.argv[1]))
ok = lambda r: r.get("exactIgnoringWrap")  # SVG labels wrap long words; line breaks added by wrapping are ignored
seen = collections.defaultdict(set)
for r in rows:
    seen[(r["version"], r["html"], r["strategy"], r["name"])].add(r.get("text", "ERR"))
print("combinations where theme or securityLevel changed the displayed text:", sum(len(v) > 1 for v in seen.values()))
print("foreignObject present by htmlLabels:", dict(collections.Counter((r["html"], r.get("fo")) for r in rows)))
names = list(dict.fromkeys(r["name"] for r in rows))
versions = list(dict.fromkeys(r["version"] for r in rows))
strategies = list(dict.fromkeys(r["strategy"] for r in rows))
base = [r for r in rows if r["theme"] == "default" and r["sec"] == "strict"]
print(f"\n## Names displayed exactly, of {len(names)} (theme/securityLevel had no effect)\n")
cols = [(v, h) for v in versions for h in (True, False)]
print("| strategy | " + " | ".join(f"{v} html={'T' if h else 'F'}" for v, h in cols) + " |")
print("|---" * (len(cols) + 1) + "|")
for s in strategies:
    print(f"| {s} | " + " | ".join(str(sum(1 for r in base if r["strategy"] == s and r["version"] == v and r["html"] == h and ok(r))) for v, h in cols) + " |")
print("\n## Failures (displayed text, first line) per strategy\n")
for s in strategies:
    print(f"### {s}")
    for v, h in cols:
        bad = [r for r in base if r["strategy"] == s and r["version"] == v and r["html"] == h and not ok(r)]
        if bad:
            shown = "; ".join(f"{r['name']} -> " + ("PARSE ERROR" if "error" in r else repr(r["text"].replace("\n", "⏎"))) for r in bad)
            print(f"- {v} htmlLabels={h}: {shown}")
    print()
