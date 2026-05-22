import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

# Add backend/ to path so test files can import backend modules
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Must be set before auth_utils is imported — it raises RuntimeError at module load if missing
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-tests")

# Mock custom modules that are not available outside the running app
for _mod in [
    "db.models",
    "db.connection",
    "routes.daily",
    "services.achievement_engine",
    "core.dependencies",
]:
    sys.modules.setdefault(_mod, MagicMock())
