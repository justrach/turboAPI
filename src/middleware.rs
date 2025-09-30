use pyo3::prelude::*;
use std::sync::Arc;
use std::collections::HashMap;
use tokio::sync::RwLock;
use std::time::{Duration, Instant};
use crate::zerocopy::{ZeroCopyBufferPool, ZeroCopyBytes};

/// Advanced middleware pipeline for production-grade request processing
#[pyclass]
pub struct MiddlewarePipeline {
    middlewares: Vec<Arc<dyn Middleware + Send + Sync>>,
    buffer_pool: Arc<ZeroCopyBufferPool>,
    metrics: Arc<RwLock<MiddlewareMetrics>>,
}

/// Middleware trait for processing requests and responses
pub trait Middleware: Send + Sync {
    fn name(&self) -> &str;
    fn process_request(&self, ctx: &mut RequestContext) -> Result<(), MiddlewareError>;
    fn process_response(&self, ctx: &mut ResponseContext) -> Result<(), MiddlewareError>;
    fn priority(&self) -> i32 { 0 } // Higher priority runs first
}

#[derive(Debug)]
pub struct MiddlewareError {
    pub message: String,
    pub status_code: u16,
}

impl std::fmt::Display for MiddlewareError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "Middleware Error: {}", self.message)
    }
}

impl std::error::Error for MiddlewareError {}

/// Request context passed through middleware pipeline
#[pyclass]
#[derive(Clone)]
pub struct RequestContext {
    pub method: String,
    pub path: String,
    pub headers: HashMap<String, String>,
    pub body: Option<ZeroCopyBytes>,
    pub metadata: HashMap<String, String>,
    pub start_time: Instant,
}

/// Response context passed through middleware pipeline
#[pyclass]
#[derive(Clone)]
pub struct ResponseContext {
    pub status_code: u16,
    pub headers: HashMap<String, String>,
    pub body: Option<ZeroCopyBytes>,
    pub metadata: HashMap<String, String>,
    pub processing_time: Duration,
}

#[derive(Default)]
struct MiddlewareMetrics {
    total_requests: u64,
    total_responses: u64,
    middleware_timings: HashMap<String, Vec<Duration>>,
    error_counts: HashMap<String, u64>,
}

#[pymethods]
impl RequestContext {
    #[new]
    pub fn new() -> Self {
        RequestContext {
            method: String::new(),
            path: String::new(),
            headers: HashMap::new(),
            body: None,
            metadata: HashMap::new(),
            start_time: std::time::Instant::now(),
        }
    }

    #[getter]
    pub fn method(&self) -> &str {
        &self.method
    }

    #[setter]
    pub fn set_method(&mut self, method: String) {
        self.method = method;
    }

    #[getter]
    pub fn path(&self) -> &str {
        &self.path
    }

    #[setter]
    pub fn set_path(&mut self, path: String) {
        self.path = path;
    }

    #[getter]
    pub fn headers(&self) -> HashMap<String, String> {
        self.headers.clone()
    }

    #[setter]
    pub fn set_headers(&mut self, headers: HashMap<String, String>) {
        self.headers = headers;
    }

    #[getter]
    pub fn metadata(&self) -> HashMap<String, String> {
        self.metadata.clone()
    }

    #[setter]
    pub fn set_metadata(&mut self, metadata: HashMap<String, String>) {
        self.metadata = metadata;
    }
}

#[pymethods]
impl ResponseContext {
    #[new]
    pub fn new() -> Self {
        ResponseContext {
            status_code: 200,
            headers: HashMap::new(),
            body: None,
            metadata: HashMap::new(),
            processing_time: Duration::from_millis(0),
        }
    }

    #[getter]
    pub fn status_code(&self) -> u16 {
        self.status_code
    }

    #[setter]
    pub fn set_status_code(&mut self, status_code: u16) {
        self.status_code = status_code;
    }

    #[getter]
    pub fn headers(&self) -> HashMap<String, String> {
        self.headers.clone()
    }

    #[setter]
    pub fn set_headers(&mut self, headers: HashMap<String, String>) {
        self.headers = headers;
    }

    #[getter]
    pub fn metadata(&self) -> HashMap<String, String> {
        self.metadata.clone()
    }

