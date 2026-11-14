"""3. Measure workflow activity, select Top 300 projects and export their candidates."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent / 'utils'))
from cli import dispatch


if __name__ == '__main__':
    raise SystemExit(dispatch(__doc__, {
        'activity': ('build_activity.py', 'Count distinct workflow commits per repository and month'),
        'select': ('select_projects.py', 'Apply eligibility rules and rank size, age and stars equally'),
    }))
