"""
casb_run.py — CLI entry point for casb-automation command.
This file is the registered entry point in pyproject.toml.
It simply imports and executes run.py from the same directory.
"""

import os
import sys


def main():
    # Add the directory containing this file to sys.path
    # so run.py and all its imports (core/, apps/, config.py) are found
    script_dir = os.path.dirname(os.path.abspath(__file__))
    if script_dir not in sys.path:
        sys.path.insert(0, script_dir)

    # Execute run.py as the main script
    run_path = os.path.join(script_dir, "run.py")
    with open(run_path, "r", encoding="utf-8") as f:
        code = f.read()

    # Set __file__ so run.py resolves paths relative to itself correctly
    exec(compile(code, run_path, "exec"), {"__file__": run_path, "__name__": "__main__"})


if __name__ == "__main__":
    main()
