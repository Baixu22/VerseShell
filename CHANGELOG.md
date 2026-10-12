# Changelog

## Unreleased

### Round 14 — task set v3.0.0, live-chain repairs, two new gated claims

- **Frozen task set v3.0.0: 35 tasks (10 hand-written + 25 generated and admitted).**
  `eval/task_set_freeze.json` now reports the promoted/kept-existing split from each
  shipped task's own metadata instead of from "what this run happened to promote", so
  the record can answer *which* tasks are hand-written (10) and *which* are generated
  (25) no matter how many promotion runs happened. `per_tier` stopped folding
  generated-but-untagged tasks into a bucket named `existing` (that bucket merged 10
  generated tasks with 10 hand-written ones and made the tier composition unreadable);
  it now reports `handwritten` / the declared tier / `untiered_generated` separately.
  The record also carries a `holdout` block: the 10 tasks promoted in this batch are the
  holdout, because they were generated *after* C30 and D1–D7 were found and fixed on the
  previous set — the previous 25 cannot serve as a holdout for defects found on them.
  The pre-registration asked for 30 generated; **25 were admitted**. The five missing
  slots are all `large` (rust 5/6/7, typescript 9/10) and all failed A8's
  `>=1000-token pristine observation` gate at 277–590 tokens, while the same batch's
  python large tasks reached 1559–3496. Two structural reasons are recorded in
  `docs/task-generation-protocol.md` §4.7: a plain-node `check.mjs` aborts at the first
  failed assertion so the remaining failures never print, and `cargo test` prints short
  per-test summaries rather than pytest-style long diffs. Large-tier share is therefore
  **7/35 = 20%**, still under the pre-registered 1/3 (it was 16%). Recorded, not smoothed.
- **`lang` labels unified in `bench/aci/tasks/*.json`.** `ts` → `typescript` and
  `windows` moved out of the language field (`platform` already carried it) → `shell`.
  Verified first that no gate reads `lang`: `ts_fixture_audit` keys off task *ids*, and
  C23/C29 use ids and `kind`. Distribution is now python 13 / rust 6 / typescript 4 / shell 2.
- **Claim C34 — mixture-invariant envelope saving, pre-registered.** C14/C16 gate the
  saving as a share of the whole read bucket, and that share moves with the read mix
  (after C30 the mix became content-dominated, so the same projection showed 8.3% of the
  total while removing ~half of the named overhead). Rather than move those thresholds
  after seeing the data, `docs/acceptance-criteria.md` §4.5 registers a *separate* claim:
  `(legacy(line_wrapper+counts) − current(line_wrapper+counts)) / legacy ≥ 0.40`, read
  from `eval/read_path_breakdown.json`. **The "must be verified on a task set newer than
  2.0.0" requirement is part of the gate**: C34 reads `task_set_version` and fails while
  the artifact still comes from 2.0.0, even though the ratio (0.594) clears the bar. C14
  and C16 keep their original thresholds and stay FAIL.
- **Claim C35 — the paired control arm must match the with arm in composition.**
  C12 fingerprints each artifact against the *code*, so an artifact built on a stale
  *input* still reads fresh — and the without-arm control is deliberately outside C12's
  fingerprinted list. C35 compares the two arms on seed set, task set, row count,
  `git_rev` and `task_set_version`, and requires zero `api_error` rows. Negative control
  run: dropping seed 44's rows from the control makes C35 FAIL with
  `seed sets differ: with=[42, 43, 44] without=[42, 43] | row counts differ: with=225 without=150`
  (`audit-r12-scratch/evidence_negctl_C35.json`, `--without-arm` override added for it).
- **Round-14 difficulty targets pre-registered** (`docs/task-generation-protocol.md` §4.6),
  written before any round-14 result existed: baseline success rate in **0.40–0.70**,
  `MDE / headroom ≤ 0.50`, large-tier share **≥ 1/3**, holdout **≥10** never-tuned tasks.
  The reason is arithmetic: round 13's A/A′ success rates were both 0.8400, leaving 0.16
  of headroom against a pre-registered MDE of 0.15 — 94% of the headroom.

### Fixed
- **`tools/run_task_plan.py` declared convergence while slots were still empty.** The
  slot counter collected the `plan_index` of *every* candidate under
  `bench/aci/candidates/` and never intersected it with the current plan, so the 15-slot
  remainder plan was scored against unrelated FULL_PLAN candidates: `absent` reached
  **−19** and the driver printed *"all 15 plan slots have an admitted candidate"* and
  exited 0 with **10/15 actually covered**. It now counts per *slot* (a slot is covered
  when any of its candidates was admitted) and intersects with the plan's own indices.
  The "25/30 generated" numbers in §4.7 come from the corrected counter.
- **`tools/task_generate_v2.py`, four defects that each wasted a whole slot or run.**
  (1) A spec-step reply that named a *path* as the module (`src/lib.rs`) was pasted into
  `Cargo.toml` as the package name, so all three test attempts failed to compile and the
  slot was skipped; the name is now reduced to a bare identifier. (2) The `correct`
  module was never checked for *compiling* on its own — a truncated module (dangling doc
  comment) burned three *test* attempts and then skipped the slot without ever telling
  the model its module was broken; a minimal smoke suite now gates it and regenerates the
  module. (3) Variants were written to `<tid>/variants/` while `task.json` went to
  `<tid>_<seed>/` (the variant directory's creation made the later `cdir.exists()` branch
  fire), so A3 saw **zero** variants and rejected otherwise-passing candidates — the
  candidate directory is now chosen before anything is written. (4) A rust variant's
  `src/lib.rs` had no parent directory, crashing the generator process with
  `FileNotFoundError` and losing the whole round.
- **`tools/claim_gate.py` gained `--without-arm`** so C35's negative control can point the
  gate at a deliberately mismatched control, matching the existing override pattern of
  C28/C33.

