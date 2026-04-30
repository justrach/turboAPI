-- wrk script: each request hits /q?id=<random-int>.
-- Same no-cache intent as vary_user_id.lua, but exercises the query-string
-- parsing path instead of the path-param path.

math.randomseed(os.time() + 1)
local fmt = string.format

request = function()
    local id = math.random(1, 10000000)
    return wrk.format(nil, fmt("/q?id=%d", id))
end
