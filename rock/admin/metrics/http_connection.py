"""Per-worker inbound connection and proxy lifecycle observability.

Uvicorn creates one protocol instance for every transport accepted by a
worker.  Instrumenting the protocol therefore lets us distinguish TCP
connection distribution from HTTP request distribution on keep-alive
connections.
"""

from __future__ import annotations

import asyncio
import itertools
import json
import logging
import os
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from uvicorn.protocols.http.httptools_impl import HttpToolsProtocol
from uvicorn.protocols.websockets.websockets_impl import WebSocketProtocol

from rock.admin.metrics.constants import MetricsConstants
from rock.logger import init_logger
from rock.utils.system import get_instance_id

if TYPE_CHECKING:
    from rock.admin.metrics.monitor import MetricsMonitor


logger = init_logger("connectionLog")

_identity_pid: int | None = None
_identity_pod = ""


def _process_identity() -> tuple[int, str]:
    """Return a cached identity, refreshing it after a possible fork."""
    global _identity_pid, _identity_pod

    pid = os.getpid()
    if _identity_pid != pid:
        _identity_pid = pid
        try:
            _identity_pod = get_instance_id()
        except Exception:
            _identity_pod = "unknown"
    return pid, _identity_pod


def log_observation_event(event: str, *, level: int = logging.INFO, **fields: object) -> None:
    """Write one compact lifecycle record without allowing logging to affect traffic."""
    try:
        pid, pod = _process_identity()
        record = {
            "event": event,
            "pod": pod,
            "worker_pid": str(pid),
            **{key: value for key, value in fields.items() if value is not None},
        }
        logger.log(
            level,
            json.dumps(record, ensure_ascii=False, separators=(",", ":"), default=str),
        )
    except Exception:
        # Observability must never break Uvicorn protocol callbacks or responses.
        return


def _split_address(address: object) -> tuple[str | None, int | None]:
    if isinstance(address, (tuple, list)) and address:
        host = str(address[0])
        port = address[1] if len(address) > 1 and isinstance(address[1], int) else None
        return host, port
    if address is None:
        return None, None
    return str(address), None


@dataclass(slots=True)
class ConnectionRecord:
    connection_id: str
    accepted_at: float
    remote_ip: str | None
    remote_port: int | None
    local_ip: str | None
    local_port: int | None
    protocol: str
    request_count: int = 0
    request_sequence: int = 0


@dataclass(frozen=True, slots=True)
class ConnectionRequestContext:
    connection_id: str
    request_sequence: int


@dataclass(frozen=True, slots=True)
class WorkerObservationSnapshot:
    accepted_connections: int
    closed_connections: int
    active_connections: int
    proxy_requests_inflight: int
    sse_inflight: int


