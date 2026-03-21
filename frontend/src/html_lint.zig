// html_lint.zig — Comptime HTML linter for the merjs framework.
//
// Walks an html.Node tree at comptime and enforces structural HTML rules.
//
//   const mer = @import("mer");
//   const page_node = page();
//   comptime { mer.lint.check(page_node); }

const std = @import("std");
const html = @import("html.zig");

/// Check an HTML node tree at comptime. Triggers @compileError on violations.
pub fn check(node: html.Node) void {
    checkNode(node, .{});
}

/// Check an HTML node tree only when `enabled` is true.
pub fn checkOpt(node: html.Node, comptime enabled: bool) void {
    if (!enabled) return;
    check(node);
}

const Context = struct {
    inside_a: bool = false,
    inside_p: bool = false,
};

fn checkNode(node: html.Node, ctx: Context) void {
    @setEvalBranchQuota(100_000);
    switch (node) {
        .element => |elem| checkElement(elem, ctx),
        .text, .raw => {},
    }
}

fn checkElement(elem: html.Element, ctx: Context) void {
    const tag = elem.tag;

    // Rule 9: No nested <a> inside <a>
    if (ctx.inside_a and eql(tag, "a")) {
        @compileError("<a> must not be nested inside another <a>");
    }

    // Rule 10: No block elements inside <p>
    if (ctx.inside_p and isBlockElement(tag)) {
        @compileError("<" ++ tag ++ "> is a block element and must not appear inside <p>");
    }

    // Rule 1: <a> must have href
    if (eql(tag, "a") and !hasAttr(elem.attrs, "href")) {
        @compileError("<a> element must have an 'href' attribute");
    }

    // Rule 2: <img> must have alt
    if (eql(tag, "img") and !hasAttr(elem.attrs, "alt")) {
        @compileError("<img> element must have an 'alt' attribute");
    }

    // Rule 3: <meta> with property must have content
    if (eql(tag, "meta") and hasAttr(elem.attrs, "property") and !hasAttr(elem.attrs, "content")) {
        @compileError("<meta property=\"...\"> must have a 'content' attribute");
    }

    // Rule 4: <meta> with name must have content
    if (eql(tag, "meta") and hasAttr(elem.attrs, "name") and !hasAttr(elem.attrs, "content")) {
        @compileError("<meta name=\"...\"> must have a 'content' attribute");
    }

    // Rule 5: No empty <title>
    if (eql(tag, "title") and elem.children.len == 0) {
        @compileError("<title> element must not be empty");
    }

    // Rule 6: <button> should have type
    if (eql(tag, "button") and !hasAttr(elem.attrs, "type")) {
        @compileError("<button> element must have an explicit 'type' attribute");
    }

    // Rule 7: <input> must have type
    if (eql(tag, "input") and !hasAttr(elem.attrs, "type")) {
        @compileError("<input> element must have a 'type' attribute");
    }

    // Rule 8: <form> must have action
    if (eql(tag, "form") and !hasAttr(elem.attrs, "action")) {
        @compileError("<form> element must have an 'action' attribute");
    }

    // Recurse into children with updated context
    var child_ctx = ctx;
    if (eql(tag, "a")) child_ctx.inside_a = true;
    if (eql(tag, "p")) child_ctx.inside_p = true;

    for (elem.children) |child| {
        checkNode(child, child_ctx);
    }
}

fn hasAttr(attrs: []const html.Attr, name: []const u8) bool {
    for (attrs) |at| {
        if (eql(at.name, name)) return true;
    }
    return false;
}

fn eql(a: []const u8, b: []const u8) bool {
    return std.mem.eql(u8, a, b);
}

fn isBlockElement(tag: []const u8) bool {
    const block_tags = [_][]const u8{
        "div",    "section", "article", "aside",    "header",
        "footer", "nav",     "main",    "ul",       "ol",
        "li",     "table",   "form",    "fieldset", "blockquote",
        "pre",    "h1",      "h2",      "h3",       "h4",
        "h5",     "h6",      "hr",      "p",
    };
    for (block_tags) |bt| {
        if (eql(tag, bt)) return true;
    }
    return false;
}
