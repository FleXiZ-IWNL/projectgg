"""
Database Manager for Smart Anti-Snoring Pillow System
Handles all database operations with connection pooling and error handling
Supports both SQLite (local) and PostgreSQL (cloud)
"""

import os
import hashlib
import secrets
import datetime
import logging
from typing import Optional, Dict, Any, List, Tuple
from contextlib import contextmanager
from threading import Lock

logger = logging.getLogger(__name__)

# Try to import PostgreSQL adapter
try:
    import psycopg2
    from psycopg2 import pool, sql
    from psycopg2.extras import RealDictCursor
    POSTGRESQL_AVAILABLE = True
except ImportError:
    POSTGRESQL_AVAILABLE = False
    logger.warning("psycopg2 not available. PostgreSQL support disabled. Install with: pip install psycopg2-binary")

# SQLite import
try:
    import sqlite3
    SQLITE_AVAILABLE = True
except ImportError:
    SQLITE_AVAILABLE = False
    logger.error("sqlite3 not available")

class DatabaseManager:
    """Thread-safe database manager with connection pooling"""
    
    def __init__(self, db_path: str = None, db_type: str = None):
        """
        Initialize database manager
        
        Args:
            db_path: For SQLite: path to database file
                    For PostgreSQL: connection string (DATABASE_URL)
            db_type: 'sqlite' or 'postgresql'. If None, auto-detect from db_path or DATABASE_URL
        """
        self._lock = Lock()
        
        # Auto-detect database type
        if db_type is None:
            # Check environment variable first
            database_url = os.environ.get('DATABASE_URL')
            if database_url and database_url.startswith('postgresql://'):
                db_type = 'postgresql'
                db_path = database_url
            elif database_url and database_url.startswith('postgres://'):
                db_type = 'postgresql'
                db_path = database_url.replace('postgres://', 'postgresql://', 1)
            elif db_path and db_path.startswith('postgresql://'):
                db_type = 'postgresql'
            elif db_path and db_path.startswith('postgres://'):
                db_type = 'postgresql'
                db_path = db_path.replace('postgres://', 'postgresql://', 1)
            else:
                db_type = 'sqlite'
        
        self.db_type = db_type.lower()
        self.db_path = db_path or os.environ.get('DATABASE_URL', 'snore_system.db')
        self.connection_pool = None
        
        if self.db_type == 'postgresql':
            if not POSTGRESQL_AVAILABLE:
                raise ImportError("PostgreSQL support requires psycopg2. Install with: pip install psycopg2-binary")
            self._init_postgresql()
        else:
            if not SQLITE_AVAILABLE:
                raise ImportError("SQLite support not available")
            self._init_sqlite()
        
        logger.info(f"Database initialized: {self.db_type}")
    
    def _init_postgresql(self):
        """Initialize PostgreSQL connection pool"""
        try:
            # Parse connection string
            import urllib.parse as urlparse
            result = urlparse.urlparse(self.db_path)
            
            self.connection_pool = psycopg2.pool.ThreadedConnectionPool(
                minconn=1,
                maxconn=10,
                host=result.hostname,
                port=result.port or 5432,
                database=result.path[1:],  # Remove leading '/'
                user=result.username,
                password=result.password
            )
            logger.info("PostgreSQL connection pool created")
        except Exception as e:
            logger.error(f"Failed to create PostgreSQL connection pool: {str(e)}")
            raise
    
    def _init_sqlite(self):
        """Initialize SQLite (no pooling needed)"""
        # Ensure directory exists
        if self.db_path != ':memory:':
            os.makedirs(os.path.dirname(self.db_path) if os.path.dirname(self.db_path) else '.', exist_ok=True)
        logger.info(f"SQLite database: {self.db_path}")
    
    @contextmanager
    def get_connection(self):
        """Get database connection with context manager"""
        if self.db_type == 'postgresql':
            conn = self.connection_pool.getconn()
            conn.set_session(autocommit=False)
            try:
                yield conn
                conn.commit()
            except Exception as e:
                conn.rollback()
                logger.error(f"Database error: {str(e)}")
                raise
            finally:
                self.connection_pool.putconn(conn)
        else:
            # SQLite
            conn = sqlite3.connect(self.db_path, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            try:
                yield conn
                conn.commit()
            except Exception as e:
                conn.rollback()
                logger.error(f"Database error: {str(e)}")
                raise
            finally:
                conn.close()
    
    def _execute_query(self, query: str, params: tuple = None, fetch_one: bool = False, fetch_all: bool = False):
        """Execute query and return results"""
        with self.get_connection() as conn:
            if self.db_type == 'postgresql':
                cursor = conn.cursor(cursor_factory=RealDictCursor)
            else:
                cursor = conn.cursor()
            
            cursor.execute(query, params or ())
            
            if fetch_one:
                result = cursor.fetchone()
                return dict(result) if result else None
            elif fetch_all:
                results = cursor.fetchall()
                return [dict(row) for row in results]
            else:
                return cursor.lastrowid if self.db_type == 'sqlite' else cursor.rowcount
    
    def hash_password(self, password: str, salt: str = None) -> Tuple[str, str]:
        """Hash password with salt"""
        if salt is None:
            salt = secrets.token_hex(32)
        pwd_hash = hashlib.sha256(f"{password}{salt}".encode()).hexdigest()
        return pwd_hash, salt
    
    def verify_password(self, password: str, password_hash: str, salt: str) -> bool:
        """Verify password against hash"""
        test_hash, _ = self.hash_password(password, salt)
        return test_hash == password_hash
    
    # ========== USER MANAGEMENT ==========
    
    def create_user(self, username: str, email: str, password: str, 
                   full_name: str = None) -> Optional[int]:
        """Create a new user"""
        with self._lock:
            try:
                password_hash, password_salt = self.hash_password(password)
                
                if self.db_type == 'postgresql':
                    query = """
                        INSERT INTO users (username, email, password_hash, password_salt, full_name)
                        VALUES (%s, %s, %s, %s, %s)
                        RETURNING user_id
                    """
                else:
                    query = """
                        INSERT INTO users (username, email, password_hash, password_salt, full_name)
                        VALUES (?, ?, ?, ?, ?)
                    """
                
                with self.get_connection() as conn:
                    if self.db_type == 'postgresql':
                        cursor = conn.cursor()
                        cursor.execute(query, (username, email, password_hash, password_salt, full_name))
                        user_id = cursor.fetchone()[0]
                    else:
                        cursor = conn.cursor()
                        cursor.execute(query, (username, email, password_hash, password_salt, full_name))
                        user_id = cursor.lastrowid
                    
                    # Create default settings
                    if self.db_type == 'postgresql':
                        cursor.execute("INSERT INTO user_settings (user_id) VALUES (%s)", (user_id,))
                    else:
                        cursor.execute("INSERT INTO user_settings (user_id) VALUES (?)", (user_id,))
                    
                    conn.commit()
                    
                    logger.info(f"User created: {username} (ID: {user_id})")
                    return user_id
                    
            except Exception as e:
                if 'unique' in str(e).lower() or 'duplicate' in str(e).lower():
                    logger.warning(f"User creation failed: {str(e)}")
                    return None
                logger.error(f"Error creating user: {str(e)}")
                return None
    
    def authenticate_user(self, username: str, password: str) -> Optional[Dict[str, Any]]:
        """Authenticate user and return user data"""
        try:
            if self.db_type == 'postgresql':
                query = """
                    SELECT user_id, username, email, password_hash, password_salt, 
                           full_name, is_active
                    FROM users 
                    WHERE username = %s AND is_active = 1
                """
            else:
                query = """
                    SELECT user_id, username, email, password_hash, password_salt, 
                           full_name, is_active
                    FROM users 
                    WHERE username = ? AND is_active = 1
                """
            
            with self.get_connection() as conn:
                if self.db_type == 'postgresql':
                    cursor = conn.cursor(cursor_factory=RealDictCursor)
                    cursor.execute(query, (username,))
                else:
                    cursor = conn.cursor()
                    cursor.execute(query, (username,))
                
                user = cursor.fetchone()
                
                if not user:
                    return None
                
                # Convert to dict if needed
                if self.db_type == 'postgresql':
                    user = dict(user)
                else:
                    user = dict(user)
                
                # Verify password
                if not self.verify_password(password, user['password_hash'], user['password_salt']):
                    return None
                
                # Update last login
                if self.db_type == 'postgresql':
                    cursor.execute(
                        "UPDATE users SET last_login = CURRENT_TIMESTAMP WHERE user_id = %s",
                        (user['user_id'],)
                    )
                else:
                    cursor.execute(
                        "UPDATE users SET last_login = CURRENT_TIMESTAMP WHERE user_id = ?",
                        (user['user_id'],)
                    )
                
                conn.commit()
                logger.info(f"User authenticated: {username}")
                
                return {
                    'user_id': user['user_id'],
                    'username': user['username'],
                    'email': user['email'],
                    'full_name': user['full_name']
                }
                
        except Exception as e:
            logger.error(f"Authentication error: {str(e)}")
            return None
    
    def get_user_by_id(self, user_id: int) -> Optional[Dict[str, Any]]:
        """Get user by ID"""
        try:
            if self.db_type == 'postgresql':
                query = """
                    SELECT user_id, username, email, full_name, created_at, 
                           last_login, profile_image
                    FROM users 
                    WHERE user_id = %s AND is_active = 1
                """
            else:
                query = """
                    SELECT user_id, username, email, full_name, created_at, 
                           last_login, profile_image
                    FROM users 
                    WHERE user_id = ? AND is_active = 1
                """
            
            with self.get_connection() as conn:
                if self.db_type == 'postgresql':
                    cursor = conn.cursor(cursor_factory=RealDictCursor)
                    cursor.execute(query, (user_id,))
                else:
                    cursor = conn.cursor()
                    cursor.execute(query, (user_id,))
                
                user = cursor.fetchone()
                if user:
                    return dict(user) if self.db_type == 'postgresql' else dict(user)
                return None
                
        except Exception as e:
            logger.error(f"Error getting user: {str(e)}")
            return None
    
    def update_user_profile(self, user_id: int, full_name: str = None, 
                           email: str = None) -> bool:
        """Update user profile"""
        try:
            with self.get_connection() as conn:
                if self.db_type == 'postgresql':
                    cursor = conn.cursor()
                    updates = []
                    params = []
                    
                    if full_name is not None:
                        updates.append("full_name = %s")
                        params.append(full_name)
                    
                    if email is not None:
                        updates.append("email = %s")
                        params.append(email)
                    
                    if not updates:
                        return True
                    
                    params.append(user_id)
                    query = f"UPDATE users SET {', '.join(updates)} WHERE user_id = %s"
                else:
                    cursor = conn.cursor()
                    updates = []
                    params = []
                    
                    if full_name is not None:
                        updates.append("full_name = ?")
                        params.append(full_name)
                    
                    if email is not None:
                        updates.append("email = ?")
                        params.append(email)
                    
                    if not updates:
                        return True
                    
                    params.append(user_id)
                    query = f"UPDATE users SET {', '.join(updates)} WHERE user_id = ?"
                
                cursor.execute(query, params)
                conn.commit()
                return True
                
        except Exception as e:
            logger.error(f"Error updating user profile: {str(e)}")
            return False
    
    def change_password(self, user_id: int, old_password: str, new_password: str) -> bool:
        """Change user password"""
        try:
            with self.get_connection() as conn:
                if self.db_type == 'postgresql':
                    cursor = conn.cursor(cursor_factory=RealDictCursor)
                    cursor.execute(
                        "SELECT password_hash, password_salt FROM users WHERE user_id = %s",
                        (user_id,)
                    )
                else:
                    cursor = conn.cursor()
                    cursor.execute(
                        "SELECT password_hash, password_salt FROM users WHERE user_id = ?",
                        (user_id,)
                    )
                
                user = cursor.fetchone()
                if not user:
                    return False
                
                user = dict(user) if self.db_type == 'postgresql' else dict(user)
                
                if not self.verify_password(old_password, user['password_hash'], user['password_salt']):
                    return False
                
                # Update password
                new_hash, new_salt = self.hash_password(new_password)
                
                if self.db_type == 'postgresql':
                    cursor.execute(
                        "UPDATE users SET password_hash = %s, password_salt = %s WHERE user_id = %s",
                        (new_hash, new_salt, user_id)
                    )
                else:
                    cursor.execute(
                        "UPDATE users SET password_hash = ?, password_salt = ? WHERE user_id = ?",
                        (new_hash, new_salt, user_id)
                    )
                
                conn.commit()
                logger.info(f"Password changed for user ID: {user_id}")
                return True
                
        except Exception as e:
            logger.error(f"Error changing password: {str(e)}")
            return False
    
    # ========== SESSION MANAGEMENT ==========
    
    def create_session(self, user_id: int, ip_address: str = None, 
                      user_agent: str = None, expires_hours: int = 24) -> Optional[str]:
        """Create a new session"""
        try:
            session_id = secrets.token_urlsafe(32)
            expires_at = datetime.datetime.now() + datetime.timedelta(hours=expires_hours)
            
            if self.db_type == 'postgresql':
                query = """
                    INSERT INTO sessions (session_id, user_id, expires_at, ip_address, user_agent)
                    VALUES (%s, %s, %s, %s, %s)
                """
            else:
                query = """
                    INSERT INTO sessions (session_id, user_id, expires_at, ip_address, user_agent)
                    VALUES (?, ?, ?, ?, ?)
                """
            
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(query, (session_id, user_id, expires_at, ip_address, user_agent))
                conn.commit()
                
                logger.info(f"Session created for user ID: {user_id}")
                return session_id
                
        except Exception as e:
            logger.error(f"Error creating session: {str(e)}")
            return None
    
    def validate_session(self, session_id: str) -> Optional[int]:
        """Validate session and return user_id"""
        try:
            if self.db_type == 'postgresql':
                query = """
                    SELECT user_id 
                    FROM sessions 
                    WHERE session_id = %s AND expires_at > NOW()
                """
            else:
                query = """
                    SELECT user_id 
                    FROM sessions 
                    WHERE session_id = ? AND expires_at > datetime('now')
                """
            
            with self.get_connection() as conn:
                if self.db_type == 'postgresql':
                    cursor = conn.cursor()
                    cursor.execute(query, (session_id,))
                else:
                    cursor = conn.cursor()
                    cursor.execute(query, (session_id,))
                
                result = cursor.fetchone()
                return result[0] if result else None
                
        except Exception as e:
            logger.error(f"Error validating session: {str(e)}")
            return None
    
    def delete_session(self, session_id: str) -> bool:
        """Delete a session (logout)"""
        try:
            if self.db_type == 'postgresql':
                query = "DELETE FROM sessions WHERE session_id = %s"
            else:
                query = "DELETE FROM sessions WHERE session_id = ?"
            
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(query, (session_id,))
                conn.commit()
                logger.info(f"Session deleted: {session_id}")
                return True
                
        except Exception as e:
            logger.error(f"Error deleting session: {str(e)}")
            return False
    
    def cleanup_expired_sessions(self) -> int:
        """Remove expired sessions"""
        try:
            if self.db_type == 'postgresql':
                query = "DELETE FROM sessions WHERE expires_at < NOW()"
            else:
                query = "DELETE FROM sessions WHERE expires_at < datetime('now')"
            
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(query)
                deleted = cursor.rowcount
                conn.commit()
                logger.info(f"Cleaned up {deleted} expired sessions")
                return deleted
                
        except Exception as e:
            logger.error(f"Error cleaning up sessions: {str(e)}")
            return 0
    
    # ========== DETECTION HISTORY ==========
    
    def add_detection_record(self, user_id: int, class_name: str, confidence: float,
                           model_type: str = None, audio_file: str = None,
                           pump_activated: bool = False, notes: str = None) -> Optional[int]:
        """Add a detection record"""
        try:
            if self.db_type == 'postgresql':
                query = """
                    INSERT INTO detection_history 
                    (user_id, class_name, confidence, model_type, audio_file, pump_activated, notes)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    RETURNING detection_id
                """
            else:
                query = """
                    INSERT INTO detection_history 
                    (user_id, class_name, confidence, model_type, audio_file, pump_activated, notes)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """
            
            with self.get_connection() as conn:
                cursor = conn.cursor()
                params = (user_id, class_name, confidence, model_type, audio_file, 
                         1 if pump_activated else 0, notes)
                cursor.execute(query, params)
                
                if self.db_type == 'postgresql':
                    detection_id = cursor.fetchone()[0]
                else:
                    detection_id = cursor.lastrowid
                
                conn.commit()
                logger.info(f"Detection record added for user {user_id}: {class_name}")
                return detection_id
                
        except Exception as e:
            logger.error(f"Error adding detection record: {str(e)}")
            return None
    
    def get_detection_history(self, user_id: int, limit: int = 50) -> List[Dict[str, Any]]:
        """Get detection history for a user"""
        try:
            if self.db_type == 'postgresql':
                query = """
                    SELECT detection_id, timestamp, class_name, confidence, 
                           model_type, audio_file, pump_activated, notes
                    FROM detection_history 
                    WHERE user_id = %s 
                    ORDER BY timestamp DESC 
                    LIMIT %s
                """
            else:
                query = """
                    SELECT detection_id, timestamp, class_name, confidence, 
                           model_type, audio_file, pump_activated, notes
                    FROM detection_history 
                    WHERE user_id = ? 
                    ORDER BY timestamp DESC 
                    LIMIT ?
                """
            
            with self.get_connection() as conn:
                if self.db_type == 'postgresql':
                    cursor = conn.cursor(cursor_factory=RealDictCursor)
                    cursor.execute(query, (user_id, limit))
                else:
                    cursor = conn.cursor()
                    cursor.execute(query, (user_id, limit))
                
                rows = cursor.fetchall()
                return [dict(row) if self.db_type == 'postgresql' else dict(row) for row in rows]
                
        except Exception as e:
            logger.error(f"Error getting detection history: {str(e)}")
            return []
    
    def get_detection_statistics(self, user_id: int, days: int = 7) -> Dict[str, Any]:
        """Get detection statistics for a user"""
        try:
            if self.db_type == 'postgresql':
                query = """
                    SELECT COUNT(*) as total,
                           SUM(CASE WHEN class_name = 'กรน' THEN 1 ELSE 0 END) as snoring,
                           AVG(confidence) as avg_confidence
                    FROM detection_history 
                    WHERE user_id = %s 
                    AND timestamp >= NOW() - INTERVAL '%s days'
                """
            else:
                query = """
                    SELECT COUNT(*) as total,
                           SUM(CASE WHEN class_name = 'กรน' THEN 1 ELSE 0 END) as snoring,
                           AVG(confidence) as avg_confidence
                    FROM detection_history 
                    WHERE user_id = ? 
                    AND timestamp >= datetime('now', '-' || ? || ' days')
                """
            
            with self.get_connection() as conn:
                if self.db_type == 'postgresql':
                    cursor = conn.cursor(cursor_factory=RealDictCursor)
                    cursor.execute(query, (user_id, days))
                else:
                    cursor = conn.cursor()
                    cursor.execute(query, (user_id, days))
                
                stats = cursor.fetchone()
                stats = dict(stats) if self.db_type == 'postgresql' else dict(stats)
                
                return {
                    'total_detections': stats['total'] or 0,
                    'snoring_detected': stats['snoring'] or 0,
                    'average_confidence': round(stats['avg_confidence'], 2) if stats['avg_confidence'] else 0,
                    'period_days': days
                }
                
        except Exception as e:
            logger.error(f"Error getting detection statistics: {str(e)}")
            return {}
    
    # ========== USER SETTINGS ==========
    
    def get_user_settings(self, user_id: int) -> Optional[Dict[str, Any]]:
        """Get user settings"""
        try:
            if self.db_type == 'postgresql':
                query = """
                    SELECT auto_detect_enabled, detection_delay, confidence_threshold,
                           notification_enabled
                    FROM user_settings 
                    WHERE user_id = %s
                """
            else:
                query = """
                    SELECT auto_detect_enabled, detection_delay, confidence_threshold,
                           notification_enabled
                    FROM user_settings 
                    WHERE user_id = ?
                """
            
            with self.get_connection() as conn:
                if self.db_type == 'postgresql':
                    cursor = conn.cursor(cursor_factory=RealDictCursor)
                    cursor.execute(query, (user_id,))
                else:
                    cursor = conn.cursor()
                    cursor.execute(query, (user_id,))
                
                settings = cursor.fetchone()
                return dict(settings) if settings else None
                
        except Exception as e:
            logger.error(f"Error getting user settings: {str(e)}")
            return None
    
    def update_user_settings(self, user_id: int, **kwargs) -> bool:
        """Update user settings"""
        try:
            with self.get_connection() as conn:
                if self.db_type == 'postgresql':
                    cursor = conn.cursor()
                    updates = []
                    params = []
                    
                    for key, value in kwargs.items():
                        if key in ['auto_detect_enabled', 'detection_delay', 
                                  'confidence_threshold', 'notification_enabled']:
                            updates.append(f"{key} = %s")
                            params.append(value)
                    
                    if not updates:
                        return True
                    
                    updates.append("updated_at = CURRENT_TIMESTAMP")
                    params.append(user_id)
                    
                    query = f"UPDATE user_settings SET {', '.join(updates)} WHERE user_id = %s"
                else:
                    cursor = conn.cursor()
                    updates = []
                    params = []
                    
                    for key, value in kwargs.items():
                        if key in ['auto_detect_enabled', 'detection_delay', 
                                  'confidence_threshold', 'notification_enabled']:
                            updates.append(f"{key} = ?")
                            params.append(value)
                    
                    if not updates:
                        return True
                    
                    updates.append("updated_at = CURRENT_TIMESTAMP")
                    params.append(user_id)
                    
                    query = f"UPDATE user_settings SET {', '.join(updates)} WHERE user_id = ?"
                
                cursor.execute(query, params)
                conn.commit()
                
                logger.info(f"Settings updated for user ID: {user_id}")
                return True
                
        except Exception as e:
            logger.error(f"Error updating user settings: {str(e)}")
            return False
    
    # ========== SYSTEM LOGS ==========
    
    def add_system_log(self, message: str, log_level: str = "INFO", 
                      user_id: int = None, context: str = None) -> bool:
        """Add a system log entry"""
        try:
            if self.db_type == 'postgresql':
                query = """
                    INSERT INTO system_logs (user_id, log_level, message, context)
                    VALUES (%s, %s, %s, %s)
                """
            else:
                query = """
                    INSERT INTO system_logs (user_id, log_level, message, context)
                    VALUES (?, ?, ?, ?)
                """
            
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(query, (user_id, log_level, message, context))
                conn.commit()
                return True
                
        except Exception as e:
            logger.error(f"Error adding system log: {str(e)}")
            return False
    
    def get_system_logs(self, user_id: int = None, limit: int = 100) -> List[Dict[str, Any]]:
        """Get system logs"""
        try:
            with self.get_connection() as conn:
                if self.db_type == 'postgresql':
                    cursor = conn.cursor(cursor_factory=RealDictCursor)
                    if user_id:
                        cursor.execute("""
                            SELECT log_id, timestamp, log_level, message, context
                            FROM system_logs 
                            WHERE user_id = %s 
                            ORDER BY timestamp DESC 
                            LIMIT %s
                        """, (user_id, limit))
                    else:
                        cursor.execute("""
                            SELECT log_id, timestamp, log_level, message, context
                            FROM system_logs 
                            ORDER BY timestamp DESC 
                            LIMIT %s
                        """, (limit,))
                else:
                    cursor = conn.cursor()
                    if user_id:
                        cursor.execute("""
                            SELECT log_id, timestamp, log_level, message, context
                            FROM system_logs 
                            WHERE user_id = ? 
                            ORDER BY timestamp DESC 
                            LIMIT ?
                        """, (user_id, limit))
                    else:
                        cursor.execute("""
                            SELECT log_id, timestamp, log_level, message, context
                            FROM system_logs 
                            ORDER BY timestamp DESC 
                            LIMIT ?
                        """, (limit,))
                
                rows = cursor.fetchall()
                return [dict(row) if self.db_type == 'postgresql' else dict(row) for row in rows]
                
        except Exception as e:
            logger.error(f"Error getting system logs: {str(e)}")
            return []
    
    def close(self):
        """Close database connections"""
        if self.connection_pool:
            self.connection_pool.closeall()
            logger.info("PostgreSQL connection pool closed")
