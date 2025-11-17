"""
Database Setup Script for Smart Anti-Snoring Pillow System
Creates database schema and initialization functions
"""

import sqlite3
import hashlib
import secrets
import datetime
from pathlib import Path

# Database file path
DB_PATH = "snore_system.db"

def hash_password(password: str, salt: str = None) -> tuple:
    """
    Hash password with salt using SHA-256
    Returns (hashed_password, salt)
    """
    if salt is None:
        salt = secrets.token_hex(32)
    
    pwd_hash = hashlib.sha256(f"{password}{salt}".encode()).hexdigest()
    return pwd_hash, salt

def create_database():
    """Create database and tables"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Users table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            password_salt TEXT NOT NULL,
            full_name TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_login TIMESTAMP,
            is_active INTEGER DEFAULT 1,
            profile_image TEXT
        )
    """)
    
    # Sessions table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            session_id TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            expires_at TIMESTAMP NOT NULL,
            ip_address TEXT,
            user_agent TEXT,
            FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
        )
    """)
    
    # Detection history table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS detection_history (
            detection_id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            class_name TEXT NOT NULL,
            confidence REAL NOT NULL,
            model_type TEXT,
            audio_file TEXT,
            pump_activated INTEGER DEFAULT 0,
            notes TEXT,
            FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
        )
    """)
    
    # User settings table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_settings (
            setting_id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER UNIQUE NOT NULL,
            auto_detect_enabled INTEGER DEFAULT 0,
            detection_delay INTEGER DEFAULT 5,
            confidence_threshold REAL DEFAULT 0.85,
            notification_enabled INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
        )
    """)
    
    # System logs table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS system_logs (
            log_id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            log_level TEXT NOT NULL,
            message TEXT NOT NULL,
            context TEXT,
            FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE SET NULL
        )
    """)
    
    # Password reset tokens table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS password_reset_tokens (
            token_id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            token TEXT UNIQUE NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            expires_at TIMESTAMP NOT NULL,
            used INTEGER DEFAULT 0,
            FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
        )
    """)
    
    # Create indexes for better performance
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_sessions_user_id ON sessions(user_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_sessions_expires_at ON sessions(expires_at)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_detection_history_user_id ON detection_history(user_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_detection_history_timestamp ON detection_history(timestamp)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_system_logs_user_id ON system_logs(user_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_system_logs_timestamp ON system_logs(timestamp)")
    
    conn.commit()
    conn.close()
    
    print("✅ Database created successfully")

def create_demo_user():
    """Create a demo user for testing"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Check if demo user already exists
    cursor.execute("SELECT user_id FROM users WHERE username = ?", ("demo",))
    if cursor.fetchone():
        print("ℹ️ Demo user already exists")
        conn.close()
        return
    
    # Create demo user
    password_hash, password_salt = hash_password("demo123")
    
    cursor.execute("""
        INSERT INTO users (username, email, password_hash, password_salt, full_name)
        VALUES (?, ?, ?, ?, ?)
    """, ("demo", "demo@snoresystem.com", password_hash, password_salt, "Demo User"))
    
    user_id = cursor.lastrowid
    
    # Create default settings for demo user
    cursor.execute("""
        INSERT INTO user_settings (user_id, auto_detect_enabled, detection_delay)
        VALUES (?, 0, 5)
    """, (user_id,))
    
    conn.commit()
    conn.close()
    
    print("✅ Demo user created successfully")
    print("   Username: demo")
    print("   Password: demo123")

def cleanup_old_sessions():
    """Remove expired sessions"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute("""
        DELETE FROM sessions 
        WHERE expires_at < datetime('now')
    """)
    
    deleted = cursor.rowcount
    conn.commit()
    conn.close()
    
    print(f"✅ Cleaned up {deleted} expired sessions")

def get_database_stats():
    """Get database statistics"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Count users
    cursor.execute("SELECT COUNT(*) FROM users")
    user_count = cursor.fetchone()[0]
    
    # Count active sessions
    cursor.execute("""
        SELECT COUNT(*) FROM sessions 
        WHERE expires_at > datetime('now')
    """)
    session_count = cursor.fetchone()[0]
    
    # Count detections
    cursor.execute("SELECT COUNT(*) FROM detection_history")
    detection_count = cursor.fetchone()[0]
    
    # Count logs
    cursor.execute("SELECT COUNT(*) FROM system_logs")
    log_count = cursor.fetchone()[0]
    
    conn.close()
    
    print("\n📊 Database Statistics:")
    print(f"   Users: {user_count}")
    print(f"   Active Sessions: {session_count}")
    print(f"   Detection Records: {detection_count}")
    print(f"   System Logs: {log_count}")

if __name__ == "__main__":
    print("🚀 Initializing Smart Anti-Snoring Pillow Database...")
    print()
    
    # Create database
    create_database()
    
    # Create demo user
    create_demo_user()
    
    # Cleanup old sessions
    cleanup_old_sessions()
    
    # Show statistics
    get_database_stats()
    
    print("\n✅ Database setup completed successfully!")
