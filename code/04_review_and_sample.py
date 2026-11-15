"""Replay the recorded review decisions and original audit sampling (stdlib only).

Semantic judgments are recorded inputs, not decisions made by this script.
The nonhit population is a frozen index, not a new extraction from raw YAML.
"""
import argparse
import csv
import gzip
import hashlib
import json
import math
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SEED = '20261114'
FIELDS = ['satd_comment_id', 'name', 'file_hash', 'comment_text',
          'normalized_text', 'matched_keywords', 'line_start', 'line_end', 'satd_location']


def read_csv(path):
    with path.open(encoding='utf-8-sig', newline='') as stream:
        reader = csv.DictReader(stream)
        return reader.fieldnames, list(reader)


def key(row):
    return json.dumps([row['repository'], row['uid'], row['satd_comment_id']], separators=(',', ':'))


def rank(row, group):
    return hashlib.sha256((SEED + ':' + group + ':' + key(row)).encode()).hexdigest()


def sample_size(N):
    return min(N, math.ceil(N * 1.96**2 * .25 / (.05**2 * (N-1) + 1.96**2 * .25)))


def load(dataset, review):
    for name, item in json.loads((review/'checksums.json').read_text(encoding='utf-8')).items():
        assert hashlib.sha256((review/name).read_bytes()).hexdigest() == item['sha256'], name
    fields, rows = read_csv(dataset/'satd_comments.csv')
    assert fields == FIELDS and len(rows) == 1046
    metadata = json.loads((review/'candidate_review.json').read_text(encoding='utf-8'))
    assert len(metadata) == len(rows)
    frames = {'retained': [], 'excluded': []}
    baseline = []
    for i, (row, record) in enumerate(zip(rows, metadata, strict=True), 1):
        assert int(record['review_index']) == i
        assert record['satd_comment_id'] == row['satd_comment_id']
        assert record['file_hash'] == row['file_hash']
        assert json.loads(row['name']) == [record['repository']]
        expected_keep = record['decision'] == 'satd' or (
            record['decision'] == 'uncertain' and row['satd_comment_id'] !=
            '9b3b3ea55734d0898562d78dfdb1fba6fefd061bb88d9fac62890ee6425dd605')
        assert record['baseline_keep'] == expected_keep
        group = 'retained' if expected_keep else 'excluded'
        frames[group].append(dict(row, **{k: record[k] for k in ['repository', 'source_url']},
                                  uid=record['workflow_uid'], stratum=group, review_index=i))
        if expected_keep:
            baseline.append(row)
    assert len(baseline) == 870
    assert Counter(r['decision'] for r in metadata) == {'satd': 793, 'non_satd': 175, 'uncertain': 78}
    frozen = json.loads((review/'audit_samples.json').read_text(encoding='utf-8'))
    with gzip.open(review/'nonhit_population.json.gz', 'rt', encoding='utf-8') as stream:
        population = json.load(stream)
    return rows, baseline, frames, frozen, population


def replay(frames, frozen, population):
    # Preserve the original A/B/C identifiers: first 100+100, then extension.
    initial = [r for group, rows in frames.items() for r in sorted(rows, key=lambda r: rank(r, group))[:100]]
    initial.sort(key=lambda r: rank(r, 'display'))
    selected = {f'A{i:03d}': r for i, r in enumerate(initial, 1)}
    initial_keys = {key(r) for r in initial}
    assert len(population) == len({key(r) for r in population}) == 33003
    for i, r in enumerate(sorted(population, key=lambda r: rank(r, 'keyword_nonhit'))[:sample_size(len(population))], 1):
        selected[f'B{i:03d}'] = dict(r, stratum='keyword_nonhit')
    additions = []
    assert sample_size(870) == 267
    for group, n in [('retained', 267), ('excluded', 176)]:
        additions.extend(r for r in sorted(frames[group], key=lambda r: rank(r, group))[:n] if key(r) not in initial_keys)
    additions.sort(key=lambda r: rank(r, 'display'))
    selected.update({f'C{i:03d}': r for i, r in enumerate(additions, 1)})
    assert len(selected) == len(frozen) == 823
    assert {r['audit_id'] for r in frozen} == set(selected)
    for r in frozen:
        expected = selected[r['audit_id']]
        assert key(r) == key(expected) and r['stratum'] == expected['stratum'], r['audit_id']
    assert Counter(r['stratum'] for r in frozen) == {'retained': 267, 'excluded': 176, 'keyword_nonhit': 380}
    return selected


