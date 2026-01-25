//! SIMD-accelerated request parsing for TurboAPI.
//!
//! Moves query string, path parameter, and JSON body parsing from Python
//! into Rust, using `memchr` for SIMD-accelerated delimiter scanning.
//! This eliminates the Python enhanced handler wrapper overhead for simple routes.

use memchr::memchr;
use pyo3::prelude::*;
use pyo3::types::PyDict;
use std::collections::HashMap;

/// Parse a URL query string into key-value pairs using SIMD-accelerated scanning.
///
/// Example: "q=test&limit=20&page=1" -> {"q": "test", "limit": "20", "page": "1"}
///
/// Uses `memchr` to find `&` delimiters, then `=` within each segment.
#[inline]
pub fn parse_query_string_simd(query: &str) -> HashMap<&str, &str> {
    if query.is_empty() {
        return HashMap::new();
    }

    let mut params = HashMap::with_capacity(4); // Most queries have <4 params
    let bytes = query.as_bytes();
    let mut start = 0;

    loop {
        // Find next & delimiter using SIMD
        let end = match memchr(b'&', &bytes[start..]) {
            Some(pos) => start + pos,
            None => bytes.len(), // Last segment
        };

        // Parse key=value within this segment
        let segment = &query[start..end];
        if let Some(eq_pos) = memchr(b'=', segment.as_bytes()) {
            let key = &segment[..eq_pos];
            let value = &segment[eq_pos + 1..];
            if !key.is_empty() {
                params.insert(key, value);
            }
        } else if !segment.is_empty() {
            // Key without value (e.g., "flag")
            params.insert(segment, "");
        }

        if end >= bytes.len() {
            break;
        }
        start = end + 1;
    }

    params
}

/// Parse query string and set values into a PyDict, with type coercion
/// for parameters that match handler signature types.
///
/// `param_types` maps param_name -> type_hint ("int", "float", "bool", "str")
#[inline]
pub fn parse_query_into_pydict<'py>(
    py: Python<'py>,
    query: &str,
    kwargs: &Bound<'py, PyDict>,
    param_types: &HashMap<String, String>,
) -> PyResult<()> {
    if query.is_empty() {
        return Ok(());
    }

    let bytes = query.as_bytes();
    let mut start = 0;

    loop {
        let end = match memchr(b'&', &bytes[start..]) {
            Some(pos) => start + pos,
            None => bytes.len(),
        };

        let segment = &query[start..end];
        if let Some(eq_pos) = memchr(b'=', segment.as_bytes()) {
            let key = &segment[..eq_pos];
            let value = &segment[eq_pos + 1..];

            if !key.is_empty() {
                // URL-decode value (basic: + -> space, %XX -> byte)
                let decoded = url_decode_fast(value);

                // Type coerce based on handler signature
                if let Some(type_hint) = param_types.get(key) {
                    match type_hint.as_str() {
                        "int" => {
                            if let Ok(v) = decoded.parse::<i64>() {
                                kwargs.set_item(key, v)?;
                            } else {
                                kwargs.set_item(key, &*decoded)?;
                            }
                        }
                        "float" => {
                            if let Ok(v) = decoded.parse::<f64>() {
                                kwargs.set_item(key, v)?;
                            } else {
                                kwargs.set_item(key, &*decoded)?;
                            }
                        }
                        "bool" => {
                            let b = matches!(decoded.as_ref(), "true" | "1" | "yes" | "on");
                            kwargs.set_item(key, b)?;
                        }
                        _ => {
                            // str or unknown: pass as string
                            kwargs.set_item(key, &*decoded)?;
                        }
                    }
                } else {
                    // No type info, pass as string
                    kwargs.set_item(key, &*decoded)?;
                }
            }
        }

        if end >= bytes.len() {
            break;
        }
        start = end + 1;
    }

    Ok(())
}

/// Extract path parameters from a URL path given a route pattern.
///
/// Pattern: "/users/{user_id}/posts/{post_id}"
/// Path:    "/users/123/posts/456"
/// Result:  {"user_id": "123", "post_id": "456"}
///
/// Uses direct byte comparison with SIMD-friendly scanning.
#[inline]
pub fn extract_path_params<'a>(pattern: &'a str, path: &'a str) -> HashMap<&'a str, &'a str> {
    let mut params = HashMap::with_capacity(2);

    let pattern_parts: Vec<&str> = pattern.split('/').collect();
    let path_parts: Vec<&str> = path.split('/').collect();

    if pattern_parts.len() != path_parts.len() {
        return params;
    }

    for (pat, val) in pattern_parts.iter().zip(path_parts.iter()) {
        if pat.starts_with('{') && pat.ends_with('}') {
            let param_name = &pat[1..pat.len() - 1];
            params.insert(param_name, *val);
        }
    }

    params
}

