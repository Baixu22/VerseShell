#!/usr/bin/env python3
"""token_proxy_calibration: measure `estimate_tokens` against real tokenizers.

Every published observation-token number in this repo (the D/A ratio 0.8855 and
claims C14/C15/C16/C17/C19/C20) is computed with the crude proxy

    estimate_tokens(text) = max(1, len(text) // 4)      # bench/aci/runners/live_agent_loop.py

which was never validated against a real tokenizer. This tool measures that proxy
against (a) a real BPE tokenizer available offline, and (b) the tokenizer behind
the OpenAI-compatible endpoint in `.env.local`, and reports the two side by side.

What it does
------------
1. Resolves a *real* tokenizer, in tiers, and records which tier was used:

   tier 1  `tiktoken.get_encoding("cl100k_base")` succeeds (BPE file already in
           the tiktoken cache).
   tier 2  the BPE file is in a local tiktoken cache directory
           (`TIKTOKEN_CACHE_DIR`, `DATA_GYM_CACHE_DIR`, `%TEMP%/data-gym-cache`);
           it is parsed locally and an `Encoding` is constructed from the
           documented cl100k_base spec (pattern + special tokens), with the file
           verified against its published sha256.
   tier 3  the BPE file is not cached and is fetched once from
           `openaipublic.blob.core.windows.net` with **proxies disabled**, hash
           verified, and written into the tiktoken cache so later runs are fully
           offline. (On this machine the ambient Windows proxy config makes
           `requests`/`urllib` fail with `ProxyError: Unable to connect to
           proxy`; bypassing the proxy works. `--no-download` disables tier 3.)
   tier 4  no real tokenizer is reachable: a **documented byte-class
           approximation** is used and the whole artifact is labelled
           `is_approximation: true`. It is never silently substituted.

   `cl100k_base` is a real, published BPE vocabulary; it is the tokenizer of the
   GPT-4/3.5 family and a widely used stand-in for "a modern BPE tokenizer". It
   is *not* claimed to be the tokenizer of every model the repo's claims cover.

2. Replays stored live trajectories from `bench/aci/results/latest_live.json`
   through the *real* harness functions imported from `live_agent_loop.py`
   (`prepare_workspace`, `execute_shell_cmd`, `execute_aci_op`,
   `format_aci_result`, `ACI_OP_MAP`, `estimate_tokens`, `chat_completion`), so
   the calibrated texts are the texts the model actually saw, not a paraphrase.
   Raw-shell cells run `args["command"]`; ACI cells map the LLM tool name through
   `ACI_OP_MAP` and render with `format_aci_result(..., compact=True)`.

3. Measures each sampled text with the real tokenizer (primary), and measures a
   stratified subset *again* through the endpoint (secondary, cross-checked).

4. Adds a fixed **shape panel** (English prose, Python source, pytest output,
   cargo diagnostic, JSON envelope, hex digest, base64, CJK, log line), a
   **length ladder**, and a ~400-char **calibration anchor** so the artifact
   states the error direction and magnitude per text shape rather than only for
   whatever the live corpus happened to contain.

5. Recomputes the headline D/A observation-token ratio with real tokens on the
   paired replayed sample and compares it with the proxy ratio on the same cells.

What is an invariant, and what is not
-------------------------------------
* `real_tokens <= utf8_bytes` IS a tokenizer invariant, and it is checked over both
  the samples and the shape panel. `cl100k_base` is a byte-level BPE, so every
  token covers at least one UTF-8 byte; a violation would mean the tokenizer or the
  text plumbing is broken.
* `real_tokens <= chars` is NOT an invariant, even though an earlier version of
  this artifact published it as one. One Unicode character can encode to several
  UTF-8 bytes and therefore to several tokens: the `cjk_paragraph` panel entry is
  a named counterexample (278 chars, 284 real tokens). The comparison is kept as
  the explicitly labelled observation
  `tokenizer_invariants.chars_bound_observed`, with
  `chars_bound_is_not_an_invariant: true`, and the old key
  `real_tokens_never_exceed_chars` is retained and marked as retracted rather than
  silently dropped.
* The proxy `len(text)//4` is NOT a bound in either direction. In the same sample
  it under-counts some shapes (CJK, ASCII JSON/code observations) and over-counts
  others (plain English prose), so no single correction factor converts it into a
  real-token count.
* Every metric is a function of the FULL observation text. The `text` field in the
  artifact is a truncated display copy (`--max-stored-text`) and is never the
  measurement input; `measurement_integrity` proves the two were not confused.

Every published number carries its caliber
------------------------------------------
The top-level `caliber_labels` block labels each metric so no reader can take one
for another:

  `proxy_tokens`      OBSERVATION PROXY (`max(1, len(text)//4)`) — not a real count
  `real_tokens`       REAL BPE REPLAY (`cl100k_base`) on the FULL text
  `endpoint_tokens`   ENDPOINT USAGE (content-cached, intermittently inflated)
  `chars`/`utf8_bytes`  text-length metrics, not token counts

The endpoint hazard, and how it is neutralised
----------------------------------------------
The configured endpoint is an OpenAI-compatible *proxy* in front of a remote
service. Its `usage.prompt_tokens` is **not a pure function of the text**:

  * the proxy **caches/replays `usage` per input content** — sending the same
    message twice returns the *same* `prompt_tokens`, even when that value is
    nonsense (e.g. `""` -> 219, `"a"` -> 183, `'{"ok": true}'` -> 187, while
    `"ab"` -> 13 and `"hello world"` -> 14 are sane). See
    `tools/_dbg_endpoint_cache.py`, `tools/_dbg_endpoint_tokens*.py`;
  * even for content it has never seen, roughly 10-60% of requests report a
    value inflated by a **constant ~+170 tokens** (measured: baseline draws
    191/194 vs 22/23; sample draws 212/213 vs 41/45). The offset is additive and
    one-sided, and it is *not* a property of the text.

Neutralisation, in this order:

  a. **Unique content per request.** Every probe carries a fresh 12-hex-character
     nonce (`"[<nonce>] " + text`), so no probe can ever hit the content-keyed
     cache. The same nonce shape prefixes the placeholder baseline, so the nonce's
     own cost cancels in the subtraction.
  b. **Minimum over draws, not median.** The contamination is one-sided (+~170),
     so the minimum over K independent unique-nonce draws is a consistent
     estimator of the uncontaminated value; a median is not, because the
     contamination can exceed 50% of draws (observed 5/8 in one session). The
     median is still reported, and the gap between them is the evidence.
  c. **K independent draws + agreement test.** Each text is drawn K times with K
     different nonces. Draws are clustered against the minimum; a text whose
     draws do not produce at least two mutually agreeing uncontaminated draws is
     recorded `unstable` and **excluded from the endpoint aggregates** rather
     than trusted.
  d. **An interval, not a point.** The estimator's own noise (the observed spread
     of the uncontaminated cluster, typically 2-4 tokens) is reported as
     `endpoint_interval` on every sample and as the interval width in the
     cross-check aggregate.
  e. **A real-tokenizer cross-check.** Because the primary tokenizer is
     independent of the endpoint, an endpoint estimate that is off by ~+170 is
     visible immediately. Disagreements beyond `max(3 tokens, 10%)` are reported
     prominently instead of being averaged away.

Honesty rules baked in
----------------------
* Deterministic sampling: units and cells are sorted, selection is a pure
  function of the replayed cells, and the selection is hashed into
  `selection_digest` so a reader can confirm two runs selected the same cells.
* Nothing is silently dropped: every cell that could not be used is counted in
  `skipped.by_reason` with the error, and cells beyond the cap are counted too.
* If neither tokenizer nor endpoint can measure anything the tool exits non-zero
  and writes nothing — it never emits a JSON that looks like a measurement when
  it measured nothing.
* Synthetic fallback texts (only used when replay yields too few cells) are
  tagged `condition: "synthetic"` and are excluded from the D/A ratio check.
* A `verdict` block states, in words, the error direction, its magnitude, the
  upper-bound answer and the cache hazard, each with the numbers behind it.
* Every metric is measured on the FULL text. The sample's `chars`, `utf8_bytes`,
  `real_tokens` and `proxy_tokens` all describe the full text, while `text` is only
  the truncated artifact copy; `measurement_consistency()` re-derives that from the
  stored hashes so the confusion cannot survive unnoticed.

Usage:
    python tools/token_proxy_calibration.py --out eval/token_proxy_calibration.json
    python tools/token_proxy_calibration.py --cap 40 --max-units 30   # wider sample
    python tools/token_proxy_calibration.py --no-endpoint             # offline tokenizer only
    python tools/token_proxy_calibration.py --no-replay               # synthetic only
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import shutil
import statistics
import sys
import tempfile
import time
import traceback
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
ENV_LOCAL = ROOT / ".env.local"
RUNNERS = ROOT / "bench" / "aci" / "runners"
LIVE_RESULTS = ROOT / "bench" / "aci" / "results" / "latest_live.json"

# The measured surface, hashed into the artifact the same way cross_shell_bench.py
# does it, so claim_gate (C12) can tell whether a stored calibration still
# describes the current code.
EVIDENCE_GLOBS = [
    "bench/aci/runners/live_agent_loop.py",
    "bench/aci/results/*.json",
    "tools/token_proxy_calibration.py",
]

# Reuse the harness rather than reimplementing it. `live_agent_loop` inserts its
# own directory on sys.path and imports `fixture_deps`, so this also wires up the
# offline dependency materialisation that `prepare_workspace` needs.
sys.path.insert(0, str(RUNNERS))
HARNESS_IMPORT_ERROR: str | None = None
try:
    import live_agent_loop as H  # noqa: E402
except Exception as _import_error:  # noqa: BLE001 - the harness is edited concurrently
    # The runner is under active development (another writer can leave it
    # mid-edit). Degrading here keeps the tokenizer measurement — the primary
    # one — available, and the degradation is recorded in the artifact rather
    # than hidden.
    H = None  # type: ignore[assignment]
    HARNESS_IMPORT_ERROR = f"{type(_import_error).__name__}: {_import_error}"

CONDITIONS = ("raw_shell", "verseshell_aci")

# Every metric this tool publishes has a different caliber. The proxy is an
# OBSERVATION, the tokenizer count is a REPLAY of a real BPE on the full text, and
# the endpoint number is an ENDPOINT USAGE reading with its own hazards. They are
# not interchangeable and none of them is a cost number. This block is published
# verbatim in the artifact so a reader cannot mistake one for another.
CALIBER_LABELS: dict[str, dict[str, Any]] = {
    "proxy_tokens": {
        "caliber": "observation_proxy",
        "measured_on": "the FULL observation text (never the truncated `text` copy)",
        "definition": "estimate_tokens(text) = max(1, len(text) // 4)",
        "is_a_real_token_count": False,
        "is_a_cost": False,
        "must_not_be_read_as": [
            "a real BPE token count",
            "an endpoint usage.prompt_tokens value",
            "a billable/cost token count",
        ],
        "known_error": (
            "shape-dependent and two-sided: it under-counts CJK and ASCII JSON/code "
            "observations and over-counts plain English prose, so no single "
            "correction factor applies"
        ),
    },
    "real_tokens": {
        "caliber": "real_bpe_replay",
        "measured_on": "the FULL observation text (never the truncated `text` copy)",
        "definition": (
            "len(tokenizer.encode(text)) for the observation text the model saw in "
            "the stored run, replayed through the real harness functions"
        ),
        "is_a_real_token_count": True,
        "is_a_cost": False,
        "reference_tokenizer": "cl100k_base (GPT-4/3.5 family, published) — not the vocabulary of the endpoint model",
        "must_not_be_read_as": [
            "the endpoint's usage.prompt_tokens",
            "the endpoint model's own tokenizer (vocabularies differ; see endpoint_cross_check)",
            "a billable/cost token count",
        ],
    },
    "endpoint_tokens": {
        "caliber": "endpoint_usage",
        "measured_on": "the same texts, secondarily, under the unique-nonce protocol",
        "definition": (
            "min over unique-nonce draws of usage.prompt_tokens minus the nonce "
            "baseline; stable only when >= 2 mutually agreeing uncontaminated draws"
        ),
        "is_a_real_token_count": None,
        "is_a_cost": False,
        "hazard": "content-cached, and intermittently inflated by a constant ~+170 tokens",
        "must_not_be_read_as": [
            "ground truth for the text's token count",
            "a pure function of the text",
            "a cost estimate",
        ],
    },
    "recorded_proxy_tokens": {
        "caliber": "stored_observation_proxy_from_the_live_run",
        "measured_on": "the stored live row (`observation_tokens`)",
        "is_a_real_token_count": False,
        "is_a_cost": False,
        "note": "the already-published proxy number; kept only for replay fidelity, never recomputed as real tokens",
    },
    "chars": {
        "caliber": "text_length_metric",
        "unit": "unicode code points",
        "is_a_real_token_count": False,
        "is_a_cost": False,
    },
    "utf8_bytes": {
        "caliber": "text_length_metric",
        "unit": "UTF-8 bytes",
        "is_a_real_token_count": False,
        "is_a_cost": False,
        "why_it_matters": (
            "for a byte-level BPE this is the count that bounds real_tokens "
            "(real_tokens <= utf8_bytes), unlike the char count"
        ),
    },
    "ratio_check": {
        "caliber": "real_bpe_replay_over_replayed_cells",
        "measured_on": "cells replayable from the stored run, paired within (task_id, source_run)",
        "is_a_real_token_count": False,
        "is_a_cost": False,
        "note": (
            "a recomputed D/A ratio on a replayable subset, not the whole benchmark "
            "round; the published_proxy_ratio it carries is a separate historical "
            "cohort number and must not be combined with the recomputed values"
        ),
    },
}


def proxy_estimate(text: str) -> int:
    """The proxy under measurement: the harness function when importable.

    When the harness cannot be imported, the same one-line definition is used and
    `proxy_source` in the artifact says so.
    """
    if H is not None:
        fn = H.estimate_tokens
        return fn(text)
    return max(1, len(text) // 4)


def current_git_rev() -> str | None:
    """HEAD at generation time; the harness helper when importable."""
    if H is not None:
        return H.current_git_rev()
    import subprocess

    try:
        proc = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT,
                              capture_output=True, text=True)
    except OSError:
        return None
    return proc.stdout.strip() if proc.returncode == 0 else None

# ── Real tokenizer (tiered resolution) ──
#
# cl100k_base is fetched from the same URL tiktoken_ext.openai_public uses; the
# hash is tiktoken's own expected_hash, so a cached/ downloaded file is verified
# byte-for-byte against the published vocabulary before it is trusted.
CL100K_URL = "https://openaipublic.blob.core.windows.net/encodings/cl100k_base.tiktoken"
CL100K_SHA256 = "223921b76ee99bde995b7ff738513eef100fb51d18c93597a113bcffe865b2a7"
CL100K_PAT_STR = (
    r"""'(?i:[sdmt]|ll|ve|re)|[^\r\n\p{L}\p{N}]?+\p{L}++|\p{N}{1,3}+| ?[^\s\p{L}\p{N}]++[\r\n]*+|\s++$|\s*[\r\n]|\s+(?!\S)|\s"""
)
CL100K_SPECIAL_TOKENS = {
    "<|endoftext|>": 100257,
    "<|fim_prefix|>": 100258,
    "<|fim_middle|>": 100259,
    "<|fim_suffix|>": 100260,
    "<|endofprompt|>": 100276,
}

# ── Endpoint probe protocol ──

# Every probe request is made unique by prefixing a fresh random nonce, so the
# endpoint's content-keyed `usage` cache can never be hit (see module docstring).
NONCE_HEX_CHARS = 12
PLACEHOLDER = "x"
BASELINE_SEED_DRAWS = 5          # baseline draws taken before the first sample
DEFAULT_ENDPOINT_DRAWS = 4       # unique-nonce draws per text
DEFAULT_ENDPOINT_MAX = 20        # replay samples cross-checked through the endpoint
CONTAMINATION_MIN_TOKENS = 60    # a draw this far above the minimum is "loaded"
MIN_FRESH_DRAWS = 2              # below this a text is `unstable`

# A fixed ~400-char English paragraph measured on every run as a calibration
# anchor: the acceptance criterion for this tool is that ~400 English characters
# cost ~100 proxy tokens and land in the 80-120 real-token region.
ANCHOR_TEXT = ("The quick brown fox jumps over the lazy dog. " * 9)[:400]
ANCHOR_EXPECTED_REAL_RANGE = (80, 120)
ANCHOR_NAME = "prose_english_400"

