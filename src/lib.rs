use pyo3::prelude::*;

pub mod server;
pub mod router;
pub mod validation;
pub mod threadpool;
pub mod zerocopy;
pub mod middleware;
pub mod http2;
pub mod websocket;
pub mod micro_bench;
mod request;
mod response;

// Bring types into scope for pyo3 registration
use crate::server::TurboServer;

pub use request::RequestView;
pub use response::ResponseView;
pub use validation::ValidationBridge;
pub use router::{RadixRouter, RouteMatch, RouterStats};
pub use threadpool::{WorkStealingPool, CpuPool, AsyncExecutor, ConcurrencyManager};
pub use http2::{Http2Server, ServerPush, Http2Stream};
pub use websocket::{WebSocketServer, WebSocketConnection, WebSocketMessage, BroadcastManager};
pub use zerocopy::{ZeroCopyBufferPool, ZeroCopyBuffer, ZeroCopyBytes, StringInterner, ZeroCopyFileReader, SIMDProcessor, ZeroCopyResponse};
pub use middleware::{MiddlewarePipeline, RequestContext, ResponseContext, BuiltinMiddleware, CorsMiddleware, RateLimitMiddleware, CompressionMiddleware, AuthenticationMiddleware, LoggingMiddleware, CachingMiddleware};

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

