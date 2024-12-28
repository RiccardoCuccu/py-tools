import os
import shutil

def cleanup():
    # Cleanup the Python __pycache__ directory
    try:
        cache_dir = "__pycache__"
        if os.path.exists(cache_dir):
            shutil.rmtree(cache_dir)
    except Exception as e:
        print(f"Error deleting cache directory: {e}")