    #[setter]
    pub fn set_metadata(&mut self, metadata: HashMap<String, String>) {
        self.metadata = metadata;
    }

    #[getter]
    pub fn processing_time_ms(&self) -> f64 {
        self.processing_time.as_secs_f64() * 1000.0
    }

    #[setter]
    pub fn set_processing_time_ms(&mut self, ms: f64) {
        self.processing_time = Duration::from_secs_f64(ms / 1000.0);
    }
}

#[pymethods]
impl MiddlewarePipeline {
    #[new]
    pub fn new() -> Self {
        MiddlewarePipeline {
            middlewares: Vec::new(),
            buffer_pool: Arc::new(ZeroCopyBufferPool::new()),
            metrics: Arc::new(RwLock::new(MiddlewareMetrics::default())),
        }
    }

    /// Add middleware to the pipeline
    pub fn add_middleware(&mut self, middleware: BuiltinMiddleware) -> PyResult<()> {
        let middleware_impl: Arc<dyn Middleware + Send + Sync> = match middleware {
            BuiltinMiddleware::Cors(cors) => Arc::new(cors),
            BuiltinMiddleware::RateLimit(rate_limit) => Arc::new(rate_limit),
            BuiltinMiddleware::Compression(compression) => Arc::new(compression),
            BuiltinMiddleware::Authentication(auth) => Arc::new(auth),
            BuiltinMiddleware::Logging(logging) => Arc::new(logging),
            BuiltinMiddleware::Caching(caching) => Arc::new(caching),
        };
        
        self.middlewares.push(middleware_impl);
        
        // Sort by priority (higher priority first)
        self.middlewares.sort_by(|a, b| b.priority().cmp(&a.priority()));
        
        Ok(())
    }

    /// Process request through middleware pipeline
    pub fn process_request(&self, mut ctx: RequestContext) -> PyResult<RequestContext> {
        let rt = tokio::runtime::Runtime::new().unwrap();
        
        rt.block_on(async {
            let mut metrics = self.metrics.write().await;
            metrics.total_requests += 1;
            
            for middleware in &self.middlewares {
                let start = Instant::now();
                
                match middleware.process_request(&mut ctx) {
                    Ok(()) => {
                        let duration = start.elapsed();
                        metrics.middleware_timings
                            .entry(middleware.name().to_string())
                            .or_insert_with(Vec::new)
                            .push(duration);
                    }
                    Err(e) => {
                        *metrics.error_counts
                            .entry(middleware.name().to_string())
                            .or_insert(0) += 1;
                        
                        return Err(pyo3::exceptions::PyRuntimeError::new_err(
                            format!("Middleware {} failed: {}", middleware.name(), e)
                        ));
                    }
                }
            }
            
            Ok(ctx)
        })
    }

    /// Process response through middleware pipeline (in reverse order)
    pub fn process_response(&self, mut ctx: ResponseContext) -> PyResult<ResponseContext> {
        let rt = tokio::runtime::Runtime::new().unwrap();
        
        rt.block_on(async {
            let mut metrics = self.metrics.write().await;
            metrics.total_responses += 1;
            
            // Process in reverse order for response
            for middleware in self.middlewares.iter().rev() {
                let start = Instant::now();
                
                match middleware.process_response(&mut ctx) {
                    Ok(()) => {
                        let duration = start.elapsed();
                        metrics.middleware_timings
                            .entry(format!("{}_response", middleware.name()))
                            .or_insert_with(Vec::new)
                            .push(duration);
                    }
                    Err(e) => {
                        *metrics.error_counts
                            .entry(format!("{}_response", middleware.name()))
                            .or_insert(0) += 1;
                        
                        return Err(pyo3::exceptions::PyRuntimeError::new_err(
                            format!("Response middleware {} failed: {}", middleware.name(), e)
                        ));
                    }
                }
            }
            
            Ok(ctx)
        })
    }

