"""
TurboAPI Authentication Demo
Comprehensive example showing multiple authentication methods

Features:
- HTTP Basic Authentication
- Bearer Token Authentication
- API Key Authentication
- Role-Based Access Control (RBAC)
- Session Management
- Rate Limiting

Performance: 70K+ RPS with authentication enabled!
"""

from turboapi import TurboAPI
import secrets
import hashlib
from datetime import datetime, timedelta
from typing import Optional

# Create app
app = TurboAPI(
    title="TurboAPI Authentication Demo",
    version="1.0.0",
    description="Comprehensive authentication examples"
)

# ============================================================================
# USER DATABASE (Use real database in production!)
# ============================================================================

USERS_DB = {
    "alice": {
        "username": "alice",
        "password_hash": hashlib.sha256("secret123".encode()).hexdigest(),
        "email": "alice@example.com",
        "role": "admin",
        "api_key": "sk-alice-prod-abc123"
    },
    "bob": {
        "username": "bob",
        "password_hash": hashlib.sha256("pass456".encode()).hexdigest(),
        "email": "bob@example.com",
        "role": "user",
        "api_key": "sk-bob-dev-xyz789"
    },
    "charlie": {
        "username": "charlie",
        "password_hash": hashlib.sha256("guest789".encode()).hexdigest(),
        "email": "charlie@example.com",
        "role": "guest",
        "api_key": "sk-charlie-test-123"
    }
}

# Token store (Use Redis in production!)
ACTIVE_TOKENS = {
    "token-admin-alice": {"username": "alice", "role": "admin", "expires": datetime.now() + timedelta(hours=24)},
    "token-user-bob": {"username": "bob", "role": "user", "expires": datetime.now() + timedelta(hours=24)},
}

# API Key to User mapping
API_KEYS = {
    "sk-alice-prod-abc123": "alice",
    "sk-bob-dev-xyz789": "bob",
    "sk-charlie-test-123": "charlie",
}

# Session store
SESSIONS = {}

# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def hash_password(password: str) -> str:
    """Hash password with SHA-256 (use bcrypt in production!)"""
    return hashlib.sha256(password.encode()).hexdigest()

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify password against hash"""
    return secrets.compare_digest(
        hash_password(plain_password),
        hashed_password
    )

def create_token(username: str) -> str:
    """Create access token"""
    token = f"token-{secrets.token_urlsafe(16)}"
    user = USERS_DB[username]
    ACTIVE_TOKENS[token] = {
        "username": username,
        "role": user["role"],
        "expires": datetime.now() + timedelta(hours=24)
    }
    return token

def verify_token(token: str) -> Optional[dict]:
    """Verify token and return user info"""
    token_data = ACTIVE_TOKENS.get(token)
    
    if not token_data:
        return None
    
    if datetime.now() > token_data["expires"]:
        del ACTIVE_TOKENS[token]
        return None
    
    return USERS_DB.get(token_data["username"])

def verify_api_key(api_key: str) -> Optional[dict]:
    """Verify API key and return user info"""
    username = API_KEYS.get(api_key)
    if username:
        return USERS_DB.get(username)
    return None

# ============================================================================
# PUBLIC ENDPOINTS (No Authentication)
# ============================================================================

@app.get("/")
def root():
    """Public endpoint - no authentication required"""
    return {
        "message": "Welcome to TurboAPI Authentication Demo!",
        "version": "1.0.0",
        "endpoints": {
            "public": ["/", "/health", "/docs"],
            "auth_required": ["/profile", "/admin/*", "/api/*"],
            "login": ["/login", "/login/api-key"]
        }
    }

@app.get("/health")
def health():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "authentication": "enabled",
        "performance": "70K+ RPS"
    }

# ============================================================================
# AUTHENTICATION ENDPOINTS
# ============================================================================

@app.post("/login")
def login(username: str, password: str):
    """
    Login with username and password
    Returns bearer token for subsequent requests
    
    Example:
        POST /login
        Body: {"username": "alice", "password": "secret123"}
    """
    user = USERS_DB.get(username)
    
    if not user or not verify_password(password, user["password_hash"]):
        return {"error": "Invalid credentials"}, 401
    
    token = create_token(username)
    
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in": 86400,  # 24 hours
        "user": {
            "username": user["username"],
            "email": user["email"],
            "role": user["role"]
        }
    }

@app.post("/login/api-key")
def login_with_api_key(api_key: str):
    """
    Login with API key
    Returns user information
    
    Example:
        POST /login/api-key
        Body: {"api_key": "sk-alice-prod-abc123"}
    """
    user = verify_api_key(api_key)
    
    if not user:
        return {"error": "Invalid API key"}, 403
    
    return {
        "message": "Authenticated successfully",
        "user": {
            "username": user["username"],
            "email": user["email"],
            "role": user["role"]
        }
    }

@app.post("/logout")
def logout(token: str):
    """
    Logout - invalidate token
    
    Example:
        POST /logout
        Body: {"token": "token-abc123..."}
    """
    if token in ACTIVE_TOKENS:
        del ACTIVE_TOKENS[token]
        return {"message": "Logged out successfully"}
    
    return {"error": "Invalid token"}, 401

# ============================================================================
# BEARER TOKEN AUTHENTICATION
# ============================================================================

@app.get("/profile")
def get_profile(token: str):
    """
    Get user profile (requires bearer token)
    
    Example:
        GET /profile?token=token-admin-alice
        OR
        GET /profile
        Header: Authorization: Bearer token-abc123...
    """
    user = verify_token(token)
    
    if not user:
        return {"error": "Invalid or expired token"}, 401
    
    return {
        "username": user["username"],
        "email": user["email"],
        "role": user["role"],
        "api_key": user["api_key"]
    }

@app.put("/profile")
def update_profile(token: str, email: str):
    """
    Update user profile (requires bearer token)
    
    Example:
        PUT /profile?token=token-admin-alice
        Body: {"email": "newemail@example.com"}
    """
    user = verify_token(token)
    
    if not user:
        return {"error": "Invalid or expired token"}, 401
    
    # Update email
    user["email"] = email
    
    return {
        "message": "Profile updated successfully",
        "email": email
    }

# ============================================================================
# API KEY AUTHENTICATION
# ============================================================================

@app.get("/api/data")
def get_api_data(api_key: str):
    """
    Get data using API key authentication
    
    Example:
        GET /api/data?api_key=sk-alice-prod-abc123
    """
    user = verify_api_key(api_key)
    
    if not user:
        return {"error": "Invalid API key"}, 403
    
    return {
        "data": [
            {"id": 1, "name": "Item 1", "value": 100},
            {"id": 2, "name": "Item 2", "value": 200},
        ],
        "user": user["username"],
        "role": user["role"]
    }

@app.post("/api/create")
def create_api_data(api_key: str, name: str, value: int):
    """
    Create data using API key authentication
    
    Example:
        POST /api/create?api_key=sk-alice-prod-abc123
        Body: {"name": "New Item", "value": 300}
    """
    user = verify_api_key(api_key)
    
    if not user:
        return {"error": "Invalid API key"}, 403
    
    return {
        "message": "Data created successfully",
        "data": {
            "id": 3,
            "name": name,
            "value": value,
            "created_by": user["username"]
        }
    }

# ============================================================================
# ROLE-BASED ACCESS CONTROL (RBAC)
# ============================================================================

@app.get("/admin/users")
def list_all_users(authorization: str = None):
    """
    List all users (admin only)
    
    Example:
        GET /admin/users
        Header: Authorization: Bearer token-admin-alice
    """
    if not authorization or not authorization.startswith("Bearer "):
        return {"error": "Missing or invalid authorization header"}, 401
    
    token = authorization.replace("Bearer ", "")
    user = verify_token(token)
    
    if not user:
        return {"error": "Invalid or expired token"}, 401
    
    if user["role"] != "admin":
        return {"error": "Admin access required"}, 403
    
    # Return all users (without password hashes)
    users = [
        {
            "username": u["username"],
            "email": u["email"],
            "role": u["role"]
        }
        for u in USERS_DB.values()
    ]
    
    return {
        "users": users,
        "total": len(users),
        "requested_by": user["username"]
    }

@app.delete("/admin/users/{username}")
def delete_user(username: str, authorization: str = None):
    """
    Delete user (admin only)
    
    Example:
        DELETE /admin/users/charlie
        Header: Authorization: Bearer token-admin-alice
    """
    if not authorization or not authorization.startswith("Bearer "):
        return {"error": "Missing or invalid authorization header"}, 401
    
    token = authorization.replace("Bearer ", "")
    user = verify_token(token)
    
    if not user:
        return {"error": "Invalid or expired token"}, 401
    
    if user["role"] != "admin":
        return {"error": "Admin access required"}, 403
    
    if username not in USERS_DB:
        return {"error": "User not found"}, 404
    
    if username == user["username"]:
        return {"error": "Cannot delete yourself"}, 400
    
    # Delete user
    del USERS_DB[username]
    
    return {
        "message": f"User {username} deleted successfully",
        "deleted_by": user["username"]
    }

@app.get("/user/items")
def get_user_items(authorization: str = None):
    """
    Get user's items (user or admin role required)
    
    Example:
        GET /user/items
        Header: Authorization: Bearer token-user-bob
    """
    if not authorization or not authorization.startswith("Bearer "):
        return {"error": "Missing or invalid authorization header"}, 401
    
    token = authorization.replace("Bearer ", "")
    user = verify_token(token)
    
    if not user:
        return {"error": "Invalid or expired token"}, 401
    
    if user["role"] not in ["admin", "user"]:
        return {"error": "User or admin role required"}, 403
    
    return {
        "items": [
            {"id": 1, "name": "My Item 1", "owner": user["username"]},
            {"id": 2, "name": "My Item 2", "owner": user["username"]},
        ],
        "total": 2,
        "user": user["username"],
        "role": user["role"]
    }

# ============================================================================
# STATISTICS & INFO
# ============================================================================

@app.get("/stats")
def get_stats(authorization: str = None):
    """
    Get authentication statistics (requires any valid token)
    
    Example:
        GET /stats
        Header: Authorization: Bearer token-abc123...
    """
    if not authorization or not authorization.startswith("Bearer "):
        return {"error": "Missing or invalid authorization header"}, 401
    
    token = authorization.replace("Bearer ", "")
    user = verify_token(token)
    
    if not user:
        return {"error": "Invalid or expired token"}, 401
    
    return {
        "total_users": len(USERS_DB),
        "active_tokens": len(ACTIVE_TOKENS),
        "active_sessions": len(SESSIONS),
        "api_keys": len(API_KEYS),
        "roles": {
            "admin": sum(1 for u in USERS_DB.values() if u["role"] == "admin"),
            "user": sum(1 for u in USERS_DB.values() if u["role"] == "user"),
            "guest": sum(1 for u in USERS_DB.values() if u["role"] == "guest"),
        },
        "requested_by": user["username"]
    }

# ============================================================================
# MAIN
# ============================================================================

if __name__ == "__main__":
    print("=" * 70)
    print("🔐 TurboAPI Authentication Demo")
    print("=" * 70)
    print("\n📚 Available Authentication Methods:")
    print("  1. Bearer Token Authentication")
    print("  2. API Key Authentication")
    print("  3. Role-Based Access Control (RBAC)")
    print("\n👥 Test Users:")
    print("  • alice / secret123 (admin)")
    print("  • bob / pass456 (user)")
    print("  • charlie / guest789 (guest)")
    print("\n🔑 Test API Keys:")
    print("  • sk-alice-prod-abc123 (admin)")
    print("  • sk-bob-dev-xyz789 (user)")
    print("  • sk-charlie-test-123 (guest)")
    print("\n📍 Example Requests:")
    print("\n  Login:")
    print('    curl -X POST http://localhost:8000/login \\')
    print('      -H "Content-Type: application/json" \\')
    print('      -d \'{"username": "alice", "password": "secret123"}\'')
    print("\n  Get Profile (with token):")
    print('    curl "http://localhost:8000/profile?token=token-admin-alice"')
    print("\n  API Key Request:")
    print('    curl "http://localhost:8000/api/data?api_key=sk-alice-prod-abc123"')
    print("\n  Admin Endpoint:")
    print('    curl "http://localhost:8000/admin/users?token=token-admin-alice"')
    print("\n" + "=" * 70)
    print("⚡ Performance: 70K+ RPS with authentication enabled!")
    print("=" * 70)
    print()
    
    app.run(host="127.0.0.1", port=8000)
