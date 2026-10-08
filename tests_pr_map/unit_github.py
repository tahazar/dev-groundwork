"""Tests for github.py and the entry point's exit codes, against a local HTTP server standing in for GitHub.

Run: python -m unittest discover -s tests_pr_map -p 'unit_*.py'
"""

from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import threading
import unittest
from contextlib import redirect_stderr
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts" / "pr_map"))
import github
import render
from helpers import MapRepo, pr_map
from unit_render import a_map, arrow, b

REPO = "o/r"
COMMENTS = f"/repos/{REPO}/issues/5/comments"


class Server:
    """Issue comments of pull request 5, two per page; records every request and every body written."""

    def __init__(self, comments: list[dict] | None = None, write_status: int = 0, list_status: int = 0):
        self.comments = comments or []
        self.requests: list[tuple[str, str]] = []
        self.bodies: list[str] = []
        self.max_body: int | None = None
        self.write_status = write_status  # answer every write with this status, when set
        self.list_status = list_status  # answer every listing with this status, when set
        self.drop_writes = False  # close the connection on every write without answering
        self.list_payload: object = None  # answer every listing with this instead of the comments, when set
        server = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def reply(self, status: int, payload) -> None:
                data = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                server.requests.append(("GET", self.path))
                url = urlsplit(self.path)
                if server.list_status:
                    return self.reply(server.list_status, {"message": "Forbidden"})
                if server.list_payload is not None:
                    return self.reply(200, server.list_payload)
                if url.path != COMMENTS:
                    return self.reply(404, {"message": "Not Found"})
                page = int(parse_qs(url.query)["page"][0])
                return self.reply(200, server.comments[(page - 1) * 2 : page * 2])

            def write(self) -> str | None:
                server.requests.append((self.command, self.path))
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))["body"]
                server.bodies.append(body)
                if server.drop_writes:
                    self.close_connection = True
                    return None
                if server.write_status:
                    self.reply(server.write_status, {"message": "Refused"})
                    return None
                if server.max_body is not None and len(body) > server.max_body:
                    self.reply(422, {"message": "Validation Failed", "errors": [{"field": "body"}]})
                    return None
                return body

            def do_POST(self):
                body = self.write()
                if body is not None:
                    comment = {"id": 100 + len(server.comments), "body": body, "user": {"login": github.BOT}}
                    server.comments.append(comment)
                    self.reply(201, comment)

            def do_PATCH(self):
                body = self.write()
                if body is not None:
                    comment = next(c for c in server.comments if c["id"] == int(self.path.rsplit("/", 1)[1]))
                    comment["body"] = body
                    self.reply(200, comment)

        self.http = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.http.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.http.server_address[1]}"

    def close(self) -> None:
        self.http.shutdown()
        self.http.server_close()


def three_diagrams() -> dict:
    """A map that renders as three diagrams: three unconnected groups under a budget of one arrow."""
    boxes, arrows = [], []
    for i in range(3):
        target, caller = b("lib.py", f"f{i}", "changed", line=i + 1), b("use.py", f"c{i}", line=i + 1)
        boxes += [target, caller]
        arrows.append(arrow(caller, target, line=i + 1))
    return a_map(boxes, arrows)


class GitHubTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.summary = self.tmp / "summary.md"

    def server(self, **kwargs) -> Server:
        server = Server(**kwargs)
        self.addCleanup(server.close)
        return server

    def ctx(self, server: Server, fork: str = "") -> github.Context:
        return github.Context(
            api_url=server.url,
            token="t",
            repository=REPO,
            number=5,
            head_sha="2" * 40,
            fork=fork,
            summary=self.summary,
            run_url="https://github.com/o/r/actions/runs/7",
        )

    def publish(self, server: Server, versions: list[str], fork: str = "", warns: bool = False) -> str:
        """Publish; a fallback (fork, refused or rejected write) must log a warning, a plain post must not."""
        if warns:
            with self.assertLogs("pr_map", "WARNING"):
                return github.publish(self.ctx(server, fork), versions)
        with self.assertNoLogs("pr_map", "WARNING"):
            return github.publish(self.ctx(server, fork), versions)

    def summary_text(self) -> str:
        return self.summary.read_text(encoding="utf-8")


