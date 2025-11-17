"""
Simple Example Server with Authentication
ตัวอย่าง Flask Server พร้อมระบบ Login/Register

ใช้เพื่อทดสอบว่าระบบ Authentication ทำงานได้หรือไม่
"""

from flask import Flask, jsonify, request, render_template, session, redirect, url_for
from database_manager import DatabaseManager
from auth_middleware import AuthMiddleware, get_client_ip, get_user_agent
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Initialize Flask app
app = Flask(__name__)
app.secret_key = 'demo-secret-key-change-in-production'  # เปลี่ยนใน production
app.config['SESSION_TYPE'] = 'filesystem'

# Initialize database and auth
db_manager = DatabaseManager()
auth_middleware = AuthMiddleware(db_manager)

# =====================================================
# Page Routes
# =====================================================

@app.route('/')
@auth_middleware.require_auth
def index():
    """หน้าหลัก - ต้อง login ก่อน"""
    user = request.current_user
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Dashboard</title>
        <meta charset="UTF-8">
        <style>
            body {{
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                margin: 0;
                padding: 20px;
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                min-height: 100vh;
            }}
            .container {{
                max-width: 800px;
                margin: 0 auto;
                background: white;
                padding: 40px;
                border-radius: 20px;
                box-shadow: 0 20px 60px rgba(0,0,0,0.3);
            }}
            h1 {{ color: #667eea; }}
            .user-info {{
                background: #f8f9fa;
                padding: 20px;
                border-radius: 10px;
                margin: 20px 0;
            }}
            .btn {{
                background: #667eea;
                color: white;
                padding: 10px 20px;
                border: none;
                border-radius: 5px;
                text-decoration: none;
                display: inline-block;
                margin: 5px;
                cursor: pointer;
            }}
            .btn:hover {{
                background: #5568d3;
            }}
            .btn-danger {{
                background: #e74c3c;
            }}
            .btn-danger:hover {{
                background: #c0392b;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>🛏️ ยินดีต้อนรับสู่ระบบหมอนลดการนอนกรน!</h1>
            
            <div class="user-info">
                <h2>ข้อมูลผู้ใช้</h2>
                <p><strong>ชื่อผู้ใช้:</strong> {user['username']}</p>
                <p><strong>ชื่อ-นามสกุล:</strong> {user.get('full_name', 'ไม่ระบุ')}</p>
                <p><strong>อีเมล:</strong> {user['email']}</p>
            </div>
            
            <h2>ฟีเจอร์</h2>
            <p>✅ ระบบ Login/Register ทำงานสมบูรณ์</p>
            <p>✅ Session Management พร้อมใช้งาน</p>
            <p>✅ Database เก็บข้อมูลผู้ใช้และประวัติ</p>
            <p>✅ Authentication Middleware ป้องกันหน้า</p>
            
            <div style="margin-top: 30px;">
                <a href="/api/user/profile" class="btn">ดูโปรไฟล์ (API)</a>
                <button onclick="logout()" class="btn btn-danger">ออกจากระบบ</button>
            </div>
        </div>
        
        <script>
            function logout() {{
                fetch('/api/auth/logout', {{
                    method: 'POST',
                    headers: {{'Content-Type': 'application/json'}}
                }})
                .then(() => {{
                    window.location.href = '/login';
                }});
            }}
        </script>
    </body>
    </html>
    """

@app.route('/login')
def login():
    """หน้า Login"""
    return render_template('login.html')

@app.route('/register')
def register():
    """หน้า Register"""
    return render_template('register.html')

@app.route('/logout')
def logout():
    """ออกจากระบบ"""
    session.clear()
    return redirect(url_for('login'))

# =====================================================
# Authentication API
# =====================================================

@app.route('/api/auth/register', methods=['POST'])
def api_auth_register():
    """API สมัครสมาชิก"""
    try:
        data = request.json
        
        # Validate
        if not all(k in data for k in ['username', 'email', 'password']):
            return jsonify({
                "success": False,
                "message": "กรุณากรอกข้อมูลให้ครบถ้วน"
            }), 400
        
        # Create user
        user_id = db_manager.create_user(
            username=data['username'],
            email=data['email'],
            password=data['password'],
            full_name=data.get('full_name')
        )
        
        if not user_id:
            return jsonify({
                "success": False,
                "message": "ชื่อผู้ใช้หรืออีเมลนี้ถูกใช้งานแล้ว"
            }), 409
        
        logger.info(f"New user registered: {data['username']}")
        
        return jsonify({
            "success": True,
            "message": "สมัครสมาชิกสำเร็จ",
            "user_id": user_id
        })
        
    except Exception as e:
        logger.error(f"Registration error: {str(e)}")
        return jsonify({
            "success": False,
            "message": "เกิดข้อผิดพลาด"
        }), 500

@app.route('/api/auth/login', methods=['POST'])
def api_auth_login():
    """API เข้าสู่ระบบ"""
    try:
        data = request.json
        
        # Authenticate
        user = db_manager.authenticate_user(
            username=data.get('username'),
            password=data.get('password')
        )
        
        if not user:
            return jsonify({
                "success": False,
                "message": "ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง"
            }), 401
        
        # Create session
        session_id = db_manager.create_session(
            user_id=user['user_id'],
            ip_address=get_client_ip(request),
            user_agent=get_user_agent(request),
            expires_hours=24
        )
        
        # Store in Flask session
        session['session_id'] = session_id
        session['user_id'] = user['user_id']
        
        logger.info(f"User logged in: {user['username']}")
        
        return jsonify({
            "success": True,
            "message": "เข้าสู่ระบบสำเร็จ",
            "session_id": session_id,
            "user": user
        })
        
    except Exception as e:
        logger.error(f"Login error: {str(e)}")
        return jsonify({
            "success": False,
            "message": "เกิดข้อผิดพลาด"
        }), 500

@app.route('/api/auth/logout', methods=['POST'])
def api_auth_logout():
    """API ออกจากระบบ"""
    try:
        session_id = session.get('session_id')
        if session_id:
            db_manager.delete_session(session_id)
        
        session.clear()
        
        return jsonify({
            "success": True,
            "message": "ออกจากระบบสำเร็จ"
        })
        
    except Exception as e:
        logger.error(f"Logout error: {str(e)}")
        return jsonify({
            "success": False,
            "message": "เกิดข้อผิดพลาด"
        }), 500

@app.route('/api/auth/validate', methods=['POST'])
def api_auth_validate():
    """API ตรวจสอบ session"""
    try:
        data = request.json or {}
        session_id = data.get('session_id') or session.get('session_id')
        
        if not session_id:
            return jsonify({"valid": False})
        
        user_id = db_manager.validate_session(session_id)
        
        if not user_id:
            return jsonify({"valid": False})
        
        user = db_manager.get_user_by_id(user_id)
        
        return jsonify({
            "valid": True,
            "user": user
        })
        
    except Exception as e:
        logger.error(f"Validation error: {str(e)}")
        return jsonify({"valid": False}), 500

# =====================================================
# User API
# =====================================================

@app.route('/api/user/profile', methods=['GET'])
@auth_middleware.require_auth
def get_user_profile():
    """ดูโปรไฟล์ผู้ใช้"""
    try:
        user = request.current_user
        
        # Get settings
        settings = db_manager.get_user_settings(user['user_id'])
        
        # Get statistics
        stats = db_manager.get_detection_statistics(user['user_id'], days=7)
        
        return jsonify({
            "user": user,
            "settings": settings,
            "statistics": stats
        })
        
    except Exception as e:
        logger.error(f"Profile API error: {str(e)}")
        return jsonify({"error": str(e)}), 500

# =====================================================
# Error Handlers
# =====================================================

@app.errorhandler(404)
def not_found(error):
    return jsonify({"error": "Not found"}), 404

@app.errorhandler(500)
def internal_error(error):
    return jsonify({"error": "Internal server error"}), 500

# =====================================================
# Main
# =====================================================

if __name__ == "__main__":
    print("""
╔══════════════════════════════════════════════════════════════╗
║      Simple Example Server with Authentication              ║
╚══════════════════════════════════════════════════════════════╝

🚀 Starting server...

📝 URL: http://localhost:5000
📝 Login: http://localhost:5000/login
📝 Register: http://localhost:5000/register

🔑 Demo Account:
   Username: demo
   Password: demo123

Press Ctrl+C to stop
""")
    
    try:
        app.run(
            host='0.0.0.0',
            port=5001,
            debug=True  # เปลี่ยนเป็น False ใน production
        )
    except KeyboardInterrupt:
        print("\n\n⚠️  Server stopped by user")
    except Exception as e:
        print(f"\n\n❌ Server error: {str(e)}")