/// Set path parameters into a PyDict with type coercion.
#[inline]
pub fn set_path_params_into_pydict<'py>(
    _py: Python<'py>,
    pattern: &str,
    path: &str,
    kwargs: &Bound<'py, PyDict>,
    param_types: &HashMap<String, String>,
) -> PyResult<()> {
    let pattern_parts: Vec<&str> = pattern.split('/').collect();
    let path_parts: Vec<&str> = path.split('/').collect();

    if pattern_parts.len() != path_parts.len() {
        return Ok(());
    }

    for (pat, val) in pattern_parts.iter().zip(path_parts.iter()) {
        if pat.starts_with('{') && pat.ends_with('}') {
            let param_name = &pat[1..pat.len() - 1];

            if let Some(type_hint) = param_types.get(param_name) {
                match type_hint.as_str() {
                    "int" => {
                        if let Ok(v) = val.parse::<i64>() {
                            kwargs.set_item(param_name, v)?;
                        } else {
                            kwargs.set_item(param_name, *val)?;
                        }
                    }
                    "float" => {
                        if let Ok(v) = val.parse::<f64>() {
                            kwargs.set_item(param_name, v)?;
                        } else {
                            kwargs.set_item(param_name, *val)?;
                        }
                    }
                    _ => {
                        kwargs.set_item(param_name, *val)?;
                    }
                }
            } else {
                kwargs.set_item(param_name, *val)?;
            }
        }
    }

    Ok(())
}

/// Parse a JSON body using simd-json and set fields into a PyDict.
///
/// For simple JSON objects like {"name": "Alice", "age": 30},
/// this avoids the Python json.loads + field extraction overhead.
#[inline]
pub fn parse_json_body_into_pydict<'py>(
    py: Python<'py>,
    body: &[u8],
    kwargs: &Bound<'py, PyDict>,
    param_types: &HashMap<String, String>,
) -> PyResult<bool> {
    if body.is_empty() {
        return Ok(false);
    }

    // Use simd-json for fast parsing
    let mut body_copy = body.to_vec();
    let parsed = match simd_json::to_borrowed_value(&mut body_copy) {
        Ok(val) => val,
        Err(_) => return Ok(false), // Not valid JSON, let Python handle it
    };

    // Only handle object (dict) bodies for field extraction
    if let simd_json::BorrowedValue::Object(map) = parsed {
        for (key, value) in map.iter() {
            let key_str = key.as_ref();

            // Only set params that match the handler signature
            if param_types.contains_key(key_str) || param_types.is_empty() {
                match value {
                    simd_json::BorrowedValue::String(s) => {
                        kwargs.set_item(key_str, s.as_ref())?;
                    }
                    simd_json::BorrowedValue::Static(simd_json::StaticNode::I64(n)) => {
                        kwargs.set_item(key_str, *n)?;
                    }
                    simd_json::BorrowedValue::Static(simd_json::StaticNode::U64(n)) => {
                        kwargs.set_item(key_str, *n)?;
                    }
                    simd_json::BorrowedValue::Static(simd_json::StaticNode::F64(n)) => {
                        kwargs.set_item(key_str, *n)?;
                    }
                    simd_json::BorrowedValue::Static(simd_json::StaticNode::Bool(b)) => {
                        kwargs.set_item(key_str, *b)?;
                    }
                    simd_json::BorrowedValue::Static(simd_json::StaticNode::Null) => {
                        kwargs.set_item(key_str, py.None())?;
                    }
                    simd_json::BorrowedValue::Array(arr) => {
                        // Convert to Python list
                        let py_list = pyo3::types::PyList::empty(py);
                        for item in arr.iter() {
                            append_simd_value_to_list(py, item, &py_list)?;
                        }
                        kwargs.set_item(key_str, py_list)?;
                    }
                    simd_json::BorrowedValue::Object(_) => {
                        // Nested object - convert to Python dict
                        let nested = PyDict::new(py);
                        set_simd_object_into_dict(py, value, &nested)?;
                        kwargs.set_item(key_str, nested)?;
                    }
                }
            }
        }
        Ok(true)
    } else {
        Ok(false) // Not an object, let Python handle arrays etc.
    }
}

