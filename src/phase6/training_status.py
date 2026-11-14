"""Read-only compact status for the current full local training components."""
import json
from pathlib import Path
import psutil


def status():
    root=Path(__file__).resolve().parents[2]
    plan=json.loads((root/'reports/phase6/training/execution_plan_v3.json').read_text())
    rows=[]
    for org,relative in plan['components'].items():
        directory=root/relative
        progress=directory/'progress.jsonl'
        row=dict(organization=org,event='QUEUED')
        if progress.exists():
            for line in reversed(progress.read_text().splitlines()):
                try:
                    latest=json.loads(line)
                    row.update({k:latest[k] for k in ['event','split','branches_done','branches_total','candidate','run','epoch','val_ap'] if k in latest})
                    break
                except json.JSONDecodeError: pass
        rows.append(row)
    journal=root/'reports/phase6/training/full_v2/execution.jsonl'
    finished=set()
    if journal.exists():
        for line in journal.read_text().splitlines():
            try:
                event=json.loads(line)
                if event['event']=='organization_job_finished': finished.add(event['organization'])
            except json.JSONDecodeError: pass
    return dict(components=rows,supervisor_primary_two_finished=all(f'Org{i}' in finished for i in range(1,3)),
                free_ram_mib=round(psutil.virtual_memory().available/2**20))


if __name__=='__main__':
    print(json.dumps(status()))
