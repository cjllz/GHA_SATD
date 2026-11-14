import csv
import hashlib
import json
from pathlib import Path
import pytest
import build_satd_comments as build


def dataset(tmp_path):
    root=tmp_path/'data';(root/'workflows').mkdir(parents=True)
    sources=[
        'jobs:\n  test:\n    steps:\n      - name: test\n        # TODO workaround\n        uses: a/b@main\n',
        'jobs:\n  test:\n    # FIXME unclear\n\n    runs-on: ubuntu-latest\n',
        '# TODO detached\n\non: push\n# ordinary comment\n',
        '# TODO retain on broken tree\njobs: [}\n',
    ]
    hashes=[]
    for s in sources:
        h=hashlib.sha256(s.encode()).hexdigest();hashes.append(h)
        (root/'workflows'/h).write_bytes(s.encode())
    with (root/'workflows.csv').open('w',newline='',encoding='utf-8') as f:
        w=csv.writer(f);w.writerow(['repository','file_hash','previous_file_hash'])
        w.writerows([['a/repo',h,''] for h in hashes[:-1]])
        w.writerow(['a/repo','',hashes[-1]])
        w.writerow(['b/repo',hashes[0],''])
    return root


def rows(out):
    with (out/'satd_comments.csv').open(encoding='utf-8',newline='') as f:
        return list(csv.DictReader(f))


def test_end_to_end_all_hits_retained_and_recoverable(tmp_path):
    root=dataset(tmp_path); out=tmp_path/'output'
    report=build.run_pipeline(root,out,workers=1)
    result=rows(out)
    assert len(result)==4
    assert set(result[0])==set(build.FIELDS)
    assert sorted(r['satd_location'] for r in result)==['jobs.test','jobs.test.steps[0].uses','unknown','unknown']
    assert report['keyword_candidates']==report['output_rows']==4
    assert report['located_candidates']+report['unknown_candidates']==4
    first=next(r for r in result if 'workaround' in r['comment_text'])
    assert json.loads(first['name'])==['a/repo','b/repo']
    assert json.loads(first['matched_keywords'])==['todo','workaround']
    for r in result:
        source=(root/'workflows'/r['file_hash']).read_text()
        assert r['comment_text'] in source
    assert len({r['satd_comment_id'] for r in result})==4
    assert len(list(csv.DictReader((out/'non_satd_sample.csv').open(encoding='utf-8'))))==1


def test_resume_matches_uninterrupted_and_rejects_changed_rules(tmp_path,monkeypatch):
    root=dataset(tmp_path);out=tmp_path/'resumed'
    build.run_pipeline(root,out,limit=1,workers=1)
    build.run_pipeline(root,out,resume=True,workers=1)
    full=tmp_path/'full';build.run_pipeline(root,full,workers=1)
    assert (out/'satd_comments.csv').read_bytes()==(full/'satd_comments.csv').read_bytes()
    original=build._fingerprint
    monkeypatch.setattr(build,'_fingerprint',lambda p:original(p)+'changed')
    with pytest.raises(ValueError,match='fingerprint'):
        build.run_pipeline(root,out,resume=True,workers=1)


def test_location_changes_never_change_candidate_membership(tmp_path,monkeypatch):
    import satd_location
    root=dataset(tmp_path);one=tmp_path/'one';two=tmp_path/'two'
    build.run_pipeline(root,one,workers=1)
    monkeypatch.setattr(satd_location,'locate_comment',lambda *args:('unknown','test'))
    build.run_pipeline(root,two,workers=1)
    assert {r['satd_comment_id'] for r in rows(one)}=={r['satd_comment_id'] for r in rows(two)}
    assert all(r['satd_location']=='unknown' for r in rows(two))


def test_negative_sample_is_bounded_reproducible(tmp_path):
    import sqlite3
    con=sqlite3.connect(':memory:');build._create_state(con)
    sample=[(hashlib.sha256(str(i).encode()).hexdigest(), json.dumps({'comment_text':str(i)})) for i in range(500)]
    build._save_sample(con,sample)
    assert con.execute('select count(*) from negative_sample').fetchone()[0]==384
    kept=con.execute('select priority from negative_sample order by priority').fetchall()
    build._save_sample(con,list(reversed(sample)))
    assert kept==con.execute('select priority from negative_sample order by priority').fetchall()


def test_actual_cli_with_spawn_workers(tmp_path):
    import subprocess
    import sys
    root=dataset(tmp_path);out=tmp_path/'parallel'
    result=subprocess.run([sys.executable,str(build.ROOT/'scripts/build_satd_comments.py'),
        '--dataset-dir',str(root),'--output-dir',str(out),'--workers','2'],capture_output=True,text=True,encoding='utf-8')
    assert result.returncode==0,result.stdout+result.stderr
    assert len(rows(out))==4
