# TODO for TurboAPI v0.4.15

## ✅ Completed in v0.4.14
- [x] Query parameter parsing
- [x] Header parsing  
- [x] Combined query + headers support
- [x] Comprehensive tests for query params and headers

## 🚧 In Progress (Blocked)

### Path Parameter Extraction
**Status**: Partially implemented, needs Rust router updates

**What's Done**:
- Python parser implemented (`PathParamParser.extract_path_params`)
- Route pattern parsing works (e.g., `/users/{user_id}`)
- Regex-based extraction functional

**What's Needed**:
- Rust router needs to support parameterized routes
- Currently routes are registered with exact paths (e.g., `/users/{user_id}`)
- Router needs to match `/users/123` against pattern `/users/{user_id}`
- Requires updating `RadixRouter` in `src/router.rs`

**Implementation Plan**:
1. Update `RadixRouter::add_route()` to detect path parameters
2. Store route patterns separately from exact matches
3. Implement pattern matching in `RadixRouter::find_route()`
4. Extract path params and pass to Python handler
5. Update tests to verify path param extraction

**Estimated Effort**: 3-4 hours

---

## ⏳ TODO for v0.4.15

### 1. Form Data Support
**Priority**: High  
**Complexity**: Medium

**Requirements**:
- Parse `application/x-www-form-urlencoded` content type
- Parse `multipart/form-data` content type
- Extract form fields and pass to handler
- Support both sync and async handlers

**Implementation**:
- Add `FormDataParser` class in `request_handler.py`
- Update Rust server to pass content-type header
- Parse form data based on content-type
- Add comprehensive tests

**Estimated Effort**: 2-3 hours

---

### 2. File Upload Support
**Priority**: High  
**Complexity**: High

**Requirements**:
- Handle `multipart/form-data` with files
- Stream large files efficiently
- Provide `UploadFile` class (FastAPI-compatible)
- Support multiple file uploads
- Validate file types and sizes

**Implementation**:
- Create `UploadFile` class with file-like interface
- Implement streaming file parser
- Add file validation (size, type, extension)
- Store files temporarily or in memory
- Add comprehensive tests with various file types

**Estimated Effort**: 3-4 hours

---

### 3. WebSocket Support
**Priority**: Medium  
**Complexity**: High

**Requirements**:
- WebSocket handshake handling
- Bidirectional message passing
- Connection lifecycle management
- Support for text and binary messages
- FastAPI-compatible `WebSocket` class

**Implementation**:
- Add WebSocket support to Rust HTTP server
- Implement WebSocket protocol handling
- Create Python `WebSocket` class
- Add `@app.websocket()` decorator
- Support async message handlers
- Add comprehensive tests

**Estimated Effort**: 4-5 hours

---

## 📋 Additional Features (Lower Priority)

### 4. Cookie Support
- Parse cookies from `Cookie` header
- Set cookies in response
- Support for secure, httponly, samesite attributes

### 5. Response Models
- Validate response data against Satya models
- Automatic serialization
- OpenAPI schema generation

### 6. Dependency Injection
- `Depends()` function for reusable dependencies
- Nested dependencies
- Caching of dependency results

### 7. Background Tasks
- `BackgroundTasks` class
- Execute tasks after response sent
- Support for async background tasks

### 8. Static Files
- Serve static files from directory
- MIME type detection
- Caching headers

### 9. CORS Middleware
- Full CORS support
- Preflight request handling
- Configurable origins, methods, headers

### 10. OpenAPI Documentation
- Automatic OpenAPI schema generation
- Swagger UI integration
- ReDoc integration

---

## 🎯 v0.4.15 Goals

**Primary Goals**:
1. Complete path parameter extraction (Rust router updates)
2. Add form data support
3. Add file upload support

**Stretch Goals**:
4. Add WebSocket support
5. Add cookie support

**Success Criteria**:
- All tests passing
- FastAPI compatibility maintained
- Performance: 180K+ RPS maintained
- Documentation updated
- Examples provided

---

## 📝 Notes

### Performance Considerations
- All features must maintain 180K+ RPS performance
- Zero-copy where possible
- Minimize Python-Rust boundary crossings
- Use Rust for heavy lifting (parsing, validation)

### FastAPI Compatibility
- Maintain identical syntax to FastAPI
- Support same parameter types
- Same decorator patterns
- Same response formats

### Testing Requirements
- Comprehensive unit tests for each feature
- Integration tests for combined features
- Performance benchmarks
- Edge case testing

---

## 🔗 Related Issues

- Path parameters: Requires Rust router updates
- Form data: Depends on content-type header parsing
- File uploads: Depends on form data support
- WebSockets: Requires Rust HTTP server updates

---

**Last Updated**: 2025-10-12  
**Version**: v0.4.14 → v0.4.15  
**Estimated Total Effort**: 12-16 hours for all features