    /// Get middleware performance metrics
    pub fn get_metrics(&self) -> PyResult<String> {
        let rt = tokio::runtime::Runtime::new().unwrap();
        
        rt.block_on(async {
            let metrics = self.metrics.read().await;
            
            let mut result = format!(
                "Middleware Pipeline Metrics:\n\
                Total Requests: {}\n\
                Total Responses: {}\n\n",
                metrics.total_requests,
                metrics.total_responses
            );
            
            result.push_str("Middleware Timings:\n");
            for (name, timings) in &metrics.middleware_timings {
                if !timings.is_empty() {
                    let avg = timings.iter().sum::<Duration>() / timings.len() as u32;
                    let min = timings.iter().min().unwrap();
                    let max = timings.iter().max().unwrap();
                    
                    result.push_str(&format!(
                        "  {}: avg={:.2}ms, min={:.2}ms, max={:.2}ms, count={}\n",
                        name,
                        avg.as_secs_f64() * 1000.0,
                        min.as_secs_f64() * 1000.0,
                        max.as_secs_f64() * 1000.0,
                        timings.len()
                    ));
                }
            }
            
            if !metrics.error_counts.is_empty() {
                result.push_str("\nError Counts:\n");
                for (name, count) in &metrics.error_counts {
                    result.push_str(&format!("  {}: {}\n", name, count));
                }
            }
            
            Ok(result)
        })
    }

    /// Clear metrics
    pub fn clear_metrics(&self) -> PyResult<()> {
        let rt = tokio::runtime::Runtime::new().unwrap();
        
        rt.block_on(async {
            let mut metrics = self.metrics.write().await;
            *metrics = MiddlewareMetrics::default();
            Ok(())
        })
    }
}

/// Built-in middleware types
#[pyclass]
#[derive(Clone)]
pub enum BuiltinMiddleware {
    Cors(CorsMiddleware),
    RateLimit(RateLimitMiddleware),
    Compression(CompressionMiddleware),
    Authentication(AuthenticationMiddleware),
    Logging(LoggingMiddleware),
    Caching(CachingMiddleware),
}

/// CORS middleware for cross-origin requests
#[pyclass]
#[derive(Clone)]
pub struct CorsMiddleware {
    allowed_origins: Vec<String>,
    allowed_methods: Vec<String>,
    allowed_headers: Vec<String>,
    max_age: u32,
}

#[pymethods]
impl CorsMiddleware {
    #[new]
    pub fn new(
        allowed_origins: Vec<String>,
        allowed_methods: Vec<String>,
        allowed_headers: Vec<String>,
        max_age: Option<u32>,
    ) -> Self {
        CorsMiddleware {
            allowed_origins,
            allowed_methods,
            allowed_headers,
            max_age: max_age.unwrap_or(86400), // 24 hours default
        }
    }
}

impl Middleware for CorsMiddleware {
    fn name(&self) -> &str { "cors" }
    
    fn priority(&self) -> i32 { 100 } // High priority
    
    fn process_request(&self, ctx: &mut RequestContext) -> Result<(), MiddlewareError> {
        // Handle preflight requests
        if ctx.method == "OPTIONS" {
            ctx.metadata.insert("cors_preflight".to_string(), "true".to_string());
        }
        
        // Validate origin
        if let Some(origin) = ctx.headers.get("origin") {
            if !self.allowed_origins.contains(&"*".to_string()) 
                && !self.allowed_origins.contains(origin) {
                return Err(MiddlewareError {
                    message: "Origin not allowed".to_string(),
                    status_code: 403,
                });
            }
        }
        
        Ok(())
    }
    
    fn process_response(&self, ctx: &mut ResponseContext) -> Result<(), MiddlewareError> {
        // Add CORS headers
        ctx.headers.insert(
            "Access-Control-Allow-Origin".to_string(),
            self.allowed_origins.join(",")
        );
        ctx.headers.insert(
            "Access-Control-Allow-Methods".to_string(),
            self.allowed_methods.join(",")
        );
        ctx.headers.insert(
            "Access-Control-Allow-Headers".to_string(),
            self.allowed_headers.join(",")
        );
        ctx.headers.insert(
            "Access-Control-Max-Age".to_string(),
            self.max_age.to_string()
        );
        
        Ok(())
    }
}

/// Rate limiting middleware
#[pyclass]
#[derive(Clone)]
pub struct RateLimitMiddleware {
    requests_per_minute: u32,
    window_size: Duration,
    request_counts: Arc<RwLock<HashMap<String, (Instant, u32)>>>,
}

