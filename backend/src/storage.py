"""File and directory conventions, data persistence for CoachAgent."""

import json
import logging
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from .constants import (
    DATA_DIR,
    TASKS_DIR,
    RUNS_DIR,
    RUN_DIR_PATTERN,
    INPUT_DIR,
    STATUS_JSON,
    REPORT_JSON,
    SEGMENTS_JSON,
    FEATURES_JSON,
    LOGS_TXT,
    CONFIG_JSON,
    RunState,
    SUPPORTED_VIDEO_EXTENSIONS,
    DEFAULT_LLM_MODEL,
)
from .errors import (
    StorageError,
    RunNotFoundError,
    StorageFileNotFoundError,
    InvalidRunDirectoryError,
)
from .utils import (
    clean_filename,
    format_timestamp,
    parse_timestamp,
    safe_json_loads_path,
    safe_json_write,
    ensure_dir,
)

logger = logging.getLogger(__name__)


# ============================================================================
# Data Classes
# ============================================================================


@dataclass
class RunStatus:
    """Task status stored in status.json."""

    task_name: str
    run_id: str
    state: str  # RunState value
    progress: int  # 0-100
    message: str
    created_at: str
    started_at: str | None = None
    completed_at: str | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RunStatus":
        return cls(**data)


@dataclass
class RunConfig:
    agent_mode: str  # mock/real
    llm_model: str  # ✅ 新增
    max_frames: int
    num_segments: int
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RunConfig":
        # ✅ 兼容旧 config.json（没有 llm_model 的情况）
        if "llm_model" not in data:
            data["llm_model"] = DEFAULT_LLM_MODEL
        return cls(**data)


# ============================================================================
# RunPaths - Centralized Path Generation
# ============================================================================


@dataclass
class RunPaths:
    """All paths for a specific run."""

    run_dir: Path
    input_dir: Path
    status_json: Path
    report_json: Path
    segments_json: Path
    features_json: Path
    logs_txt: Path
    config_json: Path

    @staticmethod
    def create(task_name: str, run_id: str, base_dir: Path = RUNS_DIR) -> "RunPaths":
        """Create RunPaths for a new run."""
        dir_name = clean_filename(
            RUN_DIR_PATTERN.format(task_name=task_name, run_id=run_id)
        )
        run_dir = base_dir / dir_name
        input_dir = run_dir / INPUT_DIR

        return RunPaths(
            run_dir=run_dir,
            input_dir=input_dir,
            status_json=run_dir / STATUS_JSON,
            report_json=run_dir / REPORT_JSON,
            segments_json=run_dir / SEGMENTS_JSON,
            features_json=run_dir / FEATURES_JSON,
            logs_txt=run_dir / LOGS_TXT,
            config_json=run_dir / CONFIG_JSON,
        )

    @staticmethod
    def from_dir(run_dir: Path) -> "RunPaths":
        """Create RunPaths from an existing run directory."""
        input_dir = run_dir / INPUT_DIR

        return RunPaths(
            run_dir=run_dir,
            input_dir=input_dir,
            status_json=run_dir / STATUS_JSON,
            report_json=run_dir / REPORT_JSON,
            segments_json=run_dir / SEGMENTS_JSON,
            features_json=run_dir / FEATURES_JSON,
            logs_txt=run_dir / LOGS_TXT,
            config_json=run_dir / CONFIG_JSON,
        )


# ============================================================================
# Run Directory Operations
# ============================================================================


def create_run_directory(task_name: str, run_id: str) -> RunPaths:
    """Create a new run directory structure."""
    paths = RunPaths.create(task_name, run_id)

    if paths.run_dir.exists():
        raise StorageError(f"Run directory already exists: {paths.run_dir}")

    paths.run_dir.mkdir(parents=True)
    paths.input_dir.mkdir()

    logger.info(f"Created run directory: {paths.run_dir}")
    return paths


def initialize_run_status(paths: RunPaths, task_name: str, run_id: str) -> RunStatus:
    """Initialize status.json with queued state."""
    status = RunStatus(
        task_name=task_name,
        run_id=run_id,
        state=RunState.QUEUED,
        progress=0,
        message="Queued",
        created_at=format_timestamp(),
    )
    write_status(paths, status)
    return status


def initialize_run_config(
    paths: RunPaths,
    agent_mode: str,
    llm_model: str,  # ✅ 新增
    max_frames: int,
    num_segments: int,
) -> RunConfig:
    config = RunConfig(
        agent_mode=agent_mode,
        llm_model=llm_model,  # ✅ 新增
        max_frames=max_frames,
        num_segments=num_segments,
        created_at=format_timestamp(),
    )
    safe_json_write(paths.config_json, config.to_dict())
    return config


def list_runs() -> list[RunPaths]:
    """List all existing run directories as RunPaths."""
    runs = []
    if not RUNS_DIR.exists():
        ensure_dir(RUNS_DIR)
        return runs

    for run_dir in sorted(RUNS_DIR.iterdir(), reverse=True):
        if run_dir.is_dir():
            runs.append(RunPaths.from_dir(run_dir))
    return runs