### Added
- **Frozen task set v2.0.0: 25 tasks (10 existing + 15 generated and admitted).**
  `eval/task_set_freeze.json` records the exact task list, the promoted ids, the
  per-tier counts and a content fingerprint over the tasks and fixtures, so "the
  task set was frozen before measurement" is checkable rather than asserted. The
  pre-registration asked for 30 generated tasks; **15** were admitted, because the
  endpoint's empty-completion rate makes generation slow and intermittent (see the
  protocol's engineering section). The composition rules were not relaxed — 3
  languages, every generated task has ≥2 independently written correct variants
  verified to pass, and each was locally self-checked (tests pass on the correct
  module, fail on the buggy one) before being written. Two consequences are
  recorded honestly rather than smoothed over: the large-observation share is
  **16% (4/25), below the pre-registered 1/3**, so the token claim still rests
  mostly on small observations; but the sample is adequate — 25 tasks × 5 seeds =
  **125 pairs**, above the ~122 the token L2 claim needs.
- **Task-generation pipeline + claim C29**: `tools/task_generate.py` builds  candidate tasks with an LLM under an independence protocol (the generation
  prompt carries no VerseShell/ACI context; correct variants are written by models
  that never see the golden patch, at least one from a different model family),
  and `tools/task_admissibility.py` decides mechanically whether a candidate may
  enter the capability set: pristine fails, GOLDEN passes, ≥2 independently
  written correct answers pass, **neutering the task's own verifier must still
  fail**, verdicts are stable, the prompt does not quote the golden diff, and
  provenance is declared. `docs/task-generation-protocol.md` pre-registers the
  composition (≥30 tasks, ≥3 languages, ≥4 categories) and the freeze rule that
  forbids adding or removing tasks after seeing token results.
  The first pilot rejected its own candidate for a real reason: the prompt said
  "do not change `test_batches.py`" but nothing enforced it, so replacing that
  test with `assert True` made the predicate pass — the task measured nothing. It
  is also why the LLM-produced "shortcut" is informational rather than a gate:
  the model asked to cheat *wrote a correct fix instead*, so "shortcut passed"
  cannot distinguish a gameable predicate from a model that declined to game.
  The fix needs no product change (a `file_contains` guard on a distinctive line
  of the verifier suffices), so the live evidence chain is not invalidated.
  A pre-registered 10-candidate pilot then ran the whole pipeline end to end:  **9 candidates written in 30.1 min**, **20/20 independently written correct
  answers parsed** (two different model families, neither shown the golden patch),
  and **10/10 admitted** with A1–A7 all passing. The 0% rejection rate is not a
  dead gate — stripping the guard from an admitted candidate and re-auditing makes
  A4a reject it immediately, so the generator had simply learned the requirement
  from the system prompt. The pilot's real result is a **construct-validity**
  finding: the tasks it produces are the same size as the existing ones (mean
  78 lines), and the measured observations are tiny (per-call p50 **25–28**
  observation tokens, per-run p50 ~122–128), so the ACI's actual claim — shrinking
  *large* build/test output — is barely exercised. Expanding 10 tasks to 30 of the
  same shape would raise power without fixing that, so the protocol now
  pre-registers a **size tier** (≥1/3 of tasks must drive raw-shell observations
  to ≥1000 tokens per run) and forbids calling any small-observation ratio "the
  ACI saves tokens".
- **Decomposed generator `tools/task_generate_v2.py` + `tools/run_task_plan.py` +
  `tools/freeze_task_set.py`.** The one-shot generator is infeasible on this
  endpoint for a measured reason: asked to design a task plus fixture plus golden
  plus predicate in one completion, the model spent **16381 of 16384** completion
  tokens on `reasoning_content` and emitted **0 characters** — and a larger cap is
  unavailable because a request past ~300s returns 502. v2 splits the job into
  low-reasoning steps (spec → buggy file → fixed file → failing tests), asks for
  *code blocks* rather than nested JSON, and assembles the predicate **in
  program** from the command plus a guard line lifted from the generated test
  file, so the verifier guard can no longer be forgotten. `run_task_plan.py`
  converges generate-then-gate over multiple rounds (a gate-rejected candidate is
  deliberately *not* treated as done, so its plan slot can be regenerated), and
  `freeze_task_set.py` promotes only admitted `kind=capability` candidates and
  writes an `eval/task_set_freeze.json` fingerprint record, making "the task set
  was frozen before measurement" checkable instead of asserted.
- **Acceptance criteria + claim C28 + `tools/acceptance_power.py`**: a
  pre-registered answer to "when are we allowed to make this claim at all?".
  `docs/acceptance-criteria.md` fixes the MDE (success difference: 0.15
  absolute), the precision targets (the token-ratio ladder), the control-group
  design, and an anti-pattern list; `acceptance_power.py` re-derives the required
  sample from the stored variance and refuses to let an interval that does not
  clear its threshold be quoted as a result. Its sharpest rule: when the point
  estimate is already on the wrong side of a cap, **more data cannot rescue the
  claim** — it is reported as a product gap, not a data gap. Applied to the
  current baseline it records that the success-rate difference is underpowered
  (30 pairs vs 45 needed; at n=30 only |Δ|≥0.187 is detectable and 0.067 was
  observed), that "D is cheaper in observation tokens" is short by 7 pairs, that
  "saves ≥15%" needs ~122 pairs, that the frozen ≤0.60 target is a **product
  gap**, and that the only currently claimable items are the cross-shell ones
  (5/5 operations strictly faster and >2× faster, worst case 0.2535 with CI95
  [0.2424, 0.2704]).
