# 🔧 คู่มือการควบคุมปั๊ม - Smart Anti-Snoring Pillow System

## 📋 สารบัญ
1. [Hardware ที่ต้องใช้](#hardware-ที่ต้องใช้)
2. [การเชื่อมต่อ (Wiring)](#การเชื่อมต่อ-wiring)
3. [การติดตั้ง Software](#การติดตั้ง-software)
4. [การตั้งค่า GPIO Pins](#การตั้งค่า-gpio-pins)
5. [วิธีใช้งาน](#วิธีใช้งาน)
6. [Troubleshooting](#troubleshooting)

---

## 🔌 Hardware ที่ต้องใช้

### 1. **Raspberry Pi** (แนะนำ Raspberry Pi 4 หรือใหม่กว่า)
- OS: Raspberry Pi OS (64-bit recommended)
- RAM: อย่างน้อย 2GB (แนะนำ 4GB+)
- Storage: MicroSD Card 16GB+

### 2. **Relay Module** (2 ตัว)
- 5V Relay Module สำหรับควบคุมปั๊ม
- แนะนำ: 2-Channel Relay Module หรือ 4-Channel Relay Module
- ต้องรองรับ 3.3V logic (หรือใช้ level shifter)

### 3. **Air Pump** (2 ตัว)
- DC Air Pump 12V หรือ 24V
- กำลังไฟตามความต้องการ (แนะนำ 5-10W)
- Flow rate: ตามความต้องการของหมอน

### 4. **Solenoid Valve** (2 ตัว)
- 12V หรือ 24V Solenoid Valve
- Normally Closed (NC) type
- ต้องใช้กับ Relay Module

### 5. **Power Supply**
- 12V หรือ 24V Power Supply สำหรับปั๊มและวาล์ว
- กำลังไฟเพียงพอสำหรับปั๊ม 2 ตัว + วาล์ว 2 ตัว
- แนะนำ: 12V 5A หรือ 24V 3A

### 6. **Jumper Wires**
- Female-to-Male jumper wires สำหรับเชื่อมต่อ Relay กับ Raspberry Pi
- อย่างน้อย 8 เส้น (4 pins × 2 relays)

---

## 🔗 การเชื่อมต่อ (Wiring)

### GPIO Pin Configuration

```
Raspberry Pi GPIO Pins:
├── GPIO 17 (Physical Pin 11) → Relay 1 IN (Pump 1)
├── GPIO 27 (Physical Pin 13) → Relay 2 IN (Pump 2)
├── GPIO 23 (Physical Pin 16) → Relay 3 IN (Valve 1)
└── GPIO 24 (Physical Pin 18) → Relay 4 IN (Valve 2)

Power Connections:
├── 5V (Pin 2) → Relay Module VCC
├── GND (Pin 6) → Relay Module GND
└── GND → Power Supply GND (Common Ground)
```

### Relay Module Connections

```
Relay Module 1 (Pump 1):
├── IN → GPIO 17 (Raspberry Pi)
├── VCC → 5V (Raspberry Pi)
├── GND → GND (Raspberry Pi)
├── COM → Power Supply Positive (+)
└── NO → Pump 1 Positive (+)

Relay Module 2 (Pump 2):
├── IN → GPIO 27 (Raspberry Pi)
├── VCC → 5V (Raspberry Pi)
├── GND → GND (Raspberry Pi)
├── COM → Power Supply Positive (+)
└── NO → Pump 2 Positive (+)

Relay Module 3 (Valve 1):
├── IN → GPIO 23 (Raspberry Pi)
├── VCC → 5V (Raspberry Pi)
├── GND → GND (Raspberry Pi)
├── COM → Power Supply Positive (+)
└── NO → Valve 1 Positive (+)

Relay Module 4 (Valve 2):
├── IN → GPIO 24 (Raspberry Pi)
├── VCC → 5V (Raspberry Pi)
├── GND → GND (Raspberry Pi)
├── COM → Power Supply Positive (+)
└── NO → Valve 2 Positive (+)
```

### ⚠️ ข้อควรระวัง
1. **Common Ground**: ต้องเชื่อม GND ของ Raspberry Pi กับ GND ของ Power Supply
2. **Voltage Level**: ตรวจสอบว่า Relay Module รองรับ 3.3V logic หรือใช้ level shifter
3. **Current Rating**: ตรวจสอบว่า Relay Module รองรับกระแสของปั๊มและวาล์ว
4. **Fuse Protection**: แนะนำให้ใส่ fuse เพื่อป้องกันกระแสเกิน

---

## 💻 การติดตั้ง Software

### 1. ติดตั้ง Dependencies บน Raspberry Pi

```bash
# อัปเดตระบบ
sudo apt update && sudo apt upgrade -y

# ติดตั้ง Python และ pip
sudo apt install python3 python3-pip python3-venv -y

# ติดตั้ง GPIO library
sudo apt install python3-lgpio -y

# ติดตั้ง PortAudio สำหรับ sounddevice (ถ้าต้องการ server-side recording)
sudo apt install portaudio19-dev -y

# ติดตั้ง dependencies อื่นๆ
sudo apt install libasound2-dev libsndfile1 -y
```

### 2. Clone หรือ Copy โปรเจกต์

```bash
# สร้างโฟลเดอร์โปรเจกต์
mkdir -p ~/anti_snore
cd ~/anti_snore

# Copy ไฟล์โปรเจกต์มาที่นี่
# หรือ clone จาก git repository
```

### 3. สร้าง Virtual Environment

```bash
python3 -m venv venv
source venv/bin/activate
```

### 4. ติดตั้ง Python Packages

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

### 5. ตั้งค่า Database

```bash
# สำหรับ SQLite (development)
python database_setup.py

# หรือสำหรับ PostgreSQL (production)
export DATABASE_URL=postgresql://user:pass@localhost:5432/snore_system
python database_setup_postgresql.py
```

### 6. ตั้งค่า Environment Variables

```bash
# สร้างไฟล์ .env
nano .env
```

เพิ่มเนื้อหา:
```bash
# Flask
SECRET_KEY=your-super-secret-key-change-this-in-production
DEBUG=False

# Server
PORT=5000
HOST=0.0.0.0

# Database (ถ้าใช้ PostgreSQL)
DATABASE_URL=postgresql://user:pass@localhost:5432/snore_system
```

---

## ⚙️ การตั้งค่า GPIO Pins

### ตรวจสอบ GPIO Pins ในโค้ด

ไฟล์ `server_improve_fixed.py` มีการตั้งค่า GPIO pins ดังนี้:

```python
# GPIO Configuration
PUMP_RELAY_PIN: int = 17      # GPIO 17 สำหรับ Pump 1
PUMP_RELAY_PIN_2: int = 27   # GPIO 27 สำหรับ Pump 2
SOLENOID_VALVE_PIN_1: int = 23  # GPIO 23 สำหรับ Valve 1
SOLENOID_VALVE_PIN_2: int = 24  # GPIO 24 สำหรับ Valve 2
```

### เปลี่ยน GPIO Pins (ถ้าจำเป็น)

ถ้าต้องการเปลี่ยน GPIO pins ให้แก้ไขใน `server_improve_fixed.py`:

```python
@dataclass
class SystemConfig:
    # GPIO Configuration
    PUMP_RELAY_PIN: int = 17      # เปลี่ยนเป็น pin ที่ต้องการ
    PUMP_RELAY_PIN_2: int = 27    # เปลี่ยนเป็น pin ที่ต้องการ
    SOLENOID_VALVE_PIN_1: int = 23  # เปลี่ยนเป็น pin ที่ต้องการ
    SOLENOID_VALVE_PIN_2: int = 24  # เปลี่ยนเป็น pin ที่ต้องการ
```

### ตรวจสอบ GPIO Pins

```bash
# ตรวจสอบว่า GPIO pins ใช้งานได้หรือไม่
gpio readall

# หรือใช้ Python
python3 -c "import lgpio; h = lgpio.gpiochip_open(0); print('GPIO available')"
```

---

## 🚀 วิธีใช้งาน

### 1. เริ่มต้น Server

```bash
# เปิด virtual environment
source venv/bin/activate

# เริ่มต้น server
python server_improve_fixed.py
```

หรือใช้ Gunicorn (production):

```bash
gunicorn server_improve_fixed:app --bind 0.0.0.0:5000 --workers 2
```

### 2. เข้าถึง Web Interface

เปิดเบราว์เซอร์:
```
http://raspberry-pi-ip:5000
```

หรือถ้า deploy บน Render:
```
https://your-app-name.onrender.com
```

### 3. ควบคุมปั๊มผ่าน Web Interface

#### วิธีที่ 1: ควบคุมปั๊มด้วยตนเอง
1. Login เข้าระบบ
2. ไปที่ส่วน "การควบคุมปั๊ม"
3. คลิกปุ่ม "เปิด Pump 1" หรือ "เปิด Pump 2"
4. ระบบจะเปิด Pump และ Valve พร้อมกัน

#### วิธีที่ 2: ควบคุมผ่าน Auto Detection
1. เปิด "การตรวจจับเสียงกรนอัตโนมัติ"
2. ระบบจะอัดเสียงเป็นระยะๆ
3. เมื่อตรวจจับเสียงกรนได้ (confidence > 85%)
4. ระบบจะควบคุมปั๊มอัตโนมัติ:
   - เปิด Pump 1 + Valve 1 เป็นเวลา 50 วินาที
   - รอ 60 วินาที
   - เปิด Pump 2 + Valve 2 เป็นเวลา 20 วินาที

#### วิธีที่ 3: ควบคุมผ่าน API

```bash
# เปิด Pump 1
curl -X POST http://raspberry-pi-ip:5000/api/pump \
  -H "Content-Type: application/json" \
  -H "Cookie: session_id=your-session-id" \
  -d '{"pump": 1, "action": "ON"}'

# ปิด Pump 1
curl -X POST http://raspberry-pi-ip:5000/api/pump \
  -H "Content-Type: application/json" \
  -H "Cookie: session_id=your-session-id" \
  -d '{"pump": 1, "action": "OFF"}'
```

### 4. ตรวจสอบสถานะ

ดูสถานะ GPIO:
```bash
# ดู logs
tail -f snore_system.log

# หรือดูผ่าน Web Interface
# ไปที่หน้า Dashboard → ดู System Status
```

---

## 🔍 Troubleshooting

### ปัญหา: GPIO ไม่ทำงาน

**อาการ:**
```
❌ GPIO initialization failed: ...
GPIO not available
```

**วิธีแก้:**
1. ตรวจสอบว่าใช้ Raspberry Pi OS
2. ตรวจสอบว่า lgpio ติดตั้งแล้ว: `pip list | grep lgpio`
3. ตรวจสอบสิทธิ์: `sudo usermod -a -G gpio $USER` แล้ว logout/login
4. ตรวจสอบ wiring ว่าถูกต้องหรือไม่

### ปัญหา: Relay ไม่ทำงาน

**อาการ:**
- Relay ไม่เปิด/ปิด
- Pump ไม่ทำงาน

**วิธีแก้:**
1. ตรวจสอบ voltage: วัดที่ VCC ของ Relay ควรได้ 5V
2. ตรวจสอบ logic level: Relay บางตัวต้องการ 5V logic (ใช้ level shifter)
3. ตรวจสอบ wiring: ตรวจสอบว่า IN, VCC, GND เชื่อมต่อถูกต้อง
4. ทดสอบ Relay: ใช้ multimeter วัด continuity

### ปัญหา: Pump ไม่ทำงาน

**อาการ:**
- Relay เปิดแล้วแต่ Pump ไม่ทำงาน

**วิธีแก้:**
1. ตรวจสอบ Power Supply: วัด voltage ที่ Pump ควรได้ 12V หรือ 24V
2. ตรวจสอบ Polarity: ตรวจสอบว่า + และ - ต่อถูกต้อง
3. ตรวจสอบ Current: วัดกระแสที่ Pump ว่าพอหรือไม่
4. ทดสอบ Pump: ต่อตรงกับ Power Supply เพื่อทดสอบ

### ปัญหา: Valve ไม่ทำงาน

**อาการ:**
- Valve ไม่เปิด/ปิด

**วิธีแก้:**
1. ตรวจสอบ Voltage: วัดที่ Valve ควรได้ 12V หรือ 24V
2. ตรวจสอบ Wiring: ตรวจสอบว่า COM และ NO ต่อถูกต้อง
3. ทดสอบ Valve: ต่อตรงกับ Power Supply เพื่อทดสอบ

### ปัญหา: Server ไม่เริ่มต้น

**อาการ:**
```
Failed to create app: ...
```

**วิธีแก้:**
1. ตรวจสอบ dependencies: `pip install -r requirements.txt`
2. ตรวจสอบ database: `python database_setup.py`
3. ตรวจสอบ logs: `tail -f snore_system.log`
4. ตรวจสอบ permissions: `chmod +x server_improve_fixed.py`

---

## 📝 หมายเหตุ

### Safety Tips
1. **Always disconnect power** ก่อนแก้ไข wiring
2. **Use proper fuses** เพื่อป้องกันกระแสเกิน
3. **Check voltage** ก่อนเชื่อมต่ออุปกรณ์
4. **Use proper wire gauge** ตามกระแสที่ใช้

### Best Practices
1. **Test components individually** ก่อนเชื่อมต่อทั้งหมด
2. **Use multimeter** เพื่อตรวจสอบ voltage และ continuity
3. **Keep wiring organized** เพื่อป้องกันการสับสน
4. **Document your setup** เพื่ออ้างอิงในอนาคต

---

## 🎯 สรุป

### Hardware Setup Checklist
- [ ] Raspberry Pi พร้อม OS
- [ ] Relay Module 4 ตัว (หรือ 4-channel relay)
- [ ] Air Pump 2 ตัว
- [ ] Solenoid Valve 2 ตัว
- [ ] Power Supply
- [ ] Jumper Wires

### Software Setup Checklist
- [ ] ติดตั้ง Python และ dependencies
- [ ] ติดตั้ง lgpio library
- [ ] ตั้งค่า database
- [ ] ตั้งค่า environment variables
- [ ] ทดสอบ GPIO

### Testing Checklist
- [ ] ทดสอบ Relay แต่ละตัว
- [ ] ทดสอบ Pump แต่ละตัว
- [ ] ทดสอบ Valve แต่ละตัว
- [ ] ทดสอบ Web Interface
- [ ] ทดสอบ Auto Detection

---

**Happy Building! 🔧**