# Deterministic fallback corpus, used only when replay yields too few usable
# cells. Each entry is literal text so the tool stays self-contained and needs no
# dataset download.
FALLBACK_TEXTS: list[tuple[str, str]] = [
    (
        "source_file_python",
        "import json\n"
        "from pathlib import Path\n"
        "\n"
        "\n"
        "class WorkspaceIndex:\n"
        "    \"\"\"Minimal deterministic index over a workspace tree.\"\"\"\n"
        "\n"
        "    def __init__(self, root: Path) -> None:\n"
        "        self.root = root\n"
        "        self.files: dict[str, int] = {}\n"
        "\n"
        "    def scan(self, suffix: str = \".py\") -> dict[str, int]:\n"
        "        for path in sorted(self.root.rglob(\"*\" + suffix)):\n"
        "            if \"__pycache__\" in path.parts:\n"
        "                continue\n"
        "            self.files[path.relative_to(self.root).as_posix()] = path.stat().st_size\n"
        "        return self.files\n"
        "\n"
        "    def total_bytes(self) -> int:\n"
        "        return sum(self.files.values())\n"
        "\n"
        "\n"
        "def main() -> int:\n"
        "    index = WorkspaceIndex(Path.cwd())\n"
        "    index.scan()\n"
        "    print(json.dumps({\"files\": len(index.files), \"bytes\": index.total_bytes()}))\n"
        "    return 0\n"
        "\n"
        "\n"
        "if __name__ == \"__main__\":\n"
        "    raise SystemExit(main())\n",
    ),
    (
        "pytest_failure_output",
        "============================= test session starts =============================\n"
        "platform win32 -- Python 3.10.11, pytest-7.4.4, pluggy-1.3.0\n"
        "rootdir: C:\\Users\\dev\\AppData\\Local\\Temp\\aci-live-python_fix_pytest_fail-9f2c1a\n"
        "collected 3 items\n"
        "\n"
        "tests/test_math.py::test_add FAILED                                    [ 33%]\n"
        "tests/test_math.py::test_add_negative FAILED                           [ 66%]\n"
        "tests/test_math.py::test_mul PASSED                                    [100%]\n"
        "\n"
        "================================== FAILURES ===================================\n"
        "_________________________________ test_add ____________________________________\n"
        "\n"
        "    def test_add():\n"
        "        from mathlib import add\n"
        ">       assert add(2, 3) == 5\n"
        "E       assert 6 == 5\n"
        "E        +  where 6 = add(2, 3)\n"
        "\n"
        "tests/test_math.py:6: AssertionError\n"
        "____________________________ test_add_negative ________________________________\n"
        "\n"
        "    def test_add_negative():\n"
        "        from mathlib import add\n"
        ">       assert add(-1, 1) == 0\n"
        "E       assert -1 == 0\n"
        "E        +  where -1 = add(-1, 1)\n"
        "\n"
        "tests/test_math.py:10: AssertionError\n"
        "=========================== short test summary info ===========================\n"
        "FAILED tests/test_math.py::test_add - assert 6 == 5\n"
        "FAILED tests/test_math.py::test_add_negative - assert -1 == 0\n"
        "========================= 2 failed, 1 passed in 0.08s =========================\n"
        "\n"
        "[EXIT: 1]\n",
    ),
    (
        "cargo_diagnostic",
        "   Compiling bench_fix v0.1.0 (C:\\Users\\dev\\AppData\\Local\\Temp\\aci-live-rust_fix_compile_error-7d1b0e)\n"
        "error[E0308]: mismatched types\n"
        " --> src\\lib.rs:1:36\n"
        "  |\n"
        "1 | pub fn add(a: i32, b: i32) -> String {\n"
        "  |        ---                    ^^^^^^ expected `String`, found `i32`\n"
        "  |        |\n"
        "  |        expected `String` because of return type\n"
        "2 |     a + b\n"
        "  |     ----- this expression has type `i32`\n"
        "  |\n"
        "  = note: expected struct `String`\n"
        "             found type `i32`\n"
        "\n"
        "error: aborting due to 1 previous error\n"
        "\n"
        "For more information about this error, try `rustc --explain E0308`.\n"
        "error: could not compile `bench_fix` (lib) due to 1 previous error\n"
        "\n"
        "[STDERR]\n"
        "    Checking bench_fix v0.1.0 (C:\\Users\\dev\\AppData\\Local\\Temp\\aci-live-rust_fix_compile_error-7d1b0e)\n"
        "    Finished dev [unoptimized + debuginfo] target(s) in 0.42s\n"
        "\n"
        "[EXIT: 101]\n",
    ),
    (
        "cjk_paragraph",
        "这是一个用于校准分词器代理的中文段落。观测文本往往包含中文注释、错误信息"
        "以及路径名称，而按字符数除以四来估算词元数量的做法在非 ASCII 文本上会严重"
        "低估真实开销。中文汉字通常每个字符需要一个或两个词元，标点符号同样需要词元，"
        "因此对于纯中文的观测文本，真实词元数可能达到代理估算值的数倍。"
        "这个样本用于量化该偏差，并检验“每四个字符一个词元”是否能作为真实词元数的上界。"
        "结论是：不能。对于包含中文的观测文本，该代理是一个下界而非上界。"
        "在混合中英文的技术文档中，偏差取决于中文字符所占的比例。"
        "建议在报告观测开销时，对非 ASCII 文本单独说明其估算方法。\n",
    ),
    (
        "long_json_envelope",
        json.dumps(
            {
                "ok": True,
                "files": [
                    {
                        "path": "src/lib.rs",
                        "content_hash": "sha256:2551a0f2f738405daa1340ba7e0507f1843dc101231f37ac55b6a31203c28fb6",
                        "total_lines": 12,
                        "text": "pub fn add(a: i32, b: i32) -> i32 {\n    a + b\n}\n\n#[cfg(test)]\nmod tests {\n    use super::*;\n\n    #[test]\n    fn test_add() {\n        assert_eq!(add(2, 3), 5);\n    }\n}\n",
                    },
                    {
                        "path": "tests/test_math.py",
                        "content_hash": "sha256:8f14e45fceea167a5a36dedd4bea2543f0b0e1d2c3b4a5968778695a4b3c2d1e",
                        "total_lines": 14,
                        "text": "import sys\nfrom pathlib import Path\n\nsys.path.insert(0, str(Path(__file__).resolve().parents[1]))\n\nfrom mathlib import add\n\n\ndef test_add():\n    assert add(2, 3) == 5\n",
                    },
                ],
                "errors": [],
                "summary": "read 2 files (26 lines) in 3.1ms",
                "stats": {"files_read": 2, "lines_returned": 26, "truncated": False},
            },
            ensure_ascii=False,
        ),
    ),
]

# The shape panel: archetypal observation shapes, always measured, so the
# artifact can state the proxy's error per shape instead of only in aggregate.
# Each entry is literal text (no downloads, no workspace needed).
_HEX_DIGEST = hashlib.sha256(b"token-proxy-calibration shape panel").hexdigest()
_BASE64_BLOB = base64.b64encode(bytes(range(96))).decode("ascii")
SHAPE_PANEL: list[tuple[str, str]] = [
    (ANCHOR_NAME, ANCHOR_TEXT),
    (
        "prose_english_800",
        (
            "A tokenizer turns a string into the sequence of sub-word units the model "
            "actually consumes. The proxy used throughout this repository divides the "
            "character count by four, which happens to be close for ordinary English "
            "prose because the most common words are single tokens and a token averages "
            "roughly four characters. That rule of thumb breaks down as soon as the text "
            "stops looking like prose: source code spends characters on punctuation and "
            "indentation, JSON envelopes spend them on quotes, braces and digests, and "
            "Chinese text spends them on characters that are not shared with English. "
        )
        * 2,
    ),
    ("python_source", FALLBACK_TEXTS[0][1]),
    ("pytest_failure_output", FALLBACK_TEXTS[1][1]),
    ("cargo_diagnostic", FALLBACK_TEXTS[2][1]),
    ("cjk_paragraph", FALLBACK_TEXTS[3][1]),
    ("json_envelope", FALLBACK_TEXTS[4][1]),
    ("json_minified_tiny", '{"ok": true}'),
    ("hex_digest_line", f'{{"ok": true, "content_hash": "sha256:{_HEX_DIGEST}"}}'),
    ("base64_blob", f'{{"ok": true, "encoding": "base64", "data": "{_BASE64_BLOB}"}}'),
    (
        "log_line_300",
        "2026-09-25T02:41:08.123Z  INFO live_agent_loop: turn=3 condition=verseshell_aci "
        "task=python_fix_pytest_fail op=ae.run_tests elapsed_ms=842 exit_code=1 "
        "stdout_bytes=1820 stderr_bytes=0 truncated=false workspace=C:\\Users\\dev\\AppData\\Local\\Temp\\aci-live-python_fix_pytest_fail-9f2c1a\n",
    ),
]

# Length ladder: the same text at increasing lengths. Both tokenizers must report
# strictly increasing counts, which is the cheapest available proof that the
# numbers are counts and not artifacts (the buggy artifact reported 175 tokens
# for a 12-character text and 178 for a 552-character one).
LADDER_CHARS = (16, 64, 256, 1024, 4096)
LADDER_FILLER = "The quick brown fox jumps over the lazy dog. "

# CJK / wide-character ranges. Used only for the per-character-class breakdown
# and the byte-class approximation, never for the primary token count.
_CJK_RANGES = (
    (0x2E80, 0x2EFF), (0x3040, 0x30FF), (0x3190, 0x319F), (0x3400, 0x4DBF),
    (0x4E00, 0x9FFF), (0xF900, 0xFAFF), (0xFF00, 0xFFEF), (0x20000, 0x2FA1F),
)


def _is_cjk(ch: str) -> bool:
    cp = ord(ch)
    return any(lo <= cp <= hi for lo, hi in _CJK_RANGES)


def _display(path: Path) -> str:
    """Repo-relative path when possible; absolute otherwise (never raise)."""
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path)


# ── Provenance ──

def evidence_fingerprint(globs: list[str]) -> str:
    """Content hash of the measured surface; same convention as cross_shell_bench."""
    digest = hashlib.sha256()
    paths = sorted(
        p for pat in globs for p in ROOT.glob(pat)
        if p.is_file() and "__pycache__" not in p.parts
    )
    for path in paths:
        digest.update(path.relative_to(ROOT).as_posix().encode())
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


# ── Credentials ──

def load_env(path: Path = ENV_LOCAL) -> dict[str, str]:
    """Same KEY=VALUE convention as tools/live_bench.py. Values are never logged."""
    env: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        env[key.strip()] = value.strip()
    return env


# ── Tokenizer resolution ──

def tiktoken_cache_dirs() -> list[Path]:
    """The directories tiktoken itself consults, in its own order."""
    dirs: list[Path] = []
    for key in ("TIKTOKEN_CACHE_DIR", "DATA_GYM_CACHE_DIR"):
        value = os.environ.get(key)
        if value:
            dirs.append(Path(value))
    dirs.append(Path(tempfile.gettempdir()) / "data-gym-cache")
    return dirs


def cl100k_cache_path() -> Path:
    """tiktoken's cache file name for the cl100k_base URL (sha1 of the URL)."""
    return tiktoken_cache_dirs()[0] / hashlib.sha1(CL100K_URL.encode()).hexdigest()


def _parse_cl100k_bpe(data: bytes) -> dict[bytes, int]:
    ranks: dict[bytes, int] = {}
    for line in data.splitlines():
        if not line:
            continue
        token, rank = line.split()
        ranks[base64.b64decode(token)] = int(rank)
    return ranks


def _build_cl100k(data: bytes):
    """Construct cl100k_base from raw BPE bytes using the documented spec."""
    import tiktoken  # imported lazily: the approximation tier must not need it

    return tiktoken.Encoding(
        name="cl100k_base",
        pat_str=CL100K_PAT_STR,
        mergeable_ranks=_parse_cl100k_bpe(data),
        special_tokens=dict(CL100K_SPECIAL_TOKENS),
    )


def download_cl100k(timeout: float = 90.0) -> bytes:
    """Fetch the cl100k_base BPE file with proxies disabled, and verify its hash.

    The ambient proxy configuration on this machine cannot reach
    openaipublic.blob.core.windows.net (`ProxyError: Unable to connect to
    proxy`), which is why `tiktoken.get_encoding` fails out of the box. A direct
    connection works, so the download deliberately ignores proxy settings.
    """
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(urllib.request.Request(CL100K_URL), timeout=timeout) as resp:
        data = resp.read()
    actual = hashlib.sha256(data).hexdigest()
    if actual != CL100K_SHA256:
        raise ValueError(
            f"cl100k_base hash mismatch: expected {CL100K_SHA256}, got {actual}"
        )
    return data


# Byte-class approximation (tier 4 only). Coefficients are documented constants
# fitted to this repository's own shape panel measured against cl100k_base, NOT to
# the endpoint:
#   * English letters + spaces merge into ~5.0 characters per token;
#   * digit runs are split in groups of at most three (`\p{N}{1,3}`), ~2.0 chars;
#   * punctuation and symbols rarely merge, ~1.5 chars per token;
#   * a newline is its own token;
#   * a CJK character is ~1 token (cl100k rarely merges across CJK);
#   * other non-ASCII text is treated like punctuation.
# It is deliberately simple. Its residual error is measured on every run and
# stored in `tokenizer.approximation_error_vs_cl100k` (~20% mean, ~70% worst on
# punctuation-dense output), which is exactly why it is the last tier and why the
# artifact is flagged `is_approximation` when it is used.
BYTE_CLASS_RATES = {
    "letters_and_spaces": 1 / 5.0,
    "digits": 1 / 2.0,
    "punctuation": 1 / 1.5,
    "newlines": 1.0,
    "cjk": 1.0,
    "other_non_ascii": 1 / 1.5,
}


def byte_class_approximation(text: str) -> int:
    """Documented byte-class token approximation (tier-4 fallback only)."""
    if not text:
        return 0
    counts = {k: 0 for k in BYTE_CLASS_RATES}
    for ch in text:
        if ch == "\n":
            counts["newlines"] += 1
        elif ch.isascii() and (ch.isalpha() or ch == " "):
            counts["letters_and_spaces"] += 1
        elif ch.isascii() and ch.isdigit():
            counts["digits"] += 1
        elif ch.isascii():
            counts["punctuation"] += 1
        elif _is_cjk(ch):
            counts["cjk"] += 1
        else:
            counts["other_non_ascii"] += 1
    total = sum(counts[k] * rate for k, rate in BYTE_CLASS_RATES.items())
    return max(1, int(round(total)))


def approximation_self_check(counter: Callable[[str], int]) -> dict[str, Any]:
    """Measure the tier-4 fallback against the real tokenizer on the shape panel.

    The fallback is only ever used when no real tokenizer is reachable, but its
    accuracy is measured on every run so a reader can judge it instead of taking
    the constants on trust.
    """
    rows = []
    for name, text in SHAPE_PANEL:
        real = counter(text)
        approx = byte_class_approximation(text)
        rows.append({
            "name": name,
            "chars": len(text),
            "real_tokens": real,
            "approximation_tokens": approx,
            "relative_error": round((approx - real) / real, 4) if real else None,
        })
    errors = [abs(r["relative_error"]) for r in rows if r["relative_error"] is not None]
    return {
        "available": True,
        "n": len(errors),
        "mean_abs_relative_error": round(statistics.fmean(errors), 4) if errors else None,
        "max_abs_relative_error": round(max(errors), 4) if errors else None,
        "per_shape": rows,
        "note": (
            "the byte-class approximation is the LAST tier and is never used while a "
            "real tokenizer resolves; these are its residuals against the primary "
            "tokenizer on the shape panel, reported so the fallback's quality is "
            "visible rather than assumed"
        ),
    }


