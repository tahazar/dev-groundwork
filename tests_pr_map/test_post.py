"""Posting the map on the pull request (AC-14 to AC-18, AC-20, AC-21).

A local HTTP server stands in for GitHub's issue comment API: a fake of the
process boundary, with modes for a read-only token (403) and a body size
limit (422). The Actions environment is set as environment variables.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock
from urllib.parse import parse_qs, urlsplit

from helpers import ROOT, MapRepo, pr_map

BOT = "github-actions[bot]"
MARKER = "<!-- groundwork:pr-map -->"
LIB = "def edit(x):\n    return x + 1\n"


class FakeGitHub:
    """Issue comments for pull request 5 of o/r, kept in memory."""

    def __init__(self, forbid_writes: bool = False, max_body: int | None = None):
        self.comments: list[dict] = []
        self.writes: list[tuple[str, int]] = []
        self.forbid_writes = forbid_writes
        self.max_body = max_body
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def reply(self, status: int, payload) -> None:
                body = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                url = urlsplit(self.path)
                if url.path == "/repos/o/r/issues/5/comments":
                    page = int(parse_qs(url.query).get("page", ["1"])[0])
                    self.reply(200, fake.comments[(page - 1) * 2 : page * 2])
                else:
                    self.reply(404, {"message": "Not Found"})

            def write(self, method: str):
                data = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                body = data["body"]
                fake.writes.append((method, len(body)))
                if fake.forbid_writes:
                    return self.reply(403, {"message": "Resource not accessible by integration"})
                if fake.max_body is not None and len(body) > fake.max_body:
                    return self.reply(422, {"message": "Validation Failed"})
                return body

            def do_POST(self):
                body = self.write("POST")
                if isinstance(body, str):
                    comment = {"id": 100 + len(fake.comments), "body": body, "user": {"login": BOT}}
                    fake.comments.append(comment)
                    self.reply(201, comment)

            def do_PATCH(self):
                body = self.write("PATCH")
                if isinstance(body, str):
                    comment_id = int(self.path.rsplit("/", 1)[1])
                    comment = next(c for c in fake.comments if c["id"] == comment_id)
                    comment["body"] = body
                    self.reply(200, comment)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


class PostTests(unittest.TestCase):
    def setUp(self):
        self.repo = MapRepo()
        self.addCleanup(self.repo.close)
        self.repo.base({"lib.py": LIB})
        self.repo.head({"lib.py": LIB.replace("x + 1", "x + 2")})
        self.tmp = Path(tempfile.mkdtemp())

    def run_post(self, fake: FakeGitHub, fork: bool = False, base: str = "base") -> int:
        event = {
            "pull_request": {
                "number": 5,
                "head": {"sha": "2222222bbbb", "repo": {"full_name": "fork/r" if fork else "o/r"}},
                "base": {"repo": {"full_name": "o/r"}},
            }
        }
        (self.tmp / "event.json").write_text(json.dumps(event), encoding="utf-8")
        env = {
            "GITHUB_API_URL": fake.url,
            "GITHUB_TOKEN": "t",
            "GITHUB_REPOSITORY": "o/r",
            "GITHUB_EVENT_PATH": str(self.tmp / "event.json"),
            "GITHUB_STEP_SUMMARY": str(self.tmp / "summary.md"),
            "GITHUB_SERVER_URL": "https://github.com",
            "GITHUB_RUN_ID": "7",
        }
        with mock.patch.dict(os.environ, env):
            return pr_map.main(["--base", base, "--post", "--out", str(self.tmp / "out")])

    def summary(self) -> str:
        path = self.tmp / "summary.md"
        return path.read_text(encoding="utf-8") if path.exists() else ""

    def fake(self, **kwargs) -> FakeGitHub:
        fake = FakeGitHub(**kwargs)
        self.addCleanup(fake.close)
        return fake

    def test_first_run_creates_one_comment_with_the_map(self):  # [pr-map AC-15] [pr-map AC-17]
        fake = self.fake()
        self.assertEqual(self.run_post(fake), 0)
        self.assertEqual(len(fake.comments), 1)
        body = fake.comments[0]["body"]
        self.assertIn(MARKER, body)
        self.assertIn("edit", body)
        self.assertIn("2222222", body, "the head SHA is the pull request's head commit")

    def test_second_run_edits_the_comment_in_place(self):  # [pr-map AC-16]
        fake = self.fake()
        fake.comments += [
            {"id": 1, "body": "first!", "user": {"login": "someone"}},
            {"id": 2, "body": f"quoting {MARKER}", "user": {"login": "someone"}},
            {"id": 3, "body": "lgtm", "user": {"login": "someone"}},
        ]
        self.run_post(fake)
        self.run_post(fake)
        ours = [c for c in fake.comments if c["user"]["login"] == BOT]
        self.assertEqual(len(ours), 1, "one comment, found again on the second page")
        self.assertEqual(fake.comments[1]["body"], f"quoting {MARKER}", "another author's marker is not ours")
        self.assertEqual([m for m, _ in fake.writes], ["POST", "PATCH"])

    def test_rejected_long_comment_is_shrunk_with_a_link(self):  # [pr-map AC-14]
        lib = "".join(f"def f{i}(x):\n    return x + {i}\n\n\n" for i in range(60))
        callers = "".join(f"from lib import f{i}\n\n\ndef c{i}():\n    return f{i}(1)\n\n\n" for i in range(60))
        self.repo.head({"lib.py": lib.replace("return x", "return -x"), "use.py": callers})
        fake = self.fake(max_body=1500)
        self.assertEqual(self.run_post(fake), 0)
        self.assertEqual(len(fake.comments), 1, "a smaller comment was accepted")
        body = fake.comments[0]["body"]
        self.assertLessEqual(len(body), 1500)
        self.assertIn("actions/runs/7", body, "the comment links to the complete map")
        self.assertIn("f59", self.summary(), "the summary holds the complete map")

    def test_fork_pull_request_writes_the_summary_only(self):  # [pr-map AC-18]
        fake = self.fake()
        self.assertEqual(self.run_post(fake, fork=True), 0)
        self.assertEqual(fake.writes, [], "the token is read-only on forks; no write is attempted")
        self.assertIn("edit", self.summary())
        self.assertIn("fork", self.summary().lower())

    def test_forbidden_comment_falls_back_to_the_summary(self):  # [pr-map AC-18]
        fake = self.fake(forbid_writes=True)
        self.assertEqual(self.run_post(fake), 0)
        self.assertIn("edit", self.summary())
        self.assertIn("403", self.summary())

    def test_failure_is_posted_and_does_not_fail_the_check(self):  # [pr-map AC-20] [pr-map AC-21]
        fake = self.fake()
        self.assertEqual(self.run_post(fake, base="no-such-ref"), 0)
        self.assertEqual(len(fake.comments), 1)
        self.assertIn("could not build the map", fake.comments[0]["body"])
        self.assertIn("no-such-ref", fake.comments[0]["body"])

    def test_artifact_files_hold_the_complete_map(self):  # [pr-map AC-14]
        self.run_post(self.fake())
        out = self.tmp / "out"
        self.assertIn("edit", (out / "pr-map.md").read_text(encoding="utf-8"))
        self.assertTrue(json.loads((out / "pr-map.json").read_text(encoding="utf-8"))["boxes"])


class WorkflowTemplateTests(unittest.TestCase):
    TEMPLATE = ROOT / "templates" / "ci" / "pr-map.yml"

    def text(self) -> str:
        self.assertTrue(self.TEMPLATE.exists(), "templates/ci/pr-map.yml is missing")
        return self.TEMPLATE.read_text(encoding="utf-8")

    def test_runs_on_pull_requests_with_comment_permission(self):  # [pr-map AC-15]
        text = self.text()
        self.assertRegex(text, r"(?m)^on:\s*\n\s+pull_request:")
        self.assertIn("pull-requests: write", text)
        self.assertIn("ref: ${{ github.event.pull_request.head.sha }}", text)

    def test_one_run_per_pull_request_at_a_time(self):  # [pr-map AC-16]
        text = self.text()
        self.assertIn("pr-map-${{ github.event.pull_request.number }}", text)
        self.assertIn("cancel-in-progress: false", text)

    def test_no_step_after_checkout_can_fail_the_check(self):  # [pr-map AC-21]
        steps = self.text().split("\n      - ")[1:]
        self.assertGreaterEqual(len(steps), 7)
        for step in steps[1:]:
            self.assertIn("continue-on-error: true", step, f"step can fail the check:\n{step}")

    def test_actions_are_pinned_to_commits(self):  # [pr-map AC-15]
        for line in self.text().splitlines():
            if "uses:" in line:
                self.assertRegex(line, r"@[0-9a-f]{40}\b", f"not pinned: {line.strip()}")


if __name__ == "__main__":
    unittest.main()
