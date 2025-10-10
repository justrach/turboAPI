"""
FastAPI-compatible Middleware system for TurboAPI.

Includes:
- CORS (Cross-Origin Resource Sharing)
- Trusted Host (HTTP Host Header attack prevention)
- GZip Compression
- HTTPS Redirect
- Session Management
- Custom Middleware Support
"""

from typing import List, Optional, Callable, Awaitable, Pattern
import gzip
import re
import time
from .models import Request, Response


class Middleware:
    """Base middleware class."""

    def before_request(self, request: Request) -> None:
        """Called before processing the request."""
        pass

    def after_request(self, request: Request, response: Response) -> Response:
        """Called after processing the request."""
        return response

    def on_error(self, request: Request, error: Exception) -> Response:
        """Called when an error occurs."""
        return Response(
            content={"error": "Internal Server Error"},
            status_code=500
        )


class CORSMiddleware(Middleware):
    """
    CORS (Cross-Origin Resource Sharing) middleware.
    
    FastAPI-compatible implementation.
    
    Usage:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["http://localhost:8080"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
    """

    def __init__(
        self,
        allow_origins: List[str] = None,
        allow_methods: List[str] = None,
        allow_headers: List[str] = None,
        allow_credentials: bool = False,
        allow_origin_regex: Optional[str] = None,
        expose_headers: List[str] = None,
        max_age: int = 600,
    ):
        self.allow_origins = allow_origins or ["*"]
        self.allow_methods = allow_methods or ["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH", "HEAD"]
        self.allow_headers = allow_headers or ["*"]
        self.allow_credentials = allow_credentials
        self.allow_origin_regex = re.compile(allow_origin_regex) if allow_origin_regex else None
        self.expose_headers = expose_headers or []
        self.max_age = max_age

    def before_request(self, request: Request) -> None:
        """Handle preflight OPTIONS requests."""
        if request.method == "OPTIONS":
            # Preflight request
            pass

    def after_request(self, request: Request, response: Response) -> Response:
        """Add CORS headers to response."""
        origin = request.headers.get("origin", "")
        
        # Check if origin is allowed
        if self.allow_origin_regex and self.allow_origin_regex.match(origin):
            response.set_header("Access-Control-Allow-Origin", origin)
        elif "*" in self.allow_origins:
            response.set_header("Access-Control-Allow-Origin", "*")
        elif origin in self.allow_origins:
            response.set_header("Access-Control-Allow-Origin", origin)
        
        response.set_header("Access-Control-Allow-Methods", ", ".join(self.allow_methods))
        response.set_header("Access-Control-Allow-Headers", ", ".join(self.allow_headers))
        
        if self.expose_headers:
            response.set_header("Access-Control-Expose-Headers", ", ".join(self.expose_headers))
        
        if self.allow_credentials:
            response.set_header("Access-Control-Allow-Credentials", "true")
        
        response.set_header("Access-Control-Max-Age", str(self.max_age))
        
        return response


class TrustedHostMiddleware(Middleware):
    """
    Trusted Host middleware - prevents HTTP Host Header attacks.
    
    FastAPI-compatible implementation.
    
    Usage:
        app.add_middleware(
            TrustedHostMiddleware,
            allowed_hosts=["example.com", "*.example.com"]
        )
    """
    
    def __init__(
        self,
        allowed_hosts: List[str] = None,
        www_redirect: bool = True,
    ):
        if allowed_hosts is None:
            allowed_hosts = ["*"]
        
        self.allowed_hosts = allowed_hosts
        self.www_redirect = www_redirect
        
        # Compile regex patterns for wildcard hosts
        self.allowed_host_patterns = []
        for host in allowed_hosts:
            if host == "*":
                self.allowed_host_patterns.append(re.compile(".*"))
            else:
                # Convert wildcard to regex
                pattern = host.replace(".", r"\.").replace("*", ".*")
                self.allowed_host_patterns.append(re.compile(f"^{pattern}$"))
    
    def before_request(self, request: Request) -> None:
        """Validate Host header."""
        host = request.headers.get("host", "").split(":")[0]
        
        # Check if host is allowed
        if not any(pattern.match(host) for pattern in self.allowed_host_patterns):
            raise Exception(f"Invalid host header: {host}")