def resolve_tokenizer(*, allow_download: bool = True) -> tuple[Callable[[str], int], dict[str, Any]]:
    """Return (counter, provenance). Tiers 1-3 are real tokenizers; tier 4 is not."""
    info: dict[str, Any] = {
        "primary": None,
        "tier": None,
        "is_approximation": False,
        "how_resolved": None,
        "attempts": [],
        "vocab_size": None,
        "bpe_sha256": None,
        "cache_path": _display(cl100k_cache_path()),
        "cache_present_before": cl100k_cache_path().exists(),
        "notes": [],
    }

    # tier 1 — tiktoken with its own cache
    try:
        import tiktoken

        enc = tiktoken.get_encoding("cl100k_base")
        info.update({
            "primary": "tiktoken:cl100k_base",
            "tier": 1,
            "how_resolved": "tiktoken.get_encoding('cl100k_base') succeeded from the local tiktoken cache",
            "vocab_size": enc.n_vocab,
        })
        return (lambda text: len(enc.encode(text))), info
    except Exception as error:  # noqa: BLE001 - every tier failure is recorded
        info["attempts"].append({
            "tier": 1, "what": "tiktoken.get_encoding('cl100k_base')",
            "ok": False, "error": f"{type(error).__name__}: {error}"[:300],
        })

    # tier 2 — a locally cached BPE file, parsed and built from the published spec
    for cache_dir in tiktoken_cache_dirs():
        candidate = cache_dir / hashlib.sha1(CL100K_URL.encode()).hexdigest()
        if not candidate.exists():
            continue
        try:
            data = candidate.read_bytes()
            actual = hashlib.sha256(data).hexdigest()
            if actual != CL100K_SHA256:
                raise ValueError(f"cached file hash mismatch ({actual})")
            enc = _build_cl100k(data)
            info.update({
                "primary": "tiktoken:cl100k_base",
                "tier": 2,
                "how_resolved": f"parsed the cached BPE file at {_display(candidate)}",
                "vocab_size": enc.n_vocab,
                "bpe_sha256": actual,
                "cache_path": _display(candidate),
            })
            return (lambda text: len(enc.encode(text))), info
        except Exception as error:  # noqa: BLE001
            info["attempts"].append({
                "tier": 2, "what": f"parse cached BPE at {_display(candidate)}",
                "ok": False, "error": f"{type(error).__name__}: {error}"[:300],
            })

    # tier 3 — fetch the BPE file once, verify, cache, build
    if allow_download:
        try:
            data = download_cl100k()
            cache_dir = cl100k_cache_path().parent
            cache_dir.mkdir(parents=True, exist_ok=True)
            target = cache_dir / hashlib.sha1(CL100K_URL.encode()).hexdigest()
            tmp = target.with_suffix(".tmp")
            tmp.write_bytes(data)
            os.replace(tmp, target)
            enc = _build_cl100k(data)
            info.update({
                "primary": "tiktoken:cl100k_base",
                "tier": 3,
                "how_resolved": (
                    "downloaded the BPE file once with proxies disabled, verified "
                    f"sha256, cached it at {_display(target)}"
                ),
                "vocab_size": enc.n_vocab,
                "bpe_sha256": CL100K_SHA256,
            })
            info["notes"].append(
                "the cl100k_base BPE file was fetched over the network on this run; "
                "it is now cached, so subsequent runs are fully offline"
            )
            return (lambda text: len(enc.encode(text))), info
        except Exception as error:  # noqa: BLE001
            info["attempts"].append({
                "tier": 3, "what": "download cl100k_base with proxies disabled",
                "ok": False, "error": f"{type(error).__name__}: {error}"[:300],
            })
    else:
        info["attempts"].append({
            "tier": 3, "what": "download cl100k_base with proxies disabled",
            "ok": False, "error": "disabled by --no-download",
        })

    # tier 4 — documented approximation, loudly labelled
    info.update({
        "primary": "byte_class_approximation",
        "tier": 4,
        "is_approximation": True,
        "how_resolved": "no real tokenizer was reachable; using the documented byte-class approximation",
        "byte_class_rates": BYTE_CLASS_RATES,
    })
    info["notes"].append(
        "TIER 4: real token counts are UNAVAILABLE on this run. Every `real_tokens` "
        "in this artifact is a byte-class APPROXIMATION, not a tokenizer count, and "
        "the error direction/magnitude below are approximate too."
    )
    return byte_class_approximation, info


# ── Text classification ──

def classify_text(text: str) -> dict[str, Any]:
    non_ascii = sum(1 for ch in text if ord(ch) > 127)
    cjk = sum(1 for ch in text if _is_cjk(ch))
    if cjk:
        char_class = "cjk"
    elif non_ascii:
        char_class = "non_ascii_other"
    else:
        char_class = "ascii_only"
    lines = text.count("\n") + 1
    chars = len(text)
    if chars < 64:
        size_bucket = "lt_64"
    elif chars < 256:
        size_bucket = "64_255"
    elif chars < 1024:
        size_bucket = "256_1023"
    else:
        size_bucket = "gte_1024"
    return {
        "char_class": char_class,
        "chars": chars,
        "lines": lines,
        "non_ascii_chars": non_ascii,
        "cjk_chars": cjk,
        "size_bucket": size_bucket,
        # "long multi-line" is a shape flag, independent of the char class.
        "long_multiline": bool(lines >= 8 and chars >= 400),
    }


# ── Endpoint measurement (unique-nonce protocol) ──

def fresh_nonce() -> str:
    return uuid.uuid4().hex[:NONCE_HEX_CHARS]


def nonce_prefix(nonce: str) -> str:
    return f"[{nonce}] "


class Endpoint:
    """`usage.prompt_tokens` probes that cannot hit the endpoint's usage cache.

    Every request body carries a fresh nonce, so no two requests ever share
    content. Draws are collected first and reduced afterwards, because the
    uncontaminated value is only identifiable relative to the whole draw pool.
    """

    def __init__(self, *, model: str, api_key: str, base_url: str,
                 draws: int = DEFAULT_ENDPOINT_DRAWS) -> None:
        self.model = model
        self.api_key = api_key
        self.base_url = base_url
        self.draws = draws
        self.calls = 0
        self.failures: list[str] = []
        self.contents: set[str] = set()
        self.baseline_draws: list[int] = []

    def prompt_tokens(self, content: str, *, attempts: int = 2) -> int:
        """One probe request. `content` is never logged and never stored raw."""
        self.contents.add(hashlib.sha256(content.encode("utf-8")).hexdigest())
        last: Exception | None = None
        for attempt in range(attempts):
            try:
                # Reuse the harness call path: chat_completion is the function the
                # live loop uses, so the measurement rides the same transport and
                # retry policy. max_tokens=1 keeps the cost to the prompt alone.
                resp = H.chat_completion(
                    [{"role": "user", "content": content}],
                    [],
                    model=self.model,
                    api_key=self.api_key,
                    base_url=self.base_url,
                    max_tokens=1,
                    temperature=0.0,
                )
                usage = resp.get("usage") or {}
                value = usage.get("prompt_tokens")
                if not isinstance(value, int) or value <= 0:
                    raise RuntimeError(
                        "endpoint returned no usable usage.prompt_tokens: "
                        + json.dumps(resp, ensure_ascii=False)[:300]
                    )
                self.calls += 1
                return value
            except Exception as error:  # noqa: BLE001 - retried, then recorded
                last = error
                if attempt + 1 < attempts:
                    time.sleep(1.0 + attempt)
        self.failures.append(f"{type(last).__name__}: {last}"[:300])
        raise RuntimeError(f"{type(last).__name__}: {last}")

    def baseline_draw(self) -> None:
        """One uncontaminated-baseline draw: a unique nonce + a 1-char placeholder."""
        value = self.prompt_tokens(nonce_prefix(fresh_nonce()) + PLACEHOLDER)
        self.baseline_draws.append(value)

    def collect(self, text: str) -> dict[str, Any]:
        """K unique-nonce draws of `text`, preceded by one baseline draw.

        One baseline draw per text is enough: the baseline pool grows across the
        whole run (one draw per cross-checked text, ~30 draws), and the minimum
        over that pool is what cancels the chat-template overhead. Returns raw
        draws only; the reduction happens in `reduce_endpoint`, once every
        baseline draw from the whole run is available.
        """
        raws: list[int] = []
        bases: list[int] = []
        errors: list[str] = []
        for index in range(self.draws):
            if index == 0:
                try:
                    self.baseline_draw()
                    bases.append(self.baseline_draws[-1])
                except Exception as error:  # noqa: BLE001
                    errors.append(f"baseline: {type(error).__name__}: {error}"[:200])
            try:
                raws.append(self.prompt_tokens(nonce_prefix(fresh_nonce()) + text))
            except Exception as error:  # noqa: BLE001
                errors.append(f"sample: {type(error).__name__}: {error}"[:200])
        return {"raws": raws, "bases": bases, "errors": errors}


def _fresh_cluster(values: list[int]) -> tuple[list[int], int]:
    """Split draws into the uncontaminated cluster and its tolerance."""
    if not values:
        return [], 0
    low = min(values)
    tol = min(max(5, int(round(0.05 * low))), CONTAMINATION_MIN_TOKENS)
    return [v for v in values if v - low <= tol], tol


def reduce_endpoint(collected: dict[str, Any], baseline_draws: list[int]) -> dict[str, Any]:
    """Turn raw draws into an estimate, an interval and a stability verdict."""
    raws = list(collected.get("raws") or [])
    base_fresh, base_tol = _fresh_cluster(baseline_draws)
    overhead_raw = min(baseline_draws) if baseline_draws else None
    overhead_median = statistics.median(base_fresh) if base_fresh else None
    overhead_spread = (max(base_fresh) - min(base_fresh)) if len(base_fresh) > 1 else 0

    result: dict[str, Any] = {
        "endpoint_measured": bool(raws) and overhead_raw is not None,
        "draws": raws,
        "draw_min": min(raws) if raws else None,
        "draw_max": max(raws) if raws else None,
        "draw_spread": (max(raws) - min(raws)) if raws else None,
        "contaminated_draws": None,
        "fresh_draws": None,
        "fresh_cluster": None,
        "fresh_tolerance_tokens": None,
        "baseline_raw_min": overhead_raw,
        "baseline_median_of_fresh": overhead_median,
        "baseline_fresh_spread": overhead_spread,
        "baseline_draws_available": len(baseline_draws),
        "endpoint_tokens": None,
        "endpoint_tokens_median_estimator": None,
        "endpoint_interval": None,
        "endpoint_noise_tokens": None,
        "stable": False,
        "unstable_reason": None,
        "errors": collected.get("errors") or [],
    }
    if not result["endpoint_measured"]:
        result["unstable_reason"] = "no usable endpoint draw"
        return result

    fresh, tol = _fresh_cluster(raws)
    result["fresh_cluster"] = fresh
    result["fresh_draws"] = len(fresh)
    result["fresh_tolerance_tokens"] = tol
    result["contaminated_draws"] = len(raws) - len(fresh)

    estimate = max(0, min(raws) - overhead_raw + 1)  # +1: the placeholder is 1 token
    fresh_spread = (max(fresh) - min(fresh)) if len(fresh) > 1 else 0
    # The interval is half the observed spread of the uncontaminated cluster
    # (min and max are the two tails of the same distribution), floored at one
    # token; the raw spread is kept alongside it so the choice is auditable.
    spread = max(fresh_spread, overhead_spread, 1)
    half_width = max(1, int(round(spread / 2)))
    result["endpoint_spread_tokens"] = spread
    result["endpoint_noise_tokens"] = half_width
    result["endpoint_interval"] = [max(0, estimate - half_width), estimate + half_width]
    result["endpoint_tokens"] = estimate
    if overhead_median is not None and fresh:
        median_estimate = statistics.median(fresh) - overhead_median + 1
        result["endpoint_tokens_median_estimator"] = int(round(max(0, median_estimate)))

    if len(fresh) < MIN_FRESH_DRAWS:
        result["unstable_reason"] = (
            f"only {len(fresh)}/{len(raws)} draws were mutually consistent (need "
            f">= {MIN_FRESH_DRAWS}); the minimum may not be an uncontaminated draw"
        )
    elif len(fresh) > 1 and (max(fresh) - min(fresh)) > tol:
        result["unstable_reason"] = (
            f"the consistent cluster spans {max(fresh) - min(fresh)} tokens "
            f"(> {tol}); draws disagree beyond the estimator's noise"
        )
    else:
        result["stable"] = True
    return result


def endpoint_hazard_demo(endpoint: Endpoint, text: str) -> dict[str, Any]:
    """Direct, in-artifact evidence of the content-keyed usage cache."""
    demo: dict[str, Any] = {
        "text_preview": text[:80],
        "chars": len(text),
        "what": (
            "the same exact content is sent twice, then the same text is sent twice "
            "with two different nonces; a content-keyed cache makes the first pair "
            "identical and lets the nonce pair escape it"
        ),
    }
    try:
        plain = [endpoint.prompt_tokens(text) for _ in range(2)]
        demo["plain_repeated_content_prompt_tokens"] = plain
        demo["plain_repeats_are_identical"] = plain[0] == plain[1]
    except Exception as error:  # noqa: BLE001
        demo["plain_error"] = f"{type(error).__name__}: {error}"[:200]
    try:
        nonced = [endpoint.prompt_tokens(nonce_prefix(fresh_nonce()) + text) for _ in range(2)]
        demo["nonced_content_prompt_tokens"] = nonced
    except Exception as error:  # noqa: BLE001
        demo["nonce_error"] = f"{type(error).__name__}: {error}"[:200]
    return demo


# ── Trajectory replay ──

def load_units(results_path: Path) -> tuple[dict[str, Any], dict[tuple[str, str], dict[str, dict]]]:
    """Group stored rows into (task_id, source_run) units holding both conditions."""
    doc = json.loads(results_path.read_text(encoding="utf-8-sig"))
    units: dict[tuple[str, str], dict[str, dict]] = {}
    for row in doc.get("rows") or []:
        condition = row.get("condition")
        if condition not in CONDITIONS:
            continue
        source_run = row.get("source_run") or f"run_index={row.get('run_index', 0)}"
        key = (str(row.get("task_id", "?")), str(source_run))
        units.setdefault(key, {})[condition] = row
    return doc, dict(sorted(units.items()))


def replay_row(row: dict, skips: list[dict]) -> list[dict]:
    """Replay one stored row's calls and return the observation texts it produces.

    The workspace is materialised once per row and the recorded calls are replayed
    in order, because later calls depend on files earlier calls created. A cell
    that cannot be reproduced is recorded in `skips` with its reason instead of
    being dropped silently.
    """
    condition = row["condition"]
    task_id = str(row.get("task_id", "?"))
    source_run = str(row.get("source_run") or f"run_index={row.get('run_index', 0)}")
    cells: list[dict] = []

    def skip(cell_index: int | None, op: str | None, reason: str, detail: str = "") -> None:
        skips.append({
            "condition": condition, "task_id": task_id, "source_run": source_run,
            "cell_index": cell_index, "op": op, "reason": reason,
            "detail": detail[:300],
        })

    try:
        workspace = H.prepare_workspace(task_id)
    except Exception as error:  # noqa: BLE001
        skip(None, None, "prepare_workspace_failed", f"{type(error).__name__}: {error}")
        return cells

    try:
        for index, entry in enumerate(row.get("trajectory") or []):
            op = entry.get("op")
            args = entry.get("args") or {}
            if op == "task_complete":
                # Not an observation: it is a fixed {"ok": true, "acknowledged": true}
                # acknowledgement with no workspace-dependent content.
                skip(index, op, "control_call:task_complete")
                continue
            try:
                if condition == "raw_shell":
                    command = args.get("command")
                    if not command:
                        skip(index, op, "missing_command", json.dumps(args, ensure_ascii=False))
                        continue
                    text = H.execute_shell_cmd(command, str(workspace))
                    if text.startswith("[TIMEOUT after"):
                        skip(index, op, "replay_timeout", text[:120])
                        continue
                    aci_ok = None
                else:
                    ae_op = H.ACI_OP_MAP.get(op, op)
                    response = H.execute_aci_op(ae_op, args, str(workspace), H.ACI_CAPABILITIES)
                    aci_ok = response.get("ok")
                    text = H.format_aci_result(response)
                    if not aci_ok:
                        # An ACI op often acts on a file the recorded run itself
                        # created, so it legitimately cannot replay. Recorded as a
                        # skip, never as a sample.
                        code = (response.get("error") or {}).get("code", "unknown")
                        skip(index, op, f"aci_replay_failed:{code}",
                             json.dumps(response.get("error") or {}, ensure_ascii=False))
                        continue
            except Exception as error:  # noqa: BLE001
                skip(index, op, f"replay_exception:{type(error).__name__}", str(error))
                continue

            if not text or not text.strip():
                skip(index, op, "empty_text")
                continue

            cells.append({
                "cell_index": index,
                "op": op,
                "condition": condition,
                "task_id": task_id,
                "source_run": source_run,
                "text": text,
                "proxy_tokens": proxy_estimate(text),
                "recorded_proxy_tokens": entry.get("observation_tokens"),
                "recorded_aci_ok": entry.get("aci_ok"),
                "replay_aci_ok": aci_ok,
            })
    except Exception as error:  # noqa: BLE001
        skip(None, None, "replay_aborted", f"{type(error).__name__}: {error}")
    finally:
        shutil.rmtree(workspace, ignore_errors=True)

    return cells


def round_robin_select(per_row: dict[tuple[str, str], list[dict]], cap: int) -> list[dict]:
    """Take up to `cap` cells, one per row per pass, so a small cap still spans tasks.

    Deterministic: rows are visited in sorted order and the selection is a pure
    function of the replayed cells.
    """
    selected: list[dict] = []
    keys = sorted(per_row)
    depth = 0
    while len(selected) < cap:
        added = False
        for key in keys:
            cells = per_row[key]
            if depth < len(cells):
                selected.append(cells[depth])
                added = True
                if len(selected) >= cap:
                    break
        if not added:
            break
        depth += 1
    return selected


def spread_selection(count: int, want: int) -> list[int]:
    """Deterministically pick `want` indices evenly spread across `count` items."""
    if want >= count:
        return list(range(count))
    if want <= 0:
        return []
    step = count / want
    return sorted({min(count - 1, int(i * step)) for i in range(want)})


# ── Aggregation ──

def _stats(values: list[float]) -> dict[str, Any]:
    vals = [v for v in values if v is not None]
    if not vals:
        return {"n": 0, "mean": None, "sd": None, "median": None, "min": None, "max": None}
    return {
        "n": len(vals),
        "mean": round(statistics.fmean(vals), 4),
        "sd": round(statistics.pstdev(vals), 4) if len(vals) > 1 else 0.0,
        "median": round(statistics.median(vals), 4),
        "min": round(min(vals), 4),
        "max": round(max(vals), 4),
    }


