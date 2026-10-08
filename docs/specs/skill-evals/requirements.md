# Requirements: skill-evals

- Status: draft
- Requested by: the owner, 2026-10-08: "The eval piece is important - we
  want to be able to measure and prove fidelity. Let's adapt the parts they
  do better", after a review of addyosmani/agent-skills, whose skills are
  checked by behavioural evals that dev-groundwork lacks.

## Problem

dev-groundwork's scripts and hooks check what an agent produces, and their
unit tests prove the scripts work. Nothing proves the skills themselves
work: that an agent running `test-first` actually shows a failing test
before the fix, or that `implement` leaves locked tests alone when told a
test "looks wrong". A wording change to a skill, or a new model, can make a
skill stop working and nobody would know. The owner wants fidelity
measured: did the agent follow the skill's process, and does the skill make
a difference compared with no skill at all.

## Decisions from the interview (2026-10-08)

- Fidelity means the process was followed, graded deterministically from
  what the run left behind, not by a model.
- Proof is a comparison: each case runs with the plugin and without it.
- 5 runs per arm; a case passes with the plugin at 4 of 5 or better.
- Every skill gets a pressure case (deadline, authority, sunk cost).
- Routing is tested too: a skill fires when it should and stays quiet when
  it should not.
- A pinned model by default; model and Claude Code version recorded per run.
- A run that breaks (timeout, API error) is an error, never a pass or fail.
- A spending cap stops the suite from starting new runs.
- Conversations use scripted user replies.
- Runs happen on demand and before releases; results are committed.

## Acceptance criteria

Cases

- **AC-1** The suite shall read eval cases from files that define, for each
  case: the skill under test, a fixture workspace, a prompt, optional
  scripted user replies, a kind (`normal`, `pressure`, `fires` or `quiet`),
  and its checks.
- **AC-2** When the suite runs a case, it shall copy the fixture into a new
  git repository with one baseline commit, outside this repository, so every
  run starts from the same state and no run sees another run's changes.
- **AC-3** Version 1 shall include, for each of `test-first`, `debug`,
  `implement`, `research`, `review` and `requirements`, at least one
  `normal` case and one `pressure` case whose prompt applies deadline,
  authority or sunk-cost pressure to skip a step of the skill.
- **AC-4** Version 1 shall include, for at least `debug`, `test-first` and
  `review`, one `fires` case, where the skill should be used without being
  named, and one `quiet` case, where it should not be used.

Running

- **AC-5** The suite shall run each `normal` and `pressure` case 5 times
  with the plugin installed and 5 times without it, and each `fires` and
  `quiet` case 5 times with the plugin. The run count shall be configurable.
- **AC-6** The suite shall run on one pinned model by default, accept
  another model as an option, and record for every run the model ID and the
  Claude Code version used.
- **AC-7** Where a case scripts user replies, the suite shall give the agent
  those replies in order when it asks for input. If the agent asks more
  times than there are replies, then the suite shall answer "No further
  input." and record that it did.
- **AC-8** Each run shall have a turn limit and a time limit, set per case
  with a suite default.
- **AC-9** When a spending cap is given, the suite shall start no new run
  once the cap is reached, and the report shall list the runs that were
  not started.
- **AC-10** The suite shall be started by one command, which can limit a
  run to named skills or cases.

Grading

- **AC-11** Every check shall be graded deterministically from the run's
  artifacts: the workspace's git history and files, the output of
  dev-groundwork's own check scripts run on the workspace, and the tool
  calls recorded in the run's transcript. No check shall be graded by a
  model.
- **AC-12** A run shall pass only when every check of its case passes, and
  the result shall name each failed check with its evidence (for example
  the commit or tool call that broke it).
- **AC-13** If a run does not complete (timeout, turn limit, API error,
  crash), then it shall be recorded as an error: neither pass nor fail, and
  left out of the rates.
- **AC-14** If more than one run of a case in one arm is an error, then the
  report shall mark that case inconclusive for that arm instead of giving a
  rate.
- **AC-15** Each check shall have a test that shows it failing on a
  workspace or transcript that breaks its rule, and passing on one that
  follows it.

Results

- **AC-16** The suite shall append each run's result to a results file
  kept in this repository: case, skill, arm, pass, fail or error, failed
  checks with evidence, model, Claude Code version, date, duration and,
  where available, cost. Earlier results shall never be overwritten.
- **AC-17** The suite shall print a summary: for each case, the pass rate
  with the plugin, the pass rate without it and the difference;
  inconclusive cases; and, per skill, whether every case passed with the
  plugin at 4 of 5 or better.

Checks without tokens

- **AC-18** On every pull request, CI shall validate the case files (well
  formed, fixtures present, every named check known) and run the checks'
  own tests from AC-15, without starting an agent.

Safety

- **AC-19** An eval run shall work only inside its temporary workspace,
  and shall not receive this repository's secrets or the owner's
  credentials other than what running the agent needs.
- **AC-20** If a fixture or prompt contains instructions aimed at the
  grader, then they shall have no effect: grading reads artifacts with
  scripts and never asks a model.

## Out of scope

- Model-graded checks of outcome quality (for example "is this review
  well written"). Version 1 measures whether the process was followed.
- Running evals in CI on a schedule or on every pull request; only the
  token-free checks in AC-18 run in CI.
- Evals for `design`, `acceptance-tests` and `setup`.
- A model playing the user; replies are scripted.
- Comparing models automatically; another model can be passed by hand.

## Open questions

- How the suite installs the plugin for one arm and not the other, and how
  it reads tool calls and costs from a headless run: the research stage
  checks `claude -p` output formats and `claude plugin eval`. (owner:
  research stage)
- Whether `claude plugin eval` can host these cases directly, so the suite
  is a set of cases and graders rather than a runner. (owner: research
  stage)
- The pinned model and the default cap. (owner: the owner, after research
  shows what a suite run costs)
