"""Apply the user's whole-file readability exclusion to a completed checkpoint.

Kept separate from the extraction executable so an ongoing scan remains stable.
Only status=ok files are eligible; location diagnostics do not change that status.
"""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'utils'))
from build_satd_comments import FIELDS, SAMPLE_FIELDS


def export_readable(con, output_dir, raw_report):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    def write_csv(name, fields, rows):
        dest = output_dir / name
        temporary = dest.with_suffix('.csv.tmp')
        with temporary.open('w', encoding='utf-8', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(fields)
            writer.writerows(rows)
        temporary.replace(dest)

    invalid = con.execute("SELECT count(*) FROM files WHERE status NOT IN ('ok','partial','failed') OR status IS NULL").fetchone()[0]
    if invalid:
        raise ValueError('Unexpected checkpoint file status')
    counts = con.execute("SELECT count(*),coalesce(sum(comments),0),coalesce(sum(hits),0),coalesce(sum(located),0),coalesce(sum(unknown),0) FROM files WHERE status='ok'").fetchone()
    total = con.execute('SELECT count(*) FROM files').fetchone()[0]
    raw_hits = con.execute('SELECT count(*) FROM candidates').fetchone()[0]
    rows = con.execute("SELECT count(*) FROM candidates c JOIN files f USING(file_hash) WHERE f.status='ok'").fetchone()[0]
    assert total == raw_report['processed_hashes']
    assert counts[2] == rows == counts[3] + counts[4]
    write_csv('satd_comments.csv', FIELDS, con.execute("""
        SELECT c.* FROM candidates c JOIN files f USING(file_hash)
        WHERE f.status='ok'
        ORDER BY c.file_hash,c.line_start,c.line_end,c.satd_comment_id
    """))
    samples = []
    for (payload,) in con.execute('SELECT payload FROM negative_sample ORDER BY priority'):
        row = json.loads(payload)
        status = con.execute('SELECT status FROM files WHERE file_hash=?', (row['file_hash'],)).fetchone()
        if status and status[0] == 'ok':
            samples.append(row)
    write_csv('non_satd_sample.csv', SAMPLE_FIELDS, ([row[k] for k in SAMPLE_FIELDS] for row in samples))
    report = dict(raw_report)
    report.update({
        'selection_policy': 'exclude_entire_file_unless_status_ok_v1',
        'selection_policy_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'eligible_file_hashes': counts[0],
        'excluded_file_hashes': total - counts[0],
        'raw_extracted_comments': raw_report.get('raw_extracted_comments', raw_report['extracted_comments']),
        'extracted_comments': counts[1],
        'raw_keyword_candidates': raw_hits,
        'excluded_keyword_candidates': raw_hits - rows,
        'keyword_candidates': rows,
        'output_rows': rows,
        'located_candidates': counts[3],
        'unknown_candidates': counts[4],
        'negative_sample_size': len(samples),
        'negative_sample_policy': 'Seeded global bottom-384 sample restricted to eligible files, without replenishment.',
        'all_keyword_candidates_retained': rows == raw_hits,
        'all_eligible_keyword_candidates_retained': True,
        'limitations': [
            'Keyword candidates are not human-validated SATD.',
            'Any extraction/parser problem excludes the entire file, including otherwise readable comments.',
            'Unknown and coarse locations in otherwise eligible files remain in the main table.',
            'Negative sample excludes problem files; its size can be below 384. Human review is pending; no recall claim is made.',
            'File status and issue counts cover the full scanned manifest, including excluded files.'
        ],
    })
    temporary = output_dir / 'satd_build_report.json.tmp'
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(output_dir / 'satd_build_report.json')
    return report


if __name__ == '__main__':
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--state', type=Path, required=True)
    cli.add_argument('--output-dir', type=Path, required=True)
    args = cli.parse_args()
    with sqlite3.connect(args.state.resolve().as_uri() + '?mode=ro', uri=True) as con:
        report = json.loads((args.output_dir / 'satd_build_report.json').read_text(encoding='utf-8'))
        print(json.dumps(export_readable(con, args.output_dir, report), ensure_ascii=False))
