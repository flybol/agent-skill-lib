"""Process orchestration for CoachAgent.

Handles task lifecycle: queued → running → done/failed.
"""

import logging
import queue
import shutil
import threading
from pathlib import Path

from constants import AGENT_MODE_REAL, RunState, DEFAULT_SEGMENTS, POSE_MAX_FRAMES
from errors import PipelineError, StepError
from storage import (
    RunPaths,
    create_run_directory,
    initialize_run_status,
    initialize_run_config,
    update_status,
    write_report,
    write_segments,
    write_features,
    append_log,
    get_video_path,
    increment_user_run_count,
)
from steps import (
    extract_frames,
    compute_features,
    run_llm_analysis,
    assemble_report,
    FrameExtractionError,
    FeatureComputationError,
)
from utils import generate_id
from constants import DEFAULT_LLM_MODEL  # 顶部加 import

logger = logging.getLogger(__name__)


# ============================================================================
# 任务队列（单机 FIFO，避免并发冲突）
# ============================================================================

_task_queue: queue.Queue = queue.Queue()
_worker_thread: threading.Thread | None = None
_worker_lock = threading.Lock()


def _get_worker() -> threading.Thread:
    """获取或创建 worker 线程（单例模式）。"""
    global _worker_thread

    with _worker_lock:
        if _worker_thread is None or not _worker_thread.is_alive():
            _worker_thread = threading.Thread(
                target=_worker_loop, name="PipelineWorker", daemon=True
            )
            _worker_thread.start()
            logger.info("Pipeline worker thread started")

    return _worker_thread


def _worker_loop() -> None:
    """Worker 线程主循环：串行执行队列中的任务。"""
    while True:
        try:
            # 从队列获取任务（阻塞等待）
            task_data = _task_queue.get()

            if task_data is None:
                # 哨兵值：退出信号
                logger.info("Worker received shutdown signal")
                break

            paths, agent_mode = task_data

            try:
                logger.info(f"Worker executing task: {paths.run_dir.name}")
                execute_run(paths, agent_mode)
                logger.info(f"Worker completed task: {paths.run_dir.name}")
            except Exception as e:
                logger.error(f"Worker task failed: {e}")
                # execute_run 内部已经更新了状态为 FAILED

            finally:
                _task_queue.task_done()

        except Exception as e:
            logger.error(f"Worker loop error: {e}")


def get_queue_info() -> dict[str, int]:
    """获取队列状态信息。

    Returns:
        包含队列大小和 worker 状态的字典
    """
    with _worker_lock:
        return {
            "queue_size": _task_queue.qsize(),
            "worker_alive": _worker_thread is not None
            and _worker_thread.is_alive(),
        }


# ============================================================================
# Run Creation
# ============================================================================


def create_run(
    task_name: str,
    video_path: Path,
    agent_mode: str = AGENT_MODE_REAL,
    llm_model: str = DEFAULT_LLM_MODEL,
    max_frames: int = POSE_MAX_FRAMES,
    num_segments: int = DEFAULT_SEGMENTS,
    user_id: str | None = None,
) -> tuple[RunPaths, str]:
    """Create a new run and copy video input.

    Args:
        task_name: Name of the task
        video_path: Path to the video file
        agent_mode: Agent mode (mock/real)
        llm_model: LLM model to use
        max_frames: Maximum frames to extract
        num_segments: Number of segments to divide video into
        user_id: Optional user ID for multi-user isolation

    Returns:
        Tuple of (RunPaths, run_id)
    """
    run_id = generate_id("run_")
    paths = create_run_directory(task_name, run_id, user_id=user_id)

    # Copy video to input directory
    try:
        target_video = paths.input_dir / video_path.name
        shutil.copy2(video_path, target_video)
        logger.info(f"Copied video to {target_video}")
    except Exception as e:
        raise PipelineError(f"Failed to copy video: {e}") from e

    # Initialize status
    initialize_run_status(paths, task_name, run_id)

    # Initialize config
    initialize_run_config(paths, agent_mode, llm_model, max_frames, num_segments)

    # 更新用户的任务计数（如果有 user_id）
    if user_id:
        increment_user_run_count(user_id)

    return paths, run_id


# ============================================================================
# Run Execution
# ============================================================================


