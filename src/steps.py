"""Pure step functions for video analysis workflow.

Minimal Streamlit dependency for reusability in CLI/testing.
"""

import logging
from pathlib import Path
from typing import Any

from errors import StepError, FrameExtractionError, FeatureComputationError
from storage import RunPaths

logger = logging.getLogger(__name__)


# ============================================================================
# Frame Extraction Step
# ============================================================================


def _parse_fraction(value: str) -> float | None:
    """Parse ffprobe fraction string like '30000/1001'."""
    try:
        if not value:
            return None
        if "/" in value:
            a, b = value.split("/", 1)
            a = float(a.strip())
            b = float(b.strip())
            if b == 0:
                return None
            return a / b
        return float(value)
    except Exception:
        return None


def _ffprobe_video_meta(
    video_path: Path,
) -> tuple[float | None, int | None, float | None]:
    """
    Return (fps, frame_count, duration_sec) from ffprobe if possible.
    frame_count may be None if nb_frames is unavailable.
    """
    try:
        import subprocess
        import json as _json
        from imageio_ffmpeg import get_ffprobe_exe
    except Exception:
        return None, None, None

    ffprobe = get_ffprobe_exe()
    cmd = [
        ffprobe,
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=nb_frames,avg_frame_rate,r_frame_rate,duration",
        "-of",
        "json",
        str(video_path),
    ]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if p.returncode != 0 or not p.stdout.strip():
            return None, None, None

        data = _json.loads(p.stdout)
        streams = data.get("streams") or []
        if not streams:
            return None, None, None

        s0 = streams[0]
        # duration might be string
        dur = s0.get("duration")
        duration = float(dur) if dur not in (None, "", "N/A") else None

        # fps from avg_frame_rate / r_frame_rate
        fps = (
            _parse_fraction(str(s0.get("avg_frame_rate") or ""))  # preferred
            or _parse_fraction(str(s0.get("r_frame_rate") or ""))
        )

        # nb_frames might be "N/A"
        nb = s0.get("nb_frames")
        frame_count = int(nb) if nb not in (None, "", "N/A") else None

        return fps, frame_count, duration
    except Exception:
        return None, None, None


