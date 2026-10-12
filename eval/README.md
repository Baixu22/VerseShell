# Evidence status — 2026-10-06

The canonical live reports in this directory are **historical baselines**. They
have not been refreshed from c20/c21, and neither those collections nor these
reports establish acceptance of the repaired runner.

The c20/c21 source collections remain unchanged. Offline reports using their
original recorded scores are in `audit-r12-scratch/repair-2026-10-06/`. They add
Holm-labelled verdicts, both ratio estimators and corrected exclusion counts;
they do not retroactively repair the scoring of the original live runs.

Do not copy a with-only collection over the canonical paired with/without
baselines: c20/c21 have no read_files ablation control. New source fingerprints
require a new collection tag and live rerun before publishing current claims.

See [repair report](../docs/c20-c21-repair-2026-10-06.md) for evidence and the next
measurement protocol.
