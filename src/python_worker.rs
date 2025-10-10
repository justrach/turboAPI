//! Python Interpreter Worker - Persistent Event Loop
//! 
//! This module implements a dedicated worker thread that runs:
//! - A Tokio current_thread runtime
//! - A persistent Python asyncio event loop
//! - Cached TaskLocals for zero-overhead async calls
//!
//! Architecture:
//! Main Hyper Runtime → MPSC → Python Worker Thread → Response
//!                              (single thread, no cross-thread hops)

use pyo3::prelude::*;
use pyo3::types::PyDict;
use tokio::sync::{mpsc, oneshot};
use std::sync::Arc;
use bytes::Bytes;

/// Request message sent from Hyper handlers to Python worker
pub struct PythonRequest {
    pub handler: PyObject,
    pub method: String,
    pub path: String,
    pub query_string: String,
    pub body: Bytes,
    pub response_tx: oneshot::Sender<Result<String, String>>,
}

/// Handle to the Python worker for sending requests
#[derive(Clone)]
pub struct PythonWorkerHandle {
    tx: mpsc::Sender<PythonRequest>,
}

impl PythonWorkerHandle {
    /// Send a request to the Python worker and await the response
    pub async fn execute_handler(
        &self,
        handler: PyObject,
        method: String,
        path: String,
        query_string: String,
        body: Bytes,
    ) -> Result<String, String> {
        let (response_tx, response_rx) = oneshot::channel();
        
        let request = PythonRequest {
            handler,
            method,
            path,
            query_string,
            body,
            response_tx,
        };
        
        // Send request to worker (with backpressure)
        self.tx.send(request).await
            .map_err(|_| "Python worker channel closed".to_string())?;
        
        // Await response
        response_rx.await
            .map_err(|_| "Python worker response channel closed".to_string())?
    }
}

/// Spawn the Python interpreter worker thread
/// 
/// This creates a dedicated thread that runs:
/// 1. Tokio current_thread runtime
/// 2. Python asyncio event loop (persistent)
/// 3. Cached TaskLocals for efficient async calls
pub fn spawn_python_worker(queue_capacity: usize) -> PythonWorkerHandle {
    let (tx, rx) = mpsc::channel::<PythonRequest>(queue_capacity);
    
    // Spawn dedicated worker thread
    std::thread::spawn(move || {
        // Create current_thread Tokio runtime
        let rt = tokio::runtime::Builder::new_current_thread()
            .enable_all()
            .build()
            .expect("Failed to create Python worker runtime");
        
        // Run the worker loop on this runtime
        rt.block_on(async move {
            if let Err(e) = run_python_worker(rx).await {
                eprintln!("[ERROR] Python worker failed: {}", e);
            }
        });
    });
    
    PythonWorkerHandle { tx }
}

/// Main Python worker loop - runs on dedicated thread
async fn run_python_worker(mut rx: mpsc::Receiver<PythonRequest>) -> PyResult<()> {
    // Initialize Python interpreter (if not already initialized)
    pyo3::prepare_freethreaded_python();
    
    // Set up persistent asyncio event loop and TaskLocals
    let (task_locals, json_module) = Python::with_gil(|py| -> PyResult<_> {
        // Import asyncio and create new event loop
        let asyncio = py.import("asyncio")?;
        let event_loop = asyncio.call_method0("new_event_loop")?;
        asyncio.call_method1("set_event_loop", (event_loop,))?;
        
        println!("[WORKER] Python asyncio event loop created");
        
        // Create TaskLocals once and cache them
        let task_locals = pyo3_async_runtimes::TaskLocals::with_running_loop(py)?
            .copy_context(py)?;
        
        println!("[WORKER] TaskLocals cached for reuse");
        
        // Cache JSON module for serialization
        let json_module: PyObject = py.import("json")?.into();
        
        // Cache inspect module for checking async functions
        let _inspect_module: PyObject = py.import("inspect")?.into();
        
        Ok((task_locals, json_module))
    })?;
    
    println!("[WORKER] Python worker ready - processing requests...");
    
    // Process requests from the queue
    while let Some(request) = rx.recv().await {
        let result = process_request(
            request.handler,
            &task_locals,
            &json_module,
        ).await;
        
        // Send response back (ignore if receiver dropped)
        let _ = request.response_tx.send(result);
    }
    
    println!("[WORKER] Python worker shutting down");
    Ok(())
}

/// Process a single request - either sync or async handler
async fn process_request(
    handler: PyObject,
    task_locals: &pyo3_async_runtimes::TaskLocals,
    json_module: &PyObject,
) -> Result<String, String> {
    // Check if handler is async
    let is_async = Python::with_gil(|py| {
        let inspect = py.import("inspect").unwrap();
        inspect.call_method1("iscoroutinefunction", (handler.clone_ref(py),))
            .unwrap()
            .extract::<bool>()
            .unwrap()
    });
    
    if is_async {
        // Async handler - use cached TaskLocals (no event loop creation!)
        process_async_handler(handler, task_locals, json_module).await
    } else {
        // Sync handler - direct call with single GIL acquisition
        process_sync_handler(handler, json_module)
    }
}

/// Process sync handler - single GIL acquisition
fn process_sync_handler(
    handler: PyObject,
    json_module: &PyObject,
) -> Result<String, String> {
    Python::with_gil(|py| {
        // Call handler
        let result = handler.bind(py).call0()
            .map_err(|e| format!("Handler error: {}", e))?;
        
        // Serialize result (convert Bound to Py)
        serialize_result(py, result.unbind(), json_module)
    })
}

/// Process async handler - reuse cached TaskLocals
async fn process_async_handler(
    handler: PyObject,
    task_locals: &pyo3_async_runtimes::TaskLocals,
    json_module: &PyObject,
) -> Result<String, String> {
    // Convert Python coroutine to Rust future using cached TaskLocals
    let future = Python::with_gil(|py| {
        // Call async handler to get coroutine
        let coroutine = handler.bind(py).call0()
            .map_err(|e| format!("Handler error: {}", e))?;
        
        // Convert to Rust future with cached TaskLocals (no new event loop!)
        pyo3_async_runtimes::into_future_with_locals(
            task_locals,
            coroutine
        ).map_err(|e| format!("Failed to convert coroutine: {}", e))
    })?;
    
    // Await the future
    let result = future.await
        .map_err(|e| format!("Async execution error: {}", e))?;
    
    // Serialize result
    Python::with_gil(|py| {
        serialize_result(py, result, json_module)
    })
}

/// Serialize Python result to JSON string
fn serialize_result(
    py: Python,
    result: Py<PyAny>,
    json_module: &PyObject,
) -> Result<String, String> {
    let result = result.bind(py);
    // Try direct string extraction first
    if let Ok(json_str) = result.extract::<String>() {
        return Ok(json_str);
    }
    
    // Fall back to json.dumps()
    let json_dumps = json_module.getattr(py, "dumps")
        .map_err(|e| format!("Failed to get json.dumps: {}", e))?;
    
    let json_str = json_dumps.call1(py, (result,))
        .map_err(|e| format!("JSON serialization error: {}", e))?;
    
    json_str.extract::<String>(py)
        .map_err(|e| format!("Failed to extract JSON string: {}", e))
}
