import csv
import importlib.util
from pathlib import Path
import pytest

MODULE = Path(__file__).resolve().parents[2] / 'postprocess/history/build_latest_snapshot.py'

def write(path, rows):
    with path.open('w',encoding='utf-8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)

def version(uid, n, current, previous='', kind='M', status='ok', repo='a/r', date='100'):
    return dict(version_id=f'{repo}:{uid}:{n}',repository=repo,uid=uid,commit_hash=f'commit{n}',
                committed_date=date,file_path=f'{uid}.yml' if current else '',previous_file_path=f'{uid}.yml' if previous else '',
                file_hash=current,previous_file_hash=previous,git_change_type=kind,source_row_number=str(n),
                source_multiplicity='1',commit_variant_count='1',current_file_status=status,previous_file_status='ok')

def run(tmp, versions, without_candidates=()):
    assert MODULE.exists(), 'Latest snapshot builder not implemented'
    spec=importlib.util.spec_from_file_location('latest',MODULE);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    v=tmp/'versions.csv';o=tmp/'occurrences.csv';write(v,versions)
    # Two candidates per version: they must never collapse just because text is equal.
    occurrences=[dict(occurrence_id=r['version_id']+f':{k}',version_id=r['version_id'],satd_comment_id=r['file_hash']+f':{k}',
                      repository=r['repository'],uid=r['uid'],file_hash=r['file_hash'],comment_text='# TODO',
                      normalized_text='todo',satd_location=f'jobs.x.steps[{k}].run')
                 for r in versions if r['current_file_status']=='ok' and r['file_hash']
                 and r['version_id'] not in without_candidates for k in range(2)]
    write(o,occurrences)
    return m.build(v,o,tmp/'result')

def read(tmp,name):
    with (tmp/'result'/name).open(encoding='utf-8',newline='') as f:return list(csv.DictReader(f))

def test_source_order_beats_clock_and_preserves_positions_and_repositories(tmp_path):
    r=run(tmp_path,[version('u',2,'new','old',date='10'),version('u',3,'old',kind='A',date='20'),
                    version('u',4,'new',kind='A',repo='b/r')])
    assert r['candidate_rows']==4
    assert r['eligible_workflows']==2
    assert r['timestamp_disagreement_workflows']==1
    assert {x['file_hash'] for x in read(tmp_path,'latest_satd_comments.csv')}=={'new'}

def test_deleted_bad_and_renamed_out_do_not_fall_back(tmp_path):
    r=run(tmp_path,[version('deleted',2,'','old','D','missing'),version('deleted',3,'old',kind='A'),
                    version('bad',4,'bad','old',status='partial'),version('bad',5,'old',kind='A'),
                    version('out',6,'','old','R','missing'),version('out',7,'old',kind='A'),
                    version('keep',8,'yes',kind='A')])
    assert r['candidate_rows']==2
    assert r['selection_counts']['deleted']==1
    assert r['selection_counts']['problem_latest_file']==1
    assert r['selection_counts']['renamed_out_of_workflow_scope']==1
    assert read(tmp_path,'latest_satd_comments.csv')[0]['uid']=='keep'

def test_broken_chain_and_conflicting_commit_are_quarantined(tmp_path):
    bad=version('conflict',4,'x',kind='A');bad['commit_variant_count']='2'
    r=run(tmp_path,[version('broken',2,'a','missing'),version('broken',3,'b',kind='A'),bad,
                    version('keep',5,'a',kind='A')])
    assert r['eligible_workflows']==1
    assert r['selection_counts']['ambiguous_history']==1
    assert r['selection_counts']['conflicting_latest_commit']==1

def test_same_timestamp_ordered_rename_and_recreated_uid(tmp_path):
    newest=version('renamed',2,'b','a','R');newest['file_path']='renamed-new.yml'
    r=run(tmp_path,[newest,version('renamed',3,'a',kind='A'),
                    version('old-life',4,'','x','D','missing'),version('old-life',5,'x',kind='A'),
                    version('new-life',6,'x',kind='A')])
    assert r['eligible_workflows']==2 and r['candidate_rows']==4
    assert 'old-life' not in {x['uid'] for x in read(tmp_path,'latest_satd_comments.csv')}

def test_live_path_collision_excluded_and_outputs_not_overwritten(tmp_path):
    a=version('a',2,'x',kind='A');b=version('b',3,'y',kind='A');b['file_path']=a['file_path']
    r=run(tmp_path,[a,b])
    assert r['candidate_rows']==0 and r['selection_counts']['ambiguous_live_path']==2
    with pytest.raises(FileExistsError):run(tmp_path,[a,b])

def test_latest_without_candidates_is_kept_without_resurrecting_old_comments(tmp_path):
    latest=version('u',2,'new','old');old=version('u',3,'old',kind='A')
    r=run(tmp_path,[latest,old],without_candidates=[latest['version_id']])
    assert r['eligible_workflows']==1 and r['candidate_rows']==0
    assert read(tmp_path,'latest_workflows.csv')[0]['candidate_count']=='0'
    assert read(tmp_path,'latest_satd_comments.csv')==[]
