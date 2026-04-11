import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
backend_dir_str = str(BACKEND_DIR)
if backend_dir_str not in sys.path:
    sys.path.insert(0, backend_dir_str)
