"""Source-level joins only: these tests do not claim entity matching works."""
import csv
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

MODULE = Path(__file__).resolve().parents[2] / 'postprocess/history/build_occurrences.py'


def load_builder():
    assert MODULE.exists(), 'Phase-2 occurrence builder has not been implemented'
    spec = importlib.util.spec_from_file_location('phase2_occurrences', MODULE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_csv(path, rows, fields=None):
    with path.open('w', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields or list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def read_csv(path):
    with path.open(encoding='utf-8', newline='') as stream:
        return list(csv.DictReader(stream))


def h(value):
    return hashlib.sha256(value.encode()).hexdigest()


def candidate(version, suffix='', text='# TODO: remove workaround', location='jobs.test.steps[0].run'):
    return dict(satd_comment_id=h(version + suffix), name=json.dumps(['a/repo', 'b/repo']),
                file_hash=h(version), comment_text=text, normalized_text=text.lower(),
                matched_keywords='["todo"]', line_start='3' if not suffix else '8',
                line_end='3' if not suffix else '8', satd_location=location)


def change(commit, current, previous='', kind='M', repo='a/repo', uid='u1', path='x.yml', old_path='x.yml'):
    return dict(repository=repo, uid=uid, commit_hash=h(commit)[:40], committed_date=str(100 + ord(commit[0])),
                file_path=path if current else '', previous_file_path=old_path if previous else '',
                file_hash=h(current) if current else '', previous_file_hash=h(previous) if previous else '',
                git_change_type=kind, author_name='not used', author_email='not published')


def run(tmp_path, candidates, changes, statuses=None):
    cp, hp, sp = [tmp_path / name for name in ['candidates.csv', 'history.csv', 'statuses.csv']]
    write_csv(cp, candidates)
    write_csv(hp, changes)
    versions = {row[key] for row in changes for key in ['file_hash', 'previous_file_hash'] if row[key]}
    write_csv(sp, [dict(file_hash=v, status=(statuses or {}).get(v, 'ok')) for v in sorted(versions)
                   if (statuses or {}).get(v, 'ok') is not None])
    before = {p.name: p.read_bytes() for p in (cp, hp, sp)}
    output = tmp_path / 'out'
    report = load_builder().build(cp, hp, sp, output, expected_sha=hashlib.sha256(cp.read_bytes()).hexdigest())
    assert before == {p.name: p.read_bytes() for p in (cp, hp, sp)}
    return report, read_csv(output / 'satd_occurrences.csv'), read_csv(output / 'stage2_issues.csv')


def test_expands_repository_uid_commit_and_preserves_same_version_positions(tmp_path):
    c = [candidate('a'), candidate('a', 'second')]
    events = [change('a', 'a', kind='A'), change('b', 'a', 'a'),
              change('c', 'a', kind='A', uid='u2'), change('d', 'a', kind='A', repo='b/repo')]
    report, rows, _ = run(tmp_path, c, events)
    assert len(rows) == 8
    assert len({r['occurrence_id'] for r in rows}) == 8
    assert {r['satd_comment_id'] for r in rows} == {x['satd_comment_id'] for x in c}
    assert report['validation']['passed']
    assert not any('entity' in k or 'semantic_label' in k for k in rows[0])


@pytest.mark.parametrize('new_text,new_location', [
    ('# TODO: remove workaround', 'jobs.test.steps[0].run'),  # retained text
    ('# TODO: remove workaround', 'jobs.test.steps[1].run'),  # inserted step
    ('# TODO: replace temporary workaround', 'jobs.test.steps[0].run'),  # updated
    ('# TODO: remove workaround', 'jobs.deploy.steps[0].run'),  # moved
])
def test_versions_are_preserved_without_preempting_entity_matching(tmp_path, new_text, new_location):
    old, new = candidate('a'), candidate('b', text=new_text, location=new_location)
    _, rows, _ = run(tmp_path, [old, new], [change('a', 'a', kind='A'), change('b', 'b', 'a')])
    assert len(rows) == 2
    assert {r['satd_comment_id'] for r in rows} == {old['satd_comment_id'], new['satd_comment_id']}


def test_rename_deletion_and_reintroduction_keep_source_identity(tmp_path):
    changes = [change('a', 'a', kind='A'), change('b', 'a', 'a', kind='R', path='renamed.yml'),
               change('c', '', 'a', kind='D'), change('d', 'a', kind='A', uid='u2')]
    _, rows, _ = run(tmp_path, [candidate('a')], changes)
    assert len(rows) == 3
    assert not any(r['git_change_type'] == 'D' for r in rows)
    assert next(r for r in rows if r['git_change_type'] == 'R')['previous_file_path'] == 'x.yml'
    assert {r['uid'] for r in rows} == {'u1', 'u2'}


def test_problem_version_is_gap_not_absence_and_old_only_has_no_invented_commit(tmp_path):
    events = [change('a', 'a', kind='A'), change('b', 'bad', 'a'), change('c', 'c', 'bad'),
              change('d', '', 'old_only', kind='D', uid='u2')]
    report, rows, issues = run(tmp_path, [candidate('a'), candidate('bad'), candidate('c'), candidate('old_only')], events,
                              {h('bad'): 'partial'})
    assert len(rows) == 2
    assert 'problem_file' in {x['issue_type'] for x in issues}
    assert report['unmapped_candidates'] == 2
    orphans = {r['satd_comment_id']: r['reason'] for r in read_csv(tmp_path / 'out/unmapped_candidates.csv')}
    assert orphans[h('old_only')] == 'previous_side_only'
    assert orphans[h('bad')] == 'current_evidence_quarantined'
    assert not any(r['file_hash'] == h('bad') for r in rows)


def test_missing_status_excludes_only_unobserved_current_content(tmp_path):
    report, rows, issues = run(tmp_path, [candidate('a'), candidate('b')],
                              [change('a', 'a', kind='A'), change('b', 'b', 'a')], {h('a'): None})
    assert len(rows) == 1 and rows[0]['file_hash'] == h('b')
    assert report['unmapped_candidates'] == 1
    assert 'missing_file_status' in {r['issue_type'] for r in issues}


def test_duplicates_collapsed_conflicts_quarantined_repeats_and_broken_edges_reported(tmp_path):
    a = change('a', 'a', kind='A')
    events = [a, a, change('b', 'b', 'a'), change('c', 'a', 'b'),
              change('d', 'c', 'missing'), change('e', 'a', 'b'), change('e', 'c', 'b')]
    report, rows, issues = run(tmp_path, [candidate('a'), candidate('b'), candidate('c')], events)
    assert len(rows) == 4
    assert report['duplicate_source_rows'] == 1
    assert next(r for r in rows if r['commit_hash'] == h('a')[:40])['source_multiplicity'] == '2'
    types = {x['issue_type'] for x in issues}
    assert {'duplicate_source_record', 'conflicting_commit_record', 'repeated_content',
            'missing_predecessor', 'ambiguous_content_successor'} <= types


def test_missing_rename_side_multiline_text_unknown_location_and_name_mismatch(tmp_path):
    c = candidate('a', text='# TODO: "fix", later\n# keep evidence', location='unknown')
    c['name'] = '["other/repo"]'
    _, rows, issues = run(tmp_path, [c], [change('a', 'a', kind='R')])
    assert len(rows) == 1
    assert rows[0]['comment_text'] == c['comment_text']
    assert rows[0]['satd_location'] == 'unknown'
    assert {'missing_previous_hash', 'repository_membership_mismatch'} <= {i['issue_type'] for i in issues}


def test_wrong_frozen_digest_and_output_overwrite_are_rejected(tmp_path):
    run(tmp_path, [candidate('a')], [change('a', 'a', kind='A')])
    builder = load_builder()
    args = [tmp_path / n for n in ['candidates.csv', 'history.csv', 'statuses.csv']]
    with pytest.raises(ValueError, match='SHA'):
        builder.build(*args, tmp_path / 'bad', expected_sha='0' * 64)
    with pytest.raises(FileExistsError):
        builder.build(*args, tmp_path / 'out')
    builder.build(*args, tmp_path / 'second')
    assert (tmp_path / 'out/satd_occurrences.csv').read_bytes() == (tmp_path / 'second/satd_occurrences.csv').read_bytes()


def test_independent_export_verification_detects_tampering(tmp_path):
    run(tmp_path, [candidate('a')], [change('a', 'a', kind='A')])
    path = MODULE.parent / 'verify_occurrences.py'
    assert path.exists(), 'Independent export validator not implemented'
    spec = importlib.util.spec_from_file_location('phase2_verify', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    result = module.verify(tmp_path / 'out')
    assert result['passed'] and result['independent_occurrence_rows'] == 1
    output = tmp_path / 'out/satd_occurrences.csv'
    output.write_text(output.read_text(encoding='utf-8').replace('workaround', 'altered'), encoding='utf-8')
    with pytest.raises(AssertionError, match='checksum'):
        module.verify(tmp_path / 'out')
