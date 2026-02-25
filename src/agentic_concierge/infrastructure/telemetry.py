"""Optional OpenTelemetry tracing for agentic-concierge.

When ``opentelemetry-api`` and ``opentelemetry-sdk`` are installed (optional
dependency: ``pip install "agentic-concierge[otel]"``) this module sets up a tracer
provider with the configured exporter and returns real OTEL spans.

When the packages are **not** installed every public function returns no-op
objects so the rest of the code is completely unaware of whether OTEL is present.
This keeps OTEL a soft dependency: the fabric works identically whether it is
installed or not; observability is additive.

Usage in application code::

    from agentic_concierge.infrastructure.telemetry import get_tracer

    tracer = get_tracer()
    with tracer.start_as_current_span("fabric.my_operation") as span:
        span.set_attribute("key", "value")
        ...

Configuration (``ConciergeConfig.telemetry``)::

    telemetry:
        enabled: true
        exporter: console      # "none" | "console" | "otlp"
        service_name: my-app   # shown in traces
        otlp_endpoint: ""      # required when exporter="otlp"
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from agentic_concierge.config import ConciergeConfig

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# No-op shim (used when OTEL is not installed or telemetry is disabled)
# ---------------------------------------------------------------------------

class _NoOpSpan:
    """Minimal no-op span that satisfies the context-manager protocol."""

    def set_attribute(self, key: str, value: Any) -> None:  # noqa: ARG002
        pass

    def record_exception(self, exc: BaseException) -> None:  # noqa: ARG002
        pass

    def set_status(self, *args: Any, **kwargs: Any) -> None:
        pass

    def __enter__(self) -> "_NoOpSpan":
        return self

    def __exit__(self, *args: Any) -> None:
        pass


class _NoOpTracer:
    """Minimal no-op tracer."""

    def start_as_current_span(self, name: str, **kwargs: Any) -> _NoOpSpan:  # noqa: ARG002
        return _NoOpSpan()


_NOOP_TRACER = _NoOpTracer()

# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------

_tracer: Any = None          # real opentelemetry.trace.Tracer once initialised
_otel_available: bool = False

try:
    import opentelemetry  # noqa: F401
    _otel_available = True
except ImportError:
    pass


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def setup_telemetry(config: "ConciergeConfig") -> None:
    """Initialise the tracer provider from ``config.telemetry``.

    Safe to call multiple times; subsequent calls are no-ops if a tracer is
    already set up.  Call once at application startup (CLI or HTTP API).

    If telemetry is disabled in config (``enabled=False``) or OTEL is not
    installed this function is a no-op.
    """
    global _tracer  # noqa: PLW0603

    if _tracer is not None:
        return  # already initialised

    tel_cfg = getattr(config, "telemetry", None)
    if tel_cfg is None or not getattr(tel_cfg, "enabled", False):
        logger.debug("Telemetry disabled or not configured; using no-op tracer")
        return

    if not _otel_available:
        logger.warning(
            "Telemetry is enabled in config but opentelemetry-sdk is not installed. "
            "Install with: pip install 'agentic-concierge[otel]'"
        )
        return

    _setup_otel_tracer(tel_cfg)


def _setup_otel_tracer(tel_cfg: Any) -> None:
    """Internal: configure the real OTEL tracer provider."""
    global _tracer  # noqa: PLW0603

    from opentelemetry import trace
    from opentelemetry.sdk.resources import SERVICE_NAME, Resource
    from opentelemetry.sdk.trace import TracerProvider

    resource = Resource(attributes={SERVICE_NAME: tel_cfg.service_name})
    provider = TracerProvider(resource=resource)

    exporter_name = getattr(tel_cfg, "exporter", "none")

    if exporter_name == "console":
        from opentelemetry.sdk.trace.export import (
            BatchSpanProcessor,
            ConsoleSpanExporter,
        )
        provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
        logger.info("Telemetry: console exporter configured (service=%s)", tel_cfg.service_name)

    elif exporter_name == "otlp":
        endpoint = getattr(tel_cfg, "otlp_endpoint", "") or ""
        if not endpoint:
            logger.warning("Telemetry exporter='otlp' but otlp_endpoint is not set; traces dropped")
        else:
            try:
                from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
                from opentelemetry.sdk.trace.export import BatchSpanProcessor
                provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
                logger.info(
                    "Telemetry: OTLP exporter configured (endpoint=%s service=%s)",
                    endpoint, tel_cfg.service_name,
                )
            except ImportError:
                logger.warning(
                    "OTLP exporter requested but 'opentelemetry-exporter-otlp-proto-grpc' is not installed. "
                    "Install with: pip install opentelemetry-exporter-otlp-proto-grpc"
                )

    elif exporter_name != "none":
        logger.warning("Unknown telemetry exporter %r; no spans will be exported", exporter_name)

    trace.set_tracer_provider(provider)
    _tracer = trace.get_tracer("agentic_concierge")
    logger.debug("Telemetry initialised: exporter=%s service=%s", exporter_name, tel_cfg.service_name)


def get_tracer() -> Any:
    """Return the active tracer (real OTEL tracer or no-op).

    Always safe to call — returns the no-op tracer when OTEL is not configured.
    """
    return _tracer if _tracer is not None else _NOOP_TRACER


def reset_for_testing() -> None:
    """Reset module state for use in tests. Not for production use."""
    global _tracer  # noqa: PLW0603
    _tracer = None
    if _otel_available:
        from opentelemetry import trace
        trace.set_tracer_provider(trace.NoOpTracerProvider())
