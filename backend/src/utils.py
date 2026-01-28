"""工具函数模块"""

import json
import re
import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


# ============================================================================
# 文件名清理
# ============================================================================


def clean_filename(name: str) -> str:
    """清理文件名，移除不安全字符"""
    # 移除或替换不安全的字符
    name = re.sub(r'[<>:"/\\|?*]', '_', name)
    # 移除前后空格
    name = name.strip()
    # 限制长度
    if len(name) > 255:
        name = name[:255]
    return name


# ============================================================================
# 时间戳处理
# ============================================================================


def format_timestamp(dt: datetime | None = None) -> str:
    """格式化时间戳为 ISO 格式字符串"""
    if dt is None:
        dt = datetime.now()
    return dt.isoformat()


def parse_timestamp(ts: str) -> datetime | None:
    """解析 ISO 格式时间戳字符串"""
    try:
        return datetime.fromisoformat(ts)
    except (ValueError, TypeError):
        return None


# ============================================================================
# JSON 读写
# ============================================================================


def safe_json_loads_path(path: Path) -> dict | None:
    """安全地从文件读取 JSON"""
    if not path.exists():
        return None

    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.error(f"Failed to load JSON from {path}: {e}")
        return None


def safe_json_write(path: Path, data: dict) -> None:
    """安全地将数据写入 JSON 文件"""
    path.parent.mkdir(parents=True, exist_ok=True)

    try:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except OSError as e:
        logger.error(f"Failed to write JSON to {path}: {e}")
        raise


# ============================================================================
# 目录操作
# ============================================================================


def ensure_dir(path: Path) -> None:
    """确保目录存在"""
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        logger.error(f"Failed to create directory {path}: {e}")
        raise
