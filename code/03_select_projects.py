"""Run first: select Top 300 projects independently of SATD extraction."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent / 'utils'))
from cli import dispatch


if __name__ == '__main__':
    raise SystemExit(dispatch(__doc__, {
        'activity': ('build_activity.py', 'Count monthly workflow commits for all repositories'),
        'select': ('select_projects.py', 'Select Top 300 without using comments or SATD candidates'),
    }))
