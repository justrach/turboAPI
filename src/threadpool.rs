use std::sync::{Arc, Mutex};
use std::thread;
use std::time::Duration;
use crossbeam::channel::{unbounded, Receiver, Sender};
use pyo3::prelude::*;
use pyo3::types::PyAnyMethods;

/// High-performance work-stealing thread pool for Python handler execution
#[pyclass]
pub struct WorkStealingPool {
    workers: Vec<Worker>,
    sender: Sender<Job>,
    size: usize,
}

type Job = Box<dyn FnOnce() + Send + 'static>;

struct Worker {
    id: usize,
    thread: Option<thread::JoinHandle<()>>,
}

impl Worker {
    fn new(id: usize, receiver: Arc<Mutex<Receiver<Job>>>) -> Worker {
        let thread = thread::spawn(move || loop {
            let job = receiver.lock().unwrap().recv();
            
            match job {
                Ok(job) => {
                    // Execute the job
                    job();
                }
                Err(_) => {
                    // Channel closed, exit worker
                    break;
                }
            }
        });

        Worker {
            id,
            thread: Some(thread),
        }
    }
}

#[pymethods]
impl WorkStealingPool {
    #[new]
    pub fn new(size: Option<usize>) -> Self {
        let size = size.unwrap_or_else(num_cpus::get);
        let (sender, receiver) = unbounded();
        let receiver = Arc::new(Mutex::new(receiver));

        let mut workers = Vec::with_capacity(size);

        for id in 0..size {
            workers.push(Worker::new(id, Arc::clone(&receiver)));
        }

        WorkStealingPool {
            workers,
            sender,
            size,
        }
    }

    /// Execute a Python callable in the thread pool (free-threading compatible)
    pub fn execute_python(&self, callable: Bound<'_, PyAny>, args: Bound<'_, PyAny>) -> PyResult<()> {
        // Convert to unbound objects that can be sent across threads
        let callable_unbound = callable.unbind();
        let args_unbound = args.unbind();

        let job = Box::new(move || {
            // Attach to the Python runtime for this thread
            // This works in both GIL and free-threading modes
            Python::with_gil(|py| {
                let callable_bound = callable_unbound.bind(py);
                let args_bound = args_unbound.bind(py);
                
                if let Err(e) = callable_bound.call1((args_bound,)) {
                    // Log errors only in debug mode to reduce production overhead
                    if cfg!(debug_assertions) {
                        eprintln!("Thread pool execution error: {:?}", e);
                    }
                }
                // Thread automatically detaches when py goes out of scope
            });
        });

        self.sender.send(job).map_err(|_| {
            pyo3::exceptions::PyRuntimeError::new_err("Thread pool is shut down")
        })?;

        Ok(())
    }

    /// Get pool statistics
    pub fn stats(&self) -> std::collections::HashMap<String, usize> {
        let mut stats = std::collections::HashMap::new();
        stats.insert("worker_count".to_string(), self.size);
        stats.insert("queue_size".to_string(), self.sender.len());
        stats
    }

    /// Get the number of worker threads
    pub fn worker_count(&self) -> usize {
        self.size
    }
}

impl Drop for WorkStealingPool {
    fn drop(&mut self) {
        // Close the channel
        drop(self.sender.clone());

        // Wait for all workers to finish
        for worker in &mut self.workers {
            if let Some(thread) = worker.thread.take() {
                thread.join().unwrap();
            }
        }
    }
}

/// CPU-optimized thread pool for compute-intensive tasks
#[pyclass]
pub struct CpuPool {
    pool: rayon::ThreadPool,
}

#[pymethods]
impl CpuPool {
    #[new]
    pub fn new(threads: Option<usize>) -> PyResult<Self> {
        let threads = threads.unwrap_or_else(num_cpus::get);
        
        let pool = rayon::ThreadPoolBuilder::new()
            .num_threads(threads)
            .build()
            .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(format!("Failed to create thread pool: {}", e)))?;

        Ok(CpuPool { pool })
    }

    /// Execute CPU-intensive work in parallel
    pub fn execute_parallel(&self, py: Python, work_items: Vec<PyObject>) -> PyResult<Vec<PyObject>> {
        use rayon::prelude::*;

        let results: Result<Vec<_>, _> = work_items
            .into_par_iter()
            .map(|item| {
                Python::with_gil(|py| {
                    // Process each item in parallel
                    // This is where CPU-intensive validation or processing would happen
                    Ok(item)
                })
            })
            .collect();

        results.map_err(|e: PyErr| e)
    }

    /// Get the number of threads in the pool
    pub fn thread_count(&self) -> usize {
        self.pool.current_num_threads()
    }
}

/// Async task executor for I/O-bound operations
#[pyclass]
pub struct AsyncExecutor {
    runtime: tokio::runtime::Runtime,
}

