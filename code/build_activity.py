"""Optional: rebuild monthly workflow activity from the original workflows.csv."""
import argparse
import csv
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from select_projects import ROOT,read,write


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--workflows',type=Path,required=True)
    p.add_argument('--repositories',type=Path,required=True,help='Original repositories.csv or a matching subset')
    p.add_argument('--output',type=Path,default=ROOT/'output/workflow_activity_monthly.csv')
    a=p.parse_args()
    if a.output.exists():raise FileExistsError(a.output)
    _,repos=read(a.repositories);names={r['name'] for r in repos}
    start=int(datetime(2025,3,1,tzinfo=timezone.utc).timestamp())
    end=int(datetime(2026,3,1,tzinfo=timezone.utc).timestamp())
    commits=defaultdict(set);csv.field_size_limit(10_000_000)
    with a.workflows.open(encoding='utf-8-sig',newline='') as f:
        for r in csv.DictReader(f):
            if r['repository'] not in names:continue
            t=int(r['committed_date'])
            if start<=t<end:
                month=datetime.fromtimestamp(t,timezone.utc).strftime('%Y-%m')
                commits[r['repository'],month].add(r['commit_hash'])
    rows=[dict(name=n,month=m,workflow_commits=len(c)) for (n,m),c in sorted(commits.items())]
    a.output.parent.mkdir(parents=True,exist_ok=True)
    write(a.output,['name','month','workflow_commits'],rows)
    print(f'Exported {len(rows)} repository-month records to {a.output}')


if __name__=='__main__':main()
