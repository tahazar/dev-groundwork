# Research: skill-evals

- Requirements: `requirements.md` (approved 2026-10-08)
- Measurements: `spike/` holds the scripts and `spike/results.txt` their
  output. The spikes ran Claude Code 2.1.294 headless (`claude -p`) on
  `claude-haiku-5-5` with one-line prompts in throwaway git repositories,
  inside a claude.ai cloud container where authentication comes from the
  host. All runs together cost about $0.02 by the CLI's own estimate.
  Raw transcripts are not kept because they hold account and container
  details.

## Summary for the design

| Job | Candidate | Evidence | Fits |
|---|---|---|---|
| Run one eval run | `claude -p` with `--output-format stream-json --verbose`, `--model`, `--max-turns`, `--permission-mode dontAsk`, `--allowedTools` | Every tool call and its result are in the stream; the first event names model, version, plugins and skills; the last carries cost, turn count and an error subtype (C1 to C9) | AC-6, AC-8, AC-11, AC-13, AC-16 |
| Arm with the plugin | `--plugin-dir <this repo>` for that run only | Init lists `dev-groundwork@inline` and its 9 skills; its hooks run and deny a locked-test edit (C10, C11, C12, C13, C13b) | AC-5 |
| Arm without the plugin | Same command without `--plugin-dir` | Init lists no `dev-groundwork` plugin and no `dev-groundwork:` skill, which the suite can assert per run (C14) | AC-5 |
| Settings isolation | `--setting-sources ""`, `--strict-mcp-config`, explicit environment; `--bare` with an API key where available | Dropped user-level skills (35 to 21) while keeping the plugin; the child appears to inherit the caller's environment (C14 to C20e) | AC-19 |
| Scripted replies | `--resume <session-id> -p "<reply>"` after each run ends | No question tool in headless mode; the agent asks in plain text and the run ends; resume continues with memory (C21 to C26) | AC-7 |
| Spending cap | Sum `total_cost_usd` per run (taking the last value after resumes) | Reported on every result; an estimate at list price, not a bill (C27 to C31) | AC-9, AC-16 |
| Rejected as the runner: `claude plugin eval` | | Has arms, runs, cost ceiling and a sandbox, but "no custom-code graders" and no scripted replies; can grade `fires`/`quiet` with a `tool_used: Skill` grader (C32 to C45) | AC-4 only |

## Existing code to reuse

| What | Where | Use it for |
|---|---|---|
| Project root and config | `scripts/groundwork_config.py` (`project_root`, `load_config`, `DEFAULTS`, `TEST_LOCK`) | Every check script finds the workspace as `$CLAUDE_PROJECT_DIR`, else the git top level, else the working directory (C46). Graders run in the workspace with `CLAUDE_PROJECT_DIR` set to it or unset |
| Citation check | `scripts/check_citations.py --json` | Grading `research` cases from its JSON result and exit code (C47) |
| AC coverage check | `scripts/check_ac_coverage.py <feature>` | Grading `requirements` and `review` cases. Needs `.groundwork/config.json` in the fixture; exits 2 without it (C48) |
| Workaround check | `scripts/detect_workarounds.py --base <ref>` | Grading `implement` and `review` cases. Sees only tracked changes, so the grader stages first, as the tests do (C49) |
| Test lock and its guard | `hooks/hooks.json`, `scripts/hook_guard_tests.py` | The lock is the file `.groundwork/state/tests-locked`; the guard denies test edits while it exists. The deny reason appears in the transcript as a failed tool result (C13, C50, C50b, C51) |
| Commit gate | `scripts/hook_commit_gate.py` | Runs the fixture's `onCommit` before `git commit` and denies the commit when it fails, with a fixed message the grader can find (C52, C53) |
| Temporary git repositories | `tests/test_scripts.py` (`Repo`, `git`, `run_main`); `tests_pr_map/helpers.py` (`MapRepo(Repo)`) | `Repo` already makes a temporary repository with a config and one `init` commit (C54, C55, C55b). AC-2's workspace builder and AC-15's check tests should extend it, as pr-map did |
| CI | `.github/workflows/ci.yml` job `test` | AC-18's token-free checks: `unittest discover tests` already runs there, so check tests placed under `tests/` run without a new job (C56) |
| Plugin root | `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json` | The repository root is the plugin, so `--plugin-dir` takes the repository path (C57) |

Nothing in the repository parses a transcript or calls `claude -p` today;
the transcript reader is new code.

Duplicates the design should not copy a third time:

- A `git` subprocess helper exists in `hook_commit_gate.py` (returns text)
  and in `tests/test_scripts.py` (returns nothing), and
  `groundwork_config.merge_base` / `diff_against` call git inline. The
  eval workspace builder and graders should use one of these, not a new one.
- Setting the git user name and email is done in `Repo.__init__` and in
  both CI jobs. The workspace builder needs the same and should get it from
  `Repo`.
- The deny JSON is built twice (`hook_guard_tests.deny`, inline in
  `hook_commit_gate.main`). Not this feature's job, but graders matching a
  deny reason depend on both wordings.

## External APIs and libraries

**`claude -p` (Claude Code 2.1.294).** The help output is in
`spike/claude-help.txt`.

