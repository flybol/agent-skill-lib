"""目标运动员检测模块

通过分析视频帧的左右侧运动量，自动判断主要击球者（左侧球员或右侧球员）。
"""

import logging
from pathlib import Path
from typing import Any
import numpy as np
import imageio.v3 as iio

logger = logging.getLogger(__name__)


def detect_target_player(
    frames_data: dict[str, Any],
    output_dir: Path,
    motion_threshold: float = 0.05,
    confidence_threshold: float = 0.65,
) -> dict[str, Any]:
    """检测视频中的主要击球者（左侧或右侧球员）

    Args:
        frames_data: 抽帧数据（来自 extract_frames）
        output_dir: 输出目录（用于保存检测结果）
        motion_threshold: 运动量阈值（低于此值认为该侧没有明显运动）
        confidence_threshold: 置信度阈值（低于此值建议用户确认）

    Returns:
        目标球员配置字典：
        {
            "mode": "auto_with_override",
            "auto_pick": "left" | "right" | "single_player",
            "confidence": 0.0-1.0,
            "override": null | "left" | "right",
            "reason": "判断原因说明",
            "motion_stats": {
                "left_ratio": 0.5,
                "right_ratio": 0.5,
                "dominant_side": "left"
            }
        }
    """
    frames = frames_data.get("frames", [])
    if not frames:
        logger.warning("没有可用的帧数据，无法检测目标球员")
        return {
            "mode": "auto_with_override",
            "auto_pick": "single_player",
            "confidence": 0.0,
            "override": None,
            "reason": "没有可用的帧数据",
            "motion_stats": None,
        }

    # 只取前10帧进行快速检测（避免处理所有帧）
    sample_frames = frames[:10]
    frame_paths = []
    for frame_info in sample_frames:
        frame_path = frame_info.get("path", "")
        if frame_path:
            # 如果是相对路径，转换为绝对路径
            if not Path(frame_path).is_absolute():
                frame_paths.append(output_dir / frame_path)
            else:
                frame_paths.append(Path(frame_path))

    if not frame_paths:
        logger.warning("没有找到有效的帧文件路径")
        return {
            "mode": "auto_with_override",
            "auto_pick": "single_player",
            "confidence": 0.0,
            "override": None,
            "reason": "无法读取帧文件",
            "motion_stats": None,
        }

    # 计算左右侧运动量
    motion_stats = _calculate_side_motion(frame_paths)

    # 判断主要击球者
    left_ratio = motion_stats["left_ratio"]
    right_ratio = motion_stats["right_ratio"]
    dominant_side = motion_stats["dominant_side"]

    # 判断是否为单人视频
    total_motion = left_ratio + right_ratio
    if total_motion < motion_threshold:
        result = {
            "mode": "auto_with_override",
            "auto_pick": "single_player",
            "confidence": 0.9,
            "override": None,
            "reason": "检测到单人训练场景",
            "motion_stats": motion_stats,
        }
        logger.info(f"[目标球员检测] 单人场景，置信度: 0.9")
        return result

    # 判断主要击球者
    if dominant_side == "left":
        confidence = left_ratio / (left_ratio + right_ratio) if (left_ratio + right_ratio) > 0 else 0.5
        auto_pick = "left"
        reason = f"左侧球员运动量更大（左侧 {left_ratio:.2%} vs 右侧 {right_ratio:.2%}）"
    else:
        confidence = right_ratio / (left_ratio + right_ratio) if (left_ratio + right_ratio) > 0 else 0.5
        auto_pick = "right"
        reason = f"右侧球员运动量更大（右侧 {right_ratio:.2%} vs 左侧 {left_ratio:.2%}）"

    # 如果置信度低于阈值，建议用户确认
    if confidence < confidence_threshold:
        reason += "，建议确认主要击球者"

    result = {
        "mode": "auto_with_override",
        "auto_pick": auto_pick,
        "confidence": round(confidence, 2),
        "override": None,
        "reason": reason,
        "motion_stats": motion_stats,
    }

    logger.info(f"[目标球员检测] {auto_pick} 侧，置信度: {confidence:.2f}")
    return result


