# C14 / C16 headroom analysis: is the gap closable, and at what cost

- **Task:** `task-9` (owner `headroom-analyst`), read-only analysis plus this file and
  scripts under `audit-r12-scratch/repair-c14-c16-2026-09-29/`.
- **Claims under analysis:** C14 `>= 0.15` currently **0.0422 (FAIL)**; C16 `>= 0.10`
  currently **0.0768 (FAIL)**. Thresholds are **not moved** (TF-0116 / P2-1 acceptance
  criteria: "C14/C16 thresholds MUST NOT be lowered").
- **Method:** the frozen call set was replayed **offline against the local
  `target/debug/ae.exe`** (the same thing `tools/tf45_envelope_replay.py` and
  `tools/read_path_breakdown.py` do). No endpoint was called, nothing was live, no
  product code, fixture, task, tool or eval artifact was modified. Candidate
  projections were measured with a **scratch copy** of the reference projector
  (`variant_projector.py`) that is asserted byte-identical to
  `bench/aci/runners/live_agent_loop.format_aci_result` on all 129 envelopes × both
  renderings (516 assertions) before any counterfactual number is trusted.
- **Bottom line:** **C14 is not closable at any acceptable cost** — its numerator is
  only the digest-length difference, capped at **6.63%** of the most favourable
  denominator the verbatim-content constraint allows; reaching 0.15 would require
  showing the model **16–24% of today's rendered lines**. **C16 is closable, but only
  by giving the model *less* information (dropping or weakening the change-detection
  digest, 10.35%–10.75%) or *different* information (a positional/text rendering
  schema, 10.94% / 15.00%)**; every option that keeps the current keyed-JSON grammar,
  the 16-hex digest and all values tops out at **9.68%**. Since **C34 (0.5654,
  PASS)** is the already-claimable substitute, the recommendation is **no-go: leave
  both red, keep C34**.

---

## 1. The frozen call set and the exact arithmetic of each claim

Source of the call set: `bench/aci/results/latest_live.json`, condition
`verseshell_aci` read ops (`file.view`, `file.read_many`, `file.read_range`).

| | value |
|---|---|
| frozen read calls | **133** (54 `file.view` + 79 `file.read_many`) |
| matched / reproducible | **129** (C14 and C16 use the *same* 129 — verified by identity list) |
| excluded | **4** — run-produced state: `.ae/audit.log` (1), `out/result.txt` (2), `csvlite.py` (1) |
| coverage | 0.9699 |
| C14 measure | `tools/tf45_envelope_replay.py` — `max(1, len(text)//4)` |
| C16 measure | `tools/read_path_breakdown.py` — `len(text)//4` |

**C14** (`eval/tf45_envelope_replay.json`): legacy = the *same envelope with the
compact `hash` removed*, so `digest_of()` falls back to the 71-char
`sha256:<64 hex>` `content_hash`; current = the envelope as returned.

```
numerator   = 72792 - 69718 =  3074 proxy tokens  (291373 - 279053 = 12320 chars)
denominator = 72792 proxy tokens (291373 chars)
saving      = 3074 / 72792 = 0.04223
by op: file.view 50 calls 21476 -> 20792 (0.0318)
       file.read_many 79 calls 51316 -> 48926 (0.0466)
untruncated subset (111 calls): 52120 -> 49525 = 0.0498  (still far below 0.15)
truncated usable calls: 18
```

**C16** (`eval/read_path_breakdown.json`): legacy = `format_aci_result(env,
compact=False)` (JSON `lines` array, keeps the derivable counts), current =
`compact=True` (one joined `text`, drops counts the text makes derivable).

```
numerator   = 75517 - 69718 =  5799 proxy tokens  (302291 - 279053 = 23238 chars)
denominator = 75517 proxy tokens (302291 chars)
saving      = 5799 / 75517 = 0.076791
by op: file.view      88841 -> 83233 chars, 22190 -> 20792 tok (0.0630)
       file.read_many 213450 -> 195820 chars, 53327 -> 48926 tok (0.0825)
```

Both claims share the same `current_tokens = 69718` (the current projection; the
`max(1, .)` floor in C14 never binds on this set). The two claims are **different
counterfactuals and must not be added or substituted** for each other.

Recorded pre-change attribution (share of the 302291 legacy chars), reproduced
exactly in this analysis:

| component | legacy chars | share | current chars |
|---|---:|---:|---:|
| `content` | 236316 | 78.18% | 236316 |
| `line_wrapper` | 32620 | 10.79% | 16310 |
| `residual` | 12956 | 4.29% | 12732 |
| `counts` | 8082 | 2.67% | 1378 |
| `digest` | 8064 | 2.67% | 8064 |
| `path` | 4253 | 1.41% | 4253 |
| **total** | **302291** | 100% | **279053** |

