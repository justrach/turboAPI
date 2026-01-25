//! SIMD-accelerated JSON serialization for Python objects.
//!
//! Walks PyO3 Python objects (dict, list, str, int, float, bool, None) and
//! serializes them directly to JSON bytes in Rust — eliminating the Python
//! `json.dumps` FFI crossing entirely.
//!
//! Uses `memchr` for fast string escape detection, `itoa`/`ryu` for fast
//! number formatting.

use memchr::memchr3;
use pyo3::prelude::*;
use pyo3::types::{PyBool, PyDict, PyFloat, PyInt, PyList, PyNone, PyString, PyTuple};

/// Pre-allocated buffer capacity for typical JSON responses (512 bytes).
const INITIAL_CAPACITY: usize = 512;

/// Serialize a Python object to JSON bytes entirely in Rust.
///
/// Handles: dict, list, tuple, str, int, float, bool, None.
/// Falls back to Python str() for unknown types.
///
/// Returns the JSON as a UTF-8 String (ready for HTTP response body).
pub fn serialize_pyobject_to_json(py: Python, obj: &Bound<'_, PyAny>) -> PyResult<String> {
    let mut buf = Vec::with_capacity(INITIAL_CAPACITY);
    write_value(py, obj, &mut buf)?;
    // SAFETY: We only write valid UTF-8 (ASCII JSON + escaped Unicode)
    Ok(unsafe { String::from_utf8_unchecked(buf) })
}

/// Serialize a Python object to JSON bytes (returns Vec<u8>).
pub fn serialize_pyobject_to_bytes(py: Python, obj: &Bound<'_, PyAny>) -> PyResult<Vec<u8>> {
    let mut buf = Vec::with_capacity(INITIAL_CAPACITY);
    write_value(py, obj, &mut buf)?;
    Ok(buf)
}

/// Write a Python value as JSON into the buffer.
#[inline]
fn write_value(py: Python, obj: &Bound<'_, PyAny>, buf: &mut Vec<u8>) -> PyResult<()> {
    // Check types in order of likelihood for web API responses:
    // dict > str > int > list > bool > float > None > tuple > unknown

    // Dict (most common for API responses)
    if let Ok(dict) = obj.downcast::<PyDict>() {
        return write_dict(py, dict, buf);
    }

    // String
    if let Ok(s) = obj.downcast::<PyString>() {
        return write_string(s, buf);
    }

    // Integer (check before bool since bool is subclass of int in Python)
    // But we need to check bool FIRST because isinstance(True, int) is True in Python
    if let Ok(b) = obj.downcast::<PyBool>() {
        if b.is_true() {
            buf.extend_from_slice(b"true");
        } else {
            buf.extend_from_slice(b"false");
        }
        return Ok(());
    }

    if let Ok(i) = obj.downcast::<PyInt>() {
        return write_int(i, buf);
    }

    // List
    if let Ok(list) = obj.downcast::<PyList>() {
        return write_list(py, list, buf);
    }

    // Float
    if let Ok(f) = obj.downcast::<PyFloat>() {
        return write_float(f, buf);
    }

    // None
    if obj.downcast::<PyNone>().is_ok() || obj.is_none() {
        buf.extend_from_slice(b"null");
        return Ok(());
    }

    // Tuple (treat as array)
    if let Ok(tuple) = obj.downcast::<PyTuple>() {
        return write_tuple(py, tuple, buf);
    }

    // Fallback: try to convert to a serializable Python representation

    // Check for Response objects (JSONResponse, HTMLResponse, etc.)
    // These have a 'body' attribute that contains the serialized content
    if let Ok(body_attr) = obj.getattr("body") {
        if let Ok(status_attr) = obj.getattr("status_code") {
            // This is a Response object - extract and serialize the body content
            if let Ok(body_bytes) = body_attr.extract::<Vec<u8>>() {
                // Try to parse body as JSON first
                if let Ok(json_str) = String::from_utf8(body_bytes.clone()) {
                    // If it's valid JSON, use it directly
                    if json_str.starts_with('{')
                        || json_str.starts_with('[')
                        || json_str.starts_with('"')
                    {
                        buf.extend_from_slice(json_str.as_bytes());
                        return Ok(());
                    }
                    // Otherwise treat as string
                    buf.push(b'"');
                    for byte in json_str.bytes() {
                        match byte {
                            b'"' => buf.extend_from_slice(b"\\\""),
                            b'\\' => buf.extend_from_slice(b"\\\\"),
                            b'\n' => buf.extend_from_slice(b"\\n"),
                            b'\r' => buf.extend_from_slice(b"\\r"),
                            b'\t' => buf.extend_from_slice(b"\\t"),
                            b if b < 32 => {
                                buf.extend_from_slice(format!("\\u{:04x}", b).as_bytes());
                            }
                            _ => buf.push(byte),
                        }
                    }
                    buf.push(b'"');
                    return Ok(());
                }
            }
        }
    }

    // Check if it has a model_dump() method (dhi/Pydantic models)
    if let Ok(dump_method) = obj.getattr("model_dump") {
        if let Ok(dumped) = dump_method.call0() {
            return write_value(py, &dumped, buf);
        }
    }

    // Last resort: convert to string
    let s = obj.str()?;
    write_string(&s, buf)
}

