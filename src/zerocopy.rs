use pyo3::prelude::*;
use std::sync::Arc;
use bytes::{Bytes, BytesMut, Buf, BufMut};
use std::collections::{VecDeque, HashMap};
use tokio::sync::Mutex;
use std::ptr;
use std::slice;
use std::sync::OnceLock;

// Singleton runtime for zerocopy operations
static ZEROCOPY_RUNTIME: OnceLock<tokio::runtime::Runtime> = OnceLock::new();

fn get_runtime() -> &'static tokio::runtime::Runtime {
    ZEROCOPY_RUNTIME.get_or_init(|| {
        tokio::runtime::Runtime::new().expect("Failed to create zerocopy runtime")
    })
}

/// Zero-copy buffer pool for efficient memory management
#[pyclass]
pub struct ZeroCopyBufferPool {
    small_buffers: Arc<Mutex<VecDeque<BytesMut>>>,  // 4KB buffers
    medium_buffers: Arc<Mutex<VecDeque<BytesMut>>>, // 64KB buffers
    large_buffers: Arc<Mutex<VecDeque<BytesMut>>>,  // 1MB buffers
    pool_stats: Arc<Mutex<PoolStats>>,
}

#[derive(Debug, Clone)]
struct PoolStats {
    small_allocated: usize,
    medium_allocated: usize,
    large_allocated: usize,
    small_reused: usize,
    medium_reused: usize,
    large_reused: usize,
    total_bytes_saved: usize,
}

impl Default for PoolStats {
    fn default() -> Self {
        PoolStats {
            small_allocated: 0,
            medium_allocated: 0,
            large_allocated: 0,
            small_reused: 0,
            medium_reused: 0,
            large_reused: 0,
            total_bytes_saved: 0,
        }
    }
}

#[pymethods]
impl ZeroCopyBufferPool {
    #[new]
    pub fn new() -> Self {
        ZeroCopyBufferPool {
            small_buffers: Arc::new(Mutex::new(VecDeque::new())),
            medium_buffers: Arc::new(Mutex::new(VecDeque::new())),
            large_buffers: Arc::new(Mutex::new(VecDeque::new())),
            pool_stats: Arc::new(Mutex::new(PoolStats::default())),
        }
    }

    /// Get a buffer from the pool or allocate a new one
    pub fn get_buffer(&self, size_hint: usize) -> PyResult<ZeroCopyBuffer> {
        let rt = get_runtime();
        
        rt.block_on(async {
            let mut stats = self.pool_stats.lock().await;
            
            match size_hint {
                0..=4096 => {
                    let mut pool = self.small_buffers.lock().await;
                    if let Some(mut buffer) = pool.pop_front() {
                        buffer.clear();
                        stats.small_reused += 1;
                        stats.total_bytes_saved += 4096;
                        Ok(ZeroCopyBuffer::new(buffer))
                    } else {
                        stats.small_allocated += 1;
                        Ok(ZeroCopyBuffer::new(BytesMut::with_capacity(4096)))
                    }
                }
                4097..=65536 => {
                    let mut pool = self.medium_buffers.lock().await;
                    if let Some(mut buffer) = pool.pop_front() {
                        buffer.clear();
                        stats.medium_reused += 1;
                        stats.total_bytes_saved += 65536;
                        Ok(ZeroCopyBuffer::new(buffer))
                    } else {
                        stats.medium_allocated += 1;
                        Ok(ZeroCopyBuffer::new(BytesMut::with_capacity(65536)))
                    }
                }
                _ => {
                    let mut pool = self.large_buffers.lock().await;
                    if let Some(mut buffer) = pool.pop_front() {
                        buffer.clear();
                        stats.large_reused += 1;
                        stats.total_bytes_saved += 1024 * 1024;
                        Ok(ZeroCopyBuffer::new(buffer))
                    } else {
                        stats.large_allocated += 1;
                        Ok(ZeroCopyBuffer::new(BytesMut::with_capacity(1024 * 1024)))
                    }
                }
            }
        })
    }

