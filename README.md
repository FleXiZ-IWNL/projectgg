# Smart Anti-Snoring Pillow System with Authentication

ระบบหมอนลดการนอนกรนอัจฉริยะ พร้อมระบบ Login/Register และ Database

## 🚀 Features ใหม่

### 1. ระบบ Authentication
- ✅ Login/Register สำหรับผู้ใช้
- ✅ Session Management ที่ปลอดภัย
- ✅ Password Hashing (SHA-256 + Salt)
- ✅ Remember Me functionality
- ✅ Auto logout เมื่อ session หมดอายุ

### 2. Database Integration
- ✅ SQLite Database สำหรับเก็บข้อมูล
- ✅ เก็บข้อมูลผู้ใช้ (users)
- ✅ เก็บประวัติการตรวจจับเสียงกรน (detection_history)
- ✅ เก็บ Session (sessions)
- ✅ เก็บการตั้งค่าของผู้ใช้ (user_settings)
- ✅ เก็บ System Logs (system_logs)

### 3. User Management
- ✅ สร้างบัญชีผู้ใช้ใหม่
- ✅ แก้ไขโปรไฟล์
- ✅ เปลี่ยนรหัสผ่าน
- ✅ ดูสถิติการตรวจจับ
- ✅ ดูประวัติการตรวจจับของตัวเอง

## 📦 การติดตั้ง

### 1. ติดตั้ง Dependencies
```bash
pip install flask numpy librosa sounddevice soundfile tensorflow
```

### 2. สร้าง Database
```bash
python database_setup.py
```

สคริปต์นี้จะ:
- สร้าง database (snore_system.db)
- สร้างตาราง users, sessions, detection_history, etc.
- สร้างบัญชี demo user (username: demo, password: demo123)

### 3. เริ่มต้นใช้งาน Server
```bash
python server_with_auth.py
```

Server จะทำงานที่ `http://localhost:5000`

## 🔐 การใช้งาน

### หน้า Login
- URL: `http://localhost:5000/login`
- สามารถใช้บัญชี demo:
  - Username: `demo`
  - Password: `demo123`

### หน้า Register
- URL: `http://localhost:5000/register`
- กรอกข้อมูล:
  - ชื่อ-นามสกุล
  - ชื่อผู้ใช้ (3-20 ตัวอักษร, a-z, 0-9, _)
  - อีเมล
  - รหัสผ่าน (อย่างน้อย 6 ตัวอักษร)

### Dashboard
- URL: `http://localhost:5000/`
- ต้อง Login ก่อนเข้าใช้งาน
- แสดงข้อมูลและประวัติการตรวจจับของผู้ใช้

## 📊 Database Schema

### Table: users
- `user_id` (PK, AUTO_INCREMENT)
- `username` (UNIQUE)
- `email` (UNIQUE)
- `password_hash`
- `password_salt`
- `full_name`
- `created_at`
- `last_login`
- `is_active`

### Table: sessions
- `session_id` (PK)
- `user_id` (FK → users)
- `created_at`
- `expires_at`
- `ip_address`
- `user_agent`

### Table: detection_history
- `detection_id` (PK, AUTO_INCREMENT)
- `user_id` (FK → users)
- `timestamp`
- `class_name` (กรน/ไม่กรน)
- `confidence` (0-100%)
- `model_type`
- `audio_file`
- `pump_activated`
- `notes`

### Table: user_settings
- `setting_id` (PK, AUTO_INCREMENT)
- `user_id` (FK → users)
- `auto_detect_enabled`
- `detection_delay`
- `confidence_threshold`
- `notification_enabled`

### Table: system_logs
- `log_id` (PK, AUTO_INCREMENT)
- `user_id` (FK → users, nullable)
- `timestamp`
- `log_level` (INFO, WARNING, ERROR)
- `message`
- `context`

## 🔧 API Endpoints

### Authentication APIs

#### POST /api/auth/register
สมัครสมาชิกใหม่
```json
{
  "username": "johndoe",
  "email": "john@example.com",
  "password": "securepass123",
  "full_name": "John Doe"
}
```

#### POST /api/auth/login
เข้าสู่ระบบ
```json
{
  "username": "johndoe",
  "password": "securepass123",
  "remember_me": true
}
```

Response:
```json
{
  "success": true,
  "session_id": "abc123...",
  "user": {
    "user_id": 1,
    "username": "johndoe",
    "email": "john@example.com",
    "full_name": "John Doe"
  }
}
```