/// Write a Python dict as a JSON object.
#[inline]
fn write_dict(py: Python, dict: &Bound<'_, PyDict>, buf: &mut Vec<u8>) -> PyResult<()> {
    buf.push(b'{');
    let mut first = true;

    for (key, value) in dict.iter() {
        if !first {
            buf.push(b',');
        }
        first = false;

        // Keys must be strings in JSON
        if let Ok(key_str) = key.downcast::<PyString>() {
            write_string(key_str, buf)?;
        } else {
            // Convert non-string key to string
            let key_s = key.str()?;
            write_string(&key_s, buf)?;
        }

        buf.push(b':');
        write_value(py, &value, buf)?;
    }

    buf.push(b'}');
    Ok(())
}

/// Write a Python list as a JSON array.
#[inline]
fn write_list(py: Python, list: &Bound<'_, PyList>, buf: &mut Vec<u8>) -> PyResult<()> {
    buf.push(b'[');
    let len = list.len();

    for i in 0..len {
        if i > 0 {
            buf.push(b',');
        }
        let item = list.get_item(i)?;
        write_value(py, &item, buf)?;
    }

    buf.push(b']');
    Ok(())
}

/// Write a Python tuple as a JSON array.
#[inline]
fn write_tuple(py: Python, tuple: &Bound<'_, PyTuple>, buf: &mut Vec<u8>) -> PyResult<()> {
    buf.push(b'[');
    let len = tuple.len();

    for i in 0..len {
        if i > 0 {
            buf.push(b',');
        }
        let item = tuple.get_item(i)?;
        write_value(py, &item, buf)?;
    }

    buf.push(b']');
    Ok(())
}

/// Write a Python string as a JSON string with proper escaping.
/// Uses `memchr` for SIMD-accelerated scan for characters needing escape.
#[inline]
fn write_string(s: &Bound<'_, PyString>, buf: &mut Vec<u8>) -> PyResult<()> {
    let rust_str = s.to_cow()?;
    write_str_escaped(rust_str.as_ref(), buf);
    Ok(())
}

/// Write a Rust &str as a JSON-escaped string.
/// Uses SIMD-accelerated memchr to find escape characters quickly.
#[inline(always)]
fn write_str_escaped(s: &str, buf: &mut Vec<u8>) {
    buf.push(b'"');

    let bytes = s.as_bytes();
    let mut start = 0;

    while start < bytes.len() {
        // SIMD-accelerated scan for characters that need escaping: " \ and control chars
        // memchr3 uses SIMD to scan for 3 bytes simultaneously
        match memchr3(b'"', b'\\', b'\n', &bytes[start..]) {
            Some(pos) => {
                let abs_pos = start + pos;
                // Write everything before the escape character
                buf.extend_from_slice(&bytes[start..abs_pos]);
                // Write the escape sequence
                match bytes[abs_pos] {
                    b'"' => buf.extend_from_slice(b"\\\""),
                    b'\\' => buf.extend_from_slice(b"\\\\"),
                    b'\n' => buf.extend_from_slice(b"\\n"),
                    _ => unreachable!(),
                }
                start = abs_pos + 1;
            }
            None => {
                // No more special characters found by memchr3.
                // But we still need to check for other control characters: \r, \t, etc.
                let remaining = &bytes[start..];
                let mut i = 0;
                while i < remaining.len() {
                    let b = remaining[i];
                    if b < 0x20 {
                        // Write everything before this control char
                        buf.extend_from_slice(&remaining[..i]);
                        // Write escape
                        match b {
                            b'\r' => buf.extend_from_slice(b"\\r"),
                            b'\t' => buf.extend_from_slice(b"\\t"),
                            0x08 => buf.extend_from_slice(b"\\b"),
                            0x0C => buf.extend_from_slice(b"\\f"),
                            _ => {
                                // \u00XX format
                                buf.extend_from_slice(b"\\u00");
                                let hi = b >> 4;
                                let lo = b & 0x0F;
                                buf.push(if hi < 10 { b'0' + hi } else { b'a' + hi - 10 });
                                buf.push(if lo < 10 { b'0' + lo } else { b'a' + lo - 10 });
                            }
                        }
                        // Continue scanning the rest
                        let new_remaining = &remaining[i + 1..];
                        start += i + 1;
                        // Recurse on remainder (tail-call style)
                        write_str_remaining(new_remaining, buf);
                        buf.push(b'"');
                        return;
                    }
                    i += 1;
                }
                // No control chars found, write the rest
                buf.extend_from_slice(remaining);
                break;
            }
        }
    }

    buf.push(b'"');
}