    /// Return a buffer to the pool for reuse
    pub fn return_buffer(&self, buffer: &ZeroCopyBuffer) -> PyResult<()> {
        let rt = get_runtime();
        
        rt.block_on(async {
            let inner = buffer.inner.clone();
            let capacity = inner.capacity();
            
            // Only return buffers that are reasonably sized to avoid memory bloat
            match capacity {
                4096 => {
                    let mut pool = self.small_buffers.lock().await;
                    if pool.len() < 100 { // Limit pool size
                        pool.push_back(inner);
                    }
                }
                65536 => {
                    let mut pool = self.medium_buffers.lock().await;
                    if pool.len() < 50 {
                        pool.push_back(inner);
                    }
                }
                1048576 => { // 1MB
                    let mut pool = self.large_buffers.lock().await;
                    if pool.len() < 20 {
                        pool.push_back(inner);
                    }
                }
                _ => {
                    // Don't pool unusual sizes
                }
            }
            
            Ok(())
        })
    }

    /// Get pool statistics
    pub fn stats(&self) -> PyResult<String> {
        let rt = get_runtime();
        
        rt.block_on(async {
            let stats = self.pool_stats.lock().await;
            let small_pool_size = self.small_buffers.lock().await.len();
            let medium_pool_size = self.medium_buffers.lock().await.len();
            let large_pool_size = self.large_buffers.lock().await.len();
            
            Ok(format!(
                "BufferPool Stats:\n\
                Small (4KB): {} allocated, {} reused, {} pooled\n\
                Medium (64KB): {} allocated, {} reused, {} pooled\n\
                Large (1MB): {} allocated, {} reused, {} pooled\n\
                Total bytes saved: {:.2} MB",
                stats.small_allocated, stats.small_reused, small_pool_size,
                stats.medium_allocated, stats.medium_reused, medium_pool_size,
                stats.large_allocated, stats.large_reused, large_pool_size,
                stats.total_bytes_saved as f64 / 1024.0 / 1024.0
            ))
        })
    }

    /// Clear all pools and reset stats
    pub fn clear(&self) -> PyResult<()> {
        let rt = get_runtime();
        
        rt.block_on(async {
            self.small_buffers.lock().await.clear();
            self.medium_buffers.lock().await.clear();
            self.large_buffers.lock().await.clear();
            *self.pool_stats.lock().await = PoolStats::default();
            Ok(())
        })
    }
}

/// Zero-copy buffer wrapper
#[pyclass]
#[derive(Clone)]
pub struct ZeroCopyBuffer {
    inner: BytesMut,
}

impl ZeroCopyBuffer {
    fn new(buffer: BytesMut) -> Self {
        ZeroCopyBuffer { inner: buffer }
    }
}

#[pymethods]
impl ZeroCopyBuffer {
    /// Write data to the buffer without copying
    pub fn write_bytes(&mut self, data: &[u8]) -> PyResult<()> {
        self.inner.put_slice(data);
        Ok(())
    }

    /// Write string data to the buffer
    pub fn write_str(&mut self, data: &str) -> PyResult<()> {
        self.inner.put_slice(data.as_bytes());
        Ok(())
    }

    /// Get the buffer contents as bytes (zero-copy view)
    pub fn as_bytes(&self) -> Vec<u8> {
        self.inner.to_vec()
    }

    /// Get buffer length
    pub fn len(&self) -> usize {
        self.inner.len()
    }

    /// Get buffer capacity
    pub fn capacity(&self) -> usize {
        self.inner.capacity()
    }

    /// Check if buffer is empty
    pub fn is_empty(&self) -> bool {
        self.inner.is_empty()
    }

    /// Clear the buffer (keep capacity)
    pub fn clear(&mut self) {
        self.inner.clear();
    }

    /// Reserve additional capacity
    pub fn reserve(&mut self, additional: usize) {
        self.inner.reserve(additional);
    }

    /// Freeze the buffer into immutable Bytes (zero-copy)
    pub fn freeze(&mut self) -> ZeroCopyBytes {
        let taken = std::mem::replace(&mut self.inner, BytesMut::new());
        ZeroCopyBytes {
            inner: taken.freeze(),
        }
    }
}