#### POST /api/auth/logout
ออกจากระบบ
```json
{
  "session_id": "abc123..."
}
```

#### POST /api/auth/validate
ตรวจสอบ session
```json
{
  "session_id": "abc123..."
}
```

### User APIs

#### GET /api/user/profile
ดูโปรไฟล์ (ต้อง login)

#### PUT /api/user/profile
แก้ไขโปรไฟล์
```json
{
  "full_name": "John Smith",
  "email": "john.smith@example.com"
}
```

#### POST /api/user/change-password
เปลี่ยนรหัสผ่าน
```json
{
  "old_password": "oldpass123",
  "new_password": "newpass456"
}
```

### Detection APIs (ต้อง login)

#### GET /api/detection_history
ดูประวัติการตรวจจับ

#### GET /api/detection_statistics
ดูสถิติการตรวจจับ
- Query params: `days=7` (default)

### Original System APIs (ต้อง login)
- POST /api/record - บันทึกและตรวจจับเสียง
- POST /api/auto_detect - เปิด/ปิดการตรวจจับอัตโนมัติ
- POST /api/adjust_pillow - ปรับระดับหมอน
- POST /api/deflate_pillow - ดูดลมออกจากหมอน
- GET /api/status - สถานะระบบ
- GET /api/settings - การตั้งค่า
- GET /api/logs - ดู system logs

## 🔒 Security Features

1. **Password Security**
   - SHA-256 hashing
   - Random salt per user
   - Minimum 6 characters

2. **Session Management**
   - Secure session tokens (32 bytes)
   - Automatic expiration (24 hours default)
   - IP address tracking
   - User agent tracking

3. **SQL Injection Protection**
   - Parameterized queries
   - Input validation

4. **XSS Protection**
   - HTML escaping
   - Content Security Policy headers

5. **Access Control**
   - User can only see their own data
   - Authentication required for sensitive operations

## 🛠️ Development

### Database Management

#### สร้าง User ใหม่
```python
from database_manager import DatabaseManager

db = DatabaseManager()
user_id = db.create_user(
    username="newuser",
    email="user@example.com",
    password="password123",
    full_name="New User"
)
```

#### ตรวจสอบ User
```python
user = db.authenticate_user("username", "password")
if user:
    print(f"Logged in as: {user['username']}")
```

#### เพิ่มประวัติการตรวจจับ
```python
db.add_detection_record(
    user_id=1,
    class_name="กรน",
    confidence=85.5,
    model_type="improved",
    audio_file="recording_123.wav",
    pump_activated=True
)
```

### Cleanup

#### ลบ Session ที่หมดอายุ
```python
db.cleanup_expired_sessions()
```

#### ดูสถิติ Database
```bash
python database_setup.py
```

## 📝 ไฟล์ที่สร้างขึ้น

```
project/
├── database_setup.py           # สคริปต์สร้าง database
├── database_manager.py         # จัดการ database operations
├── auth_middleware.py          # Authentication middleware
├── server_with_auth.py         # Server หลักพร้อม authentication
├── templates/
│   ├── login.html             # หน้า Login
│   ├── register.html          # หน้า Register
│   └── index.html             # Dashboard (ต้อง login)
├── static/
│   ├── js/
│   │   └── script.js          # Frontend JavaScript
│   └── css/
│       └── styles.css         # Styles
└── snore_system.db            # SQLite Database
```

## 🐛 Troubleshooting

### ปัญหา: ไม่สามารถ Login ได้
- ตรวจสอบว่า database ถูกสร้างแล้ว (`snore_system.db`)
- ตรวจสอบ username และ password
- ลองใช้บัญชี demo (username: demo, password: demo123)

### ปัญหา: Session หมดอายุเร็วเกินไป
- แก้ไขในไฟล์ `database_manager.py`:
  ```python
  expires_hours=24  # เปลี่ยนเป็น 48 หรือมากกว่า
  ```

### ปัญหา: ไม่มีข้อมูลในประวัติ
- ตรวจสอบว่า logged in แล้ว
- ลองบันทึกเสียงและตรวจจับใหม่
- ตรวจสอบ database ด้วย:
  ```bash
  sqlite3 snore_system.db "SELECT * FROM detection_history;"
  ```

## 📄 License

MIT License - ใช้งานได้เลย!

## 👨‍💻 Support

หากมีปัญหาหรือคำถาม สามารถเปิด issue ได้เลย!

---

**Happy Coding! 🎉**