- Claim C27 + `tools/token_proxy_calibration.py`: every observation-token number
  in this repo (the D/A ratio, claims C13–C17, C19, C20) comes from
  `estimate_tokens(text) = max(1, len(text)//4)`, which had **never** been
  validated. This calibrates it against a real BPE tokenizer (`cl100k_base`) on
  the observation texts replayed from the stored live run, and the measured
  verdict is that the proxy is **not** an upper bound: on these JSON/code
  envelopes it **under-counts by ~33%** (mean `real/proxy` 1.5617, 59/60
  samples above 1). The error is shape-dependent, so no single correction factor
  exists — English prose is *over*-counted 12–39%, while a hex digest is
  under-counted 1.8×, base64 2.6× and CJK 4.1×. The tool also documents that the
  **endpoint's own `usage.prompt_tokens` is unusable as ground truth**: it is
  cached per input content (the same text returns the same value even when that
  value is wrong) and a large fraction of cache-missing requests are inflated by
  a constant ~+171, which the tool neutralises with a unique nonce per request
  and a min-over-draws estimator.
- Claim C26 + `tools/projection_contract.py`: the reference client
  (`format_aci_result`) must project the payload each tool's own description
  promises. It runs six real ops through `ae --serve --agent` and checks what
  actually reaches the model, and it exists because real calls showed three
  fields being silently dropped — see Fixed below.
- Claim C25 + `tools/live_uncertainty.py`: every live number now carries an
  interval. Wilson intervals per success rate, a pooled z-test and a paired
  **McNemar** test on `(task, seed, run_index)` cells, paired t intervals for the
  continuous metrics, a bootstrap interval for the headline D/A ratios with
  `P(ratio < frozen target)`, and a recomputation of each stored aggregate from
  `rows[]` (so an aggregate cannot drift from its rows). It gates the *presence*
  of uncertainty, not its favourability: on the current sample it reports that the
  A/D success-rate difference is **not significant** and that the frozen ≤0.7 /
  ≤0.6 targets are not met with any confidence — which is the honest result, and
  still passes.
- Claim C5 now has a metric instead of a status. `tools/aci_learning_probe.py`
  gives a real model **only** `docs/quickstart/aci-mcp.md` as its system prompt
  (no tool schemas), asks for JSON-RPC op lines, executes every emitted op through
  the real server, and checks the workspace against the task predicate. Gated
  number: first-attempt op acceptance **conditional on the agent emitting a
  documented shape** (so a model that answers in prose is reported separately
  instead of being scored as a rejected contract). Real-call result: **0.4 before
  the quickstart fix → 0.8 after**.
- `--max-tokens` on the live runner (default raised 4096 → 16384), and every row
  now records `completion_truncated_turns`.
- Claim C21 + `tools/ts_fixture_audit.py`: a deterministic audit of the two
  boundaries around `ts_fix_type_error`. It splits the task's toolchain chain
  (15 `exec.run` calls / 754 tokens over three D runs) into **6 calls / 288
  tokens lost to bare `npm` / `npx`** — this machine has an extensionless POSIX
  shim on PATH, `resolve_candidate` returns it before trying PATHEXT, and Win32
  cannot launch it — **6 calls / 457 tokens** spent on the missing
  `node_modules` plus the install workaround, and the **3 calls / 9 tokens** the
  task actually needs. Dropping D's share moves the D/A step ratio 1.402 → 1.278
  and the token ratio 0.876 → 0.753 without flipping either conclusion, so the
  task set is deliberately left unchanged and the boundary is registered
  instead. The same audit re-scores the declared success predicate against the
  file each run left behind: it is a literal GOLDEN match, and **5 of 6 runs
  fixed the type error yet failed it** (D 0/3, A 1/3).
- `file.read_many` on-demand windows: `windows[]` gives each file its own
  `{start_line, window}`, and `max_total_lines` (default 240) bounds the whole
  batch. An entry cut by its own window is `truncated`, one that no longer fits
  the budget comes back `deferred`; both return `next_start_line`, so a bounded
  batch stays paginable instead of silently dropping files.
- Read ops (`file.view` / `file.read_range` / `file.read_many`) return a compact
  `hash` (16 hex chars) next to the full `content_hash`, and `expected_hash` now
  accepts any unambiguous hex prefix of at least 8 characters. The stale-write
  check is unchanged in strength (a wrong prefix still fails with
  `E_STALE_HASH` + `data.actual_hash`), but an observation stops paying 71
  characters per file for a digest the agent only hands back. Additive: an
  existing consumer that reads `content_hash` keeps working.
- Claim C14 + `tools/tf45_envelope_replay.py`: a deterministic replay that pins
  the read calls the model actually issued in the stored live run, re-runs them
  against the current binary, and projects each envelope twice (legacy full
  digest vs compact digest). It measures the observation surface, not model
  behaviour, and lists every call it could not reproduce with both token counts.
- `bench/aci/runners/merge_live_runs.py`: merging per-seed live runs now refuses
  to merge when any row carries `api_error` (exit 2), instead of letting an
  upstream 500 into the average as a 0-tool / 0-token data point.
- `file.read_many`: read up to 8 files in one call, each entry carrying its own
  `content_hash` / `total_lines` / line window; a missing path is reported in its
  own entry instead of failing the batch. It gives an agent the single call raw
  shell gets from `type a & type b`, instead of N separate `file.view` calls.
  Exposed to the live benchmark as the `read_files` tool.
- Live runner: `--exclude-tools` (hide a tool from condition D to A/B it on the
  same model) and an `api_error` flag on every row, so an upstream outage can
  never be averaged into the benchmark as a 0-tool / 0-token data point.
- Live runner sampling controls: `--temperature` (default 0), `--seed`, and
  `--repeat N`; every row carries `run_index` and `live_config` records all
  three, so a live result can be repeated and quoted with a spread instead of a
  single sample.
- Live ACI-Bench evaluation is actually usable: the runner now starts the AE
  server with an explicit capability set (`--cap`, overridable via `--caps`).
  Before this, condition D ran with **no** grants, so every ACI op returned
  `E_CAPABILITY_DENY` and the D condition never executed a single operation.
- Live artifacts (`bench/aci/results/latest_live.json`) record `live_config`
  (model / api_base / caps / max_turns / tasks / conditions) plus the code
  fingerprint, and are covered by claim C12.
