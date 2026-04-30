-- wrk script: each request hits /user/<random-int>.
-- Intent: defeat any per-path memoization (noargs cache keys on the URL
-- in TurboAPI, routers may also cache last-matched path, etc) so the
-- radix trie lookup + param extraction runs every request.
--
-- Space is intentionally larger than any reasonable LRU cache size.

math.randomseed(os.time())

-- Pre-allocate so we don't churn the request method on every call.
local fmt = string.format

request = function()
    local id = math.random(1, 10000000)
    return wrk.format(nil, fmt("/user/%d", id))
end
