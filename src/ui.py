from __future__ import annotations

import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import streamlit as st
import streamlit.components.v1 as components


from constants import (
    AGENT_MODE_REAL,
    DEFAULT_LLM_MODEL,
    DEFAULT_SEGMENTS,
    POSE_MAX_FRAMES,
    MAX_BYTES,
    MAX_UPLOAD_MB,
    MAX_VIDEO_DURATION_SEC,
    DEBUG_MODE_ENABLED,
)
from streamlit_autorefresh import st_autorefresh
import pipeline
import storage
from utils import get_video_duration, clean_filename

logger = logging.getLogger(__name__)
# =========================
# 基础配置
# =========================
APP_TITLE = "乒乓数字教练v1.0"
DATA_DIR = Path("./data")
UPLOAD_DIR = DATA_DIR / "uploads"
RUNS_DIR = DATA_DIR / "runs"
RECENT_LIMIT = 10

SUPPORTED_VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".avi"}

# 新方案：每段固定抽 5 帧（时间均分段内均匀采样）
FRAMES_PER_SEGMENT = 5

# =========================
# 产品级自动刷新配置
# =========================
AUTO_REFRESH_BASE_MS = 1200
AUTO_REFRESH_SLOW_MS = 2500
AUTO_REFRESH_IDLE_MS = 4000
AUTO_REFRESH_STALL_SEC = 12

# =========================
# 任务队列状态管理
# =========================
# 用于跟踪当前用户的任务在队列中的位置
QUEUED_TASK_RUN_DIR = "__queued_task_run_dir__"


def _ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    RUNS_DIR.mkdir(parents=True, exist_ok=True)


def _slugify_task_name(s: str) -> str:
    s = (s or "").strip()
    if not s:
        return ""
    return clean_filename(s)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        if not path.exists():
            return {}
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _pretty_state(state: str) -> str:
    s = (state or "unknown").lower()
    m = {
        "pending": "pending",
        "queued": "queued",
        "running": "running",
        "processing": "running",
        "done": "done",
        "success": "done",
        "failed": "failed",
        "error": "failed",
        "unknown": "unknown",
    }
    return m.get(s, s)


def _status_to_ui(status: dict[str, Any]) -> tuple[str, float, str, str]:
    state = _pretty_state(str(status.get("state") or "unknown"))
    prog = status.get("progress", 0)
    try:
        prog_f = float(prog)
    except Exception:
        prog_f = 0.0

    # progress in storage is 0-100
    if prog_f > 1.0:
        prog_f = prog_f / 100.0
    prog_f = max(0.0, min(1.0, prog_f))

    msg = str(status.get("message") or "")
    ts = str(
        status.get("completed_at")
        or status.get("started_at")
        or status.get("created_at")
        or ""
    )
    return state, prog_f, msg, ts


def _should_auto_refresh(state: str) -> bool:
    return _pretty_state(state) in {"queued", "pending", "running", "unknown"}


def _calc_refresh_interval_ms(state: str, prog: float, *, unchanged_hits: int) -> int:
    s = _pretty_state(state)
    if s in {"queued", "pending"}:
        return AUTO_REFRESH_SLOW_MS
    if unchanged_hits >= 6:
        return AUTO_REFRESH_IDLE_MS
    if prog >= 0.9:
        return AUTO_REFRESH_SLOW_MS
    return AUTO_REFRESH_BASE_MS


def _list_run_dirs(limit: int = RECENT_LIMIT) -> list[Path]:
    """列出当前用户的任务目录。

    多用户隔离后：
    1. 扫描用户子目录 data/runs/{user_id}/ 中的新任务
    2. 兼容扫描根目录 data/runs/ 中的旧任务（无 user_id 前缀的目录）

    Returns:
        按修改时间倒序排列的任务目录列表
    """
    _ensure_dirs()
    user_id = st.session_state.get("user_id", "")
    runs = []

    # 需要跳过的目录名称（非任务目录）
    SKIP_DIR_NAMES = {"frames", "input", "segments", "output", "__pycache__", ".git"}

    # 1. 扫描当前用户的子目录（新任务）
    if user_id:
        user_dir = RUNS_DIR / user_id
        logger.info(f"Scanning user directory: {user_dir}, exists: {user_dir.exists()}")
        if user_dir.exists():
            for p in user_dir.iterdir():
                if p.is_dir() and p.name not in SKIP_DIR_NAMES:
                    # 验证是有效的任务目录（包含 status.json 或 input/frames 子目录）
                    if (
                        (p / "status.json").exists()
                        or (p / "input").exists()
                        or (p / "frames").exists()
                    ):
                        runs.append(p)
                        logger.info(f"Found task directory: {p}")
        else:
            logger.warning(f"User directory does not exist: {user_dir}")
    else:
        logger.warning("user_id is empty, cannot scan user directory")

    # 2. 扫描根目录中的旧任务（兼容）
    # 旧任务目录名格式：{task_name}__{run_id}，不包含 user_ 前缀
    if RUNS_DIR.exists():
        for p in RUNS_DIR.iterdir():
            if p.is_dir():
                # 跳过用户子目录本身和系统目录
                if p.name.startswith("user_") or p.name in SKIP_DIR_NAMES:
                    continue
                # 验证是有效的任务目录（包含 status.json 或 input/frames 子目录）
                if (
                    (p / "status.json").exists()
                    or (p / "input").exists()
                    or (p / "frames").exists()
                ):
                    runs.append(p)
                    logger.info(f"Found legacy task directory: {p}")

    # 按修改时间倒序排序
    runs.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    logger.info(f"Total runs found: {len(runs)}")
    return runs[:limit]