def _group_summary(samples: list[dict], *, real_key: str = "real_tokens") -> dict[str, Any]:
    pairs = [
        (s[real_key], s["proxy_tokens"])
        for s in samples
        if s.get(real_key) is not None and s.get("proxy_tokens")
    ]
    ratios = [r / p for r, p in pairs]
    rel_errors = [(p - r) / r for r, p in pairs if r]
    over = sum(1 for r, p in pairs if r < p)
    under = sum(1 for r, p in pairs if r > p)
    equal = len(pairs) - over - under
    chars = sum(s["chars"] for s in samples if s.get(real_key) is not None)
    real_sum = sum(r for r, _ in pairs)
    return {
        "n_samples": len(samples),
        "n_scored": len(pairs),
        "real_over_proxy_ratio": _stats(ratios),
        "relative_error_proxy_vs_real": _stats(rel_errors),
        "proxy_overcounts_samples": over,
        "proxy_undercounts_samples": under,
        "exact_match_samples": equal,
        "chars_per_real_token": round(chars / real_sum, 4) if real_sum else None,
    }


def _invariant_observation(item: dict[str, Any], source: str) -> dict[str, Any]:
    """One measured text, reduced to the counts the invariant checks need."""
    return {
        "source": source,
        "name": item.get("name") or item.get("id"),
        "condition": item.get("condition"),
        "char_class": item.get("char_class"),
        "chars": item.get("chars"),
        "utf8_bytes": item.get("utf8_bytes"),
        "real_tokens": item.get("real_tokens"),
        "proxy_tokens": item.get("proxy_tokens"),
    }


def build_tokenizer_invariants(samples: list[dict],
                               panel: list[dict] | None = None) -> dict[str, Any]:
    """Which tokenizer relationships actually hold, over samples AND the panel.

    * `real_tokens <= utf8_bytes` is the invariant that MUST hold: cl100k_base is a
      byte-level BPE over UTF-8 bytes, and every token emits at least one byte, so
      the token count can never exceed the byte count. A violation means the
      tokenizer or the text plumbing is broken.
    * `real_tokens <= chars` is NOT an invariant. An earlier version of this
      artifact published it as one; it is false for any text with multi-byte
      characters (one character may become several tokens). The comparison is kept
      here as an explicitly labelled observation with the panel counterexample
      named, and the old key is retained and marked retracted rather than dropped.
    """
    panel = panel or []
    observations = [
        _invariant_observation(s, "sample") for s in samples
        if s.get("real_tokens") is not None and s.get("utf8_bytes") is not None
    ] + [
        _invariant_observation(item, "shape_panel") for item in panel
        if item.get("real_tokens") is not None and item.get("utf8_bytes") is not None
    ]

    byte_violations = [o for o in observations if o["real_tokens"] > o["utf8_bytes"]]
    char_violations = [
        o for o in observations
        if o["real_tokens"] > max(1, o["chars"] or 0)
    ]
    panel_counterexamples = [o for o in char_violations if o["source"] == "shape_panel"]
    named = next((o for o in panel_counterexamples if o["name"] == "cjk_paragraph"), None)
    if named is None and panel_counterexamples:
        named = panel_counterexamples[0]

    chars_bound_observed = {
        "observed_holds": not char_violations,
        "is_an_invariant": False,
        "chars_bound_is_not_an_invariant": True,
        "status": "RETRACTED_AS_AN_INVARIANT_KEPT_AS_AN_OBSERVATION",
        "claim_as_previously_published": (
            "real_tokens <= chars: 'cl100k_base covers at least one character per "
            "token, so real <= chars must hold'"
        ),
        "why_that_claim_is_false": (
            "cl100k_base is a byte-level BPE: a single Unicode character can encode "
            "to several UTF-8 bytes and therefore to several tokens, so no tokenizer "
            "guarantees one token per character"
        ),
        "replaced_by": "tokenizer_invariants.real_tokens_never_exceed_utf8_bytes",
        "n_checked": len(observations),
        "violations": len(char_violations),
        "violations_by_source": {
            "sample": sum(1 for o in char_violations if o["source"] == "sample"),
            "shape_panel": len(panel_counterexamples),
        },
        "counterexamples": char_violations[:10],
        "named_panel_counterexample": named,
        "counterexample_note": (
            "the cjk_paragraph sample text itself says the proxy 'is a lower bound, "
            "not an upper bound'; that sentence is measured DATA and is kept "
            "byte-identical, because changing it would change the documented "
            "counterexample. The tool's own prose (build_verdict, this block, the "
            "module docstring) states the stronger, correct claim: the proxy is not a "
            "bound in either direction."
            if named and named.get("name") == "cjk_paragraph" else None
        ),
    }

    return {
        "real_tokens_never_exceed_utf8_bytes": not byte_violations,
        "byte_invariant_detail": {
            "claim": "real_tokens <= utf8_bytes for every measured text",
            "why_it_must_hold": (
                "cl100k_base is a byte-level BPE over UTF-8 bytes: every token emits "
                "at least one byte, so real_tokens can never exceed utf8_bytes"
            ),
            "evaluated_over": "samples AND the shape panel",
            "n_checked": len(observations),
            "n_samples_checked": sum(1 for o in observations if o["source"] == "sample"),
            "n_panel_checked": sum(1 for o in observations if o["source"] == "shape_panel"),
            "n_violations": len(byte_violations),
            "violations": byte_violations[:10],
        },
        # Retained (type-stable) for readers and downstream consumers of the old
        # artifact, but explicitly NOT an invariant; see chars_bound_observed.
        "real_tokens_never_exceed_chars": not char_violations,
        "chars_bound_is_not_an_invariant": True,
        "chars_bound_observed": chars_bound_observed,
        "note": (
            "real_tokens_never_exceed_chars is retained only for backward "
            "compatibility and is NOT an invariant; read chars_bound_observed. The "
            "invariant that must hold for a byte-level BPE is "
            "real_tokens_never_exceed_utf8_bytes."
        ),
    }


def aggregate(samples: list[dict], *, panel: list[dict] | None = None) -> dict[str, Any]:
    """Per-sample and aggregate proxy-vs-real statistics, split by class/condition."""
    overall = _group_summary(samples)

    def group_by(key: str, *, include_absent: bool = False) -> dict[str, Any]:
        out: dict[str, Any] = {}
        values = sorted({s.get(key) for s in samples if s.get(key) is not None})
        for value in values:
            out[str(value)] = _group_summary([s for s in samples if s.get(key) == value])
        if include_absent and any(s.get(key) is None for s in samples):
            out["endpoint_not_measured"] = _group_summary(
                [s for s in samples if s.get(key) is None]
            )
        return out

    by_condition = {
        cond: _group_summary([s for s in samples if s["condition"] == cond])
        for cond in sorted({s["condition"] for s in samples})
    }
    by_char_class = {
        cls: _group_summary([s for s in samples if s["char_class"] == cls])
        for cls in sorted({s["char_class"] for s in samples})
    }
    by_size_bucket = {
        bucket: _group_summary([s for s in samples if s["size_bucket"] == bucket])
        for bucket in ("lt_64", "64_255", "256_1023", "gte_1024")
        if any(s["size_bucket"] == bucket for s in samples)
    }
    by_shape = {
        ("long_multiline" if flag else "short_or_single_line"): _group_summary(
            [s for s in samples if s["long_multiline"] == flag]
        )
        for flag in (True, False)
        if any(s["long_multiline"] == flag for s in samples)
    }

    mean_ratio = overall["real_over_proxy_ratio"]["mean"]
    median_ratio = overall["real_over_proxy_ratio"]["median"]
    mean_rel_error = overall["relative_error_proxy_vs_real"]["mean"]
    if mean_ratio is None:
        direction = "undetermined"
    elif overall["proxy_overcounts_samples"] > overall["proxy_undercounts_samples"]:
        direction = "proxy_overcounts_real_tokens"
    elif overall["proxy_undercounts_samples"] > overall["proxy_overcounts_samples"]:
        direction = "proxy_undercounts_real_tokens"
    else:
        direction = "mixed_no_systematic_direction"

    violations = [s for s in samples if s.get("real_tokens") is not None
                  and s["real_tokens"] > s["proxy_tokens"]]
    worst = max(violations, key=lambda s: s["real_tokens"] - s["proxy_tokens"]) if violations else None
    violation_by_class: dict[str, int] = {}
    for s in violations:
        violation_by_class[s["char_class"]] = violation_by_class.get(s["char_class"], 0) + 1

    return {
        "overall": overall,
        "by_condition": by_condition,
        "by_char_class": by_char_class,
        "by_size_bucket": by_size_bucket,
        "by_shape": by_shape,
        "error_direction": direction,
        "error_direction_detail": (
            "ratio = real_tokens/proxy_tokens; a mean ratio < 1 means the proxy "
            "OVER-counts (it charges more tokens than the tokenizer does); "
            "relative_error = (proxy - real)/real, positive means over-counting. "
            f"mean ratio={mean_ratio}, median ratio={median_ratio}, "
            f"mean relative error={mean_rel_error}."
        ),
        "upper_bound_check": {
            "claim": "len(text)//4 is an upper bound on real tokens (real <= proxy)",
            "at_least_4x_chars_per_token_holds": len(violations) == 0,
            "violations": len(violations),
            "n_samples": len(samples),
            "violation_rate": round(len(violations) / len(samples), 4) if samples else None,
            "violations_by_char_class": dict(sorted(violation_by_class.items())),
            "worst_violation": (
                {
                    "condition": worst["condition"], "op": worst["op"],
                    "task_id": worst["task_id"], "char_class": worst["char_class"],
                    "chars": worst["chars"], "proxy_tokens": worst["proxy_tokens"],
                    "real_tokens": worst["real_tokens"],
                    "proxy_undercount_tokens": worst["real_tokens"] - worst["proxy_tokens"],
                    "proxy_undercount_relative": round(
                        (worst["real_tokens"] - worst["proxy_tokens"]) / worst["real_tokens"], 4
                    ),
                }
                if worst else None
            ),
        },
        "tokenizer_invariants": build_tokenizer_invariants(samples, panel),
    }


def build_ratio_check(samples: list[dict], published_proxy_ratio: float) -> dict[str, Any]:
    """Recompute the D/A observation-token ratio with real tokens on paired cells.

    Only cells that actually came from the two live conditions are used; synthetic
    fallback texts are excluded, because they are not A or D observations.

    Scope and buckets: cells are grouped into buckets keyed by
    `(task_id, source_run)` and a bucket is used only when BOTH conditions are
    present in it. Cells from different buckets are never combined, and a cell in a
    bucket that has no counterpart is left out of the ratio (it is counted in
    `sample_scope.cells_replayable_but_unpaired`). The result is therefore a
    subset of the round — the cells that replayed AND paired — not the whole
    35-task benchmark round.

    `published_proxy_ratio` is a SEPARATE historical number: it is echoed with an
    explicit provenance label, is not the current whole-round baseline, and must
    not be combined with the recomputed ratios in this block.
    """
    live = [s for s in samples if s["condition"] in CONDITIONS and s.get("real_tokens") is not None]
    units: dict[tuple[str, str], dict[str, list[dict]]] = {}
    for s in live:
        units.setdefault((s["task_id"], s["source_run"]), {}).setdefault(
            s["condition"], []
        ).append(s)

    paired = {
        key: value for key, value in sorted(units.items())
        if value.get("raw_shell") and value.get("verseshell_aci")
    }

    per_unit: list[dict] = []
    tot = {c: {"real": 0, "proxy": 0} for c in CONDITIONS}
    for key, value in paired.items():
        entry: dict[str, Any] = {
            "task_id": key[0], "source_run": key[1],
            "cells_A": len(value["raw_shell"]), "cells_D": len(value["verseshell_aci"]),
        }
        for cond, label in (("raw_shell", "A"), ("verseshell_aci", "D")):
            real = sum(s["real_tokens"] for s in value[cond])
            proxy = sum(s["proxy_tokens"] for s in value[cond])
            tot[cond]["real"] += real
            tot[cond]["proxy"] += proxy
            entry[f"real_tokens_{label}"] = real
            entry[f"proxy_tokens_{label}"] = proxy
        entry["real_ratio_D_over_A"] = (
            round(entry["real_tokens_D"] / entry["real_tokens_A"], 4)
            if entry["real_tokens_A"] else None
        )
        entry["proxy_ratio_D_over_A"] = (
            round(entry["proxy_tokens_D"] / entry["proxy_tokens_A"], 4)
            if entry["proxy_tokens_A"] else None
        )
        entry["direction_agrees"] = (
            entry["real_ratio_D_over_A"] is not None
            and entry["proxy_ratio_D_over_A"] is not None
            and (entry["real_ratio_D_over_A"] < 1) == (entry["proxy_ratio_D_over_A"] < 1)
        )
        per_unit.append(entry)

    real_ratio = (
        round(tot["verseshell_aci"]["real"] / tot["raw_shell"]["real"], 4)
        if tot["raw_shell"]["real"] else None
    )
    proxy_ratio = (
        round(tot["verseshell_aci"]["proxy"] / tot["raw_shell"]["proxy"], 4)
        if tot["raw_shell"]["proxy"] else None
    )

    min_cells = 3
    supported = bool(paired) and all(
        sum(1 for s in live if s["condition"] == c) >= min_cells for c in CONDITIONS
    )
    reason = None
    if not supported:
        reason = (
            f"too few paired replayed cells to support a D/A ratio "
            f"(paired units={len(paired)}, A cells="
            f"{sum(1 for s in live if s['condition'] == 'raw_shell')}, D cells="
            f"{sum(1 for s in live if s['condition'] == 'verseshell_aci')}); "
            f"need >= {min_cells} cells per condition and >= 1 paired unit"
        )

    absolute_error = (
        round(real_ratio - proxy_ratio, 4)
        if real_ratio is not None and proxy_ratio is not None else None
    )
    relative_error = (
        round((proxy_ratio - real_ratio) / real_ratio, 4)
        if real_ratio and proxy_ratio is not None else None
    )
    sign_flip = (
        real_ratio is not None and proxy_ratio is not None
        and (real_ratio < 1) != (proxy_ratio < 1)
    )
    material = bool(
        sign_flip
        or (relative_error is not None and abs(relative_error) > 0.10)
    )

    units_agree = sum(1 for u in per_unit if u["direction_agrees"])
    aggregate_flip_but_units_agree = bool(
        sign_flip and per_unit and units_agree > len(per_unit) / 2
    )

    if not supported:
        conclusion = "unsupported: " + str(reason)
    elif sign_flip and aggregate_flip_but_units_agree:
        conclusion = (
            f"MATERIAL: the proxy puts the ratio on the other side of 1.0 "
            f"(real={real_ratio}, proxy={proxy_ratio}); the qualitative conclusion "
            f"('D uses fewer observation tokens than A') flips in the aggregate. "
            f"CAVEAT: {units_agree}/{len(per_unit)} individual units keep the same side "
            f"of 1.0, and both aggregate ratios are close to 1.0, so the aggregate flip "
            f"is driven by cell weighting (a few large observations), not by a per-unit "
            f"reversal."
        )
    elif sign_flip:
        conclusion = (
            f"MATERIAL: the proxy puts the ratio on the other side of 1.0 "
            f"(real={real_ratio}, proxy={proxy_ratio}); the qualitative conclusion "
            f"('D uses fewer observation tokens than A') flips."
        )
    elif material:
        conclusion = (
            f"MATERIAL: both agree D/A < 1 but the magnitude differs by "
            f"{abs(relative_error):.1%} (real={real_ratio}, proxy={proxy_ratio}), "
            f"beyond the 10% materiality threshold."
        )
    else:
        conclusion = (
            f"NOT MATERIAL: real={real_ratio} vs proxy={proxy_ratio} "
            f"({abs(relative_error or 0):.1%} difference), same side of 1.0; "
            f"the proxy's error does not change the conclusion on this sample."
        )

    return {
        "supported": supported,
        "reason_if_unsupported": reason,
        "published_proxy_ratio_D_over_A": published_proxy_ratio,
        "published_proxy_ratio_provenance": {
            "caliber": "historical_published_proxy_cohort_ratio",
            "value": published_proxy_ratio,
            "is_the_current_whole_round_baseline": False,
            "provenance_verified": False,
            "what_it_is": (
                "the historically published D/A observation-token ratio (default 0.8855) "
                "computed with the len//4 proxy on the published cohort; its cohort and "
                "provenance have NOT been verified against the stored runs"
            ),
            "must_not_be_combined_with": (
                "the current ratio_check numbers in this artifact "
                "(totals.real_ratio_D_over_A, totals.proxy_ratio_D_over_A, per_unit): "
                "they come from a different, replayable cohort, so averaging, dividing "
                "or differencing the two would be comparing unrelated populations"
            ),
            "interpretation": (
                "read it as a historical reference point only; it is not evidence about "
                "the current code, and it is not a baseline for the recomputed ratio"
            ),
        },
        "unit": "(task_id, source_run); cells summed within a unit",
        "sample_scope": {
            "pairing_unit": "(task_id, source_run)",
            "pairs_only_within_the_same_bucket": True,
            "only_cells_replayable_from_the_stored_run": True,
            "n_paired_units": len(paired),
            "n_paired_tasks": len({key[0] for key in paired}),
            "paired_task_ids": sorted({key[0] for key in paired}),
            "paired_source_runs": sorted({key[1] for key in paired}),
            "n_observations_paired": sum(
                len(value[c]) for value in paired.values() for c in CONDITIONS
            ),
            "n_observations_replayable": len(live),
            "cells_replayable_but_unpaired": len(live) - sum(
                len(value[c]) for value in paired.values() for c in CONDITIONS
            ),
            "is_the_whole_benchmark_round": False,
            "covers_every_task_in_the_task_set": False,
            "note": (
                "the recomputed ratio uses only cells that replayed from the stored run "
                "AND exist for BOTH conditions inside the same (task_id, source_run) "
                f"bucket: {sum(len(value[c]) for value in paired.values() for c in CONDITIONS)}"
                f" observations in {len(paired)} buckets covering "
                f"{len({key[0] for key in paired})} tasks — a subset of the replayable "
                f"cells ({len(live)}) and NOT the whole benchmark round (the replay "
                "covers only the units selected by --max-units). An unpaired bucket is "
                "never merged into another bucket."
            ),
        },
        "paired_units": len(paired),
        "cells_used": {
            "raw_shell": sum(1 for s in live if s["condition"] == "raw_shell"),
            "verseshell_aci": sum(1 for s in live if s["condition"] == "verseshell_aci"),
        },
        "per_unit": per_unit,
        "totals": {
            "real_tokens_A": tot["raw_shell"]["real"],
            "real_tokens_D": tot["verseshell_aci"]["real"],
            "proxy_tokens_A": tot["raw_shell"]["proxy"],
            "proxy_tokens_D": tot["verseshell_aci"]["proxy"],
            "real_ratio_D_over_A": real_ratio,
            "proxy_ratio_D_over_A": proxy_ratio,
        },
        "proxy_ratio_error": {"absolute": absolute_error, "relative": relative_error},
        "direction_agreement": {
            "unit": "(task_id, source_run)",
            "pairs_only_within_the_same_bucket": True,
            "units": len(per_unit),
            "units_with_D_below_A_real": sum(
                1 for u in per_unit if u["real_ratio_D_over_A"] is not None
                and u["real_ratio_D_over_A"] < 1
            ),
            "units_with_D_below_A_proxy": sum(
                1 for u in per_unit if u["proxy_ratio_D_over_A"] is not None
                and u["proxy_ratio_D_over_A"] < 1
            ),
            "units_where_sign_agrees": units_agree,
            "units_where_direction_disagrees": len(per_unit) - units_agree,
            "disagreeing_units": [
                {
                    "task_id": u["task_id"], "source_run": u["source_run"],
                    "real_ratio_D_over_A": u["real_ratio_D_over_A"],
                    "proxy_ratio_D_over_A": u["proxy_ratio_D_over_A"],
                    "real_tokens_A": u["real_tokens_A"], "real_tokens_D": u["real_tokens_D"],
                    "proxy_tokens_A": u["proxy_tokens_A"], "proxy_tokens_D": u["proxy_tokens_D"],
                }
                for u in per_unit if not u["direction_agrees"]
            ],
            "note": (
                "direction is which side of 1.0 the D/A ratio falls on INSIDE one "
                "(task_id, source_run) bucket; buckets are never mixed, so a "
                "disagreement here is a real per-bucket reversal, while the aggregate "
                "can also be moved by cell weighting (see sign_flip_robustness)"
            ),
        },
        "sign_flip_robustness": {
            "aggregate_sign_flip": sign_flip,
            "units": len(per_unit),
            "units_where_sign_agrees": units_agree,
            "aggregate_flip_but_units_mostly_agree": aggregate_flip_but_units_agree,
            "note": (
                "the aggregate D/A ratio weights cells by their token count, so a few "
                "large observations can flip it while most individual units keep the "
                "same side of 1.0; this field makes that visible instead of leaving the "
                "aggregate to speak alone"
            ),
        },
        "materiality_threshold_relative": 0.10,
        "materially_changes_conclusion": material,
        "conclusion": conclusion,
        "excluded_from_ratio": "samples with condition == 'synthetic' (fallback corpus)",
    }


