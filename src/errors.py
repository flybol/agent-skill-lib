"""Domain-specific exceptions for CoachAgent."""


class CoachAgentError(Exception):
    """Base exception for all CoachAgent errors."""
    pass


class StorageError(CoachAgentError):
    """Error related to paths, files, or parsing."""
    pass


class RunNotFoundError(StorageError):
    """Run directory does not exist."""
    pass


class FileNotFoundError(StorageError):
    """Expected file not found in run directory."""
    pass


class InvalidRunDirectoryError(StorageError):
    """Run directory structure is invalid."""
    pass


class PipelineError(CoachAgentError):
    """Error related to lifecycle, state, or concurrency."""
    pass


class InvalidStatusError(PipelineError):
    """Invalid state transition or operation for current status."""
    pass


class RunAlreadyExistsError(PipelineError):
    """Run with same task_name and run_id already exists."""
    pass


class StepError(CoachAgentError):
    """Error during a specific step execution."""
    pass


class FrameExtractionError(StepError):
    """Failed to extract frames from video."""
    pass


class FeatureComputationError(StepError):
    """Failed to compute features."""
    pass


class AgentError(CoachAgentError):
    """Error related to LLM input/output parsing or invocation."""
    pass


class PromptConstructionError(AgentError):
    """Failed to construct LLM prompt."""
    pass


class OutputParsingError(AgentError):
    """Failed to parse LLM output."""
    pass


class AgentInvocationError(AgentError):
    """Failed to invoke LLM."""
    pass