- Claim C13 registers the live A-vs-D result separately from the mock C1/C2:
  on one real model (10 tasks x 2 conditions, two full runs) condition D used
  ~2.0-2.6x the tool calls and ~2.0-2.6x the observation tokens of raw shell at
  the same 0.6 success rate — the ACI did not reduce steps or tokens there.
  Single-run variance is large, so the direction is the finding, not the ratio.

### Changed
- **C14 and C16 now register as NOT meeting their thresholds, and the thresholds were
  deliberately left alone.** Both are client-side envelope optimizations whose benefit
  is proportional to *envelope overhead*, not to content. On the post-C30-fix v2.0.0
  read mix the measured savings are **5.1%** and **8.3%** against registered **15%**
  and **10%**. The mechanism, stated mix-invariantly: the compact projection removes
  **45.5% of the named envelope overhead** (`line_wrapper` plus the derivable
  `counts`), but overhead is now only ~18% of the payload because D finally receives
  real file content, so the total-bucket percentage falls. This is a **mix change, not
  a code regression** — the v1.3.0 read mix was overhead-dominated and measured 20.4%.
  Moving a registered threshold after seeing the number is the exact failure mode this
  repo exists to prevent, so `claim_gate` is **red on C14 and C16**, and both claims
  are annotated with the failing number *and* the mix-invariant one. Whether to
  re-register them against envelope overhead (rather than the total read bucket) is a
  product decision that needs the threshold changed deliberately in
  `docs/claims-and-evidence.md` and `tools/claim_gate.py` with the reason recorded.

  Final gate state after a full refresh: **22/24** (C14, C16 failing).

