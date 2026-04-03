import os
from pathlib import Path

# Set DATABASE_PATH to absolute path before any tests run
_project_root = Path(__file__).parent.parent
_db_path = _project_root / "synthetic_startup.sqlite"
os.environ["DATABASE_PATH"] = str(_db_path)