def _get_run_paths(run_dir: Path) -> storage.RunPaths:
    return storage.RunPaths.from_dir(run_dir)


def _load_report(paths: storage.RunPaths) -> dict[str, Any]:
    return storage.read_report(paths) or {}


def _list_frames(run_dir: Path) -> list[Path]:
    d = run_dir / "frames"
    if not d.exists():
        return []
    imgs: list[Path] = []
    for ext in (".jpg", ".jpeg", ".png", ".webp"):
        imgs.extend(d.glob(f"*{ext}"))
    imgs.sort()
    return imgs


def _load_features(paths: storage.RunPaths) -> dict[str, Any]:
    return storage.read_features(paths) or {}


def _load_segments(paths: storage.RunPaths) -> dict[str, Any]:
    return storage.read_segments(paths) or {}


def _load_logs(paths: storage.RunPaths) -> str:
    return storage.read_logs(paths, max_lines=None)


def _parse_frame_evidence(evidence: str) -> list[int]:
    """从证据文本中提取帧号。

    Args:
        evidence: 证据文本，格式如 "Frame 42 at 1.92s" 或 "Frame 12, Frame 25"

    Returns:
        提取的帧号列表
    """
    import re

    pattern = r"Frame\s+(\d+)"
    matches = re.findall(pattern, evidence)
    return [int(m) for m in matches]


def _parse_segment_evidence(evidence: str) -> list[int]:
    """从证据文本中提取 segment ID 列表。

    Args:
        evidence: 证据文本，格式如 "Segment 0, Frame 15" 或 "在 Segment 1 中"

    Returns:
        提取的 segment_id 列表
    """
    import re

    pattern = r"Segment\s+(\d+)"
    matches = re.findall(pattern, evidence)
    return [int(m) for m in matches]


def _get_frames_by_segment(run_dir: Path, segment_id: int) -> list[Path]:
    """根据 segment_id 获取该 segment 的所有帧图片。

    Args:
        run_dir: 任务目录
        segment_id: 段落 ID

    Returns:
        该 segment 的帧图片路径列表
    """
    # 读取 report.json 获取 segment 的帧信息
    paths = _get_run_paths(run_dir)
    report = _load_report(paths)

    if not report:
        return []

    # 从 features.segments 中获取段落信息
    features = report.get("features", {})
    segments = features.get("segments", [])

    target_segment = None
    for seg in segments:
        if seg.get("segment_id") == segment_id:
            target_segment = seg
            break

    if not target_segment:
        return []

    # 获取该 segment 的 frame_indices
    frame_indices = target_segment.get("frame_indices", [])
    return _find_frame_images(run_dir, frame_indices)


def _find_frame_images(run_dir: Path, frame_numbers: list[int]) -> list[Path]:
    """根据帧号查找对应的图片文件。

    Args:
        run_dir: 任务目录
        frame_numbers: 帧号列表

    Returns:
        找到的图片路径列表
    """
    frames_dir = run_dir / "frames"
    if not frames_dir.exists():
        return []

    result = []
    for frame_num in frame_numbers:
        # 直接根据帧号匹配文件名（frame_000015.jpg 或 000015.jpg）
        found = None
        for ext in (".jpg", ".jpeg", ".png", ".webp"):
            # 尝试 frame_000015.jpg 格式
            frame_file = frames_dir / f"frame_{frame_num:06d}{ext}"
            if frame_file.exists():
                found = frame_file
                break
            # 尝试 000015.jpg 格式（兼容旧格式）
            frame_file = frames_dir / f"{frame_num:06d}{ext}"
            if frame_file.exists():
                found = frame_file
                break
        if found:
            result.append(found)

    return result


def _ui_autorefresh(*, interval_ms: int, key: str) -> None:
    # 返回值是计数器，用不用都行
    st_autorefresh(interval=interval_ms, key=key)


def _is_running_from_selected() -> bool:
    """根据当前选中的 run 状态判断是否运行中。"""
    ss = st.session_state
    selected = ss.get("selected_run_dir", "")
    if not selected:
        return False
    run_dir = Path(selected)
    if not run_dir.exists():
        return False
    paths = _get_run_paths(run_dir)
    status = _read_json(paths.status_json)
    state, _prog, _msg, _ts = _status_to_ui(status)
    return state in {"queued", "pending", "running", "unknown"}


def _render_queue_status() -> None:
    """渲染任务队列状态组件。

    显示：
    1. 队列中等待的任务数量
    2. Worker 是否正在运行
    3. 如果当前用户有任务在队列中，显示其排队位置
    """
    ss = st.session_state

    # 获取队列信息
    try:
        queue_info = pipeline.get_queue_info()
        queue_size = queue_info.get("queue_size", 0)
        worker_alive = queue_info.get("worker_alive", False)
    except Exception as e:
        logger.warning(f"Failed to get queue info: {e}")
        queue_size = 0
        worker_alive = False

    # 检查当前用户的任务是否在队列中
    my_task_dir = ss.get(QUEUED_TASK_RUN_DIR, "")
    my_task_position = None
    my_task_name = None

    if my_task_dir:
        # 尝试从 run_dir 解析任务名称
        task_dir = Path(my_task_dir)
        if task_dir.exists():
            parts = task_dir.name.split("__")
            if len(parts) >= 1:
                my_task_name = parts[0]

            # 检查任务状态是否还在 queued
            try:
                paths = _get_run_paths(task_dir)
                status = _read_json(paths.status_json)
                state, _prog, _msg, _ts = _status_to_ui(status)
                if state == "queued":
                    # 任务仍在队列中，队列位置大约是 queue_size
                    # 注意：这只是估算，因为无法直接访问队列内容
                    my_task_position = queue_size
                else:
                    # 任务已经不在队列中（可能已开始执行或完成）
                    ss[QUEUED_TASK_RUN_DIR] = ""
            except Exception:
                # 无法读取状态，可能任务已删除
                ss[QUEUED_TASK_RUN_DIR] = ""

    # 如果队列是空的且没有用户任务，不显示组件
    if queue_size == 0 and not my_task_dir:
        return

    # 渲染队列状态组件
    with st.sidebar.container(border=True):
        st.markdown("### 📋 任务队列")

        if queue_size > 0:
            if worker_alive:
                st.info(f"正在执行任务，**{queue_size}** 个任务等待中...")
            else:
                st.warning(f"队列中有 **{queue_size}** 个任务等待处理")
        else:
            if worker_alive:
                st.success("✅ 队列空闲，正在处理任务...")
            else:
                st.caption("队列空闲")

        if my_task_name:
            if my_task_position is not None:
                st.info(
                    f"📍 您的任务「{my_task_name}」排在第 **{my_task_position}** 位"
                )
            else:
                # 任务已不在队列中，但用户可能还关心
                st.caption(f"✅ 您的任务「{my_task_name}」已开始处理")

        st.caption("💡 任务会按顺序依次执行，请耐心等待")


