"""File and directory conventions, data persistence for CoachAgent."""

import json
import logging
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from constants import (
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
from errors import (
    StorageError,
    RunNotFoundError,
    FileNotFoundError,
    InvalidRunDirectoryError,
)
from utils import (
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
    def create(task_name: str, run_id: str, user_id: str | None = None, base_dir: Path = RUNS_DIR) -> "RunPaths":
        """Create RunPaths for a new run.

        Args:
            task_name: Name of the task
            run_id: Unique run identifier
            user_id: Optional user ID for multi-user isolation
            base_dir: Base directory for runs (default: RUNS_DIR)

        Returns:
            RunPaths object with all paths for the run
        """
        dir_name = clean_filename(
            RUN_DIR_PATTERN.format(task_name=task_name, run_id=run_id)
        )
        # 支持用户子目录隔离
        if user_id:
            run_dir = base_dir / user_id / dir_name
        else:
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


def create_run_directory(task_name: str, run_id: str, user_id: str | None = None) -> RunPaths:
    """Create a new run directory structure.

    Args:
        task_name: Name of the task
        run_id: Unique run identifier
        user_id: Optional user ID for multi-user isolation

    Returns:
        RunPaths object with all paths for the run

    Raises:
        StorageError: If directory already exists (atomic check)
    """
    paths = RunPaths.create(task_name, run_id, user_id=user_id)

    # 原子操作：如果目录已存在则抛出异常，避免竞态条件
    try:
        paths.run_dir.mkdir(parents=True, exist_ok=False)
        paths.input_dir.mkdir()
        logger.info(f"Created run directory: {paths.run_dir}")
    except FileExistsError as e:
        raise StorageError(f"Run directory already exists: {paths.run_dir}") from e

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


def list_runs(user_id: str | None = None) -> list[RunPaths]:
    """List existing run directories as RunPaths.

    Args:
        user_id: Optional user ID to filter runs. If provided, only returns
                 runs from that user's subdirectory. If None, returns all runs.

    Returns:
        List of RunPaths, sorted by modification time (newest first)
    """
    runs = []
    if not RUNS_DIR.exists():
        ensure_dir(RUNS_DIR)
        return runs

    # 如果指定了 user_id，只扫描该用户目录
    if user_id:
        user_dir = RUNS_DIR / user_id
        if not user_dir.exists():
            return runs
        search_dirs = [user_dir]
    else:
        search_dirs = [RUNS_DIR]

    for search_dir in search_dirs:
        for item in search_dir.iterdir():
            if item.is_dir():
                # 跳过用户子目录本身（当 user_id 为 None 时）
                if user_id is None and item.name.startswith("user_"):
                    # 递归扫描用户目录
                    runs.extend(list_runs(user_id=item.name))
                elif user_id is not None and item.name.startswith("user_"):
                    # 在用户目录内扫描时，跳过嵌套的用户目录
                    continue
                else:
                    runs.append(RunPaths.from_dir(item))

    runs.sort(key=lambda p: p.run_dir.stat().st_mtime, reverse=True)
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
        raise FileNotFoundError(f"No status found at {paths.status_json}")

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


# ============================================================================
# User Data Persistence (新增)
# ============================================================================

# 用户数据文件（单个文件存储所有用户）
USERS_JSON = DATA_DIR / "users.json"


@dataclass
class UserRecord:
    """用户记录，存储用户的基本信息和任务关联。

    所有用户数据存储在 data/users.json 中
    """

    user_id: str
    created_at: str  # ISO 8601 timestamp
    last_access: str  # ISO 8601 timestamp
    run_count: int = 0  # 该用户创建的任务总数

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "UserRecord":
        return cls(**data)


def _load_users_data() -> dict[str, dict[str, Any]]:
    """加载用户数据文件。

    Returns:
        用户数据字典，格式: {user_id: user_data}
    """
    if not USERS_JSON.exists():
        return {}
    return safe_json_loads_path(USERS_JSON) or {}


def _save_users_data(data: dict[str, dict[str, Any]]) -> None:
    """保存用户数据文件。

    Args:
        data: 用户数据字典
    """
    safe_json_write(USERS_JSON, data)
    logger.debug(f"Saved users data, total users: {len(data)}")


def load_user_record(user_id: str) -> UserRecord | None:
    """加载用户记录。

    Args:
        user_id: 用户 ID

    Returns:
        UserRecord 对象，不存在返回 None
    """
    users_data = _load_users_data()
    user_data = users_data.get(user_id)
    if user_data:
        return UserRecord.from_dict(user_data)
    return None


def save_user_record(record: UserRecord) -> None:
    """保存用户记录。

    Args:
        record: UserRecord 对象
    """
    users_data = _load_users_data()
    users_data[record.user_id] = record.to_dict()
    _save_users_data(users_data)
    logger.debug(f"Saved user record: {record.user_id}")


def get_or_create_user(user_id: str) -> UserRecord:
    """获取或创建用户记录。

    Args:
        user_id: 用户 ID

    Returns:
        UserRecord 对象
    """
    record = load_user_record(user_id)
    if record is None:
        # 创建新用户记录
        record = UserRecord(
            user_id=user_id,
            created_at=format_timestamp(),
            last_access=format_timestamp(),
            run_count=0,
        )
        save_user_record(record)
        logger.info(f"Created new user record: {user_id}")
    else:
        # 更新最后访问时间（仅在必要时保存）
        old_access = record.last_access
        record.last_access = format_timestamp()
        if old_access != record.last_access:
            save_user_record(record)
    return record


def increment_user_run_count(user_id: str) -> None:
    """增加用户的任务计数。

    Args:
        user_id: 用户 ID
    """
    users_data = _load_users_data()
    user_data = users_data.get(user_id)
    if user_data:
        user_data["run_count"] = user_data.get("run_count", 0) + 1
        user_data["last_access"] = format_timestamp()
        _save_users_data(users_data)
        logger.info(f"Incremented run count for user: {user_id}")


def list_all_users() -> list[UserRecord]:
    """列出所有用户记录。

    Returns:
        UserRecord 对象列表，按最后访问时间倒序
    """
    users_data = _load_users_data()
    users = []
    for user_data in users_data.values():
        try:
            users.append(UserRecord.from_dict(user_data))
        except Exception as e:
            logger.warning(f"Failed to load user record: {e}")

    users.sort(key=lambda u: u.last_access, reverse=True)
    return users
