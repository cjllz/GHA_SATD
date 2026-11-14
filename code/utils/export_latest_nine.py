"""Convert latest context records into the frozen nine-column candidate schema."""
import argparse
import csv
import json
from pathlib import Path

FIELDS=['satd_comment_id','name','file_hash','comment_text','normalized_text',
        'matched_keywords','line_start','line_end','satd_location']


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    a.output.parent.mkdir(parents=True,exist_ok=True)
    with a.input.open(encoding='utf-8-sig',newline='') as src, a.output.open('x',encoding='utf-8-sig',newline='') as dest:
        writer=csv.DictWriter(dest,fieldnames=FIELDS,extrasaction='ignore');writer.writeheader()
        count=0
        for r in csv.DictReader(src):
            r['name']=json.dumps([r['repository']],ensure_ascii=False)
            writer.writerow(r);count+=1
    print(f'Exported {count} rows')


if __name__=='__main__':main()