## 2. Component-level headroom (proxy tokens = chars // 4)

"Already removed" is what the shipped compact projection already takes out;
"remaining" is the maximum additional amount if that component were driven to zero.

| component | legacy proxy tok | already removed by compact | remaining = max if zeroed | note |
|---|---:|---:|---:|---|
| `content` | 59079 | 0 | 59079 | the only big lever; removing it *is* "showing the model less" |
| `line_wrapper` | 8155 | 4077 | 4077 | JSON `\n` escaping floor: 2 chars per line (8155 lines), so most of the rest cannot go |
| `residual` | 3239 | 56 | 3183 | key names, braces, commas, array containers; only a schema/format change touches it |
| `counts` | 2020 | 1676 | 344 | remaining 1378 chars are partial-window `total_lines` / `start_line > 1` |
| `digest` | 2016 | 0 | 2016 | delta is **0 in C16** (both legs render it) and is **C14's entire numerator** |
| `path` | 1063 | 0 | 1063 | read_many entry identity; cancels inside C16 today |
| **sum** | **75572** | **5809** | | measured C16 numerator is 5799 tok (per-call floor effects) |

### Reconciliation with the recorded 5.31% C14 ceiling

`audit-r12-scratch/repair-p2-1-2026-09-29/scope_analysis.py` computed a conditional
upper bound; this analysis reproduces it exactly:

```
lower denominator = Σ per-call floor(content_chars / 4)        = 59030
upper numerator   = Σ per-call ceil(digest_chars_delta / 4)    =  3136
bound             = 3136 / 59030 = 0.0531255…   (reproduced: True)
baseline observed = 3074 / 72792 = 0.04223
```

Meaning: **even if every non-content component vanished, and even rounding the
digest delta up, a digest-only change cannot exceed 5.31% of the content-only
denominator.** The bound is conditional on this frozen call set, `content` kept
verbatim, and the 71-char → 16-char digest difference — exactly as its scope line
says. Section 4 extends it to the strongest digest surgery possible.

## 3. Candidate table (all values measured on the frozen 129-call set)

`lossless` = the agent can still recover everything it can read today.
`model-visible` = the model's observation surface changes.
`offline` = measurable with this offline replay (no endpoint).

| # | candidate | C14 | C16 | lossless | model-visible | offline | verdict |
|---|---|---:|---:|---|---|---|---|
| 0 | baseline (shipped) | 4.22% | 7.68% | yes | — | yes | both FAIL |
| 1 | 16-hex digest → **1-char** digest | **5.38%** | 7.77% | weaker stale-write token | yes | yes | best possible digest surgery; still FAIL |
| 2 | compact drops **remaining counts** | 4.24% | 7.99% | counts derivable from text | yes | yes | harmless, but only +0.31pp |
| 3 | compact drops **path** in batches | 4.27% | 9.09% | **no** (entries unlabeled) | yes | yes | FAIL; lossy |
| 4 | 2+3 (counts + path) | 4.29% | 9.40% | no | yes | yes | FAIL |
| 5 | document **abbreviated keys** (all values kept) | 4.31% | 9.48% | yes (info-lossless) | yes | yes | FAIL |
| 6 | 5+2 (abbrev + counts) | 4.32% | **9.63%** | yes | yes | yes | FAIL — best lossless keyed-JSON option |
| 7 | **upper bound**: every key → 1 char + counts | 4.32% | **9.68%** | yes | yes | yes | FAIL — ceiling of the key-renaming family |
| 8 | compact drops **digest** | **0.00%** | **10.35%** | **no** (no stale-write check) | yes | yes | C16 PASS by +0.35pp; **collapses C14 to 0** |
| 9 | **positional-array schema** (tight separators, all values kept) | 4.38% | **10.94%** | yes | yes (new schema) | yes | C16 PASS by +0.94pp |
| 10 | **text framing** (header + verbatim lines, no JSON) | 4.58% | **15.00%** | yes | yes (new format) | yes (one concrete design) | C16 PASS by +5.0pp |
| 11 | 5+2+3 (abbrev + counts + path) | 4.37% | 10.87% | no (path) | yes | yes | PASS but lossy |
| 12 | 5+8 (abbrev + digest) | 0.00% | 11.34% | no (digest) | yes | yes | PASS but lossy + C14 = 0 |
| 13 | 4+8 (counts + path + digest) | 0.00% | 12.07% | no | yes | yes | PASS but lossy + C14 = 0 |
| 14 | **state-tracking dedup** of unchanged repeat reads | 6.38% | 6.73% | yes | yes | yes | **best total-volume change, does NOT clear either** |
| 15 | compact rendering truncates digest to **1 hex char** | **0.00%** | 8.79% | no (stale-write token weakened) | yes | yes | FAIL alone; **collapses C14** |
| 16 | 15 + abbrev keys + counts | **0.00%** | **10.75%** | no | yes | yes | C16 PASS by +0.75pp; C14 = 0 |
| 17 | abbrev keys + counts + **4-hex** digest | **0.00%** | **10.52%** | no (much weaker token) | yes | yes | C16 PASS by +0.52pp; C14 = 0 |

