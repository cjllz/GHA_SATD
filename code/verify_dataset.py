"""Verify the 1,046 candidates and 876 reviewed rows without raw inputs."""
import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent / 'utils'))
from select_projects import ROOT,FIELDS,PROJECT_FIELDS,read


def verify_final(dataset):
    fields,comments=read(dataset/'satd_comments.csv')
    pf,projects=read(dataset/'projects.csv')
    assert fields==FIELDS and pf==PROJECT_FIELDS
    assert len(comments)==1046 and len(projects)==300
    names={r['name'] for r in projects}
    assert len(names)==300
    counts=Counter()
    for r in comments:
        name=json.loads(r['name']);assert len(name)==1 and name[0] in names
        counts[name[0]]+=1
        assert 1<=int(r['line_start'])<=int(r['line_end'])
        assert json.loads(r['matched_keywords'])
    for i,r in enumerate(projects,1):
        assert int(r['rank'])==i and counts[r['name']]==int(r['satd_candidate_count'])
    assert projects==sorted(projects,key=lambda r:(-float(r['composite_score']),r['name']))
    rf,reviewed=read(dataset/'satd_comments_reviewed.csv')
    assert rf==FIELDS and len(reviewed)==876
    rowkey=lambda r:tuple(r[f] for f in FIELDS)
    available=Counter(rowkey(r) for r in comments)
    assert not (Counter(rowkey(r) for r in reviewed)-available)
    assert len({n for r in reviewed for n in json.loads(r['name'])})==263
    for relative,item in json.loads((dataset/'checksums.json').read_text(encoding='utf-8')).items():
        with (dataset/Path(relative).relative_to('dataset')).open('rb') as f:
            assert hashlib.file_digest(f,'sha256').hexdigest()==item['sha256']
    return dict(projects=300,candidate_occurrences=1046,reviewed_occurrences=876,fields=9,checksums_match=True,
                scope='Final files only; this check does not rebuild selection from raw data')


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--dataset',type=Path,default=ROOT/'dataset')
    print(json.dumps(verify_final(p.parse_args().dataset),indent=2))
