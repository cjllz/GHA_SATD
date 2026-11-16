"""Build repository workflow activity before any SATD extraction."""
import argparse
import csv
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from select_projects import ROOT,read,write


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--workflows',type=Path,required=True)
    p.add_argument('--repositories',type=Path,required=True,help='Original full repositories.csv')
    p.add_argument('--output',type=Path,default=ROOT/'output/workflow_activity_monthly.csv')
    a=p.parse_args()
    if a.output.exists():raise FileExistsError(a.output)
    fields,repos=read(a.repositories)
    if 'name' not in fields:raise ValueError('repositories.csv has no name field')
    names={r['name'] for r in repos}
    if len(names)!=len(repos):raise ValueError('Duplicate repository names')
    start=int(datetime(2025,3,1,tzinfo=timezone.utc).timestamp())
    end=int(datetime(2026,3,1,tzinfo=timezone.utc).timestamp())
    commits=defaultdict(set);csv.field_size_limit(10_000_000)
    with a.workflows.open(encoding='utf-8-sig',newline='') as f:
        reader=csv.DictReader(f)
        required={'repository','commit_hash','committed_date'}
        if not required<=set(reader.fieldnames or []):raise ValueError('Unexpected workflows.csv schema')
        for r in reader:
            if r['repository'] not in names:continue
            t=int(r['committed_date'])
            if start<=t<end and r['commit_hash']:
                month=datetime.fromtimestamp(t,timezone.utc).strftime('%Y-%m')
                commits[r['repository'],month].add(r['commit_hash'])
    rows=[dict(name=n,month=m,workflow_commits=len(c)) for (n,m),c in sorted(commits.items())]
    a.output.parent.mkdir(parents=True,exist_ok=True)
    write(a.output,['name','month','workflow_commits'],rows)
    print(json.dumps({'repositories':len(repos),'active_repositories':len({r['name'] for r in rows}),
        'repository_months':len(rows),'window':'2025-03 through 2026-02',
        'counting_unit':'distinct (repository, commit_hash) per month','output':str(a.output.resolve())},indent=2))


if __name__=='__main__':main()
