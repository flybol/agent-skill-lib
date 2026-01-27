"""Streamlit UI components for CoachAgent.

Responsible for: sidebar, forms, buttons, task selection, right-side tabs.
No heavy computation - delegates to pipeline/steps.
"""

import logging
import time
import streamlit as st
from pathlib import Path
from typing import Any
from constants import LLM_MODELS
from constants import LLM_MODELS, DEFAULT_LLM_MODEL

from constants import (
    APP_TITLE,
    APP_SUBTITLE,
    RunState,
    SUPPORTED_VIDEO_EXTENSIONS,
    AGENT_MODE_MOCK,
    AGENT_MODE_REAL,
    PROGRESS_REFRESH_INTERVAL_MS,
)
from storage import RunPaths, list_runs, get_run_paths, read_status, read_report
from pipeline import create_run, execute_run_async
from utils import format_duration, clamp

logger = logging.getLogger(__name__)


def init_session_state() -> None:
    if "selected_run_dir" not in st.session_state:
        st.session_state.selected_run_dir = None

    if "right_last_refresh_ts" not in st.session_state:
        st.session_state.right_last_refresh_ts = 0

    if "auto_refresh_enabled" not in st.session_state:
        st.session_state.auto_refresh_enabled = False


def render_sidebar() -> None:
    st.sidebar.header("控制面板")
    # 1) 任务名称
    task_name = st.sidebar.text_input("任务名称", value="my_analysis")

    # 2) 分析模式（✅ 默认不再选“真实模式”，改为默认“模拟模式”）
    agent_mode_label = st.sidebar.radio(
        "分析模式",
        ("模拟模式", "真实模式"),
        index=0,  # ✅ 原来是 1（真实模式），改成 0（模拟模式）
        help="模拟模式用于测试；真实模式会调用模型接口",
    )
    agent_mode = AGENT_MODE_MOCK if agent_mode_label == "模拟模式" else AGENT_MODE_REAL

    # 3) 分析模型（仅真实模式显示）
    if agent_mode == AGENT_MODE_REAL:
        llm_model = st.sidebar.selectbox(
            "🧠 分析模型",
            options=list(LLM_MODELS.keys()),
            index=list(LLM_MODELS.keys()).index(DEFAULT_LLM_MODEL),
            format_func=lambda k: LLM_MODELS[k]["label"],
            help="文本模型：走特征总结；图像理解模型：直接看关键截图给教练建议",
        )
    else:
        llm_model = DEFAULT_LLM_MODEL

    # 4) 上传视频（按你的顺序放到模型选择之后）
    uploaded_file = st.sidebar.file_uploader(
        "上传视频",
        type=list({ext[1:] for ext in SUPPORTED_VIDEO_EXTENSIONS}),
        help="上传运动视频进行分析",
    )

    # 5) 高级选项
    with st.sidebar.expander("高级选项"):
        max_frames = st.slider(
            "最大帧数",
            5,
            24,
            60,
            help=(
                "控制最多抽取多少张关键帧用于分析。帧数越多，分析更细但会更慢、占用更多存储。"
            ),
        )
        num_segments = st.slider(
            "分段数量",
            2,
            10,
            2,
            help=(
                "把视频按时间切成 N 段，系统会对每一段给出单独点评（分段越多，点评越细但更耗时）。\n"
                "建议：10~20秒 6~8 段；20~40秒 8~12 段。"
            ),
        )
        st.caption(
            "提示：最大帧数影响“抽帧数量/速度/存储”；分段数量影响“逐段点评的细致程度/耗时”。"
        )

    # 开始分析按钮（保持原逻辑）
    if st.sidebar.button("开始分析", type="primary", width="stretch"):
        if not uploaded_file:
            st.sidebar.error("请先上传视频文件")
            return
        if not task_name.strip():
            st.sidebar.error("请输入任务名称")
            return

        try:
            temp_path = Path(f"temp_{uploaded_file.name}")
            with open(temp_path, "wb") as f:
                f.write(uploaded_file.read())

            paths, run_id = create_run(
                task_name=task_name.strip(),
                video_path=temp_path,
                agent_mode=agent_mode,
                llm_model=llm_model,
                max_frames=max_frames,
                num_segments=num_segments,
            )

            temp_path.unlink()
            execute_run_async(paths)
            st.session_state.selected_run_dir = paths.run_dir
            st.sidebar.success(f"已开始: {task_name}__{run_id}")
            st.rerun()

        except Exception as e:
            st.sidebar.error(f"启动分析失败: {e}")
            logger.error(f"Failed to start analysis: {e}")

    # 6) 自动刷新
    st.session_state.auto_refresh_enabled = st.sidebar.checkbox(
        "自动刷新",
        value=st.session_state.auto_refresh_enabled,
        help="自动刷新运行中的任务",
    )

    # 7) 历史任务（保持原逻辑）
    st.sidebar.divider()
    st.sidebar.subheader("历史记录")

    # ✅ 只取最近 10 条（list_runs 已按目录名倒序）
    runs = list_runs()[:10]  # :contentReference[oaicite:1]{index=1}

    if not runs:
        st.sidebar.info("暂无分析记录")
    else:
        # options 用 str，避免 Path 在 Streamlit 组件里出现序列化/比较问题
        option_keys: list[str] = [""] + [str(p.run_dir) for p in runs]

        labels: dict[str, str] = {"": "— 选择最近任务（最多10条）—"}
        for p in runs:
            status = read_status(p)
            if status is None:
                labels[str(p.run_dir)] = p.run_dir.name
                continue

            state_emoji = {
                RunState.QUEUED: "⏳",
                RunState.RUNNING: "🏃",
                RunState.DONE: "✅",
                RunState.FAILED: "❌",
            }.get(status.state, "❓")

            time_str = (status.created_at or "")[:10]
            labels[str(p.run_dir)] = f"{state_emoji} {status.task_name} ({time_str})"

        chosen = st.sidebar.selectbox(
            "最近10条任务",
            options=option_keys,
            index=0,
            format_func=lambda x: str(labels.get(x, x)),  # ✅ 必须返回 str
            key="history_select",
        )

        # 选择后切换右侧展示
        if chosen:
            chosen_path = Path(chosen)
            if st.session_state.selected_run_dir != chosen_path:
                st.session_state.selected_run_dir = chosen_path
                st.rerun()