Exact numerators/denominators are in `out/headroom_model.json`.

**Dedup detail (candidate 14).** Keyed on `(path, digest, start_line, end_line)`, so
newly written content is always shown. It removes **91814 of 236316 rendered content
chars (38.9%)**, and delivered projected tokens fall **69718 → 45153 (−35.2%)** on
the frozen set. But it removes the same content from *both* C16 legs, so the ratio
**falls** to 6.73%; C14 rises only to 6.38%. Dedup is a real product win that needs a
**total-observation-volume claim**, not C16.

**Other levers checked:**

- *Smaller default `file.view` window / smaller `read_many` budget* — the shipped
  batch budget is `max_total_lines = 240` (worst-case probe: 8×300-line files return
  240 lines within the cap; 18 of the 129 usable frozen calls are already truncated).
  Lowering it truncates the same windows the scaling curve truncates: C16 **falls**
  (both legs lose content and its wrapper; e.g. k≈0.5 → 7.03%), C14 rises only under
  extreme cuts, total volume falls. Not a threshold route.
- *Larger window / budget* — extra lines grow the numerator (`line_wrapper` delta) and
  the denominator together, so C16 stays in the same 7–9% band and does not reach 10%;
  C14 falls (bigger denominator). Not a route either.
- *Removing content entirely for repeated reads* — same as dedup.

## 4. Reachability arithmetic

### 4.1 C14 cannot be closed without starving the model

C14's counterfactual is **digest-only by construction**: the legacy leg is the same
envelope with `hash` removed, so every non-digest rendering choice lands on *both*
legs and cancels. Confirmations from the measurements:

- 224 digest field occurrences; baseline delta = 224 × 55 chars = 12320 ✓.
- Shortening the **envelope's** `hash` to 1 char (the projection unchanged) is the
  maximum surgery that still yields a usable token: delta 224 × 70 = **15680 chars
  (3916 proxy tokens after the per-call floors)** → C14 5.38%.
- Setting `hash` to the empty string does **not** help: `digest_of()` falls back to
  the 71-char `content_hash`, so both legs render it and the delta is **0**.
- Reformatting the digest **inside the compact branch** (drop it, or truncate it)
  makes both C14 legs identical → **C14 = 0.0000** (candidates 8, 15–17, see §4.2).
  So digest surgery has a hard ceiling in either location.

```
C14 numerator ceiling (1-char digest) = 3916 tokens
most favourable denominator possible  = 59030 tokens (content-only floor)
C14 ceiling under verbatim content    = 3916 / 59030 = 6.63%   <   15%
```

To reach 15% the *denominator* must shrink instead, i.e. the model must be shown
less content. Measured by content scaling (§5):

```
C14 >= 0.15  requires keeping only  k <= 0.156  of today's rendered lines
             (current 16-hex digest), or  k <= 0.239  with a 1-char digest.
             i.e. 15.6% - 23.9% of today's model-visible read content.
```

