#!/usr/bin/env python3
"""
Quick Start Guide
Smart Anti-Snoring Pillow System with Authentication

เริ่มต้นใช้งานภายใน 5 นาที!
"""

print("""
╔══════════════════════════════════════════════════════════════╗
║  🛏️  Smart Anti-Snoring Pillow System - Quick Start  🛏️   ║
╚══════════════════════════════════════════════════════════════╝

📝 ขั้นตอนการเริ่มต้น (5 นาที)
""")

import os
import sys

def check_file(filename):
    """ตรวจสอบว่าไฟล์มีอยู่หรือไม่"""
    exists = os.path.exists(filename)
    status = "✅" if exists else "❌"
    print(f"   {status} {filename}")
    return exists

def check_dependencies():
    """ตรวจสอบ dependencies"""
    print("\n📦 ตรวจสอบ Dependencies:")
    
    required_modules = [
        'flask',
        'numpy',
        'sqlite3',
        'hashlib',
        'secrets'
    ]
    
    missing = []
    for module in required_modules:
        try:
            __import__(module)
            print(f"   ✅ {module}")
        except ImportError:
            print(f"   ❌ {module} (ติดตั้งด้วย: pip install {module})")
            missing.append(module)
    
    return len(missing) == 0

def main():
    print("\n🔍 ขั้นตอนที่ 1: ตรวจสอบไฟล์")
    print("=" * 60)
    
    required_files = [
        'database_setup.py',
        'database_manager.py',
        'auth_middleware.py',
        'templates/login.html',
        'templates/register.html'
    ]
    
    all_exist = all(check_file(f) for f in required_files)
    
    if not all_exist:
        print("\n❌ ไฟล์ไม่ครบ! กรุณาตรวจสอบว่าคุณได้คัดลอกไฟล์ทั้งหมดแล้ว")
        return False
    
    print("\n📦 ขั้นตอนที่ 2: ตรวจสอบ Dependencies")
    print("=" * 60)
    
    if not check_dependencies():
        print("\n❌ Dependencies ไม่ครบ! กรุณาติดตั้งก่อน")
        return False
    
    print("\n🗄️  ขั้นตอนที่ 3: สร้าง Database")
    print("=" * 60)
    
    if os.path.exists('snore_system.db'):
        print("   ℹ️  Database มีอยู่แล้ว")
        response = input("   ต้องการสร้างใหม่หรือไม่? (y/n): ")
        if response.lower() == 'y':
            os.remove('snore_system.db')
            print("   🗑️  ลบ database เดิม")
    
    print("\n   🔨 กำลังสร้าง database...")
    os.system('python database_setup.py')
    
    print("\n✅ ขั้นตอนที่ 4: เสร็จสิ้น!")
    print("=" * 60)
    
    print("""
🎉 ระบบพร้อมใช้งานแล้ว!

📚 ขั้นตอนถัดไป:

1️⃣  เพิ่ม Authentication ลงใน server เดิม:
   📖 อ่าน: INTEGRATION_GUIDE.py
   📖 หรืออ่าน: README.md

2️⃣  รัน Server:
   python server_improve_fixed.py

3️⃣  เปิด Browser:
   http://localhost:5000/login

4️⃣  Login ด้วยบัญชี Demo:
   Username: demo
   Password: demo123

📝 ไฟล์สำคัญ:
   📄 README.md                - คู่มือการใช้งานฉบับเต็ม
   📄 INTEGRATION_GUIDE.py     - วิธีเพิ่ม auth ลงใน server
   📄 PROJECT_SUMMARY.md       - สรุปโปรเจค
   📄 database_setup.py        - สคริปต์สร้าง database
   📄 database_manager.py      - จัดการ database
   📄 auth_middleware.py       - Authentication middleware

🔧 การใช้งาน Database Manager:

   from database_manager import DatabaseManager
   
   db = DatabaseManager()
   
   # สร้าง user ใหม่
   user_id = db.create_user(
       username="myuser",
       email="user@example.com",
       password="mypassword",
       full_name="My Name"
   )
   
   # ตรวจสอบ authentication
   user = db.authenticate_user("myuser", "mypassword")
   if user:
       print(f"Welcome {user['username']}!")
   
   # เพิ่มประวัติการตรวจจับ
   db.add_detection_record(
       user_id=user['user_id'],
       class_name="กรน",
       confidence=87.5,
       audio_file="recording.wav"
   )
   
   # ดูประวัติ
   history = db.get_detection_history(user_id)
   for record in history:
       print(f"{record['timestamp']}: {record['class_name']} ({record['confidence']}%)")

🆘 ต้องการความช่วยเหลือ?
   1. อ่าน README.md - คู่มือครบถ้วน
   2. ดู INTEGRATION_GUIDE.py - ตัวอย่างโค้ด
   3. ตรวจสอบ logs ใน snore_system.log

🚀 พร้อมเริ่มต้นแล้ว! Good luck!
""")
    
    return True

if __name__ == "__main__":
    try:
        success = main()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n\n⚠️  ยกเลิกโดยผู้ใช้")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n❌ เกิดข้อผิดพลาด: {str(e)}")
        sys.exit(1)
