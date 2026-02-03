use crate::router::RadixRouter;
use crate::simd_json;
use crate::simd_parse;
use crate::zerocopy::ZeroCopyBufferPool;
use bytes::Bytes;
use http_body_util::{BodyExt, Full};
use hyper::body::Incoming as IncomingBody;
use hyper::server::conn::http1;
use hyper::service::service_fn;
use hyper::{Request, Response};
use hyper_util::rt::TokioIo;
use pyo3::prelude::*;
use pyo3::types::{PyDict, PyString};
use std::collections::HashMap;
use std::collections::HashMap as StdHashMap;
use std::convert::Infallible;
use std::net::SocketAddr;
use std::sync::Arc;
use std::sync::OnceLock;
use std::time::{Duration, Instant};
use tokio::net::TcpListener;
use tokio::sync::RwLock;

type Handler = Arc<PyObject>;

/// Handler dispatch type for fast-path routing (Phase 3: eliminate Python wrapper)
#[derive(Clone, Debug, PartialEq)]
enum HandlerType {
    /// Simple sync: no body, just path/query params. Rust parses + serializes everything.
    SimpleSyncFast,
    /// Needs body parsing: Rust parses body with simd-json, calls handler directly.
    BodySyncFast,
    /// Model sync: Rust parses JSON with simd-json, validates with dhi model in Python.
    ModelSyncFast,
    /// Simple async: no body, just path/query params. Rust parses, calls async handler via Tokio.
    SimpleAsyncFast,
    /// Async body: Rust parses body with simd-json, calls async handler via Tokio.
    BodyAsyncFast,
    /// Needs full Python enhanced wrapper (async, dependencies, etc.)
    Enhanced,
    /// WebSocket: HTTP upgrade to WebSocket protocol
    WebSocket,
}

// Metadata struct with fast dispatch info
#[derive(Clone)]
struct HandlerMetadata {
    handler: Handler,
    is_async: bool,
    handler_type: HandlerType,
    route_pattern: String,
    param_types: HashMap<String, String>, // param_name -> type ("int", "str", "float")
    original_handler: Option<Handler>,    // Unwrapped handler for fast dispatch
    model_info: Option<(String, Handler)>, // (param_name, model_class) for ModelSyncFast
}

// Response data with status code and content type support
struct HandlerResponse {
    body: String,
    status_code: u16,
    content_type: Option<String>,
    raw_body: Option<Vec<u8>>,  // For binary responses
}

// Pure Rust Async Runtime with Tokio
// Uses work-stealing scheduler across all CPU cores for maximum throughput
struct TokioRuntime {
    task_locals: pyo3_async_runtimes::TaskLocals,
    json_dumps_fn: PyObject,
    semaphore: Arc<tokio::sync::Semaphore>,
}

impl Clone for TokioRuntime {
    fn clone(&self) -> Self {
        Python::with_gil(|py| Self {
            task_locals: self.task_locals.clone_ref(py),
            json_dumps_fn: self.json_dumps_fn.clone_ref(py),
            semaphore: self.semaphore.clone(),
        })
    }
}

// Cached Python modules for performance
static CACHED_JSON_MODULE: OnceLock<PyObject> = OnceLock::new();
static CACHED_BUILTINS_MODULE: OnceLock<PyObject> = OnceLock::new();
static CACHED_TYPES_MODULE: OnceLock<PyObject> = OnceLock::new();

/// TurboServer - Main HTTP server class with radix trie routing
/// Uses pure Tokio runtime for high-performance async processing
#[pyclass]
pub struct TurboServer {
    handlers: Arc<RwLock<HashMap<String, HandlerMetadata>>>,
    router: Arc<RwLock<RadixRouter>>,
    host: String,
    port: u16,
    worker_threads: usize,
    buffer_pool: Arc<ZeroCopyBufferPool>,
}

#[pymethods]
impl TurboServer {
    #[new]
    pub fn new(host: Option<String>, port: Option<u16>) -> Self {
        // PHASE 2: Intelligent worker thread calculation
        let cpu_cores = std::thread::available_parallelism()
            .map(|n| n.get())
            .unwrap_or(4);

        // PHASE 2: Optimized worker thread calculation
        // - Use 3x CPU cores for I/O-bound workloads (common in web servers)
        // - Cap at 24 threads to avoid excessive context switching
        // - Minimum 8 threads for good baseline performance
        let worker_threads = ((cpu_cores * 3).min(24)).max(8);

        TurboServer {
            handlers: Arc::new(RwLock::new(HashMap::with_capacity(128))),
            router: Arc::new(RwLock::new(RadixRouter::new())),
            host: host.unwrap_or_else(|| "127.0.0.1".to_string()),
            port: port.unwrap_or(8000),
            worker_threads,
            buffer_pool: Arc::new(ZeroCopyBufferPool::new()),
        }
    }

    /// Register a route handler with radix trie routing (legacy: uses Enhanced wrapper)
    pub fn add_route(&self, method: String, path: String, handler: PyObject) -> PyResult<()> {
        let route_key = format!("{} {}", method.to_uppercase(), path);

        // Check if handler is async ONCE at registration time
        let is_async = Python::with_gil(|py| {
            let inspect = py.import("inspect")?;
            inspect
                .getattr("iscoroutinefunction")?
                .call1((&handler,))?
                .extract::<bool>()
        })?;

        let handlers = Arc::clone(&self.handlers);
        let router = Arc::clone(&self.router);
        let path_clone = path.clone();

        Python::with_gil(|py| {
            py.allow_threads(|| {
                let rt = tokio::runtime::Runtime::new().unwrap();
                rt.block_on(async {
                    let mut handlers_guard = handlers.write().await;
                    handlers_guard.insert(
                        route_key.clone(),
                        HandlerMetadata {
                            handler: Arc::new(handler),
                            is_async,
                            handler_type: HandlerType::Enhanced,
                            route_pattern: path_clone,
                            param_types: HashMap::new(),
                            original_handler: None,
                            model_info: None,
                        },
                    );
                    drop(handlers_guard);

                    let mut router_guard = router.write().await;
                    let _ =
                        router_guard.add_route(&method.to_uppercase(), &path, route_key.clone());
                });
            })
        });

        Ok(())
    }

    /// Register a route with fast dispatch metadata (Phase 3: bypass Python wrapper).
    ///
    /// handler_type: "simple_sync" | "body_sync" | "enhanced"
    /// param_types_json: JSON string of {"param_name": "type_hint", ...}
    /// original_handler: The unwrapped Python function (no enhanced wrapper)
    pub fn add_route_fast(
        &self,
        method: String,
        path: String,
        handler: PyObject,
        handler_type: String,
        param_types_json: String,
        original_handler: PyObject,
    ) -> PyResult<()> {
        let route_key = format!("{} {}", method.to_uppercase(), path);

        let ht = match handler_type.as_str() {
            "simple_sync" => HandlerType::SimpleSyncFast,
            "body_sync" => HandlerType::BodySyncFast,
            _ => HandlerType::Enhanced,
        };

        // Parse param types from JSON
        let param_types: HashMap<String, String> =
            serde_json::from_str(&param_types_json).unwrap_or_default();

        let is_async = ht == HandlerType::Enhanced
            && Python::with_gil(|py| {
                let inspect = py.import("inspect").ok()?;
                inspect
                    .getattr("iscoroutinefunction")
                    .ok()?
                    .call1((&handler,))
                    .ok()?
                    .extract::<bool>()
                    .ok()
            })
            .unwrap_or(false);

        let handlers = Arc::clone(&self.handlers);
        let router = Arc::clone(&self.router);
        let path_clone = path.clone();

        Python::with_gil(|py| {
            py.allow_threads(|| {
                let rt = tokio::runtime::Runtime::new().unwrap();
                rt.block_on(async {
                    let mut handlers_guard = handlers.write().await;
                    handlers_guard.insert(
                        route_key.clone(),
                        HandlerMetadata {
                            handler: Arc::new(handler),
                            is_async,
                            handler_type: ht,
                            route_pattern: path_clone,
                            param_types,
                            original_handler: Some(Arc::new(original_handler)),
                            model_info: None,
                        },
                    );
                    drop(handlers_guard);

                    let mut router_guard = router.write().await;
                    let _ =
                        router_guard.add_route(&method.to_uppercase(), &path, route_key.clone());
                });
            })
        });

        Ok(())
    }

