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
    MAX_BYTES,
    MAX_UPLOAD_MB,
)
from streamlit_autorefresh import st_autorefresh
import pipeline
import storage

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


# =========================
# UI：Sidebar 操作面板
# 目标：默认无需用户操作（上传 + 开始分析即可）
# 保留能力：1) 任务名称 2) 分析参数 3) 历史任务
# =========================
def render_sidebar_panel() -> None:
    ss = st.session_state
    ss.setdefault("selected_run_dir", "")
    ss.setdefault("task_name", datetime.now().strftime("%Y%m%d_%H%M"))
    ss.setdefault("auto_refresh_enabled", False)
    ss.setdefault("llm_model", DEFAULT_LLM_MODEL)
    ss.setdefault("num_segments", DEFAULT_SEGMENTS)

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

        with st.expander("展开设置", expanded=False):
            if is_running:
                st.info("任务运行中：参数仅对下一次分析生效。")

            # 自动刷新允许运行中随时开关（对当前任务有意义）
            ss["auto_refresh_enabled"] = st.toggle(
                "自动刷新",
                value=bool(ss.get("auto_refresh_enabled", False)),
                help="开启后，任务运行中会自动刷新右侧进度与结果；默认关闭。",
            )

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
            task_name = status.get("task_name") or p.name.split("__")[0]
            labels[str(p)] = f"{dot} {task_name} · {p.name.split('__')[-1]}"

        options = [""] + [str(p) for p in run_dirs]

        def _fmt(x: str) -> str:
            if not x:
                return "（未选择任务）"
            return labels.get(x, Path(x).name)

        with st.expander("展开查看最近任务", expanded=False):
            chosen = st.selectbox(
                "最近10条",
                options=options,
                index=0
                if ss.get("selected_run_dir", "") not in options
                else options.index(ss.get("selected_run_dir", "")),
                format_func=_fmt,
            )
            ss["selected_run_dir"] = chosen

            if not ss["selected_run_dir"]:
                st.caption("未选择历史任务。")
            else:
                run_dir = Path(ss["selected_run_dir"])
                paths = _get_run_paths(run_dir)
                status = _read_json(paths.status_json)
                state, prog, msg, ts = _status_to_ui(status)
                task_name = status.get("task_name") or run_dir.name.split("__")[0]

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

/* 替换第二行：Limit 200MB per file • ... */
section[data-testid="stFileUploaderDropzone"]
  div[data-testid="stFileUploaderDropzoneInstructions"] > div:nth-child(2) > span:nth-child(2)::after {
  content: "单文件最大 10MB • 支持 MP4 / AVI / MOV / MKV / MPEG4";
  visibility: visible;
  position: absolute;
  left: 0;
  top: 0;
  white-space: nowrap;
}
span[data-testid="stFileUploaderFileErrorMessage"]{
  visibility: hidden;
  position: relative;
  display: inline-block; /* 保证伪元素定位稳定 */
  min-height: 1em;
}

span[data-testid="stFileUploaderFileErrorMessage"]::after{
  content: "文件大小不能超过 50MB。";
  visibility: visible;
  position: absolute;
  left: 0;
  top: 0;
  white-space: nowrap;
}

/* ✅ 替换上传错误提示：File must be 50.0MB or smaller. */
span[data-testid="stFileUploaderFileErrorMessage"]{
  visibility: hidden;
  position: relative;
  display: inline-block; /* 保证伪元素定位稳定 */
  min-height: 1em;
}

span[data-testid="stFileUploaderFileErrorMessage"]::after{
  content: "文件大小不能超过 50MB。";
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
        if uploaded is not None:
            ss["uploaded_file"] = uploaded
        uploaded = ss.get("uploaded_file")
        st.caption("建议 1~3 秒，尽量拍到完整准备动作与击球瞬间。")

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
            ss["auto_refresh_enabled"] = True  # ✅ 开始后默认开启自动刷新
            st.success("已开始分析（后台执行中）。")
            if ss.get("auto_refresh_enabled", False):
                st.caption("已开启自动刷新：右侧会自动更新进度。")
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
    render_sidebar_panel()
    render_main_panel()
