#!/usr/bin/env python3
"""
cleanup_util.py - Remove the tool's Python __pycache__ directory after a run.
"""

import os
import shutil
import sys

# Anchored to this file so the cleanup never touches the caller's working directory
CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "__pycache__")


def cleanup():
    """Delete the tool's __pycache__ directory if it exists."""
    try:
        if os.path.isdir(CACHE_DIR):
            shutil.rmtree(CACHE_DIR)
    except OSError as e:
        print(f"Error deleting cache directory: {e}", file=sys.stderr)