def build_verdict(agg: dict[str, Any], cross: dict[str, Any], tokenizer: dict[str, Any],
                  anchor: dict[str, Any]) -> dict[str, Any]:
    """State, in words and with numbers, the answers this tool exists to give."""
    ov = agg["overall"]
    ub = agg["upper_bound_check"]
    inv = agg.get("tokenizer_invariants") or {}
    byte_detail = inv.get("byte_invariant_detail") or {}
    chars_observed = inv.get("chars_bound_observed") or {}
    named_counterexample = chars_observed.get("named_panel_counterexample") or {}
    mean_ratio = ov["real_over_proxy_ratio"]["mean"]
    median_ratio = ov["real_over_proxy_ratio"]["median"]
    mean_rel = ov["relative_error_proxy_vs_real"]["mean"]
    approx = tokenizer["is_approximation"]

    if mean_ratio is None:
        direction = "undetermined: no sample could be scored"
    elif mean_ratio > 1.0:
        direction = (
            f"the proxy UNDER-counts real tokens on this sample: mean real/proxy = "
            f"{mean_ratio} (> 1), i.e. the proxy charges about "
            f"{abs(mean_rel):.1%} fewer tokens than the tokenizer produces"
        )
    elif mean_ratio < 1.0:
        direction = (
            f"the proxy OVER-counts real tokens on this sample: mean real/proxy = "
            f"{mean_ratio} (< 1), i.e. the proxy charges about "
            f"{abs(mean_rel):.1%} more tokens than the tokenizer produces"
        )
    else:
        direction = "no systematic direction: mean real/proxy = 1.0"

    magnitude = (
        f"mean real/proxy = {mean_ratio}, median = {median_ratio}, "
        f"mean relative error (proxy-real)/real = {mean_rel}; "
        f"proxy over-counts {ov['proxy_overcounts_samples']} and under-counts "
        f"{ov['proxy_undercounts_samples']} of {ov['n_scored']} scored samples; "
        f"the spread is shape-dependent, not a single constant: "
        + "; ".join(
            f"{cls}: mean real/proxy={summary['real_over_proxy_ratio']['mean']} "
            f"(n={summary['n_scored']})"
            for cls, summary in sorted(agg["by_char_class"].items())
        )
    )

    if ub["at_least_4x_chars_per_token_holds"]:
        upper = (
            f"YES on this sample: real <= proxy for all {ub['n_samples']} samples, so "
            f"len(text)//4 does not under-charge on these {ub['n_samples']} texts. That "
            f"is a statement about THIS sample, not a guarantee: the proxy is still not "
            f"a bound in either direction, and it over-counts other shapes on the same "
            f"corpus (see `answer`)."
        )
    else:
        upper = (
            f"NO: real > proxy on {ub['violations']}/{ub['n_samples']} samples "
            f"({ub['violation_rate']:.1%}), i.e. len(text)//4 UNDER-counts real tokens on "
            f"those shapes ({ub['violations_by_char_class']}). The proxy is NOT a bound in "
            f"either direction: in this same sample it under-counts "
            f"{ov['proxy_undercounts_samples']} and over-counts "
            f"{ov['proxy_overcounts_samples']} of {ov['n_scored']} scored texts, so no "
            f"single correction factor converts it into a real-token count. Worst: "
            f"{ub['worst_violation']['char_class']} text of "
            f"{ub['worst_violation']['chars']} chars scored "
            f"{ub['worst_violation']['real_tokens']} real tokens against "
            f"{ub['worst_violation']['proxy_tokens']} proxy tokens "
            f"(-{ub['worst_violation']['proxy_undercount_relative']:.0%})."
        )

    no_single_factor = (
        f"no single correction factor exists: across {ov['n_scored']} scored texts the "
        f"proxy under-counts {ov['proxy_undercounts_samples']}, over-counts "
        f"{ov['proxy_overcounts_samples']} and exactly matches "
        f"{ov['exact_match_samples']}, and the mean real/proxy ratio is shape-dependent ("
        + "; ".join(
            f"{cls}={summary['real_over_proxy_ratio']['mean']} (n={summary['n_scored']})"
            for cls, summary in sorted(agg["by_char_class"].items())
        )
        + "). A per-shape correction — or a real tokenizer — is required; one constant "
        "multiplier is not defensible."
    )

    byte_invariant = (
        f"real_tokens <= utf8_bytes holds for {byte_detail.get('n_checked')} checked "
        f"texts (samples + shape panel) = "
        f"{inv.get('real_tokens_never_exceed_utf8_bytes')}, with "
        f"{byte_detail.get('n_violations')} violation(s). This is the applicable "
        f"byte-level BPE invariant: every token covers at least one UTF-8 byte."
    )

    chars_bound = (
        f"The previously published chars bound (real_tokens <= chars) is NOT an "
        f"invariant and is retracted: it fails on "
        f"{chars_observed.get('violations')} of {chars_observed.get('n_checked')} checked "
        f"texts"
        + (
            f", counterexample `{named_counterexample.get('name')}` "
            f"({named_counterexample.get('chars')} chars vs "
            f"{named_counterexample.get('real_tokens')} real tokens, "
            f"{named_counterexample.get('utf8_bytes')} UTF-8 bytes)"
            if named_counterexample else ""
        )
        + ". It is kept, explicitly labelled, as tokenizer_invariants.chars_bound_observed "
          "(chars_bound_is_not_an_invariant: true)."
    )

    hazard = (
        "The endpoint's usage.prompt_tokens is unusable as written: it is cached per "
        "input content (the same text returns the same value even when that value is "
        "nonsense), and roughly 10-60% of even cache-missing requests report a value "
        "inflated by a constant ~+170 tokens. This tool neutralises both by giving "
        "every probe request unique content (a fresh 12-hex nonce), taking K="
        f"{cross['draws_per_text']} draws and keeping the minimum (the contamination is "
        "one-sided, so the minimum is the consistent estimator; a median is not), "
        "requiring at least two mutually agreeing uncontaminated draws before a text is "
        "trusted, reporting an interval rather than a point, and cross-checking every "
        "endpoint number against the independent real tokenizer. "
        f"{cross['n_stable']}/{cross['n_texts']} cross-checked texts were stable."
    )

    answer = (
        ("APPROXIMATE ONLY: no real tokenizer was available, so this answer rests on "
         "the byte-class approximation. " if approx else
         f"Measured against {tokenizer['primary']}. ")
        + f"{direction}. {upper} {no_single_factor}"
    )

    return {
        "question": (
            "is estimate_tokens(text) = max(1, len(text)//4) a defensible proxy, and in "
            "which direction and by how much does it err?"
        ),
        "answer": answer,
        "a_error_direction": direction,
        "b_error_magnitude": magnitude,
        "c_upper_bound": upper,
        "d_cache_hazard_and_neutralisation": hazard,
        "e_no_single_correction_factor": no_single_factor,
        "f_tokenizer_byte_invariant": byte_invariant,
        "g_chars_bound_retracted": chars_bound,
        "h_caliber": (
            "a_error_direction/b_error_magnitude/c_upper_bound/e_no_single_correction_factor "
            "are about `proxy_tokens` (an OBSERVATION PROXY); "
            "f_tokenizer_byte_invariant/g_chars_bound_retracted are about `real_tokens` "
            "(a REAL BPE REPLAY on the full text); "
            "d_cache_hazard_and_neutralisation is about `endpoint_tokens` (ENDPOINT "
            "USAGE). See the top-level `caliber_labels` block; none of these numbers is "
            "a cost."
        ),
        "anchor_check": {
            "statement": (
                f"a {anchor['chars']}-character English paragraph costs "
                f"{anchor['proxy_tokens']} proxy tokens and {anchor['real_tokens']} real "
                f"tokens (expected {anchor['expected_real_range']}); within range: "
                f"{anchor['within_expected_range']}"
            ),
            "within_expected_range": anchor["within_expected_range"],
        },
        "endpoint_vs_offline": cross["conclusion"],
        "primary_is_approximation": approx,
    }


# ── Sample construction and FULL-text measurement ──
#
# Every published metric (chars, utf8_bytes, real_tokens, proxy_tokens) is a
# function of the FULL observation text. The artifact stores only `text` = the
# first `max_stored_text` characters as a display copy. `build_sample` keeps the
# full text in the private `_measured_text` key, `measure_sample` consumes it, and
# `measurement_consistency` re-derives the relationship from the stored hashes so a
# measurement taken on the truncated copy cannot pass unnoticed.

def build_sample(text: str | None, *, condition: str, op: str, task_id: str,
                 source_run: str, cell_index: int | None, max_stored_text: int,
                 recorded_proxy_tokens: int | None = None,
                 recorded_aci_ok: Any = None, replay_aci_ok: Any = None,
                 origin: str = "replay") -> dict[str, Any]:
    """Metadata for one sample, plus the full text to measure in `_measured_text`.

    `text is None` means the stored cell has no observation text. That is handled
    explicitly: every measured metric is None, `measurement_skip_reason` says why,
    and the sample is never scored as 0. Likewise a cell with no recorded usage
    gets `recorded_usage_skip_reason` instead of a fabricated 0.

    Callers must `pop("_measured_text")` (measure_sample does) before serialising.
    """
    sample_id = (
        f"{condition}:{task_id}:{source_run}:"
        f"{cell_index if cell_index is not None else op}"
    )
    if text is None:
        return {
            "id": sample_id,
            "origin": origin,
            "condition": condition,
            "task_id": task_id,
            "source_run": source_run,
            "cell_index": cell_index,
            "op": op,
            "chars": None,
            "utf8_bytes": None,
            "bytes_per_char": None,
            "lines": None,
            "char_class": "no_text",
            "cjk_chars": None,
            "non_ascii_chars": None,
            "size_bucket": "unknown",
            "long_multiline": False,
            "proxy_tokens": None,
            "recorded_proxy_tokens": recorded_proxy_tokens,
            "recorded_usage_skip_reason": (
                None if recorded_proxy_tokens is not None else "no_recorded_usage"
            ),
            "recorded_aci_ok": recorded_aci_ok,
            "replay_aci_ok": replay_aci_ok,
            "proxy_matches_recorded": None,
            "text_sha256": None,
            "text_preview": None,
            "artifact_text_chars": None,
            "text_truncated_in_artifact": False,
            "text": None,
            "measurement_target": "none:no_stored_text",
            "measured_text_is_full_text": False,
            "measurement_skip_reason": "no_stored_text",
            "measurement_caliber": "unmeasured",
            "real_tokens": None,
            "real_tokens_primary": None,
            "ratio_real_over_proxy": None,
            "relative_error_proxy_vs_real": None,
        }

    meta = classify_text(text)
    encoded = text.encode("utf-8")
    stored = text[:max_stored_text]
    return {
        "id": sample_id,
        "origin": origin,
        "condition": condition,
        "task_id": task_id,
        "source_run": source_run,
        "cell_index": cell_index,
        "op": op,
        "chars": meta["chars"],
        "utf8_bytes": len(encoded),
        "bytes_per_char": round(len(encoded) / meta["chars"], 4) if meta["chars"] else None,
        "lines": meta["lines"],
        "char_class": meta["char_class"],
        "cjk_chars": meta["cjk_chars"],
        "non_ascii_chars": meta["non_ascii_chars"],
        "size_bucket": meta["size_bucket"],
        "long_multiline": meta["long_multiline"],
        # The proxy is measured on the FULL text, exactly like every other metric.
        "proxy_tokens": proxy_estimate(text),
        "recorded_proxy_tokens": recorded_proxy_tokens,
        "recorded_usage_skip_reason": (
            None if recorded_proxy_tokens is not None else "no_recorded_usage"
        ),
        "recorded_aci_ok": recorded_aci_ok,
        "replay_aci_ok": replay_aci_ok,
        "proxy_matches_recorded": (
            None if recorded_proxy_tokens is None
            else proxy_estimate(text) == int(recorded_proxy_tokens)
        ),
        "text_sha256": hashlib.sha256(encoded).hexdigest(),
        "text_preview": text[:300],
        # `text` is the DISPLAY copy only; it is never the measurement input.
        "artifact_text_chars": len(stored),
        "text_truncated_in_artifact": len(text) > max_stored_text,
        "text": stored,
        "measurement_target": "full_text",
        "measured_text_is_full_text": None,  # set by measure_sample
        "measurement_skip_reason": None,
        "measurement_caliber": "pending",
        "real_tokens": None,
        "real_tokens_primary": None,
        "ratio_real_over_proxy": None,
        "relative_error_proxy_vs_real": None,
        "_measured_text": text,
    }