def render_main_content() -> None:
    selected_dir = st.session_state.selected_run_dir

    if selected_dir is None:
        st.info("⌕8 从侧边栏选择任务或开始新的分析")
        return

    try:
        paths = get_run_paths_from_dir(selected_dir)
    except Exception:
        st.error("选中的分析未找到")
        st.session_state.selected_run_dir = None
        return

    render_status_header(paths)

    status = read_status(paths)
    if (
        st.session_state.auto_refresh_enabled
        and status is not None
        and status.state == RunState.RUNNING
    ):
        time.sleep(PROGRESS_REFRESH_INTERVAL_MS / 1000)
        st.rerun()

    tab1, tab2, tab3, tab4 = st.tabs(["分析报告", "视频分段", "特征分析", "执行日志"])

    with tab1:
        render_report_tab(paths)

    with tab2:
        render_segments_tab(paths)

    with tab3:
        render_features_tab(paths)

    with tab4:
        render_logs_tab(paths)


def get_run_paths_from_dir(dir_path: Path) -> RunPaths:
    dir_name = dir_path.name
    if "__" not in dir_name:
        return RunPaths.from_dir(dir_path)

    parts = dir_name.rsplit("__", 1)
    return RunPaths.from_dir(dir_path)


def render_status_header(paths: RunPaths) -> None:
    status = read_status(paths)

    if status is None:
        st.error("无状态信息")
        return

    state_color = {
        RunState.QUEUED: "blue",
        RunState.RUNNING: "orange",
        RunState.DONE: "green",
        RunState.FAILED: "red",
    }.get(status.state, "gray")

    state_label = {
        RunState.QUEUED: "等待中",
        RunState.RUNNING: "分析中",
        RunState.DONE: "已完成",
        RunState.FAILED: "失败",
    }.get(status.state, str(status.state).upper())

    # ====== ✅ 状态 + 手动刷新按钮（新增） ======
    head_l, head_r = st.columns([0.75, 0.25])
    with head_l:
        st.markdown(f"**状态:** :{state_color}[{state_label}]")
    with head_r:
        if st.button(
            "🔄 刷新状态",
            key=f"refresh_status_{paths.run_dir.name}",
            width="stretch",
        ):
            st.session_state.right_last_refresh_ts = time.time()
            st.rerun()

    # ====== ✅ 始终显示当前进度条（修改） ======
    prog = float(getattr(status, "progress", 0) or 0)
    prog = clamp(prog, 0, 100)  # clamp 在 ui.py 已 import
    st.progress(prog / 100.0)

    # 提示信息
    if status.message:
        st.info(status.message)

    if status.state == RunState.FAILED and status.error:
        st.error(f"错误: {status.error}")

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("任务", status.task_name)
    with col2:
        st.metric("运行 ID", status.run_id)
    with col3:
        st.metric("进度", f"{int(prog)}%")

    st.divider()