- **Output.** `stream-json` writes one JSON object per line (C1). The
  `system/init` event reports the model, tools, MCP servers and loaded
  plugins (C2); the spike's init also carried `claude_code_version` and the
  skill list (C3). Each tool call is an `assistant` event with a `tool_use`
  block holding the tool name and full input, and its result is a `user`
  event with a `tool_result` block (C4). The last line is a `result`
  message with cost and session metadata (C5); the spike's held
  `total_cost_usd`, `num_turns`, `duration_ms`, `is_error`, `subtype`,
  `terminal_reason`, `permission_denials` and per-model token counts (C6).
  So AC-6's model ID and version, AC-11's tool calls and AC-16's duration
  and cost all come from the transcript.
- **Limits.** `--max-turns` exits with an error at the limit (C7). The
  spike's result was `subtype=error_max_turns`, `is_error=True`, exit code
  1 (C8, C8b). There is no time limit flag; the suite enforces AC-8's time limit
  by killing the process. `--max-budget-usd` caps one run's spend (C9).
- **Permissions.** `dontAsk` denies anything that would prompt and runs
  what `--allowedTools` allows (C17). Runs never wait for a person.

**Loading the plugin for one arm.** `--plugin-dir` loads a plugin for
that session only (C10). With it, init listed `dev-groundwork@inline` and
the nine `dev-groundwork:` skills (C11, C12); without it, neither (C14).
The plugin's hooks run under `--plugin-dir`: the guard denied
`rm tests/test_a.py` in a locked fixture, the file survived, and the
transcript recorded the hook's deny reason as an error tool result (C13,
C13b, C51). The proof that the
"without" arm had no dev-groundwork skills is therefore a check on each
run's own init event, recorded with the run.

Two caveats for the design:
- `--safe-mode` is not usable: with `--plugin-dir` it listed the plugin but
  loaded none of its skills (C18).
- The "without" arm is not skill-free. Skills named `debug` and `design`
  that do not come from dev-groundwork were present without the plugin,
  even with no setting sources (C19). A `fires` check for `debug` must match the skill name
  `dev-groundwork:debug` in the `Skill` tool input, not `debug`.

**Isolation (AC-19).** Without flags a headless run loads user, project
and local settings and the account's skills; `--setting-sources ""`
dropped the skill count from 35 to 21 and kept the plugin's (C14, C15,
C15b). The child appears to inherit the caller's environment: in the
spike its session ID equalled the calling session's
`CLAUDE_CODE_SESSION_ID` (C16), and `plugin eval` withholds the
environment on purpose (C40). So the suite should start each run with an
explicit, minimal environment, not `os.environ`.
`--bare` skips hooks, plugin sync, CLAUDE.md and auto-memory (C20e) and
reads only `ANTHROPIC_API_KEY` or an `apiKeyHelper` for Anthropic auth
(C20), which
is the documented way to keep the owner's login out of a run, at the cost
of needing an API key. `CLAUDE_CONFIG_DIR` moves settings, history and
plugins (C20b). Whether a run with a temporary `CLAUDE_CONFIG_DIR` can
still use a subscription login without copying credentials into it was
not verified (C20c). Whether `--bare` still runs the hooks of a
`--plugin-dir` plugin was not verified either (C20d); the design should
spike it, because the "with" arm needs those hooks.

**Questions and scripted replies (AC-7).** In headless mode
`AskUserQuestion` was not in the tool list (C21; `spike/results.txt`
shows the same for every run), and the
docs say unattended modes remove or deny it (C22, C23). Asked to put a
question, the agent wrote it as plain text and the run ended normally
(C24). `--resume <session-id>` with a new `-p` prompt delivered the reply,
and the agent remembered a word given only in the first turn (C25,
C25b, C25c). Two
user messages on stdin with `--input-format stream-json` were also
answered (C26, C26b, C26c), but the docs describe that stdin format only for the
Agent SDK, so resume is the documented path.

**Cost (AC-9, AC-16).** The result reports `total_cost_usd` (C27), a
client-side estimate at list price, not billing data (C28, C29). After a
resume the figure is the whole conversation's total, earlier runs
included (C30), so a run with scripted replies counts its last figure, not
the sum. The spike's figure matches the published Haiku 5.5 prices
exactly: 1,189 input × $0.10 + 11,142 cache-write × $0.20 (the 1-hour
rate) + 59,717 cache-read × $0.01 + 92 output × $0.50, per million
tokens, is $0.00299047, the CLI's own figure (C31, C31b, C31e). So list
prices are a sound basis for the estimate below, and the CLI writes its
cache at the 1-hour rate.

**`claude plugin eval` (Claude Code 2.1.294).** A suite of cases, each a
prompt plus graders (C32), run in a fresh isolated headless session with
only the plugin loaded (C33), three runs per case by default (C34), with a
no-plugin baseline arm and a `Δ` (C35). It has turn and time limits (C36),
a cost ceiling checked before each run (C37), per-case model and run
count, and a JSON result with cost, duration and Claude Code version
(C38). Its sandbox gives each run a temporary home, working directory and
configuration and withholds user settings, hooks, CLAUDE.md, MCP servers,
other plugins and most of the environment (C39, C40). It cannot host this
suite's `normal` and `pressure` cases:
- "There are no custom-code graders" (C41); graders are regex, tool use,
  tool order, file existence and model-judged (C42). AC-11 needs graders
  that read git history and run dev-groundwork's scripts.
- `file_exists` sees only files created during the run (C43).
- A fixture repository comes from a Bash `scaffold_script` run only with
  `--scaffold` (C44).
- There are no scripted replies; a case can only resume a recorded
  transcript (C45).