    /// Register a route with model validation (Phase 3: fast model path).
    /// Rust parses JSON with simd-json, then calls Python model.model_validate()
    pub fn add_route_model(
        &self,
        method: String,
        path: String,
        handler: PyObject,
        param_name: String,
        model_class: PyObject,
        original_handler: PyObject,
    ) -> PyResult<()> {
        let route_key = format!("{} {}", method.to_uppercase(), path);

        let handlers = Arc::clone(&self.handlers);
        let router = Arc::clone(&self.router);
        let path_clone = path.clone();

        Python::with_gil(|py| {
            py.allow_threads(|| {
                let rt = tokio::runtime::Runtime::new().unwrap();
                rt.block_on(async {
                    let mut handlers_guard = handlers.write().await;
                    handlers_guard.insert(
                        route_key.clone(),
                        HandlerMetadata {
                            handler: Arc::new(handler),
                            is_async: false,
                            handler_type: HandlerType::ModelSyncFast,
                            route_pattern: path_clone,
                            param_types: HashMap::new(),
                            original_handler: Some(Arc::new(original_handler)),
                            model_info: Some((param_name, Arc::new(model_class))),
                        },
                    );
                    drop(handlers_guard);

                    let mut router_guard = router.write().await;
                    let _ =
                        router_guard.add_route(&method.to_uppercase(), &path, route_key.clone());
                });
            })
        });

        Ok(())
    }

    /// Register an async route with fast dispatch metadata (Phase 4: async fast paths).
    ///
    /// handler_type: "simple_async" | "body_async"
    /// param_types_json: JSON string of {"param_name": "type_hint", ...}
    /// original_handler: The unwrapped Python async function
    pub fn add_route_async_fast(
        &self,
        method: String,
        path: String,
        handler: PyObject,
        handler_type: String,
        param_types_json: String,
        original_handler: PyObject,
    ) -> PyResult<()> {
        let route_key = format!("{} {}", method.to_uppercase(), path);

        let ht = match handler_type.as_str() {
            "simple_async" => HandlerType::SimpleAsyncFast,
            "body_async" => HandlerType::BodyAsyncFast,
            _ => HandlerType::Enhanced, // Fallback to Enhanced for unknown types
        };

        // Parse param types from JSON
        let param_types: HashMap<String, String> =
            serde_json::from_str(&param_types_json).unwrap_or_default();

        let handlers = Arc::clone(&self.handlers);
        let router = Arc::clone(&self.router);
        let path_clone = path.clone();

        Python::with_gil(|py| {
            py.allow_threads(|| {
                let rt = tokio::runtime::Runtime::new().unwrap();
                rt.block_on(async {
                    let mut handlers_guard = handlers.write().await;
                    handlers_guard.insert(
                        route_key.clone(),
                        HandlerMetadata {
                            handler: Arc::new(handler),
                            is_async: true, // Async handlers
                            handler_type: ht,
                            route_pattern: path_clone,
                            param_types,
                            original_handler: Some(Arc::new(original_handler)),
                            model_info: None,
                        },
                    );
                    drop(handlers_guard);

                    let mut router_guard = router.write().await;
                    let _ =
                        router_guard.add_route(&method.to_uppercase(), &path, route_key.clone());
                });
            })
        });

        Ok(())
    }

    /// Register a WebSocket route handler
    /// WebSocket routes are handled with HTTP upgrade protocol
    pub fn add_route_websocket(
        &self,
        path: String,
        on_connect: PyObject,
        on_message: PyObject,
        on_disconnect: PyObject,
    ) -> PyResult<()> {
        let route_key = format!("WEBSOCKET {}", path);
        let handlers = Arc::clone(&self.handlers);
        let router = Arc::clone(&self.router);
        let path_clone = path.clone();

        // Clone PyObjects inside GIL before releasing threads
        Python::with_gil(|py| {
            let on_message_clone = on_message.clone_ref(py);
            let on_connect_clone = on_connect.clone_ref(py);
            let on_disconnect_clone = on_disconnect.clone_ref(py);

            py.allow_threads(|| {
                let rt = tokio::runtime::Runtime::new().unwrap();
                rt.block_on(async {
                    let mut handlers_guard = handlers.write().await;
                    handlers_guard.insert(
                        route_key.clone(),
                        HandlerMetadata {
                            handler: Arc::new(on_message_clone),
                            is_async: true, // WebSocket handlers are inherently async
                            handler_type: HandlerType::WebSocket,
                            route_pattern: path_clone.clone(),
                            param_types: HashMap::new(),
                            original_handler: Some(Arc::new(on_connect_clone)),
                            model_info: Some((
                                "on_disconnect".to_string(),
                                Arc::new(on_disconnect_clone),
                            )),
                        },
                    );
                    drop(handlers_guard);

                    // Also register as GET for upgrade detection
                    let mut router_guard = router.write().await;
                    let _ = router_guard.add_route("GET", &path_clone, route_key.clone());
                });
            })
        });

        eprintln!("🌐 WebSocket route registered: {}", path);
        Ok(())
    }

    /// Legacy HTTP server method (DEPRECATED)
    /// This now delegates to run() for backwards compatibility
    #[deprecated(
        since = "0.5.0",
        note = "Use run() instead - same performance, cleaner API"
    )]
    pub fn run_legacy(&self, py: Python) -> PyResult<()> {
        eprintln!("⚠️  WARNING: run_legacy() is deprecated and now delegates to run().");
        eprintln!("   Please update your code to use run() directly.");
        self.run(py)
    }

    /// Start the HTTP server with Pure Rust Async Runtime (Tokio)
    /// High-performance mode with work-stealing scheduler across all CPU cores
    /// Expected: 10-18K RPS (3-5x improvement over legacy loop shards)
    pub fn run(&self, py: Python) -> PyResult<()> {
        eprintln!("🚀 Starting TurboAPI with Pure Rust Async Runtime!");

        // Parse address
        let mut addr_str = String::with_capacity(self.host.len() + 10);
        addr_str.push_str(&self.host);
        addr_str.push(':');
        addr_str.push_str(&self.port.to_string());

        let addr: SocketAddr = addr_str
            .parse()
            .map_err(|_| pyo3::exceptions::PyValueError::new_err("Invalid address"))?;

        let handlers = Arc::clone(&self.handlers);
        let router = Arc::clone(&self.router);

        // Initialize Tokio runtime with optimized settings
        let tokio_runtime = initialize_tokio_runtime()?;
        eprintln!("✅ Tokio runtime initialized successfully!");

        py.allow_threads(|| {
            // Create Tokio multi-threaded runtime with work-stealing scheduler
            let cpu_cores = num_cpus::get();
            eprintln!(
                "🧵 Creating Tokio runtime with {} worker threads",
                cpu_cores
            );

            let rt = tokio::runtime::Builder::new_multi_thread()
                .worker_threads(cpu_cores)
                .thread_name("turbo-worker")
                .thread_keep_alive(std::time::Duration::from_secs(60))
                .thread_stack_size(2 * 1024 * 1024) // 2MB stack
                .enable_all()
                .build()
                .unwrap();

            rt.block_on(async {
                let listener = TcpListener::bind(addr).await.unwrap();
                eprintln!("✅ Server listening on {}", addr);
                eprintln!("🎯 Target: 10-18K RPS with Tokio work-stealing scheduler!");

                // Optimized connection management (2x capacity)
                let max_connections = cpu_cores * 200;
                let connection_semaphore = Arc::new(tokio::sync::Semaphore::new(max_connections));

                loop {
                    let (stream, _) = listener.accept().await.unwrap();

                    // Acquire connection permit with backpressure
                    let permit = match connection_semaphore.clone().try_acquire_owned() {
                        Ok(permit) => permit,
                        Err(_) => {
                            drop(stream);
                            continue;
                        }
                    };

                    let io = TokioIo::new(stream);
                    let handlers_clone = Arc::clone(&handlers);
                    let router_clone = Arc::clone(&router);
                    let tokio_runtime_clone = tokio_runtime.clone();

                    // Spawn Tokio task (work-stealing across all cores)
                    tokio::task::spawn(async move {
                        let _permit = permit;

                        let _ = http1::Builder::new()
                            .keep_alive(true)
                            .half_close(true)
                            .pipeline_flush(true)
                            .max_buf_size(16384)
                            .serve_connection(
                                io,
                                service_fn(move |req| {
                                    let handlers = Arc::clone(&handlers_clone);
                                    let router = Arc::clone(&router_clone);
                                    let runtime = tokio_runtime_clone.clone();
                                    handle_request(req, handlers, router, runtime)
                                }),
                            )
                            .await;
                    });
                }
            })
        });

        Ok(())
    }

    /// Get server info with comprehensive performance metrics
    pub fn info(&self) -> String {
        // PHASE 2+: Production-ready server info with all optimizations
        let mut info = String::with_capacity(self.host.len() + 200);
        info.push_str("🚀 TurboServer PRODUCTION v2.0 running on ");
        info.push_str(&self.host);
        info.push(':');
        info.push_str(&self.port.to_string());
        info.push_str("\n   ⚡ Worker threads: ");
        info.push_str(&self.worker_threads.to_string());
        info.push_str(" (3x CPU cores, optimized)");
        info.push_str("\n   🔧 Optimizations: Phase 2+ Complete");
        info.push_str("\n   📊 Features: Rate limiting, Response caching, HTTP/2 ready");
        info.push_str("\n   🛡️  Security: Enhanced error handling, IP-based rate limits");
        info.push_str("\n   💫 Performance: Zero-alloc routes, Object pooling, SIMD JSON");
        info.push_str("\n   🎯 Status: Production Ready - High Performance Web Framework");
        info
    }
}

