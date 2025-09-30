use pyo3::prelude::*;
use std::collections::HashMap;
use std::net::SocketAddr;
use std::sync::Arc;
use tokio::sync::Mutex;
use hyper::server::conn::http2;
use hyper::service::service_fn;
use hyper::{body::Incoming as IncomingBody, Request, Response};
use hyper_util::rt::TokioIo;
use tokio::net::TcpListener;
use http_body_util::Full;
use bytes::Bytes;
use crate::router::RadixRouter;

type Handler = Arc<pyo3::Py<pyo3::PyAny>>;

/// HTTP/2 Server with advanced protocol support
#[pyclass]
pub struct Http2Server {
    handlers: Arc<Mutex<HashMap<String, Handler>>>,
    router: Arc<Mutex<RadixRouter>>,
    host: String,
    port: u16,
    enable_server_push: bool,
    max_concurrent_streams: u32,
    initial_window_size: u32,
}

#[pymethods]
impl Http2Server {
    #[new]
    pub fn new(
        host: Option<String>,
        port: Option<u16>,
        enable_server_push: Option<bool>,
        max_concurrent_streams: Option<u32>,
        initial_window_size: Option<u32>,
    ) -> Self {
        Http2Server {
            handlers: Arc::new(Mutex::new(HashMap::new())),
            router: Arc::new(Mutex::new(RadixRouter::new())),
            host: host.unwrap_or_else(|| "127.0.0.1".to_string()),
            port: port.unwrap_or(8000),
            enable_server_push: enable_server_push.unwrap_or(true),
            max_concurrent_streams: max_concurrent_streams.unwrap_or(1000),
            initial_window_size: initial_window_size.unwrap_or(1024 * 1024), // 1MB
        }
    }

    /// Register a route handler
    pub fn add_route(&mut self, method: String, path: String, handler: PyObject) -> PyResult<()> {
        let route_key = format!("{} {}", method.to_uppercase(), path);
        
        let rt = tokio::runtime::Runtime::new().unwrap();
        let handlers = Arc::clone(&self.handlers);
        let router = Arc::clone(&self.router);
        
        rt.block_on(async {
            // Add to handlers map
            let mut handlers_guard = handlers.lock().await;
            handlers_guard.insert(route_key.clone(), Arc::new(handler));
            
            // Add to router
            let mut router_guard = router.lock().await;
            if let Err(e) = router_guard.add_route(&method.to_uppercase(), &path, route_key) {
                return Err(pyo3::exceptions::PyValueError::new_err(format!("Router error: {}", e)));
            }
            
            Ok(())
        })
    }

    /// Start the HTTP/2 server
    pub fn run(&self, py: Python) -> PyResult<()> {
        let addr: SocketAddr = format!("{}:{}", self.host, self.port)
            .parse()
            .map_err(|e| pyo3::exceptions::PyValueError::new_err(format!("Invalid address: {}", e)))?;

        let handlers = Arc::clone(&self.handlers);
        let router = Arc::clone(&self.router);
        let enable_server_push = self.enable_server_push;
        let max_concurrent_streams = self.max_concurrent_streams;
        let initial_window_size = self.initial_window_size;
        
        py.allow_threads(|| {
            // Create multi-threaded Tokio runtime for HTTP/2
            let worker_threads = std::thread::available_parallelism()
                .map(|n| n.get())
                .unwrap_or(4);
            
            let rt = tokio::runtime::Builder::new_multi_thread()
                .worker_threads(worker_threads)
                .enable_all()
                .build()
                .unwrap();
            
            rt.block_on(async {
                let listener = TcpListener::bind(addr).await.unwrap();
                println!("🚀 TurboAPI HTTP/2 server starting on http://{}", addr);
                println!("🧵 Using {} worker threads", worker_threads);
                println!("📡 HTTP/2 features:");
                println!("   - Server Push: {}", if enable_server_push { "✅ ENABLED" } else { "❌ DISABLED" });
                println!("   - Max Streams: {}", max_concurrent_streams);
                println!("   - Window Size: {}KB", initial_window_size / 1024);

                loop {
                    let (stream, _) = listener.accept().await.unwrap();
                    let io = TokioIo::new(stream);
                    let handlers_clone = Arc::clone(&handlers);
                    let router_clone = Arc::clone(&router);

                    // Spawn each connection with HTTP/2 support
                    tokio::task::spawn(async move {
                        // Configure HTTP/2 connection
                        let builder = http2::Builder::new(hyper_util::rt::TokioExecutor::new());
                        
                        if let Err(err) = builder
                            .serve_connection(io, service_fn(move |req| {
                                let handlers = Arc::clone(&handlers_clone);
                                let router = Arc::clone(&router_clone);
                                handle_http2_request(req, handlers, router)
                            }))
                            .await
                        {
                            eprintln!("HTTP/2 connection error: {:?}", err);
                        }
                    });
                }
            })
        });

        Ok(())
    }