It can host routing: a `tool_used` grader on `Skill` with an
`input_match` regex detects that a skill fired (C42b, C42c). The design can
either use it for AC-4's `fires` and `quiet` cases or run those through
the same runner as the rest; one runner keeps one results file (AC-16).
`--judge-model` defaults to haiku, but no model judge is needed (AC-11).

## Answers to open questions

- **How the suite installs the plugin for one arm and not the other.**
  `--plugin-dir <repo>` on the "with" runs only; nothing installed (C10).
  Each run's init event proves which plugins and skills loaded (C11, C12,
  C14). Hooks load with it (C13). User settings and the account's skills
  are kept out with `--setting-sources ""` and an explicit environment
  (C15, C16); `--bare` with an API key is the fuller isolation (C20).
- **How it reads tool calls and costs from a headless run.**
  `--output-format stream-json --verbose`: `tool_use` and `tool_result`
  blocks per call, init for model and version, result for cost, turns,
  duration and error kind (C1 to C8, C27).
- **Whether `claude plugin eval` can host these cases.** Not the `normal`
  and `pressure` cases: no custom-code graders and no scripted replies
  (C41, C45). It can host `fires` and `quiet` routing cases (C42b, C42c). The
  suite therefore needs its own runner; `plugin eval`'s isolation list
  (C39, C40) is the model for what that runner withholds.
- **Scripted replies.** Resume after each run that ends with replies left
  (C25, C25b, C25c). See the first point under "Points the requirements
  may need to revisit".
- **The pinned model and the default cap.** Deferred to the owner, as the
  requirements say; the estimate is under Constraints.

## Points the requirements may need to revisit

Research does not change the requirements; these are questions for the
owner.

1. **AC-7, "when it asks for input".** A headless agent has no question
   tool (C21, C22); a question is a run that ends with text (C24), which
   a script cannot tell apart from a finished answer. A deterministic
   reading: whenever a run ends normally and the case still has replies,
   the suite resumes with the next one; when replies are used up, it
   resumes once with "No further input." and records that. Is that what
   AC-7 means, and should "No further input." be sent once, or after
   every further end?
2. **The `requirements` skill tells the agent to use AskUserQuestion**
   (`skills/requirements/SKILL.md`), which is not available headless.
   Its cases would test the skill with questions asked in plain text. Is
   that acceptable for version 1?
3. **The "without" arm still has built-in skills named `debug` and
   `design`** (C19). AC-5's comparison is then "dev-groundwork against
   stock Claude Code", not "against no skills". `--disable-slash-commands`
   would disable all skills (`spike/claude-help.txt`), which is a stricter
   baseline but not what a user without the plugin has. Which does the
   owner want?
4. **AC-19 and credentials.** Full isolation (`--bare`) needs an API key
   (C20). Without one, the runner keeps the owner's login available to the
   run. Will the owner use an API key for eval runs?
5. **AC-9 counts an estimate.** On a subscription the cost figure is a
   list-price estimate, not money spent (C28, C29). Is a cap on that
   estimate what the owner wants?
6. **Tier list.** Anthropic's pricing page is on `platform.claude.com`,
   which `.groundwork/config.json` does not list, so it counts as Tier 3.
   Should it be added to Tier 1?

## Constraints

- **Cost estimate (inputs stated; an estimate, not a measurement of a
  real case).** Inputs:
  - The suite's size from AC-3 to AC-5: 12 `normal`/`pressure` cases × 2
    arms × 5 runs = 120 runs, plus 6 `fires`/`quiet` cases × 5 = 30 runs;
    150 runs.
  - Per run, from the spike (70,859 cached tokens over two calls, so
    about 35,000 tokens of context per call with the plugin; C6, C11b):
    25 model calls whose context grows to
    about 80,000 tokens, so about 1.4 million cache-read tokens, 80,000
    cache-write tokens (written at the 1-hour rate, as observed) and
    8,000 output tokens.
  - List prices per million tokens, input / 1-hour cache write / cache
    read / output (C31b to C31i): Opus 5.5 $4 / $8 / $0.20 / $20;
    Sonnet 5.5 $2 / $4 / $0.10 / $10; Haiku 5.5 $0.10 / $0.20 / $0.01 /
    $0.50 (prompts up to 100,000 tokens).

  | Model | Per run | Suite (150 runs) |
  |---|---|---|
  | Opus 5.5 | about $1.10 | about $160 |
  | Sonnet 5.5 | about $0.55 | about $80 |
  | Haiku 5.5 | about $0.03 | about $5 |

  The turn count is the weakest input: a run of 50 calls whose context
  grows further costs roughly two to three times as much, and on Haiku a
  context above 100,000 tokens moves to the higher price row. A first pilot of one case per arm would replace the
  guess with a measurement. On a subscription the figure counts against
  plan usage rather than a bill (C28).
- **Credentials.** `--bare` needs `ANTHROPIC_API_KEY` (C20). Without it,
  isolation relies on `--setting-sources ""` and an explicit environment,
  and the run can still use the owner's login from the default config
  directory.
- **Version drift.** The spike ran 2.1.294; `plugin eval` needs 2.1.269 or
  later (C33b). The result's fields were observed, and only some are
  documented in prose (C2, C5); the transcript reader should fail loudly
  on a missing field rather than record an empty value.
- **Sources.** Pricing is on `platform.claude.com`, which this project's
  `.groundwork/config.json` does not list as Tier 1, so those entries are
  pointers (C31b to C31i). The spike's cost figure matching those prices
  (C31) is the Tier 1 support.