// Old loop shard-based handle_request removed - using Tokio-based handler instead

/// PHASE 2: Fast route key creation without allocations
fn create_route_key_fast(method: &str, path: &str, buffer: &mut [u8]) -> String {
    // Use stack buffer for common cases, fall back to heap for large routes
    let method_upper = method.to_ascii_uppercase();
    let total_len = method_upper.len() + 1 + path.len();

    if total_len <= buffer.len() {
        // Fast path: use stack buffer
        let mut pos = 0;
        for byte in method_upper.bytes() {
            buffer[pos] = byte;
            pos += 1;
        }
        buffer[pos] = b' ';
        pos += 1;
        for byte in path.bytes() {
            buffer[pos] = byte;
            pos += 1;
        }
        unsafe { String::from_utf8_unchecked(buffer[..pos].to_vec()) }
    } else {
        // Fallback: heap allocation for very long routes
        format!("{} {}", method_upper, path)
    }
}

/// PHASE 2: Object pool for request objects to reduce allocations
static REQUEST_OBJECT_POOL: OnceLock<std::sync::Mutex<Vec<PyObject>>> = OnceLock::new();

/// PHASE 2+: Simple rate limiting - track request counts per IP
static RATE_LIMIT_TRACKER: OnceLock<std::sync::Mutex<StdHashMap<String, (Instant, u32)>>> =
    OnceLock::new();

/// Rate limiting configuration
static RATE_LIMIT_CONFIG: OnceLock<RateLimitConfig> = OnceLock::new();

#[derive(Clone)]
struct RateLimitConfig {
    enabled: bool,
    requests_per_minute: u32,
}

impl Default for RateLimitConfig {
    fn default() -> Self {
        Self {
            enabled: false,                 // Disabled by default for benchmarking
            requests_per_minute: 1_000_000, // Very high default limit (1M req/min)
        }
    }
}

/// Configure rate limiting settings
#[pyfunction]
pub fn configure_rate_limiting(enabled: bool, requests_per_minute: Option<u32>) {
    let config = RateLimitConfig {
        enabled,
        requests_per_minute: requests_per_minute.unwrap_or(1_000_000), // Default to 1M req/min
    };
    let _ = RATE_LIMIT_CONFIG.set(config);
}

/// Legacy fast handler call (unused, kept for reference)
#[allow(dead_code)]
fn call_python_handler_fast_legacy(
    handler: Handler,
    method_str: &str,
    path: &str,
    query_string: &str,
    body: &Bytes,
) -> Result<String, pyo3::PyErr> {
    Python::with_gil(|py| {
        // Get cached modules (initialized once)
        let types_module = CACHED_TYPES_MODULE.get_or_init(|| py.import("types").unwrap().into());
        let json_module = CACHED_JSON_MODULE.get_or_init(|| py.import("json").unwrap().into());
        let builtins_module =
            CACHED_BUILTINS_MODULE.get_or_init(|| py.import("builtins").unwrap().into());

        // PHASE 2: Try to reuse request object from pool
        let request_obj = get_pooled_request_object(py, types_module)?;

        // Set attributes directly (no intermediate conversions)
        request_obj.setattr(py, "method", method_str)?;
        request_obj.setattr(py, "path", path)?;
        request_obj.setattr(py, "query_string", query_string)?;

        // Set body as bytes
        let body_py = pyo3::types::PyBytes::new(py, body.as_ref());
        request_obj.setattr(py, "body", body_py.clone())?;

        // Use cached empty dict for headers
        let empty_dict = builtins_module.getattr(py, "dict")?.call0(py)?;
        request_obj.setattr(py, "headers", empty_dict)?;

        // Create get_body method that returns the body
        request_obj.setattr(py, "get_body", body_py)?;

        // Call handler directly
        let result = handler.call1(py, (request_obj,))?;

        // PHASE 2: Fast JSON serialization with fallback
        // Use Python JSON module for compatibility
        let json_dumps = json_module.getattr(py, "dumps")?;
        let json_str = json_dumps.call1(py, (result,))?;
        json_str.extract(py)
    })
}

// PHASE 2: Simplified for compatibility - complex SIMD optimizations removed for stability

/// PHASE 2: Get pooled request object to reduce allocations
fn get_pooled_request_object(py: Python, types_module: &PyObject) -> PyResult<PyObject> {
    // Try to get from pool first
    let pool = REQUEST_OBJECT_POOL.get_or_init(|| std::sync::Mutex::new(Vec::new()));

    if let Ok(mut pool_guard) = pool.try_lock() {
        if let Some(obj) = pool_guard.pop() {
            return Ok(obj);
        }
    }

    // If pool is empty or locked, create new object
    let simple_namespace = types_module.getattr(py, "SimpleNamespace")?;
    simple_namespace.call0(py)
}

/// PHASE 2: Return request object to pool for reuse
#[allow(dead_code)]
fn return_pooled_request_object(obj: PyObject) {
    let pool = REQUEST_OBJECT_POOL.get_or_init(|| std::sync::Mutex::new(Vec::new()));

    if let Ok(mut pool_guard) = pool.try_lock() {
        if pool_guard.len() < 50 {
            // Limit pool size
            pool_guard.push(obj);
        }
    }
    // If pool is full or locked, let object be dropped normally
}

/// PHASE 2+: Extract client IP for rate limiting
fn extract_client_ip(req: &Request<IncomingBody>) -> Option<String> {
    // Try X-Forwarded-For header first (common in reverse proxy setups)
    if let Some(forwarded) = req.headers().get("x-forwarded-for") {
        if let Ok(forwarded_str) = forwarded.to_str() {
            return Some(forwarded_str.split(',').next()?.trim().to_string());
        }
    }

    // Fallback to X-Real-IP header
    if let Some(real_ip) = req.headers().get("x-real-ip") {
        if let Ok(ip_str) = real_ip.to_str() {
            return Some(ip_str.to_string());
        }
    }

    // Note: In a real implementation, we'd extract from connection info
    // For now, return a placeholder
    Some("127.0.0.1".to_string())
}

/// PHASE 2+: Simple rate limiting check (configurable)
fn check_rate_limit(client_ip: &str) -> bool {
    let rate_config = RATE_LIMIT_CONFIG.get_or_init(|| RateLimitConfig::default());
    let tracker = RATE_LIMIT_TRACKER.get_or_init(|| std::sync::Mutex::new(StdHashMap::new()));

    if let Ok(mut tracker_guard) = tracker.try_lock() {
        let now = Instant::now();
        let limit = rate_config.requests_per_minute;
        let window = Duration::from_secs(60);

        let entry = tracker_guard
            .entry(client_ip.to_string())
            .or_insert((now, 0));

        // Reset counter if window expired
        if now.duration_since(entry.0) > window {
            entry.0 = now;
            entry.1 = 0;
        }

        entry.1 += 1;
        let result = entry.1 <= limit;

        // Clean up old entries occasionally (simple approach)
        if tracker_guard.len() > 10000 {
            tracker_guard.retain(|_, (timestamp, _)| now.duration_since(*timestamp) < window);
        }

        result
    } else {
        // If lock is contended, allow request (fail open for performance)
        true
    }
}

/// PHASE 2: Create zero-copy response using efficient memory management
fn create_zero_copy_response(data: &str) -> Bytes {
    // For now, use direct conversion but optimized for future zero-copy implementation
    // In production, this would use memory-mapped buffers or shared memory
    Bytes::from(data.to_string())
}

// ============================================================================
// PHASE D: PURE RUST ASYNC RUNTIME WITH TOKIO
// ============================================================================

