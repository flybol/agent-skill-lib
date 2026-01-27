from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timedelta, timezone
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
        "pending": "等待中",
        "queued": "队列中",
        "running": "运行中",
        "processing": "运行中",
        "done": "已完成",
        "success": "已完成",
        "failed": "失败",
        "error": "失败",
        "unknown": "未知",
    }
    return m.get(s, s)


def _format_timestamp(ts: str) -> str:
    """将时间戳格式化为中国上海时区。

    Args:
        ts: ISO 8601 格式的时间戳字符串

    Returns:
        格式化后的时间字符串，如 "2026-01-27 23:02:06"
    """
    if not ts:
        return ""

    try:
        # 解析 ISO 8601 时间戳
        dt = datetime.fromisoformat(ts)

        # 转换为中国上海时区（UTC+8）
        # 使用 timezone.timedelta 模拟时区偏移
        tz_offset = timezone(timedelta(hours=8))
        dt_shanghai = dt.astimezone(tz_offset)

        return dt_shanghai.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        # 解析失败，返回原始字符串
        return ts


def _status_to_ui(status: dict[str, Any]) -> tuple[str, str, float, str, str]:
    raw_state = str(status.get("state") or "unknown")
    pretty_state = _pretty_state(raw_state)
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
    ts_raw = str(
        status.get("completed_at")
        or status.get("started_at")
        or status.get("created_at")
        or ""
    )
    ts = _format_timestamp(ts_raw)
    return raw_state, pretty_state, prog_f, msg, ts


def _should_auto_refresh(state: str) -> bool:
    return state.lower() in {"queued", "pending", "running", "processing", "unknown"}


