const mer = @import("mer");
const h = mer.h;

pub const meta: mer.Meta = .{
    .title = "Building with merjs — Notes",
    .description = "Honest notes on building TurboAPI's frontend with merjs, a Zig-native SSR framework. What broke, what worked, and what to watch out for.",
};

pub const prerender = true;

const page_node = page();

pub fn render(req: mer.Request) mer.Response {
    return mer.render(req.allocator, page_node);
}

fn page() h.Node {
    return h.div(.{ .class = "docs" }, .{
        h.div(.{ .class = "section-label" }, "Devlog"),
        h.h1(.{ .class = "section-title" }, "Building with merjs"),
        h.p(.{}, "merjs is a Zig-native SSR web framework with file-based routing. We used it to build this site. Here's what we hit along the way — documented so you don't have to."),

        h.div(.{ .class = "toc" }, .{
            h.div(.{ .class = "toc-label" }, "On this page"),
            h.a(.{ .href = "#setup", .class = "toc-link" }, "Package setup gotchas"),
            h.a(.{ .href = "#missing-files", .class = "toc-link" }, "Missing files from the package"),
            h.a(.{ .href = "#html-dsl", .class = "toc-link" }, "h.* DSL quirks"),
            h.a(.{ .href = "#raw-html", .class = "toc-link" }, "Raw HTML pages"),
            h.a(.{ .href = "#layout", .class = "toc-link" }, "layout.zig pitfalls"),
            h.a(.{ .href = "#verdict", .class = "toc-link" }, "Verdict"),
        }),

        h.h2(.{ .id = "setup" }, "1. Package setup gotchas"),
        h.p(.{}, "Getting merjs into a new project requires a valid build.zig.zon. Several fields are easy to get wrong:"),
        h.div(.{ .class = "issue-list" }, .{
            h.div(.{ .class = "issue" }, .{
                h.div(.{ .class = "issue-title" }, "Missing fingerprint"),
                h.div(.{ .class = "issue-body" }, "Zig 0.15 requires a fingerprint field in build.zig.zon. If missing, the compiler prints the expected value — paste it in."),
                h.pre(.{},
                    \\.fingerprint = 0xf5794ba041c0e27d,
                ),
            }),
            h.div(.{ .class = "issue" }, .{
                h.div(.{ .class = "issue-title" }, "Invalid package name"),
                h.div(.{ .class = "issue-body" }, "Package names can't use @\"...\" escape syntax. Use a plain snake_case identifier instead."),
                h.pre(.{},
                    \\- .name = .@"frontend",
                    \\+ .name = .turboapi_frontend,
                ),
            }),
            h.div(.{ .class = "issue" }, .{
                h.div(.{ .class = "issue-title" }, "URL needs a pinned git ref"),
                h.div(.{ .class = "issue-body" }, "The dependency URL must include a specific commit hash in the fragment (#abcdef...) or Zig won't fetch it reproducibly."),
            }),
            h.div(.{ .class = "issue" }, .{
                h.div(.{ .class = "issue-title" }, "Missing .hash field"),
                h.div(.{ .class = "issue-body" }, "After adding the URL, run zig fetch --save to compute the content hash. Without it the build fails immediately."),
            }),
        }),

        h.h2(.{ .id = "missing-files" }, "2. Missing files from the package"),
        h.p(.{}, "The biggest time sink. The published merjs package at the pinned commit was missing two categories of files — neither included in .paths in build.zig.zon:"),
        h.div(.{ .class = "issue-list" }, .{
            h.div(.{ .class = "issue" }, .{
                h.div(.{ .class = "issue-title" }, "wasm/counter_config.zig not in package"),
                h.div(.{ .class = "issue-body" }, "The wasm/ directory is excluded from the package. The build system imports counter_config.zig and fails with FileNotFound. Fix: create the file manually in the Zig global cache from the GitHub source."),
            }),
            h.div(.{ .class = "issue" }, .{
                h.div(.{ .class = "issue-title" }, "src/ runtime files missing"),
                h.div(.{ .class = "issue-body" }, "server.zig, ssr.zig, watcher.zig, prerender.zig, router.zig, request.zig, response.zig, static.zig, env.zig, html.zig, html_lint.zig, dhi.zig, worker.zig — all absent from the published package. Had to copy them manually from the Zig global cache after a failed build populated it."),
            }),
        }),
        h.div(.{ .class = "callout callout-warn" }, .{
            h.span(.{ .class = "callout-icon" }, "📦"),
            h.span(.{}, "If starting fresh: clone the repo directly rather than depending on it as a Zig package. The published package at the pinned hash is incomplete."),
        }),

        h.h2(.{ .id = "html-dsl" }, "3. h.* DSL quirks"),
        h.p(.{}, "merjs provides a Zig HTML builder DSL. It's clean once you know the rules — but several are non-obvious:"),
        h.div(.{ .class = "issue-list" }, .{
            h.div(.{ .class = "issue" }, .{
                h.div(.{ .class = "issue-title" }, "Void elements take zero args"),
                h.div(.{ .class = "issue-body" }, "h.br(), h.hr(), h.input() take no arguments. Passing .{} causes \"expected 0 args\"."),
                h.pre(.{},
                    \\- h.br(.{})  // compile error
                    \\+ h.br()     // correct
                ),
            }),
            h.div(.{ .class = "issue" }, .{
                h.div(.{ .class = "issue-title" }, "Single child requires a tuple"),
                h.div(.{ .class = "issue-body" }, "Passing one child node directly fails. Wrap it in a single-element tuple:"),
                h.pre(.{},
                    \\- h.pre(.{}, h.code(.{}, "..."))
                    \\+ h.pre(.{}, .{h.code(.{}, "...")})
                ),
            }),
            h.div(.{ .class = "issue" }, .{
                h.div(.{ .class = "issue-title" }, "thead/tbody same rule"),
                h.div(.{ .class = "issue-body" }, "h.thead(.{}, h.tr(...)) fails for the same reason. Must be h.thead(.{}, .{h.tr(...)})."),
            }),
            h.div(.{ .class = "issue" }, .{
                h.div(.{ .class = "issue-title" }, "h.pre with h.code inside"),
                h.div(.{ .class = "issue-body" }, "Hits the single-child tuple issue. For code blocks, pass a raw string to h.pre() directly — it renders in monospace anyway and avoids the nesting problem."),
            }),
        }),

        h.h2(.{ .id = "raw-html" }, "4. Raw HTML pages"),
        h.p(.{}, "For pages needing embedded JS (Chart.js, etc.), the h.* DSL is limiting. merjs lets you bypass layout.zig entirely with raw HTML responses:"),
        h.pre(.{},
            \\pub fn render(req: mer.Request) mer.Response {
            \\    _ = req;
            \\    return .{
            \\        .status    = .ok,
            \\        .content_type = .html,
            \\        .body      = html,
            \\    };
            \\}
            \\
            \\const html =
            \\    \\<!DOCTYPE html>
            \\    \\...
            \\;   // don't forget the semicolon
        ),
        h.div(.{ .class = "callout callout-warn" }, .{
            h.span(.{ .class = "callout-icon" }, "⚠️"),
            h.span(.{}, "Raw HTML pages still need pub const meta: mer.Meta exported — even though meta isn't used. Missing it causes a compile error from the generated router. The closing semicolon after the multiline string is also easy to forget; the error message points to the last HTML line, which is confusing."),
        }),

        h.h2(.{ .id = "layout" }, "5. layout.zig pitfalls"),
        h.p(.{}, "layout.zig uses a Zig ArrayList writer pattern to build the HTML shell. Two things bit us:"),
        h.div(.{ .class = "issue-list" }, .{
            h.div(.{ .class = "issue" }, .{
                h.div(.{ .class = "issue-title" }, "CSS accidentally placed outside writeAll"),
                h.div(.{ .class = "issue-body" }, "When range-replacing inside layout.zig it's easy to insert CSS after the closing paren of writeAll(\"\"\"). Zig compiles fine but the CSS never reaches the browser. Best fix: rewrite the whole file cleanly rather than patching small ranges."),
            }),
            h.div(.{ .class = "issue" }, .{
                h.div(.{ .class = "issue-title" }, "404.zig duplicate HTML block"),
                h.div(.{ .class = "issue-body" }, "A bad range-replace left two concatenated versions of the page HTML in the string literal. The Zig compiler error (\"expected ';' after declaration\") pointed to a line mid-way through the HTML, which is confusing. Fix: find and delete the orphaned duplicate block."),
            }),
        }),

        h.h2(.{ .id = "verdict" }, "Verdict"),
        h.p(.{}, "merjs is a genuinely good idea. Zig-native SSR with file-based routing, sub-millisecond builds, and a clean HTML DSL. The output is lean and the dev server is fast."),
        h.p(.{}, "The main blocker right now is the incomplete package publish — the .paths list in build.zig.zon excludes wasm/ and most of src/, so fresh installs fail immediately. Once that's resolved, setup should be straightforward."),
        h.p(.{}, "For JS-heavy pages, raw HTML is a clean escape hatch. The framework doesn't fight you. We'd use it again once the packaging story is sorted."),

        h.div(.{ .class = "hero-actions" }, .{
            h.a(.{ .href = "https://github.com/justrach/merjs", .class = "btn" }, "merjs on GitHub →"),
            h.a(.{ .href = "/docs", .class = "btn btn-outline" }, "TurboAPI docs"),
        }),
    });
}