/// Convert a simd-json value and append to a Python list.
fn append_simd_value_to_list<'py>(
    py: Python<'py>,
    value: &simd_json::BorrowedValue,
    list: &Bound<'py, pyo3::types::PyList>,
) -> PyResult<()> {
    match value {
        simd_json::BorrowedValue::String(s) => list.append(s.as_ref())?,
        simd_json::BorrowedValue::Static(simd_json::StaticNode::I64(n)) => list.append(*n)?,
        simd_json::BorrowedValue::Static(simd_json::StaticNode::U64(n)) => list.append(*n)?,
        simd_json::BorrowedValue::Static(simd_json::StaticNode::F64(n)) => list.append(*n)?,
        simd_json::BorrowedValue::Static(simd_json::StaticNode::Bool(b)) => list.append(*b)?,
        simd_json::BorrowedValue::Static(simd_json::StaticNode::Null) => list.append(py.None())?,
        simd_json::BorrowedValue::Array(arr) => {
            let nested_list = pyo3::types::PyList::empty(py);
            for item in arr.iter() {
                append_simd_value_to_list(py, item, &nested_list)?;
            }
            list.append(nested_list)?;
        }
        simd_json::BorrowedValue::Object(_) => {
            let dict = PyDict::new(py);
            set_simd_object_into_dict(py, value, &dict)?;
            list.append(dict)?;
        }
    }
    Ok(())
}

/// Set simd-json object fields into a PyDict recursively.
fn set_simd_object_into_dict<'py>(
    py: Python<'py>,
    value: &simd_json::BorrowedValue,
    dict: &Bound<'py, PyDict>,
) -> PyResult<()> {
    if let simd_json::BorrowedValue::Object(map) = value {
        for (key, val) in map.iter() {
            match val {
                simd_json::BorrowedValue::String(s) => dict.set_item(key.as_ref(), s.as_ref())?,
                simd_json::BorrowedValue::Static(simd_json::StaticNode::I64(n)) => {
                    dict.set_item(key.as_ref(), *n)?
                }
                simd_json::BorrowedValue::Static(simd_json::StaticNode::U64(n)) => {
                    dict.set_item(key.as_ref(), *n)?
                }
                simd_json::BorrowedValue::Static(simd_json::StaticNode::F64(n)) => {
                    dict.set_item(key.as_ref(), *n)?
                }
                simd_json::BorrowedValue::Static(simd_json::StaticNode::Bool(b)) => {
                    dict.set_item(key.as_ref(), *b)?
                }
                simd_json::BorrowedValue::Static(simd_json::StaticNode::Null) => {
                    dict.set_item(key.as_ref(), py.None())?
                }
                simd_json::BorrowedValue::Array(arr) => {
                    let list = pyo3::types::PyList::empty(py);
                    for item in arr.iter() {
                        append_simd_value_to_list(py, item, &list)?;
                    }
                    dict.set_item(key.as_ref(), list)?;
                }
                simd_json::BorrowedValue::Object(_) => {
                    let nested = PyDict::new(py);
                    set_simd_object_into_dict(py, val, &nested)?;
                    dict.set_item(key.as_ref(), nested)?;
                }
            }
        }
    }
    Ok(())
}

/// Parse JSON body using simd-json and return as a Python dict.
/// This is used for model validation where we need the full dict.
#[inline]
pub fn parse_json_to_pydict<'py>(py: Python<'py>, body: &[u8]) -> PyResult<Bound<'py, PyDict>> {
    if body.is_empty() {
        return Ok(PyDict::new(py));
    }

    // Use simd-json for fast parsing
    let mut body_copy = body.to_vec();
    let parsed = simd_json::to_borrowed_value(&mut body_copy)
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(format!("JSON parse error: {}", e)))?;

    let dict = PyDict::new(py);

    // Only handle object (dict) bodies
    if let simd_json::BorrowedValue::Object(map) = parsed {
        for (key, value) in map.iter() {
            set_simd_value_into_dict(py, key.as_ref(), value, &dict)?;
        }
    } else {
        return Err(pyo3::exceptions::PyValueError::new_err(
            "Expected JSON object",
        ));
    }

    Ok(dict)
}

