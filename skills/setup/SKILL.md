---
name: setup
description: Set up the dev-groundwork pipeline in the current project. Creates .groundwork/config.json, the project rules file, the CI workflow and the vendored check scripts. Use when the user asks to add or install the development pipeline in a repository.
disable-model-invocation: true
---

# Set up dev-groundwork in this project

The plugin's hooks do nothing in a project until `.groundwork/config.json`
exists, so this skill is what turns the pipeline on.

## 1. Learn the project

Read the build and test setup before asking anything: `package.json`,
`pyproject.toml`, `Makefile`, CI workflows, `CONTRIBUTING.md`, existing
`CLAUDE.md`, and any review guide. Find:

- the commands that check formatting, lint, typecheck and test the
  project, fast enough to run before every commit (a few minutes at most;
  split slow suites so they run only when their part of the tree changed);
- where tests live;
- where design documents live today, if anywhere.

## 2. Write `.groundwork/config.json`

Start from `${CLAUDE_PLUGIN_ROOT}/templates/config.json` and fill in:

- `specDir`: where feature specs go. Default `docs/specs`; use an existing
  design-doc directory if the project has one.
- `testGlobs`: globs that match test files and nothing else.
- `onCommit`: the format check, lint, typecheck and test commands, joined
  with `&&`, or a script that runs them. It runs before each commit Claude
  makes and blocks the commit on failure.
- `sources.tier1` and `sources.tier2`: domains for this project's stack.
  Tier 1 is official documentation, standards bodies, and the source hosts
  of libraries the project uses (for example `docs.python.org`,
  `nodejs.org`, `docs.aws.amazon.com`, `github.com`, `arxiv.org`). Tier 2 is
  vendor and maintainer blogs. Leave everything else unlisted; unlisted
  domains count as Tier 3.

Show the user the file and confirm the commands before writing it.

## 3. Copy the project files

```bash
mkdir -p .groundwork/bin
cp ${CLAUDE_PLUGIN_ROOT}/scripts/groundwork_config.py ${CLAUDE_PLUGIN_ROOT}/scripts/check_citations.py \
   ${CLAUDE_PLUGIN_ROOT}/scripts/check_ac_coverage.py ${CLAUDE_PLUGIN_ROOT}/scripts/detect_workarounds.py .groundwork/bin/
```

- Add `.groundwork/state/` to `.gitignore`.
- Copy `${CLAUDE_PLUGIN_ROOT}/templates/project-rules.md` to
  `.groundwork/project-rules.md`. Read the project's existing rules
  (CLAUDE.md, CONTRIBUTING.md, review guides, ADRs) and add the
  project-specific ones under the last heading. Do not duplicate rules that
  already live elsewhere; reference the file instead.
- If the project uses GitHub Actions, copy
  `${CLAUDE_PLUGIN_ROOT}/templates/ci/groundwork.yml` to
  `.github/workflows/groundwork.yml`. Keep the pinned action SHA.

## 4. Point CLAUDE.md at the pipeline

Add a short section to the project's `CLAUDE.md` (create it if missing):

```markdown
## Development pipeline

Features go through dev-groundwork: requirements, research, design,
acceptance tests, implementation, review. Specs live in `<specDir>/<feature>/`.
Skip the first three stages only when the change fits in one sentence.
Project rules: `.groundwork/project-rules.md`.
```

## 5. Check it works

- `python3 .groundwork/bin/detect_workarounds.py --base origin/<default branch>` runs.
- Run the `onCommit` command once by hand and confirm it passes on the
  current tree.
- Report what was set up and what the user still needs to decide.
