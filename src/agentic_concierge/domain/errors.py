"""Domain and application errors."""


class FabricError(Exception):
    """Base for fabric errors."""
    pass


class RecruitError(FabricError):
    """Failed to recruit specialist(s) for the task."""
    pass


class ToolExecutionError(FabricError):
    """Tool execution failed (sandbox, permission, or tool error)."""
    pass
