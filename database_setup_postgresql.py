"""
Database Setup Script for PostgreSQL
Creates database schema for Smart Anti-Snoring Pillow System
"""

import os
import sys
import urllib.parse as urlparse

try:
    import psycopg2
    from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT
except ImportError:
    print("❌ psycopg2 not installed. Install with: pip install psycopg2-binary")
    sys.exit(1)

def get_database_url():
    """Get database URL from environment variable"""
    database_url = os.environ.get('DATABASE_URL')
    if not database_url:
        print("❌ DATABASE_URL environment variable not set")
        print("Set it like: export DATABASE_URL=postgresql://user:pass@host:port/dbname")
        sys.exit(1)
    
    # Convert postgres:// to postgresql:// if needed
    if database_url.startswith('postgres://'):
        database_url = database_url.replace('postgres://', 'postgresql://', 1)
    
    return database_url

def create_database_schema(database_url):
    """Create database schema"""
    try:
        # Parse connection string
        result = urlparse.urlparse(database_url)
        
        # Connect to database
        conn = psycopg2.connect(
            host=result.hostname,
            port=result.port or 5432,
            database=result.path[1:],  # Remove leading '/'
            user=result.username,
            password=result.password
        )
        conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
        cursor = conn.cursor()
        
        print("✅ Connected to PostgreSQL database")
        
        # Users table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id SERIAL PRIMARY KEY,
                username VARCHAR(50) UNIQUE NOT NULL,
                email VARCHAR(100) UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                password_salt TEXT NOT NULL,
                full_name VARCHAR(100),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_login TIMESTAMP,
                is_active INTEGER DEFAULT 1,
                profile_image TEXT
            )
        """)
        
        # Sessions table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                session_id VARCHAR(255) PRIMARY KEY,
                user_id INTEGER NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                expires_at TIMESTAMP NOT NULL,
                ip_address VARCHAR(45),
                user_agent TEXT,
                FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
            )
        """)
        
        # Detection history table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS detection_history (
                detection_id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                class_name VARCHAR(50) NOT NULL,
                confidence REAL NOT NULL,
                model_type VARCHAR(50),
                audio_file TEXT,
                pump_activated INTEGER DEFAULT 0,
                notes TEXT,
                FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
            )
        """)
        
        # User settings table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_settings (
                setting_id SERIAL PRIMARY KEY,
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
                log_id SERIAL PRIMARY KEY,
                user_id INTEGER,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                log_level VARCHAR(20) NOT NULL,
                message TEXT NOT NULL,
                context TEXT,
                FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE SET NULL
            )
        """)
        
        # Password reset tokens table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS password_reset_tokens (
                token_id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL,
                token VARCHAR(255) UNIQUE NOT NULL,
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
        cursor.close()
        conn.close()
        
        print("✅ Database schema created successfully")
        
    except Exception as e:
        print(f"❌ Error creating database schema: {str(e)}")
        sys.exit(1)

def create_demo_user(database_url):
    """Create a demo user for testing"""
    import hashlib
    import secrets
    
    def hash_password(password: str, salt: str = None) -> tuple:
        if salt is None:
            salt = secrets.token_hex(32)
        pwd_hash = hashlib.sha256(f"{password}{salt}".encode()).hexdigest()
        return pwd_hash, salt
    
    try:
        result = urlparse.urlparse(database_url)
        
        conn = psycopg2.connect(
            host=result.hostname,
            port=result.port or 5432,
            database=result.path[1:],
            user=result.username,
            password=result.password
        )
        cursor = conn.cursor()
        
        # Check if demo user already exists
        cursor.execute("SELECT user_id FROM users WHERE username = %s", ("demo",))
        if cursor.fetchone():
            print("ℹ️ Demo user already exists")
            conn.close()
            return
        
        # Create demo user
        password_hash, password_salt = hash_password("demo123")
        
        cursor.execute("""
            INSERT INTO users (username, email, password_hash, password_salt, full_name)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING user_id
        """, ("demo", "demo@snoresystem.com", password_hash, password_salt, "Demo User"))
        
        user_id = cursor.fetchone()[0]
        
        # Create default settings for demo user
        cursor.execute("""
            INSERT INTO user_settings (user_id, auto_detect_enabled, detection_delay)
            VALUES (%s, 0, 5)
        """, (user_id,))
        
        conn.commit()
        cursor.close()
        conn.close()
        
        print("✅ Demo user created successfully")
        print("   Username: demo")
        print("   Password: demo123")
        
    except Exception as e:
        print(f"❌ Error creating demo user: {str(e)}")

if __name__ == "__main__":
    print("🚀 Initializing Smart Anti-Snoring Pillow Database (PostgreSQL)...")
    print()
    
    database_url = get_database_url()
    
    # Create database schema
    create_database_schema(database_url)
    
    # Create demo user
    create_demo_user(database_url)
    
    print("\n✅ Database setup completed successfully!")

