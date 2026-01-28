"""Global constants and conventions for CoachAgent."""

from enum import Enum
from pathlib import Path


# ============================================================================
# App / UI Constants
# ============================================================================

APP_TITLE = "CoachAgent - Sports Video Analysis"
APP_SUBTITLE = "AI-powered sports technique analysis"


# ============================================================================
# Data Directory Constants
# ============================================================================

DATA_DIR = Path("./data")
TASKS_DIR = DATA_DIR / "tasks"
RUNS_DIR = DATA_DIR / "runs"

# Run directory naming convention: <task_name>__<run_id>
RUN_DIR_PATTERN = "{task_name}__{run_id}"

# Input subdirectory within run dir
INPUT_DIR = "input"


# ============================================================================
# File Name Constants
# ============================================================================

STATUS_JSON = "status.json"
REPORT_JSON = "report.json"
SEGMENTS_JSON = "segments.json"
FEATURES_JSON = "features.json"
LOGS_TXT = "logs.txt"
CONFIG_JSON = "config.json"


# ============================================================================
# Status Constants
# ============================================================================


class RunState(str, Enum):
    """Task lifecycle states."""

    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


# ============================================================================
# Video Support Constants
# ============================================================================

SUPPORTED_VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".webm"}
MAX_UPLOAD_MB = 10
MAX_BYTES = MAX_UPLOAD_MB * 1024 * 1024

# ============================================================================
# Processing Limits
# ============================================================================

POSE_MAX_FRAMES = 1000
DEFAULT_SEGMENTS = 2
MAX_FRAMES_PER_SEGMENT = 120

# 视频抽帧配置（用于实际分析流程）
MAX_FRAMES = 20  # 总共最多抽取20帧
FRAMES_PER_SEGMENT = 5  # 每个分段抽取5帧
DEFAULT_NUM_SEGMENTS = 2  # 默认分为4个分段


# ============================================================================
# Agent / LLM Constants
# ============================================================================

# Agent modes
AGENT_MODE_MOCK = "mock"
AGENT_MODE_REAL = "real"

# LLM output structure requirements
PROBLEMS_COUNT = 3
IMPROVEMENTS_COUNT = 3


# ============================================================================
# UI Refresh Constants
# ============================================================================

PROGRESS_REFRESH_INTERVAL_MS = 1000  # Refresh progress every 1 second
AUTO_REFRESH_THRESHOLD_SEC = 30  # Stop auto-refresh after 30 seconds idle


# constants.py

DEFAULT_LLM_MODEL = "glm-4.6v-flash"

LLM_MODELS = {
    "deepseek-chat": {
        "type": "text",
        "provider": "deepseek",
        "label": "DeepSeek（文本）",
    },
    "glm-4.6v-flash": {
        "type": "vision",
        "provider": "zhipu",
        "label": "GLM-4.6V-Flash（图像理解）",
    },
}