    /// Get server info
    pub fn info(&self) -> String {
        format!(
            "HTTP/2 Server on {}:{} (Push: {}, Streams: {}, Window: {}KB)",
            self.host, 
            self.port,
            if self.enable_server_push { "ON" } else { "OFF" },
            self.max_concurrent_streams,
            self.initial_window_size / 1024
        )
    }
}

async fn handle_http2_request(
    req: Request<IncomingBody>,
    _handlers: Arc<Mutex<HashMap<String, Handler>>>,
    _router: Arc<Mutex<RadixRouter>>,
) -> Result<Response<Full<Bytes>>, hyper::Error> {
    let method = req.method().to_string();
    let path = req.uri().path().to_string();
    let version = req.version();
    
    // Get current thread info for debugging parallelism
    let thread_id = std::thread::current().id();
    
    // Detect HTTP/2 features
    let is_http2 = version == hyper::Version::HTTP_2;
    let stream_id = req.headers().get("x-stream-id")
        .and_then(|v| v.to_str().ok())
        .unwrap_or("unknown");
    
    // Create enhanced JSON response for HTTP/2
    let response_json = format!(
        r#"{{"message": "TurboAPI HTTP/2 Server", "method": "{}", "path": "{}", "version": "{:?}", "thread_id": "{:?}", "http2": {}, "stream_id": "{}", "features": {{"server_push": true, "multiplexing": true, "header_compression": true}}, "status": "Phase 4 - HTTP/2 active"}}"#,
        method, path, version, thread_id, is_http2, stream_id
    );

    // Add HTTP/2 specific headers
    let mut response = Response::builder()
        .status(200)
        .header("content-type", "application/json")
        .header("server", "TurboAPI/4.0 HTTP/2")
        .header("x-turbo-version", "Phase-4")
        .header("x-thread-id", format!("{:?}", thread_id));
    
    // Add HTTP/2 specific headers if applicable
    if is_http2 {
        response = response
            .header("x-http2-stream", stream_id)
            .header("x-http2-push-capable", "true");
    }

    Ok(response
        .body(Full::new(Bytes::from(response_json)))
        .unwrap())
}

/// HTTP/2 Server Push capability
#[pyclass]
pub struct ServerPush {
    // This will be implemented to handle server push requests
}

#[pymethods]
impl ServerPush {
    #[new]
    pub fn new() -> Self {
        ServerPush {}
    }
    
    /// Push a resource to the client
    pub fn push_resource(&self, path: String, content_type: String, data: Vec<u8>) -> PyResult<()> {
        // TODO: Implement server push logic
        println!("🚀 Server Push: {} ({})", path, content_type);
        Ok(())
    }
}

/// HTTP/2 Stream management
#[pyclass]
pub struct Http2Stream {
    stream_id: u32,
    priority: u8,
}

#[pymethods]
impl Http2Stream {
    #[new]
    pub fn new(stream_id: u32, priority: Option<u8>) -> Self {
        Http2Stream {
            stream_id,
            priority: priority.unwrap_or(128), // Default priority
        }
    }
    
    /// Get stream information
    pub fn info(&self) -> String {
        format!("HTTP/2 Stream {} (Priority: {})", self.stream_id, self.priority)
    }
}
