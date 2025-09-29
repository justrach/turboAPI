use pyo3::prelude::*;
use std::collections::HashMap;

/// HTTP response builder for Python handlers
#[pyclass]
pub struct ResponseView {
    #[pyo3(get, set)]
    pub status_code: u16,
    pub headers: HashMap<String, String>,
    pub body: Vec<u8>,
}

#[pymethods]
impl ResponseView {
    #[new]
    pub fn new(status_code: Option<u16>) -> Self {
        ResponseView {
            status_code: status_code.unwrap_or(200),
            headers: HashMap::new(),
            body: Vec::new(),
        }
    }

    /// Set a header
    pub fn set_header(&mut self, name: String, value: String) {
        self.headers.insert(name, value);
    }

    /// Get a header value
    pub fn get_header(&self, name: &str) -> Option<String> {
        self.headers.get(name).cloned()
    }

    /// Set response body from string
    pub fn set_body(&mut self, body: String) {
        self.body = body.into_bytes();
    }

    /// Set response body from bytes
    pub fn set_body_bytes(&mut self, body: Vec<u8>) {
        self.body = body;
    }

    /// Get response body as string
    pub fn get_body_str(&self) -> PyResult<String> {
        String::from_utf8(self.body.clone())
            .map_err(|e| pyo3::exceptions::PyUnicodeDecodeError::new_err(e.to_string()))
    }

    /// Get response body as bytes
    pub fn get_body_bytes(&self) -> Vec<u8> {
        self.body.clone()
    }

    /// Set JSON response with automatic content-type header
    pub fn json(&mut self, data: String) -> PyResult<()> {
        self.set_header("content-type".to_string(), "application/json".to_string());
        self.set_body(data);
        Ok(())
    }

    /// Set text response with automatic content-type header
    pub fn text(&mut self, data: String) -> PyResult<()> {
        self.set_header("content-type".to_string(), "text/plain; charset=utf-8".to_string());
        self.set_body(data);
        Ok(())
    }
}
