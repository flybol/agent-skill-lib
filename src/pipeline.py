"""Process orchestration for CoachAgent.

Handles task lifecycle: queued → running → done/failed.
"""

import logging
import shutil
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
# Run Creation
# ============================================================================


def create_run(
    task_name: str,
    video_path: Path,
    agent_mode: str = AGENT_MODE_REAL,
    llm_model: str = DEFAULT_LLM_MODEL,
    max_frames: int = POSE_MAX_FRAMES,
    num_segments: int = DEFAULT_SEGMENTS,
) -> tuple[RunPaths, str]:
    """Create a new run and copy video input.

    Returns:
        Tuple of (RunPaths, run_id)
    """
    run_id = generate_id("run_")
    paths = create_run_directory(task_name, run_id)

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
        # Set state to running
        update_status(
            paths, state=RunState.RUNNING, progress=0, message="Starting analysis..."
        )
        append_log(paths, f"Starting analysis with agent_mode={agent_mode}")

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
    """Execute run in background for Streamlit.

    This is a wrapper that can be called from Streamlit callbacks.
    The actual execution happens synchronously in a separate thread/process.

    Note: For MVP, this runs synchronously. True async execution
    would require threading or multiprocessing with proper state management.
    """
    import threading

    def _run():
        try:
            execute_run(paths, agent_mode)
        except Exception as e:
            logger.error(f"Background run failed: {e}")

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    logger.info(f"Started background run in thread: {paths.run_dir.name}")


def start_background_run(paths, overwrite: bool = True):
    # overwrite 目前在 pipeline 里没有用到，先吃掉参数保证兼容 UI
    return execute_run_async(paths)