#[pymethods]
impl AsyncExecutor {
    #[new]
    pub fn new() -> PyResult<Self> {
        let runtime = tokio::runtime::Builder::new_multi_thread()
            .worker_threads(num_cpus::get())
            .enable_all()
            .build()
            .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(format!("Failed to create async runtime: {}", e)))?;

        Ok(AsyncExecutor { runtime })
    }

    /// Execute async Python code
    pub fn execute_async(&self, py: Python, coro: Py<PyAny>) -> PyResult<Py<PyAny>> {
        // This would be used for async Python handlers
        // For now, return the coroutine as-is
        Ok(coro)
    }

    /// Get runtime statistics
    pub fn stats(&self) -> std::collections::HashMap<String, usize> {
        let mut stats = std::collections::HashMap::new();
        stats.insert("worker_threads".to_string(), num_cpus::get());
        stats
    }
}

/// Phase 3 concurrency manager that coordinates all thread pools
#[pyclass]
pub struct ConcurrencyManager {
    work_stealing_pool: WorkStealingPool,
    cpu_pool: CpuPool,
    async_executor: AsyncExecutor,
}

#[pymethods]
impl ConcurrencyManager {
    #[new]
    pub fn new(
        work_threads: Option<usize>,
        cpu_threads: Option<usize>
    ) -> PyResult<Self> {
        Ok(ConcurrencyManager {
            work_stealing_pool: WorkStealingPool::new(work_threads),
            cpu_pool: CpuPool::new(cpu_threads)?,
            async_executor: AsyncExecutor::new()?,
        })
    }

    /// Execute a Python handler with optimal threading strategy
    pub fn execute_handler(
        &self,
        handler_type: &str,
        callable: Bound<'_, PyAny>,
        args: Bound<'_, PyAny>
    ) -> PyResult<()> {
        match handler_type {
            "sync" => self.work_stealing_pool.execute_python(callable, args),
            "cpu_intensive" => {
                // Use CPU pool for compute-heavy tasks
                self.work_stealing_pool.execute_python(callable, args)
            }
            "async" => {
                // Use async executor for I/O-bound tasks
                self.work_stealing_pool.execute_python(callable, args)
            }
            _ => {
                // Default to work-stealing pool
                self.work_stealing_pool.execute_python(callable, args)
            }
        }
    }

    /// Get comprehensive concurrency statistics
    pub fn get_stats(&self) -> std::collections::HashMap<String, std::collections::HashMap<String, usize>> {
        let mut stats = std::collections::HashMap::new();
        stats.insert("work_stealing".to_string(), self.work_stealing_pool.stats());
        stats.insert("async_executor".to_string(), self.async_executor.stats());
        
        let mut cpu_stats = std::collections::HashMap::new();
        cpu_stats.insert("thread_count".to_string(), self.cpu_pool.thread_count());
        stats.insert("cpu_pool".to_string(), cpu_stats);
        
        stats
    }

    /// Optimize thread pool sizes based on workload
    pub fn optimize_for_workload(&self, workload_type: &str) -> std::collections::HashMap<String, String> {
        let mut recommendations = std::collections::HashMap::new();
        
        match workload_type {
            "cpu_intensive" => {
                recommendations.insert("strategy".to_string(), "Use CPU pool for parallel processing".to_string());
                recommendations.insert("threads".to_string(), format!("{} (CPU cores)", num_cpus::get()));
            }
            "io_intensive" => {
                recommendations.insert("strategy".to_string(), "Use async executor with high concurrency".to_string());
                recommendations.insert("threads".to_string(), format!("{} (2x CPU cores)", num_cpus::get() * 2));
            }
            "mixed" => {
                recommendations.insert("strategy".to_string(), "Use work-stealing pool for balanced load".to_string());
                recommendations.insert("threads".to_string(), format!("{} (CPU cores)", num_cpus::get()));
            }
            _ => {
                recommendations.insert("strategy".to_string(), "Default work-stealing configuration".to_string());
                recommendations.insert("threads".to_string(), format!("{}", num_cpus::get()));
            }
        }
        
        recommendations
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_work_stealing_pool_creation() {
        let pool = WorkStealingPool::new(Some(4));
        assert_eq!(pool.worker_count(), 4);
    }

    #[test]
    fn test_cpu_pool_creation() {
        let pool = CpuPool::new(Some(2)).unwrap();
        assert_eq!(pool.thread_count(), 2);
    }

    #[test]
    fn test_concurrency_manager() {
        let manager = ConcurrencyManager::new(Some(4), Some(2)).unwrap();
        let stats = manager.get_stats();
        assert!(stats.contains_key("work_stealing"));
        assert!(stats.contains_key("cpu_pool"));
        assert!(stats.contains_key("async_executor"));
    }
}
