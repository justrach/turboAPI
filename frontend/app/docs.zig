const mer = @import("mer");
const h = mer.h;

pub const meta: mer.Meta = .{
    .title = "Docs",
    .description = "TurboAPI documentation — architecture, API reference, migration guide, and dhi validation.",
};

pub const prerender = true;

const page_node = page();

pub fn render(req: mer.Request) mer.Response {
    return mer.render(req.allocator, page_node);
}

fn page() h.Node {
    return h.div(.{ .class = "docs" }, .{
        h.div(.{ .class = "section-label" }, "Documentation"),
        h.h1(.{ .class = "section-title" }, "TurboAPI Docs"),
        h.p(.{}, "Drop-in FastAPI replacement with a Zig HTTP core. Change one import line — keep everything else."),

        // TOC
        h.div(.{ .class = "toc" }, .{
            h.div(.{ .class = "toc-label" }, "On this page"),
            h.a(.{ .href = "#install", .class = "toc-link" }, "Installation"),
            h.a(.{ .href = "#migration", .class = "toc-link" }, "Migrating from FastAPI"),
            h.a(.{ .href = "#architecture", .class = "toc-link" }, "Architecture"),
            h.a(.{ .href = "#routing", .class = "toc-link" }, "Routing"),
            h.a(.{ .href = "#validation", .class = "toc-link" }, "dhi validation"),
            h.a(.{ .href = "#middleware", .class = "toc-link" }, "Middleware & CORS"),
            h.a(.{ .href = "#errors", .class = "toc-link" }, "Error handling"),
            h.a(.{ .href = "#ffi", .class = "toc-link" }, "Native FFI handlers"),
            h.a(.{ .href = "#compat", .class = "toc-link" }, "Compatibility"),
        }),

        // Installation
        h.h2(.{ .id = "install" }, "Installation"),
        h.p(.{}, "Requires Python 3.13+. For maximum throughput use Python 3.14t (free-threaded build)."),
        h.pre(.{},
            \\pip install turboapi
        ),
        h.p(.{}, "Verify your install:"),
        h.pre(.{},
            \\python -c "import turboapi; print(turboapi.__version__)"
        ),
        h.div(.{ .class = "callout" }, .{
            h.span(.{ .class = "callout-icon" }, "⚡"),
            h.span(.{}, "For the full 7× speedup, use Python 3.14t (free-threaded). Performance on CPython 3.12+ is still 2–3× faster than vanilla FastAPI."),
        }),

        // Migration
        h.h2(.{ .id = "migration" }, "Migrating from FastAPI"),
        h.p(.{}, "In most cases, only the import line changes. Everything else — decorators, dependency injection, middleware, Pydantic models — stays the same."),
        h.pre(.{},
            \\- from fastapi import FastAPI, HTTPException, Depends
            \\+ from turboapi import TurboAPI, HTTPException, Depends
            \\
            \\  app = TurboAPI()   # identical API surface
            \\
            \\  @app.get("/items/{id}")
            \\  async def get_item(id: int):
            \\      return {"id": id}
        ),
        h.p(.{}, "Run with uvicorn as normal:"),
        h.pre(.{},
            \\uvicorn main:app --host 0.0.0.0 --port 8000
        ),

        // Architecture
        h.h2(.{ .id = "architecture" }, "Architecture"),
        h.p(.{}, "TurboAPI replaces the Python HTTP/ASGI layer with a Zig-native server. Your Python code never touches the network stack."),
        h.pre(.{},
            \\Request
            \\  └── Zig TCP listener (8-thread pool)
            \\        └── Zig HTTP parser (zero-copy)
            \\              └── Zig JSON → Python dict (no json.loads)
            \\                    └── dhi validation (native, pre-Python)
            \\                          └── Python route handler
            \\                                └── Zero-copy response pipeline
            \\                                      └── Response
        ),
        h.p(.{}, "Key properties:"),
        h.div(.{ .class = "prop-grid" }, .{
            h.div(.{ .class = "prop-card" }, .{
                h.div(.{ .class = "prop-title" }, "Zero-copy I/O"),
                h.div(.{ .class = "prop-desc" }, "Request bodies are parsed in Zig and handed to Python as memoryview slices — no intermediate string allocation."),
            }),
            h.div(.{ .class = "prop-card" }, .{
                h.div(.{ .class = "prop-title" }, "Free-threading"),
                h.div(.{ .class = "prop-desc" }, "On Python 3.14t the GIL is disabled. Zig threads and Python coroutines run truly concurrently."),
            }),
            h.div(.{ .class = "prop-card" }, .{
                h.div(.{ .class = "prop-title" }, "Native validation"),
                h.div(.{ .class = "prop-desc" }, "dhi constraints are compiled to Zig. Invalid requests are rejected before Python executes."),
            }),
            h.div(.{ .class = "prop-card" }, .{
                h.div(.{ .class = "prop-title" }, "Cold start ~5ms"),
                h.div(.{ .class = "prop-desc" }, "The Zig server binary loads in ~5ms. Python module import is the remaining startup time."),
            }),
        }),

        // Routing
        h.h2(.{ .id = "routing" }, "Routing"),
        h.p(.{}, "All standard FastAPI route decorators are supported. Path parameters, query strings, and request bodies work identically."),
        h.pre(.{},
            \\from turboapi import TurboAPI
            \\
            \\app = TurboAPI()
            \\
            \\@app.get("/")
            \\async def root():
            \\    return {"status": "ok"}
            \\
            \\@app.get("/items/{item_id}")
            \\async def get_item(item_id: int, q: str | None = None):
            \\    return {"item_id": item_id, "q": q}
            \\
            \\@app.post("/items")
            \\async def create_item(item: Item):
            \\    return item
            \\
            \\@app.put("/items/{item_id}")
            \\async def update_item(item_id: int, item: Item):
            \\    return {"item_id": item_id, **item.dict()}
            \\
            \\@app.delete("/items/{item_id}")
            \\async def delete_item(item_id: int):
            \\    return {"deleted": item_id}
        ),

        // dhi validation
        h.h2(.{ .id = "validation" }, "dhi — Zig-native validation"),
        h.p(.{}, "dhi provides Pydantic-compatible models backed by Zig validators. Constraints are checked in native code before your Python handler runs."),
        h.pre(.{},
            \\from dhi import Model, Str, Int, Float, EmailStr
            \\
            \\class Product(Model):
            \\    name:  Str(min_length=1, max_length=200)
            \\    price: Float(gt=0)
            \\    stock: Int(ge=0)
            \\    email: EmailStr
            \\
            \\@app.post("/products")
            \\async def create_product(product: Product):
            \\    # product is already validated — no extra checks needed
            \\    return product
        ),
        h.p(.{}, "Supported constraint types:"),
        h.div(.{ .class = "type-grid" }, .{
            h.div(.{ .class = "type-row" }, .{
                h.code(.{}, "Str"),
                h.span(.{}, "min_length, max_length, pattern, strip_whitespace"),
            }),
            h.div(.{ .class = "type-row" }, .{
                h.code(.{}, "Int"),
                h.span(.{}, "gt, ge, lt, le, multiple_of"),
            }),
            h.div(.{ .class = "type-row" }, .{
                h.code(.{}, "Float"),
                h.span(.{}, "gt, ge, lt, le, allow_inf_nan"),
            }),
            h.div(.{ .class = "type-row" }, .{
                h.code(.{}, "EmailStr"),
                h.span(.{}, "RFC 5321 validated in Zig"),
            }),
            h.div(.{ .class = "type-row" }, .{
                h.code(.{}, "List[T]"),
                h.span(.{}, "min_length, max_length, element constraints"),
            }),
        }),

        // Middleware
        h.h2(.{ .id = "middleware" }, "Middleware & CORS"),
        h.p(.{}, "Standard Starlette middleware works unchanged. CORS, GZip, and session middleware are all supported."),
        h.pre(.{},
            \\from turboapi import TurboAPI
            \\from turboapi.middleware.cors import CORSMiddleware
            \\
            \\app = TurboAPI()
            \\
            \\app.add_middleware(
            \\    CORSMiddleware,
            \\    allow_origins=["*"],
            \\    allow_methods=["*"],
            \\    allow_headers=["*"],
            \\)
        ),

        // Error handling
        h.h2(.{ .id = "errors" }, "Error handling"),
        h.p(.{}, "HTTPException and custom exception handlers work exactly as in FastAPI."),
        h.pre(.{},
            \\from turboapi import TurboAPI, HTTPException, Request
            \\from turboapi.responses import JSONResponse
            \\
            \\app = TurboAPI()
            \\
            \\@app.exception_handler(404)
            \\async def not_found(request: Request, exc: HTTPException):
            \\    return JSONResponse({"error": "not found"}, status_code=404)
            \\
            \\@app.get("/items/{id}")
            \\async def get_item(id: int):
            \\    if id < 0:
            \\        raise HTTPException(status_code=400, detail="id must be positive")
            \\    return {"id": id}
        ),

        // FFI
        h.h2(.{ .id = "ffi" }, "Native FFI handlers"),
        h.p(.{}, "For maximum performance, mount a compiled Zig or C shared library as a route handler. Zero Python overhead — requests are handled entirely in native code."),
        h.pre(.{},
            \\from turboapi import TurboAPI
            \\
            \\app = TurboAPI()
            \\
            \\# Mount a .so / .dylib — handler is called from Zig directly
            \\app.mount_native("/fast", "./libnative_handler.dylib")
            \\
            \\# The native handler signature (Zig):
            \\# pub export fn handle(req: *Request, res: *Response) void
        ),
        h.div(.{ .class = "callout callout-warn" }, .{
            h.span(.{ .class = "callout-icon" }, "🔧"),
            h.span(.{}, "Native FFI handlers are experimental. API surface may change before 1.0."),
        }),

        // Compatibility
        h.h2(.{ .id = "compat" }, "Compatibility"),
        h.p(.{}, "Current alpha compatibility status with FastAPI features:"),
        h.table(.{ .class = "status-table" }, .{
            h.tbody(.{}, .{
                h.tr(.{}, .{ h.td(.{}, "Path / query / body params"), h.td(.{}, .{h.span(.{ .class = "ok" }, "✅ Supported")}) }),
                h.tr(.{}, .{ h.td(.{}, "Pydantic v2 models"), h.td(.{}, .{h.span(.{ .class = "ok" }, "✅ Supported")}) }),
                h.tr(.{}, .{ h.td(.{}, "dhi native models"), h.td(.{}, .{h.span(.{ .class = "ok" }, "✅ Supported")}) }),
                h.tr(.{}, .{ h.td(.{}, "Dependency injection"), h.td(.{}, .{h.span(.{ .class = "ok" }, "✅ Supported")}) }),
                h.tr(.{}, .{ h.td(.{}, "Background tasks"), h.td(.{}, .{h.span(.{ .class = "ok" }, "✅ Supported")}) }),
                h.tr(.{}, .{ h.td(.{}, "CORS / middleware"), h.td(.{}, .{h.span(.{ .class = "ok" }, "✅ Supported")}) }),
                h.tr(.{}, .{ h.td(.{}, "OpenAPI / Swagger UI"), h.td(.{}, .{h.span(.{ .class = "ok" }, "✅ Supported")}) }),
                h.tr(.{}, .{ h.td(.{}, "OAuth2 / security"), h.td(.{}, .{h.span(.{ .class = "ok" }, "✅ Supported")}) }),
                h.tr(.{}, .{ h.td(.{}, "File uploads"), h.td(.{}, .{h.span(.{ .class = "wip" }, "🔧 In progress")}) }),
                h.tr(.{}, .{ h.td(.{}, "WebSockets"), h.td(.{}, .{h.span(.{ .class = "wip" }, "🔧 In progress")}) }),
                h.tr(.{}, .{ h.td(.{}, "Streaming responses"), h.td(.{}, .{h.span(.{ .class = "wip" }, "🔧 In progress")}) }),
            }),
        }),

        h.div(.{ .class = "hero-actions" }, .{
            h.a(.{ .href = "/quickstart", .class = "btn" }, "Quick start →"),
            h.a(.{ .href = "https://github.com/justrach/turboAPI", .class = "btn btn-outline" }, "GitHub"),
        }),
    });
}