def _build_report_markdown(paths: RunPaths, report: dict[str, Any]) -> str:
    status = read_status(paths)
    analysis = (report or {}).get("analysis", {}) or {}

    task_name = getattr(status, "task_name", "") if status else ""
    run_id = getattr(status, "run_id", "") if status else ""
    created_at = getattr(status, "created_at", "") if status else ""

    summary = analysis.get("summary", "（无摘要）")

    problems = analysis.get("problems", []) or []
    improvements = analysis.get("improvements", []) or []
    seg_fb = analysis.get("segment_feedback", []) or []

    lines: list[str] = []
    lines.append(f"# 训练分析报告")
    if task_name or run_id:
        lines.append("")
        lines.append(f"- 任务：{task_name}")
        lines.append(f"- Run ID：{run_id}")
        if created_at:
            lines.append(f"- 创建时间：{created_at}")
    lines.append("")
    lines.append("## 总体评价")
    lines.append("")
    lines.append(summary.strip() if isinstance(summary, str) else "（无摘要）")

    lines.append("")
    lines.append("## 主要问题（3条）")
    lines.append("")
    if not problems:
        lines.append("（暂无）")
    else:
        for i, p in enumerate(problems, 1):
            title = (p.get("title") or "（无标题）").strip()
            evidence = (p.get("evidence") or "（无证据）").strip()
            impact = (p.get("impact") or "（无影响）").strip()
            lines.append(f"### {i}. {title}")
            lines.append("")
            lines.append(f"- **观察证据**：{evidence}")
            lines.append(f"- **影响**：{impact}")
            lines.append("")

    lines.append("## 改进建议（3条）")
    lines.append("")
    if not improvements:
        lines.append("（暂无）")
    else:
        for i, imp in enumerate(improvements, 1):
            title = (imp.get("title") or "（无标题）").strip()
            drills = imp.get("drills", []) or []
            checkpoints = imp.get("checkpoints", []) or []
            lines.append(f"### {i}. {title}")
            lines.append("")
            lines.append("**训练方法**：")
            if drills:
                for d in drills:
                    lines.append(f"- {str(d).strip()}")
            else:
                lines.append("- （暂无）")
            lines.append("")
            lines.append("**检查点**：")
            if checkpoints:
                for c in checkpoints:
                    lines.append(f"- {str(c).strip()}")
            else:
                lines.append("- （暂无）")
            lines.append("")

    lines.append("## 分段点评")
    lines.append("")
    if not seg_fb:
        lines.append("（暂无）")
    else:
        # 按 segment_id 排序更稳定
        try:
            seg_fb_sorted = sorted(seg_fb, key=lambda x: int(x.get("segment_id", 0)))
        except Exception:
            seg_fb_sorted = seg_fb

        for s in seg_fb_sorted:
            sid = s.get("segment_id", "?")
            comment = (s.get("comment") or "").strip()
            lines.append(f"### 分段 {sid}")
            lines.append("")
            lines.append(comment if comment else "（无点评）")
            lines.append("")

    return "\n".join(lines).strip() + "\n"