# =========================
# UI：Sidebar 操作面板
# 目标：默认无需用户操作（上传 + 开始分析即可）
# 保留能力：1) 任务名称 2) 分析参数 3) 历史任务
# =========================
def render_sidebar_panel() -> None:
    ss = st.session_state

    # 初始化用户 ID（用于多用户隔离）
    # 使用文件持久化，确保关闭浏览器后仍能识别用户
    import uuid

    # 每次都优先从 URL 查询参数获取 user_id
    query_params = st.query_params
    url_user_id = query_params.get("user_id")

    if url_user_id:
        # URL 中有 user_id，优先使用（最可靠）
        if ss.get("user_id") != url_user_id:
            ss["user_id"] = url_user_id
            logger.info(f"Loaded user_id from URL: {ss['user_id']}")
    elif ss.get("user_id"):
        # URL 中没有，但 session_state 中有，使用 session_state 的值
        # 并更新 URL
        ss_user_id = ss.get("user_id")
        query_params["user_id"] = ss_user_id
        logger.info(f"Using user_id from session_state: {ss_user_id}, updated URL")
    else:
        # 既没有 URL 参数，也没有 session_state，尝试从文件恢复
        # 扫描 data/users/ 目录，找到最近访问的用户
        all_users = storage.list_all_users()
        if all_users:
            # 使用最近访问的用户
            last_user = all_users[0]
            ss["user_id"] = last_user.user_id
            query_params["user_id"] = last_user.user_id
            logger.info(f"Restored user_id from file: {last_user.user_id}")
        else:
            # 没有任何用户记录，生成新的 user_id
            ss["user_id"] = f"user_{uuid.uuid4().hex[:8]}"
            query_params["user_id"] = ss["user_id"]
            logger.info(f"Generated new user_id: {ss['user_id']}")

    # 加载或创建用户记录（更新最后访问时间）
    user_record = storage.get_or_create_user(ss["user_id"])
    ss["user_record"] = user_record

    # 使用 JavaScript 设置 cookie 和 localStorage（辅助存储）
    # 这样即使 Streamlit 关闭，浏览器仍能识别用户
    js_code = f"""
    <script>
    (function() {{
        // 设置 cookie（365 天有效）
        const cookieName = 'coachagent_user_id';
        const cookieValue = '{ss["user_id"]}';
        const days = 365;
        const date = new Date();
        date.setTime(date.getTime() + (days * 24 * 60 * 60 * 1000));
        const expires = '; expires=' + date.toUTCString();
        document.cookie = cookieName + '=' + cookieValue + expires + '; path=/';
        console.log('User ID stored to cookie:', cookieValue);

        // 同时存储到 localStorage（备用）
        localStorage.setItem('coachagent_user_id', cookieValue);

        // 确保 URL 中有 user_id
        const urlParams = new URLSearchParams(window.location.search);
        if (!urlParams.get('user_id')) {{
            urlParams.set('user_id', cookieValue);
            const newUrl = window.location.pathname + '?' + urlParams.toString();
            window.history.replaceState({{path: newUrl}}, '', newUrl);
            console.log('URL updated with user_id:', cookieValue);
        }}
    }})();
    </script>
    """
    components.html(js_code, height=0)

    ss.setdefault("selected_run_dir", "")
    ss.setdefault("task_name", datetime.now().strftime("%Y%m%d_%H%M"))
    ss.setdefault("auto_refresh_enabled", False)
    ss.setdefault("llm_model", DEFAULT_LLM_MODEL)
    ss.setdefault("num_segments", DEFAULT_SEGMENTS)
    ss.setdefault("debug_mode", DEBUG_MODE_ENABLED)  # 调试模式开关

    # 运行中：锁定部分设置，避免用户误以为对当前任务生效
    is_running = _is_running_from_selected()
    ss["is_running"] = is_running

    # 预先计算 max_frames（供主页面 create_run 使用）
    try:
        num_segments = int(ss.get("num_segments", DEFAULT_SEGMENTS))
    except Exception:
        num_segments = DEFAULT_SEGMENTS
    expected_total = int(num_segments) * FRAMES_PER_SEGMENT
    ss["max_frames"] = int(min(expected_total, int(POSE_MAX_FRAMES)))

    st.sidebar.title("CoachAgent")
    st.sidebar.caption("默认：上传视频 → 点击开始分析。左侧仅在需要时调整设置。")

    # =========================
    # 1) 任务名称（默认只读展示）
    # =========================
    with st.sidebar.container():
        st.markdown("🧾 **任务名称**")
        st.write(ss.get("task_name", ""))

        # ✅ 自动刷新开关：放在任务名称下面、重新生成上面（更符合用户心智）
        ss["auto_refresh_enabled"] = st.toggle(
            "自动刷新",
            value=bool(ss.get("auto_refresh_enabled", False)),
            help="开启后，任务运行中会自动刷新右侧进度与结果；默认关闭。",
        )

        if st.button("重新生成", use_container_width=True, disabled=is_running):
            ss["task_name"] = datetime.now().strftime("%Y%m%d_%H%M%S")

    # =========================
    # 2) 分析参数（默认摘要 + 展开设置）
    # =========================
    with st.sidebar.container():
        st.markdown("⚙️ **分析参数**")
        st.caption(
            f"默认：模型 {ss.get('llm_model', DEFAULT_LLM_MODEL)} ｜ "
            f"分段 {int(ss.get('num_segments', DEFAULT_SEGMENTS))} ｜ "
            f"自动刷新 {'开' if ss.get('auto_refresh_enabled') else '关'}"
        )

        # 调试模式开关
        ss["debug_mode"] = st.toggle(
            "调试模式",
            value=bool(ss.get("debug_mode", DEBUG_MODE_ENABLED)),
            help="开启后显示完整 JSON 和调试信息（仅供开发调试使用）",
        )

        with st.expander("展开设置", expanded=False):
            if is_running:
                st.info("任务运行中：参数仅对下一次分析生效。")

            # 模型：保持你当前策略（锁死/可扩展），不改功能
            ss["llm_model"] = st.selectbox(
                "分析模型",
                [DEFAULT_LLM_MODEL, "glm-4.6v-flash"],
                index=0,
                disabled=True,
            )

            ss["num_segments"] = st.number_input(
                "分段数量",
                min_value=1,
                max_value=16,
                value=int(ss.get("num_segments", DEFAULT_SEGMENTS)),
                step=1,
                disabled=is_running,
            )

            expected_total = int(ss["num_segments"]) * FRAMES_PER_SEGMENT
            ss["max_frames"] = int(min(expected_total, int(POSE_MAX_FRAMES)))
            st.caption(
                f"抽帧策略：按时间均分 {int(ss['num_segments'])} 段，每段均匀抽 {FRAMES_PER_SEGMENT} 帧"
                f"（预计总帧数≈ {expected_total}，上限兜底= {ss['max_frames']}）。"
            )

    # =========================
    # 3) 历史任务（默认折叠）
    # =========================
    with st.sidebar.container(border=False):
        st.markdown("🕘 **历史任务**")

        run_dirs = _list_run_dirs(limit=RECENT_LIMIT)
        labels: dict[str, str] = {}
        for p in run_dirs:
            try:
                paths = _get_run_paths(p)
                status = _read_json(paths.status_json)
                state, _prog, _m, _ts = _status_to_ui(status)
                dot = {
                    "done": "🟢",
                    "running": "🟡",
                    "queued": "🟡",
                    "pending": "🟡",
                    "failed": "🔴",
                }.get(state, "⚪")

                # 安全获取 task_name 和 run_id
                # 支持新旧两种目录格式：
                # - 新格式: data/runs/{user_id}/{task_name}__{run_id}
                # - 旧格式: data/runs/{task_name}__{run_id}
                parts = p.name.split("__")
                if len(parts) >= 2:
                    task_name = status.get("task_name") or parts[0]
                    run_id = parts[-1]
                else:
                    task_name = p.name
                    run_id = ""

                labels[str(p)] = (
                    f"{dot} {task_name} · {run_id}" if run_id else f"{dot} {task_name}"
                )
            except Exception as e:
                logger.warning(f"Failed to load status for {p}: {e}")
                labels[str(p)] = f"⚪ {p.name}"

        options = [""] + [str(p) for p in run_dirs]

        def _fmt(x: str) -> str:
            if not x:
                return "（未选择任务）"
            return labels.get(x, Path(x).name)

        with st.expander("展开查看最近任务", expanded=False):
            # 确保索引安全：默认选择第一个任务（如果有的话）
            selected = ss.get("selected_run_dir", "")
            default_index = 0

            # 如果当前没有选中任务，或者选中的任务不在列表中，默认选择第一个
            if not selected or selected not in options:
                if len(options) > 1:  # 有历史任务
                    default_index = 1  # 选择第一个任务（跳过空选项）
                    # 更新 session_state
                    ss["selected_run_dir"] = options[default_index]
                else:
                    default_index = 0  # 没有历史任务，选择空选项

            # 计算当前索引
            try:
                current_index = options.index(ss.get("selected_run_dir", ""))
            except Exception:
                current_index = default_index

            chosen = st.selectbox(
                "最近10条",
                options=options,
                index=current_index,
                format_func=_fmt,
            )
            ss["selected_run_dir"] = chosen

            if not ss["selected_run_dir"]:
                st.caption("未选择历史任务。")
            else:
                try:
                    run_dir = Path(ss["selected_run_dir"])
                    paths = _get_run_paths(run_dir)
                    status = _read_json(paths.status_json)
                    state, prog, msg, ts = _status_to_ui(status)

                    # 安全获取 task_name（支持新旧格式）
                    parts = run_dir.name.split("__")
                    if len(parts) >= 2:
                        task_name = status.get("task_name") or parts[0]
                    else:
                        task_name = status.get("task_name") or run_dir.name

                    st.markdown(f"**当前任务**：{task_name}")
                    st.markdown(f"**状态**：`{state}`")
                    st.progress(prog)
                    if msg:
                        st.caption(msg)
                    if ts:
                        st.caption(f"更新时间：{ts}")
                except Exception as e:
                    logger.warning(f"Failed to load selected task details: {e}")
                    st.warning(f"无法加载任务详情：{e}")


