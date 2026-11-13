#!/usr/bin/env python3
"""Delete a finished checkout's build output, and optionally the checkout.

Run it as the last step of a task, in the clone or worktree the task used:

    python clean_checkout.py PATH            # delete build output
    python clean_checkout.py PATH --remove   # then delete the checkout too
    python clean_checkout.py PATH --dry-run  # list what would go

It refuses to touch a checkout with uncommitted or untracked changes, or with
commits that are on no remote branch, so work that exists only on this disk
is never lost. With --remove on a full clone it also checks every local branch
and the stash, since those go with the folder; a linked worktree's branches
live in the main checkout and survive.

Build output is a git-ignored folder named in BUILD_DIRS. Tracked folders
with those names are kept.

Exit status: 0 when cleaned, 1 when refused, 2 on errors.
"""

from __future__ import annotations

import argparse
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

# Unreal (Intermediate, Binaries, DerivedDataCache), Godot (.godot), Visual
# Studio (.vs) and Python caches. All are rebuilt on the next build. Unreal's
# Saved folder is left alone because it holds editor autosaves.
BUILD_DIRS = {"Intermediate", "Binaries", "DerivedDataCache", ".godot", ".vs", "__pycache__"}


def git(root: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed in {root}: {result.stderr.strip()}")
    return result.stdout


def is_linked_worktree(root: Path) -> bool:
    git_dir = Path(git(root, "rev-parse", "--absolute-git-dir").strip())
    common = (root / git(root, "rev-parse", "--git-common-dir").strip()).resolve()
    return git_dir.resolve() != common


def reasons_to_refuse(root: Path, whole_clone: bool) -> list[str]:
    reasons = []
    changes = git(root, "status", "--porcelain").splitlines()
    if changes:
        reasons.append("uncommitted or untracked changes:\n  " + "\n  ".join(changes[:20]))
    refs = ["--branches", "HEAD"] if whole_clone else ["HEAD"]
    local_only = git(root, "log", "--oneline", *refs, "--not", "--remotes").splitlines()
    if local_only:
        reasons.append("commits not on any remote branch:\n  " + "\n  ".join(local_only[:20]))
    if whole_clone:
        stashes = git(root, "stash", "list").splitlines()
        if stashes:
            reasons.append("stashed changes:\n  " + "\n  ".join(stashes))
    return reasons


def build_dirs(root: Path) -> list[Path]:
    # --directory reports an ignored folder once instead of every file in it.
    listed = git(root, "ls-files", "--others", "--ignored", "--exclude-standard", "--directory").splitlines()
    return [root / entry for entry in listed if entry.endswith("/") and Path(entry).name in BUILD_DIRS]


def _make_writable(func, path, _exc_info):
    # Git marks pack files read-only, which stops rmtree on Windows.
    os.chmod(path, stat.S_IWRITE)
    func(path)


def remove_tree(path: Path) -> None:
    shutil.rmtree(path, onerror=_make_writable)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("path", type=Path, help="the clone or worktree to clean")
    parser.add_argument("--remove", action="store_true", help="also delete the checkout")
    parser.add_argument("--dry-run", action="store_true", help="list what would be deleted, delete nothing")
    args = parser.parse_args(argv)

    root = args.path.resolve()
    try:
        linked = is_linked_worktree(root)
        reasons = reasons_to_refuse(root, whole_clone=args.remove and not linked)
        if reasons:
            print(f"Left {root} as it is. It has", file=sys.stderr)
            for reason in reasons:
                print(f"- {reason}", file=sys.stderr)
            return 1

        for folder in build_dirs(root):
            print(f"{'would delete' if args.dry_run else 'deleting'} {folder}")
            if not args.dry_run:
                remove_tree(folder)

        if args.remove:
            print(f"{'would remove' if args.dry_run else 'removing'} {root}")
            if not args.dry_run:
                if linked:
                    # Run from the shared .git folder: Windows cannot delete a git process's working directory.
                    common = (root / git(root, "rev-parse", "--git-common-dir").strip()).resolve()
                    git(common, "worktree", "remove", str(root))
                else:
                    remove_tree(root)
    except (RuntimeError, OSError) as error:
        print(f"clean_checkout: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