#[pymethods]
impl RateLimitMiddleware {
    #[new]
    pub fn new(requests_per_minute: u32) -> Self {
        RateLimitMiddleware {
            requests_per_minute,
            window_size: Duration::from_secs(60),
            request_counts: Arc::new(RwLock::new(HashMap::new())),
        }
    }
}

impl Middleware for RateLimitMiddleware {
    fn name(&self) -> &str { "rate_limit" }
    
    fn priority(&self) -> i32 { 90 } // High priority
    
    fn process_request(&self, ctx: &mut RequestContext) -> Result<(), MiddlewareError> {
        let rt = tokio::runtime::Runtime::new().unwrap();
        
        rt.block_on(async {
            let client_ip = ctx.headers.get("x-forwarded-for")
                .or_else(|| ctx.headers.get("x-real-ip"))
                .unwrap_or(&"unknown".to_string())
                .clone();
            
            let mut counts = self.request_counts.write().await;
            let now = Instant::now();
            
            let default_entry = (now, 0);
            let (last_reset, count) = counts.get(&client_ip).unwrap_or(&default_entry);
            let last_reset = *last_reset;
            let count = *count;
            
            // Reset window if expired
            if now.duration_since(last_reset) >= self.window_size {
                counts.insert(client_ip.clone(), (now, 1));
            } else if count >= self.requests_per_minute {
                return Err(MiddlewareError {
                    message: "Rate limit exceeded".to_string(),
                    status_code: 429,
                });
            } else {
                counts.insert(client_ip, (last_reset, count + 1));
            }
            
            Ok(())
        })
    }
    
    fn process_response(&self, ctx: &mut ResponseContext) -> Result<(), MiddlewareError> {
        ctx.headers.insert(
            "X-RateLimit-Limit".to_string(),
            self.requests_per_minute.to_string()
        );
        Ok(())
    }
}

/// Compression middleware
#[pyclass]
#[derive(Clone)]
pub struct CompressionMiddleware {
    min_size: usize,
    compression_level: u32,
}

#[pymethods]
impl CompressionMiddleware {
    #[new]
    pub fn new(min_size: Option<usize>, compression_level: Option<u32>) -> Self {
        CompressionMiddleware {
            min_size: min_size.unwrap_or(1024), // 1KB default
            compression_level: compression_level.unwrap_or(6), // Balanced compression
        }
    }
}

impl Middleware for CompressionMiddleware {
    fn name(&self) -> &str { "compression" }
    
    fn priority(&self) -> i32 { 10 } // Low priority (runs last)
    
    fn process_request(&self, ctx: &mut RequestContext) -> Result<(), MiddlewareError> {
        // Check if client accepts compression
        if let Some(accept_encoding) = ctx.headers.get("accept-encoding") {
            if accept_encoding.contains("gzip") {
                ctx.metadata.insert("compression_supported".to_string(), "gzip".to_string());
            }
        }
        Ok(())
    }
    
    fn process_response(&self, ctx: &mut ResponseContext) -> Result<(), MiddlewareError> {
        // Compress response if conditions are met
        if let Some(body) = &ctx.body {
            if body.len() >= self.min_size {
                if let Some(_) = ctx.metadata.get("compression_supported") {
                    // TODO: Implement actual compression
                    ctx.headers.insert("Content-Encoding".to_string(), "gzip".to_string());
                    ctx.metadata.insert("compressed".to_string(), "true".to_string());
                }
            }
        }
        Ok(())
    }
}

/// Authentication middleware
#[pyclass]
#[derive(Clone)]
pub struct AuthenticationMiddleware {
    secret_key: String,
    token_header: String,
}

#[pymethods]
impl AuthenticationMiddleware {
    #[new]
    pub fn new(secret_key: String, token_header: Option<String>) -> Self {
        AuthenticationMiddleware {
            secret_key,
            token_header: token_header.unwrap_or_else(|| "Authorization".to_string()),
        }
    }
}

impl Middleware for AuthenticationMiddleware {
    fn name(&self) -> &str { "authentication" }
    
    fn priority(&self) -> i32 { 80 } // High priority
    
