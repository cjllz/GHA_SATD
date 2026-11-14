"""Re-read exported CSV and original inputs; never trust the build's DuckDB cache."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / '.deps'))
import duckdb


def sha(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            value.update(chunk)
    return value.hexdigest()


def verify(output, *, input_root=None):
    output = Path(output)
    report = json.loads((output / 'stage2_validation_report.json').read_text(encoding='utf-8'))
    manifest = json.loads((output / 'input_manifest.json').read_text(encoding='utf-8'))
    def resolve(original):
        path = Path(original)
        if input_root is None:
            return path
        # Published manifests are repo-relative; local manifests have absolute paths.
        normalized = original.replace('\\', '/')
        if ':/Desktop/dataset/' in normalized:
            normalized = normalized.split(':/Desktop/dataset/', 1)[1]
        return Path(input_root) / normalized
    for name, meta in manifest.items():
        assert sha(resolve(name)) == meta['sha256'], f'Input checksum mismatch: {name}'
    for name, meta in report['outputs'].items():
        assert sha(output / name) == meta['sha256'], f'Output checksum mismatch: {name}'
    # Build's manifest insertion order is candidates, workflow metadata, statuses,
    # followed by frozen code. This order is part of input_manifest v1.
    candidates, history, statuses = [resolve(name) for name in list(manifest)[:3]]
    db = duckdb.connect()
    db.execute("SET memory_limit='2GB'")
    db.execute('SET threads=4')
    try:
        db.execute('CREATE TABLE c AS SELECT * FROM read_csv(?,all_varchar=true)', [str(candidates)])
        db.execute('CREATE TABLE s AS SELECT * FROM read_csv(?,all_varchar=true)', [str(statuses)])
        db.execute('CREATE TABLE o AS SELECT * FROM read_csv(?,all_varchar=true)', [str(output / 'satd_occurrences.csv')])
        db.execute('''CREATE TABLE h AS SELECT DISTINCT
            coalesce(repository,'') repository,coalesce(uid,'') uid,coalesce(commit_hash,'') commit_hash,
            coalesce(committed_date,'') committed_date,coalesce(file_hash,'') file_hash,
            coalesce(previous_file_hash,'') previous_file_hash,coalesce(file_path,'') file_path,
            coalesce(previous_file_path,'') previous_file_path,coalesce(git_change_type,'') git_change_type
            FROM read_csv(?,all_varchar=true)''', [str(history)])
        db.execute('''CREATE TABLE unique_commits AS SELECT repository,uid,commit_hash FROM h
            GROUP BY repository,uid,commit_hash HAVING count(*)=1''')
        db.execute('''CREATE TABLE expected AS SELECT c.satd_comment_id,h.repository,h.uid,h.commit_hash,
            h.committed_date,h.file_path,h.previous_file_path,h.file_hash,h.previous_file_hash,h.git_change_type,
            c.comment_text,c.normalized_text,c.matched_keywords,c.line_start,c.line_end,c.satd_location
            FROM h JOIN unique_commits USING(repository,uid,commit_hash)
            JOIN s ON h.file_hash=s.file_hash JOIN c ON h.file_hash=c.file_hash
            WHERE h.repository<>'' AND h.uid<>'' AND h.commit_hash<>''
              AND h.git_change_type IN ('A','M','R') AND s.status='ok'
              AND regexp_full_match(h.file_hash,'[0-9a-f]{64}')''')
        columns = [d[0] for d in db.execute('SELECT * FROM expected LIMIT 0').description]
        # CSV encodes empty strings as blanks, which read_csv reads as NULL.
        actual = ','.join(f"coalesce({col},'') AS {col}" for col in columns)
        expected = ','.join(f"coalesce({col},'') AS {col}" for col in columns)
        missing = db.execute(f'SELECT count(*) FROM (SELECT {expected} FROM expected EXCEPT ALL SELECT {actual} FROM o)').fetchone()[0]
        extra = db.execute(f'SELECT count(*) FROM (SELECT {actual} FROM o EXCEPT ALL SELECT {expected} FROM expected)').fetchone()[0]
        duplicate_ids = db.execute('SELECT count(*)-count(DISTINCT occurrence_id) FROM o').fetchone()[0]
        bad_ids = db.execute('''SELECT count(*) FROM o WHERE occurrence_id <>
            sha256(to_json(list_value('satd-occurrence-v1',repository,uid,commit_hash,satd_comment_id)))''').fetchone()[0]
        counts = db.execute('SELECT (SELECT count(*) FROM o),(SELECT count(*) FROM expected)').fetchone()
        assert missing == extra == duplicate_ids == bad_ids == 0, (missing, extra, duplicate_ids, bad_ids)
        assert counts[0] == counts[1] == report['occurrences'], counts
        result = {'passed': True, 'independent_occurrence_rows': counts[1],
                  'missing_rows': missing, 'extra_rows': extra, 'duplicate_ids': duplicate_ids,
                  'invalid_ids': bad_ids, 'all_input_and_output_checksums_match': True,
                  'method': 'Fresh CSV reads, DISTINCT version metadata, unique commit groups, bidirectional EXCEPT ALL over all 16 research fields; no build database used'}
        (output / 'independent_validation.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
        return result
    finally:
        db.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--input-root', type=Path, help='Root for portable relative input manifest')
    args = parser.parse_args()
    print(json.dumps(verify(args.output, input_root=args.input_root), indent=2))