# =========================
# UI：上传与启动
# =========================
def render_upload_and_start() -> None:
    ss = st.session_state
    ss.setdefault("task_name", datetime.now().strftime("%Y%m%d_%H%M"))
    ss.setdefault("uploaded_file", None)

    # ✅ 自动刷新：默认关闭（开关在左侧「分析参数」里）
    ss.setdefault("auto_refresh_enabled", False)
    with st.container(border=False):
        st.markdown("### 上传训练视频")
        st.markdown(
            """
<style>
/* 作用范围：只针对 file_uploader 的 dropzone 提示区域 */
section[data-testid="stFileUploaderDropzone"]
  div[data-testid="stFileUploaderDropzoneInstructions"] > div:nth-child(2) > span:nth-child(1) {
  visibility: hidden;
  position: relative;
  display: inline-block; /* 让伪元素定位稳定 */
}

/* 替换第一行：Drag and drop file here */
section[data-testid="stFileUploaderDropzone"]
  div[data-testid="stFileUploaderDropzoneInstructions"] > div:nth-child(2) > span:nth-child(1)::after {
  content: "将视频文件拖拽到这里";
  visibility: visible;
  position: absolute;
  left: 0;
  top: 0;
  white-space: nowrap;
}

/* 第二行：Limit 200MB per file ... */
section[data-testid="stFileUploaderDropzone"]
  div[data-testid="stFileUploaderDropzoneInstructions"] > div:nth-child(2) > span:nth-child(2) {
  visibility: hidden;
  position: relative;
  display: inline-block;
}

/* 替换第二行：文件大小和时长限制 */
section[data-testid="stFileUploaderDropzone"]
  div[data-testid="stFileUploaderDropzoneInstructions"] > div:nth-child(2) > span:nth-child(2)::after {
  content: "单文件最大 10MB • 时长不超过 5 秒 • 支持 MP4 / AVI / MOV / MKV";
  visibility: visible;
  position: absolute;
  left: 0;
  top: 0;
  white-space: nowrap;
}

/* 替换上传错误提示 */
span[data-testid="stFileUploaderFileErrorMessage"]{
  visibility: hidden;
  position: relative;
  display: inline-block;
  min-height: 1em;
}

span[data-testid="stFileUploaderFileErrorMessage"]::after{
  content: "文件大小不能超过 10MB，时长不超过 5 秒。";
  visibility: visible;
  position: absolute;
  left: 0;
  top: 0;
  white-space: nowrap;
}
</style>
""",
            unsafe_allow_html=True,
        )

        uploaded = st.file_uploader(
            "选择视频文件",
            type=[e.lstrip(".") for e in SUPPORTED_VIDEO_EXTS],
            accept_multiple_files=False,
        )
        if uploaded is not None:
            size = uploaded.size  # bytes
            if size > MAX_BYTES:
                st.error(
                    f"文件过大：{size / 1024 / 1024:.1f}MB，最大允许 {MAX_UPLOAD_MB}MB。请压缩或截取视频后再上传。"
                )
                st.stop()

            # 校验视频时长
            # 先将文件保存到临时位置
            suffix = Path(uploaded.name).suffix.lower()
            if suffix not in SUPPORTED_VIDEO_EXTS:
                suffix = ".mp4"
            safe_name = clean_filename(Path(uploaded.name).stem) + suffix
            tmp_video = (
                UPLOAD_DIR / f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{safe_name}"
            )
            _ensure_dirs()
            with open(tmp_video, "wb") as f:
                f.write(uploaded.getbuffer())

            # 获取视频时长
            duration = get_video_duration(tmp_video)
            if duration is None:
                # 无法获取时长，显示警告但不阻止上传
                st.warning(
                    f"⚠️ 无法自动检测视频时长，请确保视频不超过 {MAX_VIDEO_DURATION_SEC:.0f} 秒。"
                )
            elif duration > MAX_VIDEO_DURATION_SEC:
                st.error(
                    f"视频时长过长：{duration:.1f}秒，最大允许 {MAX_VIDEO_DURATION_SEC:.0f}秒。"
                    f"请截取视频前{MAX_VIDEO_DURATION_SEC:.0f}秒后再上传。"
                )
                # 删除临时文件
                tmp_video.unlink(missing_ok=True)
                st.stop()

            # 校验通过，删除临时文件（稍后会重新创建）
            tmp_video.unlink(missing_ok=True)

        if uploaded is not None:
            ss["uploaded_file"] = uploaded
        uploaded = ss.get("uploaded_file")

        # 显示上传的视频（可播放）
        if uploaded is not None:
            st.video(uploaded)
            st.caption(
                f"建议 1~{int(MAX_VIDEO_DURATION_SEC)} 秒，尽量拍到完整准备动作与击球瞬间。"
            )
        else:
            st.caption(
                f"建议 1~{int(MAX_VIDEO_DURATION_SEC)} 秒，尽量拍到完整准备动作与击球瞬间。"
            )

        # ✅ 任务名称 / 分析参数：统一从左侧操作面板（session_state）读取
        task_name = str(ss.get("task_name", "") or "")
        agent_mode = AGENT_MODE_REAL
        llm_model = str(ss.get("llm_model", DEFAULT_LLM_MODEL) or DEFAULT_LLM_MODEL)
        try:
            num_segments = int(ss.get("num_segments", DEFAULT_SEGMENTS))
        except Exception:
            num_segments = DEFAULT_SEGMENTS
        try:
            max_frames = int(ss.get("max_frames", POSE_MAX_FRAMES))
        except Exception:
            max_frames = int(POSE_MAX_FRAMES)

        start_clicked = st.button(
            "🚀 开始分析",
            type="primary",
            width="stretch",
            disabled=(uploaded is None),
        )

        if not start_clicked:
            return
        if uploaded is None:
            st.warning("请先上传视频。")
            return

        _ensure_dirs()

        # 1) 上传文件先落盘到 uploads（避免 UploadedFile 生命周期问题）
        suffix = Path(uploaded.name).suffix.lower()
        if suffix not in SUPPORTED_VIDEO_EXTS:
            suffix = ".mp4"
        safe_name = clean_filename(Path(uploaded.name).stem) + suffix
        tmp_video = (
            UPLOAD_DIR / f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{safe_name}"
        )
        with open(tmp_video, "wb") as f:
            f.write(uploaded.getbuffer())

        # 2) create_run：写 status/config + 拷贝视频到 input_dir
        try:
            paths, _run_id = pipeline.create_run(
                task_name=_slugify_task_name(task_name) or "task",
                video_path=tmp_video,
                agent_mode=agent_mode,
                llm_model=(llm_model or DEFAULT_LLM_MODEL),
                max_frames=int(
                    max_frames
                ),  # ✅ 兜底上限（实际抽帧由 per_segment 决定）
                num_segments=int(num_segments),
                user_id=ss.get("user_id"),  # ✅ 传递 user_id 实现用户隔离
            )
        except Exception as e:
            st.error(f"创建任务失败：{e}")
            return

        ss["selected_run_dir"] = str(paths.run_dir)

        # 记录任务到队列状态（用于显示排队位置）
        ss[QUEUED_TASK_RUN_DIR] = str(paths.run_dir)

        # 3) 后台启动执行
        try:
            pipeline.start_background_run(paths, overwrite=True)
            ss["auto_refresh_enabled"] = True  # ✅ 开始后默认开启自动刷新
            st.success("✅ 任务已加入队列，等待执行...")
            if ss.get("auto_refresh_enabled", False):
                st.caption("已开启自动刷新：右侧会自动更新进度.")

            # 显示任务队列状态（放在开始分析按钮后面）
            st.divider()
            _render_queue_status()
        except Exception as e:
            try:
                storage.update_status(
                    paths,
                    state=storage.RunState.FAILED,
                    message="启动失败",
                    error=str(e),
                )  # type: ignore
            except Exception:
                pass
            st.error(f"启动失败：{e}")


