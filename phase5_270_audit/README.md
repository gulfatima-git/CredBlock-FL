# CredBlock-FL: read-only audit of all 270 Phase 5 campaigns

This script audits each expected `CS_XXX_SEEDYYYY_SPLIT` campaign directory against the saved split schedule, allocation table, manifest and Parquet event data.

## Run

From the root of the existing CredBlock-FL repository, copy `audit_270_campaigns.py` into the project root and run:

```powershell
python -m pip install duckdb
python audit_270_campaigns.py
```

The script assumes the project already has:

- `src/simulation/credential_stuffing_generator.py`
- `data/phase5/metadata/split_campaign_schedule.json`
- `data/phase5/synthetic_events/`

## What it checks per campaign

- Whether the campaign directory exists (missing campaigns are `NOT_GENERATED`, never PASS).
- Manifest presence and validity, campaign ID, scenario and split.
- Manifest start against the schedule timestamp for that campaign's deterministic slot.
- Campaign duration and chronological split bounds.
- Required manifest measurements and basic scenario/RIP consistency.
- Parquet presence and readability.
- Actual event IPs against that campaign's reserved IP interval.
- Event campaign IDs, event timestamps, event-ID uniqueness and event count against the manifest.

## Outputs

The script writes:

- `reports/phase5_270_campaign_audit.json` — detailed per-campaign and per-check results.
- `reports/phase5_270_campaign_audit.csv` — compact campaign-level summary.

Statuses are deliberately distinct:

- `PASS`: all applicable checks passed.
- `FAIL`: at least one check failed.
- `INCOMPLETE`: a campaign exists but one or more checks could not be performed.
- `NOT_GENERATED`: expected campaign directory is absent.

The script is read-only with respect to campaign data. It does not generate, overwrite, rename or delete campaign files. It only creates/overwrites the two audit reports under `reports/`.

## Important scope limitation

This is a campaign-level data-integrity and schedule/IP audit. It does not prove matched factorial controls, seven-day temporal graph retention, ten-minute feature correctness, label onset/expiration, no future-data leakage, or reproducible independent batch regeneration. Those require separate evidence and specialized tests.