class FindCommentTests(GitHubTestCase):
    def test_pages_until_our_comment(self):
        others = [{"id": i, "body": "lgtm", "user": {"login": "someone"}} for i in range(1, 6)]
        ours = {"id": 9, "body": f"{github.MARKER}\nold map", "user": {"login": github.BOT}}
        server = self.server(comments=[*others, ours])
        self.publish(server, ["new map"])
        pages = [path for method, path in server.requests if method == "GET"]
        self.assertEqual(len(pages), 3, "two comments per page: ours is on page 3")
        self.assertEqual(server.requests[-1], ("PATCH", f"/repos/{REPO}/issues/comments/9"))
        self.assertEqual(server.comments[-1]["body"], f"{github.MARKER}\nnew map")

    def test_pages_until_an_empty_page_when_there_is_none(self):
        server = self.server(comments=[{"id": i, "body": "x", "user": {"login": "someone"}} for i in range(1, 4)])
        self.publish(server, ["map"])
        self.assertEqual([m for m, _ in server.requests], ["GET", "GET", "GET", "POST"])

    def test_a_marker_in_another_authors_comment_is_not_ours(self):
        quoted = {"id": 1, "body": f"quoting {github.MARKER}", "user": {"login": "someone"}}
        server = self.server(comments=[quoted])
        self.assertTrue(self.publish(server, ["map"]).startswith("Created"))
        self.assertEqual(server.comments[0]["body"], f"quoting {github.MARKER}")
        self.assertEqual(len(server.comments), 2)

    def test_a_bot_comment_without_the_marker_is_not_ours(self):
        server = self.server(comments=[{"id": 1, "body": "another bot's note", "user": {"login": github.BOT}}])
        self.publish(server, ["map"])
        self.assertEqual(server.requests[-1][0], "POST")


class ShrinkTests(GitHubTestCase):
    def setUp(self):
        super().setUp()
        self.versions = render.comment_versions(three_diagrams(), "https://github.com/o/r/actions/runs/7", max_arrows=1)

    def test_versions_follow_the_design_order(self):
        v = self.versions
        self.assertEqual(len(v), 6, "complete, text list out, three diagrams out one at a time, header and counts")
        self.assertIn("<details>", v[0])
        self.assertNotIn("Shortened", v[0])
        for body in v[1:]:
            self.assertNotIn("<details>", body)
            self.assertIn("(https://github.com/o/r/actions/runs/7)", body)
        self.assertIn("so the text list moved", v[1])
        self.assertEqual([body.count("```mermaid") for body in v], [3, 3, 2, 1, 0, 0])
        self.assertIn("Group 1 of 3", v[3], "the last diagrams leave first")
        self.assertNotIn("Group 2 of 3", v[3])
        for k, body in enumerate(v[2:5], 1):
            self.assertIn(f"the text list and {k} of 3 diagrams moved", body)
        self.assertIn("so the map moved", v[5])
        self.assertIn("3 changed, 0 added, 0 removed, 3 neighbours", v[5])
        self.assertEqual([len(body) for body in v], sorted((len(body) for body in v), reverse=True))

    def test_a_map_without_changes_shrinks_only_its_notes(self):
        self.assertEqual(len(render.comment_versions(a_map([], []), "https://run")), 1)
        notes = {"skipped": [{"path": "a.py", "reason": "not UTF-8"}]}
        whole, brief = render.comment_versions(a_map([], [], notes), "https://run")
        self.assertIn("a.py", whole)
        self.assertNotIn("a.py", brief)
        self.assertIn("Notes moved to [the workflow run's summary](https://run)", brief)

    def test_each_step_is_tried_until_one_fits(self):
        for accepted in range(len(self.versions)):
            with self.subTest(accepted=accepted):
                self.summary.unlink(missing_ok=True)
                server = self.server()
                server.max_body = len(github.MARKER) + 1 + len(self.versions[accepted])
                status = self.publish(server, self.versions, warns=accepted > 0)
                self.assertEqual(server.bodies, [f"{github.MARKER}\n{v}" for v in self.versions[: accepted + 1]])
                self.assertEqual(server.comments[0]["body"], f"{github.MARKER}\n{self.versions[accepted]}")
                if accepted:
                    self.assertIn(f"rejected {accepted} longer version", status)
                self.assertIn(self.versions[0], self.summary_text(), "the summary holds the complete map")

    def test_shrinking_edits_an_existing_comment(self):
        server = self.server(comments=[{"id": 3, "body": f"{github.MARKER}\nold", "user": {"login": github.BOT}}])
        server.max_body = len(github.MARKER) + 1 + len(self.versions[1])
        self.publish(server, self.versions, warns=True)
        self.assertEqual([m for m, _ in server.requests], ["GET", "PATCH", "PATCH"])
        self.assertEqual(len(server.comments), 1)

    def test_gives_up_after_the_header_and_counts_and_records_the_response(self):
        server = self.server()
        server.max_body = 10
        status = self.publish(server, self.versions, warns=True)
        self.assertEqual(len(server.bodies), 6, "every version was tried once")
        self.assertEqual(server.comments, [])
        self.assertIn("rejected every version", status)
        self.assertIn("Validation Failed", self.summary_text(), "the API's response is recorded")
        self.assertIn(self.versions[0], self.summary_text())


