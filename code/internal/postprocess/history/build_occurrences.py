"""Join frozen content candidates to observed workflow changes. No entity inference.

Run with --help. Source files and the phase-1 checkpoint are opened read-only.
Only explicit post-change file_hash states create occurrences. The before side
is retained in workflow_versions; a deletion never creates a post-change row.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / '.deps'))
import duckdb

FROZEN_SHA = '44b642822f3d44cce8c2d2b331699aebd320e08deaad1bfa43ccca0e554a6890'
HISTORY_FIELDS = ['repository', 'uid', 'commit_hash', 'committed_date', 'file_path',
                  'previous_file_path', 'file_hash', 'previous_file_hash', 'git_change_type']
COMMENT_FIELDS = ['satd_comment_id', 'name', 'file_hash', 'comment_text', 'normalized_text',
                  'matched_keywords', 'line_start', 'line_end', 'satd_location']


def sha_file(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def sql_string(value):
    return "'" + str(value).replace("'", "''") + "'"


def snapshot(paths):
    return {str(Path(p).resolve()): {'sha256': sha_file(p), 'bytes': Path(p).stat().st_size}
            for p in paths}


def export_status(state, target):
    """Export only the reproducibility-relevant status table, never candidate payloads."""
    target = Path(target)
    if target.exists():
        raise FileExistsError(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(Path(state).resolve().as_uri() + '?mode=ro', uri=True) as db:
        with gzip.open(target, 'wt', encoding='utf-8', newline='') as stream:
            writer = csv.writer(stream)
            writer.writerow(['file_hash', 'status'])
            writer.writerows(db.execute('SELECT file_hash,status FROM files ORDER BY file_hash'))


def build(candidates, history, statuses, output, *, expected_sha=None, freeze_paths=()):
    candidates, history, statuses, output = map(Path, (candidates, history, statuses, output))
    started = time.monotonic()
    # Check the external freeze contract before creating any results.
    if expected_sha and sha_file(candidates) != expected_sha:
        raise ValueError('Candidate SHA-256 does not match the frozen input')
    if output.exists() and any(output.iterdir()):
        raise FileExistsError(f'Refusing to overwrite nonempty output directory: {output}')
    output.mkdir(parents=True, exist_ok=True)
    frozen = snapshot([candidates, history, statuses, *freeze_paths])
    (output / 'input_manifest.json').write_text(json.dumps(frozen, indent=2), encoding='utf-8')
    db = duckdb.connect(str(output / 'occurrences.duckdb'))
    db.execute("SET memory_limit='2GB'")
    db.execute('SET threads=4')
    db.execute('SET preserve_insertion_order=true')
    db.execute('SET temp_directory=' + sql_string(output / '.duckdb_tmp'))

    def scalar(sql):
        return db.execute(sql).fetchone()[0]

    def log(message):
        print(message, flush=True)
        with (output / 'build.log').open('a', encoding='utf-8') as stream:
            stream.write(message + '\n')

    def export(query, name):
        compression = ", COMPRESSION GZIP" if name.endswith('.gz') else ''
        db.execute(f'COPY ({query}) TO {sql_string(output / name)} (HEADER, FORMAT CSV{compression})')

    def issue(kind, query):
        # Each query returns version_id and details. The full version record is joined on export.
        db.execute(f'INSERT INTO issues SELECT {sql_string(kind)}, * FROM ({query})')

    try:
        log('Loading frozen candidates and file statuses')
        cols = ','.join(COMMENT_FIELDS)
        db.execute(f'CREATE TABLE candidates AS SELECT {cols} FROM read_csv(?, all_varchar=true)', [str(candidates)])
        db.execute('CREATE TABLE file_status AS SELECT file_hash,status FROM read_csv(?, all_varchar=true)', [str(statuses)])
        if scalar('SELECT count(*)-count(DISTINCT satd_comment_id) FROM candidates'):
            raise ValueError('Duplicate satd_comment_id in frozen input')
        if scalar('SELECT count(*)-count(DISTINCT file_hash) FROM file_status'):
            raise ValueError('Duplicate file status')
        if scalar("SELECT count(*) FROM candidates WHERE satd_comment_id IS NULL OR file_hash IS NULL OR comment_text IS NULL OR normalized_text IS NULL OR NOT json_valid(name) OR NOT json_valid(matched_keywords)"):
            raise ValueError('Invalid candidate identity, text or JSON')
        # Original line and text fields remain strings, avoiding any normalization of evidence.
        log('Reading workflow source rows and preserving logical CSV row ordinals')
        coalesced = ','.join(f"coalesce({f},'') AS {f}" for f in HISTORY_FIELDS)
        db.execute(f'''CREATE TABLE history_rows AS SELECT row_number() OVER () + 1 AS source_row_number,
                       {coalesced} FROM read_csv(?, all_varchar=true, parallel=false)''', [str(history)])
        source_rows = scalar('SELECT count(*) FROM history_rows')
        fields = ','.join(HISTORY_FIELDS)
        values = ','.join(HISTORY_FIELDS)
        db.execute(f'''CREATE TABLE versions_base AS SELECT
            sha256(to_json(list_value('workflow-version-v1',{values}))) AS version_id,
            {fields}, min(source_row_number) AS source_row_number, count(*) AS source_multiplicity
            FROM history_rows GROUP BY {fields}''')
        db.execute('''CREATE TABLE versions AS SELECT v.*,
            count(*) OVER (PARTITION BY repository,uid,commit_hash) AS commit_variant_count,
            coalesce(cs.status,'missing') AS current_file_status,
            coalesce(ps.status,'missing') AS previous_file_status
            FROM versions_base v LEFT JOIN file_status cs ON v.file_hash=cs.file_hash
            LEFT JOIN file_status ps ON v.previous_file_hash=ps.file_hash''')
        db.execute('DROP TABLE versions_base')
        db.execute('CREATE TABLE issues(issue_type VARCHAR, version_id VARCHAR, details VARCHAR)')
        log('Auditing workflow version evidence (no temporal parent inference)')
        issue('duplicate_source_record', "SELECT version_id, 'multiplicity=' || source_multiplicity FROM versions WHERE source_multiplicity>1")
        issue('conflicting_commit_record', "SELECT version_id, 'variants=' || commit_variant_count FROM versions WHERE commit_variant_count>1")
        issue('missing_identity', "SELECT version_id, 'repository, uid or commit missing' FROM versions WHERE repository='' OR uid='' OR commit_hash=''")
        issue('invalid_change_type', "SELECT version_id, git_change_type FROM versions WHERE git_change_type NOT IN ('A','M','R','D')")
        issue('invalid_timestamp', "SELECT version_id, committed_date FROM versions WHERE try_cast(committed_date AS BIGINT) IS NULL")
        issue('missing_current_hash', "SELECT version_id, git_change_type FROM versions WHERE git_change_type IN ('A','M','R') AND file_hash=''")
        issue('missing_previous_hash', "SELECT version_id, git_change_type FROM versions WHERE git_change_type IN ('M','R','D') AND previous_file_hash=''")
        issue('unexpected_hash_side', "SELECT version_id, git_change_type FROM versions WHERE (git_change_type='A' AND previous_file_hash<>'') OR (git_change_type='D' AND file_hash<>'')")
        issue('missing_current_path', "SELECT version_id, 'current hash exists but path is empty' FROM versions WHERE file_hash<>'' AND file_path=''")
        for side, field in [('current', 'file_hash'), ('previous', 'previous_file_hash')]:
            issue('problem_file', f"SELECT version_id, '{side}:' || {field} || ':' || {side}_file_status FROM versions WHERE {field}<>'' AND {side}_file_status NOT IN ('ok','missing')")
            issue('missing_file_status', f"SELECT version_id, '{side}:' || {field} FROM versions WHERE {field}<>'' AND {side}_file_status='missing'")
            issue('invalid_content_hash', f"SELECT version_id, '{side}:' || {field} FROM versions WHERE {field}<>'' AND NOT regexp_full_match({field}, '[0-9a-f]{{64}}')")
        issue('missing_predecessor', '''SELECT v.version_id, v.previous_file_hash FROM versions v
            WHERE v.previous_file_hash<>'' AND NOT EXISTS (
              SELECT 1 FROM versions p WHERE p.repository=v.repository AND p.uid=v.uid
              AND p.file_hash=v.previous_file_hash AND p.version_id<>v.version_id AND p.git_change_type<>'D')''')
        issue('repeated_content', '''SELECT version_id, 'content appearances=' || n FROM
            (SELECT *, count(*) OVER (PARTITION BY repository,uid,file_hash) n FROM versions WHERE file_hash<>'') WHERE n>1''')
        issue('repeated_transition', '''SELECT version_id, 'content edge appearances=' || n FROM
            (SELECT *, count(*) OVER (PARTITION BY repository,uid,previous_file_hash,file_hash) n FROM versions) WHERE n>1''')
        issue('ambiguous_content_successor', '''SELECT version_id, 'distinct successor contents=' || n FROM
            (SELECT *, count(DISTINCT file_hash) OVER (PARTITION BY repository,uid,previous_file_hash) n
             FROM versions WHERE previous_file_hash<>'') WHERE n>1''')
        issue('ambiguous_content_predecessor', '''SELECT version_id, 'distinct predecessor contents=' || n FROM
            (SELECT *, count(DISTINCT previous_file_hash) OVER (PARTITION BY repository,uid,file_hash) n
             FROM versions WHERE file_hash<>'') WHERE n>1''')
        db.execute('''CREATE TABLE eligible_versions AS SELECT * FROM versions WHERE
            repository<>'' AND uid<>'' AND commit_hash<>'' AND commit_variant_count=1
            AND git_change_type IN ('A','M','R') AND file_hash<>'' AND current_file_status='ok'
            AND regexp_full_match(file_hash,'[0-9a-f]{64}')''')
        log('Joining post-change content to candidates')
        db.execute('''CREATE TABLE occurrences AS SELECT
            sha256(to_json(list_value('satd-occurrence-v1', v.repository,v.uid,v.commit_hash,c.satd_comment_id))) AS occurrence_id,
            c.satd_comment_id, v.repository,v.uid,v.commit_hash,v.committed_date,
            v.file_path,v.previous_file_path,v.file_hash,v.previous_file_hash,v.git_change_type,
            c.comment_text,c.normalized_text,c.matched_keywords,c.line_start,c.line_end,c.satd_location,
            v.version_id,v.source_row_number,v.source_multiplicity
            FROM eligible_versions v JOIN candidates c ON v.file_hash=c.file_hash''')
        issue('repository_membership_mismatch', '''SELECT o.version_id, o.satd_comment_id FROM occurrences o
            JOIN candidates c USING(satd_comment_id)
            WHERE NOT list_contains(from_json(c.name,'["VARCHAR"]'),o.repository)''')
        db.execute('''CREATE TABLE unmapped AS SELECT c.satd_comment_id,c.file_hash,
            CASE WHEN EXISTS(SELECT 1 FROM versions v WHERE v.file_hash=c.file_hash) THEN 'current_evidence_quarantined'
                 WHEN EXISTS(SELECT 1 FROM versions v WHERE v.previous_file_hash=c.file_hash) THEN 'previous_side_only'
                 ELSE 'no_history_evidence' END AS reason
            FROM candidates c WHERE NOT EXISTS (SELECT 1 FROM occurrences o WHERE o.satd_comment_id=c.satd_comment_id)''')
        db.execute('''CREATE VIEW issue_export AS SELECT
            sha256(to_json(list_value('stage2-issue-v1',i.issue_type,i.version_id,i.details))) AS issue_id,
            i.issue_type,i.version_id,v.repository,v.uid,v.commit_hash,v.committed_date,
            v.file_hash,v.previous_file_hash,v.git_change_type,v.source_row_number,i.details
            FROM issues i JOIN versions v USING(version_id)''')
        log('Checking join cardinality and frozen evidence')
        occurrence_count = scalar('SELECT count(*) FROM occurrences')
        expected_count = scalar('''SELECT coalesce(sum(n),0)::BIGINT FROM eligible_versions v JOIN
            (SELECT file_hash,count(*) n FROM candidates GROUP BY file_hash) c USING(file_hash)''')
        failures = {
            'duplicate_occurrence_ids': scalar('SELECT count(*)-count(DISTINCT occurrence_id) FROM occurrences'),
            'join_count_difference': occurrence_count - expected_count,
            'deletion_after_state_rows': scalar("SELECT count(*) FROM occurrences WHERE git_change_type='D'"),
            'missing_version_foreign_keys': scalar('SELECT count(*) FROM occurrences o ANTI JOIN versions v USING(version_id)'),
            'missing_candidate_foreign_keys': scalar('SELECT count(*) FROM occurrences o ANTI JOIN candidates c USING(satd_comment_id)'),
            'non_ok_occurrences': scalar("SELECT count(*) FROM occurrences o JOIN versions v USING(version_id) WHERE v.current_file_status<>'ok'"),
            'altered_candidate_fields': scalar('''SELECT count(*) FROM occurrences o JOIN candidates c USING(satd_comment_id)
                WHERE o.file_hash IS DISTINCT FROM c.file_hash OR o.comment_text IS DISTINCT FROM c.comment_text
                OR o.normalized_text IS DISTINCT FROM c.normalized_text OR o.matched_keywords IS DISTINCT FROM c.matched_keywords
                OR o.line_start IS DISTINCT FROM c.line_start OR o.line_end IS DISTINCT FROM c.line_end
                OR o.satd_location IS DISTINCT FROM c.satd_location'''),
        }
        if any(failures.values()):
            raise AssertionError(f'Join validation failed: {failures}')
        log(f'Exporting {occurrence_count:,} occurrences and version/issue evidence')
        export('SELECT * FROM occurrences ORDER BY occurrence_id', 'satd_occurrences.csv')
        export('SELECT * FROM versions ORDER BY version_id', 'workflow_versions.csv.gz')
        export('SELECT * FROM issue_export ORDER BY issue_id', 'stage2_issues.csv')
        export('SELECT * FROM unmapped ORDER BY satd_comment_id', 'unmapped_candidates.csv')
        # Round-robin across change type and known/unknown location, not a statistical sample.
        export('''SELECT * EXCLUDE(sample_rank) FROM (
            SELECT *,row_number() OVER(PARTITION BY git_change_type,satd_location='unknown' ORDER BY occurrence_id) sample_rank
            FROM occurrences) ORDER BY sample_rank,git_change_type,satd_location='unknown',occurrence_id LIMIT 20''', 'occurrence_examples.csv')
        report = {
            'stage': 'stage2_step1_occurrence_linkage', 'stop_point': 1,
            'candidate_rows': scalar('SELECT count(*) FROM candidates'), 'history_source_rows': source_rows,
            'unique_version_records': scalar('SELECT count(*) FROM versions'),
            'duplicate_source_rows': source_rows - scalar('SELECT count(*) FROM versions'),
            'occurrences': occurrence_count, 'independent_join_expected_count': expected_count,
            'mapped_candidates': scalar('SELECT count(DISTINCT satd_comment_id) FROM occurrences'),
            'unmapped_candidates': scalar('SELECT count(*) FROM unmapped'),
            'repositories_with_occurrences': scalar('SELECT count(DISTINCT repository) FROM occurrences'),
            'workflow_lifecycles_with_occurrences': scalar('SELECT count(*) FROM (SELECT DISTINCT repository,uid FROM occurrences)'),
            'commits_with_occurrences': scalar('SELECT count(*) FROM (SELECT DISTINCT repository,commit_hash FROM occurrences)'),
            'occurrence_change_types': dict(db.execute('SELECT git_change_type,count(*) FROM occurrences GROUP BY 1 ORDER BY 1').fetchall()),
            'source_change_types': dict(db.execute('SELECT git_change_type,count(*) FROM history_rows GROUP BY 1 ORDER BY 1').fetchall()),
            'issues_by_type': dict(db.execute('SELECT issue_type,count(*) FROM issues GROUP BY 1 ORDER BY 1').fetchall()),
            'unmapped_reasons': dict(db.execute('SELECT reason,count(*) FROM unmapped GROUP BY 1 ORDER BY 1').fetchall()),
            'validation': {'passed': True, **failures},
            'semantic_evaluation': {'status': 'not_run', 'confusion_matrix': None, 'precision': None, 'recall': None, 'f1': None},
            'entity_matching': 'not_implemented_pending_stop_point_1',
            'branch_filter_applied': False, 'semantic_labels_propagated': False,
            'occurrence_semantics': 'explicit post-change states at recorded workflow-changing commits only',
            'limitations': [
                'Workflow metadata contains file transitions, not Git commit parent identifiers.',
                'Before-only content is not assigned the current commit timestamp.',
                'Unchanged workflow states at commits absent from workflows.csv are not reconstructed.',
                'Repeated hashes/content edges are diagnostic ambiguity, not proof of ancestry or reversion.',
                'Extraction gaps are not evidence of removal or repayment.',
                'No SATD entities, semantic labels, lifetimes or repayment have been inferred.'
            ],
            'runtime': {'python': sys.version.split()[0], 'duckdb': duckdb.__version__},
        }
        after = snapshot([candidates, history, statuses, *freeze_paths])
        if frozen != after:
            raise AssertionError('Frozen inputs changed during build')
        report['validation']['frozen_inputs_unchanged'] = True
        report['elapsed_seconds'] = round(time.monotonic() - started, 3)
        report['outputs'] = {p.name: {'sha256': sha_file(p), 'bytes': p.stat().st_size}
                             for p in output.iterdir() if p.name.endswith(('.csv', '.csv.gz'))}
        (output / 'stage2_validation_report.json').write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')
        db.execute('CHECKPOINT')
        log('Stop point 1 reached. Entity matching and semantic review have not been run.')
        return report
    finally:
        db.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidates', type=Path, default=ROOT / 'output/satd_comments.csv')
    parser.add_argument('--history', type=Path, default=ROOT / 'workflows.csv')
    parser.add_argument('--statuses', type=Path, help='Exported file_hash,status CSV, optionally gzip')
    parser.add_argument('--state', type=Path, help='Phase-1 checkpoint; reads only files table')
    parser.add_argument('--output', type=Path, default=ROOT / 'output/stage2/run')
    parser.add_argument('--expected-sha', default=FROZEN_SHA)
    args = parser.parse_args()
    if bool(args.statuses) == bool(args.state):
        parser.error('Provide exactly one of --statuses or --state')
    if args.state:
        args.statuses = args.output.parent / 'file_status.csv.gz'
        export_status(args.state, args.statuses)
    frozen_code = sorted((ROOT / 'scripts').glob('*.py')) + sorted((ROOT / 'scripts').glob('*.ps1'))
    frozen_code += [ROOT / 'config/keywords_list.txt', ROOT / 'postprocess/export_readable_satd.py']
    result = build(args.candidates, args.history, args.statuses, args.output,
                   expected_sha=args.expected_sha, freeze_paths=frozen_code)
    print(json.dumps({k: result[k] for k in ['occurrences', 'mapped_candidates', 'unmapped_candidates', 'duplicate_source_rows']}, indent=2))


if __name__ == '__main__':
    main()