def render_report_tab(paths: RunPaths) -> None:
    report = read_report(paths)

    if report is None:
        st.info("报告尚未生成")
        return

    analysis = report.get("analysis", {})
    if not analysis:
        st.info("无分析结果")
        return

    md = _build_report_markdown(paths, report)

    # ✅ Markdown 展示
    st.markdown(md)

    # ✅ 提供下载（markdown）
    status = read_status(paths)
    task_name = getattr(status, "task_name", "report") if status else "report"
    run_id = getattr(status, "run_id", "") if status else ""
    file_name = f"{task_name}__{run_id}.md" if run_id else f"{task_name}.md"

    st.download_button(
        label="⬇️ 下载 Markdown 报告",
        data=md.encode("utf-8"),
        file_name=file_name,
        mime="text/markdown",
        key=f"download_md_{paths.run_dir.name}",
        width="stretch",
    )


def render_segments_tab(paths: RunPaths) -> None:
    """
    ✅ 正确版：同时展示
    - 抽帧图片（来自 segments.json：frames_data）
    - 分段信息（来自 features.json：segments）
    并且对 frame["path"] 的相对路径/绝对路径都做兼容处理。
    """
    from storage import read_segments, read_features

    segments_data = read_segments(paths)
    if segments_data is None:
        st.info("抽帧结果尚未生成（segments.json 不存在）")
        return

    frames = segments_data.get("frames", [])
    if not isinstance(frames, list) or not frames:
        st.warning("segments.json 中未找到 frames 列表，无法展示抽帧图片。")
        st.caption(f"segments.json keys = {list(segments_data.keys())}")
        return

    # ====== 顶部指标（抽帧结果）======
    dur = float(segments_data.get("video_duration", 0) or 0)
    fps = float(segments_data.get("frame_rate", 0) or 0)
    fc = int(segments_data.get("frame_count", 0) or len(frames))

    col1, col2, col3, col4 = st.columns([1, 1, 1, 1])
    with col1:
        st.metric("时长", f"{dur:.2f} 秒")
    with col2:
        st.metric("帧率", f"{fps:.0f} fps" if fps else "N/A")
    with col3:
        st.metric("抽帧数", fc)
    with col4:
        st.metric("视频总帧", int(segments_data.get("total_frames_in_video", 0) or 0))

    st.divider()

    # ====== 抽帧图片展示（可配置数量）======
    st.subheader("提取的关键帧")

    max_show = st.slider(
        "最多显示帧数",
        min_value=8,
        max_value=min(120, max(8, len(frames))),
        value=min(24, len(frames)),
        step=4,
        key=f"seg_show_max_{paths.run_dir.name}",
        help="仅影响展示数量，不影响抽帧结果。",
    )

    cols_per_row = st.selectbox(
        "每行列数",
        options=[3, 4, 5, 6],
        index=1,
        key=f"seg_cols_{paths.run_dir.name}",
    )

    display_frames = frames[:max_show]

    def _resolve_frame_path(frame_path_value: str) -> Path:
        """把 segments.json 里的 frame['path'] 解析成可用的磁盘路径。"""
        p = Path(frame_path_value)

        # 1) 已经是绝对路径且存在
        if p.is_absolute() and p.exists():
            return p

        # 2) 相对 run_dir 的路径（你当前 extract_frames 写入的就是这种：frames/xxx.jpg）
        cand = paths.run_dir / p
        if cand.exists():
            return cand

        # 3) 兜底：如果 path 里只存了文件名，默认在 run_dir/frames 下
        cand2 = paths.run_dir / "frames" / p.name
        if cand2.exists():
            return cand2

        return cand  # 返回最可能的位置，便于 warning 展示

    for i in range(0, len(display_frames), cols_per_row):
        cols = st.columns(cols_per_row)
        for j in range(cols_per_row):
            idx = i + j
            if idx >= len(display_frames):
                break

            frame = display_frames[idx]
            fp_val = str(frame.get("path", "") or "")
            frame_idx = frame.get("frame_index", "?")
            ts = frame.get("timestamp", "?")

            frame_path = _resolve_frame_path(fp_val)

            with cols[j]:
                if fp_val and frame_path.exists():
                    st.image(
                        str(frame_path),
                        caption=f"帧 {frame_idx} @ {ts}s",
                        width="stretch",
                    )
                else:
                    st.warning(f"帧 {frame_idx} 未找到")
                    st.caption(f"path={fp_val}")
                    st.caption(f"resolved={frame_path}")

    st.divider()

    # ====== 分段信息（来自 features.json）======
    st.subheader("视频分段信息（用于分析）")

    features_data = read_features(paths)
    if not features_data:
        st.info("分段信息尚未生成（features.json 不存在）")
        return

    segs = features_data.get("segments", [])
    if not isinstance(segs, list) or not segs:
        st.info("features.json 中没有 segments 分段信息。")
        st.caption(f"features.json keys = {list(features_data.keys())}")
        return

    seg_count = int(features_data.get("segment_count", len(segs)) or len(segs))
    st.caption(f"共 {seg_count} 段")

    for seg in segs:
        sid = seg.get("segment_id", "?")
        stt = seg.get("start_time", 0)
        edt = seg.get("end_time", 0)
        fcnt = seg.get("frame_count", 0)

        with st.expander(f"分段 {sid}: {stt}s - {edt}s（{fcnt} 帧）", expanded=False):
            st.write(f"**时长:** {seg.get('duration', 0):.2f} 秒")
            indices = seg.get("frame_indices", []) or []
            if indices:
                preview = ", ".join(str(x) for x in indices[:20])
                st.write(
                    f"**帧索引（前20个）:** {preview}{' ...' if len(indices) > 20 else ''}"
                )
            else:
                st.info("该段没有 frame_indices（MVP 可能是空）。")


