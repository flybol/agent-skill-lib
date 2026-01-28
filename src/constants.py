"""Global constants and conventions for CoachAgent."""

from enum import Enum
from pathlib import Path


# ============================================================================
# App / UI Constants
# ============================================================================

APP_TITLE = "CoachAgent - Sports Video Analysis"


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
MAX_VIDEO_DURATION_SEC = 5.0  # 最大视频时长（秒）

# ============================================================================
# Processing Limits
# ============================================================================

POSE_MAX_FRAMES = 1000
DEFAULT_SEGMENTS = 2
MAX_FRAMES_PER_SEGMENT = 120


# ============================================================================
# Agent / LLM Constants
# ============================================================================

# Agent modes
AGENT_MODE_MOCK = "mock"
AGENT_MODE_REAL = "real"

# Debug mode（UI 层面的调试模式）
# True: 显示完整的原始 JSON 和调试信息
# False: 仅显示用户友好的分析结果
DEBUG_MODE_ENABLED = False

# LLM output structure requirements
PROBLEMS_COUNT = 3
IMPROVEMENTS_COUNT = 3


# ============================================================================
# UI Refresh Constants
# ============================================================================

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
