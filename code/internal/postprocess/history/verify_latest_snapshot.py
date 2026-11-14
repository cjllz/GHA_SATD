"""Independent latest-snapshot check against original history and frozen candidates.

Uses CSV streaming and the read-only phase-1 SQLite status table; no selection
query or latest builder database is reused.
"""
import csv
import hashlib
import json
from pathlib import Path
import sqlite3
import argparse

ROOT=Path(__file__).resolve().parents[2]

def verify(root,output,state):
    root,output,state=map(Path,(root,output,state))
    first={};previous={};broken=set();nonterminal=set()
    print('Independently streaming original workflows.csv',flush=True)
    with (root/'workflows.csv').open(encoding='utf-8',newline='') as f:
        for index,row in enumerate(csv.DictReader(f),2):
            key=(row['repository'],row['uid'])
            if key not in first:first[key]={**row,'source_row_number':str(index)}
            else:
                newer=previous[key]
                if (newer['previous_file_hash'],newer['previous_file_path'])!=(row['file_hash'],row['file_path']):broken.add(key)
                if row['git_change_type']=='D' or (row['git_change_type']=='R' and not row['file_hash']):nonterminal.add(key)
            previous[key]=row
    del previous
    expected={};path_members={}
    for key,r in first.items():
        if r['file_hash'] and r['git_change_type']!='D':path_members.setdefault((r['repository'],r['file_path']),[]).append(key)
    with sqlite3.connect(state.resolve().as_uri()+'?mode=ro',uri=True) as db:
        for key,r in first.items():
            if key in broken or key in nonterminal:continue
            if r['git_change_type'] not in ('A','M','R') or not r['file_hash'] or not r['file_path']:continue
            if len(path_members[(r['repository'],r['file_path'])])!=1:continue
            status=db.execute('SELECT status FROM files WHERE file_hash=?',(r['file_hash'],)).fetchone()
            if status==('ok',):expected[key]=r
    with (output/'latest_workflows.csv').open(encoding='utf-8',newline='') as f:
        actual={(r['repository'],r['uid']):r for r in csv.DictReader(f)}
    assert expected.keys()==actual.keys(),(len(expected),len(actual))
    for key,r in expected.items():
        for col in ['file_hash','previous_file_hash','file_path','previous_file_path','commit_hash','committed_date','source_row_number']:
            assert r[col]==actual[key][col],(key,col)
    byhash={}
    for r in expected.values():byhash.setdefault(r['file_hash'],[]).append(r)
    expected_comments={}
    with (root/'output/satd_comments.csv').open(encoding='utf-8',newline='') as f:
        for c in csv.DictReader(f):
            for v in byhash.get(c['file_hash'],[]):
                parts=['satd-occurrence-v1',v['repository'],v['uid'],v['commit_hash'],c['satd_comment_id']]
                identity=hashlib.sha256(json.dumps(parts,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
                expected_comments[identity]=(c,v)
    seen=set()
    with (output/'latest_satd_comments.csv').open(encoding='utf-8',newline='') as f:
        for r in csv.DictReader(f):
            assert r['occurrence_id'] not in seen
            seen.add(r['occurrence_id']);c,v=expected_comments[r['occurrence_id']]
            for col in ['satd_comment_id','file_hash','comment_text','normalized_text','matched_keywords','line_start','line_end','satd_location']:assert r[col]==c[col],col
            for col in ['repository','uid','commit_hash','committed_date','file_path','previous_file_path','previous_file_hash','git_change_type']:assert r[col]==v[col],col
    assert seen==expected_comments.keys()
    result={'passed':True,'original_history_lifecycles':len(first),'eligible_latest_workflows':len(expected),
            'candidate_rows':len(seen),'workflow_keys_and_metadata_match':True,'all_candidate_fields_match':True,
            'no_missing_or_extra_candidates':True,'method':'Original workflows.csv streaming + read-only phase1 statuses + frozen candidate CSV; no latest selection tables used to construct expected results'}
    (output/'independent_latest_validation.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    return result

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,default=ROOT)
    p.add_argument('--output',type=Path,default=ROOT/'output/stage2/latest')
    p.add_argument('--state',type=Path,required=True);a=p.parse_args()
    print(json.dumps(verify(a.root,a.output,a.state),indent=2))
