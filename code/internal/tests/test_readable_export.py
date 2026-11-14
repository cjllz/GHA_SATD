import csv
import importlib.util
import json
from pathlib import Path
import sqlite3

import build_satd_comments as build


def load_exporter():
    path = build.ROOT / 'postprocess/export_readable_satd.py'
    spec = importlib.util.spec_from_file_location('readable_export', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_whole_problem_file_excluded_but_good_unknown_kept(tmp_path):
    con = sqlite3.connect(':memory:')
    build._create_state(con)
    con.executemany('INSERT INTO files VALUES (?,?,?,?,?,?)', [
        ('good', 'ok', 3, 2, 1, 1),
        ('broken', 'partial', 3, 2, 2, 0),
        ('missing', 'failed', 0, 0, 0, 0),
    ])
    for identity, file_hash, location in [
        ('a', 'good', 'jobs'), ('b', 'good', 'unknown'),
        ('c', 'broken', 'jobs'), ('d', 'broken', 'on'),
    ]:
        con.execute('INSERT INTO candidates VALUES (?,?,?,?,?,?,?,?,?)',
                    (identity, '["a/repo"]', file_hash, '# TODO', 'todo', '["todo"]', 1, 1, location))
    for identity, file_hash in [('e', 'good'), ('f', 'broken')]:
        row = dict(zip(build.SAMPLE_FIELDS, [identity, '["a/repo"]', file_hash, '# ordinary', 'ordinary', 2, 2]))
        con.execute('INSERT INTO negative_sample VALUES (?,?)', (identity, json.dumps(row)))
    raw = {'scope': 'full', 'manifest_hashes': 3, 'processed_hashes': 3,
           'keyword_candidates': 4, 'output_rows': 4, 'located_candidates': 3,
           'unknown_candidates': 1, 'extracted_comments': 6, 'negative_sample_size': 2,
           'fingerprint': 'original-extractor', 'all_keyword_candidates_retained': True,
           'limitations': [], 'file_status_counts': {'ok': 1, 'partial': 1, 'failed': 1}}
    result = load_exporter().export_readable(con, tmp_path, raw)
    with (tmp_path / 'satd_comments.csv').open(encoding='utf-8', newline='') as f:
        reader = csv.DictReader(f)
        assert reader.fieldnames == build.FIELDS
        rows = list(reader)
    assert {r['satd_comment_id'] for r in rows} == {'a', 'b'}
    assert result['keyword_candidates'] == result['output_rows'] == 2
    assert result['unknown_candidates'] == 1
    assert result['excluded_file_hashes'] == 2
    assert result['excluded_keyword_candidates'] == 2
    assert result['raw_keyword_candidates'] == 4
    assert result['eligible_file_hashes'] == 1
    assert result['extracted_comments'] == 3
    assert result['all_keyword_candidates_retained'] is False
    assert result['all_eligible_keyword_candidates_retained'] is True
    with (tmp_path / 'non_satd_sample.csv').open(encoding='utf-8', newline='') as f:
        assert [r['file_hash'] for r in csv.DictReader(f)] == ['good']
    assert result['negative_sample_size'] == 1
    assert con.execute('SELECT count(*) FROM candidates').fetchone()[0] == 4
    assert raw['keyword_candidates'] == 4
