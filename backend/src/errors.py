"""
领域异常定义
"""

from typing import Any


class AnalysisError(Exception):
    """分析错误基类"""
    pass


class StepError(AnalysisError):
    """步骤错误基类"""
    pass


class FrameExtractionError(StepError):
    """抽帧错误"""
    pass


class FeatureComputationError(StepError):
    """特征计算错误"""
    pass


class AgentError(AnalysisError):
    """AI 调用错误"""
    pass


class AgentInvocationError(AgentError):
    """AI 调用失败（网络、认证等）"""
    pass


class OutputParsingError(AgentError):
    """AI 输出解析失败（非 JSON 或格式不符）"""
    pass


# ============================================================================
# Storage Errors（存储相关异常）
# ============================================================================


class StorageError(Exception):
    """存储操作错误基类"""
    pass


class RunNotFoundError(StorageError):
    """运行目录未找到"""
    pass


class InvalidRunDirectoryError(StorageError):
    """无效的运行目录结构"""
    pass


class StorageFileNotFoundError(StorageError):
    """存储文件未找到"""
    pass