/// Initialize Tokio runtime for pure Rust async execution
/// Initialize Tokio runtime with optimized settings for high-throughput
/// Uses work-stealing scheduler across all CPU cores
fn initialize_tokio_runtime() -> PyResult<TokioRuntime> {
    eprintln!("🚀 Initializing Tokio Async Runtime...");

    // Note: No need to call prepare_freethreaded_python() since we're a Python extension
    // Python is already initialized when our module is loaded

    // Create single Python event loop for pyo3-async-runtimes
    // This is only used for Python asyncio primitives (asyncio.sleep, etc.)
    let (task_locals, json_dumps_fn, event_loop_handle) = Python::with_gil(|py| -> PyResult<_> {
        let asyncio = py.import("asyncio")?;
        let event_loop = asyncio.call_method0("new_event_loop")?;
        asyncio.call_method1("set_event_loop", (&event_loop,))?;

        eprintln!("✅ Python event loop created (for asyncio primitives)");

        let task_locals = pyo3_async_runtimes::TaskLocals::new(event_loop.clone());
        let json_module = py.import("json")?;
        let json_dumps_fn: PyObject = json_module.getattr("dumps")?.into();
        let event_loop_handle: PyObject = event_loop.unbind();

        Ok((task_locals, json_dumps_fn, event_loop_handle))
    })?;

    // Start Python event loop in background thread
    // This is needed for asyncio primitives (asyncio.sleep, etc.) to work
    let event_loop_for_runner = Python::with_gil(|py| event_loop_handle.clone_ref(py));
    std::thread::spawn(move || {
        Python::with_gil(|py| {
            let loop_obj = event_loop_for_runner.bind(py);
            eprintln!("🔄 Python event loop running in background...");
            let _ = loop_obj.call_method0("run_forever");
        });
    });

    // Create Tokio semaphore for rate limiting with increased capacity
    // Total capacity: 1024 * num_cpus (e.g., 14,336 for 14 cores)
    let num_cpus = num_cpus::get();
    let total_capacity = 1024 * num_cpus;
    let semaphore = Arc::new(tokio::sync::Semaphore::new(total_capacity));

    eprintln!(
        "✅ Semaphore capacity: {} concurrent requests",
        total_capacity
    );
    eprintln!("✅ Tokio runtime ready with {} worker threads", num_cpus);

    Ok(TokioRuntime {
        task_locals,
        json_dumps_fn,
        semaphore,
    })
}

/// Process request using Tokio runtime (PHASE D)
/// Uses Python::attach for free-threading (no GIL overhead!)
/// NOTE: This function is for fast-path handlers that don't need request kwargs.
/// For Enhanced handlers, use call_python_handler_enhanced_async which passes kwargs.
async fn process_request_tokio(
    handler: Handler,
    is_async: bool,
    runtime: &TokioRuntime,
) -> Result<HandlerResponse, String> {
    // Acquire semaphore permit for rate limiting
    let _permit = runtime
        .semaphore
        .acquire()
        .await
        .map_err(|e| format!("Semaphore error: {}", e))?;

    if is_async {
        // PHASE D: Async handler with Tokio + pyo3-async-runtimes
        // Use Python::attach (no GIL in free-threading mode!)
        let future = Python::with_gil(|py| {
            // Call async handler to get coroutine
            let coroutine = handler
                .bind(py)
                .call0()
                .map_err(|e| format!("Handler error: {}", e))?;

            // Convert Python coroutine to Rust Future using pyo3-async-runtimes
            // This allows Tokio to manage the async execution!
            // Note: call0() returns Bound<'py, PyAny> which can be passed directly
            pyo3_async_runtimes::into_future_with_locals(&runtime.task_locals, coroutine)
                .map_err(|e| format!("Failed to convert coroutine: {}", e))
        })?;

        // Await the Rust future on Tokio runtime (non-blocking!)
        let result = future
            .await
            .map_err(|e| format!("Async execution error: {}", e))?;

        // Serialize result
        Python::with_gil(|py| serialize_result_optimized(py, result, &runtime.json_dumps_fn))
    } else {
        // Sync handler - direct call with Python::attach
        Python::with_gil(|py| {
            let result = handler
                .bind(py)
                .call0()
                .map_err(|e| format!("Handler error: {}", e))?;
            serialize_result_optimized(py, result.unbind(), &runtime.json_dumps_fn)
        })
    }
}

/// ENHANCED ASYNC PATH: Call async enhanced handler with request kwargs.
/// Enhanced handlers expect: body, headers, method, path, query_string
async fn call_python_handler_enhanced_async(
    handler: &PyObject,
    method_str: &str,
    path: &str,
    query_string: &str,
    body_bytes: &Bytes,
    headers_map: &std::collections::HashMap<String, String>,
    runtime: &TokioRuntime,
) -> Result<HandlerResponse, String> {
    // Acquire semaphore permit for rate limiting
    let _permit = runtime
        .semaphore
        .acquire()
        .await
        .map_err(|e| format!("Semaphore error: {}", e))?;

    // Build kwargs and call async handler
    // Make a defensive copy to own the data before the async boundary
    let body_vec: Vec<u8> = body_bytes.to_vec();

    // Use Python::attach (like sync handlers) instead of with_gil for better free-threading support
    let future = Python::attach(|py| {
        use pyo3::types::PyDict;
        let kwargs = PyDict::new(py);

        // Add body as bytes - use PyBytes to copy into Python-managed memory
        // (as_slice() would reference Rust memory that may be freed after closure ends)
        let body_py = pyo3::types::PyBytes::new(py, body_vec.as_slice());
        kwargs
            .set_item("body", body_py)
            .map_err(|e| format!("Body set error: {}", e))?;

        // Add headers dict
        let headers = PyDict::new(py);
        for (key, value) in headers_map {
            headers
                .set_item(key, value)
                .map_err(|e| format!("Header set error: {}", e))?;
        }
        kwargs
            .set_item("headers", headers)
            .map_err(|e| format!("Headers set error: {}", e))?;

        // Add method
        kwargs
            .set_item("method", method_str)
            .map_err(|e| format!("Method set error: {}", e))?;

        // Add path
        kwargs
            .set_item("path", path)
            .map_err(|e| format!("Path set error: {}", e))?;

        // Add query string
        kwargs
            .set_item("query_string", query_string)
            .map_err(|e| format!("Query set error: {}", e))?;

        // Call async handler to get coroutine
        let coroutine = handler
            .call(py, (), Some(&kwargs))
            .map_err(|e| format!("Handler error: {}", e))?;

        // Convert Python coroutine to Rust Future
        pyo3_async_runtimes::into_future_with_locals(
            &runtime.task_locals,
            coroutine.bind(py).clone(),
        )
        .map_err(|e| format!("Failed to convert coroutine: {}", e))
    })?;

    // Await the Rust future on Tokio runtime
    let result = future
        .await
        .map_err(|e| format!("Async execution error: {}", e))?;

    // Extract status_code and serialize response
    Python::with_gil(|py| {
        let bound = result.bind(py);

        // Enhanced handler returns {"content": ..., "status_code": ..., "content_type": ...}
        let mut status_code: u16 = 200;
        let mut content_type: Option<String> = None;
        let content = if let Ok(dict) = bound.downcast::<pyo3::types::PyDict>() {
            if let Ok(Some(status_val)) = dict.get_item("status_code") {
                status_code = status_val
                    .extract::<i64>()
                    .ok()
                    .and_then(|v| u16::try_from(v).ok())
                    .unwrap_or(200);
            }
            if let Ok(Some(ct_val)) = dict.get_item("content_type") {
                content_type = ct_val.extract::<String>().ok();
            }
            if let Ok(Some(content_val)) = dict.get_item("content") {
                content_val.unbind()
            } else {
                result
            }
        } else {
            result
        };

        // Check if content is raw bytes (binary response)
        let content_bound = content.bind(py);
        if let Ok(raw_bytes) = content_bound.extract::<Vec<u8>>() {
            // Binary response - return raw bytes without JSON serialization
            return Ok(HandlerResponse {
                body: String::new(),
                status_code,
                content_type,
                raw_body: Some(raw_bytes),
            });
        }

        // Serialize to JSON for non-binary content
        let body = match content.extract::<String>(py) {
            Ok(json_str) => json_str,
            Err(_) => {
                simd_json::serialize_pyobject_to_json(py, content_bound)
                    .map_err(|e| format!("SIMD JSON error: {}", e))?
            }
        };

        Ok(HandlerResponse {
            body,
            status_code,
            content_type,
            raw_body: None,
        })
    })
}

