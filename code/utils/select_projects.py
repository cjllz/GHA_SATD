"""Select mature, large, maintained Top 300 projects before SATD extraction."""
import argparse
import csv
import json
import re
from collections import Counter
from datetime import datetime, timezone
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
# Published dataset schemas remain available to the independent verifier.
FIELDS = ['satd_comment_id','name','file_hash','comment_text','normalized_text',
    'matched_keywords','line_start','line_end','satd_location']
PROJECT_FIELDS = ['rank','name','language','codelines','age_years','stars','contributors',
    'commits','workflow_commits_12m','workflow_max_consecutive_months_12m',
    'satd_candidate_count','size_percentile','age_percentile','stars_percentile','composite_score']
SELECTION_FIELDS = ['rank','name','language','codelines','age_years','stars','contributors',
    'commits','workflow_commits_12m','workflow_max_consecutive_months_12m',
    'size_percentile','age_percentile','stars_percentile','composite_score']
MONTHS = [f'2025-{month:02d}' for month in range(3,13)]+['2026-01','2026-02']
CUTOFF = datetime(2026,3,27,tzinfo=timezone.utc)
MIN_CREATED = datetime(2023,3,27,tzinfo=timezone.utc)


def read(path):
    with Path(path).open(encoding='utf-8-sig',newline='') as stream:
        reader=csv.DictReader(stream)
        return reader.fieldnames,list(reader)


def write(path,fields,rows):
    with Path(path).open('x',encoding='utf-8-sig',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=fields,extrasaction='ignore')
        writer.writeheader();writer.writerows(rows)


def percentiles(values):
    """Average ascending ranks, scaled by 100*(rank-1)/(N-1)."""
    if len(values)<2:raise ValueError('At least two eligible projects required')
    counts=Counter(values);scores={};below=0
    for value in sorted(counts):
        scores[value]=Fraction(2*below+counts[value]-1,2)*100/(len(values)-1)
        below+=counts[value]
    return [scores[value] for value in values]


def utc(value):
    parsed=datetime.fromisoformat(value)
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


def build(repositories_path,activity_path):
    repository_fields,repositories=read(repositories_path)
    activity_fields,activity=read(activity_path)
    required={'name','created','commits','contributors','codelines','stars','language'}
    if not required<=set(repository_fields or []):raise ValueError('Unexpected repositories.csv schema')
    if activity_fields!=['name','month','workflow_commits']:raise ValueError('Unexpected activity schema')
    names={row['name'] for row in repositories}
    if len(names)!=len(repositories):raise ValueError('Duplicate repository names')

    monthly={}
    for row in activity:
        if row['name'] not in names:raise ValueError(f"Unknown activity repository: {row['name']}")
        key=(row['name'],row['month'])
        count=int(row['workflow_commits'])
        if key in monthly or row['month'] not in MONTHS or count<1:
            raise ValueError(f'Invalid monthly activity record: {key}')
        monthly[key]=count

    eligible=[]
    for source in repositories:
        created=utc(source['created'])
        bits=''.join('1' if (source['name'],month) in monthly else '0' for month in MONTHS)
        streak=max([len(run) for run in re.findall('1+',bits)] or [0])
        if not (created<MIN_CREATED and int(source['commits'])>=500
                and int(source['contributors'])>=100 and int(source['codelines'])>100000
                and streak>=7):continue
        row=dict(source)
        row['_age']=int((CUTOFF-created).total_seconds())
        row['age_years']=round(row['_age']/86400/365.2425,4)
        row['workflow_commits_12m']=sum(monthly.get((row['name'],month),0) for month in MONTHS)
        row['workflow_max_consecutive_months_12m']=streak
        row['_score']=Fraction(0)
        eligible.append(row)

    for source,target in [('codelines','size_percentile'),('_age','age_percentile'),('stars','stars_percentile')]:
        scores=percentiles([int(row[source]) for row in eligible])
        for row,score in zip(eligible,scores):
            row[target]=float(score);row['_score']+=score/3
    eligible.sort(key=lambda row:(-row['_score'],row['name']))
    for index,row in enumerate(eligible,1):
        row['rank']=index;row['composite_score']=float(row['_score'])
    if len(eligible)<300:raise ValueError('Fewer than 300 eligible projects; criteria will not be relaxed')
    selected=eligible[:300]
    report={'starting_repositories':len(repositories),'repositories_with_workflow_activity':len({name for name,_ in monthly}),
        'eligible_repositories':len(eligible),'selected_repositories':len(selected),
        'selection_uses_comments':False,'selection_uses_satd_candidates':False,
        'eligibility':{'created_before':'2023-03-27T00:00:00Z','commits_min':500,
            'contributors_min':100,'codelines_strictly_greater_than':100000,
            'workflow_activity_window':'2025-03 through 2026-02','consecutive_active_months_min':7},
        'ranking':{'codelines_weight':'1/3','age_weight':'1/3','stars_weight':'1/3'}}
    return eligible,selected,report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repositories',type=Path,required=True,help='Original full repositories.csv')
    parser.add_argument('--activity',type=Path,required=True,help='Output of the activity subcommand')
    parser.add_argument('--output',type=Path,default=ROOT/'output/project_selection')
    args=parser.parse_args()
    if args.output.exists() and any(args.output.iterdir()):raise FileExistsError('Use an empty output directory')
    args.output.mkdir(parents=True,exist_ok=True)
    eligible,selected,report=build(args.repositories,args.activity)
    write(args.output/'eligible_projects.csv',SELECTION_FIELDS,eligible)
    write(args.output/'selected_projects_300.csv',SELECTION_FIELDS,selected)
    (args.output/'project_selection_report.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(report,output=str(args.output.resolve())),indent=2))


if __name__=='__main__':main()
