"""Pytest configuration: make the tool module importable from the tests package."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