class GZipMiddleware(Middleware):
    """
    GZip compression middleware.
    
    FastAPI-compatible implementation.
    
    Usage:
        app.add_middleware(GZipMiddleware, minimum_size=1000)
    """
    
    def __init__(
        self,
        minimum_size: int = 500,
        compresslevel: int = 9,
    ):
        self.minimum_size = minimum_size
        self.compresslevel = compresslevel
    
    def after_request(self, request: Request, response: Response) -> Response:
        """Compress response if client accepts gzip."""
        accept_encoding = request.headers.get("accept-encoding", "")
        
        if "gzip" not in accept_encoding.lower():
            return response
        
        # Check if response is large enough to compress
        if hasattr(response, 'content'):
            content = response.content
            if isinstance(content, str):
                content = content.encode('utf-8')
            
            if len(content) < self.minimum_size:
                return response
            
            # Compress content
            compressed = gzip.compress(content, compresslevel=self.compresslevel)
            response.content = compressed
            response.set_header("Content-Encoding", "gzip")
            response.set_header("Content-Length", str(len(compressed)))
            response.set_header("Vary", "Accept-Encoding")
        
        return response


class HTTPSRedirectMiddleware(Middleware):
    """
    HTTPS redirect middleware - redirects HTTP to HTTPS.
    
    FastAPI-compatible implementation.
    
    Usage:
        app.add_middleware(HTTPSRedirectMiddleware)
    """
    
    def before_request(self, request: Request) -> None:
        """Redirect HTTP to HTTPS."""
        # Check if request is HTTP
        scheme = request.headers.get("x-forwarded-proto", "http")
        if scheme == "http":
            # Redirect to HTTPS
            https_url = f"https://{request.headers.get('host', '')}{request.path}"
            if request.query_string:
                https_url += f"?{request.query_string}"
            
            raise HTTPSRedirect(https_url)


class HTTPSRedirect(Exception):
    """Exception to trigger HTTPS redirect."""
    def __init__(self, url: str):
        self.url = url


class SessionMiddleware(Middleware):
    """
    Session management middleware.
    
    Usage:
        app.add_middleware(
            SessionMiddleware,
            secret_key="your-secret-key-here",
            session_cookie="session"
        )
    """
    
    def __init__(
        self,
        secret_key: str,
        session_cookie: str = "session",
        max_age: int = 14 * 24 * 60 * 60,  # 14 days
        same_site: str = "lax",
        https_only: bool = False,
    ):
        self.secret_key = secret_key
        self.session_cookie = session_cookie
        self.max_age = max_age
        self.same_site = same_site
        self.https_only = https_only
    
    def before_request(self, request: Request) -> None:
        """Load session from cookie."""
        # TODO: Implement session loading
        request.session = {}
    
    def after_request(self, request: Request, response: Response) -> Response:
        """Save session to cookie."""
        # TODO: Implement session saving
        return response


class RateLimitMiddleware(Middleware):
    """
    Rate limiting middleware.
    
    Usage:
        app.add_middleware(
            RateLimitMiddleware,
            requests_per_minute=60
        )
    """
    
    def __init__(
        self,
        requests_per_minute: int = 60,
        burst: int = 10,
    ):
        self.requests_per_minute = requests_per_minute
        self.burst = burst
        self.requests = {}  # IP -> [(timestamp, count)]
    
    def before_request(self, request: Request) -> None:
        """Check rate limit."""
        client_ip = request.headers.get("x-forwarded-for", "unknown").split(",")[0].strip()
        now = time.time()
        
        # Clean old requests
        if client_ip in self.requests:
            self.requests[client_ip] = [
                (ts, count) for ts, count in self.requests[client_ip]
                if now - ts < 60
            ]
        
        # Count requests in last minute
        if client_ip not in self.requests:
            self.requests[client_ip] = []
        
        request_count = sum(count for _, count in self.requests[client_ip])
        
        if request_count >= self.requests_per_minute:
            raise Exception("Rate limit exceeded")
        
        # Add this request
        self.requests[client_ip].append((now, 1))


class LoggingMiddleware(Middleware):
    """
    Request logging middleware.
    
    Usage:
        app.add_middleware(LoggingMiddleware)
    """

    def before_request(self, request: Request) -> None:
        """Log incoming request."""
        request._start_time = time.time()
        print(f"[REQUEST] {request.method} {request.path}")

    def after_request(self, request: Request, response: Response) -> Response:
        """Log response with timing."""
        duration = time.time() - getattr(request, '_start_time', time.time())
        print(f"[RESPONSE] {request.method} {request.path} -> {response.status_code} ({duration*1000:.2f}ms)")
        return response


class CustomMiddleware(Middleware):
    """
    Custom middleware wrapper for function-based middleware.
    
    Usage:
        @app.middleware("http")
        async def add_process_time_header(request, call_next):
            start_time = time.time()
            response = await call_next(request)
            process_time = time.time() - start_time
            response.headers["X-Process-Time"] = str(process_time)
            return response
    """
    
    def __init__(self, func: Callable):
        self.func = func
    
    async def __call__(self, request: Request, call_next: Callable) -> Response:
        """Execute custom middleware function."""
        return await self.func(request, call_next)
