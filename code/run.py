"""Named entry points for building candidates and selecting the latest workflows."""
import runpy
import sys
from pathlib import Path

COMMANDS={
    'extract':'scripts/build_satd_comments.py',
    'export-readable':'postprocess/export_readable_satd.py',
    'link-history':'postprocess/history/build_occurrences.py',
    'select-latest':'postprocess/history/build_latest_snapshot.py',
    'export-nine-columns':'export_latest_nine.py',
}
if len(sys.argv)<2 or sys.argv[1] not in COMMANDS:
    print(__doc__)
    print('Usage: python code/run.py COMMAND [arguments]')
    print('Commands: '+', '.join(COMMANDS))
    print('Use COMMAND --help for its inputs and options.')
    raise SystemExit(0 if len(sys.argv)<2 or sys.argv[1] in ['-h','--help'] else 2)
target=Path(__file__).resolve().parent/'internal'/COMMANDS[sys.argv[1]]
sys.argv=[str(target),*sys.argv[2:]]
runpy.run_path(str(target),run_name='__main__')