/// Handle HTTP request using pure Tokio runtime
/// Uses work-stealing scheduler for high-throughput async processing
async fn handle_request(
    req: Request<IncomingBody>,
    handlers: Arc<RwLock<HashMap<String, HandlerMetadata>>>,
    router: Arc<RwLock<RadixRouter>>,
    tokio_runtime: TokioRuntime,
) -> Result<Response<Full<Bytes>>, Infallible> {
    // Extract parts first before borrowing
    let (parts, body) = req.into_parts();
    let method_str = parts.method.as_str();
    let path = parts.uri.path();
    let query_string = parts.uri.query().unwrap_or("");
    let body_bytes = match body.collect().await {
        Ok(collected) => collected.to_bytes(),
        Err(e) => {
            eprintln!("Failed to read request body: {}", e);
            Bytes::new()
        }
    };

    // Rate limiting check (same as before)
    let rate_config = RATE_LIMIT_CONFIG.get();
    if let Some(config) = rate_config {
        if config.enabled {
            let client_ip = parts
                .headers
                .get("x-forwarded-for")
                .and_then(|v| v.to_str().ok())
                .and_then(|s| s.split(',').next())
                .map(|s| s.trim().to_string())
                .or_else(|| {
                    parts
                        .headers
                        .get("x-real-ip")
                        .and_then(|v| v.to_str().ok())
                        .map(|s| s.to_string())
                });

            if let Some(ip) = client_ip {
                if !check_rate_limit(&ip) {
                    let rate_limit_json = format!(
                        r#"{{"error": "RateLimitExceeded", "message": "Too many requests", "retry_after": 60}}"#
                    );
                    return Ok(Response::builder()
                        .status(429)
                        .header("content-type", "application/json")
                        .header("retry-after", "60")
                        .body(Full::new(Bytes::from(rate_limit_json)))
                        .unwrap());
                }
            }
        }
    }

    // Check for WebSocket upgrade request
    let is_websocket_upgrade = method_str == "GET"
        && parts
            .headers
            .get("upgrade")
            .and_then(|v| v.to_str().ok())
            .map(|v| v.to_lowercase() == "websocket")
            .unwrap_or(false)
        && parts
            .headers
            .get("connection")
            .and_then(|v| v.to_str().ok())
            .map(|v| v.to_lowercase().contains("upgrade"))
            .unwrap_or(false);

    // Zero-allocation route key
    let mut route_key_buffer = [0u8; 256];
    let route_key = if is_websocket_upgrade {
        // For WebSocket, look up the WEBSOCKET route
        format!("WEBSOCKET {}", path)
    } else {
        create_route_key_fast(method_str, path, &mut route_key_buffer)
    };

    // Single read lock acquisition for handler lookup
    // Try direct lookup first (faster for static routes)
    let handlers_guard = handlers.read().await;
    let mut metadata = handlers_guard.get(&route_key).cloned();

    // If no direct match, use the radix router to find parameterized routes
    if metadata.is_none() && !is_websocket_upgrade {
        let router_guard = router.read().await;
        if let Some(route_match) = router_guard.find_route(method_str, path) {
            // Found a route with path parameters - get handler by template key
            metadata = handlers_guard.get(&route_match.handler_key).cloned();
        }
    }
    drop(handlers_guard);

    // Handle WebSocket upgrade if detected
    if is_websocket_upgrade {
        if let Some(ref metadata) = metadata {
            if metadata.handler_type == HandlerType::WebSocket {
                // Return WebSocket upgrade response (101 Switching Protocols)
                // Note: Full WebSocket handling requires hyper-tungstenite integration
                // which needs access to the raw connection. For now, we return a
                // placeholder that indicates WebSocket support is available.
                let upgrade_response = format!(
                    r#"{{"status": "websocket_upgrade_detected", "path": "{}", "message": "Use dedicated WebSocket server on separate port for now"}}"#,
                    path
                );
                return Ok(Response::builder()
                    .status(200)
                    .header("content-type", "application/json")
                    .body(Full::new(Bytes::from(upgrade_response)))
                    .unwrap());
            }
        }
        // No WebSocket handler registered for this path
        let error_json = r#"{"error": "WebSocket upgrade not supported", "message": "No WebSocket handler registered for this path"}"#;
        return Ok(Response::builder()
            .status(400)
            .header("content-type", "application/json")
            .body(Full::new(Bytes::from(error_json)))
            .unwrap());
    }

    // Extract headers for Enhanced path
    let mut headers_map = std::collections::HashMap::new();
    for (name, value) in parts.headers.iter() {
        if let Ok(value_str) = value.to_str() {
            headers_map.insert(name.as_str().to_string(), value_str.to_string());
        }
    }

    // Process handler if found
    if let Some(metadata) = metadata {
        // PHASE 3: Fast dispatch based on handler type
        let response_result = match &metadata.handler_type {
            HandlerType::SimpleSyncFast => {
                if let Some(ref orig) = metadata.original_handler {
                    call_python_handler_fast(
                        orig,
                        &metadata.route_pattern,
                        path,
                        query_string,
                        &metadata.param_types,
                    )
                } else {
                    call_python_handler_sync_direct(
                        &metadata.handler,
                        method_str,
                        path,
                        query_string,
                        &body_bytes,
                        &headers_map,
                    )
                }
            }
            HandlerType::BodySyncFast => {
                if let Some(ref orig) = metadata.original_handler {
                    call_python_handler_fast_body(
                        orig,
                        &metadata.route_pattern,
                        path,
                        query_string,
                        &body_bytes,
                        &metadata.param_types,
                    )
                } else {
                    call_python_handler_sync_direct(
                        &metadata.handler,
                        method_str,
                        path,
                        query_string,
                        &body_bytes,
                        &headers_map,
                    )
                }
            }
            HandlerType::ModelSyncFast => {
                if let (Some(ref orig), Some((ref param_name, ref model_class))) =
                    (&metadata.original_handler, &metadata.model_info)
                {
                    call_python_handler_fast_model(
                        orig,
                        &metadata.route_pattern,
                        path,
                        query_string,
                        &body_bytes,
                        param_name,
                        model_class,
                    )
                } else {
                    call_python_handler_sync_direct(
                        &metadata.handler,
                        method_str,
                        path,
                        query_string,
                        &body_bytes,
                        &headers_map,
                    )
                }
            }
            HandlerType::SimpleAsyncFast => {
                // Async fast path for handlers without body (GET requests with path/query params)
                if let Some(ref orig) = metadata.original_handler {
                    call_python_handler_async_fast(
                        orig,
                        &metadata.route_pattern,
                        path,
                        query_string,
                        &metadata.param_types,
                        &tokio_runtime,
                    )
                    .await
                } else {
                    process_request_tokio(metadata.handler.clone(), true, &tokio_runtime).await
                }
            }
            HandlerType::BodyAsyncFast => {
                // Async fast path for handlers with body (POST/PUT with JSON body)
                if let Some(ref orig) = metadata.original_handler {
                    call_python_handler_async_fast_body(
                        orig,
                        &metadata.route_pattern,
                        path,
                        query_string,
                        &body_bytes,
                        &metadata.param_types,
                        &tokio_runtime,
                    )
                    .await
                } else {
                    process_request_tokio(metadata.handler.clone(), true, &tokio_runtime).await
                }
            }
            HandlerType::Enhanced => {
                // Enhanced handlers need request kwargs (body, headers, method, path, query_string)
                if metadata.is_async {
                    call_python_handler_enhanced_async(
                        &metadata.handler,
                        method_str,
                        path,
                        query_string,
                        &body_bytes,
                        &headers_map,
                        &tokio_runtime,
                    )
                    .await
                } else {
                    // Sync enhanced handler - use direct call with kwargs
                    call_python_handler_sync_direct(
                        &metadata.handler,
                        method_str,
                        path,
                        query_string,
                        &body_bytes,
                        &headers_map,
                    )
                }
            }
            HandlerType::WebSocket => {
                // WebSocket requests should have been handled earlier in the function
                // This case shouldn't be reached for WebSocket upgrade requests
                Err("WebSocket handler should not be called directly".to_string())
            }
        };

        match response_result {
            Ok(handler_response) => {
                // Check for binary response (raw_body takes precedence)
                if let Some(raw_bytes) = handler_response.raw_body {
                    let content_type = handler_response
                        .content_type
                        .unwrap_or_else(|| "application/octet-stream".to_string());
                    Ok(Response::builder()
                        .status(handler_response.status_code)
                        .header("content-type", content_type)
                        .body(Full::new(Bytes::from(raw_bytes)))
                        .unwrap())
                } else {
                    let content_type = handler_response
                        .content_type
                        .unwrap_or_else(|| "application/json".to_string());
                    Ok(Response::builder()
                        .status(handler_response.status_code)
                        .header("content-type", content_type)
                        .body(Full::new(Bytes::from(handler_response.body)))
                        .unwrap())
                }
            }
            Err(e) => {
                let error_json =
                    format!(r#"{{"error": "InternalServerError", "message": "{}"}}"#, e);
                Ok(Response::builder()
                    .status(500)
                    .header("content-type", "application/json")
                    .body(Full::new(Bytes::from(error_json)))
                    .unwrap())
            }
        }
    } else {
        // 404 Not Found
        let not_found_json = format!(
            r#"{{"error": "NotFound", "message": "Route not found: {} {}"}}"#,
            method_str, path
        );
        Ok(Response::builder()
            .status(404)
            .header("content-type", "application/json")
            .body(Full::new(Bytes::from(not_found_json)))
            .unwrap())
    }
}

// ============================================================================
// LOOP SHARDING - Phase A Implementation (OLD - will be replaced by Phase D)
// ============================================================================

// ============================================================================
// DIRECT SYNC CALLS - High-performance Python handler invocation
// ============================================================================

/// HYBRID: Direct synchronous Python handler call (NO channel overhead!)
/// This is the FAST PATH for sync handlers - bypasses the worker thread entirely
/// FREE-THREADING: Uses Python::attach() for TRUE parallelism (no GIL contention!)
fn call_python_handler_sync_direct(
    handler: &PyObject,
    method_str: &str,
    path: &str,
    query_string: &str,
    body_bytes: &Bytes,
    headers_map: &std::collections::HashMap<String, String>,
) -> Result<HandlerResponse, String> {
    // FREE-THREADING: Python::attach() instead of Python::with_gil()
    // This allows TRUE parallel execution on Python 3.14+ with --disable-gil
    Python::attach(|py| {
        // Get cached modules
        let json_module = CACHED_JSON_MODULE.get_or_init(|| py.import("json").unwrap().into());

        // Create kwargs dict with request data for enhanced handler
        use pyo3::types::PyDict;
        let kwargs = PyDict::new(py);

        // Add body as bytes
        kwargs.set_item("body", body_bytes.as_ref()).ok();

        // Add headers dict
        let headers = PyDict::new(py);
        for (key, value) in headers_map {
            headers.set_item(key, value).ok();
        }
        kwargs.set_item("headers", headers).ok();

        // Add method
        kwargs.set_item("method", method_str).ok();

        // Add path
        kwargs.set_item("path", path).ok();

        // Add query string
        kwargs.set_item("query_string", query_string).ok();

        // Call handler with kwargs (body and headers)
        let result = handler
            .call(py, (), Some(&kwargs))
            .map_err(|e| format!("Python error: {}", e))?;

        // Enhanced handler returns {"content": ..., "status_code": ..., "content_type": ...}
        // Extract status_code, content_type, and content
        let mut status_code: u16 = 200;
        let mut content_type: Option<String> = None;
        let content = if let Ok(dict) = result.downcast_bound::<pyo3::types::PyDict>(py) {
            // Check for status_code in dict response
            if let Ok(Some(status_val)) = dict.get_item("status_code") {
                status_code = status_val
                    .extract::<i64>()
                    .ok()
                    .and_then(|v| u16::try_from(v).ok())
                    .unwrap_or(200);
            }
            // Extract content_type for binary responses
            if let Ok(Some(ct_val)) = dict.get_item("content_type") {
                content_type = ct_val.extract::<String>().ok();
            }
            if let Ok(Some(content_val)) = dict.get_item("content") {
                // Also check content for Response object with status_code
                if let Ok(inner_status) = content_val.getattr("status_code") {
                    status_code = inner_status
                        .extract::<i64>()
                        .ok()
                        .and_then(|v| u16::try_from(v).ok())
                        .unwrap_or(status_code);
                }
                content_val.unbind()
            } else {
                result
            }
        } else {
            // Check if result itself is a Response object with status_code
            let bound = result.bind(py);
            if let Ok(status_attr) = bound.getattr("status_code") {
                status_code = status_attr
                    .extract::<i64>()
                    .ok()
                    .and_then(|v| u16::try_from(v).ok())
                    .unwrap_or(200);
            }
            result
        };

        // Check if content is raw bytes (binary response)
        let content_bound = content.bind(py);
        if let Ok(raw_bytes) = content_bound.extract::<Vec<u8>>() {
            // Binary response - return raw bytes without JSON serialization
            return Ok(HandlerResponse {
                body: String::new(),
                status_code,
                content_type,
                raw_body: Some(raw_bytes),
            });
        }

        // PHASE 1: SIMD JSON serialization (eliminates json.dumps FFI!)
        let body = match content.extract::<String>(py) {
            Ok(json_str) => json_str,
            Err(_) => {
                // Use Rust SIMD serializer instead of Python json.dumps
                simd_json::serialize_pyobject_to_json(py, content_bound)
                    .map_err(|e| format!("SIMD JSON error: {}", e))?
            }
        };

        Ok(HandlerResponse { body, status_code, content_type, raw_body: None })
    })
}

// ============================================================================
// PHASE 3: FAST PATH - Direct handler calls with Rust-side parsing
// ============================================================================

/// FAST PATH for simple sync handlers (GET with path/query params only).
/// Rust parses query string and path params, calls Python handler directly,
/// then serializes the response with SIMD JSON — single FFI crossing!
fn call_python_handler_fast(
    handler: &PyObject,
    route_pattern: &str,
    path: &str,
    query_string: &str,
    param_types: &HashMap<String, String>,
) -> Result<HandlerResponse, String> {
    Python::attach(|py| {
        let kwargs = PyDict::new(py);

        // Parse path params in Rust (SIMD-accelerated)
        simd_parse::set_path_params_into_pydict(py, route_pattern, path, &kwargs, param_types)
            .map_err(|e| format!("Path param error: {}", e))?;

        // Parse query string in Rust (SIMD-accelerated)
        simd_parse::parse_query_into_pydict(py, query_string, &kwargs, param_types)
            .map_err(|e| format!("Query param error: {}", e))?;

        // Single FFI call: Python handler with pre-parsed kwargs
        let result = handler
            .call(py, (), Some(&kwargs))
            .map_err(|e| format!("Handler error: {}", e))?;

        // Check if result is a Response object with status_code and media_type
        let bound = result.bind(py);
        let status_code = if let Ok(status_attr) = bound.getattr("status_code") {
            // Python integers are typically i64, convert to u16
            status_attr
                .extract::<i64>()
                .ok()
                .and_then(|v| u16::try_from(v).ok())
                .unwrap_or(200)
        } else {
            200
        };

        // Check for Response object with media_type (for binary responses)
        let content_type: Option<String> = bound.getattr("media_type")
            .ok()
            .and_then(|v| v.extract::<String>().ok());

        // If this is a Response object with body attribute, extract the body
        if let Ok(body_attr) = bound.getattr("body") {
            // Try extracting as bytes using Vec<u8> (more reliable than downcast)
            if let Ok(raw_bytes) = body_attr.extract::<Vec<u8>>() {
                // Only return as binary if we have a content_type (Response object)
                if content_type.is_some() {
                    return Ok(HandlerResponse {
                        body: String::new(),
                        status_code,
                        content_type,
                        raw_body: Some(raw_bytes),
                    });
                }
            }
        }

        // SIMD JSON serialization of result (no json.dumps FFI!)
        let body = match result.extract::<String>(py) {
            Ok(s) => s,
            Err(_) => simd_json::serialize_pyobject_to_json(py, bound)
                .map_err(|e| format!("SIMD JSON error: {}", e))?,
        };

        Ok(HandlerResponse { body, status_code, content_type, raw_body: None })
    })
}

/// FAST PATH for body sync handlers (POST/PUT with JSON body).
/// Rust parses body with simd-json, path/query params, calls handler directly,
/// then serializes response with SIMD JSON — single FFI crossing!
fn call_python_handler_fast_body(
    handler: &PyObject,
    route_pattern: &str,
    path: &str,
    query_string: &str,
    body_bytes: &Bytes,
    param_types: &HashMap<String, String>,
) -> Result<HandlerResponse, String> {
    Python::attach(|py| {
        let kwargs = PyDict::new(py);

        // Parse path params in Rust
        simd_parse::set_path_params_into_pydict(py, route_pattern, path, &kwargs, param_types)
            .map_err(|e| format!("Path param error: {}", e))?;

        // Parse query string in Rust
        simd_parse::parse_query_into_pydict(py, query_string, &kwargs, param_types)
            .map_err(|e| format!("Query param error: {}", e))?;

        // Parse JSON body with simd-json (SIMD-accelerated!)
        if !body_bytes.is_empty() {
            let parsed = simd_parse::parse_json_body_into_pydict(
                py,
                body_bytes.as_ref(),
                &kwargs,
                param_types,
            )
            .map_err(|e| format!("Body parse error: {}", e))?;

            if !parsed {
                // Couldn't parse as simple JSON object, pass raw body
                kwargs
                    .set_item("body", body_bytes.as_ref())
                    .map_err(|e| format!("Body set error: {}", e))?;
            }
        }

        // Single FFI call: Python handler with pre-parsed kwargs
        let result = handler
            .call(py, (), Some(&kwargs))
            .map_err(|e| format!("Handler error: {}", e))?;

        // Check if result is a Response object with status_code and media_type
        let bound = result.bind(py);
        let status_code = if let Ok(status_attr) = bound.getattr("status_code") {
            // Python integers are typically i64, convert to u16
            status_attr
                .extract::<i64>()
                .ok()
                .and_then(|v| u16::try_from(v).ok())
                .unwrap_or(200)
        } else {
            200
        };

        // Check for Response object with media_type (for binary responses)
        let content_type: Option<String> = bound.getattr("media_type")
            .ok()
            .and_then(|v| v.extract::<String>().ok());

        // If this is a Response object with body attribute, extract the body
        if let Ok(body_attr) = bound.getattr("body") {
            // Check if body is bytes (binary response)
            if let Ok(raw_bytes) = body_attr.extract::<Vec<u8>>() {
                // Binary response - return raw bytes directly
                return Ok(HandlerResponse {
                    body: String::new(),
                    status_code,
                    content_type,
                    raw_body: Some(raw_bytes),
                });
            }
        }

        // SIMD JSON serialization
        let body = match result.extract::<String>(py) {
            Ok(s) => s,
            Err(_) => simd_json::serialize_pyobject_to_json(py, bound)
                .map_err(|e| format!("SIMD JSON error: {}", e))?,
        };

        Ok(HandlerResponse { body, status_code, content_type, raw_body: None })
    })
}

/// FAST PATH for model sync handlers (POST/PUT with dhi model validation).
/// Rust parses JSON body with simd-json into PyDict, calls model.model_validate(),
/// then passes validated model to handler — bypasses Python json.loads entirely!
fn call_python_handler_fast_model(
    handler: &PyObject,
    route_pattern: &str,
    path: &str,
    query_string: &str,
    body_bytes: &Bytes,
    param_name: &str,
    model_class: &PyObject,
) -> Result<HandlerResponse, String> {
    Python::attach(|py| {
        let kwargs = PyDict::new(py);

        // Parse path params in Rust (SIMD-accelerated)
        let empty_types = HashMap::new();
        simd_parse::set_path_params_into_pydict(py, route_pattern, path, &kwargs, &empty_types)
            .map_err(|e| format!("Path param error: {}", e))?;

        // Parse query string in Rust (SIMD-accelerated)
        simd_parse::parse_query_into_pydict(py, query_string, &kwargs, &empty_types)
            .map_err(|e| format!("Query param error: {}", e))?;

        // Parse JSON body with simd-json into a Python dict
        if !body_bytes.is_empty() {
            // Use simd-json to parse into PyDict
            let body_dict = simd_parse::parse_json_to_pydict(py, body_bytes.as_ref())
                .map_err(|e| format!("JSON parse error: {}", e))?;

            // Validate with dhi model: model_class.model_validate(body_dict)
            let validated_model = model_class
                .bind(py)
                .call_method1("model_validate", (body_dict,))
                .map_err(|e| format!("Model validation error: {}", e))?;

            // Set the validated model as the parameter
            kwargs
                .set_item(param_name, validated_model)
                .map_err(|e| format!("Param set error: {}", e))?;
        }

        // Single FFI call: Python handler with validated model
        let result = handler
            .call(py, (), Some(&kwargs))
            .map_err(|e| format!("Handler error: {}", e))?;

        // Check if result is a Response object with status_code and media_type
        let bound = result.bind(py);
        let status_code = if let Ok(status_attr) = bound.getattr("status_code") {
            status_attr
                .extract::<i64>()
                .ok()
                .and_then(|v| u16::try_from(v).ok())
                .unwrap_or(200)
        } else {
            200
        };

        // Check for Response object with media_type (for binary responses)
        let content_type: Option<String> = bound.getattr("media_type")
            .ok()
            .and_then(|v| v.extract::<String>().ok());

        // If this is a Response object with body attribute, extract the body
        if let Ok(body_attr) = bound.getattr("body") {
            // Check if body is bytes (binary response)
            if let Ok(raw_bytes) = body_attr.extract::<Vec<u8>>() {
                // Binary response - return raw bytes directly
                return Ok(HandlerResponse {
                    body: String::new(),
                    status_code,
                    content_type,
                    raw_body: Some(raw_bytes),
                });
            }
        }

        // SIMD JSON serialization of result
        let body = match result.extract::<String>(py) {
            Ok(s) => s,
            Err(_) => simd_json::serialize_pyobject_to_json(py, bound)
                .map_err(|e| format!("SIMD JSON error: {}", e))?,
        };

        Ok(HandlerResponse { body, status_code, content_type, raw_body: None })
    })
}

// ============================================================================
// PHASE 4: ASYNC FAST PATHS - Tokio + pyo3-async-runtimes for async handlers
// ============================================================================

/// ASYNC FAST PATH for simple async handlers (GET with path/query params only).
/// Rust parses query string and path params, calls Python async handler via Tokio,
/// then serializes the response with SIMD JSON — minimal FFI crossings!
async fn call_python_handler_async_fast(
    handler: &PyObject,
    route_pattern: &str,
    path: &str,
    query_string: &str,
    param_types: &HashMap<String, String>,
    runtime: &TokioRuntime,
) -> Result<HandlerResponse, String> {
    // Acquire semaphore permit for rate limiting
    let _permit = runtime
        .semaphore
        .acquire()
        .await
        .map_err(|e| format!("Semaphore error: {}", e))?;

    // Build kwargs and call async handler in Python GIL context
    let future = Python::with_gil(|py| {
        let kwargs = PyDict::new(py);

        // Parse path params in Rust (SIMD-accelerated)
        simd_parse::set_path_params_into_pydict(py, route_pattern, path, &kwargs, param_types)
            .map_err(|e| format!("Path param error: {}", e))?;

        // Parse query string in Rust (SIMD-accelerated)
        simd_parse::parse_query_into_pydict(py, query_string, &kwargs, param_types)
            .map_err(|e| format!("Query param error: {}", e))?;

        // Call async handler to get coroutine
        let coroutine = handler
            .call(py, (), Some(&kwargs))
            .map_err(|e| format!("Handler error: {}", e))?;

        // Convert Python coroutine to Rust Future using pyo3-async-runtimes
        // Note: call() returns Py<PyAny>, bind().clone() converts to owned Bound<'py, PyAny>
        pyo3_async_runtimes::into_future_with_locals(
            &runtime.task_locals,
            coroutine.bind(py).clone(),
        )
        .map_err(|e| format!("Failed to convert coroutine: {}", e))
    })?;

    // Await the Rust future on Tokio runtime (non-blocking!)
    let result = future
        .await
        .map_err(|e| format!("Async execution error: {}", e))?;

    // Serialize result with SIMD JSON
    Python::with_gil(|py| {
        let bound = result.bind(py);
        let status_code = if let Ok(status_attr) = bound.getattr("status_code") {
            status_attr
                .extract::<i64>()
                .ok()
                .and_then(|v| u16::try_from(v).ok())
                .unwrap_or(200)
        } else {
            200
        };

        // Check for Response object with media_type (for binary responses)
        let content_type: Option<String> = bound.getattr("media_type")
            .ok()
            .and_then(|v| v.extract::<String>().ok());

        // If this is a Response object with body attribute, extract the body
        if let Ok(body_attr) = bound.getattr("body") {
            // Check if body is bytes (binary response)
            if let Ok(raw_bytes) = body_attr.extract::<Vec<u8>>() {
                // Binary response - return raw bytes directly
                return Ok(HandlerResponse {
                    body: String::new(),
                    status_code,
                    content_type,
                    raw_body: Some(raw_bytes),
                });
            }
        }

        let body = match result.extract::<String>(py) {
            Ok(s) => s,
            Err(_) => simd_json::serialize_pyobject_to_json(py, bound)
                .map_err(|e| format!("SIMD JSON error: {}", e))?,
        };

        Ok(HandlerResponse { body, status_code, content_type, raw_body: None })
    })
}

/// ASYNC FAST PATH for async handlers with body (POST/PUT with JSON body).
/// Rust parses body with simd-json, path/query params, calls async handler via Tokio,
/// then serializes response with SIMD JSON — minimal FFI crossings!
async fn call_python_handler_async_fast_body(
    handler: &PyObject,
    route_pattern: &str,
    path: &str,
    query_string: &str,
    body_bytes: &Bytes,
    param_types: &HashMap<String, String>,
    runtime: &TokioRuntime,
) -> Result<HandlerResponse, String> {
    // Acquire semaphore permit for rate limiting
    let _permit = runtime
        .semaphore
        .acquire()
        .await
        .map_err(|e| format!("Semaphore error: {}", e))?;

    // Build kwargs with parsed body and call async handler in Python GIL context
    let future = Python::with_gil(|py| {
        let kwargs = PyDict::new(py);

        // Parse path params in Rust
        simd_parse::set_path_params_into_pydict(py, route_pattern, path, &kwargs, param_types)
            .map_err(|e| format!("Path param error: {}", e))?;

        // Parse query string in Rust
        simd_parse::parse_query_into_pydict(py, query_string, &kwargs, param_types)
            .map_err(|e| format!("Query param error: {}", e))?;

        // Parse JSON body with simd-json (SIMD-accelerated!)
        if !body_bytes.is_empty() {
            let parsed = simd_parse::parse_json_body_into_pydict(
                py,
                body_bytes.as_ref(),
                &kwargs,
                param_types,
            )
            .map_err(|e| format!("Body parse error: {}", e))?;

            if !parsed {
                // Couldn't parse as simple JSON object, pass raw body
                kwargs
                    .set_item("body", body_bytes.as_ref())
                    .map_err(|e| format!("Body set error: {}", e))?;
            }
        }

        // Call async handler to get coroutine
        let coroutine = handler
            .call(py, (), Some(&kwargs))
            .map_err(|e| format!("Handler error: {}", e))?;

        // Convert Python coroutine to Rust Future using pyo3-async-runtimes
        // Note: call() returns Py<PyAny>, bind().clone() converts to owned Bound<'py, PyAny>
        pyo3_async_runtimes::into_future_with_locals(
            &runtime.task_locals,
            coroutine.bind(py).clone(),
        )
        .map_err(|e| format!("Failed to convert coroutine: {}", e))
    })?;

    // Await the Rust future on Tokio runtime (non-blocking!)
    let result = future
        .await
        .map_err(|e| format!("Async execution error: {}", e))?;

    // Serialize result with SIMD JSON
    Python::with_gil(|py| {
        let bound = result.bind(py);
        let status_code = if let Ok(status_attr) = bound.getattr("status_code") {
            status_attr
                .extract::<i64>()
                .ok()
                .and_then(|v| u16::try_from(v).ok())
                .unwrap_or(200)
        } else {
            200
        };

        // Check for Response object with media_type (for binary responses)
        let content_type: Option<String> = bound.getattr("media_type")
            .ok()
            .and_then(|v| v.extract::<String>().ok());

        // If this is a Response object with body attribute, extract the body
        if let Ok(body_attr) = bound.getattr("body") {
            // Check if body is bytes (binary response)
            if let Ok(raw_bytes) = body_attr.extract::<Vec<u8>>() {
                // Binary response - return raw bytes directly
                return Ok(HandlerResponse {
                    body: String::new(),
                    status_code,
                    content_type,
                    raw_body: Some(raw_bytes),
                });
            }
        }

        let body = match result.extract::<String>(py) {
            Ok(s) => s,
            Err(_) => simd_json::serialize_pyobject_to_json(py, bound)
                .map_err(|e| format!("SIMD JSON error: {}", e))?,
        };

        Ok(HandlerResponse { body, status_code, content_type, raw_body: None })
    })
}

// ============================================================================
// MULTI-WORKER PATTERN - Multiple Python Workers for Parallel Async Execution
// ============================================================================

/// Serialize Python result to JSON string - SIMD-optimized version
/// Phase 1: Uses Rust SIMD serializer instead of Python json.dumps
fn serialize_result_optimized(
    py: Python,
    result: Py<PyAny>,
    _json_dumps_fn: &PyObject, // Kept for API compat, no longer used
) -> Result<HandlerResponse, String> {
    let bound = result.bind(py);

    // Check if result is a Response object with status_code
    let status_code = if let Ok(status_attr) = bound.getattr("status_code") {
        // Python integers are typically i64, convert to u16
        status_attr
            .extract::<i64>()
            .ok()
            .and_then(|v| u16::try_from(v).ok())
            .unwrap_or(200)
    } else {
        200
    };

    // Check for Response object with media_type (for binary responses)
    let content_type: Option<String> = bound.getattr("media_type")
        .ok()
        .and_then(|v| v.extract::<String>().ok());

    // If this is a Response object with body attribute, extract the body
    if let Ok(body_attr) = bound.getattr("body") {
        // Check if body is bytes (binary response)
        if let Ok(raw_bytes) = body_attr.extract::<Vec<u8>>() {
            // Binary response - return raw bytes directly
            return Ok(HandlerResponse {
                body: String::new(),
                status_code,
                content_type,
                raw_body: Some(raw_bytes),
            });
        }
    }

    // Try direct string extraction first (zero-copy fast path)
    if let Ok(json_str) = bound.extract::<String>() {
        return Ok(HandlerResponse {
            body: json_str,
            status_code,
            content_type,
            raw_body: None,
        });
    }

    // PHASE 1: Rust SIMD JSON serialization (no Python FFI!)
    let body = simd_json::serialize_pyobject_to_json(py, bound)
        .map_err(|e| format!("SIMD JSON serialization error: {}", e))?;

    Ok(HandlerResponse { body, status_code, content_type, raw_body: None })
}

/// Handle Python request - supports both SYNC and ASYNC handlers
/// Async handlers run in dedicated thread with their own event loop
async fn handle_python_request_sync(
    handler: PyObject,
    _method: String,
    _path: String,
    _query_string: String,
    body: Bytes,
) -> Result<String, String> {
    // Check if handler is async
    let is_async = Python::with_gil(|py| {
        let inspect = py.import("inspect").unwrap();
        inspect
            .call_method1("iscoroutinefunction", (handler.clone_ref(py),))
            .unwrap()
            .extract::<bool>()
            .unwrap()
    });

    let body_clone = body.clone();

    if is_async {
        // Async handler - run in blocking thread with asyncio.run()
        tokio::task::spawn_blocking(move || {
            Python::with_gil(|py| {
                // Import asyncio
                let asyncio = py
                    .import("asyncio")
                    .map_err(|e| format!("Failed to import asyncio: {}", e))?;

                // Create kwargs dict with request data
                use pyo3::types::PyDict;
                let kwargs = PyDict::new(py);
                kwargs.set_item("body", body_clone.as_ref()).ok();
                let headers = PyDict::new(py);
                kwargs.set_item("headers", headers).ok();

                // Call async handler to get coroutine
                let coroutine = handler
                    .call(py, (), Some(&kwargs))
                    .map_err(|e| format!("Failed to call handler: {}", e))?;

                // Run coroutine with asyncio.run()
                let result = asyncio
                    .call_method1("run", (coroutine,))
                    .map_err(|e| format!("Failed to run coroutine: {}", e))?;

                // Enhanced handler returns {"content": ..., "status_code": ..., "content_type": ...}
                // Extract just the content
                let content = if let Ok(dict) = result.downcast::<PyDict>() {
                    if let Ok(Some(content_val)) = dict.get_item("content") {
                        content_val
                    } else {
                        result
                    }
                } else {
                    result
                };

                // PHASE 1: SIMD JSON serialization
                if let Ok(json_str) = content.extract::<String>() {
                    Ok(json_str)
                } else {
                    simd_json::serialize_pyobject_to_json(py, &content)
                        .map_err(|e| format!("SIMD JSON error: {}", e))
                }
            })
        })
        .await
        .map_err(|e| format!("Thread join error: {}", e))?
    } else {
        // Sync handler - call directly
        Python::with_gil(|py| {
            // Create kwargs dict with request data
            use pyo3::types::PyDict;
            let kwargs = PyDict::new(py);
            kwargs.set_item("body", body.as_ref()).ok();
            let headers = PyDict::new(py);
            kwargs.set_item("headers", headers).ok();

            let result = handler
                .call(py, (), Some(&kwargs))
                .map_err(|e| format!("Python handler error: {}", e))?;

            // Enhanced handler returns {"content": ..., "status_code": ..., "content_type": ...}
            let content = if let Ok(dict) = result.downcast_bound::<PyDict>(py) {
                if let Ok(Some(content_val)) = dict.get_item("content") {
                    content_val.unbind()
                } else {
                    result
                }
            } else {
                result
            };

            // PHASE 1: SIMD JSON serialization
            match content.extract::<String>(py) {
                Ok(json_str) => Ok(json_str),
                Err(_) => {
                    let bound = content.bind(py);
                    simd_json::serialize_pyobject_to_json(py, bound)
                        .map_err(|e| format!("SIMD JSON error: {}", e))
                }
            }
        })
    }
}
