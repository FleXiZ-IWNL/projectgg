"""
Authentication Middleware and Decorators
For Smart Anti-Snoring Pillow System
"""

from functools import wraps
from flask import request, jsonify, session, redirect, url_for
import logging

logger = logging.getLogger(__name__)

class AuthMiddleware:
    """Authentication middleware for Flask"""
    
    def __init__(self, db_manager):
        self.db_manager = db_manager
    
    def get_current_user(self, request):
        """Get current user from session or token"""
        # Check session first
        session_id = session.get('session_id')
        
        # If not in session, check Authorization header
        if not session_id:
            auth_header = request.headers.get('Authorization')
            if auth_header and auth_header.startswith('Bearer '):
                session_id = auth_header.split(' ')[1]
        
        # If not in header, check request body
        if not session_id:
            data = request.get_json(silent=True)
            if data:
                session_id = data.get('session_id')
        
        if not session_id:
            return None
        
        # Validate session
        user_id = self.db_manager.validate_session(session_id)
        if not user_id:
            return None
        
        # Get user data
        user = self.db_manager.get_user_by_id(user_id)
        return user
    
    def require_auth(self, f):
        """Decorator to require authentication"""
        @wraps(f)
        def decorated_function(*args, **kwargs):
            user = self.get_current_user(request)
            
            if not user:
                # Check if this is an API request or page request
                if request.path.startswith('/api/'):
                    return jsonify({
                        "success": False,
                        "error": "Authentication required",
                        "code": "AUTH_REQUIRED"
                    }), 401
                else:
                    return redirect(url_for('login'))
            
            # Add user to request context
            request.current_user = user
            return f(*args, **kwargs)
        
        return decorated_function
    
    def optional_auth(self, f):
        """Decorator for optional authentication"""
        @wraps(f)
        def decorated_function(*args, **kwargs):
            user = self.get_current_user(request)
            request.current_user = user  # Can be None
            return f(*args, **kwargs)
        
        return decorated_function

def get_client_ip(request):
    """Get client IP address"""
    if request.headers.get('X-Forwarded-For'):
        return request.headers.get('X-Forwarded-For').split(',')[0]
    return request.remote_addr

def get_user_agent(request):
    """Get user agent string"""
    return request.headers.get('User-Agent', 'Unknown')
