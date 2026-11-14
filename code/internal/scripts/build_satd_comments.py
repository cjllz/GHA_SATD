"""YAML adaptation of NAIST-SE/SATDinBuildSystems.

Upstream commit: 329a2428045fc6fd4541013c65287eb4917732b1.
Unmodified source and keyword bytes: reference/SATDinBuildSystems/.
The keyword expression is retained; local history input/output are adapters.
"""
from pathlib import Path
import sys
import hashlib
import json
import re
from functools import lru_cache
import argparse
import csv
import sqlite3
import time
import importlib.metadata
from concurrent.futures import ProcessPoolExecutor, wait, FIRST_COMPLETED

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / '.deps'))
sys.path.insert(0, str(ROOT / 'scripts'))
import duckdb


@lru_cache(maxsize=1)
def load_keywords() -> list[str]:
    data = (ROOT / 'config/keywords_list.txt').read_bytes()
    if hashlib.sha256(data).hexdigest() != 'c29084ca69ff0079548917d435a527b7c9a622d4771c0b49cdc8a74db78b0189':
        raise ValueError('Keyword bytes differ from pinned upstream')
    keywords = data.decode('utf-8').split(', ')
    assert len(keywords) == len(set(keywords)) == 73
    return keywords


@lru_cache(maxsize=2)
def _patterns(words):
    return [(word, re.compile(r'\b' + re.escape(word.lower()) + r'\b')) for word in words]


def match_keywords(body: str, keywords: list[str]) -> list[str]:
    # Upstream identify_SATD_comments.py line 52, expression unchanged.
    # Compile once for throughput; only the extracted comment body is lowercased.
    lower = body.lower()
    return [word for word, pattern in _patterns(tuple(keywords)) if pattern.search(lower)]


def normalize_text(body: str) -> str:
    return ' '.join(body.lower().split())


def make_comment_id(file_hash: str, block) -> str:
    value = ['satd-comment-v1', file_hash, block.line_start, block.line_end, block.comment_text]
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,separators=(',', ':')).encode('utf-8')).hexdigest()


def build_manifest(csv_path: Path, db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(str(db_path)) as con:
        con.execute("SET memory_limit='2GB'")
        con.execute('SET threads=4')
        con.execute('''CREATE OR REPLACE TABLE hash_repositories AS
            WITH history AS (
                SELECT repository, file_hash, previous_file_hash
                FROM read_csv(?, header=true, all_varchar=true)
            ), expanded AS (
                SELECT repository AS name, unnest([file_hash, previous_file_hash]) AS file_hash
                FROM history
            ) SELECT DISTINCT file_hash, name FROM expanded
              WHERE file_hash IS NOT NULL AND file_hash <> '' AND name IS NOT NULL''', [str(csv_path)])
        invalid = con.execute("SELECT count(*) FROM hash_repositories WHERE NOT regexp_full_match(file_hash, '[0-9a-f]{64}')").fetchone()[0]
        if invalid:
            raise ValueError(f'{invalid} invalid hash references')
        con.execute('CREATE OR REPLACE TABLE hashes AS SELECT file_hash, list(name ORDER BY name) AS names FROM hash_repositories GROUP BY file_hash ORDER BY file_hash')


def iter_hashes(db_path: Path):
    with duckdb.connect(str(db_path), read_only=True) as con:
        cursor = con.execute('SELECT file_hash FROM hashes ORDER BY file_hash')
        while rows := cursor.fetchmany(10000):
            yield from (r[0] for r in rows)


FIELDS = ['satd_comment_id','name','file_hash','comment_text','normalized_text',
          'matched_keywords','line_start','line_end','satd_location']
ISSUE_FIELDS = ['file_hash','line','reason','detail']
SAMPLE_FIELDS = ['satd_comment_id','name','file_hash','comment_text','normalized_text','line_start','line_end']


def _sha_file(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024*1024), b''):
            h.update(block)
    return h.hexdigest()


