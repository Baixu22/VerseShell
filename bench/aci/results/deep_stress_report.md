# VerseShell ACI Deep-Stress Report

**Verdict: GOOD** — all six phases pass. Zero regressions. Two P1 defects fixed.

Generated: 2026-07-19T13:30:00Z

---

## Scores

| Dimension | Score | Threshold | Pass |
|---|---|---|---|
| S1 — Reducer Quality | **1.00** | 0.95 | Y |
| S2 — Compression Ratio | **1.00** | 0.70 | Y |
| S3 — Agent-Loop Utility | **1.00** | 0.90 | Y |
| S4 — ACI-Bench Gate | **1.00** | 0.95 | Y (mock; live skipped) |
| S5 — Robustness | **1.00** | 0.90 | Y |
| S6 — Regressions | **1.00** | 0.95 | Y |

---

## Phase 0 — Baseline Lock

| Metric | Count |
|---|---|
| Library tests | 144 passed, 0 failed |
| Gate tests (semantic + compression + bench) | 27 passed, 0 failed |
| **Total** | **171/171 green** |

---

## Phase 1 — Semantic Reducer Adversarial (22 tests)

Every profile tested: cargo, pytest, git, npm_install. Each gets success, 2+ failures, noisy, and malformed variants.

| Profile | Tests | Key verifications |
|---|---|---|
| cargo | 6 | E0308 path:line, E0308+E0277 multi, E0599 in 200-warning noise, panic fallback, malformed no-crash |
| pytest | 5 | path:line extraction, headerless fallback, ANSI resilience, multi-failure, suggested test.run_target |
| git | 5 | status stats, mixed staging, fatal: not a repo, CONFLICT detection, no false file.view on git errors |
| npm_install | 4 | package count, vulnerability stats, ENOENT capture, network error (ETIMEDOUT/503) |
| invariants | 2 | all failure summaries ≤500 chars; success produces zero error diagnostics |

---

## Phase 2 — Token Compression (4 tests)

| Test | Raw tokens | Agent tokens | Ratio | Critical info preserved |
|---|---|---|---|---|
| cargo_large_noise (55.9KB) | 14,665 | 212 | **0.985** | E0502 at src/engine.rs:142 |
| npm_large_noise (78.7KB) | 20,678 | 185 | **0.991** | added=1024, vulnerabilities=0 |
| git_diff_large (56.3KB) | 14,830 | 330 | **0.978** | files_changed=51, insertions=750, deletions=125 |
| cargo_fail_noisy | — | — | verified | E0599 with path:line preserved |

---

## Phase 3 — Op Protocol Closed-Loop (9 tests, 9/9)

All tests run against real `ae --serve`. Key results:

- **Hash consistency**: exec.run → file.replace_exact(hash) → re-read → bytes match
- **Stale hash**: `sha256:deadbeef` → `E_STALE_HASH` with actual hash in message
- **Ambiguous match**: text matching 2× → `E_AMBIGUOUS`
- **Outside workspace**: path traversal → `E_OUTSIDE_WORKSPACE`
- **Suggested next**: cargo fail → file.view + result.query in suggested_next
- **Result query**: `result://sha256/...` → artifact recovery confirmed
- **Ledger**: ops.list shows observation ledger populated
- **20 sequential ops**: all succeed, no state corruption
- **Multi-agent**: 2 concurrent agents isolated

---

## Phase 4 — ACI-Bench

| Check | Result |
|---|---|
| Mock 10 tasks A vs D | PASS: D=1.0 vs A=0.0 success, tools 0.55×, tokens 0.106× |
| Destructive (false-green) | PASS: corrupted comparison correctly FAILS scorer |
| Live model | SKIPPED (no ACI_BENCH_API_KEY or OPENAI_API_KEY) |

---

## Phase 5 — Stability / Security / Resource (8 tests, 8/8)

- **Timeout**: `ping -n 60` with timeout 1s → `E_TIMEOUT`
- **Nonzero exit**: `exit /b 1` → `E_PROCESS_EXIT` with diagnostics
- **Budget truncation**: oversized output truncated, artifact omitted flag set
- **ANSI stripping**: escape sequences removed from observation text
- **100 serial ops**: all 100 succeed, no state leak
- **Large artifact**: 2100-byte file → handle created, content recovered
- **Permission denial**: path outside workspace → `E_NEEDS_APPROVAL`
- **Windows paths**: forward and backslash paths normalized

---

## Phase 6 — Anti-Regression (3 tests, 3/3)

- cargo semantic collapse (body collapsed for success)
- npm install collapse (body collapsed, stats preserved)
- match_guard verification

---

## Defects Fixed

| Severity | File | Issue | Regression test |
|---|---|---|---|
| P1 | `src/reducers/cargo.rs` | 30-diagnostics cap lost real errors buried after 200+ warnings | `cargo_large_noise_high_compression` |
| P1 | `src/reducers/cargo.rs` | Spurious diagnostics from "aborting due to" / "could not compile" meta-messages | `cargo_large_noise_high_compression` |

## Known Defects (Not Fixed — P2)

- Windows artifact storage may produce encoding artifacts with non-ASCII output. Clean ASCII recovers correctly. Recommend normalizing to UTF-8 in the artifact write path.

---

## Evidence Files

| Artifact | Path |
|---|---|
| Phase 0 build + gate | `cargo test --lib` (144 tests) + `cargo test` (27 additional) |
| Phase 1 tests | `tests/semantic_reducer_adversarial_tests.rs` |
| Phase 2 tests | `tests/token_compression_tests.rs` |
| Phases 3,5,6 e2e results | `bench/aci/results/deep_stress_phases_356.json` |
| Phase 4 bench results | `bench/aci/results/latest.json` |
| Phase 4 gate test | `tests/aci_bench_mock_acceptance.rs` |
| Final report JSON | `bench/aci/results/deep_stress_report.json` |
| Fixture data | `tests/fixtures/reducers/adversarial/` (17 files) |
| E2E runner | `tools/deep_stress_eval.py` |
