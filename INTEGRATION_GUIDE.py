"""
คู่มือการเพิ่ม Authentication ลงใน Server เดิม
Smart Anti-Snoring Pillow System

ขั้นตอนที่ 1: เพิ่ม imports ที่จำเป็น
"""

# เพิ่มที่ด้านบนของ server_improve_fixed.py
from database_manager import DatabaseManager
from auth_middleware import AuthMiddleware, get_client_ip, get_user_agent
from flask import session, redirect, url_for

"""
ขั้นตอนที่ 2: เพิ่มการตั้งค่า Flask session
"""

# ในฟังก์ชัน create_app(), เพิ่มหลัง app = Flask(...)
app.secret_key = 'your-super-secret-key-change-this-in-production'  # เปลี่ยนเป็น key ของคุณเอง
app.config['SESSION_TYPE'] = 'filesystem'
app.config['PERMANENT_SESSION_LIFETIME'] = 86400  # 24 ชั่วโมง

"""
ขั้นตอนที่ 3: Initialize Database และ Auth Middleware
"""

# ใน create_app(), เพิ่มหลังสร้าง directories
# Initialize database and auth
db_manager = DatabaseManager()
auth_middleware = AuthMiddleware(db_manager)

"""
ขั้นตอนที่ 4: เพิ่ม Routes สำหรับ Authentication
"""

# =========================
# Authentication Routes
# =========================

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

# =========================
# Authentication API
# =========================

@app.route('/api/auth/register', methods=['POST'])
def api_auth_register():
    """API สมัครสมาชิก"""
    try:
        data = request.json
        
        # Validate required fields
        required_fields = ['username', 'email', 'password']
        for field in required_fields:
            if not data.get(field):
                return jsonify({
                    "success": False,
                    "message": f"กรุณากรอก {field}"
                }), 400
        
        # Check username format
        import re
        if not re.match(r'^[a-zA-Z0-9_]{3,20}$', data['username']):
            return jsonify({
                "success": False,
                "message": "ชื่อผู้ใช้ต้องมี 3-20 ตัวอักษร (a-z, 0-9, _)"
            }), 400
        
        # Check email format
        if not re.match(r'^[^\s@]+@[^\s@]+\.[^\s@]+$', data['email']):
            return jsonify({
                "success": False,
                "message": "รูปแบบอีเมลไม่ถูกต้อง"
            }), 400
        
        # Check password length
        if len(data['password']) < 6:
            return jsonify({
                "success": False,
                "message": "รหัสผ่านต้องมีอย่างน้อย 6 ตัวอักษร"
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
        
        logger.info(f"New user registered: {data['username']} (ID: {user_id})")
        
        # Add system log
        db_manager.add_system_log(
            message=f"User registered: {data['username']}",
            log_level="INFO",
            user_id=user_id
        )
        
        return jsonify({
            "success": True,
            "message": "สมัครสมาชิกสำเร็จ",
            "user_id": user_id
        })
        
    except Exception as e:
        logger.error(f"Registration error: {str(e)}")
        return jsonify({
            "success": False,
            "message": "เกิดข้อผิดพลาดในการสมัครสมาชิก"
        }), 500

@app.route('/api/auth/login', methods=['POST'])
def api_auth_login():
    """API เข้าสู่ระบบ"""
    try:
        data = request.json
        
        if not data.get('username') or not data.get('password'):
            return jsonify({
                "success": False,
                "message": "กรุณากรอกชื่อผู้ใช้และรหัสผ่าน"
            }), 400
        
        # Authenticate user
        user = db_manager.authenticate_user(
            username=data['username'],
            password=data['password']
        )
        
        if not user:
            return jsonify({
                "success": False,
                "message": "ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง"
            }), 401
        
        # Create session
        remember_me = data.get('remember_me', False)
        expires_hours = 720 if remember_me else 24  # 30 days or 1 day
        
        session_id = db_manager.create_session(
            user_id=user['user_id'],
            ip_address=get_client_ip(request),
            user_agent=get_user_agent(request),
            expires_hours=expires_hours
        )
        
        if not session_id:
            return jsonify({
                "success": False,
                "message": "ไม่สามารถสร้าง session ได้"
            }), 500
        
        # Store session in Flask session
        session['session_id'] = session_id
        session['user_id'] = user['user_id']
        
        logger.info(f"User logged in: {user['username']} (ID: {user['user_id']})")
        
        # Add system log
        db_manager.add_system_log(
            message=f"User logged in: {user['username']}",
            log_level="INFO",
            user_id=user['user_id']
        )
        
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
            "message": "เกิดข้อผิดพลาดในการเข้าสู่ระบบ"
        }), 500