class WorkerConnectionTracker:
    """Process-local state for one Uvicorn worker."""

    def __init__(self) -> None:
        self._pid = os.getpid()
        self._sequence = itertools.count(1)
        self._connections: dict[int, ConnectionRecord] = {}
        self._accepted_connections = 0
        self._closed_connections = 0
        self._proxy_requests_inflight = 0
        self._sse_inflight = 0
        self._monitor: MetricsMonitor | None = None

    def _ensure_process(self) -> None:
        """Discard inherited state if this module was imported before fork."""
        current_pid = os.getpid()
        if self._pid == current_pid:
            return
        self._pid = current_pid
        self._sequence = itertools.count(1)
        self._connections.clear()
        self._accepted_connections = 0
        self._closed_connections = 0
        self._proxy_requests_inflight = 0
        self._sse_inflight = 0
        self._monitor = None

    def bind_monitor(self, monitor: MetricsMonitor) -> None:
        self._ensure_process()
        # Resolve and cache pod identity during worker startup, not on the first
        # accepted transport where DNS latency could perturb burst scheduling.
        _process_identity()
        self._monitor = monitor
        self._record_gauge(MetricsConstants.HTTP_SERVER_ACTIVE_CONNECTIONS, len(self._connections))
        self._record_gauge(MetricsConstants.PROXY_REQUEST_INFLIGHT, self._proxy_requests_inflight)
        self._record_gauge(MetricsConstants.PROXY_SSE_INFLIGHT, self._sse_inflight)

    def _record_counter(self, name: str, value: int = 1) -> None:
        if self._monitor is None:
            return
        try:
            self._monitor.record_counter_by_name(name, value)
        except Exception as exc:
            log_observation_event(
                "observability.metric_error",
                level=logging.ERROR,
                metric=name,
                exception_type=type(exc).__name__,
                exception_message=str(exc),
            )

    def _record_gauge(self, name: str, value: int) -> None:
        if self._monitor is None:
            return
        try:
            self._monitor.record_gauge_by_name(name, value)
        except Exception as exc:
            log_observation_event(
                "observability.metric_error",
                level=logging.ERROR,
                metric=name,
                exception_type=type(exc).__name__,
                exception_message=str(exc),
            )

    def register_transport(self, transport: asyncio.Transport, protocol: str) -> ConnectionRecord:
        self._ensure_process()
        transport_key = id(transport)
        existing = self._connections.get(transport_key)
        if existing is not None:
            if existing.protocol != protocol:
                previous_protocol = existing.protocol
                existing.protocol = protocol
                log_observation_event(
                    "tcp.protocol_upgraded",
                    connection_id=existing.connection_id,
                    previous_protocol=previous_protocol,
                    protocol=protocol,
                    remote_ip=existing.remote_ip,
                    remote_port=existing.remote_port,
                    local_ip=existing.local_ip,
                    local_port=existing.local_port,
                )
            return existing

        remote_ip, remote_port = _split_address(transport.get_extra_info("peername"))
        local_ip, local_port = _split_address(transport.get_extra_info("sockname"))
        record = ConnectionRecord(
            connection_id=f"{self._pid}-{next(self._sequence)}",
            accepted_at=time.perf_counter(),
            remote_ip=remote_ip,
            remote_port=remote_port,
            local_ip=local_ip,
            local_port=local_port,
            protocol=protocol,
        )
        self._connections[transport_key] = record
        self._accepted_connections += 1
        self._record_counter(MetricsConstants.HTTP_SERVER_ACCEPTED_CONNECTIONS)
        self._record_gauge(MetricsConstants.HTTP_SERVER_ACTIVE_CONNECTIONS, len(self._connections))
        log_observation_event(
            "tcp.accepted",
            connection_id=record.connection_id,
            protocol=protocol,
            remote_ip=remote_ip,
            remote_port=remote_port,
            local_ip=local_ip,
            local_port=local_port,
            active_connections=len(self._connections),
            accepted_connections=self._accepted_connections,
        )
        return record

    def begin_http_request(self, transport: asyncio.Transport) -> ConnectionRequestContext | None:
        self._ensure_process()
        record = self._connections.get(id(transport))
        if record is None:
            return None
        record.request_count += 1
        record.request_sequence += 1
        return ConnectionRequestContext(record.connection_id, record.request_sequence)

    def log_http_request(
        self,
        transport: asyncio.Transport,
        context: ConnectionRequestContext | None,
        *,
        method: str | None,
        path: str | None,
        http_version: str | None,
    ) -> None:
        if context is None:
            return
        record = self._connections.get(id(transport))
        log_observation_event(
            "http.request_started",
            connection_id=context.connection_id,
            connection_request_seq=context.request_sequence,
            method=method,
            path=path,
            http_version=http_version,
            protocol=record.protocol if record else None,
            remote_ip=record.remote_ip if record else None,
            remote_port=record.remote_port if record else None,
        )

    def unregister_transport(self, transport: asyncio.Transport, exc: BaseException | None = None) -> None:
        self._ensure_process()
        record = self._connections.pop(id(transport), None)
        if record is None:
            return
        self._closed_connections += 1
        self._record_counter(MetricsConstants.HTTP_SERVER_CLOSED_CONNECTIONS)
        self._record_gauge(MetricsConstants.HTTP_SERVER_ACTIVE_CONNECTIONS, len(self._connections))
        log_observation_event(
            "tcp.closed",
            level=logging.ERROR if exc else logging.INFO,
            connection_id=record.connection_id,
            protocol=record.protocol,
            remote_ip=record.remote_ip,
            remote_port=record.remote_port,
            local_ip=record.local_ip,
            local_port=record.local_port,
            lifetime_ms=round((time.perf_counter() - record.accepted_at) * 1000, 3),
            request_started_count=record.request_count,
            active_connections=len(self._connections),
            closed_connections=self._closed_connections,
            close_reason="error" if exc else "eof",
            exception_type=type(exc).__name__ if exc else None,
            exception_message=str(exc) if exc else None,
        )

    def proxy_request_started(self) -> int:
        self._ensure_process()
        self._proxy_requests_inflight += 1
        self._record_counter(MetricsConstants.PROXY_REQUEST_TOTAL)
        self._record_gauge(MetricsConstants.PROXY_REQUEST_INFLIGHT, self._proxy_requests_inflight)
        return self._proxy_requests_inflight

    def proxy_request_finished(self) -> int:
        self._ensure_process()
        self._proxy_requests_inflight = max(0, self._proxy_requests_inflight - 1)
        self._record_gauge(MetricsConstants.PROXY_REQUEST_INFLIGHT, self._proxy_requests_inflight)
        return self._proxy_requests_inflight

    def sse_opened(self) -> int:
        self._ensure_process()
        self._sse_inflight += 1
        self._record_counter(MetricsConstants.PROXY_SSE_OPENED)
        self._record_gauge(MetricsConstants.PROXY_SSE_INFLIGHT, self._sse_inflight)
        return self._sse_inflight

    def sse_finished(self, reason: str, *, close_failed: bool = False) -> int:
        self._ensure_process()
        self._sse_inflight = max(0, self._sse_inflight - 1)
        self._record_counter(MetricsConstants.PROXY_SSE_CLOSED)
        if reason == "cancelled":
            self._record_counter(MetricsConstants.PROXY_SSE_CANCELLED)
        if reason == "error" or close_failed:
            self._record_counter(MetricsConstants.PROXY_SSE_ERRORS)
        self._record_gauge(MetricsConstants.PROXY_SSE_INFLIGHT, self._sse_inflight)
        return self._sse_inflight

    def pool_timeout(self) -> None:
        self._ensure_process()
        self._record_counter(MetricsConstants.HTTP_POOL_TIMEOUTS)

    def snapshot(self) -> WorkerObservationSnapshot:
        self._ensure_process()
        return WorkerObservationSnapshot(
            accepted_connections=self._accepted_connections,
            closed_connections=self._closed_connections,
            active_connections=len(self._connections),
            proxy_requests_inflight=self._proxy_requests_inflight,
            sse_inflight=self._sse_inflight,
        )


