"""Post the map on the pull request and write the job summary.

Design: docs/specs/pr-map/design.md, Pipeline step 9. Standard library only:
the REST API through urllib. The comment is found by its marker and its
author, edited in place or created; on a fork, or when the API refuses the
write (403), only the job summary is written, saying why; when it rejects
the body (422), smaller versions are tried in turn.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

MARKER = "<!-- groundwork:pr-map -->"
BOT = "github-actions[bot]"
# Each step's job summary is limited to 1 MiB (C31).
SUMMARY_LIMIT = 1024 * 1024
ARTIFACT = "pr-map"
PER_PAGE = 100
TIMEOUT = 30  # seconds per request

log = logging.getLogger("pr_map")


class ContextError(RuntimeError):
    """The GitHub Actions environment lacks what posting needs; the message names the variable or field."""


class GitHubError(RuntimeError):
    """A request to the GitHub API failed. status is the HTTP status, or None when no response came."""

    def __init__(self, action: str, status: int | None, response: str):
        super().__init__(f"{action}: {f'HTTP {status}' if status else 'no response'}: {response}")
        self.status = status
        self.response = response


@dataclass(frozen=True)
class Context:
    """What posting needs, from the Actions environment and the pull_request event."""

    api_url: str
    token: str
    repository: str  # "owner/name" of the base repository
    number: int
    head_sha: str  # the pull request's head commit, not GitHub's merge commit (C49)
    fork: str  # the head repository's "owner/name" when it is not the base repository, else ""
    summary: Path
    run_url: str


def context(environ: Mapping[str, str]) -> Context:
    """Read the Context; raise ContextError naming what is missing."""

    def need(name: str) -> str:
        value = environ.get(name, "")
        if not value:
            raise ContextError(f"reading the Actions environment: {name} is not set")
        return value

    event_path = need("GITHUB_EVENT_PATH")
    try:
        event = json.loads(Path(event_path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ContextError(f"reading the event file {event_path}: {exc}") from exc
    try:
        pr = event["pull_request"]
        number = int(pr["number"])
        head_sha = pr["head"]["sha"]
        head_repo = (pr["head"].get("repo") or {}).get("full_name", "")
        base_repo = pr["base"]["repo"]["full_name"]
    except (KeyError, TypeError, ValueError) as exc:
        raise ContextError(f"reading the pull request from {event_path}: missing or invalid {exc}") from exc
    repository = need("GITHUB_REPOSITORY")
    run_url = f"{need('GITHUB_SERVER_URL')}/{repository}/actions/runs/{need('GITHUB_RUN_ID')}"
    return Context(
        api_url=need("GITHUB_API_URL").rstrip("/"),
        token=need("GITHUB_TOKEN"),
        repository=repository,
        number=number,
        head_sha=head_sha,
        # A deleted head repository reads as null; that is not the base repository either.
        fork=(head_repo or "a deleted repository") if head_repo != base_repo else "",
        summary=Path(need("GITHUB_STEP_SUMMARY")),
        run_url=run_url,
    )


def publish(ctx: Context, versions: list[str]) -> str:
    """Post the first comment version GitHub accepts, write the job summary, and return what happened.

    versions[0] is the complete map; it always goes to the summary (AC-14,
    AC-18). The returned status line is also the summary's first line.
    """
    status = post_comment(ctx, versions)
    write_summary(ctx.summary, status, versions[0], ctx.run_url)
    return status


def post_comment(ctx: Context, versions: list[str]) -> str:
    """Upsert the comment with the first version that is accepted; return a status line for the summary."""
    where = f"pull request #{ctx.number}"
    if ctx.fork:
        # Fallback: the token is read-only on forks (C33), so no write is tried; the summary holds the map.
        log.warning("not commenting on %s: it comes from the fork %s", where, ctx.fork)
        return (
            f"No comment was posted on {where}: it comes from the fork `{ctx.fork}`, "
            "and the workflow token is read-only on pull requests from forks. The map is below."
        )
    api = Client(ctx.api_url, ctx.token)
    comments = f"/repos/{ctx.repository}/issues/{ctx.number}/comments"
    try:
        existing = find_comment(api, comments)
        last: GitHubError | None = None
        for number, body in enumerate(versions):
            try:
                if existing is None:
                    api.request("POST", comments, {"body": f"{MARKER}\n{body}"}, f"creating the comment on {where}")
                else:
                    api.request(
                        "PATCH",
                        f"/repos/{ctx.repository}/issues/comments/{existing}",
                        {"body": f"{MARKER}\n{body}"},
                        f"editing comment {existing} on {where}",
                    )
            except GitHubError as exc:
                if exc.status != 422:
                    raise
                # Fallback: the length limit is undocumented (C30), so a rejected body is retried smaller.
                log.warning("GitHub rejected version %d of %d of the comment: %s", number + 1, len(versions), exc)
                last = exc
                continue
            action = "Created" if existing is None else "Updated"
            if number == 0:
                return f"{action} the map comment on {where}."
            return (
                f"{action} the map comment on {where} with a shortened version (GitHub rejected "
                f"{number} longer version{'s' if number != 1 else ''} with 422). The complete map is below."
            )
        return (
            f"No comment was posted on {where}: GitHub rejected every version of the comment, down to the "
            f"header and counts. The last response: {last}. The map is below."
        )
    except GitHubError as exc:
        # Fallback: a token without write access (403) or an API failure; the summary holds the map and why.
        log.warning("not commenting on %s: %s", where, exc)
        if exc.status == 403:
            return (
                f"No comment was posted on {where}: GitHub refused the write with 403 ({exc.response}); "
                "the workflow token cannot write pull request comments. The map is below."
            )
        return f"No comment was posted on {where}: {exc}. The map is below."


def find_comment(api: Client, comments: str) -> int | None:
    """The id of our comment: it carries MARKER and was written by BOT. Pages until an empty page."""
    page = 1
    while True:
        found = api.request("GET", f"{comments}?per_page={PER_PAGE}&page={page}", None, "listing the comments")
        if not found:
            return None
        for comment in found:
            if MARKER in (comment.get("body") or "") and (comment.get("user") or {}).get("login") == BOT:
                return comment["id"]
        page += 1


def write_summary(path: Path, status: str, full_map: str, run_url: str) -> None:
    """Append the status and the complete map to the job summary, or a pointer to the artifact over 1 MiB (C31)."""
    text = f"{status}\n\n{full_map}\n"
    size = len(text.encode("utf-8"))
    if size > SUMMARY_LIMIT:
        # Fallback: a summary over the limit would not be shown, so it points to the artifact instead.
        log.warning("the map is %d bytes, over the job summary's limit; pointing to the artifact", size)
        text = (
            f"{status}\n\nThe complete map is {size:,} bytes, over the 1 MiB limit of a job summary, so it is "
            f"not shown here. Download the `{ARTIFACT}` artifact of [this workflow run]({run_url}): "
            "it holds `pr-map.md` and `pr-map.json`.\n"
        )
    try:
        with path.open("a", encoding="utf-8") as summary:
            summary.write(text)
    except OSError as exc:
        raise OSError(f"writing the job summary {path}: {exc}") from exc


class Client:
    """JSON requests to the GitHub REST API with the workflow token."""

    def __init__(self, api_url: str, token: str):
        self.api_url = api_url
        self.token = token

    def request(self, method: str, path: str, payload: dict | None, action: str):
        """Send one request and return the decoded JSON; raise GitHubError naming action."""
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = urllib.request.Request(
            self.api_url + path,
            data=data,
            method=method,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
                "User-Agent": "groundwork-pr-map",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
                return json.loads(response.read() or b"null")
        except urllib.error.HTTPError as exc:
            raise GitHubError(action, exc.code, exc.read().decode("utf-8", "replace").strip()) from exc
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            raise GitHubError(action, None, str(exc)) from exc
