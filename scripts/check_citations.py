#!/usr/bin/env python3
"""Check the citations in a research document.

Citations live in fenced blocks tagged `citations`:

    ```citations
    - id: C1
      claim: Retrieving docs for every call hurt common APIs.
      source: https://example.com/paper.pdf
      tier: 1
      quote: negatively impacts high frequency APIs
      retrieved: 2026-10-07
    - id: C2
      claim: The codebase already clamps velocity.
      source: file:packages/core/src/arp/engine.ts
      tier: 1
      quote: function clampVelocity
    - id: C3
      claim: Live's Simpler slices at transients by default.
      status: unverified
    ```

For each entry this checks, without judging meaning:

- required fields are present (`id`, `claim`, and `source`/`tier`/`quote`
  unless `status: unverified`);
- the declared tier is not better than the source's domain allows
  (domains come from .groundwork/config.json; unlisted domains are Tier 3,
  `file:` sources are Tier 1);
- a Tier 3 source is only used as `role: pointer`;
- the quote appears verbatim, after whitespace and punctuation
  normalization, in the fetched page or the local file.

Whether a quote supports its claim is a judgment call; the
`citation-verifier` agent does that part.

An entry may set `override: <reason>` when the page cannot be checked
automatically (a PDF, a page rendered by JavaScript). Overrides are listed
in the report so a reviewer sees each one.

Exit status: 0 when every entry passes or is unverified/overridden, 1 when
any entry fails, 2 on usage errors.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import ssl
import sys
import unicodedata
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
from groundwork_config import load_config, project_root

BLOCK_RE = re.compile(r"^```citations[ \t]*\n(.*?)^```", re.MULTILINE | re.DOTALL)
REQUIRED_VERIFIED = ("source", "tier", "quote")


@dataclass
class Result:
    entry: dict
    status: str  # pass | fail | unverified | override | not-fetched
    messages: list[str] = field(default_factory=list)


def parse_entries(text: str) -> list[dict]:
    """Parse `- key: value` entries; each value is one line."""
    entries: list[dict] = []
    for block in BLOCK_RE.findall(text):
        current: dict | None = None
        for raw in block.splitlines():
            line = raw.rstrip()
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            item = re.match(r"^-\s+(\w[\w-]*):\s*(.*)$", line)
            field_ = re.match(r"^\s+(\w[\w-]*):\s*(.*)$", line)
            if item:
                current = {item.group(1): _unquote(item.group(2))}
                entries.append(current)
            elif field_ and current is not None:
                current[field_.group(1)] = _unquote(field_.group(2))
            else:
                raise ValueError(f"cannot parse citation line: {line!r}")
    return entries


def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def normalize(text: str) -> str:
    """Lowercase, fold Unicode quotes and dashes, collapse whitespace."""
    text = unicodedata.normalize("NFKC", text)
    for a, b in (("\u2018", "'"), ("\u2019", "'"), ("\u201c", '"'), ("\u201d", '"')):
        text = text.replace(a, b)
    text = re.sub("[\u2010-\u2015\u2212]", "-", text)
    return re.sub(r"\s+", " ", text).strip().lower()


def html_to_text(raw: str) -> str:
    raw = re.sub(r"(?is)<(script|style|noscript)\b.*?</\1>", " ", raw)
    raw = re.sub(r"(?s)<[^>]+>", " ", raw)
    return html.unescape(raw)


def domain_tier(host: str, sources: dict) -> int:
    host = host.lower()
    for tier_key, tier in (("tier1", 1), ("tier2", 2)):
        for domain in sources.get(tier_key, []):
            domain = domain.lower()
            if host == domain or host.endswith("." + domain):
                return tier
    return 3


def fetch(url: str, timeout: float) -> tuple[str, str]:
    """Return (content type, text) for a URL."""
    req = urllib.request.Request(url, headers={"User-Agent": "dev-groundwork-citation-check/0.1"})
    ctx = ssl.create_default_context()
    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
        ctype = resp.headers.get("Content-Type", "")
        charset = resp.headers.get_content_charset() or "utf-8"
        return ctype, resp.read().decode(charset, errors="replace")


def check_entry(entry: dict, root: Path, sources: dict, offline: bool, timeout: float) -> Result:
    cid = entry.get("id", "?")
    res = Result(entry, "pass")
    if "id" not in entry or "claim" not in entry:
        return Result(entry, "fail", [f"{cid}: needs both `id` and `claim`"])
    if entry.get("status") == "unverified":
        return Result(entry, "unverified")

    missing = [k for k in REQUIRED_VERIFIED if not entry.get(k)]
    if missing:
        return Result(entry, "fail", [f"{cid}: missing {', '.join(missing)} (or set `status: unverified`)"])

    try:
        declared = int(entry["tier"])
        assert declared in (1, 2, 3)
    except (ValueError, AssertionError):
        return Result(entry, "fail", [f"{cid}: tier must be 1, 2 or 3"])

    source = entry["source"]
    if source.startswith("file:"):
        actual = 1
    else:
        parsed = urlparse(source)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            return Result(entry, "fail", [f"{cid}: source must be an http(s) URL or file:<path>"])
        actual = domain_tier(parsed.hostname, sources)

    if declared < actual:
        res.status = "fail"
        res.messages.append(
            f"{cid}: declared Tier {declared}, but {source} is Tier {actual} under this project's source list"
        )
    if max(declared, actual) == 3 and entry.get("role") != "pointer":
        res.status = "fail"
        res.messages.append(f"{cid}: Tier 3 sources can only be pointers (`role: pointer`); find the Tier 1 source")

    if entry.get("override"):
        if res.status == "pass":
            res.status = "override"
        res.messages.append(f"{cid}: quote not checked, override: {entry['override']}")
        return res

    quote = normalize(entry["quote"])
    if len(quote) < 20:
        res.status = "fail"
        res.messages.append(f"{cid}: quote is too short to check ({len(quote)} chars); quote a full phrase")
        return res

    if source.startswith("file:"):
        path = (root / source[len("file:") :].split("#", 1)[0]).resolve()
        if not path.is_file():
            res.status = "fail"
            res.messages.append(f"{cid}: file not found: {path}")
            return res
        haystack = normalize(path.read_text(encoding="utf-8", errors="replace"))
    elif offline:
        if res.status == "pass":
            res.status = "not-fetched"
        res.messages.append(f"{cid}: offline, quote not checked")
        return res
    else:
        try:
            ctype, body = fetch(source, timeout)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            res.status = "fail"
            res.messages.append(f"{cid}: could not fetch {source}: {exc}")
            return res
        if "pdf" in ctype.lower():
            res.status = "fail"
            res.messages.append(
                f"{cid}: {source} is a PDF, which this script cannot read; check it by hand and set `override:`"
            )
            return res
        haystack = normalize(html_to_text(body) if "html" in ctype.lower() else body)

    if quote not in haystack:
        res.status = "fail"
        res.messages.append(f"{cid}: quote not found at {source}")
    return res


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("files", nargs="+", help="markdown files with ```citations blocks")
    parser.add_argument("--offline", action="store_true", help="skip network fetches")
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--json", action="store_true", help="print results as JSON")
    parser.add_argument("--require", action="store_true", help="fail when the files contain no citations")
    args = parser.parse_args(argv)

    root = project_root()
    config = load_config(root) or {}
    sources = config.get("sources", {})

    results: list[Result] = []
    for name in args.files:
        text = Path(name).read_text(encoding="utf-8")
        try:
            entries = parse_entries(text)
        except ValueError as exc:
            print(f"{name}: {exc}", file=sys.stderr)
            return 2
        results += [check_entry(e, root, sources, args.offline, args.timeout) for e in entries]

    if args.json:
        print(
            json.dumps(
                [{"id": r.entry.get("id"), "status": r.status, "messages": r.messages} for r in results], indent=2
            )
        )
    else:
        for r in results:
            print(f"{r.status:12} {r.entry.get('id', '?'):6} {r.entry.get('claim', '')[:70]}")
            for m in r.messages:
                print(f"{'':12} {m}")
        counts = {
            s: sum(r.status == s for r in results) for s in ("pass", "fail", "unverified", "override", "not-fetched")
        }
        print(", ".join(f"{v} {k}" for k, v in counts.items() if v) or "no citations found")

    if args.require and not results:
        print("no citations found; a research document needs at least one", file=sys.stderr)
        return 1
    return 1 if any(r.status == "fail" for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