def _calc_refresh_interval_ms(state: str, prog: float, *, unchanged_hits: int) -> int:
    s = state.lower()
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
    1. 扫描用户子目录 data/runs/{user_id}/ 中的任务

    Returns:
        按修改时间倒序排列的任务目录列表
    """
    _ensure_dirs()
    user_id = st.session_state.get("user_id", "")
    runs = []

    # 需要跳过的目录名称（非任务目录）
    SKIP_DIR_NAMES = {"frames", "input", "segments", "output", "__pycache__", ".git"}

    # 扫描当前用户的子目录
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
            logger.info(
                f"User directory does not exist: {user_dir} (new user, no tasks yet)"
            )
    else:
        logger.warning("user_id is empty, cannot scan user directory")

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


# =========================
# 报告导出功能
# =========================


def _format_report_as_markdown(
    report: dict[str, Any],
    task_name: str,
    video_name: str,
    analysis_time: str,
) -> str:
    """将报告格式化为 Markdown 文档。

    Args:
        report: 报告数据
        task_name: 任务名称
        video_name: 视频名称
        analysis_time: 分析时间

    Returns:
        Markdown 格式的报告文本
    """
    analysis = report.get("analysis") or {}

    # 检查是否为教练实战版格式
    is_coach_report = "one_sentence" in analysis

    lines = []
    lines.append(f"# {task_name} - 训练报告")
    lines.append("")
    lines.append(f"**视频名称**：{video_name}  ")
    lines.append(f"**分析时间**：{analysis_time}  ")
    lines.append("")
    lines.append("---")
    lines.append("")

    if is_coach_report:
        # 教练实战版格式
        one_sentence = (analysis.get("one_sentence") or "").strip()
        if one_sentence:
            lines.append("## 一句话总结")
            lines.append("")
            lines.append(f"> {one_sentence}")
            lines.append("")
            lines.append("---")
            lines.append("")

        # 核心问题
        top_problems = analysis.get("top_problems") or []
        if top_problems:
            lines.append("## 核心问题（3条）")
            lines.append("")
            for p in top_problems:
                prob_id = p.get("id", "")
                title = p.get("title", "")
                key_features = p.get("key_features") or []
                direct_consequences = p.get("direct_consequences") or []
                coach_judgment = p.get("coach_judgment", "")

                lines.append(f"### {prob_id}：{title}")
                lines.append("")

                if key_features:
                    lines.append("**关键表现**（你现在在做什么）：")
                    lines.append("")
                    for f in key_features:
                        lines.append(f"- {f}")
                    lines.append("")

                if direct_consequences:
                    lines.append("**直接后果**（比赛会发生什么）：")
                    lines.append("")
                    for c in direct_consequences:
                        lines.append(f"- {c}")
                    lines.append("")

                if coach_judgment:
                    lines.append(f"> 💡 教练判断：{coach_judgment}")
                    lines.append("")

                lines.append("---")
                lines.append("")

        # 训练计划
        training_plan = analysis.get("training_plan") or {}
        if training_plan:
            session_goal = training_plan.get("session_goal", "")
            improvements = training_plan.get("improvements") or []

            lines.append("## 训练计划")
            lines.append("")

            if session_goal:
                lines.append(f"**本次训练目标**：{session_goal}")
                lines.append("")
                lines.append("---")
                lines.append("")

            if improvements:
                for imp in improvements:
                    title = imp.get("title", "")
                    training_methods = imp.get("training_methods") or []
                    self_check_criteria = imp.get("self_check_criteria") or []

                    lines.append(f"### {title}")
                    lines.append("")

                    if training_methods:
                        lines.append("**训练方法**：")
                        lines.append("")
                        for m in training_methods:
                            lines.append(f"- {m}")
                        lines.append("")

                    if self_check_criteria:
                        lines.append("**自检标准**：")
                        lines.append("")
                        for c in self_check_criteria:
                            lines.append(f"- {c}")
                        lines.append("")

                    lines.append("---")
                    lines.append("")

        # 分段点评
        segment_notes = analysis.get("segment_notes") or []
        if segment_notes:
            lines.append("## 分段点评")
            lines.append("")

            for note in segment_notes:
                seg_id = note.get("segment_id")
                title = note.get("title", "")
                coach_comment = note.get("coach_comment", "")
                evidence = note.get("evidence") or []

                lines.append(f"### {title}（Segment {seg_id}）")
                lines.append("")

                if coach_comment:
                    lines.append(coach_comment)
                    lines.append("")

                if evidence:
                    frame_numbers = [
                        e.get("frame_index")
                        for e in evidence
                        if e.get("frame_index") is not None
                    ]
                    if frame_numbers:
                        lines.append(
                            f"**关键帧证据**：帧号 {', '.join(map(str, frame_numbers))}"
                        )
                        lines.append("")

                lines.append("---")
                lines.append("")

    else:
        # 旧格式兼容
        summary = (analysis.get("summary") or "").strip()
        if summary:
            lines.append("## 总结")
            lines.append("")
            lines.append(summary)
            lines.append("")
            lines.append("---")
            lines.append("")

        # 主要问题
        problems = analysis.get("problems") or []
        if problems:
            lines.append("## 主要问题（3条）")
            lines.append("")
            for i, p in enumerate(problems, 1):
                title = p.get("title", "")
                impact = (p.get("impact") or "").strip()
                lines.append(f"### 问题 {i}：{title}")
                lines.append("")
                if impact:
                    lines.append(f"**影响**：{impact}")
                    lines.append("")
                lines.append("---")
                lines.append("")

        # 改进措施
        improvements = analysis.get("improvements") or []
        if improvements:
            lines.append("## 改进措施（3条）")
            lines.append("")
            for i, imp in enumerate(improvements, 1):
                title = imp.get("title", "")
                drills = imp.get("drills") or []
                checkpoints = imp.get("checkpoints") or []

                lines.append(f"### 改进 {i}：{title}")
                lines.append("")

                if drills:
                    lines.append("**训练方法**：")
                    lines.append("")
                    for d in drills:
                        lines.append(f"- {d}")
                    lines.append("")

                if checkpoints:
                    lines.append("**检查点**：")
                    lines.append("")
                    for c in checkpoints:
                        lines.append(f"- {c}")
                    lines.append("")

                lines.append("---")
                lines.append("")

        # 逐段点评
        segment_feedback = analysis.get("segment_feedback") or []
        if segment_feedback:
            lines.append("## 逐段点评")
            lines.append("")
            for s in segment_feedback:
                sid = s.get("segment_id")
                comment = (s.get("comment") or "").strip()
                evidence = (s.get("evidence") or "").strip()

                lines.append(f"### Segment {sid}")
                lines.append("")

                if comment:
                    lines.append(comment)
                    lines.append("")

                if evidence:
                    lines.append(f"**证据**：{evidence}")
                    lines.append("")

                lines.append("---")
                lines.append("")

    # 页脚
    lines.append("---")
    lines.append("")
    lines.append(f"*本报告由 AI 教练分析生成，分析时间：{analysis_time}*")
    lines.append("")

    return "\n".join(lines)


def _generate_markdown_filename(task_name: str) -> str:
    """生成 Markdown 导出文件名。"""
    safe_name = clean_filename(task_name)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{safe_name}_训练报告_{timestamp}.md"


def _render_export_buttons(
    run_dir: Path,
    task_name: str,
    video_name: str,
) -> None:
    """渲染报告导出按钮（Markdown）。

    Args:
        run_dir: 任务目录
        task_name: 任务名称
        video_name: 视频名称
    """
    paths = _get_run_paths(run_dir)
    report = _load_report(paths)

    if not report:
        return

    # 读取分析时间
    status = _read_json(paths.status_json)
    analysis_time = status.get(
        "updated_at", datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    )

    # 生成 Markdown
    markdown_content = _format_report_as_markdown(
        report, task_name, video_name, analysis_time
    )
    markdown_filename = _generate_markdown_filename(task_name)

    st.markdown("### 📥 导出报告")

    st.download_button(
        label="📄 下载 Markdown (.md)",
        data=markdown_content.encode("utf-8"),
        file_name=markdown_filename,
        mime="text/markdown",
        width="stretch",
    )


def _render_metrics_panel(
    feats: dict[str, Any], segs: dict[str, Any], run_dir: Path
) -> None:
    """渲染技术指标面板。

    根据设计文档分层展示：
    - Level 1: 默认展示（普通用户）
    - Level 2: 展开详情（进阶用户）
    - Level 3: 调试模式（开发/高级用户）
    """
    ss = st.session_state
    debug_mode = ss.get("debug_mode", DEBUG_MODE_ENABLED)

    # 从 features 和 segments 获取数据
    video_duration = float(feats.get("video_duration", 0) or 0)
    frame_rate = float(feats.get("frame_rate", 30) or 30)
    segment_count = int(feats.get("segment_count", 0) or 0)
    segments = feats.get("segments", [])

    # 从 segments 获取抽帧数据
    total_frames_extracted = int(segs.get("frame_count", 0) or 0)
    total_frames_in_video = int(segs.get("total_frames_in_video", 0) or 0)

    # 计算抽帧比例
    extraction_ratio = (
        (total_frames_extracted / total_frames_in_video * 100)
        if total_frames_in_video > 0
        else 0
    )

    # 计算平均段长
    avg_segment_duration = video_duration / segment_count if segment_count > 0 else 0

    # 查找最长/最短段落
    if segments:
        longest_seg = max(segments, key=lambda s: s.get("duration", 0))
        shortest_seg = min(segments, key=lambda s: s.get("duration", 0))
    else:
        longest_seg = None
        shortest_seg = None

    # ============================================================================
    # Level 1: 默认展示（普通用户）
    # ============================================================================
    st.markdown("#### 📊 核心指标")

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("视频时长", f"{video_duration:.1f}s")
    with col2:
        st.metric("抽帧数量", str(total_frames_extracted))
    with col3:
        st.metric("动作段数", str(segment_count))
    with col4:
        # 简化的可信度评分
        quality_score = min(100, int(extraction_ratio + 50))
        st.metric("分析可信度", f"{quality_score}/100")

    st.caption(
        f"💡 **AI 分析了 {total_frames_extracted} 帧"
        f"（占原视频 {extraction_ratio:.1f}%），"
        f"分为 {segment_count} 个动作段进行分析。"
    )

    # ============================================================================
    # Level 2: 展开详情（进阶用户）
    # ============================================================================
    with st.expander("📹 视频基础信息", expanded=False):
        col1, col2, col3 = st.columns(3)
        with col1:
            st.write(f"**视频时长**: {video_duration:.2f} 秒")
            st.write(f"**帧率 (FPS)**: {frame_rate:.1f}")
        with col2:
            st.write(f"**总帧数**: {total_frames_in_video}")
            st.write(f"**抽帧数量**: {total_frames_extracted}")
        with col3:
            st.write(f"**抽帧比例**: {extraction_ratio:.1f}%")
            st.write(f"**抽帧策略**: 均匀分段（每段 5 帧）")

        # 推荐提示
        if video_duration < 3:
            st.warning(
                "⚠️ 视频过短（< 3秒），建议使用 3-12 秒的视频以获得更好的分析效果。"
            )
        elif video_duration > 12:
            st.warning("⚠️ 视频较长（> 12秒），建议截取关键动作片段以提高分析精度。")
        else:
            st.success("✅ 视频时长适中，适合进行技术分析。")

        if frame_rate < 25:
            st.warning("⚠️ 帧率较低（< 25 FPS），可能影响动作识别精度。")
        else:
            st.success("✅ 帧率良好（≥ 25 FPS），动作捕捉流畅。")

    with st.expander("🧩 抽帧与分段详情", expanded=False):
        st.markdown("**抽帧信息**")
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("抽帧数量", str(total_frames_extracted))
        with col2:
            st.metric("抽帧比例", f"{extraction_ratio:.1f}%")
        with col3:
            st.metric("抽帧间隔", f"均匀分段")

        st.markdown("**动作分段信息**")
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("动作段数", str(segment_count))
        with col2:
            st.metric("平均段长", f"{avg_segment_duration:.2f}s")
        with col3:
            if longest_seg:
                st.metric(
                    "最长段落",
                    f"段 {longest_seg.get('segment_id') + 1}",
                    help=f"{longest_seg.get('start_time', 0):.1f}s - {longest_seg.get('end_time', 0):.1f}s",
                )
        with col4:
            if shortest_seg:
                st.metric(
                    "最短段落",
                    f"段 {shortest_seg.get('segment_id') + 1}",
                    help=f"{shortest_seg.get('start_time', 0):.1f}s - {shortest_seg.get('end_time', 0):.1f}s",
                )

        # 分段详情表格
        if segments:
            st.markdown("**各段落详情**")
            seg_data = []
            for seg in segments:
                seg_data.append(
                    {
                        "段落": f"段 {seg.get('segment_id') + 1}",
                        "时长": f"{seg.get('duration', 0):.2f}s",
                        "时间范围": f"{seg.get('start_time', 0):.1f}s - {seg.get('end_time', 0):.1f}s",
                        "帧数": seg.get("frame_count", 0),
                    }
                )
            st.dataframe(
                seg_data,
                width="stretch",
                hide_index=True,
            )

            # 段落分布可视化
            st.markdown("**段落时间分布**")
            import matplotlib.pyplot as plt

            fig, ax = plt.subplots(figsize=(10, 1))
            y_pos = 0
            for i, seg in enumerate(segments):
                start = seg.get("start_time", 0)
                duration = seg.get("duration", 0)
                ax.barh(y_pos, duration, left=start, height=0.5, color=f"C{i}")
                ax.text(
                    start + duration / 2,
                    y_pos,
                    f"段{i + 1}",
                    ha="center",
                    va="center",
                    fontsize=8,
                    color="white",
                )
            ax.set_xlim(0, video_duration)
            ax.set_ylim(-0.5, 0.5)
            ax.set_xlabel("时间 (秒)")
            ax.set_yticks([])
            ax.set_title("动作段落时间分布图")
            st.pyplot(fig)
            plt.close()

    with st.expander("🧍 姿态识别质量", expanded=False):
        # 简化的稳定性指标（基于抽帧数据）
        stability_score = min(5, int(total_frames_extracted / 10) + 1)
        stars = "⭐" * stability_score + "☆" * (5 - stability_score)

        col1, col2 = st.columns(2)
        with col1:
            st.metric("姿态稳定性", stars)
        with col2:
            quality_label = "良好" if frame_rate >= 25 else "一般"
            st.metric("画面质量", quality_label)

        st.caption(
            f"💡 基于 {total_frames_extracted} 帧的分析，"
            f"姿态识别{'稳定' if stability_score >= 3 else '可能不稳定'}。"
        )

        # 帧数分布
        if segments:
            frame_counts = [seg.get("frame_count", 0) for seg in segments]
            fig, ax = plt.subplots(figsize=(10, 3))
            ax.bar(range(1, len(frame_counts) + 1), frame_counts, color="steelblue")
            ax.set_xlabel("段落编号")
            ax.set_ylabel("帧数")
            ax.set_title("各段落帧数分布")
            ax.grid(axis="y", alpha=0.3)
            st.pyplot(fig)
            plt.close()

    with st.expander("🤖 AI 分析质量评估", expanded=False):
        col1, col2, col3 = st.columns(3)
        with col1:
            # 有效分析帧占比 = 抽帧数 / 总帧数
            valid_ratio = extraction_ratio
            st.metric("有效分析帧占比", f"{valid_ratio:.1f}%")
        with col2:
            # 低置信帧数量（简化：基于抽帧稀疏度）
            low_conf = max(0, total_frames_in_video - total_frames_extracted)
            st.metric("未采样帧数", str(low_conf))
        with col3:
            st.metric("分析模式", "连续动作")

        st.caption(
            f"💡 AI 基于均匀分段策略分析视频，"
            f"每段固定采样 5 帧，共分析 {total_frames_extracted} 个关键帧。"
        )

    with st.expander("🎯 教学可用性评估", expanded=False):
        # 简化的教学可用性评估
        completeness = "✅ 良好" if 3 <= video_duration <= 12 else "⚠️ 一般"
        rhythm = "⚠️ 偏快" if avg_segment_duration < 0.5 else "✅ 适中"
        teachability_score = min(5, 3 + (1 if 3 <= video_duration <= 12 else 0))
        teachability_stars = "⭐" * teachability_score + "☆" * (5 - teachability_score)

        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("动作完整度", completeness)
        with col2:
            st.metric("节奏一致性", rhythm)
        with col3:
            st.metric("可教学性", teachability_stars)

        st.caption(
            f"💡 {'视频适合作为教学素材' if teachability_score >= 4 else '视频可作为参考，但建议优化'}"
        )

    # ============================================================================
    # Level 3: 调试模式（开发/高级用户）
    # ============================================================================
    if debug_mode:
        st.divider()
        st.markdown("#### 🔧 调试模式 (Debug Mode)")

        with st.expander("原始 Features 数据", expanded=False):
            st.json(feats, expanded=False)

        with st.expander("原始 Segments 数据", expanded=False):
            st.json(segs, expanded=False)

        st.caption("ℹ️ 以上为原始数据格式，用于开发调试和问题排查。")


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
    raw_state, _pretty_state, _prog, _msg, _ts = _status_to_ui(status)
    return raw_state in {"queued", "pending", "running", "processing", "unknown"}


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
                raw_state, _pretty_state, _prog, _msg, _ts = _status_to_ui(status)
                if raw_state == "queued":
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
# 用户 ID 辅助函数
# =========================
def _update_user_id_in_browser(user_id: str) -> None:
    """将 user_id 同步到 localStorage 和 Cookie。

    Args:
        user_id: 用户 ID
    """
    js_code = f"""
    <script>
    (function() {{
        const key = 'coachagent_user_id';
        const value = '{user_id}';

        // 优先存储到 localStorage（更可靠）
        try {{
            localStorage.setItem(key, value);
            console.log('User ID stored to localStorage:', value);
        }} catch (e) {{
            console.warn('Failed to store to localStorage:', e);
        }}

        // 同时设置 Cookie（备用）
        const days = 365;
        const date = new Date();
        date.setTime(date.getTime() + (days * 24 * 60 * 60 * 1000));
        const expires = '; expires=' + date.toUTCString();
        document.cookie = key + '=' + value + expires + '; path=/; SameSite=Lax';
        console.log('User ID stored to cookie:', value);

        // 更新 URL 参数（保持一致性）
        const urlParams = new URLSearchParams(window.location.search);
        if (urlParams.get('user_id') !== value) {{
            urlParams.set('user_id', value);
            const newUrl = window.location.pathname + '?' + urlParams.toString();
            window.history.replaceState({{path: newUrl}}, '', newUrl);
        }}
    }})();
    </script>
    """
    components.html(js_code, height=0)


# =========================
# UI：Sidebar 操作面板
# =========================
def render_sidebar_panel() -> None:
    ss = st.session_state

    # 初始化用户 ID（用于多用户隔离）
    # 策略：优先使用 session_state，其次使用 URL 参数（已由 JavaScript 从 Cookie 同步）
    # 最后才生成新的 user_id
    import uuid

    ss_user_id = ss.get("user_id", "")
    query_params = st.query_params
    url_user_id = query_params.get("user_id", "")

    if ss_user_id:
        # session_state 中已有 user_id，使用它
        # 更新 URL 以保持一致性
        if query_params.get("user_id") != ss_user_id:
            query_params["user_id"] = ss_user_id
        logger.info(f"Using existing user_id from session_state: {ss_user_id}")
    elif url_user_id:
        # session_state 中没有 user_id，但 URL 中有（由 JavaScript 从 Cookie 同步）
        # 使用 URL 中的 user_id 恢复 session_state
        ss["user_id"] = url_user_id
        logger.info(f"Restored user_id from URL (synced from cookie): {url_user_id}")
    else:
        # session_state 和 URL 都没有 user_id，生成新的
        new_user_id = f"user_{uuid.uuid4().hex[:8]}"
        ss["user_id"] = new_user_id
        query_params["user_id"] = new_user_id
        logger.info(f"Generated new user_id: {new_user_id}")
        _update_user_id_in_browser(new_user_id)

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

        if st.button("重新生成", width="stretch", disabled=is_running):
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
                raw_state, _pretty_state, _prog, _m, _ts = _status_to_ui(status)
                dot = {
                    "done": "🟢",
                    "running": "🟡",
                    "queued": "🟡",
                    "pending": "🟡",
                    "failed": "🔴",
                }.get(raw_state, "⚪")

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
                    raw_state, pretty_state, prog, msg, ts = _status_to_ui(status)

                    # 安全获取 task_name（支持新旧格式）
                    parts = run_dir.name.split("__")
                    if len(parts) >= 2:
                        task_name = status.get("task_name") or parts[0]
                    else:
                        task_name = status.get("task_name") or run_dir.name

                    st.markdown(f"**当前任务**：{task_name}")
                    st.markdown(f"**状态**：`{pretty_state}`")
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

        # 添加 CSS 隐藏不需要的文件选择器选项
        st.markdown(
            """
        <style>