@app.route('/api/auth/logout', methods=['POST'])
def api_auth_logout():
    """API ออกจากระบบ"""
    try:
        data = request.json or {}
        session_id = data.get('session_id') or session.get('session_id')
        
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
            "message": "เกิดข้อผิดพลาดในการออกจากระบบ"
        }), 500

@app.route('/api/auth/validate', methods=['POST'])
def api_auth_validate():
    """API ตรวจสอบ session"""
    try:
        data = request.json or {}
        session_id = data.get('session_id') or session.get('session_id')
        
        if not session_id:
            return jsonify({
                "valid": False,
                "message": "No session provided"
            })
        
        user_id = db_manager.validate_session(session_id)
        
        if not user_id:
            return jsonify({
                "valid": False,
                "message": "Session expired or invalid"
            })
        
        user = db_manager.get_user_by_id(user_id)
        
        return jsonify({
            "valid": True,
            "user": user
        })
        
    except Exception as e:
        logger.error(f"Session validation error: {str(e)}")
        return jsonify({
            "valid": False,
            "message": "Validation error"
        }), 500

"""
ขั้นตอนที่ 5: เพิ่ม Authentication ให้กับ Routes เดิม
"""

# ตัวอย่าง: เพิ่ม authentication ให้กับ index route
@app.route('/')
@auth_middleware.require_auth
def index():
    # ตอนนี้ route นี้ต้อง login ก่อนถึงจะเข้าได้
    # สามารถเข้าถึงข้อมูล user ผ่าน request.current_user
    return render_template('index.html')

# ตัวอย่าง: เพิ่ม authentication ให้กับ API routes
@app.route('/api/record', methods=['POST'])
@auth_middleware.require_auth
def api_record():
    # User ที่ login แล้วเท่านั้นที่เรียกใช้ได้
    user = request.current_user
    
    # ... original code ...
    
    # บันทึกการตรวจจับลง database
    if result:
        db_manager.add_detection_record(
            user_id=user['user_id'],
            class_name=result['class_name'],
            confidence=result['confidence'],
            model_type=result.get('model_type'),
            audio_file=audio_file,
            pump_activated=pump_was_activated
        )
    
    return jsonify(...)

"""
ขั้นตอนที่ 6: แก้ไข detection_history API ให้แสดงเฉพาะข้อมูลของ user ที่ login
"""

@app.route('/api/detection_history', methods=['GET'])
@auth_middleware.require_auth
def get_detection_history():
    try:
        user = request.current_user
        
        # ดึงข้อมูลจาก database แทนที่จะใช้ snore_system.data_store
        history = db_manager.get_detection_history(
            user_id=user['user_id'],
            limit=50
        )
        
        return jsonify(history)
        
    except Exception as e:
        logger.error(f"Detection history API error: {str(e)}")
        return jsonify({"error": str(e)}), 500

"""
ขั้นตอนที่ 7: เพิ่ม User Profile API
"""

@app.route('/api/user/profile', methods=['GET'])
@auth_middleware.require_auth
def get_user_profile():
    """ดูโปรไฟล์ผู้ใช้"""
    try:
        user = request.current_user
        
        # Get user settings
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

