"""3. Link candidates to workflow history and keep the latest observed workflows."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent / 'utils'))
from cli import dispatch


if __name__ == '__main__':
    raise SystemExit(dispatch(__doc__, {
        'link': ('build_occurrences.py', 'Link candidates to repository and workflow history'),
        'select': ('build_latest_snapshot.py', 'Select the latest observed workflow states'),
        'export': ('export_latest_nine.py', 'Export candidates with the original nine fields'),
    }))
