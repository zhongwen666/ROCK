class MetricsConstants:
    METRICS_METER_NAME = "XRL_GATEWAY_CONFIG"

    SANDBOX_REQUEST_TOTAL = "request.total"
    SANDBOX_REQUEST_SUCCESS = "request.success"
    SANDBOX_REQUEST_FAILURE = "request.failure"
    SANDBOX_REQUEST_CLIENT_ERROR = "request.client_error"

    SANDBOX_REQUEST_RT = "request.rt"

    SANDBOX_TOTAL_COUNT = "sandbox.count.total"
    SANDBOX_COUNT_IMAGE = "sandbox.count.image"

    SANDBOX_CPU = "system.cpu"
    SANDBOX_MEM = "system.memory"
    SANDBOX_DISK = "system.disk"
    SANDBOX_DISK_LOG = "system.disk.log"
    SANDBOX_DISK_DIND = "system.disk.dind"
    SANDBOX_NET = "system.network"

    TOTAL_CPU_RESOURCE = "resource.cpu.total"
    TOTAL_MEM_RESOURCE = "resource.mem.total"
    AVAILABLE_CPU_RESOURCE = "resource.cpu.available"
    AVAILABLE_MEM_RESOURCE = "resource.mem.available"
    TOTAL_DISK_RESOURCE = "resource.disk.total"
    AVAILABLE_DISK_RESOURCE = "resource.disk.available"
    DISK_OVERCOMMIT_RATIO = "resource.disk.overcommit_ratio"

    SANDBOX_PHASE_FAILURE = "sandbox.phase.failure"

    METASTORE_TOTAL = "meta_store.total"
    METASTORE_SUCCESS = "meta_store.success"
    METASTORE_FAILURE = "meta_store.failure"
    METASTORE_RT = "meta_store.rt"

    METASTORE_DB_TOTAL = "meta_store.db.total"
    METASTORE_DB_SUCCESS = "meta_store.db.success"
    METASTORE_DB_FAILURE = "meta_store.db.failure"
    METASTORE_DB_RT = "meta_store.db.rt"

    HTTP_POOL_ACTIVE_CONNECTIONS = "http_pool.active_connections"
    HTTP_POOL_IDLE_CONNECTIONS = "http_pool.idle_connections"
    HTTP_POOL_INFLIGHT_REQUESTS = "http_pool.inflight_requests"
    HTTP_POOL_PENDING_REQUESTS = "http_pool.pending_requests"
    HTTP_POOL_TIMEOUTS = "http_pool.pool_timeouts"

    HTTP_SERVER_ACCEPTED_CONNECTIONS = "http_server.accepted_connections"
    HTTP_SERVER_CLOSED_CONNECTIONS = "http_server.closed_connections"
    HTTP_SERVER_ACTIVE_CONNECTIONS = "http_server.active_connections"

    PROXY_REQUEST_TOTAL = "proxy.request.total"
    PROXY_REQUEST_INFLIGHT = "proxy.request.inflight"

    PROXY_SSE_OPENED = "proxy.sse.opened"
    PROXY_SSE_CLOSED = "proxy.sse.closed"
    PROXY_SSE_INFLIGHT = "proxy.sse.inflight"
    PROXY_SSE_CANCELLED = "proxy.sse.cancelled"
    PROXY_SSE_ERRORS = "proxy.sse.errors"
