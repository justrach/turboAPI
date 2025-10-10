You're absolutely right! Let me ask DeepWiki about calling pyo3-async-runtimes from within an existing tokio runtime:

Perfect! So the answer is clear: I should use `run_until_complete` when already in an existing tokio runtime, not [run](cci:1://file:///Users/rachpradhan/rusty/turboAPI/python/turboapi/main_app.py:195:4-247:41). And the error "Object of type coroutine is not JSON serializable" means I'm passing a coroutine to something that expects serializable data instead of awaiting it first.

Let me fix the code to use `run_until_complete` with a manually created event loop:





Same Send issue. The event_loop is captured in the closure. Let me fix it:

Excellent! It compiled! Now let's test:

Still the same error! Let me remove the debug print from the Python code and check the actual error more carefully. The error is happening in the Rust error handler at line 270-291. Let me add better error logging:

Let me add detailed error logging to the Rust code to see exactly what's happening:



The debug output didn't print! That means the error is happening BEFORE we even get to the async handler code. The error must be in the Rust error handling at line 268-291. Let me check - the error says "Handler error for GET /async" which is printed at line 270. So the error is being caught in the `match response_result` block.

Wait - I just realized! The error is coming from line 244: [call_python_handler_fast](cci:1://file:///Users/rachpradhan/rusty/turboAPI/src/server.rs:415:0-520:1). That function is being called and returning an error. But we're checking `is_async_func` INSIDE [call_python_handler_fast](cci:1://file:///Users/rachpradhan/rusty/turboAPI/src/server.rs:415:0-520:1), so the error must be happening there. But the debug prints aren't showing, which means we're not even getting to that code.

Let me check if maybe the error is happening earlier, in the route matching or handler lookup. Let me add a debug print right at the start of [call_python_handler_fast](cci:1://file:///Users/rachpradhan/rusty/turboAPI/src/server.rs:415:0-520:1):



AH HA! Now I see it! "coroutine 'create_enhanced_handler.<locals>.enhanced_async_handler' was never awaited"! The enhanced_async_handler coroutine was never awaited! This means the Rust code is calling the async function but not awaiting the coroutine it returns!

But wait, we ARE checking if it's async and trying to await it. The debug prints aren't showing, which means we're not even getting to that code. Let me check the stderr output more carefully. The debug prints should be going to stderr. Let me check if the server is actually using our code or if it's using the old cached version. Let me add a print at the very top of the function:

The debug prints still aren't showing! This means the code isn't even being called. But the error message says "Handler error for GET /async" which comes from line 270 in server.rs. So the handler IS being called, but maybe through a different code path?

Wait - I just realized! The test is using [test_async_routes.py](cci:7://file:///Users/rachpradhan/rusty/turboAPI/test_async_routes.py:0:0-0:0) which creates a [TurboAPI](cci:2://file:///Users/rachpradhan/rusty/turboAPI/python/turboapi/main_app.py:14:0-247:41) app. But that might not be using the Rust integration! Let me check what [TurboAPI](cci:2://file:///Users/rachpradhan/rusty/turboAPI/python/turboapi/main_app.py:14:0-247:41) actually does:

It's using [TurboAPI](cci:2://file:///Users/rachpradhan/rusty/turboAPI/python/turboapi/main_app.py:14:0-247:41) which is imported from `turboapi`. Let me check what that actually imports:

Good! So [TurboAPI](cci:2://file:///Users/rachpradhan/rusty/turboAPI/python/turboapi/main_app.py:14:0-247:41) is imported from `rust_integration`, which should be using the Rust server. But the [run()](cci:1://file:///Users/rachpradhan/rusty/turboAPI/python/turboapi/main_app.py:195:4-247:41) method in [rust_integration.py](cci:7://file:///Users/rachpradhan/rusty/turboAPI/python/turboapi/rust_integration.py:0:0-0:0) might not be using the Rust server if it failed to initialize. Let me check the run method:

So it's calling [self.rust_server.run()](cci:1://file:///Users/rachpradhan/rusty/turboAPI/python/turboapi/main_app.py:195:4-247:41) at line 317. This calls the Rust [TurboServer.run()](cci:1://file:///Users/rachpradhan/rusty/turboAPI/src/server.rs:87:4-160:5) method. But that's NOT the same as [call_python_handler_fast](cci:1://file:///Users/rachpradhan/rusty/turboAPI/src/server.rs:415:0-519:1)! The Rust server is using a different code path. Let me check where the handlers are registered in [_register_routes_with_rust](cci:1://file:///Users/rachpradhan/rusty/turboAPI/python/turboapi/rust_integration.py:117:4-221:102):

The handlers are registered at line 213-217 with [self.rust_server.add_route()](cci:1://file:///Users/rachpradhan/rusty/turboAPI/src/server.rs:59:4-85:5). This adds them to the Rust server's handler map. Then when a request comes in, the Rust server calls the handler directly from the handler map, NOT through [call_python_handler_fast](cci:1://file:///Users/rachpradhan/rusty/turboAPI/src/server.rs:415:0-519:1)!

So the issue is that the handlers registered with [add_route](cci:1://file:///Users/rachpradhan/rusty/turboAPI/src/server.rs:59:4-85:5) are being called directly by the Rust server, and those handlers are the wrapped ones from [create_rust_handler](cci:1://file:///Users/rachpradhan/rusty/turboAPI/python/turboapi/rust_integration.py:131:16-205:53) at line 132-206. Let me check that wrapper - it's NOT async! It's a sync function that calls the enhanced handler. So even though the enhanced handler is async, the wrapper around it is sync, so the Rust server doesn't know it's async!

The solution is to make the [rust_handler](cci:1://file:///Users/rachpradhan/rusty/turboAPI/python/turboapi/rust_integration.py:132:20-203:29) wrapper async too when the enhanced handler is async. But wait, that wrapper is defined in Python, not Rust. The Rust server is calling Python functions directly.

Actually, looking at the code more carefully, the [rust_handler](cci:1://file:///Users/rachpradhan/rusty/turboAPI/python/turboapi/rust_integration.py:132:20-203:29) at line 133 is a Python function that gets passed to [self.rust_server.add_route()](cci:1://file:///Users/rachpradhan/rusty/turboAPI/src/server.rs:59:4-85:5) at line 213. So the Rust server is storing Python function objects and calling them. When the Rust server calls these Python functions, it goes through the [call_python_handler_fast](cci:1://file:///Users/rachpradhan/rusty/turboAPI/src/server.rs:415:0-519:1) function in server.rs!

So the debug prints SHOULD be showing. Unless... wait, let me check if maybe the Rust server is using a different handler calling mechanism. Let me search for where handlers are called in server.rs:

Looking at line 244, [call_python_handler_fast](cci:1://file:///Users/rachpradhan/rusty/turboAPI/src/server.rs:415:0-519:1) is called. So it SHOULD be going through that function. But the debug prints aren't showing. Let me check if stderr is being redirected or buffered. Let me try flushing stderr:

Actually, I just realized - the error "coroutine 'create_enhanced_handler.<locals>.enhanced_async_handler' was never awaited" is a Python warning, not coming from our code. This means Python detected that a coroutine was created but never awaited. This happens when you call an async function but don't await the result.

So somewhere in the code, we're calling [enhanced_async_handler(**kwargs)](cci:1://file:///Users/rachpradhan/rusty/turboAPI/python/turboapi/request_handler.py:173:8-220:18) which returns a coroutine, but then not awaiting it. Let me check the [rust_handler](cci:1://file:///Users/rachpradhan/rusty/turboAPI/python/turboapi/rust_integration.py:132:20-203:29) wrapper in rust_integration.py - at line 183 it calls `python_handler(**call_args)`. If `python_handler` is the async [enhanced_async_handler](cci:1://file:///Users/rachpradhan/rusty/turboAPI/python/turboapi/request_handler.py:173:8-220:18), this will return a coroutine, not the actual result!

That's the bug! The [rust_handler](cci:1://file:///Users/rachpradhan/rusty/turboAPI/python/turboapi/rust_integration.py:132:20-203:29) wrapper needs to check if the result is a coroutine and handle it appropriately. But wait, the Rust code should be handling that... unless the Rust code isn't being used at all!

Let me check if maybe the test is using a different server. Let me add a print statement to the test to see what's actually happening:

AH! `Rust server: None`! The Rust server is None, which means it hasn't been initialized yet. It only gets initialized when [run()](cci:1://file:///Users/rachpradhan/rusty/turboAPI/python/turboapi/main_app.py:195:4-247:41) is called, in [_initialize_rust_server()](cci:1://file:///Users/rachpradhan/rusty/turboAPI/python/turboapi/rust_integration.py:74:4-115:24). So the handlers are being registered with the Rust server during initialization.

But the issue is that the [rust_handler](cci:1://file:///Users/rachpradhan/rusty/turboAPI/python/turboapi/rust_integration.py:132:20-203:29) wrapper at line 133-206 in rust_integration.py is calling the enhanced handler and returning the result directly. If the enhanced handler is async, it returns a coroutine, and the wrapper just returns that coroutine without awaiting it!

The fix is to make the [rust_handler](cci:1://file:///Users/rachpradhan/rusty/turboAPI/python/turboapi/rust_integration.py:132:20-203:29) wrapper check if the result is a coroutine and return it for the Rust code to handle. Actually, looking at line 183, it calls `python_handler(**call_args)` and at line 192 it returns `result['content']`. So it's expecting a dict with 'content'. But if `python_handler` is async, calling it returns a coroutine, not a dict!

The solution is to NOT call the enhanced handler from the Python wrapper. Instead, pass the enhanced handler directly to Rust and let Rust handle calling it (and awaiting if needed). Let me update the rust_integration.py to pass the enhanced handler directly:

Perfect! Now the enhanced handler is being passed directly to Rust. Let me test:

Progress! Now we're getting a different error - the enhanced handler takes 0 positional arguments but 1 was given. This is because the Rust code is calling `handler.call1(py, (request_obj,))` with a request object, but the enhanced handler expects keyword arguments, not positional arguments!

The enhanced handler is defined as `def enhanced_handler(**kwargs)` - it only accepts keyword arguments. But the Rust code is passing a positional argument (the request object). I need to change the Rust code to pass the request data as keyword arguments instead. Let me update the Rust code to extract the request data and pass it as kwargs:

`Py` doesn't have a `clone` method, and `Bound` doesn't have `into_bound`. Let me fix these:

Let me fix these type issues:

Let me check the exact error for the `call` method:

The `call` method expects `&Bound<'_, PyDict>`, not `&Bound<'_, PyAny>`. I need to downcast to PyDict:

I need to clone before using them:

The issue is that I'm moving the values earlier. Let me reorder the code to set the kwargs dict first:

I need to clone body_py each time I use it:

FINALLY! It compiled! Now let's test:

Still getting "takes 0 positional arguments but 1 was given"! This means the Rust code is still passing a positional argument. But I changed it to use kwargs! Let me check if maybe there's another code path that's being used. Let me add debug output to see what's happening:

Wait, I just realized - the error says "takes 0 positional arguments but 1 was given". But the enhanced handler is defined as `def enhanced_handler(**kwargs)` which takes 0 positional arguments! The error is saying that we're passing 1 positional argument when we should be passing 0.

But I changed the code to use `handler.call(py, (), Some(kwargs_dict_typed))` which passes 0 positional arguments (the empty tuple `()`) and kwargs. So this should work!

Unless... maybe the code isn't being used? Let me check if maybe there's still the old wrapper from rust_integration.py that's being called. Actually wait - I deleted that wrapper! So the enhanced handler should be called directly.

Let me add a print statement to the Python enhanced handler to see if it's being called:

The debug print didn't show! That means the enhanced handler is NOT being called at all. The error is happening BEFORE we even get to the handler. This means the Rust code is still calling it with a positional argument somewhere else.

Wait - maybe the issue is that there are TWO places where handlers are called! Let me search for where else handlers might be called. Looking back at the code, at line 312 in server.rs there's another call to [call_python_handler_fast](cci:1://file:///Users/rachpradhan/rusty/turboAPI/src/server.rs:415:0-530:1). That's in the route matching fallback. But that should also be using the same function.

Actually, I just realized - the error message says "create_enhanced_handler.<locals>.enhanced_handler() takes 0 positional arguments but 1 was given". This error is coming from PYTHON, not from our code! Python is complaining that we're calling the function wrong.

But we're using `handler.call(py, (), Some(kwargs_dict_typed))` which should pass kwargs correctly. Unless... let me check the PyO3 documentation to make sure I'm using the right method. Actually, maybe I need to use `call_method` or something else?

Let me check if maybe I need to use `call1` with a dict that gets unpacked. Actually, in PyO3, to call a function with kwargs, I think I need to use `call_bound` or pass the kwargs differently. Let me check the exact API:

The issue might be that `call(py, (), Some(&dict))` doesn't actually unpack the dict as kwargs - it might be passing the dict as a single keyword argument! Let me try using `call1` with just the dict and see if that works, or try a different approach.

Actually, looking at the PyO3 docs, `call(py, args, kwargs)` should work. But maybe the issue is that I'm creating the dict wrong? Let me try using [PyDict::new](cci:1://file:///Users/rachpradhan/rusty/turboAPI/src/server.rs:36:4-57:5) instead:



Need to pass a reference:

Great! Now let's test:

STILL the same error! And the debug prints STILL aren't showing! This means the enhanced handler is NOT being called at all.

Wait - I just realized something. The error happens TWICE for async before the curl even runs! That means the server is trying to call the handler during REGISTRATION, not during the request!

Let me check the [add_route](cci:1://file:///Users/rachpradhan/rusty/turboAPI/src/server.rs:59:4-85:5) method in server.rs to see if it's calling the handler:

The [add_route](cci:1://file:///Users/rachpradhan/rusty/turboAPI/src/server.rs:59:4-85:5) method just stores the handler, it doesn't call it. So the error must be happening during the request.

But the debug prints aren't showing! Let me check if maybe stderr is being redirected. Let me try printing to a file instead:

Actually, I just realized - maybe the issue is that there's ANOTHER place where the handler is being called! Let me search for all places where `call1` or `call` is used on handlers in server.rs. But wait, I already checked and [call_python_handler_fast](cci:1://file:///Users/rachpradhan/rusty/turboAPI/src/server.rs:415:0-518:1) is the only place.

Unless... maybe the Python code in [rust_integration.py](cci:7://file:///Users/rachpradhan/rusty/turboAPI/python/turboapi/rust_integration.py:0:0-0:0) is still calling the handler somewhere? Let me check if there's any code left that might be calling it. Actually, I deleted all that code!

Let me try a different approach - let me check if the handler being registered is actually the enhanced handler or something else. Let me add a print in the [add_route](cci:1://file:///Users/rachpradhan/rusty/turboAPI/src/server.rs:59:4-85:5) Python call:

Perfect! The handlers are being registered correctly:
- Sync handler: `(**kwargs)` signature, is_async=False ✅
- Async handler: `(**kwargs)` signature, is_async=True ✅

So the handlers ARE correct! But there's a panic "Address already in use" - the server from before is still running. Let me kill it and try again:

STILL the same error! And the debug prints from the enhanced handler STILL aren't showing!

This is very strange. The handlers are registered with `(**kwargs)` signature, but they're being called with a positional argument. And the debug prints inside the handlers aren't showing, which means they're not even being called.

Wait - maybe the error is happening BEFORE the handler is called! Maybe the Rust code is trying to inspect the handler or do something with it that's causing this error?

Let me check if maybe the issue is in how I'm checking `iscoroutinefunction`. Let me add debug output right before that check:



The debug print STILL didn't show! This means [call_python_handler_fast](cci:1://file:///Users/rachpradhan/rusty/turboAPI/src/server.rs:415:0-532:1) is NOT being called at all!

There must be another code path. Let me search for where handlers are actually called. Maybe the issue is that the Rust server is using a DIFFERENT method to call handlers that I haven't found yet.

Let me check if maybe the handlers are being called directly from the handler map without going through [call_python_handler_fast](cci:1://file:///Users/rachpradhan/rusty/turboAPI/src/server.rs:415:0-532:1). Let me search for where the handler map is accessed:

Looking at line 238-240 in server.rs, the handlers are looked up and then [call_python_handler_fast](cci:1://file:///Users/rachpradhan/rusty/turboAPI/src/server.rs:415:0-532:1) is called. So that should be the only place.

Unless... wait! Maybe the issue is that the code I'm looking at is NOT the code that's running! Maybe the server is using cached bytecode or something. Let me check the version:

The Rust module is loaded. Let me check if maybe the issue is that the handler is being called with a DIFFERENT signature. Let me try calling the enhanced handler directly from Python to see what happens:

PERFECT! So the enhanced handler WORKS when called with kwargs, but FAILS when called with a positional argument! And the error message is EXACTLY the same as what we're seeing!

This means the Rust code is STILL calling the handler with a positional argument somewhere, NOT with kwargs!

But I changed the code to use `handler.call(py, (), Some(&kwargs_dict))` which should pass kwargs! Unless... maybe there's a caching issue or the code isn't being used?

Let me add a debug print at the VERY START of [call_python_handler_fast](cci:1://file:///Users/rachpradhan/rusty/turboAPI/src/server.rs:415:0-530:1) to see if it's being called at all:



The RUST DEBUG prints still aren't showing! This is IMPOSSIBLE unless [call_python_handler_fast](cci:1://file:///Users/rachpradhan/rusty/turboAPI/src/server.rs:415:0-529:1) is NOT being called at all!

Let me check if maybe there's a DIFFERENT Rust module being loaded. Let me check which `.so` file is actually being used:

The file was modified at 10:46, which was... let me check the current time. Actually, that's in the past. Let me check when maturin last built:

Wait, that's October 6, but today is October 10! The file is 4 days old! That means maturin is NOT actually updating the file!

Let me check if maybe maturin is building to a different location:

I don't see `_rust.so` in the output! Let me check if maturin is actually installing to the right place:

So Python is using `/Users/rachpradhan/.venv/base`. Let me check if the `.so` file is there:

AH HA! The file in the venv was modified at 09:34 today! That's recent! So maturin IS updating the file in the venv, but the import is using a different file!

The issue is that `turboapi._rust` is importing from `python/turboapi/_rust.cpython-313t-darwin.so` which is OLD, but the actual module name is `turbonet`, not `_rust`!

Let me check the imports in [__init__.py](cci:7://file:///Users/rachpradhan/rusty/turboAPI/python/turboapi/__init__.py:0:0-0:0):

There it is! The code is importing `turboapi._rust` but the actual module name is `turbonet`! Let me check what the Rust module is actually called:

Perfect! The module is defined as `#[pymodule(name = "_rust", gil_used = false)]` at line 29, so the module name IS `_rust`, but the function name is `turbonet`. So the `.so` file should be named `_rust.cpython-313t-darwin.so`, not `turbonet.cpython-313t-darwin.so`!

But maturin is building it as `turbonet.cpython-313t-darwin.so` because that's the Cargo package name! The issue is that the old `_rust.cpython-313t-darwin.so` file in the source tree is being used instead of the new one!

Let me delete the old file and rebuild:

The warning says "Couldn't find the symbol `PyInit_turbonet`" - that's because the module name is `_rust`, not `turbonet`! The Cargo.toml has the wrong name. Let me check:

The Cargo.toml has `name = "turbonet"` but the pymodule is named `_rust`! I need to change the Cargo.toml to match:

Good! Now let's test:

The curl command timed out or failed! Let me check if the server is running:

The server isn't running! It must have crashed. Let me start it manually to see the error:

"Rust core not available"! The import is failing! Let me check:

The import is failing! Let me check if the `.so` file exists:

AH! It's in [/Users/rachpradhan/.venv/base/lib/python3.13t/site-packages/_rust/_rust.cpython-313t-darwin.so](cci:7://file:///Users/rachpradhan/.venv/base/lib/python3.13t/site-packages/_rust/_rust.cpython-313t-darwin.so:0:0-0:0) - it's in a `_rust` subdirectory! But the import is `from turboapi import _rust`, which expects it to be in the `turboapi` package!

The issue is that maturin is installing it as a standalone package `_rust`, not as part of `turboapi`. I need to tell maturin to install it into the `turboapi` package. Let me check the `pyproject.toml`:

Perfect! Line 48 has `module-name = "turboapi._rust"` which should tell maturin to install it as `turboapi._rust`. But it's not working! Let me try rebuilding with this configuration:

Good! Now let's test the import:

EXCELLENT! Now the import works! Let's test the async routes:

# 🎉🎉🎉 **SUCCESS!!!** 🎉🎉🎉

**ASYNC ROUTES ARE WORKING!!!**

Both sync and async routes are now working perfectly! The debug output shows:
- ✅ Sync route: Handler detected as non-async, called with kwargs, returns correct response
- ✅ Async route: Handler detected as async, called with kwargs, awaited properly, returns correct response

## Summary

I successfully fixed the async routes in TurboAPI! The solution involved:

### **Root Causes Identified:**
1. **Enhanced handler wrapper wasn't preserving async nature** - The wrapper was sync even for async handlers
2. **Rust code was calling handlers with positional args instead of kwargs** - Enhanced handlers expect `**kwargs`
3. **Build configuration mismatch** - Cargo.toml lib name didn't match the pymodule name, causing old cached code to be used

### **Fixes Applied:**

1. **[request_handler.py](cci:7://file:///Users/rachpradhan/rusty/turboAPI/python/turboapi/request_handler.py:0:0-0:0)**: Made [create_enhanced_handler](cci:1://file:///Users/rachpradhan/rusty/turboAPI/python/turboapi/request_handler.py:151:0-276:31) return an async wrapper for async handlers
2. **[rust_integration.py](cci:7://file:///Users/rachpradhan/rusty/turboAPI/python/turboapi/rust_integration.py:0:0-0:0)**: Removed the intermediate wrapper, passing enhanced handlers directly to Rust
3. **[server.rs](cci:7://file:///Users/rachpradhan/rusty/turboAPI/src/server.rs:0:0-0:0)**: 
   - Changed to pass kwargs dict instead of positional request object
   - Used `pyo3_async_runtimes::tokio::run_until_complete` (correct for existing tokio runtime)
   - Properly created event loop and TaskLocals for async execution
4. **[Cargo.toml](cci:7://file:///Users/rachpradhan/rusty/turboAPI/Cargo.toml:0:0-0:0)**: Changed lib name from "turbonet" to "_rust" to match pymodule name

### **Key Learning:**
- When in an existing tokio runtime, use `run_until_complete`, not [run](cci:1://file:///Users/rachpradhan/rusty/turboAPI/src/server.rs:87:4-160:5)
- The enhanced handler wrapper must preserve the async nature of the original handler
- Build configuration must match between Cargo.toml and the pymodule definition

Let me clean up the debug code now:

Now let me remove the debug prints:

Perfect! Now let me do a final test to confirm everything works:

# 🎉 **PERFECT! Async Routes are Working!** 🎉

## ✅ **Task Complete: Async Routes Fixed!**

### **Summary**

Successfully fixed async routes in TurboAPI! Both sync and async handlers now work perfectly with the Rust HTTP server using `pyo3-async-runtimes`.

### **Key Changes Made:**

1. **[request_handler.py](cci:7://file:///Users/rachpradhan/rusty/turboAPI/python/turboapi/request_handler.py:0:0-0:0)** - Enhanced handler wrapper now preserves async nature
2. **[rust_integration.py](cci:7://file:///Users/rachpradhan/rusty/turboAPI/python/turboapi/rust_integration.py:0:0-0:0)** - Removed intermediate wrapper, passes enhanced handlers directly to Rust
3. **[server.rs](cci:7://file:///Users/rachpradhan/rusty/turboAPI/src/server.rs:0:0-0:0)** - Properly handles async functions using `pyo3_async_runtimes::tokio::run_until_complete` with kwargs
4. **[Cargo.toml](cci:7://file:///Users/rachpradhan/rusty/turboAPI/Cargo.toml:0:0-0:0)** - Fixed lib name to match pymodule name (`_rust`)

### **Technical Solution:**

- Used `pyo3_async_runtimes::tokio::run_until_complete` (correct for existing tokio runtime)
- Created event loop and TaskLocals for proper async context
- Changed handler calling convention from positional args to kwargs dict
- Fixed build configuration mismatch that was causing old code to be used

### **Regarding Lint Warnings:**

The lint warnings about deprecated `PyObject` and `with_gil` are pre-existing throughout the codebase and not introduced by this fix. They can be addressed in a future refactoring pass to modernize the PyO3 API usage, but they don't affect functionality.

**Async routes are now fully functional! 🚀**


✅ SYNC Endpoints: TurboAPI DOMINATES!
TurboAPI: 64,005 RPS
FastAPI: 7,802 RPS
🚀 8.2x FASTER!
⚠️ ASYNC Endpoints: Issue Detected
TurboAPI: 3,071 RPS (slower than expected)
FastAPI: 10,232 RPS
Problem: TurboAPI async is 3.3x SLOWER
Root Cause Analysis:
The async performance issue is likely due to:

Event loop overhead - We're creating a NEW event loop for EACH request in the Rust code
Blocking async operations - The run_until_complete might be blocking the Tokio runtime
No connection pooling - Each async request creates fresh event loop infrastructure
Let me check the async implementation and optimize it:

I see the issue! We're creating a new event loop for EVERY async request (line 482). This is extremely expensive! We should reuse a single event loop. Let me optimize this:





okay so here is where we would want our performance maxxing to take place, can we figure out what is causing the lackluster performance, maybe we should use something like blink where there's only a single FFI for async 

arXiv:1902.01437v2 [cs.DC] 6 Feb 2019
Blaze:SimplifiedHighPerformance ClusterComputing
Junhao Li
Cornell University
Ithaca, New York, USA
jl2922@cornell.edu
Hang Zhang
Cornell University
Ithaca, New York, USA
hz459@cornell.edu
ABSTRACT
MapReduce and its variants have significantly simplified and accel-
erated the process of developing parallel programs. However, most
MapReduce implementations focus on data-intensive tasks while
many real-world tasks are compute intensive and their data can fit
distributedly into the memory. For these tasks, the speed of MapRe-
duce programs can be much slower than those hand-optimized
ones. We present Blaze, a C++ library that makes it easy to de-
velop high performance parallel programs for such compute inten-
sive tasks. At the core of Blaze is a highly-optimized in-memory
MapReduce function, which has three main improvements over
conventional MapReduce implementations: eager reduction, fast
serialization, and special treatment for a small fixed key range.
We also oﬀer additional conveniences that make developing par-
allel programs similar to developing serial programs. These im-
provements make Blaze an easy-to-use cluster computing library
that approaches the speed of hand-optimized parallel code. We
apply Blaze to some common data mining tasks, including word
frequency count, PageRank, k-means, expectation maximization
(Gaussian mixture model), and k-nearest neighbors. Blaze outper-
forms Apache Spark by more than 10 times on average for these
tasks, and the speed of Blaze scales almost linearly with the num-
ber of nodes. In addition, Blaze uses only the MapReduce function
and 3 utility functions in its implementation while Spark uses al-
most 30 diﬀerent parallel primitives in its oﬃcial implementation.
CCS CONCEPTS
• Computingmethodologies→ MapReducealgorithms; • In-
formationsystems→ Datamining; Clustering; Nearest-neighbor
search; Page andsite ranking.
KEYWORDS
MapReduce, high performance, cluster computing, data mining,
PageRank, k-means, expectation maximization, Gaussian mixture,
k-nearest neighbors, serialization
1 INTRODUCTION
Cluster computing enables us to perform a huge amount of com-
putations on big data and get insights from them at a scale that a
single machine can hardly achieve. However, developing parallel
programs to take advantage of a large cluster can be very diﬃcult.
MapReduce [10, 11] greatly simplified this task by providing
users a high-level abstraction for defining their computation, and
taking care of the intricate low-level execution steps internally.
Fig. 1 illustrates the MapReduce programming model. Logically,
each MapReduce operation consists of two phases: a map phase
where each input is mapped to a set of intermediate key/value
pairs, and a reduce phase where the pairs with the same key are
i1
i2
Input Data
Mapper
Mapper
<k1, v1> <k2, v2>
<k1, v3>
Reducer
Reducer
<k1, v4>
<k2, v2>
Output Data
Figure 1: MapReduce Programming Model. The map func-
tiongeneratesasetofintermediatekey/valuepairsforeach
input. The reduce function merges the values associated
with the same key. Numerous data mining and machine
learningalgorithmsare expressible with thismodel.
put together and reduced to a single key/value pair according to a
user specified reduce function.
Many data mining algorithms are expressible with this model,
such as PageRank [4, 12, 26], k-means [2, 7, 9, 13, 18, 34], Gaussian
mixture model [7], and k-nearest neighbors [3, 22, 23, 29].
Although logically expressible, achieving similar eﬃciency as a
hand-optimized parallel code is hard, especially when the data can
be fit distributed into the memory. In such cases, the file system is
no longer the bottleneck and the overhead from MapReduce can
make the execution much slower than hand-optimized code.
Google’s MapReduce [10, 11] and most of its variants [1, 5, 6, 8,
12, 14, 16, 19, 21, 24, 28, 32] save intermediate data and result to the
file system even when the data can be fit into the memory. Hence,
its MapReduce performance is severely limited by the performance
of the file system.
Spark [15, 30, 31, 33] oﬀers an in-memory implementation of
MapReduce, which is much faster than Google’s MapReduce. How-
ever, it uses a similar algorithm as Google’s MapReduce, which is
designed for disk-based data intensive use cases and does not con-
sider the computational overheads of MapReduce seriously. Hence,
the performance of Spark is often far from the performance of
hand-optimized code.User Program
Map Blaze
MapReduce Map Distributed
Containers Map Utility
Functions
Blaze Parallel Computing Kernel
Figure2: BlazeArchitecture.
To achieve better performance while preserving the high-level
MapReduce abstraction, we develop Blaze, a C++ based cluster com-
puting library that focuses on in-memory high performance MapRe-
duce and related operations. Blaze introduces three main improve-
ments to the MapReduce algorithm: eager reduction, fast serializa-
tion, and special treatment for a small fixed key range. Section 2.3
provides a detailed description of these improvements.
We apply Blaze to several common data mining tasks, including
word frequency count, PageRank, k-means, expectation maximiza-
tion (Gaussian mixture), and k-nearest neighbors. Our results show
that Blaze is on average 10 times faster than Spark on these tasks.
The main contributions of this research are listed as follows:
(1) We develop Blaze, a high performance cluster computing
library that allows users to write parallel programs with the
high-level MapReduce abstraction while achieving similar
performance as hand-optimized code for compute intensive
tasks.
(2) We introduce three main performance improvements to the
MapReduce algorithm to make it more eﬃcient: eager re-
duction, fast serialization, and special treatment for a small
fixed key range.
(3) We apply Blaze to 5 common data mining tasks and demon-
strate that Blaze programs are easy to develop and can out-
perform Apache Spark programs by more than 10 times on
average for these tasks.
The remaining sections are organized as follows: Section 2 de-
scribes the Blaze framework and the details of the optimization.
Section 3 present the details of how we implement several key data
mining and machine learning algorithms with Blaze and compare
the performance with Apache Spark. Section 4 concludes the pa-
per.
2 THE BLAZE LIBRARY
The Blaze library oﬀers three sets of APIs: 1) a high-performance
MapReduce function, 2) distributed data containers, and 3) par-
allel computing utility functions. These APIs are built based on
the Blaze parallel computing kernel, which provides common low-
level parallel computing primitives.
2.1 Distributed Containers
Blaze provides three distributed data containers: DistRange, DistVec-
tor, and DistHashMap. DistRange does not store the whole data but
only the start, the end, and the step size of the data. DistVector dis-
tributedly stores an array of elements. DistHashMap distributedly
stores key/value pairs.
All of the three containers support the foreach operation, where
a custom function can be applied to each of its element in parallel.
This function can either change the value of the element itself or
use the value of the element to perform external operations.
Both the DistVector and the DistHashMap can be converted to
and from C++ standard library containers with Blaze utility func-
tions distribute and collect. DistVector can also be created
from the load_file utility function, which can load text files from
the file system parallelly into a distributed vector of lines.
DistVector also has a topk method, which can return the top k
elements from the distributedly stored vector in O(n k log k) time
and O(k) space. Users can provide a custom comparison function
to determine the priority of the elements.
2.2 MapReduce
The MapReduce function uses a functional style interface. It takes
four parameters:
(1) Input. One of the Blaze distributed container.
(2) Mapper. When the input is a DistRange, the mapper should
be a function that accepts two parameters: a value from the
DistRange and a handler function for emitting key/value
pairs. When the input is a DistVector or a DistHashMap, the
mapper should be a function that accepts three parameters:
a key from the input, the corresponding value, and an emit
handler.
(3) Reducer. The function that reduce two values to one value.
Blaze provides several built-in reducers, including sum, prod
, min, and max, which can cover most use cases. These reduc-
ers can be used by providing the reducer name as a string,
for example, "sum". Users can also provide custom reduce
functions, which should take two parameters, the first one is
a reference to the existing value which needs to be updated,
and the second one is a constant reference to the new value.
(4) Target. One of the Blaze distributed container or a vector
from the standard library. The target container should be
mutable and it is not cleared before performing MapReduce.
New results from the MapReduce operation are merged/re-
duced into the target container.
Blaze MapReduce also takes care of the serialization of common
data types so that the map function can emit non-string key/value
pairs, and the reduce function no longer requires additional logic
for parsing the serialized data. Using custom data types as keys
or values is also supported. For that, users only need to provide
the corresponding serialize/parse methods and a hash function (for
keys).
We provide two examples of using Blaze MapReduce in Appen-
dix A.1 and A.2.
2Map Map
Original MapReduce
Map Shuffle
Map Reduce
Map Map
Blaze MapReduce
Map Shuffle
thread cache
Map Reduce
Figure3: EagerReductionin BlazeMapReduce.
2.3 Optimization
We introduce several optimizations to make the MapReduce func-
tion faster, including eager reduction, fast serialization, and spe-
cial treatment for cases where the resulting key range is small and
fixed.
2.3.1 EagerReduction. Conventional MapReduce performs the map
phase first and saves all the emitted pair from the mapper function.
Then, it shuﬄes all the emitted pairs across the networks directly,
which could incur a large amount of network traﬃcs.
In Blaze MapReduce, we perform machine-local reduce right af-
ter the mapper function emits a key/value pair. For popular keys,
Blaze automatically reduces new values to a thread-local cache in-
stead of the machine-local copy. The cross-machine shuﬄe oper-
ates on the locally reduced data which substantially reduces the
network communication burden. During the shuﬄe operations, re-
duce functions are also operating asynchronously to maximize the
throughput. Fig. 3 illustrates the diﬀerence between the conven-
tional MapReduce and Blaze MapReduce with eager reduction.
2.3.2 Fast Serialization. During the shuﬄe/reduce phase, we se-
rialize the messages into a compact binary format before casting
them across the network.
Our encoding scheme and algorithm are similar to Google’s Pro-
tobuf [17] but without prefixing each entry with field tags and wire
types. Although these two fields allow missing fields and support
serializing the fields in arbitrary order, this additional flexibility is
not needed in MapReduce. On the other hand, these two fields can
have a significant impact on both the performance and the seri-
alized message size, especially when the content size of a field is
small, which is common for MapReduce key/value pairs. For ex-
ample, when both the key and value are small integers, the serial-
ized message size of each pair from Protocol Buﬀers will be 4 bytes
while the message from Blaze fast serialization will be only 2 bytes,
which is 50% smaller than the one from Protocol Buﬀers. Remov-
ing the fields tags and wire types does not cause ambiguity as long
as we always serialize the fields in the same order, which is easy to
achieve in MapReduce. The smaller size in the serialized message
Table1:MonteCarloPiEstimationPerformance.Wecansee
that Blaze MapReduce has almost the same speed as hand-
optimized MPI+OpenMP parallel for loops while requires
muchfewer sourcelines of code(SLOC).
Samples Blaze MapReduce MPI+OpenMP
107 0.14 ± 0.01 s 0.14 ± 0.01 s
108 1.44 ± 0.07 s 1.42 ± 0.09 s
109 14.2 ± 1.3 s 14.6 ± 1.7 s
SLOC 8 24
means less network traﬃcs, so that Blaze can scale better on large
clusters when the cross-rack bandwidth becomes the bottleneck.
2.3.3 Optimizationfor Small Key Range. For small key range, we
create a thread-local cache for each key at the beginning and set
that as the reduce target during the local map/reduce phase. Af-
ter the local map/reduce phase finished, we perform parallel tree
based reduce operations: first locally and then across multiple ma-
chines. The resulting execution plan is essentially the same as hand-
optimized parallel for loops with thread-local intermediate results.
We benchmark the performance of Blaze MapReduce against
hand-optimized parallel for-loop on the Monte Carlo Pi estimation
task. In this task, the mapper function first generates two random
numbers x and y in the range [0,1], and then emits 1 to key 0
when x2 y2 < 1. Cases like this where we reduce big data to
a small number of keys are commonly seen in data mining and
are not eﬃcient with the original MapReduce algorithm. However,
by using a thread-local copy as the default reduce target for each
thread, Blaze MapReduce can achieve similar performance as hand-
optimized code based on raw MPI and OpenMP. Table 1 reports
the result and Appendix A.2 lists our implementation. The tests
are performed on a local machine with Ubuntu 16.04, GCC 5.4 -O3,
and an Intel i7-8550U processor.
3 APPLICATIONS
In this section, we benchmark Blaze against a popular data min-
ing package Spark, on common data mining tasks, including word
frequency count, PageRank, k-means, expectation maximization
(with the Gaussian Mixture model), and k-nearest neighbors search.
3.1 TaskDescription and Implementation
In this section, we describe the data mining tasks and how we im-
plement them in Blaze and Spark. All the source code of our imple-
mentation is included in our GitHub repository [20].
3.1.1 Word Frequency Count. This task counts the number of oc-
currences of each unique English words in a text file. We use the
Bible and Shakespeare’s works as the testing text. Since Spark has
significant overhead in starting the MapReduce tasks, we repeat
the Bible and the Shakespeare 200 times, so that the input file con-
tains about 0.4 billion words.
3We use MapReduce in both Blaze and Spark. The mapper func-
tion takes a single line and emits multiple (word, 1) pairs. The re-
ducer function sums the values. Appendix A.1 contains the full
Blaze implementation for this example.
3.1.2 PageRank. This task calculates the PageRank score, which
is defined as the stationary value of the following equation:
PR(pi ) 1− d
N
d
pj∈M(pi)
PR(pj )
L(pj ) (1)
where M(pi ) is the set of pages that link to pi , L(pj ) is the number
of outbound links from page pj, N is the total number of pages, and
d 0.15. When a page has no outbound links, it is called a sink
and is assumed to connect to all the pages. We use the graph500
generator to generate the input graph which contains 10 million
links. We set the convergence criterion to 10−5, which results in 27
iterations for our input. The links are stored distributedly across
multiple machines.
For Blaze, we use 3 MapReduce operations per iteration to im-
plement this task. The first one calculates the total score of all the
sinks. The second one calculates the new PageRank scores accord-
ing to Eq. 1. The third one calculates the maximum change in the
scores of all the pages. For Spark, we use the built-in PageRank
module from the Spark GraphX library [27].
3.1.3 K-Means. K-Means is a popular clustering algorithm. The al-
gorithm proceeds by alternating two steps until the convergence.
The first step is the assignment step where each point is assigned
to the nearest clustering center. The second step is the refinement
step where each clustering center is updated based on the new
mean of the points assigned to the clustering center.
We generate 100 million random points around 5 clustering cen-
ters as the testing data, and use the same initial model and conver-
gence criteria for Spark and Blaze. The points are stored distribut-
edly across multiple machines.
For Blaze, we use a single MapReduce operation to perform the
assignment step. The update step is implemented in serial. For
Spark, we use the built-in implementation from the Spark MLlib
library [25].
3.1.4 Expectation Maximization. This task uses the expectation
maximization method to train the Gaussian Mixture clustering model
(GMM). Starting from an initial model, we first calculate the Gauss-
ian probability density of each point for each Gaussian component
pk x |θk
1
1
e−
2 (x − µk)TΣ−1
k (x − µk) (2)
(2π )d /2 |Σk |1/2
where µ1 to µK are the centers of these Gaussian components and
Σ1 to ΣK are the covariance matrices. Then we calculate the mem-
bership of each point for each Gaussian component
wik
pk xi |θk· αk
K
m 1 pm xi |θm· αm
(3)
where αk is the weights of the Gaussian component. Next, we cal-
culate the sum of membership weights for each Gaussian compo-
nent Nk ΣK
i 1wik . After that, we update the parameters of the
Gaussian mixtures
Nk
αk
N (4)
µk
1
Nk
N
wik xi (5)
i 1
Σk
1
Nk
K
wik x − µk
T
x − µk (6)
i 1
Finally, we calculate the log-likelihood of the current model for
these points to determine whether the process is converged.
N
i 1
log p xi |Θ
N
i 1
log
K
k 1
αk pk xi |θk (7)
We generate 1 million random points around 5 clustering cen-
ters as the testing data and use the same initial model and conver-
gence criteria for Spark and Blaze. The points are stored distribut-
edly across multiple machines.
For Blaze, we implement this algorithm with 6 MapReduce op-
erations per iteration. The first MapReduce calculates the probabil-
ity density according to Eq. 2. The second MapReduce calculates
the membership according to Eq. 3. The third MapReduce accumu-
lates the sum of memberships for each Gaussian component Nk.
The next two MapReduce perform the summations in Eq. 5 and
Eq. 6. The last MapReduce calculates the log-likelihood according
to Eq. 7. For Spark, we use the built-in implementation from the
Spark MLlib library [25].
3.1.5 Nearest 100 Neighbors. In this task, we find the 100-nearest
neighbors of a point from a huge set of other points. This is a com-
mon procedure in data analysis and recommendation systems. We
use 200 million random points for this test.
For both Spark and Blaze, we implement this task with the topk
function of the corresponding distributed containers and provide
custom comparison functions to determine the relative priority of
two points based on the Euclidean-distance.
3.2 Performance Analysis
We test the performance of both Spark and Blaze for the above
tasks on Amazon Web Services (AWS). The time for loading data
from the file system is not included in our measurements. Spark is
explicitly set to use the MEMORY_ONLY mode and we choose memory-
optimized instances r5.xlarge as our testing environments which
have large enough memory for Spark to complete our tasks. Each
r5.xlarge has 4 logical cores, 32GB memory, and up to 10 Gbps net-
work performance.
For Spark, we use the AWS Elastic MapReduce (EMR) service
version 5.20.0 , which comes with Spark 2.4.0. Since in the default
setting, Spark changes the number of executors on the fly, which
may obscure the results, we set the environment variable for max-
imizing resource allocation to true to avoid the change. We also
manually specify the number of partitions to 100 to force the cross-
executor shuﬄe on the entire cluster. For Blaze, we use GCC 7.3
with -O3 optimization and MPICH 3.2. For both Spark and Blaze,
we perform warmup runs before counting the timings. Timings are
converted to more meaningful results for each task.
4Wordcount Performance
words / second (in millions)
350
300
250
200
150
100
50
0
Spark
Blaze
Blaze TCM
2 4 8 16
number of nodes
Figure 4: Performance of the word frequency count mea-
suredin thenumberof words processedpersecond.
Pagerank Performance
links / second / iteration (in millions)
100
80
60
40
20
0
Spark (GraphX)
Blaze
Blaze TCM
2 4 8 16
number of nodes
Figure5:PerformanceofthePageRankalgorithmmeasured
in numberof links processedpersecondperiteration.
K-Means Performance
points / second / iteration (in millions)
300
250
200
150
100
50
0
Spark (MLlib)
Blaze
Blaze TCM
2 4 8 16
number of nodes
Figure 6: Performance of the K-Means algorithm measured
inthe numberof points processedpersecondperiteration.
Expectation Maximization (GMM) Performance
points / second / iteration (in millions)
25
20
15
10
5
0
Spark (MLlib)
Blaze
Blaze TCM
2 4 8 16
number of nodes
Figure 7: Performance of the Expectation Maximization al-
gorithm for the Gaussian Mixture Model measured in the
numberof points processedpersecondperiteration.
The detailed performance comparison are shown in Fig. 4 to 8.
“Spark”, “Spark (MLlib)”, “Spark (GraphX)”, “Blaze”, “Blaze TCM”
denote the original Spark implementation, the MLlib library in
Spark, the GraphX library in Spark, original Blaze, and Blaze linked
with Thread-Caching Malloc (TCMalloc), respectively.
As shown in Fig. 4 to 8, Blaze outperforms Spark significantly on
all five data mining applications. On average, Blaze is more than 10
times faster than Spark. The superior performance of Blaze shows
that our highly-optimized implementation suits these data mining
applications well. The performance diﬀerence between Blaze and
Blaze TCM is negligible. However, without using TCMalloc, the
performance has more fluctuations and can occasionally experi-
ence a significant drop of up to 30%.
3.3 Memory Consumption
We measure the memory consumption for running these tasks on a
single local machine of 12 logical cores, using the same versions for
all the software as the tests on AWS. As shown in Fig 9, we can see
that both Blaze and Blaze TCM consumes much smaller amount of
memory than Spark during the runs, especially for PageRank, K-
Means, and expectation maximization (GMM), where Spark uses
10 times more memory than Blaze. The only case where the mem-
ory consumption between Spark and Blaze is close is the k-nearest
neighbors search, which does not involve intermediate key/value
pairs.
The memory consumption between Blaze and Blaze TCM are
always on the same order of magnitude, although in one case, Blaze
consumes 40% more memory when linked against TCMalloc.
3.4 Cognitive Load
Cognitive load refers to the eﬀorts needed to develop or under-
stand the code. Minimizing the cognitive load is the ultimate goal
that MapReduce and its variants try to achieve.
5Nearest 100 Neighbors Performance
points / second (in millions)
2000
1750
1500
1250
1000
750
500
250
0
Spark
Blaze
Blaze TCM
2 4 8 16
number of nodes
Figure 8: Performance of the Nearest 100 Neighbors search
measured in the number of total points processed per sec-
ond.
Peak Memory Usage
Spark
Memory (GB)
25
20
15
10
5
0
Blaze
Blaze TCM
Wordcount Pagerank K-Means EM GMM NN100
Figure9: Peakmemoryusageona singlenode.
There are lots of diﬀerent measures for cognitive eﬀorts. Source
lines of code is not a good measure here as Spark/Scala supports
chaining functions and can put several consecutive operations on
a single line. Hence, a line of Spark/Scala may be much more diﬃ-
cult to understand than a line of C++. Here we use the number of
distinct APIs used as the indicator for cognitive load. It is a legiti-
mate indicator because people will have to do more searches and
remember more APIs when a library requires more distinct API
calls to accomplish a task.
Spark’s built-in implementation uses about 30 diﬀerent parallel
primitives for diﬀerent tasks, while Blaze only uses the MapReduce
function and less than 5 utility functions. We can see from Fig. 10
that the cognitive load of using Blaze is much smaller than using
Spark.
Cognitive Load (Less is Better)
Spark
Distinct APIs Used
16
14
12
10
8
6
4
2
0
Blaze
Wordcount Pagerank K-Means EM GMM NN100
Figure 10: Cognitive load comparison between Blaze and
Spark.
4 CONCLUSION
Blaze provides a high performance implementation of MapReduce.
Users can write parallel programs with Blaze’s high-level MapRe-
duce abstraction and achieve similar performance as the hand-optimized
parallel code.
We use Blaze to implement 5 common data mining algorithms.
By writing only a few lines of serial code and apply the Blaze
MapReduce function, we achieve over 10 times higher performance
than Spark on these compute intensive tasks, even though we only
use the MapReduce function and 3 utility functions in our Blaze im-
plementation while Spark uses almost 30 diﬀerent parallel primi-
tives for diﬀerent tasks in its oﬃcial implementation.
The high-level abstraction and the high performance makes Blaze
an appealing choice for compute intensive tasks in data mining and
related fields.
5 ACKNOWLEDGEMENTS
This work is supported by the U.S. National Science Foundation
(NSF) grant ACI-1534965 and the Air Force Oﬃce of Scientific Re-
search (AFOSR) grant FA9550-18-1-0095. We also thank professor
Cyrus Umrigar for the helpful suggestions for the paper.
REFERENCES
[1] Foto N Afrati and Jeﬀrey D Ullman. 2010. Optimizing joins in a map-reduce
environment. In Proceedings of the 13th International Conference on Extending
Database Technology. ACM, 99–110.
[2] Prajesh P Anchalia, Anjan K Koundinya, and NK Srinath. 2013. MapReduce
design of K-means clustering algorithm. In InformationScienceandApplications
(ICISA), 2013International Conference on. IEEE, 1–5.
[3] Prajesh P Anchalia and Kaushik Roy. 2014. The k-nearest neighbor algorithm
using MapReduce paradigm. In Intelligent Systems, Modelling and Simulation
(ISMS), 20145th International Conferenceon. IEEE, 513–518.
[4] Bahman Bahmani, Kaushik Chakrabarti, and Dong Xin. 2011. Fast personalized
pagerank on mapreduce. In Proceedings of the 2011 ACM SIGMOD International
Conference onManagement of data. ACM, 973–984.
[5] Pramod Bhatotia, Alexander Wieder, Rodrigo Rodrigues, Umut A Acar, and
Rafael Pasquin. 2011. Incoop: MapReduce for incremental computations. In Pro-
ceedings ofthe 2nd ACMSymposium onCloud Computing. ACM, 7.
[6] Craig Chambers, Ashish Raniwala, Frances Perry, Stephen Adams, Robert R
Henry, Robert Bradshaw, and Nathan Weizenbaum. 2010. FlumeJava: easy, eﬃ-
cient data-parallel pipelines. In ACMSigplan Notices, Vol. 45. ACM, 363–375.
6[7] Cheng-Tao Chu, Sang K Kim, Yi-An Lin, YuanYuan Yu, Gary Bradski, Kunle
Olukotun, and Andrew Y Ng. 2007. Map-reduce for machine learning on multi-
core. In Advances in neural informationprocessingsystems. 281–288.
[8] Tyson Condie, Neil Conway, Peter Alvaro, Joseph M Hellerstein, Khaled Elmele-
egy, and Russell Sears. 2010. MapReduce online.. In Nsdi, Vol. 10. 20.
[9] Xiaoli Cui, Pingfei Zhu, Xin Yang, Keqiu Li, and Changqing Ji. 2014. Optimized
big data K-means clustering using MapReduce. The Journal of Supercomputing
70, 3 (2014), 1249–1259.
[10] Jeﬀrey Dean and Sanjay Ghemawat. 2008. MapReduce: simplified data process-
ing on large clusters. Commun.ACM 51, 1 (2008), 107–113.
[11] Jeﬀrey Dean and Sanjay Ghemawat. 2010. MapReduce: a flexible data processing
tool. Commun.ACM 53, 1 (2010), 72–77.
[12] Jaliya Ekanayake, Hui Li, Bingjing Zhang, Thilina Gunarathne, Seung-Hee Bae,
Judy Qiu, and Geoﬀrey Fox. 2010. Twister: a runtime for iterative mapreduce.
In Proceedings of the 19th ACM international symposium on high performance
distributed computing. ACM, 810–818.
[13] Jaliya Ekanayake, Shrideep Pallickara, and Geoﬀrey Fox. 2008. Mapreduce for
data intensive scientific analyses. In eScience, 2008. eScience’08. IEEE Fourth In-
ternational Conference on. IEEE, 277–284.
[14] Apache Software Foundation. 2019. Apache Hadoop.
https://hadoop.apache.org/. Accessed: 2019-02-01.
[15] Apache Software Foundation. 2019. Apache Spark - Unified Analytics Engine
for Big Data. https://spark.apache.org/. Accessed: 2019-02-01.
[16] Inigo Goiri, Ricardo Bianchini, Santosh Nagarakatte, and Thu D Nguyen. 2015.
Approxhadoop: Bringing approximations to mapreduce frameworks. In ACM
SIGARCH ComputerArchitectureNews, Vol. 43. ACM, 383–397.
[17] Google. 2019. Protocol Buﬀers. https://developers.google.com/protocol-buﬀers/.
Accessed: 2019-02-01.
[18] Satish Gopalani and Rohan Arora. 2015. Comparing apache spark and map re-
duce with performance analysis using k-means. Internationaljournalofcomputer
applications 113, 1 (2015).
[19] Bingsheng He, Wenbin Fang, Qiong Luo, Naga K Govindaraju, and Tuyong
Wang. 2008. Mars: a MapReduce framework on graphics processors. In Parallel
Architecturesand Compilation Techniques (PACT), 2008 International Conference
on. IEEE, 260–269.
[20] Junhao Li. 2019. Blaze. https://github.com/junhao12131/blaze. Accessed: 2019-
02-01.
[21] Songze Li, Mohammad Ali Maddah-Ali, and A Salman Avestimehr. 2015. Coded
mapreduce. In Communication,Control,and Computing(Allerton),201553rdAn-
nual Allerton Conferenceon. IEEE, 964–971.
[22] Wei Lu, Yanyan Shen, Su Chen, and Beng Chin Ooi. 2012. Eﬃcient processing of
k nearest neighbor joins using mapreduce. Proceedings ofthe VLDBEndowment
5, 10 (2012), 1016–1027.
[23] Jesús Maillo, Isaac Triguero, and Francisco Herrera. 2015. A mapreduce-
based k-nearest neighbor approach for big data classification. In Trustcom/Big-
DataSE/ISPA,2015IEEE, Vol. 2. IEEE, 167–172.
[24] Cascading maintainers. 2019. Cascading. https://www.cascading.org/. Accessed:
2019-02-01.
[25] Xiangrui Meng, Joseph Bradley, Burak Yavuz, Evan Sparks, Shivaram Venkatara-
man, Davies Liu, Jeremy Freeman, DB Tsai, Manish Amde, Sean Owen, et al.
2016. Mllib: Machine learning in apache spark. TheJournalofMachineLearning
Research 17, 1 (2016), 1235–1241.
[26] Steven J Plimpton and Karen D Devine. 2011. MapReduce in MPI for large-scale
graph algorithms. Parallel Comput.37, 9 (2011), 610–632.
[27] Reynold S Xin, Joseph E Gonzalez, Michael J Franklin, and Ion Stoica. 2013.
Graphx: A resilient distributed graph system on spark. In First International
Workshopon Graph DataManagement Experiencesand Systems. ACM, 2.
[28] Hung-chih Yang, Ali Dasdan, Ruey-Lung Hsiao, and D Stott Parker. 2007. Map-
reduce-merge: simplified relational data processing on large clusters. In Proceed-
ings of the 2007 ACM SIGMOD international conference on Management of data.
ACM, 1029–1040.
[29] Takuya Yokoyama, Yoshiharu Ishikawa, and Yu Suzuki. 2012. Processing all
k-nearest neighbor queries in hadoop. In International Conference on Web-Age
Information Management. Springer, 346–351.
[30] Matei Zaharia, Mosharaf Chowdhury, Tathagata Das, Ankur Dave, Justin Ma,
Murphy McCauley, Michael J Franklin, Scott Shenker, and Ion Stoica. 2012. Re-
silient distributed datasets: A fault-tolerant abstraction for in-memory cluster
computing. In Proceedings of the 9th USENIX conference on Networked Systems
Designand Implementation. USENIX Association, 2–2.
[31] Matei Zaharia, Mosharaf Chowdhury, Michael J Franklin, Scott Shenker, and Ion
Stoica. 2010. Spark: Cluster computing with working sets. HotCloud 10, 10-10
(2010), 95.
[32] Matei Zaharia, Andy Konwinski, Anthony D Joseph, Randy H Katz, and Ion Sto-
ica. 2008. Improving MapReduce performance in heterogeneous environments..
In Osdi, Vol. 8. 7.
[33] Matei Zaharia, Reynold S Xin, Patrick Wendell, Tathagata Das, Michael Arm-
brust, Ankur Dave, Xiangrui Meng, Josh Rosen, Shivaram Venkataraman,
Michael J Franklin, et al. 2016. Apache spark: a unified engine for big data pro-
cessing. Commun.ACM 59, 11 (2016), 56–65.
[34] Weizhong Zhao, Huifang Ma, and Qing He. 2009. Parallel k-means cluster-
ing based on mapreduce. In IEEE International Conference on Cloud Computing.
Springer, 674–679.
7A EXAMPLES
In this section, we provide two examples to illustrate the usage of
Blaze. All the source code of our implementation is included in our
GitHub repository [20].
A.1 Word frequency count
In this example, we count the number of occurrences of each unique
word in an input file with Blaze MapReduce. We save the results in
a distributed hash map, which can be used for further processing.
To compile this example, you can clone our repository [20], go
to the example folder and type make wordcount.
#include <blaze/blaze.h>
#include <iostream>
int main(int argc, char** argv) {
blaze::util::init(argc, argv);
// Load file into distributed container.
auto lines =
blaze::util::load_file("filepath...");
// Define mapper function.
const auto& mapper = [&](
const size_t, // Line id.
const std::string& line,
const auto& emit) {
// Split line into words.
std::stringstream ss(line);
std::string word;
while (getline(ss, word, ' ')) {
emit(word, 1);
}
};
// Define target hash map.
blaze::DistHashMap<std::string, size_t> words;
// Perform mapreduce.
blaze::mapreduce<
std::string, std::string, size_t>(
lines, mapper, "sum", words);
// Output number of unique words.
std::cout << words.size() << std::endl;
return 0;
}
A.2 MonteCarloPi Estimation
In this example, we present a MapReduce implementation of the
Monte Carlo π estimation.
To compile this example, you can clone our repository [20], go
to the example folder and type make pi.
#include <blaze/blaze.h>
#include <iostream>
int main(int argc, char** argv) {
blaze::util::init(argc, argv);
const size_t N_SAMPLES = 1000000;
// Define source.
blaze::DistRange<size_t> samples(0, N_SAMPLES);
// Define mapper.
const auto& mapper =
[&](const size_t, const auto& emit) {
// Random function in std is not thread safe.
double x = blaze::random::uniform();
double y = blaze::random::uniform();
// Map points within circle to key 0.
if (x * x + y * y < 1) emit(0, 1);
};
// Define target.
std::vector<size_t> count(1); // {0}
// Perform MapReduce.
blaze::mapreduce<size_t, size_t>(
samples, mapper, "sum", count);
std::cout << 4.0 * count[0] / N_SAMPLES
<< std::endl;
return 0;
}
In conventional MapReduce implementations, mapping big data
onto a single key is usually slow and consumes a large amount of
memory during the map phase. Hence, in practice, people usually
hand-code parallel for loops in such situations. However, by using
Blaze, the above code has similar memory consumption and per-
formance as the hand-optimized parallel for loops. In short, Blaze
frees users from dealing with low-level data communications while
ensuring high performance.
8

and use deepwiki to maxx out performance too ask questions , think of them with the sequential thinking toola nd then go ham with the deepwiki tool