# =========================
# UI：状态条（自动刷新）
# =========================
def render_status_strip(run_dir: Path) -> None:
    ss = st.session_state
    key_prefix = f"ar::{run_dir.name}"
    ss.setdefault(f"{key_prefix}::last_sig", "")
    ss.setdefault(f"{key_prefix}::last_change_ts", time.time())
    ss.setdefault(f"{key_prefix}::unchanged_hits", 0)
    ss.setdefault(f"{key_prefix}::completed_toast", False)

    paths = _get_run_paths(run_dir)
    status = _read_json(paths.status_json)
    state, prog, msg, ts = _status_to_ui(status)
    task_name = status.get("task_name") or run_dir.name.split("__")[0]
    video = storage.get_video_path(paths)
    video_name = video.name if video else "(未找到视频)"

    sig = f"{state}|{prog:.3f}|{msg}|{ts}"
    if sig != ss[f"{key_prefix}::last_sig"]:
        ss[f"{key_prefix}::last_sig"] = sig
        ss[f"{key_prefix}::last_change_ts"] = time.time()
        ss[f"{key_prefix}::unchanged_hits"] = 0
    else:
        ss[f"{key_prefix}::unchanged_hits"] += 1

    unchanged_hits = int(ss[f"{key_prefix}::unchanged_hits"])
    seconds_since_change = time.time() - float(ss[f"{key_prefix}::last_change_ts"])

    # ✅ 自动刷新开关：统一从 Step2 的同一开关读取（默认关闭）
    enabled = bool(ss.get("auto_refresh_enabled", False))

    # 完成/失败：无需自动刷新（即使开关开着，也不会再触发）
    if state in {"done", "failed"}:
        enabled = False

    # Toast 一次
    if state in {"done", "failed"} and not ss.get(
        f"{key_prefix}::completed_toast", False
    ):
        ss[f"{key_prefix}::completed_toast"] = True
        st.toast(
            "分析完成" if state == "done" else "❌ 分析失败（请查看日志）",
            icon="✅" if state == "done" else "❌",
        )

    with st.container(border=True):
        left, right = st.columns([0.72, 0.28], vertical_alignment="center")
        with left:
            st.markdown(f"**当前任务**：{task_name}  \n**视频**：{video_name}")
            st.caption(f"状态：{state}")
            if ts:
                st.caption(f"更新时间：{ts}")

            if enabled and _should_auto_refresh(state):
                if seconds_since_change >= AUTO_REFRESH_STALL_SEC:
                    st.warning(
                        f"状态已 {int(seconds_since_change)}s 无变化，可能卡住（建议查看日志/重跑）。"
                    )
                else:
                    st.caption(
                        f"自动刷新中…（最近变化 {int(seconds_since_change)}s 前）"
                    )

        with right:
            if st.button("↻ 刷新", width="stretch"):
                st.rerun()

        st.progress(prog)
        if msg:
            st.caption(msg)

    if enabled and _should_auto_refresh(state):
        interval_ms = _calc_refresh_interval_ms(
            state, prog, unchanged_hits=unchanged_hits
        )
        _ui_autorefresh(
            interval_ms=interval_ms, key=f"right_autorefresh_{run_dir.name}"
        )


