"""Select Top 300 using externally supplied candidates, metadata and activity."""
import argparse
import csv
import hashlib
import json
import re
from collections import Counter
from datetime import datetime, timezone
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIELDS = ['satd_comment_id','name','file_hash','comment_text','normalized_text',
          'matched_keywords','line_start','line_end','satd_location']
PROJECT_FIELDS = ['rank','name','language','codelines','age_years','stars','contributors',
    'commits','workflow_commits_12m','workflow_max_consecutive_months_12m',
    'satd_candidate_count','size_percentile','age_percentile','stars_percentile','composite_score']


def read(path):
    with path.open(encoding='utf-8-sig',newline='') as f:
        reader=csv.DictReader(f)
        return reader.fieldnames,list(reader)


def write(path,fields,rows):
    with path.open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore')
        writer.writeheader();writer.writerows(rows)


def percentiles(values):
    """Average ascending ranks, scaled by 100*(rank-1)/(N-1)."""
    if len(values)<2:raise ValueError('At least two projects required')
    counts=Counter(values);scores={};below=0
    for value in sorted(counts):
        scores[value]=Fraction(2*below+counts[value]-1,2)*100/(len(values)-1)
        below+=counts[value]
    return [scores[v] for v in values]


def build(inputs):
    fields,candidates=read(inputs/'latest_candidates.csv')
    if fields!=FIELDS:raise ValueError('Unexpected candidate schema')
    _,repositories=read(inputs/'repositories.csv')
    _,activity=read(inputs/'workflow_activity_monthly.csv')
    counts=Counter()
    for r in candidates:
        names=json.loads(r['name'])
        if not isinstance(names,list) or len(names)!=1:raise ValueError('Latest rows must identify one repository')
        counts[names[0]]+=1
    if len({r['name'] for r in repositories})!=len(repositories):raise ValueError('Duplicate repository')
    if not set(counts)<={r['name'] for r in repositories}:raise ValueError('Repository join is incomplete')
    repositories=[r for r in repositories if r['name'] in counts]
    months=[f'2025-{m:02d}' for m in range(3,13)]+['2026-01','2026-02']
    monthly={}
    for r in activity:
        if r['name'] not in counts:continue
        key=(r['name'],r['month'])
        if key in monthly or r['name'] not in counts or r['month'] not in months or int(r['workflow_commits'])<1:
            raise ValueError('Invalid monthly activity record')
        monthly[key]=int(r['workflow_commits'])
    cutoff=datetime(2026,3,27,tzinfo=timezone.utc)
    projects=[]
    for r in repositories:
        created=datetime.fromisoformat(r['created']).replace(tzinfo=timezone.utc)
        bits=''.join('1' if (r['name'],m) in monthly else '0' for m in months)
        streak=max([len(x) for x in re.findall('1+',bits)] or [0])
        if not (created<datetime(2023,3,27,tzinfo=timezone.utc) and int(r['commits'])>=500
                and int(r['contributors'])>=100 and int(r['codelines'])>100000 and streak>=7):continue
        r=dict(r)
        r['_age']=int((cutoff-created).total_seconds())
        r['age_years']=round(r['_age']/86400/365.2425,4)
        r['workflow_commits_12m']=sum(monthly.get((r['name'],m),0) for m in months)
        r['workflow_max_consecutive_months_12m']=streak
        r['satd_candidate_count']=counts[r['name']]
        r['_score']=Fraction(0)
        projects.append(r)
    for source,target in [('codelines','size_percentile'),('_age','age_percentile'),('stars','stars_percentile')]:
        for r,p in zip(projects,percentiles([int(r[source]) for r in projects])):
            r[target]=float(p);r['_score']+=p/3
    projects.sort(key=lambda r:(-r['_score'],r['name']))
    for index,r in enumerate(projects,1):r['rank']=index;r['composite_score']=float(r['_score'])
    if len(projects)<300:raise ValueError('Fewer than 300 eligible projects; criteria will not be relaxed')
    selected=projects[:300];names={r['name'] for r in selected}
    final=[r for r in candidates if json.loads(r['name'])[0] in names]
    return selected,final,{'starting_candidates':len(candidates),'starting_repositories':len(repositories),
        'eligible_repositories':len(projects),'eligible_candidates':sum(r['satd_candidate_count'] for r in projects),
        'selected_repositories':len(selected),'selected_candidates':len(final)}


def verify(dataset,projects,comments):
    """Compare every field and row, not just aggregate counts."""
    pf,expected_projects=read(dataset/'projects.csv')
    cf,expected_comments=read(dataset/'satd_comments.csv')
    actual=[{k:str(r[k]) for k in PROJECT_FIELDS} for r in projects]
    if pf!=PROJECT_FIELDS or actual!=expected_projects:raise AssertionError('Project metrics or ordering differ')
    if cf!=FIELDS or comments!=expected_comments:raise AssertionError('Candidate fields/order/multiplicity differ')
    manifest=json.loads((dataset/'checksums.json').read_text(encoding='utf-8'))
    for relative,item in manifest.items():
        path=dataset/Path(relative).relative_to('dataset')
        with path.open('rb') as f:actual_hash=hashlib.file_digest(f,'sha256').hexdigest()
        if actual_hash!=item['sha256']:raise AssertionError(f'Checksum mismatch: {relative}')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inputs',type=Path,required=True,help='External directory with latest_candidates.csv, repositories.csv and workflow_activity_monthly.csv')
    parser.add_argument('--reference',type=Path,default=ROOT/'dataset',help='Published final tables for verification')
    parser.add_argument('--output',type=Path,default=ROOT/'output/reproduced')
    parser.add_argument('--verify-only',action='store_true',help='Recompute and compare without writing outputs')
    args=parser.parse_args()
    projects,comments,report=build(args.inputs)
    verify(args.reference,projects,comments)
    if not args.verify_only:
        if args.output.exists() and any(args.output.iterdir()):raise FileExistsError('Use an empty output directory')
        args.output.mkdir(parents=True,exist_ok=True)
        write(args.output/'projects.csv',PROJECT_FIELDS,projects)
        write(args.output/'satd_comments.csv',FIELDS,comments)
        (args.output/'verification.json').write_text(json.dumps(dict(report,verified=True),indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(report,verified=True),indent=2))


if __name__=='__main__':main()
