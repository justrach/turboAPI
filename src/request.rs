use pyo3::prelude::*;
use std::collections::HashMap;

/// Zero-copy view of an HTTP request from Rust
#[pyclass]
pub struct RequestView {
    #[pyo3(get)]
    pub method: String,
    #[pyo3(get)]
    pub path: String,
    #[pyo3(get)]
    pub query_string: String,
    pub headers: HashMap<String, String>,
    pub body: Vec<u8>,
}

#[pymethods]
impl RequestView {
    #[new]
    pub fn new(method: String, path: String, query_string: String) -> Self {
        RequestView {
            method,
            path,
            query_string,
            headers: HashMap::new(),
            body: Vec::new(),
        }
    }

    /// Get header value by name (case-insensitive)
    pub fn get_header(&self, name: &str) -> Option<String> {
        let name_lower = name.to_lowercase();
        for (key, value) in &self.headers {
            if key.to_lowercase() == name_lower {
                return Some(value.clone());
            }
        }
        None
    }

    /// Get all headers as a dict
    pub fn get_headers(&self) -> HashMap<String, String> {
        self.headers.clone()
    }

    /// Get request body as bytes
    pub fn get_body(&self) -> Vec<u8> {
        self.body.clone()
    }

    /// Get request body as string (UTF-8)
    pub fn get_body_str(&self) -> PyResult<String> {
        String::from_utf8(self.body.clone())
            .map_err(|e| pyo3::exceptions::PyUnicodeDecodeError::new_err(e.to_string()))
    }
}