def _fingerprint(dataset_dir):
    h = hashlib.sha256()
    for path in sorted((ROOT/'scripts').glob('*')):
        if path.suffix in ('.py','.ps1'):
            h.update(path.name.encode()); h.update(path.read_bytes())
    h.update((ROOT/'config/keywords_list.txt').read_bytes())
    versions={name:importlib.metadata.version(name) for name in
              ('duckdb','ruamel.yaml','PyYAML','tree-sitter','tree-sitter-bash')}
    h.update(json.dumps(versions,sort_keys=True).encode())
    h.update(_sha_file(dataset_dir/'workflows.csv').encode())
    h.update(str(dataset_dir.resolve()).encode())
    return h.hexdigest()


def _create_state(con):
    con.executescript('''
        CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS files(file_hash TEXT PRIMARY KEY, status TEXT, comments INTEGER,
            hits INTEGER, located INTEGER, unknown INTEGER);
        CREATE TABLE IF NOT EXISTS candidates(satd_comment_id TEXT PRIMARY KEY, name TEXT,
            file_hash TEXT, comment_text TEXT, normalized_text TEXT, matched_keywords TEXT,
            line_start INTEGER, line_end INTEGER, satd_location TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS issues(file_hash TEXT, line INTEGER, reason TEXT, detail TEXT);
        CREATE TABLE IF NOT EXISTS negative_sample(priority TEXT PRIMARY KEY, payload TEXT);
    ''')


def _save_sample(con, samples):
    con.executemany('INSERT OR IGNORE INTO negative_sample VALUES (?,?)', samples)
    con.execute('DELETE FROM negative_sample WHERE priority NOT IN (SELECT priority FROM negative_sample ORDER BY priority LIMIT 384)')


def _process_one(item):
    from yaml_comments import extract_comments
    from fast_yaml import parse_yaml_fast as parse_yaml
    from satd_location import locate_comment
    directory, file_hash, names = item
    issues, rows, negatives = [], [], []
    def failed(reason, detail):
        return (file_hash,'failed',0,0,0,0), [], [(file_hash,0,reason,str(detail)[:800])], []
    try:
        data = (Path(directory)/'workflows'/file_hash).read_bytes()
    except OSError as exc:
        return failed('file_read_error', exc)
    if hashlib.sha256(data).hexdigest() != file_hash:
        return failed('hash_mismatch', 'Content bytes do not match file_hash')
    try:
        source = data.decode('utf-8-sig')
    except UnicodeDecodeError as exc:
        return failed('decode_error', exc)
    parsed = parse_yaml(source)
    comments, extraction_issues = extract_comments(parsed)
    issues.extend((file_hash,i['line'],i['reason'],i['detail']) for i in parsed.issues+extraction_issues)
    names_json = json.dumps(names,ensure_ascii=False,separators=(',', ':'))
    words = load_keywords()
    for block in comments:
        keywords = match_keywords(block.body,words)
        identity = make_comment_id(file_hash,block)
        if keywords:
            try:
                location, method = locate_comment(block,parsed)
            except Exception as exc:
                location, method = 'unknown', 'location_exception'
                issues.append((file_hash,block.line_start,'location_exception',str(exc)[:800]))
            rows.append((identity,names_json,file_hash,block.comment_text,normalize_text(block.body),
                         json.dumps(keywords,ensure_ascii=False,separators=(',', ':')),
                         block.line_start,block.line_end,location))
            if location == 'unknown' or method == 'containing_scope':
                issues.append((file_hash,block.line_start,'location_unknown' if location=='unknown' else 'location_coarse',method))
        elif block.body != '':
            payload = dict(zip(SAMPLE_FIELDS,[identity,names_json,file_hash,block.comment_text,normalize_text(block.body),block.line_start,block.line_end]))
            priority = hashlib.sha256(('20261113:'+identity).encode()).hexdigest()
            negatives.append((priority,json.dumps(payload,ensure_ascii=False)))
    # Dedup by physical content-version comment ID, never by normalized text.
    rows = list({row[0]:row for row in rows}.values())
    unknown = sum(row[-1]=='unknown' for row in rows)
    status = 'partial' if parsed.issues or extraction_issues else 'ok'
    return (file_hash,status,len(comments),len(rows),len(rows)-unknown,unknown), rows, issues, negatives