def render_features_tab(paths: RunPaths) -> None:
    from storage import read_features

    features_data = read_features(paths)

    if features_data is None:
        st.info("特征尚未计算")
        return

    segments = features_data.get("segments", [])
    if not segments:
        st.info("无分段信息")
        return

    st.subheader("视频分段")

    for segment in segments:
        with st.expander(
            f"分段 {segment['segment_id']}: "
            f"{segment['start_time']}秒 - {segment['end_time']}秒 "
            f"({segment['frame_count']}帧)"
        ):
            st.write(f"**时长:** {segment['duration']:.2f}秒")
            st.write(
                f"**帧索引:** {', '.join(str(f) for f in segment['frame_indices'][:10])}{'...' if len(segment['frame_indices']) > 10 else ''}"
            )


def render_logs_tab(paths: RunPaths) -> None:
    from storage import read_logs

    logs = read_logs(paths, max_lines=100)

    st.subheader("执行日志")

    st.text_area(
        "日志",
        value=logs,
        height=400,
        disabled=True,
        key=f"logs_{paths.run_dir.name}",
    )

    if st.button("刷新日志", key="refresh_logs"):
        st.rerun()


def render_app() -> None:
    init_session_state()
    col1, col2 = st.columns([1, 4])
    with col1:
        render_sidebar()

    with col2:
        render_main_content()