def _calculate_side_motion(frame_paths: list[Path]) -> dict[str, Any]:
    """计算左右侧的运动量

    策略：
    1. 将画面分为左右两半
    2. 计算相邻帧之间的差异（帧差）
    3. 统计左右两侧的帧差总和

    Returns:
        {
            "left_ratio": 0.5,  # 左侧运动量占比
            "right_ratio": 0.5,  # 右侧运动量占比
            "dominant_side": "left" | "right" | "equal"
        }
    """
    if len(frame_paths) < 2:
        # 只有一帧，无法计算运动量
        return {
            "left_ratio": 0.5,
            "right_ratio": 0.5,
            "dominant_side": "equal",
        }

    left_motion = 0.0
    right_motion = 0.0
    frame_count = 0

    # 读取所有帧
    frames = []
    for path in frame_paths:
        try:
            frame = iio.imread(path)
            # 转换为灰度图（减少计算量）
            if len(frame.shape) == 3:
                frame = np.mean(frame, axis=2)
            frames.append(frame)
        except Exception as e:
            logger.warning(f"无法读取帧 {path}: {e}")
            continue

    if len(frames) < 2:
        return {
            "left_ratio": 0.5,
            "right_ratio": 0.5,
            "dominant_side": "equal",
        }

    # 计算相邻帧之间的差异
    for i in range(len(frames) - 1):
        frame1 = frames[i]
        frame2 = frames[i + 1]

        # 确保两帧大小一致
        if frame1.shape != frame2.shape:
            continue

        # 计算帧差
        diff = np.abs(frame2.astype(float) - frame1.astype(float))

        # 分割左右两半
        height, width = diff.shape
        mid_x = width // 2

        left_half = diff[:, :mid_x]
        right_half = diff[:, mid_x:]

        # 统计运动量（差异的总和）
        left_motion += np.sum(left_half)
        right_motion += np.sum(right_half)
        frame_count += 1

    if frame_count == 0:
        return {
            "left_ratio": 0.5,
            "right_ratio": 0.5,
            "dominant_side": "equal",
        }

    total_motion = left_motion + right_motion

    if total_motion == 0:
        # 没有检测到运动
        return {
            "left_ratio": 0.5,
            "right_ratio": 0.5,
            "dominant_side": "equal",
        }

    # 计算比例
    left_ratio = left_motion / total_motion
    right_ratio = right_motion / total_motion

    # 判断优势侧
    if abs(left_ratio - right_ratio) < 0.1:
        dominant_side = "equal"
    elif left_ratio > right_ratio:
        dominant_side = "left"
    else:
        dominant_side = "right"

    return {
        "left_ratio": round(left_ratio, 3),
        "right_ratio": round(right_ratio, 3),
        "dominant_side": dominant_side,
    }


def override_target_player(
    current_config: dict[str, Any],
    override_choice: str,
) -> dict[str, Any]:
    """覆盖自动检测的目标球员选择

    Args:
        current_config: 当前目标球员配置
        override_choice: 用户选择 ("left" 或 "right")

    Returns:
        更新后的配置字典
    """
    result = current_config.copy()
    result["override"] = override_choice
    result["mode"] = "manual_override"

    logger.info(f"[目标球员覆盖] 用户选择: {override_choice}（原自动判断: {current_config.get('auto_pick')}）")
    return result


def get_effective_target(config: dict[str, Any]) -> str:
    """获取有效的目标球员选择

    优先级：用户覆盖 > 自动选择 > 单人

    Args:
        config: 目标球员配置

    Returns:
        "left" | "right" | "single_player"
    """
    if config.get("override"):
        return config["override"]

    auto_pick = config.get("auto_pick", "single_player")
    return auto_pick if auto_pick else "single_player"