def measure_sample(sample: dict[str, Any], counter: Callable[[str], int], *,
                   primary: str | None) -> str | None:
    """Measure ONE sample on its FULL text, in place; return the full text used.

    `real_tokens` and the derived ratios are computed from the full text kept in
    `_measured_text`, never from `sample["text"]` (the truncated artifact copy).
    A sample with no full text is left explicitly unmeasured: `real_tokens` stays
    None with a skip reason, never 0.
    """
    full_text = sample.pop("_measured_text", None)
    if full_text is None:
        sample["real_tokens"] = None
        sample["real_tokens_primary"] = None
        sample["ratio_real_over_proxy"] = None
        sample["relative_error_proxy_vs_real"] = None
        sample.setdefault("measurement_skip_reason", "no_measured_text")
        sample["measured_text_is_full_text"] = False
        sample["measurement_caliber"] = "unmeasured"
        return None

    encoded = full_text.encode("utf-8")
    measured_chars = len(full_text)
    measured_bytes = len(encoded)
    measured_sha = hashlib.sha256(encoded).hexdigest()
    sample["measured_chars"] = measured_chars
    sample["measured_utf8_bytes"] = measured_bytes
    sample["measured_text_sha256"] = measured_sha
    # The measurement describes the full text iff it agrees with the full-text
    # metadata recorded by build_sample; this is what the D1 regression checks.
    sample["measured_text_is_full_text"] = (
        measured_chars == sample.get("chars")
        and measured_bytes == sample.get("utf8_bytes")
        and measured_sha == sample.get("text_sha256")
        and sample.get("measurement_target") == "full_text"
    )
    sample["measurement_caliber"] = "real_bpe_replay"
    sample["measurement_skip_reason"] = None
    sample["real_tokens"] = counter(full_text)
    sample["real_tokens_primary"] = primary
    sample["ratio_real_over_proxy"] = (
        round(sample["real_tokens"] / sample["proxy_tokens"], 4)
        if sample["proxy_tokens"] else None
    )
    sample["relative_error_proxy_vs_real"] = (
        round((sample["proxy_tokens"] - sample["real_tokens"]) / sample["real_tokens"], 4)
        if sample["real_tokens"] else None
    )
    return full_text