/// Set a single simd-json value into a PyDict at the given key.
fn set_simd_value_into_dict<'py>(
    py: Python<'py>,
    key: &str,
    value: &simd_json::BorrowedValue,
    dict: &Bound<'py, PyDict>,
) -> PyResult<()> {
    match value {
        simd_json::BorrowedValue::String(s) => dict.set_item(key, s.as_ref())?,
        simd_json::BorrowedValue::Static(simd_json::StaticNode::I64(n)) => {
            dict.set_item(key, *n)?
        }
        simd_json::BorrowedValue::Static(simd_json::StaticNode::U64(n)) => {
            dict.set_item(key, *n)?
        }
        simd_json::BorrowedValue::Static(simd_json::StaticNode::F64(n)) => {
            dict.set_item(key, *n)?
        }
        simd_json::BorrowedValue::Static(simd_json::StaticNode::Bool(b)) => {
            dict.set_item(key, *b)?
        }
        simd_json::BorrowedValue::Static(simd_json::StaticNode::Null) => {
            dict.set_item(key, py.None())?
        }
        simd_json::BorrowedValue::Array(arr) => {
            let list = pyo3::types::PyList::empty(py);
            for item in arr.iter() {
                append_simd_value_to_list(py, item, &list)?;
            }
            dict.set_item(key, list)?;
        }
        simd_json::BorrowedValue::Object(_) => {
            let nested = PyDict::new(py);
            set_simd_object_into_dict(py, value, &nested)?;
            dict.set_item(key, nested)?;
        }
    }
    Ok(())
}

/// Fast URL decoding: handles %XX and + -> space.
/// Most API parameters don't need decoding, so we fast-path the common case.
#[inline]
fn url_decode_fast(s: &str) -> std::borrow::Cow<str> {
    // Quick check: if no % or +, return as-is (zero-copy)
    let bytes = s.as_bytes();
    if memchr(b'%', bytes).is_none() && memchr(b'+', bytes).is_none() {
        return std::borrow::Cow::Borrowed(s);
    }

    // Need to decode
    let mut result = Vec::with_capacity(bytes.len());
    let mut i = 0;
    while i < bytes.len() {
        match bytes[i] {
            b'+' => {
                result.push(b' ');
                i += 1;
            }
            b'%' if i + 2 < bytes.len() => {
                let hi = hex_val(bytes[i + 1]);
                let lo = hex_val(bytes[i + 2]);
                if let (Some(h), Some(l)) = (hi, lo) {
                    result.push(h * 16 + l);
                    i += 3;
                } else {
                    result.push(b'%');
                    i += 1;
                }
            }
            b => {
                result.push(b);
                i += 1;
            }
        }
    }

    std::borrow::Cow::Owned(String::from_utf8_lossy(&result).into_owned())
}

#[inline]
fn hex_val(b: u8) -> Option<u8> {
    match b {
        b'0'..=b'9' => Some(b - b'0'),
        b'a'..=b'f' => Some(b - b'a' + 10),
        b'A'..=b'F' => Some(b - b'A' + 10),
        _ => None,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_parse_query_string() {
        let params = parse_query_string_simd("q=test&limit=20&page=1");
        assert_eq!(params.get("q"), Some(&"test"));
        assert_eq!(params.get("limit"), Some(&"20"));
        assert_eq!(params.get("page"), Some(&"1"));
    }

    #[test]
    fn test_parse_empty_query() {
        let params = parse_query_string_simd("");
        assert!(params.is_empty());
    }

    #[test]
    fn test_extract_path_params() {
        let params = extract_path_params("/users/{user_id}", "/users/123");
        assert_eq!(params.get("user_id"), Some(&"123"));
    }

    #[test]
    fn test_extract_multiple_path_params() {
        let params = extract_path_params("/users/{user_id}/posts/{post_id}", "/users/42/posts/99");
        assert_eq!(params.get("user_id"), Some(&"42"));
        assert_eq!(params.get("post_id"), Some(&"99"));
    }

    #[test]
    fn test_url_decode() {
        assert_eq!(url_decode_fast("hello+world"), "hello world");
        assert_eq!(url_decode_fast("hello%20world"), "hello world");
        assert_eq!(url_decode_fast("no_encoding"), "no_encoding");
    }
}
