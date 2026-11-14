"""Dispatch numbered entry points to the existing processing scripts."""
from pathlib import Path
import subprocess
import sys


def dispatch(description, commands):
    """Forward arguments unchanged and preserve the processing script's exit code."""
    args = sys.argv[1:]
    if not args or args[0] in ('-h', '--help'):
        print(description)
        print(f'Usage: python code/{Path(sys.argv[0]).name} COMMAND [arguments]')
        for name, (filename, purpose) in commands.items():
            print(f'  {name:10} {purpose}')
        print('Use COMMAND --help for inputs and options.')
        return 0
    if args[0] not in commands:
        print(f'Unknown command: {args[0]}. Use --help.', file=sys.stderr)
        return 2
    filename, _ = commands[args[0]]
    target = Path(__file__).resolve().parent / filename
    # A real subprocess keeps Windows multiprocessing worker imports predictable.
    return subprocess.run([sys.executable, str(target), *args[1:]]).returncode