class RefusedTests(GitHubTestCase):
    def test_fork_writes_nothing_and_says_why(self):
        server = self.server()
        status = self.publish(server, ["the map"], fork="fork/r", warns=True)
        self.assertEqual(server.requests, [], "no request at all on a fork")
        self.assertIn("fork `fork/r`", status)
        self.assertTrue(self.summary_text().startswith(status))
        self.assertIn("the map", self.summary_text())

    def test_403_on_write_is_recorded_in_the_summary(self):
        server = self.server(write_status=403)
        self.publish(server, ["the map", "smaller"], warns=True)
        self.assertEqual(len(server.bodies), 1, "a 403 is not retried smaller")
        self.assertIn("403", self.summary_text())
        self.assertIn("the map", self.summary_text())

    def test_403_on_listing_is_recorded_in_the_summary(self):
        server = self.server(list_status=403)
        self.publish(server, ["the map"], warns=True)
        self.assertEqual(server.bodies, [])
        self.assertIn("403", self.summary_text())

    def test_another_error_is_recorded_without_retrying(self):
        server = self.server(write_status=500)
        self.publish(server, ["the map", "smaller"], warns=True)
        self.assertEqual(len(server.bodies), 1)
        self.assertIn("HTTP 500", self.summary_text())


class BrokenAPITests(GitHubTestCase):
    def test_dropped_connection_still_writes_the_map_to_the_summary(self):
        server = self.server()
        server.drop_writes = True
        status = self.publish(server, ["the map"], warns=True)
        self.assertIn("no response", status)
        self.assertIn("the map", self.summary_text())

    def test_listing_that_is_not_a_list_is_named(self):
        server = self.server()
        server.list_payload = {"message": "odd"}
        self.publish(server, ["the map"], warns=True)
        self.assertEqual(server.bodies, [])
        self.assertIn("expected a list of comments", self.summary_text())
        self.assertIn("the map", self.summary_text())

    def test_rejected_failure_message_is_not_called_every_version(self):
        server = self.server()
        server.max_body = 10
        status = self.publish(server, ["pr-map could not build the map: boom"], warns=True)
        self.assertIn("rejected the comment.", status)


class SummaryTests(GitHubTestCase):
    def test_map_within_the_limit_is_written_whole(self):
        github.write_summary(self.summary, "Posted.", "x" * 1000, "https://run")
        self.assertEqual(self.summary_text(), "Posted.\n\n" + "x" * 1000 + "\n")

    def test_map_over_one_mib_points_to_the_artifact(self):
        with self.assertLogs("pr_map", "WARNING"):
            github.write_summary(self.summary, "Posted.", "x" * github.SUMMARY_LIMIT, "https://run")
        text = self.summary_text()
        self.assertTrue(text.startswith("Posted."))
        self.assertIn("`pr-map` artifact", text)
        self.assertIn("(https://run)", text)
        self.assertLess(len(text), 1000)

    def test_summary_is_appended_to(self):
        self.summary.write_text("earlier step\n", encoding="utf-8")
        github.write_summary(self.summary, "Posted.", "map", "https://run")
        self.assertTrue(self.summary_text().startswith("earlier step\n"))


class ContextTests(unittest.TestCase):
    def env(self, event: dict) -> dict:
        path = Path(tempfile.mkdtemp()) / "event.json"
        path.write_text(json.dumps(event), encoding="utf-8")
        return {
            "GITHUB_API_URL": "https://api.github.com/",
            "GITHUB_TOKEN": "t",
            "GITHUB_REPOSITORY": REPO,
            "GITHUB_EVENT_PATH": str(path),
            "GITHUB_STEP_SUMMARY": "/tmp/summary",
            "GITHUB_SERVER_URL": "https://github.com",
            "GITHUB_RUN_ID": "7",
        }

    def event(self, head_repo) -> dict:
        return {
            "pull_request": {
                "number": 5,
                "head": {"sha": "abc", "repo": head_repo},
                "base": {"repo": {"full_name": REPO}},
            }
        }

    def test_reads_the_pull_request(self):
        ctx = github.context(self.env(self.event({"full_name": REPO})))
        self.assertEqual((ctx.number, ctx.head_sha, ctx.fork), (5, "abc", ""))
        self.assertEqual(ctx.api_url, "https://api.github.com")
        self.assertEqual(ctx.run_url, "https://github.com/o/r/actions/runs/7")

    def test_a_fork_or_deleted_head_repository_is_a_fork(self):
        self.assertEqual(github.context(self.env(self.event({"full_name": "x/r"}))).fork, "x/r")
        self.assertEqual(github.context(self.env(self.event(None))).fork, "a deleted repository")

    def test_missing_variable_is_named(self):
        env = self.env(self.event({"full_name": REPO}))
        del env["GITHUB_TOKEN"]
        with self.assertRaisesRegex(github.ContextError, "GITHUB_TOKEN"):
            github.context(env)

    def test_event_without_a_pull_request_is_named(self):
        with self.assertRaisesRegex(github.ContextError, "pull_request"):
            github.context(self.env({"push": {}}))


