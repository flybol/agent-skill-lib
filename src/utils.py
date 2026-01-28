"""General utility functions for CoachAgent.

Only uses standard library. Pure functions preferred.
"""

import json
import logging
import re
import string
from datetime import datetime
from pathlib import Path
from typing import Any


logger = logging.getLogger(__name__)


# ============================================================================
# String Cleaning / Normalization
# ============================================================================

def clean_filename(name: str) -> str:
    """Remove or replace characters unsafe for filenames."""
    # Remove or replace unsafe characters
    unsafe = r'[<>:"/\\|?*\x00-\x1f]'
    cleaned = re.sub(unsafe, '_', name)
    # Collapse multiple underscores
    cleaned = re.sub(r'_+', '_', cleaned)
    # Strip leading/trailing whitespace and dots
    cleaned = cleaned.strip(' .')
    return cleaned or "unnamed"


def sanitize_string(s: str) -> str:
    """Remove control characters and normalize whitespace."""
    # Remove control characters except newlines and tabs
    cleaned = ''.join(c for c in s if c.isprintable() or c in '\n\t')
    # Normalize whitespace
    cleaned = re.sub(r'[ \t]+', ' ', cleaned)
    return cleaned


def truncate_string(s: str, max_length: int, suffix: str = "...") -> str:
    """Truncate string to max_length, adding suffix if truncated."""
    if len(s) <= max_length:
        return s
    suffix_len = len(suffix)
    if max_length <= suffix_len:
        return suffix[:max_length]
    return s[:max_length - suffix_len] + suffix


# ============================================================================
# Date Time Parsing and Formatting
# ============================================================================

def format_timestamp(dt: datetime | None = None) -> str:
    """Format datetime as ISO 8601 string."""
    if dt is None:
        dt = datetime.now()
    return dt.isoformat(timespec="seconds")


def parse_timestamp(ts: str) -> datetime | None:
    """Parse ISO 8601 timestamp string, return None on failure."""
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(ts, fmt)
        except ValueError:
            continue
    return None


def format_duration(seconds: float) -> str:
    """Format seconds into human-readable duration."""
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes = int(seconds // 60)
    secs = seconds % 60
    if minutes < 60:
        return f"{minutes}m {secs:.0f}s"
    hours = minutes // 60
    mins = minutes % 60
    return f"{hours}h {mins}m"


# ============================================================================
# JSON Safe Parsing
# ============================================================================

def safe_json_loads(s: str, default: Any = None) -> Any:
    """Parse JSON string, return default on failure."""
    try:
        return json.loads(s)
    except (json.JSONDecodeError, TypeError):
        return default


def safe_json_loads_path(path: Path, default: Any = None) -> Any:
    """Load JSON file, return default on failure."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return default


def safe_json_dumps(obj: Any, indent: int = 2) -> str:
    """Serialize object to JSON string, handle non-serializable types."""
    try:
        return json.dumps(obj, indent=indent, ensure_ascii=False)
    except TypeError:
        # Fallback: convert to str representation
        return str(obj)


def safe_json_write(path: Path, obj: Any, indent: int = 2) -> bool:
    """Write JSON to file, return False on failure."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(safe_json_dumps(obj, indent), encoding="utf-8")
        return True
    except OSError:
        logger.error(f"Failed to write JSON to {path}")
        return False


# ============================================================================
# Path / Directory Helpers
# ============================================================================

def ensure_dir(path: Path) -> Path:
    """Ensure directory exists, return path."""
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_relative_path(path: Path, base: Path) -> Path:
    """Get path relative to base, handling absolute/relative paths."""
    try:
        return path.relative_to(base)
    except ValueError:
        # Path not relative to base, return as-is
        return path


def get_file_size(path: Path, unit: str = "MB") -> float:
    """Get file size in specified unit."""
    size = path.stat().st_size
    if unit.upper() == "KB":
        return size / 1024
    elif unit.upper() == "MB":
        return size / (1024 * 1024)
    elif unit.upper() == "GB":
        return size / (1024 * 1024 * 1024)
    return float(size)


def get_file_extension(path: Path) -> str:
    """Get file extension including the dot, lowercase."""
    return path.suffix.lower()


# ============================================================================
# Misc Helpers
# ============================================================================

def generate_id(prefix: str = "", length: int = 8) -> str:
    """Generate a simple ID using timestamp and random chars."""
    import time
    import random
    random.seed(int(time.time() * 1e6))
    chars = string.ascii_lowercase + string.digits
    suffix = ''.join(random.choices(chars, k=length))
    return f"{prefix}{suffix}" if prefix else suffix


# ============================================================================
# Video Helpers
# ============================================================================


def get_video_duration(video_path: Path) -> float | None:
    """获取视频时长（秒）。

    Args:
        video_path: 视频文件路径

    Returns:
        视频时长（秒），失败返回 None
    """
    try:
        # 尝试使用 imageio_ffmpeg 的 ffprobe
        import subprocess

        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(video_path),
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            duration_str = result.stdout.strip()
            if duration_str:
                return float(duration_str)
    except FileNotFoundError:
        # ffprobe 不可用，尝试其他方法
        pass
    except Exception as e:
        logger.warning(f"ffprobe failed for {video_path}: {e}")

    try:
        # 备用方案：使用 imageio
        import imageio

        reader = imageio.get_reader(str(video_path))
        meta = reader.get_meta_data()
        fps = meta.get("fps", 30.0)
        total_frames = reader.count_frames()
        reader.close()
        duration = total_frames / fps if fps > 0 else 0
        return float(duration)
    except Exception as e:
        logger.warning(f"Failed to get video duration for {video_path}: {e}")
        return None