def finalize(dataset, review, rows, baseline, selected, frozen):
    decisions = json.loads((review/'final_decisions.json').read_text(encoding='utf-8'))
    assert len(decisions) == len({r['audit_id'] for r in decisions}) == 40
    expected_ids = {r['audit_id'] for r in frozen if (r['ai_label'] == 'U' or
                    (r['stratum'] == 'keyword_nonhit' and r['ai_label'] == 'S')) and r['audit_id'] != 'A187'}
    assert {r['audit_id'] for r in decisions} == expected_ids
    row_key = lambda r: tuple(r[f] for f in FIELDS)
    keep = {row_key(r) for r in baseline}
    lookup = {r['audit_id']: r for r in frozen}
    for decision in decisions:
        aid = decision['audit_id']
        sample = lookup[aid]
        assert decision['satd_comment_id'] == sample['satd_comment_id']
        assert decision['repository'] == sample['repository']
        assert decision['matched_keywords'] == sample['matched_keywords']
        accept = bool(set(json.loads(sample['matched_keywords'])) & {'todo', 'fix'})
        if sample['stratum'] == 'keyword_nonhit':
            assert not accept and decision['decision'] == '不纳入'
            continue
        occurrence = rows[selected[aid]['review_index']-1]
        assert occurrence['matched_keywords'] == sample['matched_keywords']
        present = row_key(occurrence) in keep
        action = ('继续保留' if present else '恢复纳入') if accept else ('移出数据集' if present else '不纳入')
        assert action == decision['decision']
        if accept:
            keep.add(row_key(occurrence))
        else:
            keep.discard(row_key(occurrence))
    final = [r for r in rows if row_key(r) in keep]
    old = {row_key(r) for r in baseline}
    assert len(keep-old) == 7 and len(old-keep) == 1 and len(final) == 876
    assert read_csv(dataset/'satd_comments_reviewed.csv') == (FIELDS, final)
    return final


def write_csv(path, fields, rows):
    with path.open('x', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fields)
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['verify', 'export', 'show'])
    parser.add_argument('--dataset', type=Path, default=ROOT/'dataset')
    parser.add_argument('--review-dir', type=Path, default=ROOT/'external/review',
                        help='External frozen review inputs; not distributed with the code')
    parser.add_argument('--output', type=Path, default=ROOT/'output/review')
    parser.add_argument('--audit-id', help='Record to display, e.g. C049')
    args = parser.parse_args()
    rows, baseline, frames, frozen, population = load(args.dataset, args.review_dir)
    selected = replay(frames, frozen, population)
    final = finalize(args.dataset, args.review_dir, rows, baseline, selected, frozen)
    if args.command == 'show':
        if not args.audit_id:
            parser.error('show requires --audit-id')
        record = next((r for r in frozen if r['audit_id'] == args.audit_id), None)
        if record is None:
            parser.error('Unknown audit ID')
        print(json.dumps(record, ensure_ascii=False, indent=2))
        return
    if args.command == 'export':
        args.output.mkdir(parents=True, exist_ok=False)
        write_csv(args.output/'baseline_870.csv', FIELDS, baseline)
        write_csv(args.output/'satd_comments_reviewed.csv', FIELDS, final)
        # Blank human fields: recorded AI judgments are never converted to human labels.
        review_fields = ['audit_id', 'repository', 'source_url', 'comment_text', 'yaml_context', 'human_label', 'human_reason']
        write_csv(args.output/'audit_review.csv', review_fields,
                  [{f: r.get(f, '') for f in review_fields} for r in frozen])
    print(json.dumps(dict(original=1046, baseline=870, audit_samples=823,
                         nonhit_population=33003, final=876, exact_sampling_replay=True,
                         published_rows_match=True), indent=2))


if __name__ == '__main__':
    main()