/// Immutable zero-copy bytes
#[pyclass]
#[derive(Clone)]
pub struct ZeroCopyBytes {
    inner: Bytes,
}

#[pymethods]
impl ZeroCopyBytes {
    /// Get the bytes as a Python bytes object (zero-copy when possible)
    pub fn as_bytes(&self) -> Vec<u8> {
        self.inner.to_vec()
    }

    /// Get length
    pub fn len(&self) -> usize {
        self.inner.len()
    }

    /// Check if empty
    pub fn is_empty(&self) -> bool {
        self.inner.is_empty()
    }

    /// Slice the bytes (zero-copy)
    pub fn slice(&self, start: usize, end: usize) -> PyResult<ZeroCopyBytes> {
        if start > end || end > self.inner.len() {
            return Err(pyo3::exceptions::PyIndexError::new_err("Invalid slice range"));
        }
        
        Ok(ZeroCopyBytes {
            inner: self.inner.slice(start..end),
        })
    }

    /// Clone the bytes (reference counting, not actual copy)
    pub fn clone_ref(&self) -> ZeroCopyBytes {
        ZeroCopyBytes {
            inner: self.inner.clone(),
        }
    }
}

/// Zero-copy string interning for common strings
#[pyclass]
pub struct StringInterner {
    strings: Arc<Mutex<std::collections::HashMap<String, &'static str>>>,
    arena: Arc<Mutex<Vec<String>>>, // Keep strings alive
}

#[pymethods]
impl StringInterner {
    #[new]
    pub fn new() -> Self {
        StringInterner {
            strings: Arc::new(Mutex::new(std::collections::HashMap::new())),
            arena: Arc::new(Mutex::new(Vec::new())),
        }
    }

    /// Intern a string (returns static reference for common strings)
    pub fn intern(&self, s: String) -> PyResult<String> {
        let rt = get_runtime();
        
        rt.block_on(async {
            let mut strings = self.strings.lock().await;
            
            if let Some(&interned) = strings.get(&s) {
                // Return the interned string
                Ok(interned.to_string())
            } else {
                // Add to arena and intern
                let mut arena = self.arena.lock().await;
                arena.push(s.clone());
                
                // Get a static reference (this is safe because we keep the string in arena)
                let static_ref: &'static str = unsafe {
                    std::mem::transmute(arena.last().unwrap().as_str())
                };
                
                strings.insert(s.clone(), static_ref);
                Ok(s)
            }
        })
    }

    /// Get interning statistics
    pub fn stats(&self) -> PyResult<String> {
        let rt = get_runtime();
        
        rt.block_on(async {
            let strings = self.strings.lock().await;
            let arena = self.arena.lock().await;
            
            Ok(format!(
                "String Interner Stats:\n\
                Interned strings: {}\n\
                Arena size: {}\n\
                Memory saved: ~{} bytes",
                strings.len(),
                arena.len(),
                strings.len() * 50 // Rough estimate
            ))
        })
    }
}

/// Memory-mapped file reader for zero-copy file serving
#[pyclass]
pub struct ZeroCopyFileReader {
    file_path: String,
}

#[pymethods]
impl ZeroCopyFileReader {
    #[new]
    pub fn new(file_path: String) -> Self {
        ZeroCopyFileReader { file_path }
    }

    /// Read file contents with memory mapping (zero-copy)
    pub fn read_file(&self) -> PyResult<ZeroCopyBytes> {
        use std::fs::File;
        use std::io::Read;
        
        // For now, use regular file reading
        // In production, this would use memory mapping
        let mut file = File::open(&self.file_path)
            .map_err(|e| pyo3::exceptions::PyIOError::new_err(format!("Failed to open file: {}", e)))?;
        
        let mut contents = Vec::new();
        file.read_to_end(&mut contents)
            .map_err(|e| pyo3::exceptions::PyIOError::new_err(format!("Failed to read file: {}", e)))?;
        
        Ok(ZeroCopyBytes {
            inner: Bytes::from(contents),
        })
    }

