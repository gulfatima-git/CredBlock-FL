# CredBlock-FL full causal controlled inventory v1

## Verified execution result

The real local run passed all 11 automated tests and completed generation:

| Check | Result |
|---|---|
| Status | PASS_FULL_CONTROLLED_CAUSAL_GENERATION_ONLY |
| Instances | 513 (171 TRAIN, 171 VAL, 171 TEST) |
| Organization branches | 1,647 |
| Synthetic events | 155,988 (150,660 controlled; 5,328 descriptive reference) |
| Successful synthetic events | 7,788 (approximately 4.99%) |
| Targeted User/branch occurrences | 108,000 |
| Occurrences with strictly pre-anchor observations | 108,000/108,000 |
| Occurrences without activity in the recent seven days | 93,405 |
| Controlled RIP behavior groups | 162 |
| RIP alternatives compared with their group reference | 324 |
| Preserved input files with unchanged SHA-256 hashes | 1,532/1,532 |

The included `data/phase5/controlled_inventory_causal_v1/` contains the actual
verified generated outputs. To use the package, extract it into the project root
only if that new output directory does not already exist. The generator commands
below are for reproducing generation; they are not required to inspect the included
results. No background replay or full-inventory label output is included.

Phase 5 closeout progress: 2 of 4 handover steps complete (temporal labeling policy
and full corrected generation). Full replay/label validation and consolidated
acceptance/freeze remain. This milestone count is not a time-weighted percentage.

This standalone generator extends the accepted pilot approach to the complete
controlled recipe inventory. All original campaigns, historical campaigns, earlier
pilot/replay versions, source authentication data, and earlier reports are read-only.

## Scope

- 81 Raccount group recipes x 3 variants = 243 controlled Raccount instances.
- 81 Sorg group recipes x 3 variants = 243 controlled Sorg instances.
- 27 Sorg=1 descriptive references with Raccount not applicable.
- Total: 513 instances, 171 per chronological split, across 1,647 local branches.
- Controlled budgets total 150,660 synthetic events. Descriptive reference counts
  are inherited from their individual source campaigns and reported separately.
- This is a new attack-only experimental dataset version. It neither replaces nor
  exactly reproduces the accepted six-variant causal-v2 pilot.

## Fixed implementation choices

Each split/seed uses the original CS_004 campaign start as its common anchor.
These starts are read from existing manifests, not selected using model results:

| Split | Seed | Anchor |
|---|---|---|
| TRAIN | 1001 | 2020-03-01 13:00 |
| TRAIN | 1002 | 2020-03-02 09:00 |
| TRAIN | 1003 | 2020-03-03 21:00 |
| VAL | 1001 | 2020-10-06 07:00 |
| VAL | 1002 | 2020-10-06 19:00 |
| VAL | 1003 | 2020-10-06 23:00 |
| TEST | 1001 | 2020-12-12 06:00 |
| TEST | 1002 | 2020-12-12 21:00 |
| TEST | 1003 | 2020-12-13 17:00 |

All factor branches within a split/seed are isolated alternative replays of that
same source window. The common-anchor policy strengthens background matching but
limits the experiment to three temporal blocks per split. They are not 513
independent naturally occurring attack environments. Overlapping history windows
and repeated source observations must be respected when reporting uncertainty.

Candidates are organization-local User IDs observed strictly BEFORE the anchor.
The SQL candidate query filters timestamps before grouping or sampling. Each
organization gets a deterministic credential-ordinal -> local User mapping, shared
across controlled variants in the same split/seed block. Source flags and future
events cannot influence this selection. Historical observations are not proof of
account creation, and recently inactive accounts are intentionally retained.

The seven-day graph-history window may cross into an earlier chronological split
as past context. Attack events stay entirely within their assigned split; later
replay must never use prior-context labels as permission to train on TEST data.

Recipe organization order is canonical and controls the budget/count vectors.
Original manifests sometimes list the identical organization set in a different
order. The generator checks membership and retains the recipe vector order;
it does not reorder budgets according to source manifest order.

