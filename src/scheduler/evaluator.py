"""Compatibility entrypoint for running evaluator from src/scheduler."""

from pathlib import Path
import sys


def project_root():
    return Path(__file__).resolve().parents[2]


PROJECT_ROOT = project_root()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.evaluator import main


if __name__ == "__main__":
    main()
