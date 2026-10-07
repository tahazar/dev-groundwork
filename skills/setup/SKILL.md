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

- the command that formats and lints one file, per language;
- the commands that typecheck and test the project (fast enough to run
  before every stop; under a few minutes);
- where tests live;
- where design documents live today, if anywhere.

## 2. Write `.groundwork/config.json`

Start from `${CLAUDE_PLUGIN_ROOT}/templates/config.json` and fill in:

- `specDir`: where feature specs go. Default `docs/specs`; use an existing
  design-doc directory if the project has one.
- `testGlobs`: globs that match test files and nothing else.
- `onEdit`: one rule per language, `{"glob": "**/*.ts", "run": "<format and lint {file}>"}`.
  `{file}` is the edited path. Only per-file commands belong here.
- `onStop`: the typecheck and test command, joined with `&&`.
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
- Edit a source file and confirm the `onEdit` command runs.
- Report what was set up and what the user still needs to decide.
