use pyo3::prelude::*;

pub mod http2;
pub mod micro_bench;
pub mod middleware;
pub mod python_worker;
mod request;
mod response;
pub mod router;
pub mod server;
pub mod simd_json;
pub mod simd_parse;
pub mod threadpool;
pub mod validation;
pub mod websocket;
pub mod zerocopy;

// Bring types into scope for pyo3 registration
use crate::server::TurboServer;

pub use http2::{Http2Server, Http2Stream, ServerPush};
pub use middleware::{
    AuthenticationMiddleware, BuiltinMiddleware, CachingMiddleware, CompressionMiddleware,
    CorsMiddleware, LoggingMiddleware, MiddlewarePipeline, RateLimitMiddleware, RequestContext,
    ResponseContext,
};
pub use request::RequestView;
pub use response::ResponseView;
pub use router::{RadixRouter, RouteMatch, RouterStats};
pub use threadpool::{AsyncExecutor, ConcurrencyManager, CpuPool, WorkStealingPool};
pub use validation::ValidationBridge;
pub use websocket::{BroadcastManager, WebSocketConnection, WebSocketMessage, WebSocketServer};
pub use zerocopy::{
    SIMDProcessor, StringInterner, ZeroCopyBuffer, ZeroCopyBufferPool, ZeroCopyBytes,
    ZeroCopyFileReader, ZeroCopyResponse,
};

/// TurboNet - Rust HTTP core for TurboAPI with free-threading support
#[pymodule(gil_used = false)]
fn turbonet(m: &Bound<'_, PyModule>) -> PyResult<()> {
    // Phase 0-3: Core HTTP and concurrency
    m.add_class::<TurboServer>()?;
    m.add_class::<RequestView>()?;
    m.add_class::<ResponseView>()?;
    m.add_class::<ValidationBridge>()?;
    m.add_class::<WorkStealingPool>()?;
    m.add_class::<CpuPool>()?;
    m.add_class::<AsyncExecutor>()?;
    m.add_class::<ConcurrencyManager>()?;

    // Phase 4: HTTP/2 and advanced protocols
    m.add_class::<Http2Server>()?;
    m.add_class::<ServerPush>()?;
    m.add_class::<Http2Stream>()?;

    // Phase 4: WebSocket real-time communication
    m.add_class::<WebSocketServer>()?;
    m.add_class::<WebSocketConnection>()?;
    m.add_class::<WebSocketMessage>()?;
    m.add_class::<BroadcastManager>()?;

    // Phase 4: Zero-copy optimizations
    m.add_class::<ZeroCopyBufferPool>()?;
    m.add_class::<ZeroCopyBuffer>()?;
    m.add_class::<ZeroCopyBytes>()?;
    m.add_class::<StringInterner>()?;
    m.add_class::<ZeroCopyFileReader>()?;
    m.add_class::<SIMDProcessor>()?;
    m.add_class::<ZeroCopyResponse>()?;

    // Phase 5: Advanced middleware pipeline
    m.add_class::<MiddlewarePipeline>()?;
    m.add_class::<RequestContext>()?;
    m.add_class::<ResponseContext>()?;
    m.add_class::<BuiltinMiddleware>()?;
    m.add_class::<CorsMiddleware>()?;
    m.add_class::<RateLimitMiddleware>()?;
    m.add_class::<CompressionMiddleware>()?;
    m.add_class::<AuthenticationMiddleware>()?;
    m.add_class::<LoggingMiddleware>()?;
    m.add_class::<CachingMiddleware>()?;

    // Rate limiting configuration
    m.add_function(wrap_pyfunction!(server::configure_rate_limiting, m)?)?;

    Ok(())
}
