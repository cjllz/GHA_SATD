"""1. Extract keyword candidates, then exclude unreadable workflow files."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent / 'utils'))
from cli import dispatch


if __name__ == '__main__':
    raise SystemExit(dispatch(__doc__, {
        'extract': ('build_satd_comments.py', 'Extract comments and match the 73 keywords'),
        'filter': ('export_readable_satd.py', 'Exclude all candidates from problem files'),
    }))