def measurement_consistency(sample: dict[str, Any]) -> dict[str, Any]:
    """Cross-check a sample's measured metrics against its full-text metadata.

    This is the D1 detector: if `chars`/`utf8_bytes`/`text_sha256` describe the
    full text while `real_tokens` (or the measured_* mirrors) describe the
    truncated copy, `metrics_measured_on_the_full_text` and the truncation checks
    go False. A sample that was never measured returns ok=None with its explicit
    skip reason, so "unmeasured" is never confused with "measured as 0".
    """
    if sample.get("measurement_skip_reason"):
        return {
            "ok": None,
            "checked": False,
            "reason": sample["measurement_skip_reason"],
            "note": "the sample was not measured; None is explicit, never 0",
        }
    chars = sample.get("chars")
    utf8_bytes = sample.get("utf8_bytes")
    artifact_chars = sample.get("artifact_text_chars")
    truncated = sample.get("text_truncated_in_artifact")
    checks = {
        "metrics_measured_on_the_full_text": (
            sample.get("measured_chars") == chars
            and sample.get("measured_utf8_bytes") == utf8_bytes
            and sample.get("measured_text_sha256") == sample.get("text_sha256")
            and sample.get("measured_text_is_full_text") is True
        ),
        "truncation_flag_matches_chars_vs_stored_length": (
            bool(truncated)
            == (chars is not None and artifact_chars is not None and chars > artifact_chars)
        ),
        "utf8_bytes_describes_the_full_text": (
            utf8_bytes is None
            or (truncated is True and chars is not None and artifact_chars is not None
                and utf8_bytes > artifact_chars)
            or (not truncated and chars is not None and artifact_chars == chars)
        ),
        "proxy_tokens_matches_the_full_text_length": (
            sample.get("proxy_tokens")
            == (max(1, chars // 4) if chars is not None else None)
        ),
        "real_tokens_never_exceed_utf8_bytes": (
            sample.get("real_tokens") is None or utf8_bytes is None
            or sample["real_tokens"] <= utf8_bytes
        ),
    }
    return {"ok": all(checks.values()), "checked": True, "reason": None, "checks": checks}


# ── Main ──

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, default=ROOT / "eval/token_proxy_calibration.json")
    parser.add_argument("--results", type=Path, default=LIVE_RESULTS,
                        help="stored live trajectory artifact to replay")
    parser.add_argument("--cap", type=int, default=30,
                        help="max observations per condition (20-40 keeps cost bounded)")
    parser.add_argument("--max-units", type=int, default=30,
                        help="max (task_id, source_run) units to replay")
    parser.add_argument("--no-replay", action="store_true",
                        help="skip trajectory replay and use only the synthetic fallback corpus")
    parser.add_argument("--min-replay-samples", type=int, default=5,
                        help="below this many usable replayed cells, add the fallback corpus")
    parser.add_argument("--max-stored-text", type=int, default=4000,
                        help="characters of each sample text kept in the artifact")
    parser.add_argument("--published-proxy-ratio", type=float, default=0.8855,
                        help="the published D/A observation-token ratio for comparison")
    parser.add_argument("--endpoint-draws", type=int, default=DEFAULT_ENDPOINT_DRAWS,
                        help="unique-nonce endpoint draws per cross-checked text")
    parser.add_argument("--endpoint-max", type=int, default=DEFAULT_ENDPOINT_MAX,
                        help="how many replayed samples to cross-check through the endpoint")
    parser.add_argument("--no-endpoint", action="store_true",
                        help="skip every endpoint call; the artifact is then tokenizer-only")
    parser.add_argument("--no-download", action="store_true",
                        help="never fetch the cl100k_base BPE file (use only local caches)")
    args = parser.parse_args(argv)

    if args.cap < 1 or args.max_units < 1 or args.endpoint_draws < 1:
        print("--cap, --max-units and --endpoint-draws must be >= 1", file=sys.stderr)
        return 2

    # Accept a relative --out/--results (the documented invocation does) without
    # ever resolving it against the wrong directory.
    if not args.out.is_absolute():
        args.out = Path.cwd() / args.out
    if not args.results.is_absolute():
        args.results = ROOT / args.results

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001 - console encoding is cosmetic
        pass

    # ── 0. Resolve a real tokenizer (tiers 1-3) or the labelled approximation ──
    tokenizer, tokenizer_info = resolve_tokenizer(allow_download=not args.no_download)
    print(f"tokenizer: {tokenizer_info['primary']} (tier {tokenizer_info['tier']}) — "
          f"{tokenizer_info['how_resolved']}")
    for note in tokenizer_info["notes"]:
        print(f"  note: {note}")
    for attempt in tokenizer_info["attempts"]:
        if not attempt.get("ok"):
            print(f"  tier {attempt['tier']} failed: {attempt['what']}: {attempt['error'][:140]}")

    env = load_env()
    endpoint = None
    endpoint_errors: list[dict] = []
    if HARNESS_IMPORT_ERROR is not None:
        print(f"harness: live_agent_loop.py could not be imported "
              f"({HARNESS_IMPORT_ERROR}); replay and endpoint probes are disabled, "
              f"the offline tokenizer measurement continues")
    if args.no_endpoint or H is None:
        reason = "--no-endpoint" if args.no_endpoint else "harness_import_failed"
        print(f"endpoint: disabled ({reason})")
        endpoint_errors.append({
            "condition": None, "task_id": None, "source_run": None, "cell_index": None,
            "op": None, "error": f"endpoint_disabled:{reason}",
        })
    else:
        missing = [k for k in ("ACI_BENCH_BASE_URL", "ACI_BENCH_API_KEY", "ACI_BENCH_MODEL")
                   if k not in env]
        if missing:
            print(f"missing keys in {ENV_LOCAL.name}: {', '.join(missing)}; "
                  f"continuing with the offline tokenizer only", file=sys.stderr)
            endpoint_errors.append({
                "condition": None, "task_id": None, "source_run": None, "cell_index": None,
                "op": None, "error": "missing_env_keys: " + ",".join(missing),
            })
        else:
            endpoint = Endpoint(model=env["ACI_BENCH_MODEL"], api_key=env["ACI_BENCH_API_KEY"],
                                base_url=env["ACI_BENCH_BASE_URL"], draws=args.endpoint_draws)
            print(f"endpoint: model={endpoint.model} base={endpoint.base_url} "
                  f"draws_per_text={endpoint.draws}")

    skips: list[dict] = []

    # ── 1. Replay the stored live trajectories ──
    replayed: dict[str, dict[tuple[str, str], list[dict]]] = {c: {} for c in CONDITIONS}
    doc: dict[str, Any] = {}
    selected_units: list[tuple[str, str]] = []

    if args.no_replay:
        skips.append({"condition": None, "task_id": None, "source_run": None,
                      "cell_index": None, "op": None,
                      "reason": "replay_disabled_by_flag", "detail": "--no-replay"})
        print("replay: skipped (--no-replay); using synthetic fallback corpus only")
    elif H is None:
        skips.append({"condition": None, "task_id": None, "source_run": None,
                      "cell_index": None, "op": None,
                      "reason": "harness_import_failed",
                      "detail": str(HARNESS_IMPORT_ERROR)[:300]})
        print("replay: skipped (the harness could not be imported); using the "
              "synthetic fallback corpus only")
    elif not args.results.exists():
        skips.append({"condition": None, "task_id": None, "source_run": None,
                      "cell_index": None, "op": None,
                      "reason": "results_artifact_missing", "detail": str(args.results)})
        print(f"replay: {args.results} not found; using synthetic fallback corpus only")
    else:
        doc, all_units = load_units(args.results)
        # Ordered by (source_run, task_id) so a bounded number of units still
        # covers every task: the first N units are one complete benchmark round.
        ordered = sorted(all_units, key=lambda k: (k[1], k[0]))
        selected_units = ordered[:args.max_units]
        skipped_units = ordered[args.max_units:]
        print(f"replay: {len(selected_units)}/{len(all_units)} units from "
              f"{_display(args.results)} "
              f"(source_run={sorted({u[1] for u in selected_units})})")
        if skipped_units:
            skips.append({
                "condition": None, "task_id": None, "source_run": None,
                "cell_index": None, "op": None, "reason": "unit_beyond_max_units",
                "detail": f"{len(skipped_units)} units not replayed (--max-units={args.max_units})",
            })
        for key in selected_units:
            by_condition = all_units[key]
            for condition in CONDITIONS:
                row = by_condition.get(condition)
                if row is None:
                    skips.append({
                        "condition": condition, "task_id": key[0], "source_run": key[1],
                        "cell_index": None, "op": None, "reason": "unit_missing_condition",
                        "detail": "the other condition has no stored row for this unit",
                    })
                    continue
                replayed[condition][key] = replay_row(row, skips)

    # ── 2. Deterministic, capped selection ──
    selected: list[dict] = []
    cap_not_selected: dict[str, int] = {}
    for condition in CONDITIONS:
        chosen = round_robin_select(replayed[condition], args.cap)
        total = sum(len(v) for v in replayed[condition].values())
        cap_not_selected[condition] = max(0, total - len(chosen))
        selected.extend(chosen)
        print(f"  {condition:<15} replayed={total:4d} selected={len(chosen):4d} "
              f"units={len(replayed[condition])}")

    replayed_counts = {c: sum(1 for s in selected if s["condition"] == c) for c in CONDITIONS}
    used_fallback = args.no_replay or any(
        replayed_counts[c] < args.min_replay_samples for c in CONDITIONS
    )

    # ── 3. Build the sample list (metadata only; measurement comes next) ──
    samples: list[dict] = []

    def add_sample(text: str | None, *, condition: str, op: str, task_id: str,
                   source_run: str, cell_index: int | None,
                   recorded_proxy_tokens: int | None = None,
                   recorded_aci_ok: Any = None, replay_aci_ok: Any = None,
                   origin: str = "replay") -> None:
        sample = build_sample(
            text, condition=condition, op=op, task_id=task_id,
            source_run=source_run, cell_index=cell_index,
            max_stored_text=args.max_stored_text,
            recorded_proxy_tokens=recorded_proxy_tokens,
            recorded_aci_ok=recorded_aci_ok, replay_aci_ok=replay_aci_ok,
            origin=origin,
        )
        if text is None:
            # Explicit, counted, and never scored: a cell with no stored text is a
            # skip with a reason, not a 0-token observation.
            skips.append({
                "condition": condition, "task_id": task_id, "source_run": source_run,
                "cell_index": cell_index, "op": op, "reason": "no_stored_text",
                "detail": f"{sample['id']} has no stored observation text",
            })
        samples.append(sample)

    for cell in sorted(selected, key=lambda c: (c["condition"], c["task_id"],
                                                c["source_run"], c["cell_index"])):
        add_sample(
            cell["text"], condition=cell["condition"], op=cell["op"],
            task_id=cell["task_id"], source_run=cell["source_run"],
            cell_index=cell["cell_index"],
            recorded_proxy_tokens=cell["recorded_proxy_tokens"],
            recorded_aci_ok=cell["recorded_aci_ok"],
            replay_aci_ok=cell["replay_aci_ok"],
            origin="replay",
        )

    if used_fallback:
        reason = (
            "--no-replay requested" if args.no_replay
            else f"replayed cells below --min-replay-samples={args.min_replay_samples} "
                 f"(A={replayed_counts['raw_shell']}, D={replayed_counts['verseshell_aci']})"
        )
        print(f"fallback: adding synthetic corpus ({reason})")
        skips.append({"condition": None, "task_id": None, "source_run": None,
                      "cell_index": None, "op": None,
                      "reason": "synthetic_fallback_used", "detail": reason})
        for name, text in FALLBACK_TEXTS:
            add_sample(text, condition="synthetic", op=name, task_id=name,
                       source_run="builtin", cell_index=None, origin="synthetic_fallback")

    ladder = [
        {
            "name": f"prose_{n}_chars",
            "chars": n,
            "utf8_bytes": len(
                (LADDER_FILLER * (n // len(LADDER_FILLER) + 1))[:n].encode("utf-8")
            ),
            "text": (LADDER_FILLER * (n // len(LADDER_FILLER) + 1))[:n],
        }
        for n in LADDER_CHARS
    ]
    panel = [
        # The panel text IS the measured text (no truncation), so chars/utf8_bytes
        # and real_tokens all describe this same string.
        {"name": name, "chars": len(text), "utf8_bytes": len(text.encode("utf-8")),
         "text": text}
        for name, text in SHAPE_PANEL
    ]
    anchor_text = ANCHOR_TEXT

    # ── 4. Primary measurement (real tokenizer) for EVERY sample, on the FULL text ──
    #
    # `sample["text"]` is only the truncated display copy; measure_sample consumes
    # the full text kept in `_measured_text`. sample_full_texts[i] is the text that
    # was actually measured, reused for the endpoint cross-check so the secondary
    # measurement sees the same text as the primary one.
    sample_full_texts: list[str | None] = [
        measure_sample(sample, tokenizer, primary=tokenizer_info["primary"])
        for sample in samples
    ]
    for item in ladder:
        item["proxy_tokens"] = proxy_estimate(item["text"])
        item["real_tokens"] = tokenizer(item["text"])
    for item in panel:
        item["proxy_tokens"] = proxy_estimate(item["text"])
        item["real_tokens"] = tokenizer(item["text"])
        item["char_class"] = classify_text(item["text"])["char_class"]
    anchor_proxy = proxy_estimate(anchor_text)
    anchor_real = tokenizer(anchor_text)

    # ── 5. Secondary measurement (endpoint, unique-nonce protocol) ──
    endpoint_texts: list[dict[str, Any]] = []
    endpoint_plan: dict[str, Any] = {
        "enabled": endpoint is not None,
        "draws_per_text": args.endpoint_draws,
        "endpoint_max_replay_samples": args.endpoint_max,
        "texts_measured": 0,
        "endpoint_calls": 0,
        "baseline_draws": [],
        "baseline_raw_min": None,
        "baseline_median_of_fresh": None,
        "baseline_fresh_spread": None,
        "baseline_contaminated_draws": None,
        "contamination_offset_tokens_observed": None,
        "hazard_demo": None,
        "failures": [],
    }

    if endpoint is not None:
        picked = spread_selection(len(samples), args.endpoint_max)
        for index in picked:
            # Cross-check the SAME text the primary measurement used (the full
            # text), so a truncated sample cannot look like an endpoint
            # disagreement. An unmeasured sample has no text to cross-check.
            text = sample_full_texts[index]
            if text is None:
                continue
            endpoint_texts.append({"kind": "sample", "index": index, "text": text})
        for item in panel:
            endpoint_texts.append({"kind": "panel", "name": item["name"], "text": item["text"]})
        for item in ladder:
            endpoint_texts.append({"kind": "ladder", "name": item["name"], "text": item["text"]})
        endpoint_texts.append({"kind": "anchor", "name": ANCHOR_NAME, "text": anchor_text})

        print(f"endpoint: measuring {len(endpoint_texts)} texts "
              f"({len(picked)} replay samples + {len(panel)} panel + {len(ladder)} ladder "
              f"+ anchor) with {args.endpoint_draws} unique-nonce draws each; "
              f"{BASELINE_SEED_DRAWS} seed baseline draws first")
        for _ in range(BASELINE_SEED_DRAWS):
            try:
                endpoint.baseline_draw()
            except Exception as error:  # noqa: BLE001
                endpoint_errors.append({
                    "condition": None, "task_id": None, "source_run": None,
                    "cell_index": None, "op": "baseline_seed",
                    "error": f"{type(error).__name__}: {error}"[:300],
                })

        started = time.perf_counter()
        for position, entry in enumerate(endpoint_texts, start=1):
            entry["collected"] = endpoint.collect(entry["text"])
            if position % 5 == 0 or position == len(endpoint_texts):
                elapsed = time.perf_counter() - started
                print(f"    {position}/{len(endpoint_texts)} texts, "
                      f"{endpoint.calls} calls, {elapsed:.0f}s")

        # The hazard demo is measured last so it cannot perturb the sample draws.
        endpoint_plan["hazard_demo"] = endpoint_hazard_demo(endpoint, '{"ok": true}')

        base_fresh, base_tol = _fresh_cluster(endpoint.baseline_draws)
        if endpoint.baseline_draws:
            low = min(endpoint.baseline_draws)
            endpoint_plan["baseline_raw_min"] = low
            endpoint_plan["baseline_median_of_fresh"] = (
                statistics.median(base_fresh) if base_fresh else None
            )
            endpoint_plan["baseline_fresh_spread"] = (
                (max(base_fresh) - min(base_fresh)) if len(base_fresh) > 1 else 0
            )
            endpoint_plan["baseline_contaminated_draws"] = (
                len(endpoint.baseline_draws) - len(base_fresh)
            )
            loaded = [v for v in endpoint.baseline_draws if v - low > base_tol]
            if loaded:
                endpoint_plan["contamination_offset_tokens_observed"] = (
                    min(loaded) - low
                )
        endpoint_plan["baseline_draws"] = endpoint.baseline_draws
        endpoint_plan["endpoint_calls"] = endpoint.calls
        endpoint_plan["texts_measured"] = len(endpoint_texts)
        endpoint_plan["unique_contents"] = len(endpoint.contents)
        endpoint_plan["failures"] = endpoint.failures[:10]
        endpoint_plan["nonce_shape"] = f"[<{NONCE_HEX_CHARS} hex chars>] "

        for entry in endpoint_texts:
            reduced = reduce_endpoint(entry["collected"], endpoint.baseline_draws)
            entry.update(reduced)
            entry.pop("collected", None)

    def attach(sample: dict, entry: dict[str, Any] | None) -> None:
        if entry is None:
            sample["endpoint_measured"] = False
            sample["endpoint_tokens"] = None
            sample["endpoint_interval"] = None
            sample["endpoint_stable"] = None
            sample["endpoint_unstable_reason"] = "not selected for endpoint cross-check"
            sample["endpoint_within_tolerance_of_primary"] = None
            sample["endpoint_over_primary_ratio"] = None
            return
        sample["endpoint_measured"] = bool(entry.get("endpoint_measured"))
        sample["endpoint_tokens"] = entry.get("endpoint_tokens")
        sample["endpoint_tokens_median_estimator"] = entry.get("endpoint_tokens_median_estimator")
        sample["endpoint_draws"] = entry.get("draws")
        sample["endpoint_draw_min"] = entry.get("draw_min")
        sample["endpoint_draw_max"] = entry.get("draw_max")
        sample["endpoint_contaminated_draws"] = entry.get("contaminated_draws")
        sample["endpoint_fresh_draws"] = entry.get("fresh_draws")
        sample["endpoint_noise_tokens"] = entry.get("endpoint_noise_tokens")
        sample["endpoint_spread_tokens"] = entry.get("endpoint_spread_tokens")
        sample["endpoint_interval"] = entry.get("endpoint_interval")
        sample["endpoint_stable"] = entry.get("stable")
        sample["endpoint_unstable_reason"] = entry.get("unstable_reason")
        sample["endpoint_errors"] = entry.get("errors")
        estimate = entry.get("endpoint_tokens")
        primary = sample.get("real_tokens")
        if estimate is None or primary is None:
            sample["endpoint_within_tolerance_of_primary"] = None
            sample["endpoint_over_primary_ratio"] = None
            return
        tolerance = max(3, int(round(0.10 * primary)))
        sample["endpoint_tolerance_tokens"] = tolerance
        sample["endpoint_minus_primary_tokens"] = estimate - primary
        sample["endpoint_within_tolerance_of_primary"] = abs(estimate - primary) <= tolerance
        sample["endpoint_over_primary_ratio"] = (
            round(estimate / primary, 4) if primary else None
        )

    endpoint_by_sample = {e["index"]: e for e in endpoint_texts if e["kind"] == "sample"}
    for index, sample in enumerate(samples):
        attach(sample, endpoint_by_sample.get(index))
    panel_by_name = {e["name"]: e for e in endpoint_texts if e["kind"] == "panel"}
    ladder_by_name = {e["name"]: e for e in endpoint_texts if e["kind"] == "ladder"}
    anchor_entry = next((e for e in endpoint_texts if e["kind"] == "anchor"), None)

    for item in panel:
        item["ratio_real_over_proxy"] = (
            round(item["real_tokens"] / item["proxy_tokens"], 4) if item["proxy_tokens"] else None
        )
        item["relative_error_proxy_vs_real"] = (
            round((item["proxy_tokens"] - item["real_tokens"]) / item["real_tokens"], 4)
            if item["real_tokens"] else None
        )
        entry = panel_by_name.get(item["name"])
        item["endpoint_tokens"] = entry.get("endpoint_tokens") if entry else None
        item["endpoint_interval"] = entry.get("endpoint_interval") if entry else None
        item["endpoint_stable"] = entry.get("stable") if entry else None
        item["endpoint_unstable_reason"] = entry.get("unstable_reason") if entry else None
        item["endpoint_draws"] = entry.get("draws") if entry else None

    for item in ladder:
        entry = ladder_by_name.get(item["name"])
        item["endpoint_tokens"] = entry.get("endpoint_tokens") if entry else None
        item["endpoint_stable"] = entry.get("stable") if entry else None
        item["ratio_real_over_proxy"] = (
            round(item["real_tokens"] / item["proxy_tokens"], 4) if item["proxy_tokens"] else None
        )

    ladder_primary = [item["real_tokens"] for item in ladder]
    ladder_endpoint = [item["endpoint_tokens"] for item in ladder]
    ladder_endpoint_complete = all(v is not None for v in ladder_endpoint)
    ladder_report = {
        "lengths_chars": [item["chars"] for item in ladder],
        "proxy_tokens": [item["proxy_tokens"] for item in ladder],
        "real_tokens_primary": ladder_primary,
        "endpoint_tokens": ladder_endpoint,
        "primary_strictly_increasing": all(
            ladder_primary[i + 1] > ladder_primary[i] for i in range(len(ladder_primary) - 1)
        ),
        "endpoint_strictly_increasing": (
            all(ladder_endpoint[i + 1] > ladder_endpoint[i]
                for i in range(len(ladder_endpoint) - 1))
            if ladder_endpoint_complete else None
        ),
        "note": (
            "token counts must grow with text length; the buggy artifact reported 175 "
            "tokens for a 12-character text and 178 for a 552-character one"
        ),
    }

    # ── 6. Aggregation, cross-check, verdict ──
    agg = aggregate(samples, panel=panel)
    ratio_check = build_ratio_check(samples, args.published_proxy_ratio)

    cross_texts = [s for s in samples if s.get("endpoint_measured")]
    cross_stable = [s for s in cross_texts if s.get("endpoint_stable")]
    cross_unstable = [s for s in cross_texts if not s.get("endpoint_stable")]
    comparable = [s for s in cross_stable
                  if s.get("endpoint_within_tolerance_of_primary") is not None]
    disagreements = [s for s in comparable if not s["endpoint_within_tolerance_of_primary"]]

    def disagreement_record(s: dict) -> dict[str, Any]:
        return {
            "id": s["id"], "char_class": s["char_class"], "chars": s["chars"],
            "primary_tokens": s["real_tokens"], "endpoint_tokens": s["endpoint_tokens"],
            "endpoint_interval": s["endpoint_interval"],
            "endpoint_minus_primary_tokens": s["endpoint_minus_primary_tokens"],
            "tolerance_tokens": s["endpoint_tolerance_tokens"],
            "endpoint_stable": s["endpoint_stable"],
            "endpoint_over_primary_ratio": s["endpoint_over_primary_ratio"],
            "text_preview": s["text_preview"][:120],
        }

    unstable_records = [{
        "id": s["id"], "chars": s["chars"], "char_class": s["char_class"],
        "draws": s["endpoint_draws"], "fresh_draws": s["endpoint_fresh_draws"],
        "contaminated_draws": s["endpoint_contaminated_draws"],
        "reason": s["endpoint_unstable_reason"],
    } for s in cross_unstable]

    panel_scored = [item for item in panel
                    if item.get("endpoint_tokens") is not None
                    and item.get("endpoint_stable") is True]
    panel_disagreements = []
    for item in panel_scored:
        tolerance = max(3, int(round(0.10 * item["real_tokens"])))
        if abs(item["endpoint_tokens"] - item["real_tokens"]) > tolerance:
            panel_disagreements.append({
                "name": item["name"], "char_class": item["char_class"],
                "chars": item["chars"], "primary_tokens": item["real_tokens"],
                "endpoint_tokens": item["endpoint_tokens"],
                "endpoint_interval": item["endpoint_interval"],
                "endpoint_over_primary_ratio": (
                    round(item["endpoint_tokens"] / item["real_tokens"], 4)
                    if item["real_tokens"] else None
                ),
            })

    ratio_stats = _stats([s["endpoint_over_primary_ratio"] for s in comparable
                          if s.get("endpoint_over_primary_ratio") is not None])
    abs_err = _stats([abs(s["endpoint_minus_primary_tokens"]) for s in comparable
                      if s.get("endpoint_minus_primary_tokens") is not None])

    if not endpoint_plan["enabled"]:
        cross_conclusion = "endpoint cross-check disabled (--no-endpoint)"
    elif not cross_texts:
        cross_conclusion = "endpoint cross-check produced no usable measurement"
    elif disagreements or panel_disagreements:
        parts = []
        if disagreements:
            parts.append(
                f"{len(disagreements)}/{len(comparable)} cross-checked replay samples"
            )
        if panel_disagreements:
            parts.append(
                f"{len(panel_disagreements)}/{len(panel_scored)} shape-panel texts ("
                + ", ".join(
                    f"{d['name']}: endpoint/primary={d['endpoint_over_primary_ratio']}"
                    for d in panel_disagreements
                ) + ")"
            )
        cross_conclusion = (
            f"DISAGREEMENT: the endpoint's tokenizer and {tokenizer_info['primary']} are "
            f"NOT interchangeable on " + " and ".join(parts) + "; they differ by more "
            f"than max(3 tokens, 10%). Both numbers are reported side by side and "
            f"neither is averaged away. On the replay samples that did agree, mean "
            f"endpoint/primary={ratio_stats['mean']} and median absolute difference="
            f"{abs_err['median']} tokens."
        )
    else:
        cross_conclusion = (
            f"AGREEMENT: all {len(comparable)} stable endpoint estimates are within "
            f"max(3 tokens, 10%) of {tokenizer_info['primary']}; mean endpoint/primary "
            f"= {ratio_stats['mean']}, median absolute difference = "
            f"{abs_err['median']} tokens."
        )

    cross = {
        "enabled": endpoint_plan["enabled"],
        "primary": tokenizer_info["primary"],
        "draws_per_text": args.endpoint_draws,
        "n_texts": len(cross_texts),
        "n_stable": len(cross_stable),
        "n_unstable": len(cross_unstable),
        "n_scored_against_primary": len(comparable),
        "n_within_tolerance": len(comparable) - len(disagreements),
        "n_disagree": len(disagreements),
        "n_panel_scored": len(panel_scored),
        "n_panel_disagree": len(panel_disagreements),
        "tolerance_rule": "max(3 tokens, 10% of primary tokens)",
        "endpoint_over_primary_ratio": ratio_stats,
        "absolute_difference_tokens": abs_err,
        "endpoint_interval_width_tokens": _stats([
            (s["endpoint_interval"][1] - s["endpoint_interval"][0])
            for s in comparable if s.get("endpoint_interval")
        ]),
        "unstable_samples": unstable_records,
        "disagreements": [disagreement_record(s) for s in disagreements],
        "panel_disagreements": panel_disagreements,
        "conclusion": cross_conclusion,
        "note": (
            "the endpoint estimate is a SECONDARY, cross-checked number. Where the two "
            "disagree beyond the stated tolerance the artifact reports the disagreement "
            "and does not pick a winner; the primary tokenizer is the one used for "
            "`real_tokens`, the ratios and the D/A check."
        ),
    }

    anchor = {
        "description": "fixed ~400-char English paragraph measured every run",
        "chars": len(anchor_text),
        "proxy_tokens": anchor_proxy,
        "real_tokens": anchor_real,
        "real_tokens_primary": tokenizer_info["primary"],
        "expected_real_range": list(ANCHOR_EXPECTED_REAL_RANGE),
        "within_expected_range": (
            ANCHOR_EXPECTED_REAL_RANGE[0] <= anchor_real <= ANCHOR_EXPECTED_REAL_RANGE[1]
        ),
        "endpoint_tokens": anchor_entry.get("endpoint_tokens") if anchor_entry else None,
        "endpoint_interval": anchor_entry.get("endpoint_interval") if anchor_entry else None,
        "endpoint_stable": anchor_entry.get("stable") if anchor_entry else None,
    }
    if anchor_entry and anchor_entry.get("endpoint_tokens") is not None:
        anchor["endpoint_within_expected_range"] = (
            ANCHOR_EXPECTED_REAL_RANGE[0]
            <= anchor_entry["endpoint_tokens"]
            <= ANCHOR_EXPECTED_REAL_RANGE[1]
        )

    approximation_error = None
    if not tokenizer_info["is_approximation"]:
        try:
            approximation_error = approximation_self_check(tokenizer)
        except Exception as error:  # noqa: BLE001
            approximation_error = {"available": False,
                                   "note": f"{type(error).__name__}: {error}"[:200]}

    verdict = build_verdict(agg, cross, tokenizer_info, anchor)

    # ── 7. Never write a JSON that looks like a measurement when nothing measured ──
    if not samples:
        print("FATAL: no sample could be assembled at all. Nothing written.", file=sys.stderr)
        return 1

    recorded_pairs = [s for s in samples if s["proxy_matches_recorded"] is not None]
    fidelity = {
        "cells_with_recorded_value": len(recorded_pairs),
        "proxy_matches_recorded": sum(1 for s in recorded_pairs if s["proxy_matches_recorded"]),
        "proxy_differs_from_recorded": sum(1 for s in recorded_pairs
                                           if not s["proxy_matches_recorded"]),
        "note": (
            "the replayed text reproduced the stored proxy token count exactly; where "
            "it differs, the replayed command produced different output than the "
            "stored run (build state, timings) and the replayed text is still a "
            "genuine observation"
        ),
    }

    integrity_checks = [measurement_consistency(s) for s in samples]
    integrity_inconsistent = [
        s["id"] for s, check in zip(samples, integrity_checks)
        if check["checked"] and not check["ok"]
    ]
    integrity_unmeasured = [
        s["id"] for s, check in zip(samples, integrity_checks) if not check["checked"]
    ]
    measurement_integrity = {
        "caliber": "full_text_vs_truncated_artifact_copy",
        "claim": (
            "every measured metric (chars, utf8_bytes, real_tokens, proxy_tokens) "
            "describes the FULL observation text; `text` is only a truncated display "
            "copy of at most max_stored_text characters"
        ),
        "n_samples": len(samples),
        "n_measured": sum(1 for check in integrity_checks if check["checked"]),
        "n_unmeasured": len(integrity_unmeasured),
        "n_inconsistent": len(integrity_inconsistent),
        "all_measured_on_full_text": not integrity_inconsistent,
        "measured_on_truncated_copy": len(integrity_inconsistent),
        "unmeasured_sample_ids": integrity_unmeasured[:20],
        "unmeasured_reasons": sorted({
            check["reason"] for check in integrity_checks
            if not check["checked"] and check.get("reason")
        }),
        "inconsistent_sample_ids": integrity_inconsistent[:20],
        "max_stored_text": args.max_stored_text,
        "n_truncated_artifact_copies": sum(
            1 for s in samples if s.get("text_truncated_in_artifact")
        ),
        "note": (
            "`text_truncated_in_artifact: true` means only the display copy is short; "
            "the metrics are still full-text. A sample that was not measured is left "
            "None with a skip reason and is excluded from every aggregate, never "
            "coerced to 0"
        ),
    }

    by_reason: dict[str, int] = {}
    for item in skips:
        by_reason[item["reason"]] = by_reason.get(item["reason"], 0) + 1
    for err in endpoint_errors:
        key = "endpoint_error:" + err["error"].split(":")[0]
        by_reason[key] = by_reason.get(key, 0) + 1
    for sample in samples:
        for err in (sample.get("endpoint_errors") or []):
            key = "endpoint_draw_error:" + err.split(":")[0]
            by_reason[key] = by_reason.get(key, 0) + 1
    for err in endpoint_plan.get("failures") or []:
        key = "endpoint_transport:" + err.split(":")[0]
        by_reason[key] = by_reason.get(key, 0) + 1

    selection_digest = hashlib.sha256(
        json.dumps(
            sorted(
                (s["condition"], s["task_id"], s["source_run"], s["cell_index"], s["op"])
                for s in samples
            ),
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()

    if args.no_replay or not selected:
        sample_source = "synthetic_fallback_corpus"
    elif used_fallback:
        sample_source = "replayed_live_trajectories_plus_synthetic_fallback"
    else:
        sample_source = "replayed_live_trajectories"

    payload = {
        "schema": "verseshell.token_proxy_calibration/v1",
        "method_revision": 2,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "git_rev": current_git_rev(),
        "generator": "tools/token_proxy_calibration.py",
        "model": env.get("ACI_BENCH_MODEL"),
        "api_base": env.get("ACI_BENCH_BASE_URL"),
        "sample_source": sample_source,
        "sample_source_detail": {
            "trajectory_artifact": _display(args.results),
            "artifact_generated_at": doc.get("generated_at"),
            "artifact_schema": doc.get("schema"),
            "source_runs_sampled": sorted({s["source_run"] for s in samples
                                           if s["condition"] in CONDITIONS}),
            "units_replayed": [f"{t}::{s}" for t, s in selected_units],
            "max_units": args.max_units,
            "cap_per_condition": args.cap,
            "selection": (
                "units ordered by (source_run, task_id) so the first N units are one "
                "complete benchmark round; cells taken round-robin across units"
            ),
            "fallback_corpus_used": used_fallback,
            "fallback_corpus": [name for name, _ in FALLBACK_TEXTS],
            "synthetic_samples_excluded_from_ratio_check": True,
            "concurrent_writer_warning": (
                "bench/aci/results/latest_live.json is regenerated by a live benchmark "
                "round; the values recorded here are the ones read at this run's start"
            ),
        },
        "evidence": {
            "globs": EVIDENCE_GLOBS,
            "fingerprint": evidence_fingerprint(EVIDENCE_GLOBS),
        },
        "tokenizer": {
            **tokenizer_info,
            "approximation_error_vs_cl100k": approximation_error,
            "why_not_only_the_endpoint": (
                "the endpoint's usage.prompt_tokens is content-cached and intermittently "
                "inflated; it is used as a secondary cross-check, not as the primary "
                "measurement"
            ),
        },
        "endpoint_protocol": {
            "hazard": (
                "usage.prompt_tokens is cached per input content (identical content "
                "returns an identical value even when that value is nonsense) and, for "
                "content the cache has not seen, roughly 10-60% of requests report a "
                "value inflated by a constant ~+170 tokens"
            ),
            "neutralisation": (
                "every probe carries a fresh 12-hex nonce so no probe can hit the cache; "
                "each text is drawn K times with K distinct nonces and the MINIMUM is "
                "kept (contamination is one-sided); at least two mutually agreeing "
                "uncontaminated draws are required before a text is trusted; the "
                "observed spread is reported as an interval; and every endpoint number "
                "is cross-checked against an independent real tokenizer"
            ),
            "nonce_shape": endpoint_plan.get("nonce_shape"),
            "estimator": (
                "min(unique-nonce draws of nonce+text) - min(unique-nonce draws of "
                "nonce+placeholder) + 1"
            ),
            "why_minimum_not_median": (
                "the contamination is additive and positive, so the minimum over "
                "independent draws estimates the uncontaminated value; the median does "
                "not, because contamination can exceed half the draws (5/8 observed in "
                "one session), which is recorded here as "
                "baseline_contaminated_draws"
            ),
            "min_fresh_draws_required": MIN_FRESH_DRAWS,
            "contamination_min_tokens": CONTAMINATION_MIN_TOKENS,
            **{k: v for k, v in endpoint_plan.items() if k != "failures"},
            "failures": endpoint_plan.get("failures"),
        },
        "method": {
            "proxy": ("estimate_tokens(text) = max(1, len(text)//4) from "
                      "bench/aci/runners/live_agent_loop.py"),
            "proxy_source": (
                "bench/aci/runners/live_agent_loop.py:estimate_tokens"
                if H is not None else
                "local reimplementation of the same one-liner (harness import failed)"
            ),
            "harness_import_error": HARNESS_IMPORT_ERROR,
            "real_tokens_basis": (
                f"{tokenizer_info['primary']} via {tokenizer_info['how_resolved']}"
            ),
            "endpoint_call": (
                "POST {api_base}/chat/completions, max_tokens=1, temperature=0, single "
                "user message whose content is '[<fresh nonce>] ' + text"
            ),
            "replay": (
                "raw_shell cells: execute_shell_cmd(args['command'], workspace); "
                "verseshell_aci cells: execute_aci_op(ACI_OP_MAP[op], args, workspace) "
                "then format_aci_result(response, compact=True); one workspace per stored "
                "row, calls replayed in recorded order"
            ),
            "skipped_cells_are_counted": True,
            "full_text_measurement": (
                "chars, utf8_bytes, real_tokens and proxy_tokens are all measured on the "
                "FULL observation text; `text` is only a truncated display copy of at "
                "most --max-stored-text characters and is never the measurement input; "
                "measurement_integrity re-derives that from the stored hashes"
            ),
            "tokenizer_invariants_ref": "aggregate.tokenizer_invariants",
            "caliber_labels_ref": "caliber_labels",
            "endpoint_calls_ok": endpoint.calls if endpoint else 0,
            "unique_endpoint_contents": len(endpoint.contents) if endpoint else 0,
            "shape_panel": "archetypal observation shapes, always measured, never replayed",
            "length_ladder": "the same prose at increasing lengths, as a monotonicity check",
        },
        "caliber_labels": CALIBER_LABELS,
        "calibration_anchor": anchor,
        "length_ladder": ladder_report,
        "shape_panel": panel,
        "replay_fidelity": fidelity,
        "measurement_integrity": measurement_integrity,
        "selection_digest": selection_digest,
        "skipped": {
            "total": len(skips) + len(endpoint_errors) + sum(
                len(s.get("endpoint_errors") or []) for s in samples
            ) + len(endpoint_plan.get("failures") or []),
            "by_reason": dict(sorted(by_reason.items())),
            "not_selected_due_to_cap": cap_not_selected,
            "endpoint_not_cross_checked": max(0, len(samples) - len(cross_texts)),
            "items": skips[:60],
            "items_truncated": max(0, len(skips) - 60),
            "endpoint_errors": endpoint_errors[:20],
            "endpoint_errors_truncated": max(0, len(endpoint_errors) - 20),
        },
        "samples": samples,
        "aggregate": agg,
        "endpoint_cross_check": cross,
        "verdict": verdict,
        "ratio_check": ratio_check,
        "caveats": [
            f"real_tokens is a real tokenizer count ({tokenizer_info['primary']}), not the "
            "endpoint's usage field. It is the tokenizer of the GPT-4/3.5 family, used "
            "here as a published, reproducible BPE reference; the model named in `model` "
            "has its own vocabulary, and endpoint_cross_check shows where the two "
            "disagree.",
            "the endpoint is a proxy in front of a remote service and is not a pure "
            "tokenizer: its usage.prompt_tokens is content-cached and intermittently "
            "inflated by ~+170 tokens. endpoint_protocol records the protocol used to "
            "neutralise that, and every endpoint number carries its draws, its interval "
            "and a stability flag.",
            "endpoint estimates are reported as intervals, never as false-precision "
            "point values; the estimator's noise (2-4 tokens) is inherent to the "
            "endpoint and is not hidden.",
            "the replayed texts come from one stored live round; commands whose output "
            "depends on build state (cargo/pip/tsc) may differ from the stored run, so "
            "the proxy/real ratios are representative rather than exact per-cell replays.",
            "the replayed corpus is dominated by short observations, so the aggregate is "
            "weighted towards them; aggregate.by_size_bucket and shape_panel show the "
            "shape dependence that a single aggregate number hides.",
            "the D/A ratio is recomputed on the same cells with real tokens; it is a "
            "statement about this sample, not about the whole benchmark population. "
            "Where the aggregate ratio lands on the other side of 1.0 than the proxy, "
            "ratio_check.sign_flip_robustness says whether that flip survives at the "
            "per-unit level or is produced by cell weighting.",
            "the proxy `len(text)//4` is NOT a bound in either direction and no single "
            "correction factor exists: it under-counts CJK and ASCII JSON/code "
            "observations and over-counts plain English prose, in the same artifact. A "
            "per-shape correction, or a real tokenizer, is required; see "
            "verdict.e_no_single_correction_factor.",
            "the earlier `real_tokens <= chars` claim is RETRACTED as an invariant "
            "(cl100k_base is a byte-level BPE, so one character can become several "
            "tokens). It is kept, explicitly labelled as not an invariant, in "
            "aggregate.tokenizer_invariants.chars_bound_observed, with the "
            "cjk_paragraph panel counterexample named. The applicable invariant is "
            "real_tokens <= utf8_bytes.",
            "ratio_check.published_proxy_ratio_D_over_A (default 0.8855) is a "
            "historical published proxy-cohort number whose provenance is unverified: "
            "it is NOT the current whole-round baseline and must not be combined with "
            "the recomputed ratio_check values, which cover only the cells replayable "
            "from the stored run and paired within (task_id, source_run).",
            "every metric carries its caliber: `proxy_tokens` is an observation proxy, "
            "`real_tokens` is a real BPE replay of the full text, `endpoint_tokens` is "
            "an endpoint usage reading; see the caliber_labels block. None of them is a "
            "cost number.",
        ],
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8", newline="\n",
    )

    # ── 8. Readable summary ──
    ov = agg["overall"]
    ub = agg["upper_bound_check"]
    print("")
    print(f"wrote {_display(args.out)}")
    synthetic = sum(1 for s in samples if s["condition"] == "synthetic")
    print(f"samples: {len(samples)} measured  "
          f"({', '.join(f'{k}={v}' for k, v in sorted(replayed_counts.items()))}"
          f"{', synthetic=' + str(synthetic) if synthetic else ''})")
    print(f"  tokenizer: {tokenizer_info['primary']} (tier {tokenizer_info['tier']}, "
          f"approximation={tokenizer_info['is_approximation']})")
    print(f"  real/proxy  mean={ov['real_over_proxy_ratio']['mean']} "
          f"median={ov['real_over_proxy_ratio']['median']} "
          f"min={ov['real_over_proxy_ratio']['min']} max={ov['real_over_proxy_ratio']['max']}")
    print(f"  relative error (proxy-real)/real  mean={ov['relative_error_proxy_vs_real']['mean']} "
          f"median={ov['relative_error_proxy_vs_real']['median']}")
    print(f"  chars per real token: {ov['chars_per_real_token']}")
    print(f"  direction: {agg['error_direction']}")
    print(f"  len//4 proxy upper-bound claim (proxy >= real): "
          f"{ub['at_least_4x_chars_per_token_holds']} "
          f"({ub['violations']}/{ub['n_samples']} violations)")
    inv = agg["tokenizer_invariants"]
    binv = inv["byte_invariant_detail"]
    cobs = inv["chars_bound_observed"]
    print(f"  invariant real<=utf8_bytes: "
          f"{inv['real_tokens_never_exceed_utf8_bytes']} "
          f"({binv['n_violations']}/{binv['n_checked']} violations over "
          f"{binv['n_samples_checked']} samples + {binv['n_panel_checked']} panel texts)")
    counter = cobs.get("named_panel_counterexample") or {}
    print(f"  chars bound real<=chars is NOT an invariant (retracted): observed "
          f"{cobs['observed_holds']}, {cobs['violations']}/{cobs['n_checked']} "
          f"counterexamples"
          + (f", e.g. {counter.get('name')}: {counter.get('chars')} chars vs "
             f"{counter.get('real_tokens')} real tokens" if counter else ""))
    print(f"  full-text measurement integrity: "
          f"{measurement_integrity['n_measured']}/{measurement_integrity['n_samples']} "
          f"measured on the FULL text, "
          f"{measurement_integrity['measured_on_truncated_copy']} measured on the "
          f"truncated copy, {measurement_integrity['n_unmeasured']} unmeasured, "
          f"{measurement_integrity['n_truncated_artifact_copies']} truncated display copies")
    for cls, summary in sorted(agg["by_char_class"].items()):
        print(f"    {cls:<16} n={summary['n_scored']:<4} "
              f"mean_real/proxy={summary['real_over_proxy_ratio']['mean']} "
              f"chars/token={summary['chars_per_real_token']}")
    for bucket, summary in sorted(agg["by_size_bucket"].items()):
        print(f"    size {bucket:<10} n={summary['n_scored']:<4} "
              f"mean_real/proxy={summary['real_over_proxy_ratio']['mean']}")
    print(f"  anchor ~400 English chars: proxy={anchor['proxy_tokens']} "
          f"real={anchor['real_tokens']} expected {anchor['expected_real_range']} "
          f"within={anchor['within_expected_range']}"
          + (f" endpoint={anchor['endpoint_tokens']} "
             f"interval={anchor['endpoint_interval']}" if anchor.get("endpoint_tokens") else ""))
    print(f"  length ladder: real={ladder_report['real_tokens_primary']} "
          f"increasing={ladder_report['primary_strictly_increasing']}; "
          f"endpoint={ladder_report['endpoint_tokens']} "
          f"increasing={ladder_report['endpoint_strictly_increasing']}")
    print("  shape panel (chars / proxy / real / real-per-proxy / endpoint):")
    for item in panel:
        print(f"    {item['name']:<22}{item['chars']:>6}{item['proxy_tokens']:>7}"
              f"{item['real_tokens']:>7}{item['ratio_real_over_proxy']:>9}"
              f"{(item['endpoint_tokens'] if item['endpoint_tokens'] is not None else '-'):>9}")
    print(f"  replay fidelity: {fidelity['proxy_matches_recorded']}/"
          f"{fidelity['cells_with_recorded_value']} cells reproduced the stored proxy count")
    print(f"  endpoint cross-check: {cross['n_stable']}/{cross['n_texts']} stable, "
          f"{cross['n_unstable']} unstable, {cross['n_disagree']} disagree with primary")
    print(f"    {cross['conclusion']}")
    if endpoint_plan["baseline_draws"]:
        print(f"    baseline draws={endpoint_plan['baseline_draws']} "
              f"min={endpoint_plan['baseline_raw_min']} "
              f"contaminated={endpoint_plan['baseline_contaminated_draws']} "
              f"offset={endpoint_plan['contamination_offset_tokens_observed']}")
    demo = endpoint_plan.get("hazard_demo")
    if demo:
        print(f"    cache-hazard demo: plain repeats="
              f"{demo.get('plain_repeated_content_prompt_tokens')} "
              f"identical={demo.get('plain_repeats_are_identical')}; "
              f"nonced={demo.get('nonced_content_prompt_tokens')}")
    rc = ratio_check
    if rc["supported"]:
        print(f"D/A ratio: real={rc['totals']['real_ratio_D_over_A']} "
              f"proxy={rc['totals']['proxy_ratio_D_over_A']} "
              f"over {rc['paired_units']} paired (task_id, source_run) buckets, "
              f"{rc['cells_used']['raw_shell']}A/{rc['cells_used']['verseshell_aci']}D cells; "
              f"{rc['sample_scope']['n_observations_paired']} paired observations of "
              f"{rc['sample_scope']['n_observations_replayable']} replayable "
              f"(NOT the whole round)")
        print(f"  historical published proxy ratio {rc['published_proxy_ratio_D_over_A']} "
              f"is a SEPARATE unverified cohort number, not the current baseline, and "
              f"must not be combined with the recomputed values above")
        print(f"  {rc['conclusion']}")
        print(f"  per-bucket direction: "
              f"{rc['direction_agreement']['units_where_sign_agrees']}/"
              f"{rc['direction_agreement']['units']} buckets agree, "
              f"{rc['direction_agreement']['units_where_direction_disagrees']} disagree")
    else:
        print(f"D/A ratio: UNSUPPORTED — {rc['reason_if_unsupported']}")
    print(f"skipped: {payload['skipped']['total']} items; by reason: "
          f"{json.dumps(payload['skipped']['by_reason'], ensure_ascii=False)}")
    print(f"  beyond cap (not measured): {json.dumps(cap_not_selected)}")
    print("")
    print("VERDICT")
    print(f"  direction : {verdict['a_error_direction']}")
    print(f"  magnitude : {verdict['b_error_magnitude']}")
    print(f"  upper bnd : {verdict['c_upper_bound']}")
    print(f"  hazard    : {verdict['d_cache_hazard_and_neutralisation']}")
    print(f"  no-1-factor: {verdict['e_no_single_correction_factor']}")
    print(f"  byte inv  : {verdict['f_tokenizer_byte_invariant']}")
    print(f"  chars bnd : {verdict['g_chars_bound_retracted']}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
    except Exception:  # noqa: BLE001 - surface the traceback, do not write a fake artifact
        traceback.print_exc()
        sys.exit(1)