worker_connection_tracker = WorkerConnectionTracker()


def _log_protocol_error(action: str, exc: BaseException) -> None:
    log_observation_event(
        "observability.protocol_error",
        level=logging.ERROR,
        action=action,
        exception_type=type(exc).__name__,
        exception_message=str(exc),
    )


class ObservedHttpToolsProtocol(HttpToolsProtocol):
    """Uvicorn HTTP protocol that exposes per-worker accepted transports."""

    _observation_context: ConnectionRequestContext | None = None

    def connection_made(self, transport: asyncio.Transport) -> None:  # type: ignore[override]
        super().connection_made(transport)
        try:
            worker_connection_tracker.register_transport(transport, "http")
        except Exception as exc:
            _log_protocol_error("http.connection_made", exc)

    def on_message_begin(self) -> None:
        super().on_message_begin()
        try:
            context = worker_connection_tracker.begin_http_request(self.transport)
            self._observation_context = context
            if context is not None:
                self.scope["state"]["connection_id"] = context.connection_id
                self.scope["state"]["connection_request_seq"] = context.request_sequence
        except Exception as exc:
            self._observation_context = None
            _log_protocol_error("http.on_message_begin", exc)

    def on_headers_complete(self) -> None:
        super().on_headers_complete()
        try:
            worker_connection_tracker.log_http_request(
                self.transport,
                self._observation_context,
                method=self.scope.get("method"),
                path=self.scope.get("path"),
                http_version=self.scope.get("http_version"),
            )
        except Exception as exc:
            _log_protocol_error("http.on_headers_complete", exc)

    def connection_lost(self, exc: Exception | None) -> None:
        try:
            super().connection_lost(exc)
        finally:
            try:
                worker_connection_tracker.unregister_transport(self.transport, exc)
            except Exception as observer_exc:
                _log_protocol_error("http.connection_lost", observer_exc)


class ObservedWebSocketProtocol(WebSocketProtocol):
    """Keep HTTP-upgraded transports observable until WebSocket close."""

    def connection_made(self, transport: asyncio.Transport) -> None:  # type: ignore[override]
        super().connection_made(transport)
        try:
            worker_connection_tracker.register_transport(transport, "websocket")
        except Exception as exc:
            _log_protocol_error("websocket.connection_made", exc)

    def connection_lost(self, exc: Exception | None) -> None:
        try:
            super().connection_lost(exc)
        finally:
            try:
                worker_connection_tracker.unregister_transport(self.transport, exc)
            except Exception as observer_exc:
                _log_protocol_error("websocket.connection_lost", observer_exc)


__all__ = [
    "ObservedHttpToolsProtocol",
    "ObservedWebSocketProtocol",
    "WorkerConnectionTracker",
    "log_observation_event",
    "worker_connection_tracker",
]
