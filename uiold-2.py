# ui.py (CLEANED)
from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import streamlit as st

from constants import (
    AGENT_MODE_REAL,
    DEFAULT_LLM_MODEL,
    DEFAULT_SEGMENTS,
    POSE_MAX_FRAMES,
)

import pipeline
import storage

# =========================
# 基础配置
# =========================
APP_TITLE = "乒乓数字教练"
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


def _ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    RUNS_DIR.mkdir(parents=True, exist_ok=True)


def _slugify_task_name(s: str) -> str:
    s = (s or "").strip()
    if not s:
        return ""
    return storage.clean_filename(s) if hasattr(storage, "clean_filename") else s


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
    _ensure_dirs()
    runs = [p for p in RUNS_DIR.iterdir() if p.is_dir()]
    runs.sort(key=lambda p: p.stat().st_mtime, reverse=True)
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


def _load_logs(paths: storage.RunPaths) -> str:
    return storage.read_logs(paths, max_lines=None)


# =========================
# UI：Sidebar 历史
# =========================
def render_sidebar_history() -> None:
    ss = st.session_state
    ss.setdefault("selected_run_dir", "")

    st.sidebar.title("CoachAgent")
    st.sidebar.caption("选择历史任务，或在右侧上传视频创建新任务。")

    run_dirs = _list_run_dirs(limit=RECENT_LIMIT)

    labels: dict[str, str] = {}
    for p in run_dirs:
        paths = _get_run_paths(p)
        status = _read_json(paths.status_json)
        state, prog, _, _ts = _status_to_ui(status)
        dot = {
            "done": "🟢",
            "running": "🟡",
            "queued": "🟡",
            "pending": "🟡",
            "failed": "🔴",
        }.get(state, "⚪")
        task_name = status.get("task_name") or p.name.split("__")[0]
        labels[str(p)] = f"{dot} {task_name} · {p.name.split('__')[-1]}"

    options = [""] + [str(p) for p in run_dirs]

    def _fmt(x: str) -> str:
        if not x:
            return "（未选择任务）"
        return labels.get(x, Path(x).name)

    chosen = st.sidebar.selectbox(
        "历史任务（最近10条）",
        options=options,
        index=0
        if ss["selected_run_dir"] not in options
        else options.index(ss["selected_run_dir"]),
        format_func=_fmt,
    )
    ss["selected_run_dir"] = chosen

    st.sidebar.divider()
    if not ss["selected_run_dir"]:
        st.sidebar.info("右侧上传视频后会自动创建任务。")
        return

    run_dir = Path(ss["selected_run_dir"])
    paths = _get_run_paths(run_dir)
    status = _read_json(paths.status_json)
    state, prog, msg, ts = _status_to_ui(status)
    task_name = status.get("task_name") or run_dir.name.split("__")[0]

    with st.sidebar.container(border=True):
        st.markdown(f"**当前任务**：{task_name}")
        st.markdown(f"**状态**：`{state}`")
        st.progress(prog)
        if msg:
            st.caption(msg)
        if ts:
            st.caption(f"更新时间：{ts}")


# =========================
# UI：上传与启动
# =========================
def render_upload_and_start() -> None:
    ss = st.session_state
    ss.setdefault("task_name", datetime.now().strftime("%Y%m%d_%H%M"))
    ss.setdefault("uploaded_file", None)

    with st.container(border=True):
        st.markdown("### Step 1 · 上传训练视频")
        uploaded = st.file_uploader(
            "拖拽或选择视频文件（mp4/mov/mkv/avi）",
            type=[e.lstrip(".") for e in SUPPORTED_VIDEO_EXTS],
            accept_multiple_files=False,
        )
        if uploaded is not None:
            ss["uploaded_file"] = uploaded
        uploaded = ss.get("uploaded_file")
        st.caption("建议 5~20 秒，尽量拍到完整准备动作与击球瞬间。")

        st.markdown("### Step 2 · 任务名称（用于历史记录）")
        task_name = st.text_input("任务名称", value=ss["task_name"])
        ss["task_name"] = task_name

        st.markdown("### Step 3 · 分析参数")
        agent_mode = AGENT_MODE_REAL

        c2, c3 = st.columns(2)
        with c2:
            llm_model = st.selectbox(
                "分析模型", [DEFAULT_LLM_MODEL, "glm-4.6v-flash"], index=0
            )
        with c3:
            num_segments = st.number_input(
                "分段数量", min_value=1, max_value=16, value=DEFAULT_SEGMENTS, step=1
            )

        expected_total = int(num_segments) * FRAMES_PER_SEGMENT
        max_frames = min(expected_total, int(POSE_MAX_FRAMES))
        st.caption(
            f"抽帧策略：按时间均分 {num_segments} 段，每段均匀抽 {FRAMES_PER_SEGMENT} 帧"
            f"（预计总帧数≈ {expected_total}，上限兜底= {max_frames}）。"
        )

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
        safe_name = storage.clean_filename(Path(uploaded.name).stem) + suffix
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
            )
        except Exception as e:
            st.error(f"创建任务失败：{e}")
            return

        ss["selected_run_dir"] = str(paths.run_dir)

        # 3) 后台启动执行
        try:
            pipeline.start_background_run(paths, overwrite=True)
            st.success("已开始分析（后台执行中），右侧会自动刷新进度。")
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
    ss.setdefault(f"{key_prefix}::enabled", True)
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

    # 完成/失败自动关闭
    if state in {"done", "failed"}:
        ss[f"{key_prefix}::enabled"] = False

    enabled = bool(ss[f"{key_prefix}::enabled"])

    # Toast 一次
    if state in {"done", "failed"} and not ss.get(
        f"{key_prefix}::completed_toast", False
    ):
        ss[f"{key_prefix}::completed_toast"] = True
        st.toast(
            "✅ 分析完成" if state == "done" else "❌ 分析失败（请查看日志）",
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
            ss[f"{key_prefix}::enabled"] = st.toggle("自动刷新", value=enabled)

        st.progress(prog)
        if msg:
            st.caption(msg)

    if ss[f"{key_prefix}::enabled"] and _should_auto_refresh(state):
        interval_ms = _calc_refresh_interval_ms(
            state, prog, unchanged_hits=unchanged_hits
        )
        autorefresh = getattr(st, "autorefresh", None)
        if callable(autorefresh):
            autorefresh(interval=interval_ms, key=f"right_autorefresh_{run_dir.name}")


# =========================
# UI：结果 tabs
# =========================
def render_results_tabs(run_dir: Path) -> None:
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
                    st.markdown(f"**Segment {sid}**")
                    if comment:
                        st.write(comment)
                    st.divider()

            # 5) 保留“完整原始结构”给你调试（可折叠）
            with st.expander("查看完整报告 JSON（调试用）", expanded=False):
                st.json(report, expanded=True)

    with tabs[1]:
        frames = _list_frames(run_dir)
        if not frames:
            st.info("关键帧尚未生成（任务运行中或尚未完成）。")
        else:
            cols = st.columns(4)
            for i, img in enumerate(frames[:80]):
                with cols[i % 4]:
                    st.image(str(img), width="stretch")
                    st.caption(img.name)

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

    st.subheader("上传与启动")
    render_upload_and_start()

    st.divider()
    st.subheader("训练结果")

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
    st.set_page_config(
        page_title=APP_TITLE,
        layout="centered",
        initial_sidebar_state="collapsed",
    )
    st.title(APP_TITLE)
    st.caption("上传视频 → 抽帧/特征 → AI 教练报告（3个问题 + 3个改进措施）。")

    render_sidebar_history()
    render_main_panel()
