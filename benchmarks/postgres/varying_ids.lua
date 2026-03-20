counter = 0
request = function()
  counter = counter + 1
  return wrk.format("GET", "/users/" .. ((counter % 1000) + 1))
end