## Citations

```citations
- id: C1
  claim: stream-json output is newline-delimited JSON.
  source: https://code.claude.com/docs/en/headless.md
  tier: 1
  quote: "`stream-json`: newline-delimited JSON for real-time streaming"
  retrieved: 2026-10-08
- id: C2
  claim: The system/init event reports the model, tools, MCP servers and loaded plugins.
  source: https://code.claude.com/docs/en/headless.md
  tier: 1
  quote: The `system/init` event reports session metadata including the model, tools, MCP servers, and loaded plugins.
  retrieved: 2026-10-08
- id: C3
  claim: In the spike the init event carried the model ID, the Claude Code version and the permission mode.
  source: file:docs/specs/skill-evals/spike/results.txt
  tier: 1
  quote: "init: model=claude-haiku-5-5 claude_code_version=2.1.294 permissionMode=dontAsk apiKeySource=none"
- id: C4
  claim: The spike's stream recorded a tool call with its name and full input, followed by its tool result.
  source: file:docs/specs/skill-evals/spike/results.txt
  tier: 1
  quote: 'assistant tool_use: name=Read input={"file_path": "<tmpdir>/a.txt"} user tool_result: is_error=None'
- id: C5
  claim: The last line of the stream is a result message with the final text, cost and session metadata.
  source: https://code.claude.com/docs/en/headless.md
  tier: 1
  quote: The last line of the stream is a `result` message with the final response text, cost, and session metadata.
  retrieved: 2026-10-08
- id: C6
  claim: The spike's result message carried subtype, is_error, num_turns, total_cost_usd, duration_ms and terminal_reason.
  source: file:docs/specs/skill-evals/spike/results.txt
  tier: 1
  quote: "result: subtype=success is_error=False num_turns=2 total_cost_usd=0.0029904700000000003 duration_ms=2498 terminal_reason=completed"
- id: C7
  claim: --max-turns limits agentic turns in print mode and exits with an error at the limit.
  source: https://code.claude.com/docs/en/cli-reference.md
  tier: 1
  quote: Limit the number of agentic turns (print mode only). Exits with an error when the limit is reached.
  retrieved: 2026-10-08
- id: C8
  claim: In the turn-limit spike the result had subtype error_max_turns and is_error true.
  source: file:docs/specs/skill-evals/spike/results.txt
  tier: 1
  quote: result: subtype=error_max_turns is_error=True num_turns=2
- id: C8b
  claim: The turn-limit spike's process exited with code 1.
  source: file:docs/specs/skill-evals/spike/results.txt
  tier: 1
  quote: maxturns exit 1 remember1 exit 0
- id: C9
  claim: --max-budget-usd caps the dollar amount one print-mode run spends.
  source: https://code.claude.com/docs/en/cli-reference.md
  tier: 1
  quote: Maximum dollar amount to spend on API calls before stopping (print mode only).
  retrieved: 2026-10-08
- id: C10
  claim: --plugin-dir loads a plugin from a directory or .zip for the session only.
  source: file:docs/specs/skill-evals/spike/claude-help.txt
  tier: 1
  quote: Load a plugin from a directory or .zip for this session only
- id: C11
  claim: With --plugin-dir, the init event listed dev-groundwork as an inline plugin.
  source: file:docs/specs/skill-evals/spike/results.txt
  tier: 1
  quote: "init: plugins=['dev-groundwork@inline', 'cc-plugin-agents-md@builtin', 'cc-plugin-telemetry@builtin', 'cc-plugin-plugin-authoring@builtin']"
- id: C11b
  claim: The with-plugin spike run's model usage was 59,717 cache-read and 11,142 cache-write input tokens.
  source: file:docs/specs/skill-evals/spike/results.txt
  tier: 1
  quote: == spike1 result usage fields (with-plugin) modelUsage: {"inputTokens": 1189, "outputTokens": 92, "cacheReadInputTokens": 59717, "cacheCreationInputTokens": 11142, "costUSD": 0.0029904700000000003, "costBasis": "list"}
- id: C12
  claim: With --plugin-dir, the init event listed the plugin's skills under the dev-groundwork namespace.
  source: file:docs/specs/skill-evals/spike/results.txt
  tier: 1
  quote: "init: skills=44 dev-groundwork skills=['dev-groundwork:acceptance-tests', 'dev-groundwork:debug'"
- id: C13
  claim: After the Bash call rm tests/test_a.py, the transcript recorded an error tool result carrying a PreToolUse hook's reason that tests are locked.
  source: file:docs/specs/skill-evals/spike/results.txt
  tier: 1
  quote: assistant tool_use: name=Bash input={"command": "rm tests/test_a.py", "description": "Delete tests/test_a.py"} user tool_result: is_error=True content='PreToolUse:Bash hook error: Tests are locked; this command could change tests/test_a.py.
- id: C13b
  claim: After the hook spike, the locked test file still existed.
  source: file:docs/specs/skill-evals/spike/results.txt
  tier: 1
  quote: guard exit 0 tests/test_a.py still exists
- id: C14
  claim: In spike1's without-plugin run, the init event listed no dev-groundwork plugin and no dev-groundwork skills.
  source: file:docs/specs/skill-evals/spike/results.txt
  tier: 1
  quote: == spike1/without-plugin.jsonl init: model=claude-haiku-5-5 claude_code_version=2.1.294 permissionMode=dontAsk apiKeySource=none init: plugins=['cc-plugin-agents-md@builtin', 'cc-plugin-telemetry@builtin', 'cc-plugin-plugin-authoring@builtin'] init: skills=35 dev-groundwork skills=[]
- id: C15
  claim: The no-setting-sources run without the plugin had 21 skills and no dev-groundwork plugin or skills.
  source: file:docs/specs/skill-evals/spike/results.txt
  tier: 1
  quote: == spike2/nosources-without.jsonl init: model=claude-haiku-5-5 claude_code_version=2.1.294 permissionMode=default apiKeySource=none init: plugins=['cc-plugin-agents-md@builtin', 'cc-plugin-telemetry@builtin', 'cc-plugin-plugin-authoring@builtin'] init: skills=21 dev-groundwork skills=[]
- id: C15b
  claim: The no-setting-sources run with the plugin had 30 skills, the plugin's among them.
  source: file:docs/specs/skill-evals/spike/results.txt
  tier: 1
  quote: == spike2/nosources-with.jsonl init: model=claude-haiku-5-5 claude_code_version=2.1.294 permissionMode=default apiKeySource=none init: plugins=['dev-groundwork@inline', 'cc-plugin-agents-md@builtin', 'cc-plugin-telemetry@builtin', 'cc-plugin-plugin-authoring@builtin'] init: skills=30 dev-groundwork skills=['dev-groundwork:acceptance-tests'
- id: C16
  claim: The child claude -p run's session ID equalled the calling session's CLAUDE_CODE_SESSION_ID.
  source: file:docs/specs/skill-evals/spike/results.txt
  tier: 1
  quote: child session_id equals the calling session CLAUDE_CODE_SESSION_ID: True
- id: C17
  claim: dontAsk denies every call that would otherwise prompt.
  source: https://code.claude.com/docs/en/headless.md
  tier: 1
  quote: "`dontAsk`**: Claude Code denies every call that would otherwise prompt, which is useful for locked-down CI runs."
  retrieved: 2026-10-08
- id: C18
  claim: In the safe-mode run with the plugin, the init event listed dev-groundwork as a plugin but no dev-groundwork skills.
  source: file:docs/specs/skill-evals/spike/results.txt
  tier: 1
  quote: == spike2/safe-with.jsonl init: model=claude-haiku-5-5 claude_code_version=2.1.294 permissionMode=default apiKeySource=none init: plugins=['dev-groundwork@inline', 'cc-plugin-agents-md@builtin', 'cc-plugin-telemetry@builtin', 'cc-plugin-plugin-authoring@builtin'] init: skills=21 dev-groundwork skills=[]
- id: C19
  claim: In the without-plugin run under --setting-sources "", skills named debug and design were present.
  source: file:docs/specs/skill-evals/spike/results.txt
  tier: 1
  quote: == skills left in the without-plugin arm under --setting-sources "" (spike2) nosources-without skills: ['artifact-capabilities', 'artifact-diagramming', 'batch', 'claude-api', 'code-review', 'dataviz', 'debug', 'deep-research', 'design',
- id: C20
  claim: In --bare mode, Anthropic authentication is only ANTHROPIC_API_KEY or an apiKeyHelper; OAuth and the keychain are never read.
  source: file:docs/specs/skill-evals/spike/claude-help.txt
  tier: 1
  quote: Anthropic auth is strictly ANTHROPIC_API_KEY or apiKeyHelper via --settings (OAuth and keychain are never read).
- id: C20b
  claim: CLAUDE_CONFIG_DIR overrides the configuration directory, under which settings, session history and plugins are stored.
  source: https://code.claude.com/docs/en/env-vars.md
  tier: 1
  quote: Override the configuration directory (default: `~/.claude`). All settings, session history, and plugins are stored under this path.
  retrieved: 2026-10-08
- id: C20c
  claim: A run with a temporary CLAUDE_CONFIG_DIR can use the owner's subscription login without copying credentials into it.
  status: unverified
- id: C20d
  claim: --bare still runs the hooks of a plugin loaded with --plugin-dir.
  status: unverified
- id: C20e
  claim: --bare skips hooks from settings and installed plugins, plugin sync, auto-memory and CLAUDE.md auto-discovery.
  source: file:docs/specs/skill-evals/spike/claude-help.txt
  tier: 1
  quote: Minimal mode: skip hooks (those defined in settings and by installed plugins; features built into Claude Code are unaffected), LSP, plugin sync, attribution, auto-memory, background prefetches, keychain reads, and CLAUDE.md auto-discovery.
- id: C21
  claim: A spike run's init event listed 39 tools and did not include AskUserQuestion.
  source: file:docs/specs/skill-evals/spike/results.txt
  tier: 1
  quote: init: tools=39 AskUserQuestion in tools=False
- id: C22
  claim: With --permission-prompts none, Claude Code removes tools that need an answer from a person, such as AskUserQuestion.
  source: https://code.claude.com/docs/en/headless.md
  tier: 1
  quote: With `--permission-prompts none`, Claude Code removes the tools that need an answer from a person, such as [`AskUserQuestion`]
  retrieved: 2026-10-08
- id: C23
  claim: Under dontAsk, AskUserQuestion is denied even when an allow rule matches (the docs sentence is split by links, so the quote check cannot match it).
  status: unverified
- id: C24
  claim: In the question spike the agent wrote its question as plain assistant text and the run ended with subtype success.
  source: file:docs/specs/skill-evals/spike/results.txt
  tier: 1
  quote: assistant text: "Which colour do you prefer? Pick one from red, blue, green, purple, orange, or black, or name your own. I'll wait for your answer before going further." result: subtype=success is_error=False num_turns=1
- id: C25
  claim: The resumed run (remember2) answered PELICAN.
  source: file:docs/specs/skill-evals/spike/results.txt
  tier: 1
  quote: == spike4/remember2.jsonl init: model=claude-haiku-5-5 claude_code_version=2.1.294 permissionMode=default apiKeySource=none init: plugins=['cc-plugin-agents-md@builtin', 'cc-plugin-telemetry@builtin', 'cc-plugin-plugin-authoring@builtin'] init: skills=35 dev-groundwork skills=[] init: tools=0 AskUserQuestion in tools=False init: mcp_servers=[] assistant text: 'PELICAN'
- id: C25b
  claim: The limits spike's resumed second prompt asked for the secret word without giving it.
  source: file:docs/specs/skill-evals/spike/limits_spike.sh
  tier: 1
  quote: claude -p 'Yes. What was the secret word? One word.' --resume "$sid"
- id: C25c
  claim: The limits spike's first prompt gave the secret word.
  source: file:docs/specs/skill-evals/spike/limits_spike.sh
  tier: 1
  quote: claude -p 'The secret word is PELICAN. Ask me whether I am ready, as plain text, then stop.'
- id: C26
  claim: The stdin run (stdin.jsonl) answered Green.
  source: file:docs/specs/skill-evals/spike/results.txt
  tier: 1
  quote: == spike3/stdin.jsonl init: model=claude-haiku-5-5 claude_code_version=2.1.294 permissionMode=default apiKeySource=none init: plugins=['cc-plugin-agents-md@builtin', 'cc-plugin-telemetry@builtin', 'cc-plugin-plugin-authoring@builtin'] init: skills=35 dev-groundwork skills=[] init: tools=39 AskUserQuestion in tools=False init: mcp_servers=[] assistant text: 'Green'
- id: C26b
  claim: The question spike's stdin run used --input-format stream-json.
  source: file:docs/specs/skill-evals/spike/question_spike.sh
  tier: 1
  quote: claude -p --input-format stream-json --output-format stream-json --verbose
- id: C26c
  claim: The question spike prepares two message texts, the second giving the answer Green.
  source: file:docs/specs/skill-evals/spike/question_spike.sh
  tier: 1
  quote: for text in (sys.argv[1], "Green. Reply with the colour I chose, in one word."):
- id: C27
  claim: JSON output includes total_cost_usd and a per-model cost breakdown.
  source: https://code.claude.com/docs/en/headless.md
  tier: 1
  quote: With `--output-format json`, the response payload includes `total_cost_usd` and a per-model cost breakdown
  retrieved: 2026-10-08
- id: C28
  claim: Claude Code computes the dollar figure locally from token counts at list price.
  source: https://code.claude.com/docs/en/costs.md
  tier: 1
  quote: Claude Code computes the dollar figure locally from token counts at list price
  retrieved: 2026-10-08
- id: C29
  claim: total_cost_usd and costUSD are client-side estimates, not billing data.
  source: https://code.claude.com/docs/en/agent-sdk/cost-tracking.md
  tier: 1
  quote: The `total_cost_usd` and `costUSD` fields are client-side estimates, not authoritative billing data.
  retrieved: 2026-10-08
- id: C30
  claim: A resumed run reports the whole conversation's total cost, earlier runs included.
  source: https://code.claude.com/docs/en/headless.md
  tier: 1
  quote: When you continue an earlier conversation with `--continue` or `--resume`, the run reports the conversation's whole total,
  retrieved: 2026-10-08
- id: C31
  claim: The with-plugin spike run used 1189 input, 92 output, 59717 cache-read and 11142 cache-write tokens, and Claude Code put its cost at $0.00299 on a list-price basis.
  source: file:docs/specs/skill-evals/spike/results.txt
  tier: 1
  quote: == spike1 result usage fields (with-plugin) modelUsage: {"inputTokens": 1189, "outputTokens": 92, "cacheReadInputTokens": 59717, "cacheCreationInputTokens": 11142, "costUSD": 0.0029904700000000003, "costBasis": "list"}
- id: C31b
  claim: The pricing table's Haiku 5.5 row for prompts up to 100,000 tokens lists $0.10, $0.125, $0.20, $0.01 and $0.50 per million tokens.
  source: https://platform.claude.com/docs/en/about-claude/pricing.md
  tier: 3
  role: pointer
  quote: Claude Haiku 5.5 (for prompts up to 100,000 tokens) | $0.10 / MTok | $0.125 / MTok | $0.20 / MTok | $0.01 / MTok | $0.50 / MTok
  retrieved: 2026-10-08
- id: C31c
  claim: Opus 5.5 and Sonnet 5.5 cache hits cost 5% of the base input price, $0.20 and $0.10 per million tokens.
  source: https://platform.claude.com/docs/en/about-claude/pricing.md
  tier: 3
  role: pointer
  quote: a cache hit costs 5% of the standard input price ($0.20 USD per million tokens on Claude Opus 5.5, $0.10 USD on Claude Sonnet 5.5).
  retrieved: 2026-10-08
- id: C31d
  claim: A one-hour cache write costs twice the base input price.
  source: https://platform.claude.com/docs/en/about-claude/pricing.md
  tier: 3
  role: pointer
  quote: 1-hour cache write | 2x base input price
  retrieved: 2026-10-08
- id: C31e
  claim: The pricing table's columns are base input, 5-minute cache writes, 1-hour cache writes, cache hits and refreshes, and output tokens.
  source: https://platform.claude.com/docs/en/about-claude/pricing.md
  tier: 3
  role: pointer
  quote: | Model | Base input tokens | 5m cache writes | 1h cache writes | Cache hits and refreshes | Output tokens |
  retrieved: 2026-10-08
- id: C31f
  claim: The pricing table's Sonnet 5.5 row lists $2 base input, $2.50 five-minute and $4 one-hour cache writes.
  source: https://platform.claude.com/docs/en/about-claude/pricing.md
  tier: 3
  role: pointer
  quote: "| Claude Sonnet 5.5 | $2 / MTok | $2.50 / MTok | $4 / MTok |"
  retrieved: 2026-10-08
- id: C31g
  claim: The pricing table's Opus 5.5 row lists $4 base input, $5 five-minute and $8 one-hour cache writes.
  source: https://platform.claude.com/docs/en/about-claude/pricing.md
  tier: 3
  role: pointer
  quote: "| Claude Opus 5.5 | $4 / MTok | $5 / MTok | $8 / MTok |"
  retrieved: 2026-10-08
- id: C31h
  claim: The pricing table's Sonnet 5.5 row ends with $0.10 for cache hits and $10 for output per million tokens.
  source: https://platform.claude.com/docs/en/about-claude/pricing.md
  tier: 3
  role: pointer
  quote: "| Claude Sonnet 5.5 | $2 / MTok | $2.50 / MTok | $4 / MTok | $0.10 / MTok<sup>2</sup> | $10 / MTok |"
  retrieved: 2026-10-08
- id: C31i
  claim: The pricing table's Opus 5.5 row ends with $0.20 for cache hits and $20 for output per million tokens.
  source: https://platform.claude.com/docs/en/about-claude/pricing.md
  tier: 3
  role: pointer
  quote: "| Claude Opus 5.5 | $4 / MTok | $5 / MTok | $8 / MTok | $0.20 / MTok<sup>2</sup> | $20 / MTok |"
  retrieved: 2026-10-08
- id: C32
  claim: A plugin eval case is a prompt plus one or more graders.
  source: https://code.claude.com/docs/en/plugin-evals.md
  tier: 1
  quote: Each case is a realistic prompt plus one or more graders.
  retrieved: 2026-10-08
- id: C33
  claim: A plugin eval run has only the plugin loaded and works until it finishes or hits the case's turn or time limit.
  source: https://code.claude.com/docs/en/plugin-evals.md
  tier: 1
  quote: with only your plugin loaded, sends the prompt, and lets Claude work until it finishes or hits the case's turn or time limit.
  retrieved: 2026-10-08
- id: C33b
  claim: Running plugin evals requires Claude Code 2.1.269 or later.
  source: https://code.claude.com/docs/en/plugin-evals.md
  tier: 1
  quote: To run plugin evals you need: * Claude Code v2.1.269 or later.
  retrieved: 2026-10-08
- id: C34
  claim: Each plugin eval case runs three times by default.
  source: https://code.claude.com/docs/en/plugin-evals.md
  tier: 1
  quote: One run of a non-deterministic agent tells you little, so each case runs three times by default.
  retrieved: 2026-10-08
- id: C35
  claim: Plugin eval repeats a case's runs with no plugin loaded and reports two scores, WITH and W/OUT.
  source: https://code.claude.com/docs/en/plugin-evals.md
  tier: 1
  quote: a case's runs are repeated with no plugin loaded, and you get two scores, `WITH` and `W/OUT`.
  retrieved: 2026-10-08
- id: C36
  claim: plugin eval runs are bounded by each case's max_turns and timeout_seconds.
  source: file:docs/specs/skill-evals/spike/claude-help.txt
  tier: 1
  quote: Runs are already bounded by max_turns and timeout_seconds
- id: C37
  claim: plugin eval's --max-cost-usd ceiling is checked before each run launches.
  source: file:docs/specs/skill-evals/spike/claude-help.txt
  tier: 1
  quote: --max-cost-usd <usd> Optional hard cost ceiling; abort and report partial results if hit (exit 2). The ceiling is checked before each run launches
- id: C38
  claim: plugin eval's result reports estimated cost, duration and the Claude Code version.
  source: https://code.claude.com/docs/en/plugin-evals.md
  tier: 1
  quote: Estimated cost at list price including judge calls, wall-clock seconds, and the Claude Code version that ran the suite
  retrieved: 2026-10-08
- id: C39
  claim: plugin eval runs load no user settings, hooks, CLAUDE.md, MCP servers, other plugins, memory or skills.
  source: https://code.claude.com/docs/en/plugin-evals.md
  tier: 1
  quote: Your user settings, hooks, `CLAUDE.md` files, MCP servers, other installed plugins, memory, and skills are absent.
  retrieved: 2026-10-08
- id: C40
  claim: plugin eval withholds most of the shell environment from a run.
  source: https://code.claude.com/docs/en/plugin-evals.md
  tier: 1
  quote: Most of your shell environment is withheld too; only an
  retrieved: 2026-10-08
- id: C41
  claim: plugin eval has no custom-code graders.
  source: https://code.claude.com/docs/en/plugin-evals.md
  tier: 1
  quote: There are no custom-code graders.
  retrieved: 2026-10-08
- id: C42
  claim: plugin eval has six grader types; regex, tool_used, tool_order and file_exists are computed from the transcript and files.
  source: https://code.claude.com/docs/en/plugin-evals.md
  tier: 1
  quote: Of the six types, `regex`, `tool_used`, `tool_order`, and `file_exists` are computed from the transcript and files and cost nothing, while `llm` and `baseline` call a judge model
  retrieved: 2026-10-08
- id: C42b
  claim: A tool_used grader passes when the number of matching calls to its tool, filtered by an input_match regex, is within min and max.
  source: https://code.claude.com/docs/en/plugin-evals.md
  tier: 1
  quote: The number of calls to `tool` whose JSON-encoded input matches the optional `input_match` regex is between `min`, default 1, and `max`, default unlimited.
  retrieved: 2026-10-08
- id: C42c
  claim: The Skill grader in the docs' example passes when the skill was invoked, including in its plugin-name:skill-name form.
  source: https://code.claude.com/docs/en/plugin-evals.md
  tier: 1
  quote: This passes when Claude invoked that skill at least once during the run, including by its namespaced `plugin-name:skill-name` form.
  retrieved: 2026-10-08
- id: C43
  claim: plugin eval's file_exists grader counts only files created during the run.
  source: https://code.claude.com/docs/en/plugin-evals.md
  tier: 1
  quote: Only files created during the run count
  retrieved: 2026-10-08
- id: C44
  claim: A plugin eval case's fixture files or git repository come from a Bash script named in context.scaffold_script, which runs only with --scaffold.
  source: https://code.claude.com/docs/en/plugin-evals.md
  tier: 1
  quote: Fixture files or a git repository**: write a Bash script in the case directory and name it in `context.scaffold_script`. The script runs as you, outside the agent's sandbox, and only when you pass `--scaffold`
  retrieved: 2026-10-08
- id: C45
  claim: A plugin eval case can resume a recorded transcript, with the case prompt as the next user turn.
  source: https://code.claude.com/docs/en/plugin-evals.md
  tier: 1
  quote: A `.jsonl` transcript in the case directory to resume. The case's prompt becomes the next user turn
  retrieved: 2026-10-08
- id: C46
  claim: The check scripts take the project root from CLAUDE_PROJECT_DIR, else the git top level, else the working directory.
  source: file:scripts/groundwork_config.py
  tier: 1
  quote: The project root: $CLAUDE_PROJECT_DIR, else the git top level, else cwd.
- id: C47
  claim: check_citations.py can print its results as JSON.
  source: file:scripts/check_citations.py
  tier: 1
  quote: parser.add_argument("--json", action="store_true", help="print results as JSON")
- id: C48
  claim: check_ac_coverage.py returns 2 when the project has no .groundwork/config.json.
  source: file:scripts/check_ac_coverage.py
  tier: 1
  quote: print("no .groundwork/config.json in this project; run /dev-groundwork:setup", file=sys.stderr) return 2
- id: C49
  claim: detect_workarounds.py falls back to the default config when none exists.
  source: file:scripts/detect_workarounds.py
  tier: 1
  quote: config = load_config(root) or DEFAULTS
- id: C50
  claim: The state directory is .groundwork/state.
  source: file:scripts/groundwork_config.py
  tier: 1
  quote: STATE_DIR = Path(".groundwork") / "state"
- id: C50b
  claim: The test lock file is named tests-locked under the state directory.
  source: file:scripts/groundwork_config.py
  tier: 1
  quote: TEST_LOCK = STATE_DIR / "tests-locked"
- id: C51
  claim: A PreToolUse hook entry in hooks.json matches Edit, Write, MultiEdit, NotebookEdit and Bash.
  source: file:hooks/hooks.json
  tier: 1
  quote: "PreToolUse": [ { "matcher": "Edit|Write|MultiEdit|NotebookEdit|Bash",
- id: C52
  claim: The commit gate recognises git commit, including with -C or -c options.
  source: file:scripts/hook_commit_gate.py
  tier: 1
  quote: GIT_COMMIT = re.compile(r"(^|[\s;&|(])git(\s+-[cC]\s+\S+)*\s+commit(?=$|[\s;&|)])")
- id: C53
  claim: When the project checks fail, the commit gate's deny reason says the commit was not made.
  source: file:scripts/hook_commit_gate.py
  tier: 1
  quote: f"Project checks failed (`{check}`), so the commit was not made. Fix the cause, not the check.
- id: C54
  claim: tests/test_scripts.py defines a Repo class, a throwaway git repository with a groundwork config.
  source: file:tests/test_scripts.py
  tier: 1
  quote: class Repo: """A throwaway git repository with a .groundwork/config.json."""
- id: C55
  claim: The pr-map test helpers define MapRepo as a subclass of Repo.
  source: file:tests_pr_map/helpers.py
  tier: 1
  quote: class MapRepo(Repo):
- id: C55b
  claim: The pr-map test helpers import Repo and git from tests/test_scripts.py.
  source: file:tests_pr_map/helpers.py
  tier: 1
  quote: from test_scripts import Repo, git
- id: C56
  claim: The CI workflow runs the unit tests under tests/.
  source: file:.github/workflows/ci.yml
  tier: 1
  quote: python -m unittest discover tests -v
- id: C57
  claim: The marketplace entry's source is the repository root.
  source: file:.claude-plugin/marketplace.json
  tier: 1
  quote: '"name": "dev-groundwork", "source": "./",'
```