### Fixed
- **The reference client withheld file content from the model, which invalidated
  the headline D-vs-A comparison (claim C30).** `format_aci_result` gated its read
  projection on `len(lines) <= 10`: any window longer than ten lines was dropped
  entirely, leaving only `{ok, content_hash, total_lines}`. `file.view`'s default
  window is **80**, so a plain `file.view` of any real source file handed the model
  a hash and nothing else — while the tool description promises "a window of lines
  around a cursor". Measured on the v2.0.0 live run: **180 of 204 `file.view` calls
  returned metadata only**, **45% re-viewed a path the agent had already viewed**
  (because the first look showed nothing), and D fell back to `repo.search`
  (**301 calls / 65.7k tokens**) plus shell reads to see file content at all. That
  is the client starving the agent, not an ACI cost. The fix carries the window the
  tool actually returns (`file.view` and `file.read_many`), and the tool's own
  `window` clamp is the only bound.

  The reason this shipped unnoticed is the more useful lesson: `tools/projection_contract.py`
  tested `file.view` on a **3-line** fixture, which fell inside the ten-line cutoff,
  so the check was green while the defect was live. Two checks using a **60-line file
  with default arguments** were added, **with a negative control** — restoring the old
  rule makes them FAIL — and C30 is gated separately so a too-small fixture cannot
  hide it again. `tools/three_arm_report.py` and the fixed projection mean the live
  run must be re-measured; until then the v2.0.0 numbers in C13/C16 are known to be
  contaminated by this defect and are labelled as such.

  **The re-measurement reverses the headline result.** With the client fixed
  (25 tasks × 3 conditions × 3 seeds = 225 rows, 0 API errors, and — for the first
  time — **0% cap binding on all three arms**):

  | arm | at cap | success | tools | obs tokens |
  |---|---|---|---|---|
  | `raw_shell` (A) | 0% | 0.7067 | 3.60 | 888.1 |
  | `raw_shell_coached` (A') | 0% | 0.6667 | 3.72 | 576.0 |
  | `verseshell_aci` (D) | 0% | **0.8267** | 3.63 | 608.6 |

  D's success is now **above** both baselines (+0.12 vs A, 16 D-only wins vs 7;
  +0.16 vs A'), its observation tokens are **significantly below A** (D/A = 0.6853,
  CI95 [0.5601, 0.8551] — entirely below 1.0), and it is **indistinguishable from A'
  on tokens** (D/A' = 1.0567, CI95 [0.8435, 1.379] — crosses 1.0). Tool counts are
  now equal across arms; the previous "D uses 3× the calls" was entirely the
  starved-client artifact. The honest statement is therefore narrower than either
  earlier round: **the ACI solves more tasks than a raw shell and uses fewer
  observation tokens than an un-prompted one, but under a prompt-matched control its
  token advantage disappears** — so "the interface itself saves tokens" remains
  unproven, while "it succeeds more often" is now supported.
- **The live turn budget (`max_turns=8`) bound condition D far more than A, which
  confounded the whole D/A comparison.** Measured on the frozen 25-task set:

  | arm | runs hitting the cap | avg tool calls |
  |---|---|---|
  | `raw_shell` (A) | **0/25 = 0%** | 3.04 |
  | `raw_shell_coached` (A') | 3/25 = 12% | 3.84 |
  | `verseshell_aci` (D) | **16/25 = 64%** | 8.12 |

  D was truncated in two thirds of its runs and A never was, so D's success rate
  and token count were only a post-truncation lower bound — the comparison
  measured call granularity, not the interface (typed ops are finer-grained, while
  one shell command can read, edit and run at once). This is the same class of
  defect as the 4096 completion cap recorded earlier, and it is now a
  pre-registered control-validity requirement in
  `docs/acceptance-criteria.md` §0.5: measure each arm's cap-binding rate before
  the definitive run, treat >10% on any arm as the cap being binding, raise it,
  and always report the three rates next to the headline numbers. The run was
  redone at `max_turns=20`.
- **Condition A was handed a prompt for tools it does not have, which biased every
  previous D/A comparison in D's favour.** Condition A is `run_command`-only
  (`RAW_SHELL_TOOLS = [run_command, task_complete]`), yet both conditions received
  the *same* system prompt, whose rule 0 says "`read_file` output IS the
  authoritative file state" and whose rule 7 says "`run_command` is for
  BUILD/TEST/INSTALL only. **Use `read_file` to read files.**" For condition A that
  is self-contradictory: it is told to use a tool that does not exist and told not
  to use its only tool for reading. The stored live evidence shows A did read
  through `run_command` anyway (`type`-style commands account for ~58 observation
  tokens per run), so the model partly ignored it — but the briefing was unfair and
  the baseline cannot be called a best-effort raw shell while that prompt is in
  place. Each condition now gets a prompt that matches its own tools:
  `raw_shell` → `SHELL_SYSTEM_PROMPT` (shell-neutral, same rule count),
  `verseshell_aci` → the ACI prompt. Every row records `prompt_profile` so a result
  can always be attributed to the briefing that produced it, and the comparison now
  emits two contrasts: `D_over_A` (status quo) and **`D_over_A_coached`**.
- **Added the missing prompt-matched control arm (`raw_shell_coached`).** Claim C1
  needs to separate "the interface saves tokens" from "the prompt was written
  better". `COACHED_SHELL_PROMPT` has the same rule count and comparable length as
  the ACI prompt, but its output-budget rule is written in *shell* terms ("pipe
  through `more`/`head`, use `findstr`/`Select-String`, read one region at a time")
  instead of ACI terms. Only `D_over_A_coached` can be attributed to the interface.
  `tools/acceptance_power.py` now reports
  `token_ratio_coached_level1_D_cheaper`, and claim C28 requires it to be present
  (it is reported as not claimable until the arm is actually run).
- **The reference client silently dropped three payloads the tools promise, so
  condition D was being handicapped.** `format_aci_result` is what an agent
  actually sees. Real calls through `ae --serve --agent` showed:
  1. **`repo.search`** (exposed as `search_content`, described as "Returns
     matching files and lines") projected to only `{"ok": true}` on success — every
     match discarded. An agent that searched learned nothing, re-issued the call,
     then fell back to a raw `grep` inside `exec.run`. In the stored runs the op
     was called 2× at 3 observation tokens each; no with-arm run used it at all,
     while the raw-shell arm ran `grep`-style commands 11×. Now projected as
     `{match_count, matches:[{path,line,text}], truncated}`.
  2. **`repo.summary`** (exposed as `list_files`, described as "branch, dirty
     files, top-level directory listing") dropped `top_level` — the listing half of
     its own promise. Now projected, while deliberately *not* leaking the host
     `workspace` path.
  3. **`E_AMBIGUOUS`** carried structured `data.matches[]` (line/offset/snippet) in
     the server envelope — the payload claim **C4's one-step recovery depends on** —
     but the failure branch returned before copying it, so the model never saw the
     candidate sites. Now projected.
  Claim C26 + `tools/projection_contract.py` gate all three against the real
  server, and assert the projection never leaks the host workspace path.
- **The live runner's 4096-token completion cap truncated condition D far more
  than condition A, biasing the headline comparison.** The endpoint serves a
  reasoning model whose `reasoning_content` is billed as completion tokens; at a
  4096 cap the reply was cut off before any tool call was emitted, and such a row
  was then scored as an ordinary task failure. Measured on one full round: **7/30
  condition-D rows hit the cap, 0/30 condition-A rows** — D carries the larger
  prompt (tool schemas + envelopes), so the truncation was systematically
  anti-D, understating D's success rate while flattering D's token ratio (a
  truncated row observes little). The cap is now 16384 and configurable via
  `--max-tokens`, and each row records `completion_truncated_turns` so the
  artifact reports how many rows the cap, rather than the model, decided. The
  per-request HTTP timeout had to be raised with it (180s → 900s): once the cap
  allowed a longer generation, the *same* requests legitimately exceeded the old
  timeout and came back as `api_error: timed out` — three seeds in a row on one
  task — so the two budgets have to move together.
- **The quickstart's read→edit example told a doc-only reader to send a
  placeholder.** `docs/quickstart/aci-mcp.md` contained
  `"expected_hash":"<from file.view>"`, and a model given only that document
  copied the placeholder verbatim, earning `E_STALE_HASH` in 1 of 5 probe cells
  (the `hash_handoff` half of C5 measured 1.0 before the fix, 0.0 after — it was
  copying text, not handing back a digest). The example now shows a real 16-hex
  digest and states explicitly that the value must come from the preceding read.
- **`exec.run` could not launch a bare `npm` / `npx`.** npm-for-Windows ships an
  extensionless `npm` (a `#!/bin/sh` script) beside `npm.cmd`, and
  `resolve_candidate` returned the bare file whenever it existed — only then trying
  PATHEXT. Win32 cannot launch the shell script, so `exec.run(["npm", ...])` and
  `["npx", ...]` failed with `E_EXEC_SPAWN` while raw shell (which spawns through
  `cmd`) worked: condition D paid a wasted call plus ~48 observation tokens on
  every npm task, and `ts_package_script_fail` failed one `npm test` in all three
  seeds before falling back to `npm.cmd`. The resolver now tries PATHEXT first for
  a candidate without an extension and keeps the extensionless file as a fallback.
  Claim C22 re-runs every bare name that PATH shadows (plus its `.cmd` control)
  through the real `exec.run`, fail-closed. Verified: `npm` / `npx` / `yarn` /
  `pnpm` / `corepack --version` all exit 0, and C18's rustup shim invariant still
  holds. The stored live evidence predated the fix, so it was re-measured in the
  same round (see the next entry).
- **Re-measured after the PATHEXT fix** (120 rows, `api_error` 0, seeds 42/43/44,
  same model `sn-glm-5-3-flash`): condition D fell to **3.77 tool calls and 144.8
  observation tokens per run** (from 4.53 / 177.3), with raw shell at 3.10 / 180.9
  — a D/A tool ratio of **1.215** and a token ratio of **0.801**. `exec.run`
  dropped from 50 calls / 2121 tokens to **33 / 917**, and failed execs from
  21 / 1735 to **5 / 495**: the six bare-`npm`/`npx` launch failures C21 had
  counted are gone, and `ts_package_script_fail` now passes `npm test` on the
  first try (5 steps / 172 tokens -> 4 / 137). D's success rate this round
  (0.50 against A's 0.6333) is **not** attributable to the fix: three
  `python_fix_pytest_fail` runs spent their entire output budget on reasoning
  (0-1 tool calls), two `python_noisy_install_summary` runs missed the file
  predicate, and the previous baseline had the same mechanism in two other rows.
  The paired `--exclude-tools read_files` arm is noisier still (one raw-shell row
  at 16007 tokens dominates its A mean), so only the with-arm ratios are quoted.
- **The `ts_fix_type_error` task now scores behaviour, not the golden patch's
  text.** Its v1.1.0 predicate was `file_contains "return a + b"`, so a run that
  fixed the type error by keeping the intermediate binding was scored as a
  failure: re-scoring the six stored runs shows the old predicate rejected every
  passing fix (D 0/3, A 1/3) while a real `tsc --noEmit` passes **3/3 in both
  arms**. The fixture now ships a pinned TypeScript (`deps/typescript-5.4.5.tgz`,
  extracted offline into `node_modules/typescript` with `.bin` shims by
  `bench/aci/runners/fixture_deps.py`), the predicate runs that compiler, and
  claim C23 checks that the pristine fixture still fails it and the GOLDEN patch
  still passes — so the task can neither become pre-solved nor unsolvable. The
  live runner no longer writes `"optional_verify": None`: it records that the
  declared optional check was not run separately, and `check_success` can now
  return *unverified* (excluded from the success rate) when a required command is
  missing. `task_set_version` moves to 1.2.0.
- **Re-measured on the v1.2.0 task set** (120 rows, `api_error` 0, `unverified`
  0): condition D scores **0.70 against raw shell's 0.6333** — the first round it
  is not behind — at 4.00 calls / 152.07 tokens per run against 3.47 / 155.93, so
  the D/A ratios are **1.1538 calls and 0.9752 tokens**. `ts_fix_type_error` fell
  from 5.33 steps / 292.3 tokens to **3.00 / 173.0** in D (3.33 / 284.7 to
  2.00 / 119.0 in A), because neither arm has to obtain the toolchain any more;
  failed execs moved from 5 to 7, and all seven are now real `pytest` /
  `cargo test` retries (ts and Rust compilation are at zero).
- **`python_noisy_install_summary` scored wording, not the summary.** Its
  predicate was `file_contains SUMMARY.txt "packages"` — the GOLDEN patch happens
  to say "packages: 1 installed", while every stored run wrote "1 package" and was
  scored as a failure even though it had done exactly what the prompt asked (one
  line, no install log). The predicate is now `file_matches` with
  `(?i)[^\r\n]*\bsix\b[^\r\n]*`: one line naming the installed dependency, which a
  pasted log cannot satisfy. Re-scoring the six stored runs, the old predicate
  passed 1/6 and the new one passes 6/6. A `file_matches` predicate type was added
  to both `check_success` implementations.
- **Claim C24 + `tools/task_set_audit.py`**: every task that ships a GOLDEN patch
  is now checked with the live runner's own `check_success` — the pristine fixture
  must fail the declared predicate, the GOLDEN patch must pass, and a registered
  equivalent variant must pass too. All 10 tasks pass. The new
  `tools/trajectory_replay.py` holds the shared reconstruction of what each stored
  run wrote (typed ops, inline `python -c` writes, and `echo > file`).
- **Re-measured on task set v1.3.0** (120 rows, `api_error` 0, `unverified` 0):
  D scores **0.80 against raw shell's 0.6333** and, for the first time, uses no
  more steps (4.07 vs 4.10, ratio 0.9919) while still spending fewer observation
  tokens (157.30 vs 177.63, ratio 0.8855). `python_noisy_install_summary` went
  from 0/3 to 3/3 in both arms.
- **Re-measured after the shim fix** (120 rows, `api_error` 0, seeds 42/43/44):
  condition D now uses **177.3 observation tokens per run against raw shell's
  202.4** — a D/A token ratio of **0.876**, the first reading below 1 in five
  rounds — while still issuing 1.40x the tool calls at the same 0.6333 success
  rate. `exec.run` fell from 76 calls / 5585 tokens to 50 / 2121, and failed
  execs from 45 / 4565 to 21 / 1735 with the Rust tasks at zero. The gap
  decomposition flips with it: exec goes from +70.4 to **-74.6** tokens/run,
  because raw shell has to do its reading, running and writing through one
  command while D's `exec.run` only executes. Every D-side exec number recorded
  before this date was measured under the defect and is not comparable (C13).
- **`exec.run` could not launch a name-dispatching shim.** On a rustup install
  `cargo.exe` / `rustc.exe` are *symlinks* to `rustup.exe`, and rustup picks the
  tool from the file name it was invoked as. `resolve_candidate` canonicalised the
  path, which follows the symlink, so the child ran as plain `rustup`:
  `cargo check` returned exit 100 with "0 error(s)", `cargo build` was read as the
  `+build` toolchain, and `cargo --version` printed the rustup version. The launch
  path is now kept as resolved (the shim name survives) while
  `audited_executable` stays canonical for audit identity, so the safety guard and
  target reporting still name the real binary (claim C18,
  `tools/exec_failure_breakdown.py`, plus two regression tests in
  `src/process_command.rs`).
- **This silently corrupted the benchmark.** Condition D could not run any
  cargo/rustc command on this machine while raw shell (which spawns through
  `cmd`) was unaffected, so every D-side exec number recorded before 2026-09-24
  is measured under that defect: the rust tasks' failed execs and the toolchain
  probing were the defect, not the model. C13/C15 now carry that boundary, and
  the round below re-measures with the fix in place.

### Changed
- Decomposed the remaining step gap (claim C20, `tools/step_composition.py`).
  D issues 4.53 steps/run against raw shell's 3.23 (1.40x) while using 0.877x the
  observation tokens. The gap is the surface, not waste: **35% of raw shell's
  commands do more than one job** (read+run, read+write, run+write, all three),
  which typed ops cannot. Calls a client could have merged are 8.8% of D's steps
  (13.0 tokens/run), and most are not waste either — four are legitimate re-runs
  of the same test after an edit, and the rest are `ts_fix_type_error` probing for
  a `tsc` the fixture does not ship (`node_modules` is absent while the task
  prompt promises `tsc --noEmit` succeeds). The failed-exec observation is
  dominated by `error` and `diagnostics`; the only trimmable fields total ~20%
  and each still carries signal, so they were evaluated and left alone.
- Read-usage audit (claim C17, `tools/read_usage_audit.py`): of condition D's 85
  read paths in the with arm, **33.4% of the read tokens go to `TASK.md`**, whose
  text the system prompt already carries in a strictly more detailed form
  (compared fixture by fixture). Raw shell shows the same redundancy at 17.6%, so
  it is a prompt/fixture duplication rather than an ACI defect. The
  `unreferenced` bucket (24.8%) is *not* waste: `Cargo.toml` and the failing test
  file land there and reading them is reasonable.
- The agent prompt now says `TASK.md` restates the task and should not be read
  (rule 8). A three-task smoke obeyed it (0 `TASK.md` reads, 3/3 pass), and the
  full A/B confirms it at scale: D's `TASK.md` reads fall from 27 paths / 1064.5
  tokens to **3 / 115.3**, the read bucket drops **30.8%** (3183 -> 2203 tokens),
  and the success rate does not move (A 0.60 / D 0.60).
- **D's total tokens did not fall**, though: 296.5 -> 303.5 per run. `exec.run`
  rose from 4442 to 5585 tokens in the same round — inside its own round-to-round
  range (4442-5585) and equally consistent with the freed budget being spent on
  commands, which this sample cannot separate. What did change is where the gap
  lives: read 52.6% -> 22.3%, exec 21.6% -> **49.4%**, and `read_files` now
  *reduces* D's tokens slightly (-3.5%, the first negative reading in four
  rounds). 81.7% of D's exec tokens still come from failed commands.
- Re-measured the live A/B with the compact projection (same model, endpoint,
  seeds 42/43/44, both arms, 120 rows, `api_error` 0 after one upstream 500 was
  re-run by `splice_live_cells.py`). Condition D now spends **296.5 observation
  tokens per run** (was 333.4, and 411.1 two rounds ago), and hiding `read_files`
  moves D by **-19.6% tool calls / +6.8% observation tokens** — the token penalty
  of batch reading has fallen from +36.9% to +22.7% to +6.8% across the two
  envelope rounds. The D/A ratio is *not* the headline: raw shell is untouched
  code yet its own average swung 168.6 -> 197.4 -> 170.5, so the ratio moved
  2.44 -> 1.69 -> 1.74 mostly on sampling while D's absolute cost fell
  monotonically (claim C13).
- `bench/aci/runners/splice_live_cells.py`: re-runs the (task, condition, seed)
  cells that carry `api_error` and patches them into their run file, recomputing
  the aggregate and comparison — the per-cell retry the handoff used to do by hand.
- The reference client's read projection is compact now (claim C16,
  `tools/read_path_breakdown.py`): a complete window is carried as one
  newline-joined `text` string, and the counts the caller can derive are dropped
  — `start_line` when the window starts at 1, `total_lines` when it covers the
  whole file. Measured on the frozen live trajectory, the read bucket drops
  **20.8%** of its model-visible tokens (3690 -> 2924; `file.read_many` -20.8%,
  `file.view` -20.2%). The product envelope is untouched: with
  `compact=False` the projection is byte-identical to the previous revision
  (37/37 frozen calls compared against the projector from git), so no consumer
  has to migrate. A window longer than the 10-line display gate still keeps
  `total_lines`, because for such a file that count is the only thing the model
  can see.
- Decomposed condition D's extra observation tokens with stored artifacts only
  (claim C15, `tools/exec_token_breakdown.py`). `exec.run` is D's biggest single
  line item (50.4% of D, 63.1 tokens/call) but it is **not** why D costs more
  than raw shell: of the +144.0 tokens/run gap, reading is +84.8 (58.9%), edits
  +24.8 (17.2%) and exec only +23.3 (16.2%). D pays 48.0 tokens per file
  reference against raw shell's 26.0 and reads ~1.6x as many file references.
  80.1% of D's exec tokens come from failed commands (96.2 tokens each versus
  26.4 for successes), and adding batch reads raised exec tokens only by issuing
  7 more failing commands while the per-success cost fell. The next token lever
  is the read envelope, not the exec reducer.
- Re-measured the live A/B on the new envelope (same model `sn-glm-5-3-flash`,
  same endpoint, seeds 42/43/44, 10 tasks x 2 conditions x 2 arms, 120 rows,
  `api_error` 0). Condition D/A is now **1.64x the tool calls and 1.69x the
  observation tokens** of raw shell (previously 1.75x / 2.44x). Within this
  round, hiding `read_files` moves D by **-11.8% tool calls and +22.7%
  observation tokens** (previously -8.8% / +36.9%). The clean cross-round signal
  is the per-call cost of `file.read_many`: 175.6 -> 135.6 tokens (-22.8%),
  matching the deterministic replay's -22.1% (claim C14). Raw shell is untouched
  code yet its own average moved 168.6 -> 197.4 tokens between rounds, so the
  ratio movement is not attributable to the envelope alone (claim C13).
- Measured effect of `file.read_many` (live A/B: same model `sn-glm-5-3-flash`,
  same seeds 42/43/44, 10 tasks x 2 conditions x 2 arms): condition D's tool calls
  drop from 6.03 to 5.50 (-8.8%) and the D/A tool ratio from 1.95 to 1.75, while
  observation tokens rise from 300.2 to 411.1 (+36.9%) because one call now pulls
  more file content. Fewer steps, not fewer tokens — ACI still costs ~1.75x the
  steps and ~2.4x the tokens of raw shell here (claim C13). **Superseded by the
  re-measurement above**, which was taken after the read envelope shrank; the
  numbers stay here as the record of what that round measured.
- The model-visible observation projection drops structural redundancy:
  `file.view` lines are flattened from `[{line, text}]` to plain strings with a
  single `start_line` (a 10-line window: 444 -> 250 chars, -43.7%), and a failure
  `summary` is omitted when the diagnostics already carry its message and
  `stats` carries the counts (failing pytest: 529 -> 399 chars, -24.6%). The raw
  observation envelope is unchanged, so this is a projection choice, not a
  contract change.
- Fixture workspaces no longer copy `__pycache__` / `.pytest_cache`. Stale
  bytecode made pytest report the *fixture source* path
  (`../../../../Desktop/...`) instead of the workspace-relative one, which both
  wasted tokens and misled the agent.
- Failure observations no longer carry fields that merely repeat each other: a
  stream summary byte-identical to `summary`, and an `error.hint` that
  duplicates a diagnostic message. Reproduced failing-pytest observation:
  958 -> 689 chars (-28%).
- Claim C12 (evidence freshness): the three stored measurements (ACI-Bench
  results, L3 observation report, cross-shell bench) record the sha256
  fingerprint of the surface they measured, and `claim_gate` fails when that
  fingerprint no longer matches the code — a stale artifact can no longer pass
  the gate.
- The ACI-Bench dataset and its tooling are now tracked: `.gitignore` no longer
  hides `bench/aci/**/*.py`, so a fresh clone has the fixture code, runners and
  scorers that the task descriptions and the C1/C2 reproduction command need.
- `tools/readme_claims_check.py` + claim C10: every documented README example is
  executed against the real binary and every README implementation number is
  re-derived from its source of truth. It also verifies the README cross-shell
  table row by row against `eval/cross_shell.json`.
- `tools/cross_shell_bench.py` + claim C11: reproducible wall-clock comparison
  for the five advertised operations, with raw per-iteration samples in
  `eval/cross_shell.json`.
- Process lifecycle ops (`process.start` / `process.poll` / `process.write` /
  `process.kill` / `process.list`): runtime-owned long-lived processes with a
  monotonic byte cursor, a rolling retained output window, idempotent process-tree
  kill, explicit lifecycle state (`running` / `exited` / `killed` / `lost`) and
  24-hour record retention. JSON-RPC only — not registered as MCP tools.
- Windows ConPTY backend for `process.start` with `pty: true` (single `pty`
  stream, `cols`/`rows`, Job Object still attached); other builds return
  `E_PROCESS_PTY_UNSUPPORTED`.
- `runtime.handshake` feature flags: `process_lifecycle`,
  `monotonic_process_cursor`, `windows_conpty`.
- Docs: `docs/1.0-aci.md` "Process lifecycle" section (ownership echo, cursor and
  retention semantics, approval/capability rules, error codes); README process
  contract now covers both the one-shot and long-lived paths.
- Semantic observation reducers for cargo / pytest / git / npm_install with structured diagnostics
- Optional Diagnostic fields: code, expected, found, suggested_fix
- Session observation ledger + ops.observation_recent / ops.observation_open_errors
- ACI-Bench framework under bench/aci (10 tasks, GOLDEN fixtures, A/D comparison, leaderboard, REPORT)
- Multi-model live runner stub with trajectory cache (`baselines/`) and models.json dual slots
- docs/quickstart/aci-mcp.md and docs/v1.1-freeze.md

### Changed
- Evaluation artifacts (`bench/aci/results/*`, `eval/*.json`) are written with
  LF newlines, so re-running a dataset produces a minimal, reviewable diff
  instead of a whole-file rewrite on Windows.
- README compact-protocol claim corrected: the unverified "50-70% token savings
  vs JSON" is replaced by the measured scope of claim C9 (`>=40%` on a small
  response envelope; no saving on observation or large nested payloads).
- `src/compact.rs` module docs now point at the measurement instead of repeating
  the old number.

### Fixed
- `reduce` pipeline stage: the IR lowering returned a bare `Reduce` node and
  dropped the pipeline source, so every `... | reduce fn(..) 0` (the form README
  documents) failed with `expected array`. The `let`-bound form hid the bug
  because it never took the lowering path.
- `reverse` pipeline stage: it was lowered to the unregistered builtin name
  `arr.reverse` and to a `Call` instead of a pipeline stage, so standalone,
  direct and chained forms all failed. It is now a real `IRNode::Reverse` stage
  that reads the upstream value like `Take`.
- README numbers corrected against their sources: 5 Criterion benchmark suites
  (was 4) and 52 integration tests (was 50).
- Match-arm guards no longer clone the entire Env (scoped with_frame)

## 1.0.0 — Agent-Computer Interface surface

Operation-first ACI runtime (single-track delivery):

- Unified OperationRegistry for all agent ops (JSON-RPC + MCP auto tools)
- File ACI: file.view, file.read_range, file.hash, file.replace_exact, file.apply_patch, file.edit_range, file.diff, file.remove (agent trash)
- Safety: tx.begin/commit/rollback/status/restore, trash restore tokens
- Repo: repo.search, repo.changed_files, repo.summary
- Test: test.discover, test.run_target, test.summarize_last
- Meta: ops.list
- Retains 0.6 observation quality for exec.run / result.query
- `E_NEEDS_APPROVAL` observations now preserve `error.hint` (+ optional `data.approval_token`)
- Closed-loop acceptance tests: `tests/aci_1_0_closed_loop_acceptance.rs`

## 0.6.1 — Observation quality

Non-breaking polish of the 0.6 Observation Budget contract:

- Success silence for npm/cargo/python/pytest/msbuild
- Failure focus: error-window extraction
- ANSI strip on the observation path
- git auto-profile
- Expanded unit + integration protocol tests

## 0.6.0 — Agent Action / Observation Runtime

- Typed exec.run / result.query operations
- Observation envelope, artifact store, process runner with Windows Job Objects
- Compiled IR + plan cache, HashMap LRU
