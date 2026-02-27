from pathlib import Path

MAX_STEPS = 30
MAX_FAILURES_BEFORE_REPLAN = 1
MAX_REPLANS = 3
EXEC_TIMEOUT = 300  # seconds; exec loop is aborted when this is exceeded
LOG_DIR = Path("/app/logs")