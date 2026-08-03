"""Make the repo root importable so tests can `import second_me` regardless of
how pytest is invoked (pytest vs python -m pytest)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
