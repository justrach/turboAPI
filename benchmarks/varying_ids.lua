-- wrk lua script: requests /users/{1-100} with varying IDs
-- This prevents cache from helping — every request is a different key
counter = 0

request = function()
    counter = counter + 1
    local id = (counter % 100) + 1
    return wrk.format("GET", "/users/" .. id)
end