@app.route('/api/user/profile', methods=['PUT'])
@auth_middleware.require_auth
def update_user_profile():
    """แก้ไขโปรไฟล์"""
    try:
        user = request.current_user
        data = request.json
        
        success = db_manager.update_user_profile(
            user_id=user['user_id'],
            full_name=data.get('full_name'),
            email=data.get('email')
        )
        
        if success:
            return jsonify({
                "success": True,
                "message": "อัปเดตโปรไฟล์สำเร็จ"
            })
        else:
            return jsonify({
                "success": False,
                "message": "ไม่สามารถอัปเดตโปรไฟล์ได้"
            }), 400
            
    except Exception as e:
        logger.error(f"Update profile error: {str(e)}")
        return jsonify({
            "success": False,
            "message": "เกิดข้อผิดพลาด"
        }), 500

@app.route('/api/user/change-password', methods=['POST'])
@auth_middleware.require_auth
def change_password():
    """เปลี่ยนรหัสผ่าน"""
    try:
        user = request.current_user
        data = request.json
        
        if not data.get('old_password') or not data.get('new_password'):
            return jsonify({
                "success": False,
                "message": "กรุณากรอกรหัสผ่านเก่าและรหัสผ่านใหม่"
            }), 400
        
        success = db_manager.change_password(
            user_id=user['user_id'],
            old_password=data['old_password'],
            new_password=data['new_password']
        )
        
        if success:
            return jsonify({
                "success": True,
                "message": "เปลี่ยนรหัสผ่านสำเร็จ"
            })
        else:
            return jsonify({
                "success": False,
                "message": "รหัสผ่านเก่าไม่ถูกต้อง"
            }), 400
            
    except Exception as e:
        logger.error(f"Change password error: {str(e)}")
        return jsonify({
            "success": False,
            "message": "เกิดข้อผิดพลาด"
        }), 500

"""
ขั้นตอนที่ 8: เพิ่ม Cleanup task สำหรับ expired sessions
"""

# เพิ่มในส่วน __main__
def cleanup_sessions_periodically():
    """ทำความสะอาด expired sessions ทุกๆ 1 ชั่วโมง"""
    import threading
    import time
    
    def cleanup():
        while True:
            try:
                time.sleep(3600)  # รอ 1 ชั่วโมง
                db_manager.cleanup_expired_sessions()
                logger.info("Expired sessions cleaned up")
            except Exception as e:
                logger.error(f"Session cleanup error: {str(e)}")
    
    thread = threading.Thread(target=cleanup, daemon=True)
    thread.start()

# เพิ่มใน __main__
if __name__ == "__main__":
    try:
        app = create_app()
        
        # Start cleanup task
        cleanup_sessions_periodically()
        
        logger.info("Starting server on 0.0.0.0:5000")
        app.run(host='0.0.0.0', port=5000, debug=False, threaded=True)
        
    except Exception as e:
        logger.error(f"Server startup failed: {str(e)}")
        sys.exit(1)

"""
สรุป: ขั้นตอนการเพิ่ม Authentication

1. ติดตั้ง dependencies และสร้าง database
   - python database_setup.py

2. เพิ่ม imports ที่จำเป็น

3. เพิ่มการตั้งค่า Flask session และ secret key

4. Initialize DatabaseManager และ AuthMiddleware

5. เพิ่ม Authentication routes (/login, /register, /logout)

6. เพิ่ม Authentication API routes

7. เพิ่ม @auth_middleware.require_auth decorator ให้กับ routes ที่ต้องการ authentication

8. แก้ไข API routes เดิมให้บันทึกข้อมูลลง database

9. เพิ่ม User Profile APIs

10. เพิ่ม Cleanup task สำหรับ expired sessions

11. ทดสอบระบบ!
"""

print("""
✅ คู่มือการเพิ่ม Authentication เสร็จสมบูรณ์!

ขั้นตอนถัดไป:
1. เปิดไฟล์ server_improve_fixed.py
2. เพิ่มโค้ดตามตัวอย่างข้างบน
3. เปลี่ยน secret_key เป็นของคุณเอง
4. รัน server: python server_improve_fixed.py
5. เปิดเบราว์เซอร์ไปที่ http://localhost:5000/login

บัญชี Demo:
- Username: demo
- Password: demo123

Happy Coding! 🎉
""")
