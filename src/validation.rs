use pyo3::prelude::*;
use pyo3::types::PyDict;
use std::collections::HashMap;
use crate::RequestView;

/// Validation bridge between TurboAPI's Rust core and Satya's validation
#[pyclass]
pub struct ValidationBridge {
    /// Cache for Satya validators to avoid recreating them
    validator_cache: HashMap<String, PyObject>,
}

#[pymethods]
impl ValidationBridge {
    #[new]
    pub fn new() -> Self {
        ValidationBridge {
            validator_cache: HashMap::new(),
        }
    }

    /// Validate request data using a Satya model
    pub fn validate_request(
        &mut self,
        py: Python,
        model_class: PyObject,
        data: PyObject,
    ) -> PyResult<PyObject> {
        // Get or create validator for this model
        let model_name = model_class.getattr(py, "__name__")?.extract::<String>(py)?;
        
        let validator = if let Some(cached) = self.validator_cache.get(&model_name) {
            cached.clone_ref(py)
        } else {
            // Create new validator with batch processing enabled
            let validator = model_class.call_method0(py, "validator")?;
            validator.call_method1(py, "set_batch_size", (1000,))?;
            
            self.validator_cache.insert(model_name, validator.clone_ref(py));
            validator
        };

        // Validate the data
        let result = validator.call_method1(py, "validate", (data,))?;
        
        // Check if validation was successful
        let is_valid = result.getattr(py, "is_valid")?.extract::<bool>(py)?;
        
        if is_valid {
            Ok(result.getattr(py, "value")?)
        } else {
            let errors = result.getattr(py, "errors")?;
            Err(pyo3::exceptions::PyValueError::new_err(format!(
                "Validation failed: {:?}", 
                errors
            )))
        }
    }

    /// Validate a batch of requests for high throughput scenarios
    pub fn validate_batch(
        &mut self,
        py: Python,
        model_class: PyObject,
        data_list: PyObject,
    ) -> PyResult<PyObject> {
        let model_name = model_class.getattr(py, "__name__")?.extract::<String>(py)?;
        
        let validator = if let Some(cached) = self.validator_cache.get(&model_name) {
            cached.clone_ref(py)
        } else {
            let validator = model_class.call_method0(py, "validator")?;
            validator.call_method1(py, "set_batch_size", (1000,))?;
            
            self.validator_cache.insert(model_name, validator.clone_ref(py));
            validator
        };

        // Use Satya's batch validation for maximum performance
        validator.call_method1(py, "validate_batch", (data_list,))
    }

    /// Validate JSON bytes directly using Satya's streaming capabilities
    pub fn validate_json_bytes(
        &mut self,
        py: Python,
        model_class: PyObject,
        json_bytes: &[u8],
        streaming: bool,
    ) -> PyResult<PyObject> {
        let json_bytes_py = pyo3::types::PyBytes::new(py, json_bytes);
        
        if streaming {
            model_class.call_method1(py, "model_validate_json_bytes", (json_bytes_py, true))
        } else {
            model_class.call_method1(py, "model_validate_json_bytes", (json_bytes_py,))
        }
    }

    /// Validate JSON array bytes for bulk operations
    pub fn validate_json_array_bytes(
        &mut self,
        py: Python,
        model_class: PyObject,
        json_bytes: &[u8],
        streaming: bool,
    ) -> PyResult<PyObject> {
        let json_bytes_py = pyo3::types::PyBytes::new(py, json_bytes);
        
        if streaming {
            model_class.call_method1(py, "model_validate_json_array_bytes", (json_bytes_py, true))
        } else {
            model_class.call_method1(py, "model_validate_json_array_bytes", (json_bytes_py,))
        }
    }

    /// Clear validator cache (useful for development/testing)
    pub fn clear_cache(&mut self) {
        self.validator_cache.clear();
    }

    /// Get cache statistics
    pub fn cache_stats(&self) -> HashMap<String, usize> {
        let mut stats = HashMap::new();
        stats.insert("cached_validators".to_string(), self.validator_cache.len());
        stats
    }
}

/// Helper function to convert RequestView to Python dict for Satya validation
pub fn request_to_dict(py: Python, request: &RequestView) -> PyResult<PyObject> {
    let dict = PyDict::new(py);
    
    dict.set_item("method", request.method.clone())?;
    dict.set_item("path", request.path.clone())?;
    dict.set_item("query_string", request.query_string.clone())?;
    
    // Convert headers HashMap to Python dict
    let headers_dict = PyDict::new(py);
    for (key, value) in &request.headers {
        headers_dict.set_item(key, value)?;
    }
    dict.set_item("headers", headers_dict)?;
    
    // Add body as bytes
    let body_bytes = pyo3::types::PyBytes::new(py, &request.body);
    dict.set_item("body", body_bytes)?;
    
    Ok(dict.into())
}

/// Helper function to extract response data for Rust processing
pub fn extract_response_data(
    py: Python, 
    response: PyObject
) -> PyResult<(u16, HashMap<String, String>, Vec<u8>)> {
    let status_code: u16 = response.getattr(py, "status_code")?.extract(py)?;
    let headers: HashMap<String, String> = response.getattr(py, "headers")?.extract(py)?;
    
    // Handle different content types
    let content = response.getattr(py, "content")?;
    let body = if content.is_none(py) {
        Vec::new()
    } else {
        // Try to get as bytes first, then convert string to bytes
        if let Ok(bytes) = content.extract::<Vec<u8>>(py) {
            bytes
        } else if let Ok(string) = content.extract::<String>(py) {
            string.into_bytes()
        } else {
            // For complex objects, serialize to JSON
            let json_str = py.import("json")?.getattr("dumps")?.call1((content,))?;
            json_str.extract::<String>()?.into_bytes()
        }
    };
    
    Ok((status_code, headers, body))
}