# =========================
# UI：结果 tabs
# =========================
def render_results_tabs(run_dir: Path) -> None:
    ss = st.session_state
    debug_mode = ss.get("debug_mode", DEBUG_MODE_ENABLED)
    st.markdown("### 分析结果")
    paths = _get_run_paths(run_dir)
    tabs = st.tabs(["📝 训练报告", "🎬 关键帧", "📊 技术指标", "🧾 日志/错误"])

    with tabs[0]:
        report = _load_report(paths)
        if not report:
            st.info("报告尚未生成（任务运行中或尚未完成）。")
        else:
            analysis = report.get("analysis") or {}

            # 1) 总结
            summary = (analysis.get("summary") or "").strip()
            if summary:
                st.markdown("#### 总结")
                st.write(summary)

            st.divider()

            # 2) 主要问题（3条）
            problems = analysis.get("problems") or []
            st.markdown("#### 主要问题（3条）")
            if not problems:
                st.info("暂无 problems（可能任务未完成或模型输出为空）。")
            else:
                for i, p in enumerate(problems, 1):
                    st.markdown(f"**问题 {i}：{p.get('title', '')}**")
                    ev = (p.get("evidence") or "").strip()
                    imp = (p.get("impact") or "").strip()

                    if ev:
                        st.caption(f"证据：{ev}")

                        # 优先尝试解析帧号
                        frame_numbers = _parse_frame_evidence(ev)
                        if frame_numbers:
                            frame_images = _find_frame_images(run_dir, frame_numbers)
                            if frame_images:
                                st.markdown("**关键帧证据**：")
                                cols = st.columns(min(len(frame_images), 3))
                                for col, img_path in zip(cols, frame_images):
                                    with col:
                                        st.image(
                                            str(img_path),
                                            use_container_width=True,
                                        )
                        else:
                            # 如果没有明确帧号，尝试解析 segment 信息
                            segment_ids = _parse_segment_evidence(ev)
                            if segment_ids:
                                st.markdown("**相关段落帧**：")
                                for seg_id in segment_ids:
                                    seg_frames = _get_frames_by_segment(run_dir, seg_id)
                                    if seg_frames:
                                        st.caption(f"Segment {seg_id} 的关键帧：")
                                        cols = st.columns(min(len(seg_frames), 3))
                                        for col, img_path in zip(cols, seg_frames):
                                            with col:
                                                st.image(
                                                    str(img_path),
                                                    use_container_width=True,
                                                )
                            else:
                                # 既没有帧号也没有 segment 信息，显示所有可用的帧
                                all_frames = _list_frames(run_dir)
                                if all_frames:
                                    st.markdown(
                                        "**参考帧**（模型未指定具体帧，显示所有可用帧）："
                                    )
                                    cols = st.columns(min(len(all_frames), 4))
                                    for col, img_path in zip(cols, all_frames):
                                        with col:
                                            st.image(
                                                str(img_path),
                                                use_container_width=True,
                                            )

                    if imp:
                        st.caption(f"影响：{imp}")
                    st.divider()

            # 3) 改进措施（3条）
            imps = analysis.get("improvements") or []
            st.markdown("#### 改进措施（3条）")
            if not imps:
                st.info("暂无 improvements（可能任务未完成或模型输出为空）。")
            else:
                for i, it in enumerate(imps, 1):
                    st.markdown(f"**改进 {i}：{it.get('title', '')}**")

                    drills = it.get("drills") or []
                    checkpoints = it.get("checkpoints") or []
                    evidence = (it.get("evidence") or "").strip()

                    if drills:
                        st.markdown("训练方法：")
                        for d in drills:
                            st.write(f"- {d}")
                    if checkpoints:
                        st.markdown("检查点：")
                        for c in checkpoints:
                            st.write(f"- {c}")
                    if evidence:
                        st.caption(f"证据：{evidence}")

                        # 优先尝试解析帧号
                        frame_numbers = _parse_frame_evidence(evidence)
                        if frame_numbers:
                            frame_images = _find_frame_images(run_dir, frame_numbers)
                            if frame_images:
                                st.markdown("**关键帧证据**：")
                                cols = st.columns(min(len(frame_images), 3))
                                for col, img_path in zip(cols, frame_images):
                                    with col:
                                        st.image(
                                            str(img_path),
                                            use_container_width=True,
                                        )
                        else:
                            # 如果没有明确帧号，显示所有可用的帧作为参考
                            all_frames = _list_frames(run_dir)
                            if all_frames:
                                st.markdown("**参考帧**（显示所有可用帧供参考）：")
                                cols = st.columns(min(len(all_frames), 4))
                                for col, img_path in zip(cols, all_frames):
                                    with col:
                                        st.image(
                                            str(img_path),
                                            use_container_width=True,
                                        )

                    st.divider()

            # 4) 逐段点评（覆盖每段）
            seg_fb = analysis.get("segment_feedback") or []
            st.markdown("#### 逐段点评")
            if not seg_fb:
                st.info("暂无 segment_feedback（可能任务未完成或模型输出为空）。")
            else:
                for s in seg_fb:
                    sid = s.get("segment_id")
                    comment = (s.get("comment") or "").strip()
                    evidence = (s.get("evidence") or "").strip()

                    st.markdown(f"**Segment {sid}**")
                    if comment:
                        st.write(comment)

                    # 显示段落证据的关键帧
                    if evidence:
                        st.caption(f"证据：{evidence}")
                        frame_numbers = _parse_frame_evidence(evidence)
                        if frame_numbers:
                            frame_images = _find_frame_images(run_dir, frame_numbers)
                            if frame_images:
                                st.markdown("**关键帧证据**：")
                                cols = st.columns(min(len(frame_images), 3))
                                for col, img_path in zip(cols, frame_images):
                                    with col:
                                        st.image(
                                            str(img_path),
                                            width=200,
                                            use_container_width=True,
                                        )

                    st.divider()

            # 5) 调试模式：显示完整原始结构
            if debug_mode:
                with st.expander("查看完整报告 JSON（调试用）", expanded=False):
                    st.json(report, expanded=True)

    with tabs[1]:
        frames = _list_frames(run_dir)
        if not frames:
            st.info("关键帧尚未生成（任务运行中或尚未完成）。")
        else:
            # 读取 segments 和 report 数据，用于关联点评
            segments_data = _load_segments(paths)
            report = _load_report(paths)

            # 构建 segment_id -> 点评的映射
            segment_comments: dict[int, str] = {}
            if report:
                analysis = report.get("analysis") or {}
                seg_fb = analysis.get("segment_feedback") or []
                for s in seg_fb:
                    sid = s.get("segment_id")
                    comment = (s.get("comment") or "").strip()
                    if sid is not None and comment:
                        segment_comments[int(sid)] = comment

            # 构建帧号 -> segment_id 的映射
            frame_to_segment: dict[int, int] = {}
            if segments_data:
                segments = segments_data.get("segments", []) or []
                for seg in segments:
                    sid = seg.get("segment_id")
                    frame_indices = seg.get("frame_indices", []) or []
                    for fid in frame_indices:
                        frame_to_segment[int(fid)] = int(sid)

            cols = st.columns(4)
            for i, img in enumerate(frames[:80]):
                with cols[i % 4]:
                    st.image(str(img), width="stretch")
                    st.caption(img.name)

                    # 从文件名提取帧号
                    # 文件名格式: frame_000123.jpg 或 0001.png
                    import re

                    frame_match = re.search(r"(\d+)", img.stem)
                    if frame_match:
                        frame_num = int(frame_match.group(1))

                        # 获取该帧所属的 segment
                        sid = frame_to_segment.get(frame_num)
                        if sid is not None and sid in segment_comments:
                            # 显示该段的点评
                            st.caption(f"**Segment {sid} 点评**：")
                            st.markdown(
                                f"<small>{segment_comments[sid]}</small>",
                                unsafe_allow_html=True,
                            )

    with tabs[2]:
        feats = _load_features(paths)
        if not feats:
            st.info("技术指标尚未生成（任务运行中或尚未完成）。")
        else:
            st.json(feats, expanded=False)

    with tabs[3]:
        status = _read_json(paths.status_json)
        state, _, msg, _ = _status_to_ui(status)
        if state == "failed":
            st.error(msg or "任务失败（请查看日志）")
        logs = _load_logs(paths)
        if not logs:
            st.info("暂无日志。")
        else:
            with st.expander("展开查看日志", expanded=False):
                st.text(logs[-20000:])