class EntryPointTests(unittest.TestCase):
    def setUp(self):
        self.repo = MapRepo()
        self.addCleanup(self.repo.close)
        self.repo.base({"lib.py": "def f():\n    return 1\n"})
        self.repo.head({"lib.py": "def f():\n    return 2\n"})

    def test_missing_base_exits_2_without_post(self):
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
            pr_map.main([])
        self.assertEqual(raised.exception.code, 2)

    def test_unknown_base_exits_2_without_post(self):
        err = io.StringIO()
        with redirect_stderr(err):
            self.assertEqual(pr_map.main(["--base", "no-such-ref"]), 2)
        self.assertIn("finding the merge base of no-such-ref", err.getvalue())

    def test_missing_git_exits_2_without_post(self):
        err = io.StringIO()
        with mock.patch.dict(os.environ, {"PATH": ""}), redirect_stderr(err):
            self.assertEqual(pr_map.main(["--base", "base"]), 2)
        self.assertIn("cannot run git", err.getvalue())

    def test_missing_base_is_posted_with_post(self):
        server = Server()
        self.addCleanup(server.close)
        tmp = Path(tempfile.mkdtemp())
        event = {
            "pull_request": {
                "number": 5,
                "head": {"sha": "abc", "repo": {"full_name": REPO}},
                "base": {"repo": {"full_name": REPO}},
            }
        }
        (tmp / "event.json").write_text(json.dumps(event), encoding="utf-8")
        env = {
            "GITHUB_API_URL": server.url,
            "GITHUB_TOKEN": "t",
            "GITHUB_REPOSITORY": REPO,
            "GITHUB_EVENT_PATH": str(tmp / "event.json"),
            "GITHUB_STEP_SUMMARY": str(tmp / "summary.md"),
            "GITHUB_SERVER_URL": "https://github.com",
            "GITHUB_RUN_ID": "7",
        }
        with mock.patch.dict(os.environ, env), self.assertLogs("pr_map", "ERROR"):
            self.assertEqual(pr_map.main(["--post"]), 0)
        self.assertIn("could not build the map: reading the arguments: --base is required", server.comments[0]["body"])
        self.assertIn("--base is required", (tmp / "summary.md").read_text(encoding="utf-8"))

    def test_missing_variable_is_written_to_the_summary_when_there_is_one(self):
        summary = Path(tempfile.mkdtemp()) / "summary.md"
        env = {"GITHUB_EVENT_PATH": "", "GITHUB_STEP_SUMMARY": str(summary)}
        with mock.patch.dict(os.environ, env), self.assertLogs("pr_map", "ERROR"):
            self.assertEqual(pr_map.main(["--base", "base", "--post"]), 0)
        self.assertIn("could not build the map: reading the Actions environment", summary.read_text(encoding="utf-8"))

    def test_unwritable_out_exits_2_without_post(self):
        blocker = Path(tempfile.mkdtemp()) / "file"
        blocker.write_text("", encoding="utf-8")
        err = io.StringIO()
        with redirect_stderr(err):
            self.assertEqual(pr_map.main(["--base", "base", "--out", str(blocker / "out")]), 2)
        self.assertIn("writing the map to", err.getvalue())

    def test_missing_actions_environment_exits_0_with_post(self):
        env = {"GITHUB_EVENT_PATH": "", "GITHUB_STEP_SUMMARY": ""}
        with mock.patch.dict(os.environ, env), self.assertLogs("pr_map", "ERROR") as logs:
            self.assertEqual(pr_map.main(["--base", "base", "--post"]), 0)
        self.assertIn("GITHUB_EVENT_PATH is not set", logs.output[0])


if __name__ == "__main__":
    unittest.main()