Raccount and Sorg budgets/attempt histograms come directly from accepted recipes.
The controlled variants are regenerated from those recipes with causal users,
not patched original campaign events. A 5% success probability is fixed in advance;
the realized fraction is reported, never forced to exactly 5% after generation.

Within each controlled family/Sorg/Raccount/split/seed, all three RIP levels hold
User IDs, credential coverage, timestamps, attempt counts and login outcomes fixed.
Behavioral digests exclude IP addresses and campaign/scenario identifiers; both
additional RIP levels must match the first. There are 162 such groups and 324
comparisons to their group references. The earlier original RIP audits are retained
and not rerun as a condition of accepting their old results.

IP addresses come from unoccupied space in the existing 198.18.0.0/15 benchmark
IPv4 namespace. Before allocation, address-bearing preexisting Phase 5 Parquet and
organization Parquet files are checked for collisions. Allocations are disjoint
between behavior groups and chronological splits. Only controlled RIP alternatives
within one isolated behavior group use nested prefixes of the same allocation.
The code fails closed if the available namespace is insufficient.

The Sorg=1 references retain original relative timestamps, login outcomes, event
totals and per-credential attempt patterns; local users are causally remapped,
timestamps are rebased to the common anchor, and fresh IPs are assigned. They are
descriptive references, not matched Raccount interventions or guaranteed RIP-only
comparisons.

## Preservation and validation

The generator checks recipe input hashes, factor/organization compatibility,
all per-organization budgets, target counts, one-to-three attempt histograms,
100 credential identities, exact reuse counts, source eligibility, timestamp/split
boundaries, unique event IDs and exact rounded IP counts. Parquet writes receive
count checks. Prior Phase 5 files, organization Parquet inputs and recipe sources
receive SHA-256 preservation checks before and after generation.

Built-in tests cover deterministic generation, all recipe cohort layouts, causal
SQL filtering, insufficient/future candidates, budget/reuse checks, RIP-only
behavior, Sorg=1 semantics, invalid allocations, split boundaries and new paths.

No model is fitted or tuned. TEST is generated using the prespecified recipe and
causal eligibility rules, not used to choose a labeling horizon or model threshold.

## Files and reproduction

`generate_phase5_controlled_inventory_causal_v1.py` is the standalone script.
The default output directory is new and must not already exist:
`data/phase5/controlled_inventory_causal_v1/`.

Each instance has a manifest and one synthetic-event Parquet per targeted
organization. Top-level files include `plan.json`, `summary.json`, `summary.txt`,
`variants.csv`, `branches.csv`, and `output_sha256.json`.

With the existing virtual environment activated, save the script in the project
root and run:

```powershell
Set-Location 'C:\Users\Gulso\Documents\Gul\CredBlock-FL'
python .\generate_phase5_controlled_inventory_causal_v1.py --self-test
python .\generate_phase5_controlled_inventory_causal_v1.py
```

If the default output exists, use a different NEW directory:

```powershell
python .\generate_phase5_controlled_inventory_causal_v1.py --output '.\data\phase5\controlled_inventory_causal_v1_run2'
```

For review after your own run, share `summary.json`, `variants.csv`, and
`branches.csv`. No need to upload organization authentication data.

## Acceptance boundary and next step

Expected successful status: `PASS_FULL_CONTROLLED_CAUSAL_GENERATION_ONLY`.
This accepts synthetic generation only. Availability checks establish that source
observations exist in the history/hour; they do not certify complete logging,
identical replay backgrounds, temporal labels, graph features or model performance.

Raccount still changes coverage and per-user frequency. Primary Sorg still changes
organization composition and total attempts. No optional fixed-total Sorg
sensitivity dataset is generated here. Original RBA source flags do not establish
synthetic credential-stuffing truth, and all truth/provenance remains evaluator-only.

Next: isolated background replay for all 513 instances, apply the accepted temporal
User-node label policy, validate the complete dataset, then issue one consolidated
Phase 5 acceptance report and freeze. GraphSAGE feature checks remain later work.
