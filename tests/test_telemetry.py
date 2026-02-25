"""Tests for infrastructure/telemetry.py — no-op shim and real OTEL integration.

All tests that exercise real OTEL spans use InMemorySpanExporter so no real
OTLP endpoint is required.  The module's _tracer global is reset between tests
via reset_for_testing() to avoid state leakage.
"""
from __future__ import annotations

import pytest

from agentic_concierge.infrastructure.telemetry import (
    _NOOP_TRACER,
    _NoOpSpan,
    _NoOpTracer,
    get_tracer,
    reset_for_testing,
    setup_telemetry,
)
from agentic_concierge.config.schema import ConciergeConfig, ModelConfig, SpecialistConfig, TelemetryConfig


# ---------------------------------------------------------------------------
# Minimal ConciergeConfig factory helpers
# ---------------------------------------------------------------------------

def _minimal_config(telemetry: TelemetryConfig | None = None) -> ConciergeConfig:
    return ConciergeConfig(
        models={"quality": ModelConfig(base_url="http://localhost:11434/v1", model="test")},
        specialists={"engineering": SpecialistConfig(description="d", workflow="engineering")},
        telemetry=telemetry,
    )


# ---------------------------------------------------------------------------
# No-op shim
# ---------------------------------------------------------------------------

def test_noop_span_set_attribute_is_silent():
    span = _NoOpSpan()
    span.set_attribute("key", "value")  # must not raise


def test_noop_span_context_manager():
    span = _NoOpSpan()
    with span as s:
        assert s is span


def test_noop_tracer_returns_noop_span():
    tracer = _NoOpTracer()
    with tracer.start_as_current_span("test") as span:
        assert isinstance(span, _NoOpSpan)


def test_get_tracer_returns_noop_when_disabled(tmp_path):
    """When telemetry is disabled (default), get_tracer() returns the no-op tracer."""
    reset_for_testing()
    config = _minimal_config(telemetry=None)
    setup_telemetry(config)
    tracer = get_tracer()
    assert tracer is _NOOP_TRACER


def test_get_tracer_returns_noop_when_enabled_false():
    reset_for_testing()
    config = _minimal_config(telemetry=TelemetryConfig(enabled=False))
    setup_telemetry(config)
    assert get_tracer() is _NOOP_TRACER


def test_setup_telemetry_idempotent():
    """Calling setup_telemetry twice does not raise or re-initialise."""
    reset_for_testing()
    config = _minimal_config()
    setup_telemetry(config)
    setup_telemetry(config)  # second call is a no-op


def test_reset_for_testing_clears_state():
    reset_for_testing()
    assert get_tracer() is _NOOP_TRACER


# ---------------------------------------------------------------------------
# Real OTEL with InMemorySpanExporter (requires opentelemetry-sdk)
# ---------------------------------------------------------------------------

try:
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry import trace as otel_trace
    _OTEL_AVAILABLE = True
except ImportError:
    _OTEL_AVAILABLE = False

otel_only = pytest.mark.skipif(not _OTEL_AVAILABLE, reason="opentelemetry-sdk not installed")


@otel_only
def test_setup_telemetry_console_exporter_initialises_tracer():
    """setup_telemetry with exporter='console' sets a real tracer (not no-op)."""
    reset_for_testing()
    config = _minimal_config(
        telemetry=TelemetryConfig(enabled=True, exporter="console", service_name="test-svc")
    )
    setup_telemetry(config)
    tracer = get_tracer()
    assert tracer is not _NOOP_TRACER


@otel_only
def test_spans_emitted_via_in_memory_exporter():
    """Verify that start_as_current_span produces a real span captured by an in-memory exporter."""
    reset_for_testing()

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    # Get a tracer directly from our local provider (avoids global TracerProvider override
    # restrictions — OTEL warns and silently ignores set_tracer_provider() if already set).
    import agentic_concierge.infrastructure.telemetry as tel_mod
    tel_mod._tracer = provider.get_tracer("test")

    tracer = get_tracer()
    with tracer.start_as_current_span("fabric.test_span") as span:
        span.set_attribute("key", "value")

    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    assert spans[0].name == "fabric.test_span"
    assert spans[0].attributes["key"] == "value"

    reset_for_testing()


@otel_only
def test_nested_spans_parent_child():
    """Nested with-blocks produce parent/child spans."""
    reset_for_testing()

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))

    import agentic_concierge.infrastructure.telemetry as tel_mod
    tel_mod._tracer = provider.get_tracer("test")

    tracer = get_tracer()
    with tracer.start_as_current_span("parent") as _:
        with tracer.start_as_current_span("child") as _:
            pass

    spans = exporter.get_finished_spans()
    assert len(spans) == 2
    names = {s.name for s in spans}
    assert names == {"parent", "child"}

    reset_for_testing()


# ---------------------------------------------------------------------------
# TelemetryConfig schema
# ---------------------------------------------------------------------------

def test_telemetry_config_defaults():
    cfg = TelemetryConfig()
    assert cfg.enabled is False
    assert cfg.service_name == "agentic-concierge"
    assert cfg.exporter == "none"
    assert cfg.otlp_endpoint == ""


def test_telemetry_config_fabric_config_optional():
    """ConciergeConfig with no telemetry key is valid."""
    config = _minimal_config(telemetry=None)
    assert config.telemetry is None


def test_telemetry_config_fabric_config_present():
    config = _minimal_config(telemetry=TelemetryConfig(enabled=True, exporter="console"))
    assert config.telemetry is not None
    assert config.telemetry.enabled is True
    assert config.telemetry.exporter == "console"