def get_run_paths(task_name: str, run_id: str) -> RunPaths:
    """Get RunPaths for a specific task_name/run_id."""
    dir_name = clean_filename(
        RUN_DIR_PATTERN.format(task_name=task_name, run_id=run_id)
    )
    run_dir = RUNS_DIR / dir_name

    if not run_dir.exists():
        raise RunNotFoundError(f"Run not found: {task_name}__{run_id}")

    return RunPaths.from_dir(run_dir)


# ============================================================================
# Status Operations
# ============================================================================


def write_status(paths: RunPaths, status: RunStatus) -> None:
    """Write status to status.json."""
    safe_json_write(paths.status_json, status.to_dict())


def read_status(paths: RunPaths) -> RunStatus | None:
    """Read status from status.json."""
    data = safe_json_loads_path(paths.status_json)
    if data is None:
        return None
    return RunStatus.from_dict(data)


def update_status(
    paths: RunPaths,
    state: RunState | None = None,
    progress: int | None = None,
    message: str | None = None,
    error: str | None = None,
) -> None:
    """Update specific fields in status."""
    status = read_status(paths)
    if status is None:
        raise StorageFileNotFoundError(f"No status found at {paths.status_json}")

    if state is not None:
        status.state = state
        if state == RunState.RUNNING and status.started_at is None:
            status.started_at = format_timestamp()
        elif state in (RunState.DONE, RunState.FAILED) and status.completed_at is None:
            status.completed_at = format_timestamp()

    if progress is not None:
        status.progress = max(0, min(100, progress))

    if message is not None:
        status.message = message

    if error is not None:
        status.error = error

    write_status(paths, status)


# ============================================================================
# Report Operations
# ============================================================================


def write_report(paths: RunPaths, report: dict[str, Any]) -> None:
    """Write report to report.json."""
    safe_json_write(paths.report_json, report)


def read_report(paths: RunPaths) -> dict[str, Any] | None:
    """Read report from report.json."""
    return safe_json_loads_path(paths.report_json)


# ============================================================================
# Segments Operations
# ============================================================================


def write_segments(paths: RunPaths, segments: dict[str, Any]) -> None:
    """Write segments to segments.json."""
    safe_json_write(paths.segments_json, segments)


def read_segments(paths: RunPaths) -> dict[str, Any] | None:
    """Read segments from segments.json."""
    return safe_json_loads_path(paths.segments_json)


# ============================================================================
# Features Operations
# ============================================================================


def write_features(paths: RunPaths, features: dict[str, Any]) -> None:
    """Write features to features.json."""
    safe_json_write(paths.features_json, features)


def read_features(paths: RunPaths) -> dict[str, Any] | None:
    """Read features from features.json."""
    return safe_json_loads_path(paths.features_json)


# ============================================================================
# Config Operations
# ============================================================================


def read_config(paths: RunPaths) -> RunConfig | None:
    """Read config from config.json."""
    data = safe_json_loads_path(paths.config_json)
    if data is None:
        return None
    return RunConfig.from_dict(data)


# ============================================================================
# Logs Operations
# ============================================================================


def append_log(paths: RunPaths, message: str) -> None:
    """Append message to logs.txt."""
    timestamp = format_timestamp()
    log_line = f"[{timestamp}] {message}\n"

    try:
        with open(paths.logs_txt, "a", encoding="utf-8") as f:
            f.write(log_line)
    except OSError as e:
        logger.error(f"Failed to write log: {e}")


def read_logs(paths: RunPaths, max_lines: int | None = None) -> str:
    """Read logs from logs.txt, optionally limiting lines."""
    if not paths.logs_txt.exists():
        return "No logs available."

    try:
        with open(paths.logs_txt, "r", encoding="utf-8") as f:
            lines = f.readlines()
        if max_lines:
            lines = lines[-max_lines:]
        return "".join(lines)
    except OSError as e:
        logger.error(f"Failed to read logs: {e}")
        return f"Failed to read logs: {e}"


# ============================================================================
# Video Input Operations
# ============================================================================


def get_video_path(paths: RunPaths) -> Path | None:
    """Find video file in input directory."""
    if not paths.input_dir.exists():
        return None

    for file in paths.input_dir.iterdir():
        if file.is_file() and has_video_extension(file.name):
            return file
    return None


def has_video_extension(filename: str) -> bool:
    """Check if filename has a supported video extension."""
    return Path(filename).suffix.lower() in SUPPORTED_VIDEO_EXTENSIONS


def validate_run_directory(paths: RunPaths) -> bool:
    """Check if run directory has required structure."""
    required_dirs = {paths.input_dir}
    required_files = {paths.status_json}

    for d in required_dirs:
        if not d.exists():
            return False

    for f in required_files:
        if not f.exists():
            return False

    return True