# =========================
# UI：主面板
# =========================
def render_main_panel() -> None:
    ss = st.session_state
    render_upload_and_start()

    st.markdown("### 任务状态")

    selected = ss.get("selected_run_dir", "")
    if not selected:
        st.info("右侧将显示训练报告与分析结果。请先上传视频，或在左侧选择历史任务。")
        return

    run_dir = Path(selected)
    if not run_dir.exists():
        st.warning("选中的任务目录不存在。请重新选择。")
        ss["selected_run_dir"] = ""
        return

    with st.container(key=f"right_panel_{run_dir.name}"):
        render_status_strip(run_dir)
        render_results_tabs(run_dir)


def render_app() -> None:
    # 页面加载时，从 cookie 读取 user_id 并更新 URL
    # 这样可以确保关闭浏览器后重新打开时仍然能识别用户
    init_js = """
    <script>
    (function() {
        // 从 cookie 读取 user_id
        function getCookie(name) {
            const value = "; " + document.cookie;
            const parts = value.split("; " + name + "=");
            if (parts.length == 2) return parts.pop().split(";").shift();
            return null;
        }

        const userId = getCookie('coachagent_user_id');
        const urlParams = new URLSearchParams(window.location.search);
        const urlUserId = urlParams.get('user_id');

        // 如果 cookie 中有 user_id，但 URL 中没有，更新 URL 并刷新
        if (userId && !urlUserId) {
            urlParams.set('user_id', userId);
            const newUrl = window.location.pathname + '?' + urlParams.toString();
            window.history.replaceState({path: newUrl}, '', newUrl);
            console.log('URL updated from cookie:', userId, ', reloading...');
            // 刷新页面以应用新的 URL 参数
            setTimeout(function() {
                window.location.reload();
            }, 100);
        }
        // 如果 URL 中有 user_id，确保 cookie 也有（同步）
        else if (urlUserId && urlUserId !== userId) {
            const days = 365;
            const date = new Date();
            date.setTime(date.getTime() + (days * 24 * 60 * 60 * 1000));
            const expires = '; expires=' + date.toUTCString();
            document.cookie = 'coachagent_user_id=' + urlUserId + expires + '; path=/';
            console.log('Cookie updated from URL:', urlUserId);
        }
    })();
    </script>
    """
    components.html(init_js, height=0)

    st.set_page_config(
        page_title=APP_TITLE,
        layout="centered",
        initial_sidebar_state="collapsed",
    )
    st.title(APP_TITLE)
    st.caption("上传视频 → 抽帧/特征 → AI 教练报告（3个问题 + 3个改进措施）。")
    render_sidebar_panel()
    render_main_panel()