And that route is self-defeating for the claim: the frozen-call-set counterfactual
assumes the model issues the *same* calls, but an agent shown 16–24% of each window
will paginate and re-read, so the realised denominator would grow back. The offline
replay therefore **cannot validate** a content-starvation change — it needs a live
re-run, and it changes what the model sees (and therefore the claim's meaning).

### 4.2 C16 is closable, but only at an information cost

C16's numerator is produced by `line_wrapper` + `counts` + `residual` only; content,
path and digest cancel between the two legs. Hence:

- **Reducing content cannot close C16.** Measured: dedup 6.73%; window scaling peaks
  at 10.08% only at `k = 0.01` (≈1 line per window) and stays ≤9.97% for `k >= 0.02`.
- **Keeping the current keyed-JSON grammar, the 16-hex digest and every value does
  not reach 0.10.** Best measured: `abbrev_keys + counts` 9.63%; the upper bound
  (`every key → 1 char` + drop remaining counts) is **9.68%**.
- **Measured routes that do clear 0.10:**

| route | C16 | margin | what it costs |
|---|---:|---:|---|
| abbrev keys + counts + **4-hex** digest (keyed JSON) | 10.52% | +0.52pp | stale-write token weakened to 65 536 values; **C14 → 0** |
| drop the compact digest (candidate 8) | 10.35% | +0.35pp | no `expected_hash` ⇒ no stale-write check; **C14 → 0** |
| abbrev keys + counts + **1-hex** digest (keyed JSON) | 10.75% | +0.75pp | token weakened to 16 values; **C14 → 0** |
| tight positional-array schema (candidate 9) | 10.94% | +0.94pp | all values kept, but a new schema the model must parse |
| text framing (candidate 10) | 15.00% | +5.00pp | all values kept, but the observation stops being JSON |

**Where the digest change is made decides which claim it helps.** The C14 legacy leg
is produced by the *same* compact renderer with `hash` stripped, so shortening the
digest *inside the compact branch* is applied to both C14 legs and the C14 numerator
becomes **0** (candidates 8, 15–17). Shortening the digest at the *envelope* level
(the product emits a shorter `hash`, projection unchanged) instead lifts C14 to
5.38% while leaving C16 at 7.77%. Neither location closes C14, and only the
projection-level change helps C16 — at the price of zeroing C14.

All C16-passing options are model-visible changes: they must be pre-registered,
implemented, offline-replayed **and live-verified**. The digest routes additionally
remove or weaken a functional capability (stale-write detection) and regress C14, and
their C16 margins (+0.35pp to +0.75pp) are thin enough that a call-mix change can
flip them.

## 5. Content-scaling curve (validated emulation)

`k` = fraction of each rendered window kept. The emulation was validated against the
real binary (`window_probe.py`): re-running 3 `file.view` and 2 `file.read_many`
frozen calls with `window: 20` reproduces the emulated projection token count
**exactly in all 5 probes** (including the op-dependent `truncated` /
`next_start_line` shape, which `file.view` does not set and `file.read_many` does).

| k | C14 | C16 | C14 with 1-char digest | C16 current tokens |
|---:|---:|---:|---:|---:|
| 1.0 | 4.22% | 7.68% | 5.38% | 69718 |
| 0.8 | 4.96% | 6.68% | 6.31% | 59040 |
| 0.6 | 6.29% | 6.85% | 8.01% | 45983 |
| 0.5 | 7.24% | 7.03% | 9.19% | 39571 |
| 0.4 | 8.48% | 7.17% | 10.80% | 33262 |
| 0.3 | 10.36% | 7.48% | 13.17% | 26657 |
| 0.25 | 11.53% | 7.64% | 14.69% | 23622 |
| 0.2 | 13.06% | 7.90% | 16.59% | 20511 |
| 0.15 | **15.24%** | 8.34% | 19.33% | 17153 |
| 0.1 | 18.21% | 8.93% | 23.11% | 13830 |
| 0.02 | 24.25% | 9.97% | 30.93% | 9572 |
| 0.01 | 24.77% | 10.08% | 31.53% | 9326 |

C14 rises purely as the denominator shrinks. C16 is non-monotone: it dips to 6.68%
at k = 0.8 and then climbs, but it stays **≤9.97% for every k >= 0.02** and only
inches to 10.08% at k = 0.01, where each window is one line and the agent is
effectively blind. So content policy alone does not clear 0.10 either. The whole
family is "give the model less", and at k = 0.15 the agent would see about one
seventh of today's content.

## 6. Verdict and recommendation

**(a) Can C14 `>= 0.15` be reached at all?** Not as a read-projection improvement.
No envelope change that keeps content verbatim exceeds **6.63%** (measured ceiling
with a 1-char digest against the content-only denominator). The only arithmetic route
is to show the model **15.6%–23.9% of today's rendered lines**, which is not an
efficiency change, invalidates the frozen trajectory (the model would issue different
calls), and needs a live re-run.

**(b) Can C16 `>= 0.10` be reached?** Yes, but only by degrading or changing the
observation surface. Lossless-information routes change the rendering schema/format:
positional arrays **10.94%**, text framing **15.00%**. Digest routes keep the keyed
JSON grammar but weaken or remove the stale-write token (4-hex digest + abbrev keys +
counts **10.52%**, drop the digest **10.35%**, 1-hex digest + abbrev keys + counts
**10.75%**), and every one of them collapses C14 to **0.0000**. Keeping the current
grammar, the 16-hex digest and every value, the measured ceiling is **9.68%**.

**(c) Which single change/combination does it?** `text_render` framing is the only
option with a comfortable margin (+5.0pp) that keeps all information; the tight
positional schema is the smallest-margin-but-safe option (+0.94pp); the digest routes
are the smallest diffs that pass but are the worst trade (lossy + C14 → 0).

**(d) What breaks?** Every C16-passing option changes what the model sees → all
existing model-behaviour numbers (C13/C25 and the live A/B) are invalidated until a
live re-run; the digest route additionally removes the stale-write token and zeroes
C14's numerator components. Both claims' artifacts (`eval/tf45_envelope_replay.json`,
`eval/read_path_breakdown.json`) would need to be regenerated and re-verified, and
C14 would still be red afterwards.

### Go / no-go

> **No-go on chasing C14.** **No-go (optional) on chasing C16.** Leave the thresholds
> and the claim definitions exactly as they are, keep C14/C16 red, and keep **C34**
> as the claimable projection result: named overhead **40702 → 17688 chars =
> 0.5654**, threshold `>= 0.40` on a fresh artifact from a task set newer than the
> one it was discovered on — **PASS** (`eval/evidence.json`, `eval/read_path_breakdown.json`).
> A product change to chase C14/C16 is **optional, not required**, and is **not
> recommended**: C14 cannot be reached at all without starving the model, and C16 can
> only be reached by changing the model-visible surface for a ≤1pp-margin gain on one
> claim while regressing another.

If the Lead nevertheless chooses to pre-register one option, the least risky is the
**tight positional schema** (10.94%, all values preserved, offline-verifiable,
+0.94pp). Its risks: a model-visible format change invalidating current behaviour
measurements; a required live re-run; unknown parse-performance effects; and C14
remaining red at 4.38% (needing its own disposition).

**Do not pre-register the digest drop:** it is lossy (no stale-write token), it
**collapses C14 from 0.0422 to 0.0000**, and its C16 margin is only +0.35pp.

### Pre-registration requirement (house rule)

Any product change intended to move C14/C16 must be **pre-registered, implemented,
offline-replayed and live-verified**, because it changes what the model sees. The
thresholds must **never** be lowered. The frozen-call-set replay can quantify such a
change but cannot validate it: it holds the model's calls fixed, and the very
purpose of these changes is to alter what the model receives. Nothing in this
analysis is a proposal to ship — every alternative projection exists only as a
temporary copy under the scratch directory.

## 7. Explicitly not done

- **No endpoint calls, no live run.** Everything is offline local replay of the
  frozen call set against `target/debug/ae.exe`.
- **No candidate promotion:** no product source, runner, tool, fixture, task or eval
  artifact was modified. The alternative projector lives only in
  `audit-r12-scratch/repair-c14-c16-2026-09-29/variant_projector.py` and is never
  imported by shipped code.
- **No threshold change and no claim redefinition.**
- **No edits** to `eval/tf45_envelope_replay.json`, `eval/read_path_breakdown.json`,
  `eval/evidence.json`, `tools/task_admissibility.py`, or any file outside this
  task's two write scopes. Pre-existing `fix_c12_*` files in the scratch directory
  were left untouched.

## 8. Artifacts and reproduction

| artifact | what it is |
|---|---|
| `docs/c14-c16-headroom-analysis.md` | this analysis |
| `audit-r12-scratch/repair-c14-c16-2026-09-29/headroom_cache.py` | offline replay of the 133 frozen calls; cross-checks both recorded evals |
| `.../cache/envelopes.json` | raw envelopes for the 133 frozen calls |
| `.../cache/verify.json` | per-call match against both recorded evals |
| `.../variant_projector.py` | scratch, analysis-only variant of `format_aci_result` (byte-identical at default options) |
| `.../headroom_model.py` | component table, candidate counterfactuals, scaling curve, verdicts |
| `.../out/headroom_model.json` | every number quoted above |
| `.../window_probe.py`, `.../out/window_probe.json` | validation of the content-scaling emulation against the real binary |
| `.../dump_numbers.py` | prints the numbers used in this document |

```powershell
python -B audit-r12-scratch/repair-c14-c16-2026-09-29/headroom_cache.py
python -B audit-r12-scratch/repair-c14-c16-2026-09-29/headroom_model.py
python -B audit-r12-scratch/repair-c14-c16-2026-09-29/window_probe.py
```

`headroom_cache.py` must print `reproduces_eval=True` for both claims
(C14 `72792 -> 69718`, C16 `75517 -> 69718`) before the later scripts mean anything;
`headroom_model.py` asserts byte-identity of the scratch projector (516 assertions)
and that C14/C16 use the same 129-call set.
