# C16 lossless read projection: implementation protocol

Frozen before implementation on 2026-09-30. The user selected implementing and
verifying C16 while retaining C14's original failure. This supersedes the earlier
optional no-go for C16, not either claim's definition or threshold.

## Candidate (one format, no search over variants)

Keep the existing compact projection's semantic object, including content_hash,
paths, partial-window line counts, start_line, errors and continuation fields.
For successful projections carrying text, encode it as:

```
read-text/v1 {compact JSON metadata}
first verbatim text
second verbatim text
```

In the metadata, each `text` value is its Unicode character count. Bodies follow
in top-level-then-files order, separated by one newline; lengths, not delimiters
inside source text, determine the boundaries. Zero-length text is supported.
Decoding restores exactly the former compact JSON object. File content may
contain headers, newlines, quotes, backslashes, Unicode or control characters.
Failure and metadata-only projections remain ordinary JSON. `compact=False`
remains byte-identical to the existing C16 reference rendering. No digest
shortening, window reduction, field omission, budget or threshold change.

The reference runner documents this format in its read tool descriptions. Local
consumers must use the matching decoder. The Rust server envelope stays intact.

## Required verification

1. Round-trip edge cases and real-server read/view/batch/error/pagination cases;
   reuse the displayed digest for a successful edit and reject its stale reuse.
2. Replay all 144 current r15 read calls. Use the saved pre-change projector to
   identify the original cohort independently of candidate savings; disclose
   every exclusion. Require 141 baseline matches, the recorded baseline token
   totals, semantic equality for every replay, and unchanged legacy rendering.
   Candidate C16 must save >=10% relative to the original legacy rendering.
3. Recompute C14 with its original digest-only counterfactual; keep FAIL if <15%.
4. Run the Python regression suite. Keep canonical live/eval measurements and
   frozen tasks unchanged; code changes make existing fingerprints stale.
5. Live integration probe: seed 42, temperature 0, 8 turns, 16384 completion tokens,
   condition D, the existing smoke task list, configured ACI endpoint. Preserve
   every outcome and do not retry task failures. Verify the model actually reads
   the new format and completes task predicates. This is a development probe,
   not the full 630-cell grid or a statistical non-inferiority result.

Offline replay is mechanism evidence only. Canonical C16 PASS requires fresh
live-derived replay and the broader affected evidence chain. Do not bless old
model trajectories with a new fingerprint. Do not publish the probe over the
existing full baseline. All work artifacts go under
`audit-r12-scratch/c16-lossless-2026-09-30/`.

## 2026-09-30 strategy follow-up, before the next probe

The user delegated the engineering trade-off. C14 keeps its original FAIL and no
further threshold-chasing work. C16 remains a candidate awaiting formal evidence;
do not immediately launch a standalone full grid while the wider candidate is
still changing. Combine that collection with the next candidate freeze.

A local screen found 499 extra serialized tool-schema characters per request in
the first candidate. This is not endpoint usage and cannot establish a regression.
Before any further live probe, rewrite only the read-tool descriptions to explain
the same format within the original tool-schema character budget, both with and
without read_files. Keep parameters, tools, output format and all thresholds fixed.
Check the schema budget and unchanged parameter schemas, repeat local regression,
then repeat the same three-task D smoke once at the original configuration in a
new output file. Preserve both probe batches regardless of outcomes. This remains
development verification, not a formal comparison or a claim about total cost.