def _process_batch(items):
    stats, rows, issues, negatives = [], [], [], []
    for item in items:
        try:
            result = _process_one(item)
        except Exception as exc:
            raise RuntimeError(f'Unexpected processing failure for file_hash={item[1]}: {exc}') from exc
        stats.append(result[0]); rows.extend(result[1]); issues.extend(result[2]); negatives.extend(result[3])
    # The global bottom-384 sample is contained in the union of batch bottom-384 samples.
    return stats,rows,issues,sorted(negatives)[:384]


def _export(con, output_dir, manifest_count, fingerprint, elapsed, limit):
    def write_rows(filename, fields, iterable):
        path = output_dir/filename
        temp = path.with_suffix(path.suffix+'.tmp')
        with temp.open('w',encoding='utf-8',newline='') as f:
            writer=csv.writer(f);writer.writerow(fields);writer.writerows(iterable)
        temp.replace(path)
    write_rows('satd_comments.csv',FIELDS,con.execute('SELECT * FROM candidates ORDER BY file_hash,line_start,line_end,satd_comment_id'))
    write_rows('satd_processing_issues.csv',ISSUE_FIELDS,con.execute('SELECT * FROM issues ORDER BY file_hash,line,reason,detail'))
    samples = [json.loads(row[0]) for row in con.execute('SELECT payload FROM negative_sample ORDER BY priority')]
    write_rows('non_satd_sample.csv',SAMPLE_FIELDS,([row[k] for k in SAMPLE_FIELDS] for row in samples))
    counts=con.execute('SELECT count(*),coalesce(sum(comments),0),coalesce(sum(hits),0),coalesce(sum(located),0),coalesce(sum(unknown),0) FROM files').fetchone()
    output_rows=con.execute('SELECT count(*) FROM candidates').fetchone()[0]
    assert counts[2] == output_rows == counts[3]+counts[4]
    report={'method':'SATDinBuildSystems 73-keyword YAML adaptation',
            'upstream_commit':'329a2428045fc6fd4541013c65287eb4917732b1',
            'fingerprint':fingerprint,'manifest_hashes':manifest_count,'processed_hashes':counts[0],
            'extracted_comments':counts[1],'keyword_candidates':counts[2],
            'located_candidates':counts[3],'unknown_candidates':counts[4],
            'output_rows':output_rows,'negative_sample_size':len(samples),'sample_seed':20261113,
            'file_status_counts':dict(con.execute('SELECT status,count(*) FROM files GROUP BY status')),
            'issue_counts':dict(con.execute('SELECT reason,count(*) FROM issues GROUP BY reason')),
            'scope':'full' if counts[0]==manifest_count else 'partial', 'requested_limit':limit,
            'invocation_elapsed_seconds':round(elapsed,2),
            'all_keyword_candidates_retained':True,
            'limitations':['Keyword candidates are not human-validated SATD.',
                'Script comments require a known shell and a literal run scalar; unsupported/failed extraction is logged.',
                'Unknown and coarse locations remain in the main table.',
                '384 negative comments require human review; no recall claim is made.']}
    temp=output_dir/'satd_build_report.json.tmp'
    temp.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    temp.replace(output_dir/'satd_build_report.json')
    return report


