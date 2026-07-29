"""A minimal fictional monitoring backend.

A monitoring backend records and serves observability data through two faces: a
``MonitoringWriter`` that opens and records spans and events as tools and agents
run, and a ``MonitoringReader`` that answers metric and trace queries. You
register a zero-argument builder that returns the backend; the runtime installs
it, replacing the no-op default. This example keeps spans in a list and serves an
empty read surface; a real backend forwards to its own store (an OpenTelemetry
exporter, a tracing service, a database).
"""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from typing import Any

from tai42_contract.app import tai42_app
from tai42_contract.monitoring import (
    DEFAULT_LEVEL,
    MetricsFilter,
    MetricsResult,
    MonitoringFilter,
    MonitoringLevel,
    MonitoringTrace,
    OrderBy,
    ProjectConfig,
    Span,
    SpanKind,
    SpanWindowItem,
    TraceContext,
    TraceNotFoundError,
)


class InMemorySpan:
    """A span handle. Both methods are fail-safe — they never raise into a flow."""

    @property
    def id(self) -> str:
        return ""

    def update(
        self,
        *,
        output: Any = None,
        model: str | None = None,
        usage_details: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        level: MonitoringLevel | None = None,
        status_message: str | None = None,
    ) -> None:
        pass

    def set_trace_metadata(self, *, name: str | None = None, tags: list[str] | None = None) -> None:
        pass


class InMemoryWriter:
    """Records spans and events into a per-process list."""

    def __init__(self) -> None:
        self.events: list[str] = []

    @contextmanager
    def start_span(
        self,
        *,
        name: str,
        kind: SpanKind,
        trace_context: TraceContext | None = None,
        input: Any = None,
        model: str | None = None,
        model_parameters: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Iterator[Span]:
        self.events.append(name)
        yield InMemorySpan()

    def record_span(
        self,
        *,
        name: str,
        kind: SpanKind,
        start: datetime,
        end: datetime,
        trace_context: TraceContext,
        input: Any = None,
        output: Any = None,
        level: MonitoringLevel | None = None,
        status_message: str | None = None,
        model: str | None = None,
        usage_details: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.events.append(name)

    def create_event(
        self,
        *,
        name: str,
        level: MonitoringLevel = DEFAULT_LEVEL,
        trace_context: TraceContext | None = None,
        input: Any = None,
        output: Any = None,
        status_message: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.events.append(name)

    def update_current_span(
        self,
        *,
        level: MonitoringLevel | None = None,
        status_message: str | None = None,
        metadata: dict[str, Any] | None = None,
        output: Any = None,
    ) -> None:
        pass

    @contextmanager
    def trace_attributes(
        self,
        *,
        name: str | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Iterator[None]:
        yield

    def current_trace_id(self) -> str | None:
        return None

    def inject_context(self, ctx: TraceContext) -> dict[str, Any]:
        return {}

    def get_monitoring_callbacks(self, ctx: TraceContext) -> list[object]:
        return []

    @contextmanager
    def scope(self, public_key: str) -> Iterator[None]:
        yield

    @contextmanager
    def disable(self) -> Iterator[None]:
        yield

    def flush(self) -> None:
        pass

    def shutdown(self) -> None:
        pass


class InMemoryReader:
    """Answers read queries. This example holds no queryable history."""

    async def query_metrics(self, filter: MetricsFilter) -> MetricsResult:
        return MetricsResult()

    async def list_spans_in_window(
        self,
        t0: datetime,
        t1: datetime,
        *,
        run: str | None = None,
        kind: SpanKind | None = None,
        filter: MonitoringFilter | None = None,
        order_by: OrderBy | None = None,
    ) -> list[SpanWindowItem]:
        return []

    async def get_trace(self, trace_id: str) -> MonitoringTrace:
        # Non-optional contract: an absent trace raises, never returns None.
        raise TraceNotFoundError(f"trace {trace_id!r} not found")

    async def list_traces(
        self,
        *,
        from_timestamp: datetime | None = None,
        to_timestamp: datetime | None = None,
        limit: int | None = None,
        page: int | None = None,
        filter: MonitoringFilter | None = None,
        order_by: OrderBy | None = None,
    ) -> list[MonitoringTrace]:
        return []


class InMemoryMonitoring:
    """One backend, two faces: a writer that emits and a reader that queries."""

    def __init__(self) -> None:
        self._writer = InMemoryWriter()
        self._reader = InMemoryReader()

    @property
    def writer(self) -> InMemoryWriter:
        return self._writer

    @property
    def reader(self) -> InMemoryReader:
        return self._reader

    def add_project(self, project: ProjectConfig) -> None:
        pass


@tai42_app.monitoring.register_monitoring
def build_monitoring() -> InMemoryMonitoring:
    """Return the process monitoring backend. One provider per process."""
    return InMemoryMonitoring()
