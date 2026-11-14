import csv
import duckdb
from build_satd_comments import build_manifest, iter_hashes


def test_history_union_and_repository_membership(tmp_path):
    source = tmp_path / 'workflows.csv'
    with source.open('w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['repository', 'file_hash', 'previous_file_hash', 'git_change_type'])
        writer.writerows([
            ['a/repo', 'a'*64, '', 'A'], ['a/repo', 'b'*64, 'a'*64, 'M'],
            ['b/repo', 'b'*64, '', 'R'], ['a/repo', '', 'c'*64, 'D'],
            ['a/repo', 'b'*64, 'a'*64, 'M'],
        ])
    db = tmp_path / 'manifest.duckdb'
    build_manifest(source, db)
    assert list(iter_hashes(db)) == ['a'*64, 'b'*64, 'c'*64]
    with duckdb.connect(str(db)) as con:
        assert con.execute('select name from hash_repositories where file_hash=? order by name', ['b'*64]).fetchall() == [('a/repo',), ('b/repo',)]
        assert con.execute('select count(*) from hash_repositories').fetchone()[0] == 4