def run_pipeline(dataset_dir: Path, output_dir: Path, limit: int | None = None,
                 resume: bool = False, workers: int = 8) -> dict:
    dataset_dir=Path(dataset_dir).resolve();output_dir=Path(output_dir).resolve()
    if limit is not None and limit < 1:
        raise ValueError('limit must be positive')
    if workers < 1:
        raise ValueError('workers must be positive')
    output_dir.mkdir(parents=True,exist_ok=True)
    started=time.monotonic()
    print('Checking input and method fingerprint...',flush=True)
    fingerprint=_fingerprint(dataset_dir)
    work=dataset_dir/'work'/'satd';work.mkdir(parents=True,exist_ok=True)
    state_dir=work/('run-'+hashlib.sha256(str(output_dir).encode()).hexdigest()[:16])
    state_dir.mkdir(exist_ok=True)
    state_path=state_dir/'state.sqlite'
    existed=state_path.exists()
    if existed and not resume:
        raise ValueError('Existing checkpoint: use --resume or a different output directory')
    con=sqlite3.connect(state_path)
    con.execute('PRAGMA journal_mode=WAL');con.execute('PRAGMA synchronous=NORMAL')
    _create_state(con)
    stored=con.execute("SELECT value FROM metadata WHERE key='fingerprint'").fetchone()
    if stored and stored[0] != fingerprint:
        con.close();raise ValueError('Checkpoint fingerprint differs; do not mix input or rule versions')
    con.execute("INSERT OR REPLACE INTO metadata VALUES ('fingerprint',?)",(fingerprint,));con.commit()
    input_hash=_sha_file(dataset_dir/'workflows.csv')
    manifest=work/('manifest-'+input_hash[:16]+'.duckdb')
    if not manifest.exists():
        print('Building full-history hash/repository manifest...',flush=True)
        temporary=manifest.with_suffix('.building.duckdb')
        build_manifest(dataset_dir/'workflows.csv',temporary)
        temporary.replace(manifest)
    db=duckdb.connect(str(manifest),read_only=True)
    manifest_count=db.execute('SELECT count(*) FROM hashes').fetchone()[0]
    query='SELECT file_hash,names FROM hashes ORDER BY file_hash'
    if limit:
        query+=f' LIMIT {int(limit)}'
    cursor=db.execute(query)
    def batches():
        while values := cursor.fetchmany(250):
            if resume:
                found={r[0] for r in con.execute('SELECT file_hash FROM files WHERE file_hash IN ('+','.join('?' for _ in values)+')',[v[0] for v in values])}
                values=[v for v in values if v[0] not in found]
            if values:
                yield [(str(dataset_dir),h,names) for h,names in values]
    completed=con.execute('SELECT count(*) FROM files').fetchone()[0]
    last_print=0
    def save(result):
        nonlocal completed,last_print
        stats,rows,issues,negatives=result
        with con:
            con.executemany('INSERT INTO files VALUES (?,?,?,?,?,?)',stats)
            con.executemany('INSERT INTO candidates VALUES (?,?,?,?,?,?,?,?,?)',rows)
            con.executemany('INSERT INTO issues VALUES (?,?,?,?)',issues)
            _save_sample(con,negatives)
        completed+=len(stats)
        now=time.monotonic()
        if now-last_print>=10:
            print(json.dumps({'processed':completed,'selected':min(limit or manifest_count,manifest_count),
                'last_batch_candidates':len(rows),'elapsed_seconds':round(now-started,1)}),flush=True)
            last_print=now
    print(json.dumps({'manifest_hashes':manifest_count,'workers':workers,'checkpoint':str(state_path)}),flush=True)
    try:
        iterator=iter(batches())
        if workers==1:
            for batch in iterator:
                save(_process_batch(batch))
        else:
            with ProcessPoolExecutor(max_workers=workers) as pool:
                pending=set()
                for _ in range(workers*2):
                    batch=next(iterator,None)
                    if batch is None:break
                    pending.add(pool.submit(_process_batch,batch))
                while pending:
                    done,pending=wait(pending,return_when=FIRST_COMPLETED)
                    for future in done:
                        save(future.result())
                        batch=next(iterator,None)
                        if batch is not None:pending.add(pool.submit(_process_batch,batch))
        report=_export(con,output_dir,manifest_count,fingerprint,time.monotonic()-started,limit)
        print(json.dumps(report,ensure_ascii=False),flush=True)
        return report
    finally:
        db.close();con.close()


if __name__ == '__main__':
    cli=argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--dataset-dir',type=Path,default=ROOT)
    cli.add_argument('--output-dir',type=Path,default=ROOT/'output')
    cli.add_argument('--limit',type=int)
    cli.add_argument('--resume',action='store_true')
    cli.add_argument('--workers',type=int,default=8)
    args=cli.parse_args()
    run_pipeline(args.dataset_dir,args.output_dir,args.limit,args.resume,args.workers)