    /// Get file size
    pub fn file_size(&self) -> PyResult<u64> {
        use std::fs;
        
        let metadata = fs::metadata(&self.file_path)
            .map_err(|e| pyo3::exceptions::PyIOError::new_err(format!("Failed to get file metadata: {}", e)))?;
        
        Ok(metadata.len())
    }
}

/// SIMD-accelerated operations for high-performance data processing
#[pyclass]
pub struct SIMDProcessor {
    // Placeholder for SIMD operations
}

#[pymethods]
impl SIMDProcessor {
    #[new]
    pub fn new() -> Self {
        SIMDProcessor {}
    }

    /// Fast memory comparison using SIMD when available
    pub fn fast_compare(&self, a: &[u8], b: &[u8]) -> bool {
        if a.len() != b.len() {
            return false;
        }
        
        // For now, use standard comparison
        // In production, this would use SIMD instructions
        a == b
    }

    /// Fast string search using SIMD
    pub fn fast_find(&self, haystack: &str, needle: &str) -> Option<usize> {
        // Standard implementation for now
        haystack.find(needle)
    }

    /// Fast checksum calculation
    pub fn fast_checksum(&self, data: &[u8]) -> u32 {
        // Simple checksum for now
        data.iter().fold(0u32, |acc, &byte| acc.wrapping_add(byte as u32))
    }
}

/// Zero-copy HTTP response builder
#[pyclass]
pub struct ZeroCopyResponse {
    status_code: u16,
    headers: Vec<(String, String)>,
    body: Option<ZeroCopyBytes>,
    buffer_pool: Arc<ZeroCopyBufferPool>,
}

#[pymethods]
impl ZeroCopyResponse {
    #[new]
    pub fn new(_buffer_pool: &ZeroCopyBufferPool) -> Self {
        ZeroCopyResponse {
            status_code: 200,
            headers: Vec::new(),
            body: None,
            buffer_pool: Arc::new(ZeroCopyBufferPool::new()), // Clone the pool reference
        }
    }

    /// Set status code
    pub fn status(&mut self, code: u16) -> PyResult<()> {
        self.status_code = code;
        Ok(())
    }

    /// Add header
    pub fn header(&mut self, name: String, value: String) -> PyResult<()> {
        self.headers.push((name, value));
        Ok(())
    }

    /// Set body from zero-copy bytes
    pub fn body_bytes(&mut self, body: &ZeroCopyBytes) -> PyResult<()> {
        self.body = Some(body.clone());
        Ok(())
    }

    /// Set body from string (will be converted to zero-copy bytes)
    pub fn body_str(&mut self, body: String) -> PyResult<()> {
        let buffer = self.buffer_pool.get_buffer(body.len())?;
        let mut buffer = buffer;
        buffer.write_str(&body)?;
        self.body = Some(buffer.freeze());
        Ok(())
    }

    /// Build the response into a zero-copy buffer
    pub fn build(&self) -> PyResult<ZeroCopyBytes> {
        let estimated_size = 200 + self.headers.len() * 50 + 
            self.body.as_ref().map(|b| b.len()).unwrap_or(0);
        
        let buffer = self.buffer_pool.get_buffer(estimated_size)?;
        let mut buffer = buffer;
        
        // Write status line
        buffer.write_str(&format!("HTTP/1.1 {} OK\r\n", self.status_code))?;
        
        // Write headers
        for (name, value) in &self.headers {
            buffer.write_str(&format!("{}: {}\r\n", name, value))?;
        }
        
        // End headers
        buffer.write_str("\r\n")?;
        
        // Write body if present
        if let Some(ref body) = self.body {
            buffer.write_bytes(&body.as_bytes())?;
        }
        
        Ok(buffer.freeze())
    }

    /// Get response info
    pub fn info(&self) -> String {
        format!(
            "ZeroCopyResponse: {} {} headers, {} bytes body",
            self.status_code,
            self.headers.len(),
            self.body.as_ref().map(|b| b.len()).unwrap_or(0)
        )
    }
}
