#!/usr/bin/env python3
"""
cleanup_util.py - Remove Python __pycache__ directory after a run.
"""

import os
import shutil

CACHE_DIR = "__pycache__"


def cleanup():
    """Delete the Python __pycache__ directory if it exists."""
    try:
        if os.path.exists(CACHE_DIR):
            shutil.rmtree(CACHE_DIR)
    except Exception as e:
        print(f"Error deleting cache directory: {e}")
