"""Select each workflow's last observed state, retaining only eligible live YAML.

Input source_row_number MUST preserve gigawork's newest-to-oldest first-parent
history traversal. Do not use a CSV re-sorted by timestamp as source metadata.
This is a cross-sectional candidate snapshot, not entity or semantic labeling.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'.deps'))
import duckdb


def sha(path):
    d=hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda:f.read(8*1024*1024),b''):d.update(chunk)
    return d.hexdigest()


def literal(path):
    return "'"+str(path).replace("'","''")+"'"


def build(versions,occurrences,output):
    versions,occurrences,output=map(Path,(versions,occurrences,output))
    if output.exists() and any(output.iterdir()):raise FileExistsError(output)
    output.mkdir(parents=True,exist_ok=True)
    inputs={str(p.resolve()):{'sha256':sha(p),'bytes':p.stat().st_size} for p in (versions,occurrences)}
    db=duckdb.connect()
    db.execute("SET memory_limit='2GB'");db.execute('SET threads=4')
    db.execute('SET temp_directory='+literal(output/'.tmp'))
    def count(query):return db.execute(query).fetchone()[0]
    def export(query,name):
        db.execute(f'COPY ({query}) TO {literal(output/name)} (FORMAT CSV, HEADER)')
    try:
        print('Reading all workflow histories, including zero-candidate and deleted versions',flush=True)
        db.execute('CREATE TABLE v AS SELECT * FROM read_csv(?,all_varchar=true)',[str(versions)])
        db.execute('CREATE TABLE o AS SELECT * FROM read_csv(?,all_varchar=true)',[str(occurrences)])
        if count('SELECT count(*)-count(DISTINCT version_id) FROM v'):raise ValueError('Duplicate version IDs')
        if count("SELECT count(*) FROM v WHERE repository IS NULL OR uid IS NULL OR try_cast(source_row_number AS BIGINT) IS NULL"):
            raise ValueError('Missing workflow identity or original source order')
        if count('SELECT count(*)-count(DISTINCT source_row_number) FROM v'):
            raise ValueError('Original source order must be unique per version record')
        db.execute('''CREATE TABLE ordered AS SELECT *,
            row_number() OVER w AS history_rank,
            lead(file_hash) OVER w AS older_hash,lead(file_path) OVER w AS older_path,
            lead(version_id) OVER w AS older_version_id,
            max(try_cast(committed_date AS BIGINT)) OVER(PARTITION BY repository,uid) AS max_timestamp
            FROM v WINDOW w AS(PARTITION BY repository,uid ORDER BY cast(source_row_number AS BIGINT))''')
        db.execute('''CREATE TABLE chain_issues AS SELECT repository,uid,version_id,source_row_number,
            previous_file_hash,older_hash,previous_file_path,older_path,
            'source_order_chain_mismatch' AS issue_type FROM ordered WHERE older_version_id IS NOT NULL
            AND (coalesce(previous_file_hash,'')<>coalesce(older_hash,'')
              OR coalesce(previous_file_path,'')<>coalesce(older_path,''))
            UNION ALL SELECT repository,uid,version_id,source_row_number,
            previous_file_hash,older_hash,previous_file_path,older_path,
            'nonterminal_lifecycle_end' FROM ordered WHERE history_rank>1
            AND (git_change_type='D' OR (git_change_type='R' AND file_hash IS NULL))''')
        db.execute('''CREATE TABLE latest AS SELECT a.* EXCLUDE(older_hash,older_path,older_version_id,history_rank),
            CASE WHEN git_change_type='D' AND file_hash IS NULL THEN 'deleted'
              WHEN git_change_type='R' AND file_hash IS NULL THEN 'renamed_out_of_workflow_scope'
              WHEN exists(SELECT 1 FROM chain_issues i WHERE i.repository=a.repository AND i.uid=a.uid) THEN 'ambiguous_history'
              WHEN coalesce(try_cast(commit_variant_count AS BIGINT),0)<>1 THEN 'conflicting_latest_commit'
              WHEN commit_hash IS NULL OR file_path IS NULL OR file_hash IS NULL
                OR git_change_type NOT IN ('A','M','R') THEN 'invalid_latest_state'
              WHEN coalesce(current_file_status,'missing')='missing' THEN 'missing_latest_file_status'
              WHEN current_file_status<>'ok' THEN 'problem_latest_file'
              ELSE 'eligible' END AS selection_status
            FROM ordered a WHERE history_rank=1''')
        # At the cutoff one repository path cannot represent two active lifecycles.
        db.execute('''UPDATE latest SET selection_status='ambiguous_live_path' WHERE selection_status='eligible'
            AND (repository,file_path) IN (SELECT repository,file_path FROM latest
              WHERE file_hash IS NOT NULL AND git_change_type<>'D' GROUP BY ALL HAVING count(*)>1)''')
        db.execute('''CREATE TABLE selected AS SELECT o.* FROM o JOIN latest l USING(version_id)
            WHERE l.selection_status='eligible' ''')
        if count('SELECT count(*)-count(DISTINCT occurrence_id) FROM selected'):
            raise AssertionError('Duplicate selected occurrence IDs')
        if count('''SELECT count(*) FROM selected s JOIN latest l USING(version_id)
            WHERE s.repository<>l.repository OR s.uid<>l.uid OR s.file_hash<>l.file_hash'''):
            raise AssertionError('Candidate/source identity mismatch')
        print('Exporting latest candidates and workflow selection audit',flush=True)
        export('SELECT * FROM selected ORDER BY repository,uid,occurrence_id','latest_satd_comments.csv')
        export('''SELECT l.*,coalesce(c.n,0) AS candidate_count FROM latest l LEFT JOIN
            (SELECT version_id,count(*) n FROM selected GROUP BY 1) c USING(version_id)
            ORDER BY repository,uid''','workflow_selection_audit.csv')
        export('''SELECT l.*,coalesce(c.n,0) AS candidate_count FROM latest l LEFT JOIN
            (SELECT version_id,count(*) n FROM selected GROUP BY 1) c USING(version_id)
            WHERE selection_status='eligible' ORDER BY repository,uid''','latest_workflows.csv')
        export('SELECT * FROM chain_issues ORDER BY repository,uid,source_row_number','history_order_issues.csv')
        export('SELECT * FROM selected ORDER BY occurrence_id LIMIT 20','latest_examples.csv')
        result={
            'method':'latest_source_history_state_v1',
            'selection_order':'minimum original source_row_number per repository+uid; gigawork reverse first-parent traversal',
            'input_history_occurrences':count('SELECT count(*) FROM o'),
            'input_workflow_lifecycles':count('SELECT count(*) FROM latest'),
            'eligible_workflows':count("SELECT count(*) FROM latest WHERE selection_status='eligible'"),
            'candidate_rows':count('SELECT count(*) FROM selected'),
            'workflows_with_candidates':count('SELECT count(DISTINCT version_id) FROM selected'),
            'repositories_with_candidates':count('SELECT count(DISTINCT repository) FROM selected'),
            'unique_candidate_content_hashes':count('SELECT count(DISTINCT file_hash) FROM selected'),
            'selection_counts':dict(db.execute('SELECT selection_status,count(*) FROM latest GROUP BY 1 ORDER BY 1').fetchall()),
            'chain_issue_rows':count('SELECT count(*) FROM chain_issues'),
            'timestamp_disagreement_workflows':count('SELECT count(*) FROM latest WHERE try_cast(committed_date AS BIGINT)<>max_timestamp'),
            'validation':{'one_latest_state_per_workflow':True,'no_older_version_fallback':True,
                          'original_occurrence_fields_preserved':True,'unique_occurrence_ids':True},
            'semantic_review':'not_performed',
            'limitations':['Latest means the observed collection cutoff, not live GitHub HEAD.',
                'Source history order is a dataset-specific prerequisite; arbitrary CSV order is not accepted as chronological proof.',
                'Whole histories with mismatched source transitions are conservatively quarantined.',
                'No-candidate eligible workflows are retained in latest_workflows.csv.',
                'Repeated text across workflows or positions is intentionally retained.'],
            'inputs':inputs}
        for p in (versions,occurrences):
            assert sha(p)==inputs[str(p.resolve())]['sha256'],'Input mutated'
        result['validation']['inputs_unchanged']=True
        result['outputs']={p.name:{'sha256':sha(p),'bytes':p.stat().st_size} for p in output.glob('*.csv')}
        (output/'latest_snapshot_report.json').write_text(json.dumps(result,indent=2,ensure_ascii=False),encoding='utf-8')
        return result
    finally:db.close()


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--versions',type=Path,default=ROOT/'output/stage2/run/workflow_versions.csv.gz')
    p.add_argument('--occurrences',type=Path,default=ROOT/'output/stage2/run/satd_occurrences.csv')
    p.add_argument('--output',type=Path,default=ROOT/'output/stage2/latest')
    a=p.parse_args();print(json.dumps(build(a.versions,a.occurrences,a.output),ensure_ascii=False,indent=2))