def extract_frames(
    video_path: Path,
    output_dir: Path,
    max_frames: int = 1000,
    *,
    num_segments: int | None = None,
    frames_per_segment: int = 5,
    strategy: str = "uniform",  # "uniform" | "per_segment"
) -> dict[str, Any]:
    """Extract frames from video file (robust for mobile/VFR videos).

    Strategies:
      - "uniform": global uniform sampling up to max_frames (original behavior)
      - "per_segment": split by time into num_segments segments, sample frames_per_segment frames
                      in each segment (time-uniform). Total ≈ num_segments * frames_per_segment.

    Returns:
        {
          "frame_count": int,
          "video_duration": float,
          "frame_rate": float,
          "total_frames_in_video": int,
          "frames": [
              {"frame_index": int, "timestamp": float, "path": "frames/frame_000123.jpg"},
              ...
          ]
        }
    """
    try:
        import imageio.v3 as iio
    except ImportError as e:
        raise FrameExtractionError(
            "imageio not installed. Run: uv add imageio imageio-ffmpeg"
        ) from e

    if not video_path.exists():
        raise FrameExtractionError(f"Video file not found: {video_path}")

    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        # ---- 1) Prefer ffprobe for reliable meta ----
        fps, frame_count, duration = _ffprobe_video_meta(video_path)

        # ---- 2) Fallback to imageio meta ----
        meta: dict[str, Any] = {}
        try:
            meta = iio.immeta(video_path)  # type: ignore[assignment]
        except Exception:
            meta = {}

        fps = fps or float(meta.get("fps") or 0) or 30.0

        # Some videos don't expose n_frames; try other keys
        frame_count = frame_count or int(meta.get("n_frames") or 0) or None

        # Duration fallback (if possible)
        duration = duration or float(meta.get("duration") or 0) or None

        # ---- 3) If frame_count still unknown, estimate from duration * fps ----
        if frame_count is None and duration is not None and fps:
            est = int(duration * fps)
            frame_count = est if est > 0 else None

        # ---- 4) If still unknown, last resort: count frames via reader (can be slow) ----
        if frame_count is None:
            cap = max(3000, max_frames * 5)  # bounded count to avoid hanging
            cnt = 0
            try:
                for _ in iio.imiter(video_path):
                    cnt += 1
                    if cnt >= cap:
                        break
            except Exception:
                cnt = 0

            if cnt == 0:
                raise FrameExtractionError(
                    "Could not determine frame count from video (ffprobe/immeta/iter all failed). "
                    "Try re-encoding the video to standard H.264/AAC MP4."
                )

            frame_count = cnt
            duration = duration or (frame_count / fps if fps else None)

        # Duration final (still might be None if everything failed)
        if duration is None:
            duration = frame_count / fps if fps else 0.0

        # ---- 5) Decide which indices to extract ----
        indices: list[int] = []

        use_per_segment = (
            strategy == "per_segment"
            and num_segments is not None
            and int(num_segments) > 0
            and frames_per_segment > 0
            and duration is not None
            and fps
        )

        if use_per_segment:
            seg_n = int(num_segments)
            k = int(frames_per_segment)
            seg_dur = float(duration) / float(seg_n)

            # Time-uniform sampling inside each segment: pick midpoints
            for seg_i in range(seg_n):
                st = seg_i * seg_dur
                ed = (seg_i + 1) * seg_dur
                width = max(0.0, ed - st)

                for j in range(k):
                    # midpoint sampling: (j + 0.5) / k in [0,1)
                    t = st + (j + 0.5) / k * width
                    idx = int(round(t * float(fps)))
                    idx = max(0, min(idx, int(frame_count) - 1))
                    indices.append(idx)

            # dedupe + sort (avoid duplicates on short segments / low fps)
            indices = sorted(set(indices))

            # still respect max_frames as a safety bound
            if max_frames and len(indices) > int(max_frames):
                step = max(1, len(indices) // int(max_frames))
                indices = indices[::step][: int(max_frames)]
        else:
            # original global uniform sampling
            actual_frames = (
                min(int(max_frames), int(frame_count))
                if max_frames
                else int(frame_count)
            )
            actual_frames = max(1, actual_frames)
            step = max(1, int(frame_count) // actual_frames)
            indices = list(range(0, int(frame_count), step))[:actual_frames]

        # ---- 6) Extract and save frames ----
        frames: list[dict[str, Any]] = []
        for frame_idx in indices:
            timestamp = frame_idx / fps if fps else 0.0
            frame_path = output_dir / f"frame_{frame_idx:06d}.jpg"

            frame = iio.imread(video_path, index=int(frame_idx))

            import numpy as np

            if isinstance(frame, np.ndarray):
                from imageio import imwrite

                imwrite(str(frame_path), frame)
                frames.append(
                    {
                        "frame_index": int(frame_idx),
                        "timestamp": round(float(timestamp), 2),
                        # store path relative to run_dir (parent of frames dir)
                        "path": str(frame_path.relative_to(output_dir.parent)),
                    }
                )

        result = {
            "frame_count": len(frames),
            "video_duration": round(float(duration), 2),
            "frame_rate": float(fps),
            "total_frames_in_video": int(frame_count),
            "frames": frames,
        }

        logger.info(
            f"Extracted {len(frames)} frames from {video_path.name} "
            f"(strategy={strategy}, segments={num_segments}, k={frames_per_segment})"
        )
        return result

    except FrameExtractionError:
        raise
    except Exception as e:
        raise FrameExtractionError(f"Failed to extract frames: {e}") from e


# ============================================================================
# Feature Computation Step
# ============================================================================


def compute_features(
    frames_data: dict[str, Any],
    num_segments: int = 8,
) -> dict[str, Any]:
    """Compute motion and pose features from frame data (time-aligned segments).

    IMPORTANT:
      - Segments are defined by time ranges, not by frame-count slicing.
      - This matches 'per_segment' frame extraction strategy (e.g., 5 frames per segment).
    """
    frames = frames_data.get("frames", []) or []
    frame_count = len(frames)
    video_duration = float(frames_data.get("video_duration", 0) or 0)

    if num_segments <= 0:
        num_segments = 1

    if frame_count == 0 or video_duration <= 0:
        return {
            "segment_count": num_segments,
            "segments": [],
            "summary": "No frames available for analysis.",
            "frame_rate": frames_data.get("frame_rate", 30),
            "video_duration": video_duration,
        }

    # --- segment by time ---
    segment_duration = video_duration / num_segments

    # buckets: each segment holds frames belonging to its time range
    buckets: list[list[dict[str, Any]]] = [[] for _ in range(num_segments)]

    def _ts(f: dict[str, Any]) -> float:
        try:
            return float(f.get("timestamp", 0) or 0)
        except Exception:
            return 0.0

    # assign frames to segments by timestamp
    for fr in sorted(frames, key=_ts):
        t = _ts(fr)
        seg_idx = int(t // segment_duration) if segment_duration > 0 else 0
        if seg_idx >= num_segments:
            seg_idx = num_segments - 1
        if seg_idx < 0:
            seg_idx = 0
        buckets[seg_idx].append(fr)

    segments: list[dict[str, Any]] = []
    for seg_idx in range(num_segments):
        start_time = seg_idx * segment_duration
        end_time = (seg_idx + 1) * segment_duration

        segment_frames = buckets[seg_idx]
        segments.append(
            {
                "segment_id": seg_idx,
                "start_time": round(float(start_time), 2),
                "end_time": round(float(end_time), 2),
                "duration": round(float(segment_duration), 2),
                "frame_count": len(segment_frames),
                "frame_indices": [
                    int(f.get("frame_index", -1))
                    for f in segment_frames
                    if f.get("frame_index") is not None
                ],
            }
        )

    # Summary for LLM
    avg_frames = frame_count / num_segments if num_segments else frame_count
    summary_parts = [
        f"Video duration: {video_duration:.2f} seconds",
        f"Total frames extracted: {frame_count}",
        f"Divided into {num_segments} time-aligned segments for analysis",
        f"Avg frames per segment: {avg_frames:.1f}",
    ]

    result = {
        "segment_count": num_segments,
        "segments": segments,
        "summary": "\n".join(summary_parts),
        "frame_rate": frames_data.get("frame_rate", 30),
        "video_duration": video_duration,
    }

    logger.info(f"Computed time-aligned features for {num_segments} segments")
    return result


# ============================================================================
# LLM Analysis Step
# ============================================================================
def run_llm_analysis(
    frames_data: dict[str, Any],
    features_data: dict[str, Any],
    agent_mode: str,
    *,
    llm_model: str = "deepseek-chat",
    run_dir: Path | None = None,
) -> dict[str, Any]:
    """Run LLM analysis on the video.

    Args:
        frames_data: Data from extract_frames step
        features_data: Data from compute_features step
        agent_mode: "mock" or "real"

    Returns:
        Structured analysis report as dict
    """
    from agent import analyze_video_with_fallback, analyze_images_with_fallback

    # ✅ 统一构造（两种分支都复用），保证 Frame X at Ts 可引用
    frames_summary = _build_frames_summary_by_segment(
        frames_data,
        features_data,
        max_frames_per_segment=5,
        max_total_frames=None,  # 不截断，保证每段都有证据
    )
    num_segments = int(features_data.get("segment_count", 8) or 8)
    features_summary = features_data.get("summary", "No features available.")

    # ==========================
    # Vision branch: GLM-4.6V-Flash
    # ==========================
    if llm_model == "glm-4.6v-flash":
        frames = frames_data.get("frames", []) or []
        if not frames:
            report = analyze_images_with_fallback(
                frames_summary=frames_summary,
                num_segments=num_segments,
                image_paths=[],
                mode=agent_mode,
            )
            return report.to_dict()

        # 取最多 12 张图，均匀采样，按时间顺序
        max_images = 12
        n = len(frames)
        if n <= max_images:
            idxs = list(range(n))
        else:
            step = max(1, n // max_images)
            idxs = list(range(0, n, step))[:max_images]

        image_paths: list[str] = []
        for i in idxs:
            rel = (frames[i] or {}).get("path", "")
            if not rel:
                continue
            # frames[i]["path"] 通常是相对 run_dir 的，如 "frames/frame_00012.png"
            if run_dir is not None:
                image_paths.append(str(run_dir / rel))
            else:
                image_paths.append(str(rel))

        report = analyze_images_with_fallback(
            frames_summary=frames_summary,
            num_segments=num_segments,
            image_paths=image_paths,
            mode=agent_mode,
        )
        return report.to_dict()

    # ==========================
    # Text branch: Deepseek (existing)
    # ==========================
    report = analyze_video_with_fallback(
        frames_summary=frames_summary,
        features_summary=features_summary,
        num_segments=num_segments,
        mode=agent_mode,
    )
    return report.to_dict()


def _build_frames_summary_by_segment(
    frames_data: dict[str, Any],
    features_data: dict[str, Any],
    *,
    max_frames_per_segment: int = 5,
    max_total_frames: int | None = None,
) -> str:
    """
    按分段聚合关键帧摘要（与 features_data["segments"] 严格对齐）：
    - 每段最多展示 max_frames_per_segment 张（默认 5）
    - max_total_frames=None 表示不封顶（推荐：保证每段都有证据）
      如果提供 max_total_frames：会“尽量保证每段至少 1 张”，再按段追加直到用完额度

    输入要求：
    - frames_data["frames"]：列表，每项至少包含 timestamp / frame_index
    - features_data["segments"]：列表，每项至少包含 start_time / end_time
    """
    frames = frames_data.get("frames") or []
    if not isinstance(frames, list) or len(frames) == 0:
        return "未从视频中提取到任何关键帧。"

    segments = (
        (features_data.get("segments") or []) if isinstance(features_data, dict) else []
    )
    if not isinstance(segments, list) or len(segments) == 0:
        # 兜底：若没有 segments，则回退到平铺摘要（如果你项目里有该函数）
        try:
            return _build_frames_summary(frames_data)  # type: ignore[name-defined]
        except Exception:
            return "未提供分段信息（features.segments 为空），无法按段生成关键帧摘要。"

    # ---------- helpers ----------
    def _ts(fr: dict[str, Any]) -> float:
        try:
            return float(fr.get("timestamp", 0) or 0)
        except Exception:
            return 0.0

    def _frame_id(fr: dict[str, Any]) -> int | str:
        # 兼容旧字段 i
        if "frame_index" in fr and fr["frame_index"] is not None:
            try:
                return int(fr["frame_index"])
            except Exception:
                return fr["frame_index"]
        if "i" in fr and fr["i"] is not None:
            try:
                return int(fr["i"])
            except Exception:
                return fr["i"]
        return "?"

    def _seg_range(seg: dict[str, Any]) -> tuple[float, float]:
        try:
            st = float(seg.get("start_time", 0) or 0)
        except Exception:
            st = 0.0
        try:
            ed = float(seg.get("end_time", 0) or 0)
        except Exception:
            ed = 0.0
        return st, ed

    def _pick_uniform(seg_frames: list[dict[str, Any]], k: int) -> list[dict[str, Any]]:
        """从该段帧中均匀抽 k 张代表帧（按时间顺序）。"""
        if k <= 0 or not seg_frames:
            return []
        if len(seg_frames) <= k:
            return seg_frames
        step = max(1, len(seg_frames) // k)
        picked = seg_frames[::step][:k]
        # 尾帧补齐（更像“段尾”）
        if picked and picked[-1] is not seg_frames[-1] and len(picked) < k:
            picked.append(seg_frames[-1])
        return picked[:k]

    # ---------- bucket frames into segments by timestamp ----------
    frames_sorted = sorted([f for f in frames if isinstance(f, dict)], key=_ts)
    buckets: list[list[dict[str, Any]]] = [[] for _ in range(len(segments))]

    for fr in frames_sorted:
        t = _ts(fr)
        placed = False
        for i, seg in enumerate(segments):
            st, ed = _seg_range(seg)
            # 前闭后开，最后一段允许包含 end_time
            if (t >= st and t < ed) or (i == len(segments) - 1 and t >= st and t <= ed):
                buckets[i].append(fr)
                placed = True
                break
        if not placed:
            # timestamp 不在任何段：兜底放最后一段
            buckets[-1].append(fr)

    # ---------- choose per-segment representatives ----------
    per_seg_picks: list[list[dict[str, Any]]] = []
    for i in range(len(segments)):
        per_seg_picks.append(_pick_uniform(buckets[i], max_frames_per_segment))

    # ---------- apply optional max_total_frames cap ----------
    if max_total_frames is not None:
        cap = max(1, int(max_total_frames))

        # 先保证每段最多 1 张（如果有）
        base: list[list[dict[str, Any]]] = []
        for picks in per_seg_picks:
            base.append(picks[:1] if picks else [])
        used = sum(len(x) for x in base)
        remain = cap - used

        if remain <= 0:
            per_seg_picks = base
        else:
            out = [list(x) for x in base]
            # 轮询追加第二张、第三张...直到用完
            while remain > 0:
                added_any = False
                for i in range(len(out)):
                    picks = per_seg_picks[i]
                    cur = out[i]
                    if len(cur) < len(picks):
                        cur.append(picks[len(cur)])
                        remain -= 1
                        added_any = True
                        if remain <= 0:
                            break
                if not added_any:
                    break
            per_seg_picks = out

    # ---------- build text ----------
    duration = float(frames_data.get("video_duration", 0) or 0)
    fps = frames_data.get("frame_rate", 0)

    total_frames = len(frames_sorted)
    selected_total = sum(len(x) for x in per_seg_picks)

    lines: list[str] = []
    lines.append("视频关键帧摘要（按分段聚合，按时间顺序）")
    if duration > 0:
        lines.append(f"- 视频时长: {duration:.2f}s")
    lines.append(f"- 抽取关键帧: {total_frames} 张")
    if fps:
        lines.append(f"- 帧率: {fps} fps")
    lines.append(f"- 分段数量: {len(segments)} 段")
    lines.append(f"- 每段展示: {max_frames_per_segment} 张（严格按 segment 对齐）")
    if max_total_frames is not None:
        lines.append(
            f"- 总展示上限: {int(max_total_frames)} 张（当前展示 {selected_total} 张）"
        )
    lines.append("")
    lines.append(
        "段评要求：每段点评必须引用本段的 Frame 证据，格式：Frame <数字> at <数字>s"
    )
    lines.append("")

    for i, seg in enumerate(segments):
        st, ed = _seg_range(seg)
        seg_frames = buckets[i]
        picks = per_seg_picks[i]

        lines.append(
            f"Segment {i} ({st:.2f}s - {ed:.2f}s), 该段抽到 {len(seg_frames)} 张关键帧："
        )
        if not picks:
            lines.append("  - （该段没有可用关键帧）")
        else:
            for fr in picks:
                fi = _frame_id(fr)
                ts = fr.get("timestamp", "?")
                lines.append(f"  - Frame {fi} at {ts}s")
        lines.append("")

    # 若触发封顶，提醒
    if max_total_frames is not None and selected_total >= int(max_total_frames):
        lines.append(
            f"（为控制输入长度，已限制总展示帧数为 {int(max_total_frames)}。）"
        )

    return "\n".join(lines)


def _build_frames_summary(frames_data: dict[str, Any]) -> str:
    """Build a summary of frames for LLM prompt."""
    frames = frames_data.get("frames", [])
    frame_count = len(frames)
    duration = frames_data.get("video_duration", 0)

    if frame_count == 0:
        return "No frames were extracted from the video."

    # Sample frames to avoid overly long prompt
    max_samples = 20
    sample_step = max(1, frame_count // max_samples)

    sampled_frames = frames[::sample_step][:max_samples]

    lines = [
        f"Video Analysis Summary",
        f"Duration: {duration:.2f} seconds",
        f"Extracted frames: {frame_count}",
        f"Frame rate: {frames_data.get('frame_rate', 30)} fps",
        "",
        "Key frames analyzed:",
    ]

    for frame in sampled_frames:
        lines.append(f"  Frame {frame['frame_index']} at {frame['timestamp']}s")

    return "\n".join(lines)


# ============================================================================
# Assemble Report Step
# ============================================================================


def assemble_report(
    frames_data: dict[str, Any],
    features_data: dict[str, Any],
    llm_result: dict[str, Any],
) -> dict[str, Any]:
    """Assemble final report with all analysis results.

    Args:
        frames_data: Data from extract_frames step
        features_data: Data from compute_features step
        llm_result: Data from run_llm_analysis step

    Returns:
        Complete report dictionary
    """
    report = {
        "metadata": {
            "video_duration": frames_data.get("video_duration", 0),
            "frame_count": frames_data.get("frame_count", 0),
            "frame_rate": frames_data.get("frame_rate", 30),
            "segment_count": features_data.get("segment_count", 0),
        },
        "frames": frames_data,
        "features": features_data,
        "analysis": llm_result,
    }

    logger.info("Assembled complete report")
    return report


# ============================================================================
# Full Analysis Pipeline (for testing/CLI)
# ============================================================================


def run_full_analysis(
    video_path: Path,
    output_dir: Path,
    max_frames: int = 1000,
    num_segments: int = 8,
    agent_mode: str = "mock",
) -> dict[str, Any]:
    """Run complete analysis pipeline.

    Returns the assembled report.
    """
    # Step 1: Extract frames
    frames_data = extract_frames(video_path, output_dir, max_frames)

    # Step 2: Compute features
    features_data = compute_features(frames_data, num_segments)

    # Step 3: Run LLM analysis
    llm_result = llm_result = run_llm_analysis(
        frames_data,
        features_data,
        agent_mode,
        llm_model=llm_model,
        run_dir=paths.run_dir,  # ✅ 让 step 能找到图片实际路径
    )

    # Step 4: Assemble report
    report = assemble_report(frames_data, features_data, llm_result)

    return report