/// Helper to write remaining string bytes after a control character escape.
#[inline]
fn write_str_remaining(bytes: &[u8], buf: &mut Vec<u8>) {
    let mut i = 0;
    while i < bytes.len() {
        let b = bytes[i];
        if b == b'"' {
            buf.extend_from_slice(&bytes[..i]);
            buf.extend_from_slice(b"\\\"");
            write_str_remaining(&bytes[i + 1..], buf);
            return;
        } else if b == b'\\' {
            buf.extend_from_slice(&bytes[..i]);
            buf.extend_from_slice(b"\\\\");
            write_str_remaining(&bytes[i + 1..], buf);
            return;
        } else if b == b'\n' {
            buf.extend_from_slice(&bytes[..i]);
            buf.extend_from_slice(b"\\n");
            write_str_remaining(&bytes[i + 1..], buf);
            return;
        } else if b == b'\r' {
            buf.extend_from_slice(&bytes[..i]);
            buf.extend_from_slice(b"\\r");
            write_str_remaining(&bytes[i + 1..], buf);
            return;
        } else if b == b'\t' {
            buf.extend_from_slice(&bytes[..i]);
            buf.extend_from_slice(b"\\t");
            write_str_remaining(&bytes[i + 1..], buf);
            return;
        } else if b < 0x20 {
            buf.extend_from_slice(&bytes[..i]);
            buf.extend_from_slice(b"\\u00");
            let hi = b >> 4;
            let lo = b & 0x0F;
            buf.push(if hi < 10 { b'0' + hi } else { b'a' + hi - 10 });
            buf.push(if lo < 10 { b'0' + lo } else { b'a' + lo - 10 });
            write_str_remaining(&bytes[i + 1..], buf);
            return;
        }
        i += 1;
    }
    // No special chars, write all
    buf.extend_from_slice(bytes);
}

/// Write a Python int as a JSON number.
/// Uses `itoa` for fast integer-to-string conversion.
#[inline]
fn write_int(i: &Bound<'_, PyInt>, buf: &mut Vec<u8>) -> PyResult<()> {
    // Try i64 first (most common), then fall back to big int string
    if let Ok(val) = i.extract::<i64>() {
        let mut itoa_buf = itoa::Buffer::new();
        buf.extend_from_slice(itoa_buf.format(val).as_bytes());
    } else if let Ok(val) = i.extract::<u64>() {
        let mut itoa_buf = itoa::Buffer::new();
        buf.extend_from_slice(itoa_buf.format(val).as_bytes());
    } else {
        // Very large integer - use Python's str representation
        let s = i.str()?;
        let rust_str = s.to_cow()?;
        buf.extend_from_slice(rust_str.as_bytes());
    }
    Ok(())
}

/// Write a Python float as a JSON number.
/// Uses `ryu` for fast float-to-string conversion.
#[inline]
fn write_float(f: &Bound<'_, PyFloat>, buf: &mut Vec<u8>) -> PyResult<()> {
    let val = f.extract::<f64>()?;

    if val.is_nan() || val.is_infinite() {
        // JSON doesn't support NaN/Infinity, use null
        buf.extend_from_slice(b"null");
    } else {
        let mut ryu_buf = ryu::Buffer::new();
        let formatted = ryu_buf.format(val);
        buf.extend_from_slice(formatted.as_bytes());
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_string_escaping() {
        let mut buf = Vec::new();
        write_str_escaped("hello world", &mut buf);
        assert_eq!(buf, b"\"hello world\"");

        buf.clear();
        write_str_escaped("hello \"world\"", &mut buf);
        assert_eq!(buf, b"\"hello \\\"world\\\"\"");

        buf.clear();
        write_str_escaped("line1\nline2", &mut buf);
        assert_eq!(buf, b"\"line1\\nline2\"");

        buf.clear();
        write_str_escaped("path\\to\\file", &mut buf);
        assert_eq!(buf, b"\"path\\\\to\\\\file\"");
    }
}
