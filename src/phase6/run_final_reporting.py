"""Option A saved TRAIN/VAL reporting only. Does not expose a TEST adapter."""
import argparse
from pathlib import Path
from src.phase6.final_reporting import run,guard_split
def main():
    p=argparse.ArgumentParser();p.add_argument('--splits',nargs='+',default=['TRAIN','VAL']);args=p.parse_args()
    for split in args.splits:guard_split(split)
    root=Path(__file__).resolve().parents[2]
    run(root,root/'reports/phase6/final/v1/tables',root/'configs/phase6/final_reporting_v1.json',args.splits)
    print('PASS saved TRAIN/VAL reporting; TEST deferred, Phase 6 incomplete')
if __name__=='__main__':main()
