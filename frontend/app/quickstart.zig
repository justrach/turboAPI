const mer = @import("mer");
const h = mer.h;

pub const meta: mer.Meta = .{
    .title = "Quick Start",
    .description = "Get started with TurboAPI in under 60 seconds.",
};

pub const prerender = true;

const page_node = page();

pub fn render(req: mer.Request) mer.Response {
    return mer.render(req.allocator, page_node);
}

fn page() h.Node {
    return h.div(.{ .class = "docs" }, .{
        h.div(.{ .class = "section-label" }, "Quick Start"),
        h.h1(.{ .class = "section-title" }, "Up and running in 60 seconds"),

        h.h2(.{}, "1. Install"),
        h.p(.{}, "Requires Python 3.13+. Free-threaded 3.14t recommended for maximum throughput."),
        h.pre(.{},
            \\pip install turboapi
        ),

        h.h2(.{}, "2. Write your app"),
        h.p(.{}, "TurboAPI is a drop-in FastAPI replacement. Change one line:"),
        h.pre(.{},
            \\- from fastapi import FastAPI
            \\+ from turboapi import TurboAPI
            \\
            \\app = TurboAPI()
            \\
            \\@app.get("/")
            \\async def root():
            \\    return {"message": "Hello, World!"}
            \\
            \\@app.post("/items")
            \\async def create_item(name: str, price: float):
            \\    return {"name": name, "price": price}
        ),

        h.h2(.{}, "3. Run"),
        h.pre(.{},
            \\uvicorn main:app --reload
        ),
        h.p(.{}, "Or use the built-in Zig HTTP server directly:"),
        h.pre(.{},
            \\import turboapi
            \\turboapi.run(app, host="0.0.0.0", port=8000)
        ),

        h.h2(.{}, "dhi models — Zig-native validation"),
        h.p(.{}, "Zero-overhead request validation compiled to native code:"),
        h.pre(.{},
            \\from turboapi import TurboAPI
            \\from dhi import Model, Str, Int, EmailStr
            \\
            \\class UserModel(Model):
            \\    name:  Str(min_length=1, max_length=100)
            \\    email: EmailStr
            \\    age:   Int(gt=0, le=150)
            \\
            \\@app.post("/users")
            \\async def create_user(user: UserModel):
            \\    return user
        ),

        h.h2(.{}, "What works today"),
        h.table(.{ .class = "status-table" }, .{
            h.tbody(.{}, .{
                h.tr(.{}, .{ h.td(.{}, .{ h.span(.{ .class = "ok" }, "\xe2\x9c\x85 "), h.text("FastAPI-compatible route decorators") }), h.td(.{}, "Stable") }),
                h.tr(.{}, .{ h.td(.{}, .{ h.span(.{ .class = "ok" }, "\xe2\x9c\x85 "), h.text("Zig HTTP server — 8-thread pool + keep-alive") }), h.td(.{}, "Stable") }),
                h.tr(.{}, .{ h.td(.{}, .{ h.span(.{ .class = "ok" }, "\xe2\x9c\x85 "), h.text("dhi Zig-native JSON schema validation") }), h.td(.{}, "Stable") }),
                h.tr(.{}, .{ h.td(.{}, .{ h.span(.{ .class = "ok" }, "\xe2\x9c\x85 "), h.text("Zero-copy response pipeline") }), h.td(.{}, "Stable") }),
                h.tr(.{}, .{ h.td(.{}, .{ h.span(.{ .class = "ok" }, "\xe2\x9c\x85 "), h.text("Async handler support") }), h.td(.{}, "Stable") }),
                h.tr(.{}, .{ h.td(.{}, .{ h.span(.{ .class = "ok" }, "\xe2\x9c\x85 "), h.text("OAuth2, Bearer, API Key security") }), h.td(.{}, "Stable") }),
                h.tr(.{}, .{ h.td(.{}, .{ h.span(.{ .class = "ok" }, "\xe2\x9c\x85 "), h.text("Python 3.14t free-threaded support") }), h.td(.{}, "Stable") }),
                h.tr(.{}, .{ h.td(.{}, .{ h.span(.{ .class = "ok" }, "\xe2\x9c\x85 "), h.text("Native FFI handlers (C/Zig, no Python)") }), h.td(.{}, "Stable") }),
                h.tr(.{}, .{ h.td(.{}, .{ h.span(.{ .class = "wip" }, "\xf0\x9f\x94\xa7 "), h.text("WebSocket support") }), h.td(.{}, "In progress") }),
                h.tr(.{}, .{ h.td(.{}, .{ h.span(.{ .class = "wip" }, "\xf0\x9f\x94\xa7 "), h.text("HTTP/2 and TLS") }), h.td(.{}, "In progress") }),
                h.tr(.{}, .{ h.td(.{}, .{ h.span(.{ .class = "wip" }, "\xf0\x9f\x94\xa7 "), h.text("Cloudflare Workers WASM target") }), h.td(.{}, "In progress") }),
            }),
        }),

        h.div(.{ .class = "hero-actions" }, .{
            h.a(.{ .href = "/benchmarks", .class = "btn" }, "See benchmarks"),
            h.a(.{ .href = "https://github.com/justrach/turboAPI", .class = "btn btn-outline" }, "GitHub"),
        }),
    });
}