def execute_run(paths: RunPaths, agent_mode: str | None = None) -> None:
    """Execute the analysis pipeline for a run.

    Args:
        paths: RunPaths for the run to execute
        agent_mode: Override agent mode, or None to use config

    Raises:
        PipelineError: If execution fails critically
    """
    try:
        video_path = get_video_path(paths)
        if not video_path:
            raise PipelineError("No video file found in run directory")

        # Get config for parameters
        from storage import read_config

        config = read_config(paths)

        if config is None:
            raise PipelineError("No config found in run directory")

        max_frames = config.max_frames
        num_segments = config.num_segments
        llm_model = getattr(config, "llm_model", "deepseek-chat")
        if agent_mode is None:
            agent_mode = config.agent_mode

        update_status(
            paths, state=RunState.RUNNING, progress=0, message="Starting analysis..."
        )
        append_log(paths, f"Starting analysis with agent_mode={agent_mode}")
    except Exception as e:
        logger.error(f"Unexpected error during run: {e}")
        update_status(
            paths, state=RunState.FAILED, message="Analysis failed", error=str(e)
        )
        append_log(paths, f"ERROR: Unexpected error - {e}")
        raise
    try:
        # Step 1: Extract frames (10-30% progress)
        update_status(paths, progress=10, message="Extracting frames from video...")
        append_log(paths, "Extracting frames...")
        frames_output = paths.run_dir / "frames"
        frames_output.mkdir(exist_ok=True)
        frames_data = extract_frames(
            video_path,
            frames_output,
            max_frames=max_frames,  # 仍保留一个上限兜底
            num_segments=num_segments,
            frames_per_segment=5,
            strategy="per_segment",
        )
        write_segments(paths, frames_data)
        append_log(paths, f"Extracted {frames_data['frame_count']} frames")

        # Step 2: Compute features (30-50% progress)
        update_status(paths, progress=30, message="Computing motion features...")
        append_log(paths, "Computing features...")
        features_data = compute_features(frames_data, num_segments)
        write_features(paths, features_data)
        append_log(paths, f"Computed features for {num_segments} segments")

        # Step 3: Run LLM analysis (50-80% progress)
        update_status(paths, progress=50, message="Running AI analysis...")
        llm_model = getattr(config, "llm_model", "deepseek-chat")
        append_log(
            paths, f"Running LLM analysis (mode={agent_mode}, model={llm_model})..."
        )

        llm_result = run_llm_analysis(
            frames_data,
            features_data,
            agent_mode,
            llm_model=llm_model,
            run_dir=paths.run_dir,
        )

        append_log(paths, "LLM analysis completed")

        # Step 4: Assemble report (80-100% progress)
        update_status(paths, progress=80, message="Assembling report...")
        append_log(paths, "Assembling final report...")
        report = assemble_report(frames_data, features_data, llm_result)
        write_report(paths, report)

        # Complete
        update_status(
            paths, state=RunState.DONE, progress=100, message="Analysis complete!"
        )
        append_log(paths, "Analysis completed successfully")

    except FrameExtractionError as e:
        logger.error(f"Frame extraction failed: {e}")
        update_status(
            paths,
            state=RunState.FAILED,
            message="Frame extraction failed",
            error=str(e),
        )
        append_log(paths, f"ERROR: Frame extraction failed - {e}")
        raise PipelineError(f"Frame extraction failed: {e}") from e

    except FeatureComputationError as e:
        logger.error(f"Feature computation failed: {e}")
        update_status(
            paths,
            state=RunState.FAILED,
            message="Feature computation failed",
            error=str(e),
        )
        append_log(paths, f"ERROR: Feature computation failed - {e}")
        raise PipelineError(f"Feature computation failed: {e}") from e

    except Exception as e:
        logger.error(f"Unexpected error during run: {e}")
        update_status(
            paths, state=RunState.FAILED, message="Analysis failed", error=str(e)
        )
        append_log(paths, f"ERROR: Unexpected error - {e}")
        raise PipelineError(f"Run execution failed: {e}") from e


# ============================================================================
# Background Execution (for Streamlit)
# ============================================================================


def execute_run_async(paths: RunPaths, agent_mode: str | None = None) -> None:
    """将任务加入队列，由 worker 线程串行执行。

    Args:
        paths: RunPaths for the run to execute
        agent_mode: Override agent mode, or None to use config

    相比旧的直接创建线程方式，新方式使用队列保证：
    1. 同一时间只有一个任务在执行（避免资源竞争）
    2. 任务按 FIFO 顺序执行
    3. 避免并发写文件导致的竞态条件
    """
    # 确保 worker 线程已启动
    _get_worker()

    # 将任务加入队列
    _task_queue.put((paths, agent_mode))
    queue_info = get_queue_info()
    logger.info(
        f"Task queued: {paths.run_dir.name}, "
        f"queue size: {queue_info['queue_size']}"
    )


def start_background_run(
    paths, agent_mode: str | None = None, overwrite: bool = True
) -> None:
    """启动后台运行（兼容旧接口）。

    Args:
        paths: RunPaths for the run
        agent_mode: Agent mode override
        overwrite: 参数保留以兼容 UI，当前未使用
    """
    return execute_run_async(paths, agent_mode)