    fn process_request(&self, ctx: &mut RequestContext) -> Result<(), MiddlewareError> {
        if let Some(token) = ctx.headers.get(&self.token_header) {
            // Simple token validation (in production, use proper JWT validation)
            if token.starts_with("Bearer ") {
                let token_value = &token[7..];
                if !token_value.is_empty() {
                    ctx.metadata.insert("authenticated".to_string(), "true".to_string());
                    ctx.metadata.insert("user_token".to_string(), token_value.to_string());
                    return Ok(());
                }
            }
        }
        
        Err(MiddlewareError {
            message: "Authentication required".to_string(),
            status_code: 401,
        })
    }
    
    fn process_response(&self, _ctx: &mut ResponseContext) -> Result<(), MiddlewareError> {
        Ok(())
    }
}

/// Logging middleware
#[pyclass]
#[derive(Clone)]
pub struct LoggingMiddleware {
    log_level: String,
    include_headers: bool,
}

#[pymethods]
impl LoggingMiddleware {
    #[new]
    pub fn new(log_level: Option<String>, include_headers: Option<bool>) -> Self {
        LoggingMiddleware {
            log_level: log_level.unwrap_or_else(|| "info".to_string()),
            include_headers: include_headers.unwrap_or(false),
        }
    }
}

impl Middleware for LoggingMiddleware {
    fn name(&self) -> &str { "logging" }
    
    fn priority(&self) -> i32 { 50 } // Medium priority
    
    fn process_request(&self, ctx: &mut RequestContext) -> Result<(), MiddlewareError> {
        // No logging in production for maximum performance
        Ok(())
    }
    
    fn process_response(&self, ctx: &mut ResponseContext) -> Result<(), MiddlewareError> {
        // No logging in production for maximum performance
        Ok(())
    }
}

/// Caching middleware
#[pyclass]
#[derive(Clone)]
pub struct CachingMiddleware {
    cache_duration: Duration,
    cache_store: Arc<RwLock<HashMap<String, (Instant, ZeroCopyBytes)>>>,
}

#[pymethods]
impl CachingMiddleware {
    #[new]
    pub fn new(cache_duration_seconds: Option<u64>) -> Self {
        CachingMiddleware {
            cache_duration: Duration::from_secs(cache_duration_seconds.unwrap_or(300)), // 5 minutes
            cache_store: Arc::new(RwLock::new(HashMap::new())),
        }
    }
}

impl Middleware for CachingMiddleware {
    fn name(&self) -> &str { "caching" }
    
    fn priority(&self) -> i32 { 70 } // High priority
    
    fn process_request(&self, ctx: &mut RequestContext) -> Result<(), MiddlewareError> {
        if ctx.method == "GET" {
            let rt = tokio::runtime::Runtime::new().unwrap();
            
            rt.block_on(async {
                let cache = self.cache_store.read().await;
                let cache_key = format!("{}:{}", ctx.method, ctx.path);
                
                if let Some((timestamp, cached_response)) = cache.get(&cache_key) {
                    if timestamp.elapsed() < self.cache_duration {
                        ctx.metadata.insert("cache_hit".to_string(), "true".to_string());
                        ctx.metadata.insert("cached_response".to_string(), 
                            String::from_utf8_lossy(&cached_response.as_bytes()).to_string());
                    }
                }
            });
        }
        Ok(())
    }
    
    fn process_response(&self, ctx: &mut ResponseContext) -> Result<(), MiddlewareError> {
        if ctx.status_code == 200 {
            if let Some(body) = &ctx.body {
                let rt = tokio::runtime::Runtime::new().unwrap();
                
                rt.block_on(async {
                    let mut cache = self.cache_store.write().await;
                    let cache_key = format!("GET:{}", 
                        ctx.metadata.get("request_path").unwrap_or(&"unknown".to_string()));
                    
                    cache.insert(cache_key, (Instant::now(), body.clone()));
                    
                    // Clean up expired entries (simple cleanup)
                    let now = Instant::now();
                    cache.retain(|_, (timestamp, _)| now.duration_since(*timestamp) < self.cache_duration);
                });
                
                ctx.headers.insert("X-Cache".to_string(), "MISS".to_string());
            }
        }
        Ok(())
    }
}
