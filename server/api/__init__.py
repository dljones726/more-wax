"""
More'Wax — API handlers.

Each module holds the business logic for a group of JSON endpoints as plain
functions that take already-parsed inputs (request body, query params, path
args) and return ``(status_code, payload)``. The HTTP layer in
``server.handler`` stays a thin router: it parses the request, calls one of
these, and serialises the result. This keeps the handlers unit-testable
without spinning up a socket.

Streaming / file-download endpoints (export, cover-proxy, static files) do not
fit the ``(status, dict)`` shape and remain methods on the Handler.
"""