/* 隐藏文件选择器中的云存储和摄像头选项 */
[data-testid="stFileUploader"] button[data-kind="header"],
[data-testid="stFileUploader"] .camera-button,
[data-testid="stFileUploader"] [aria-label*="Camera"],
[data-testid="stFileUploader"] [aria-label*="摄像头"],
[data-testid="stFileUploader"] [aria-label*="拍摄"],
[data-testid="stFileUploader"] svg[data-testid="stVideoCameraIcon"] {
    display: none !important;
}

/* 隐藏可能的"拍照"或"录制"相关按钮 */
[data-testid="stFileUploader"] button:has(svg[data-testid="stVideoCameraIcon"]),
[data-testid="stFileUploader"] button:has(svg[data-testid="stCameraIcon"]) {
    display: none !important;
}
</style>
        """,
            unsafe_allow_html=True,
        )

        uploaded = st.file_uploader(
            "选择视频文件",
            type=["mp4", "mov", "avi", "mkv", "webm"],
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
    raw_state, pretty_state, prog, msg, ts = _status_to_ui(status)
    task_name = status.get("task_name") or run_dir.name.split("__")[0]
    video = storage.get_video_path(paths)
    video_name = video.name if video else "(未找到视频)"

    sig = f"{raw_state}|{prog:.3f}|{msg}|{ts}"
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
    if raw_state in {"done", "failed"}:
        enabled = False

    # Toast 一次
    if raw_state in {"done", "failed"} and not ss.get(
        f"{key_prefix}::completed_toast", False
    ):
        ss[f"{key_prefix}::completed_toast"] = True
        st.toast(
            "分析完成" if raw_state == "done" else "❌ 分析失败（请查看日志）",
            icon="✅" if raw_state == "done" else "❌",
        )

    with st.container(border=False):
        left, right = st.columns([0.72, 0.28], vertical_alignment="center")
        with left:
            st.markdown(f"**当前任务**：{task_name}  \n**视频**：{video_name}")
            st.caption(f"状态：{pretty_state}")
            if ts:
                st.caption(f"更新时间：{ts}")

            if enabled and _should_auto_refresh(raw_state):
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

    if enabled and _should_auto_refresh(raw_state):
        interval_ms = _calc_refresh_interval_ms(
            raw_state, prog, unchanged_hits=unchanged_hits
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

    # 根据调试模式动态生成标签页
    tab_names = ["📝 训练报告", "🎬 关键帧", "📊 技术指标"]
    if debug_mode:
        tab_names.append("🧾 日志/错误")

    tabs = st.tabs(tab_names)

    with tabs[0]:
        report = _load_report(paths)
        if not report:
            st.info("报告尚未生成（任务运行中或尚未完成）。")
        else:
            analysis = report.get("analysis") or {}

            # 兼容新旧格式：检查是否为教练实战版格式
            is_coach_report = "one_sentence" in analysis

            if is_coach_report:
                # =========================
                # 新格式：教练实战版报告
                # =========================

                # 1) 一句话总结（教练视角）
                one_sentence = (analysis.get("one_sentence") or "").strip()
                if one_sentence:
                    st.markdown("#### 总结")
                    st.write(one_sentence)

                st.divider()

                # 2) 核心问题（3条）
                top_problems = analysis.get("top_problems") or []
                st.markdown("#### 核心问题（3条）")
                if not top_problems:
                    st.info("暂无 top_problems（可能任务未完成或模型输出为空）。")
                else:
                    for p in top_problems:
                        prob_id = p.get("id", "")
                        title = p.get("title", "")
                        key_features = p.get("key_features") or []
                        direct_consequences = p.get("direct_consequences") or []
                        coach_judgment = p.get("coach_judgment", "")

                        st.markdown(f"**{prob_id}：{title}**")

                        if key_features:
                            st.markdown("**关键表现**（你现在在做什么）：")
                            for f in key_features:
                                st.write(f"- {f}")

                        if direct_consequences:
                            st.markdown("**直接后果**（比赛会发生什么）：")
                            for c in direct_consequences:
                                st.write(f"- {c}")

                        if coach_judgment:
                            st.info(f"💡 教练判断：{coach_judgment}")

                        st.divider()

                # 3) 训练计划
                training_plan = analysis.get("training_plan") or {}
                st.markdown("#### 训练计划")
                if not training_plan:
                    st.info("暂无 training_plan（可能任务未完成或模型输出为空）。")
                else:
                    session_goal = training_plan.get("session_goal", "")
                    if session_goal:
                        st.markdown(f"**本次训练目标**：{session_goal}")
                        st.divider()

                    improvements = training_plan.get("improvements") or []
                    if improvements:
                        for imp in improvements:
                            title = imp.get("title", "")
                            training_methods = imp.get("training_methods") or []
                            self_check_criteria = imp.get("self_check_criteria") or []

                            st.markdown(f"**{title}**")

                            if training_methods:
                                st.markdown("训练方法：")
                                for m in training_methods:
                                    st.write(f"- {m}")

                            if self_check_criteria:
                                st.markdown("自检标准：")
                                for c in self_check_criteria:
                                    st.write(f"- {c}")

                            st.divider()

                # 4) 分段点评
                segment_notes = analysis.get("segment_notes") or []
                st.markdown("#### 分段点评")
                if not segment_notes:
                    st.info("暂无 segment_notes（可能任务未完成或模型输出为空）。")
                else:
                    for note in segment_notes:
                        seg_id = note.get("segment_id")
                        title = note.get("title", "")
                        coach_comment = note.get("coach_comment", "")
                        evidence = note.get("evidence") or []

                        st.markdown(f"**{title}**（Segment {seg_id}）")
                        if coach_comment:
                            st.write(coach_comment)

                        if evidence:
                            frame_numbers = [
                                e.get("frame_index")
                                for e in evidence
                                if e.get("frame_index") is not None
                            ]
                            if frame_numbers:
                                st.caption(
                                    f"关键帧证据：帧号 {', '.join(map(str, frame_numbers))}"
                                )

                        st.divider()

            else:
                # =========================
                # 旧格式：兼容保留
                # =========================

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
                        imp = (p.get("impact") or "").strip()

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
                                st.markdown("**关键帧证据**：")
                                st.caption(
                                    f"检测到 {len(frame_numbers)} 个关键帧（帧号：{', '.join(map(str, frame_numbers))}）"
                                )
                            else:
                                # 如果没有明确帧号，提示用户查看关键帧标签页
                                all_frames = _list_frames(run_dir)
                                if all_frames:
                                    st.markdown("**参考帧**：")
                                    st.caption(
                                        f"共有 {len(all_frames)} 个关键帧（请前往「关键帧」标签页查看）"
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
                                frame_images = _find_frame_images(
                                    run_dir, frame_numbers
                                )
                                if frame_images:
                                    st.markdown("**关键帧证据**：")
                                    st.caption(
                                        f"检测到 {len(frame_images)} 个关键帧（帧号：{', '.join(map(str, frame_numbers))}）"
                                    )

            # 5) 调试模式：显示完整原始结构
            if debug_mode:
                with st.expander("查看完整报告 JSON（调试用）", expanded=False):
                    st.json(report, expanded=True)

            # 6) 导出按钮（Markdown + PDF）
            status = _read_json(paths.status_json)
            task_name = status.get("task_name", run_dir.name.split("__")[0])
            video = storage.get_video_path(paths)
            video_name = video.name if video else "未知视频"
            _render_export_buttons(run_dir, task_name, video_name)

    with tabs[1]:
        frames = _list_frames(run_dir)
        if not frames:
            st.info("关键帧尚未生成（任务运行中或尚未完成）。")
        else:
            # 读取 segments 和 report 数据，用于关联点评
            segments_data = _load_segments(paths)
            report = _load_report(paths)

            # 构建 segment_id -> 点评的映射（兼容新旧格式）
            segment_comments: dict[int, str] = {}
            if report:
                analysis = report.get("analysis") or {}

                # 新格式：segment_notes（教练实战版）
                if "segment_notes" in analysis:
                    seg_notes = analysis.get("segment_notes") or []
                    for s in seg_notes:
                        sid = s.get("segment_id")
                        comment = (s.get("coach_comment") or "").strip()
                        if sid is not None and comment:
                            segment_comments[int(sid)] = comment
                # 旧格式：segment_feedback
                else:
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
        segs = _load_segments(paths)
        if not feats:
            st.info("技术指标尚未生成（任务运行中或尚未完成）。")
        else:
            _render_metrics_panel(feats, segs, run_dir)

    # 日志/错误标签页（仅调试模式）
    if debug_mode:
        with tabs[3]:
            status = _read_json(paths.status_json)
            raw_state, _pretty_state, msg, _ = _status_to_ui(status)
            if raw_state == "failed":
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

    # 上传视频区域（独占一行）
    render_upload_and_start()

    # 任务状态区域（独占一行）
    st.markdown("### 任务状态")

    selected = ss.get("selected_run_dir", "")
    if not selected:
        st.info("请先上传视频，或在左侧选择历史任务。")
    else:
        run_dir = Path(selected)
        if not run_dir.exists():
            st.warning("任务目录不存在，请重新选择。")
            ss["selected_run_dir"] = ""
        else:
            render_status_strip(run_dir)

    # 底部：分析结果（全宽）
    if selected:
        run_dir = Path(selected)
        if run_dir.exists():
            with st.container(key=f"results_panel_{run_dir.name}"):
                render_results_tabs(run_dir)


def render_app() -> None:
    # 页面加载时立即执行：从 localStorage/Cookie 读取 user_id 并同步到 URL
    # 使用 st.markdown + unsafe_allow_html 确保脚本在页面头部立即执行
    # 如需同步则刷新页面，使 Python 端能读取到新的 URL 参数
    init_js = """
    <script>
    (function() {
        'use strict';

        function getCookie(name) {
            const value = "; " + document.cookie;
            const parts = value.split("; " + name + "=");
            if (parts.length == 2) return parts.pop().split(";").shift();
            return null;
        }

        const key = 'coachagent_user_id';
        // 优先从 localStorage 读取，其次 Cookie
        let userId = null;
        try {
            userId = localStorage.getItem(key);
        } catch (e) {
            console.warn('localStorage not available:', e);
        }
        if (!userId) {
            userId = getCookie(key);
        }

        const urlParams = new URLSearchParams(window.location.search);
        const urlUserId = urlParams.get('user_id');

        // 场景 1: 有存储的 user_id，但 URL 中没有 → 同步到 URL 并刷新
        if (userId && !urlUserId) {
            urlParams.set('user_id', userId);
            const newUrl = window.location.pathname + '?' + urlParams.toString();
            window.history.replaceState({path: newUrl}, '', newUrl);
            console.log('URL synced from storage, reloading...', userId);
            setTimeout(function() {
                window.location.reload();
            }, 50);
        }
        // 场景 2: URL 中有 user_id，但存储中没有 → 清除 URL 参数（可能是分享的 URL）
        else if (!userId && urlUserId) {
            urlParams.delete('user_id');
            const newUrl = window.location.pathname + (urlParams.toString() ? '?' + urlParams.toString() : '');
            window.history.replaceState({path: newUrl}, '', newUrl);
            console.log('URL parameter cleared (shared URL), reloading...');
            setTimeout(function() {
                window.location.reload();
            }, 50);
        }
        // 场景 3: 都有 user_id，但值不同 → 使用存储的值覆盖 URL
        else if (userId && urlUserId && userId !== urlUserId) {
            urlParams.set('user_id', userId);
            const newUrl = window.location.pathname + '?' + urlParams.toString();
            window.history.replaceState({path: newUrl}, '', newUrl);
            console.log('URL overwritten with storage, reloading...', userId, '(was:', urlUserId + ')');
            setTimeout(function() {
                window.location.reload();
            }, 50);
        }
        // 场景 4: 都有且值相同 → 无需操作
        else if (userId && urlUserId && userId === urlUserId) {
            console.log('User ID from storage matches URL:', userId);
        }
        // 场景 5: 都没有 → 首次访问，无需操作
        else {
            console.log('No user ID found (first visit)');
        }
    })();
    </script>
    """
    st.markdown(init_js, unsafe_allow_html=True)

    st.set_page_config(
        page_title=APP_TITLE,
        layout="centered",
        initial_sidebar_state="collapsed",
    )
    st.title(APP_TITLE)
    st.caption("上传视频 → 抽帧/特征 → AI 教练报告（3个问题 + 3个改进措施）。")
    render_sidebar_panel()
    render_main_panel()
