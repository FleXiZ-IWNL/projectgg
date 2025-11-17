# 🌉 คู่มือการเชื่อมต่อ Render กับ Raspberry Pi เพื่อควบคุมปั๊ม

## ✅ คำตอบ: **ได้!** โดยใช้ Bridge Service

---

## 📋 สารบัญ
1. [ภาพรวมระบบ](#ภาพรวมระบบ)
2. [วิธีที่ 1: HTTP API Bridge (แนะนำ)](#วิธีที่-1-http-api-bridge-แนะนำ)
3. [วิธีที่ 2: MQTT Bridge](#วิธีที่-2-mqtt-bridge)
4. [วิธีที่ 3: WebSocket Bridge](#วิธีที่-3-websocket-bridge)
5. [วิธีที่ 4: Webhook Service](#วิธีที่-4-webhook-service)
6. [การตั้งค่า Security](#การตั้งค่า-security)
7. [Troubleshooting](#troubleshooting)

---

## 🏗️ ภาพรวมระบบ

### สถาปัตยกรรม

```
┌─────────────┐         ┌──────────────┐         ┌─────────────┐
│   Render    │  HTTP   │  Raspberry   │  GPIO   │   Pump/      │
│  (Web App)  │ ──────> │  Pi Bridge   │ ──────> │   Valve      │
│             │         │   Service    │         │              │
└─────────────┘         └──────────────┘         └─────────────┘
     │                        │
     │                        │
     └────────────────────────┘
        (Internet/Network)
```

### หลักการทำงาน

1. **Render (Web App):**
   - อัดเสียง, Predict, แสดงผล
   - ส่งคำสั่งควบคุมปั๊มไปยัง Raspberry Pi

2. **Raspberry Pi (Bridge Service):**
   - รับคำสั่งจาก Render
   - ควบคุม GPIO/Pump/Valve
   - ส่งสถานะกลับไปยัง Render

---

## 🔌 วิธีที่ 1: HTTP API Bridge (แนะนำ)

### ขั้นตอนที่ 1: สร้าง Bridge Service บน Raspberry Pi

สร้างไฟล์ `bridge_service.py` บน Raspberry Pi:

```python
#!/usr/bin/env python3
"""
Bridge Service สำหรับรับคำสั่งจาก Render และควบคุม GPIO
"""

from flask import Flask, request, jsonify
from flask_cors import CORS
import lgpio
import time
import os
import hashlib
import hmac

app = Flask(__name__)
CORS(app)

# Security: API Key สำหรับยืนยันตัวตน
API_KEY = os.environ.get('BRIDGE_API_KEY', 'change-this-secret-key')

# GPIO Configuration
PUMP_RELAY_PIN = 17
PUMP_RELAY_PIN_2 = 27
SOLENOID_VALVE_PIN_1 = 23
SOLENOID_VALVE_PIN_2 = 24

# GPIO Handler
h = None
gpio_initialized = False

def init_gpio():
    global h, gpio_initialized
    try:
        h = lgpio.gpiochip_open(0)
        lgpio.gpio_claim_output(h, PUMP_RELAY_PIN, 0)
        lgpio.gpio_claim_output(h, PUMP_RELAY_PIN_2, 0)
        lgpio.gpio_claim_output(h, SOLENOID_VALVE_PIN_1, 0)
        lgpio.gpio_claim_output(h, SOLENOID_VALVE_PIN_2, 0)
        gpio_initialized = True
        print("✅ GPIO initialized")
        return True
    except Exception as e:
        print(f"❌ GPIO initialization failed: {e}")
        gpio_initialized = False
        return False

def verify_api_key():
    """ตรวจสอบ API Key"""
    api_key = request.headers.get('X-API-Key')
    if not api_key:
        return False
    return hmac.compare_digest(api_key, API_KEY)

@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint"""
    return jsonify({
        "status": "ok",
        "gpio_initialized": gpio_initialized
    })

@app.route('/api/pump', methods=['POST'])
def control_pump():
    """ควบคุมปั๊ม"""
    if not verify_api_key():
        return jsonify({"success": False, "message": "Unauthorized"}), 401
    
    if not gpio_initialized:
        return jsonify({"success": False, "message": "GPIO not available"}), 500
    
    try:
        data = request.json
        pump_number = data.get('pump', 1)
        action = data.get('action', 'OFF').upper()
        
        # Select pins
        if pump_number == 1:
            pump_pin = PUMP_RELAY_PIN
            valve_pin = SOLENOID_VALVE_PIN_1
        elif pump_number == 2:
            pump_pin = PUMP_RELAY_PIN_2
            valve_pin = SOLENOID_VALVE_PIN_2
        else:
            return jsonify({"success": False, "message": "Invalid pump number"}), 400
        
        # Control pump
        if action == "ON":
            lgpio.gpio_write(h, valve_pin, 1)
            time.sleep(0.1)
            lgpio.gpio_write(h, pump_pin, 1)
        else:
            lgpio.gpio_write(h, pump_pin, 0)
            time.sleep(0.1)
            lgpio.gpio_write(h, valve_pin, 0)
        
        return jsonify({
            "success": True,
            "message": f"Pump {pump_number} {action}"
        })
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

@app.route('/api/valve', methods=['POST'])
def control_valve():
    """ควบคุมวาล์ว"""
    if not verify_api_key():
        return jsonify({"success": False, "message": "Unauthorized"}), 401
    
    if not gpio_initialized:
        return jsonify({"success": False, "message": "GPIO not available"}), 500
    
    try:
        data = request.json
        valve_number = data.get('valve', 1)
        action = data.get('action', 'OFF').upper()
        
        if valve_number == 1:
            valve_pin = SOLENOID_VALVE_PIN_1
        elif valve_number == 2:
            valve_pin = SOLENOID_VALVE_PIN_2
        else:
            return jsonify({"success": False, "message": "Invalid valve number"}), 400
        
        lgpio.gpio_write(h, valve_pin, 1 if action == "ON" else 0)
        
        return jsonify({
            "success": True,
            "message": f"Valve {valve_number} {action}"
        })
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

@app.route('/api/status', methods=['GET'])
def get_status():
    """ดูสถานะ"""
    if not verify_api_key():
        return jsonify({"success": False, "message": "Unauthorized"}), 401
    
    return jsonify({
        "success": True,
        "gpio_initialized": gpio_initialized,
        "status": "ready"
    })

if __name__ == '__main__':
    init_gpio()
    port = int(os.environ.get('BRIDGE_PORT', 8080))
    app.run(host='0.0.0.0', port=port, debug=False)
```

### ขั้นตอนที่ 2: ติดตั้งและรัน Bridge Service

```bash
# บน Raspberry Pi
cd ~/anti_snore

# ติดตั้ง dependencies
pip install flask flask-cors

# ตั้งค่า API Key
export BRIDGE_API_KEY="your-super-secret-api-key-here"
export BRIDGE_PORT=8080

# รัน bridge service
python bridge_service.py
```

### ขั้นตอนที่ 3: ตั้งค่าให้ Bridge Service เริ่มอัตโนมัติ

```bash
# สร้าง systemd service
sudo nano /etc/systemd/system/bridge-service.service
```

เพิ่มเนื้อหา:
```ini
[Unit]
Description=GPIO Bridge Service
After=network.target

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/anti_snore
Environment="BRIDGE_API_KEY=your-super-secret-api-key-here"
Environment="BRIDGE_PORT=8080"
ExecStart=/usr/bin/python3 /home/pi/anti_snore/bridge_service.py
Restart=always

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable bridge-service
sudo systemctl start bridge-service
```

### ขั้นตอนที่ 4: ตั้งค่าให้เข้าถึงได้จากภายนอก

```bash
# ตั้งค่า firewall
sudo ufw allow 8080/tcp

# ตั้งค่า port forwarding (ถ้าจำเป็น)
# External Port: 8080 → Internal IP: Raspberry Pi IP
```

### ขั้นตอนที่ 5: แก้ไขโค้ดบน Render

เพิ่ม Remote GPIO Controller ใน `server_improve_fixed.py`:

```python
# เพิ่มที่ส่วนบนของไฟล์
import requests

# เพิ่มใน SystemConfig
@dataclass
class SystemConfig:
    # ... existing config ...
    
    # Remote GPIO Configuration
    REMOTE_GPIO_ENABLED: bool = os.environ.get('REMOTE_GPIO_ENABLED', 'False').lower() == 'true'
    REMOTE_GPIO_URL: str = os.environ.get('REMOTE_GPIO_URL', 'http://raspberry-pi-ip:8080')
    REMOTE_GPIO_API_KEY: str = os.environ.get('REMOTE_GPIO_API_KEY', '')

# แก้ไข GPIOController class
class GPIOController:
    def __init__(self, config: SystemConfig, data_store: ThreadSafeData):
        self.config = config
        self.data_store = data_store
        self.h = None
        self.gpio_initialized = False
        self.remote_mode = config.REMOTE_GPIO_ENABLED
        self._lock = Lock()
        
        if self.remote_mode:
            self._initialize_remote_gpio()
        else:
            self._initialize_gpio()
    
    def _initialize_remote_gpio(self):
        """Initialize remote GPIO connection"""
        try:
            # Test connection
            response = requests.get(
                f"{self.config.REMOTE_GPIO_URL}/health",
                timeout=5
            )
            if response.status_code == 200:
                self.gpio_initialized = True
                self.data_store.update_status(gpio_ready=True)
                self.data_store.add_log_entry("✅ Remote GPIO initialized")
                logger.info("Remote GPIO initialized")
            else:
                raise Exception(f"Remote GPIO health check failed: {response.status_code}")
        except Exception as e:
            self.gpio_initialized = False
            self.data_store.update_status(gpio_ready=False)
            self.data_store.add_log_entry(f"❌ Remote GPIO initialization failed: {str(e)}")
            logger.warning(f"Remote GPIO not available: {str(e)}")
    
    def control_pump(self, pin_number: int, action: str) -> Dict[str, Any]:
        """Control pump - supports both local and remote"""
        if not self.gpio_initialized:
            return {"success": False, "message": "GPIO not available"}
        
        if self.remote_mode:
            return self._control_pump_remote(pin_number, action)
        else:
            return self._control_pump_local(pin_number, action)
    
    def _control_pump_remote(self, pin_number: int, action: str) -> Dict[str, Any]:
        """Control pump via remote API"""
        try:
            response = requests.post(
                f"{self.config.REMOTE_GPIO_URL}/api/pump",
                json={"pump": pin_number, "action": action},
                headers={"X-API-Key": self.config.REMOTE_GPIO_API_KEY},
                timeout=10
            )
            
            if response.status_code == 200:
                result = response.json()
                status_msg = f"💨 Pump {pin_number} & Valve {pin_number}: {action}"
                self.data_store.add_log_entry(status_msg)
                return result
            else:
                error_msg = f"Remote GPIO error: {response.status_code}"
                self.data_store.add_log_entry(f"❌ {error_msg}")
                return {"success": False, "message": error_msg}
        except Exception as e:
            error_msg = f"❌ Remote GPIO communication failed: {str(e)}"
            self.data_store.add_log_entry(error_msg)
            return {"success": False, "message": str(e)}
    
    def _control_pump_local(self, pin_number: int, action: str) -> Dict[str, Any]:
        """Control pump locally (existing code)"""
        # ... existing local GPIO code ...
```

### ขั้นตอนที่ 6: ตั้งค่า Environment Variables บน Render

ใน Render Dashboard → Environment Variables:

```
REMOTE_GPIO_ENABLED=True
REMOTE_GPIO_URL=http://your-raspberry-pi-ip:8080
REMOTE_GPIO_API_KEY=your-super-secret-api-key-here
```

### ขั้นตอนที่ 7: อัปเดต requirements.txt

```bash
# เพิ่มใน requirements.txt
requests==2.31.0
flask-cors==4.0.0  # สำหรับ bridge service (บน Raspberry Pi)
```

---

## 📡 วิธีที่ 2: MQTT Bridge

### ใช้ MQTT Broker (เช่น HiveMQ, Mosquitto)

#### ขั้นตอนที่ 1: ติดตั้ง MQTT Broker

```bash
# บน Raspberry Pi หรือใช้ Cloud MQTT (HiveMQ Cloud - ฟรี)
sudo apt install mosquitto mosquitto-clients -y
```

#### ขั้นตอนที่ 2: สร้าง MQTT Client บน Raspberry Pi

```python
# mqtt_bridge.py
import paho.mqtt.client as mqtt
import lgpio
import json

MQTT_BROKER = "your-mqtt-broker.com"
MQTT_PORT = 1883
MQTT_TOPIC = "anti_snore/pump/control"
MQTT_USERNAME = "your-username"
MQTT_PASSWORD = "your-password"

# GPIO setup (same as before)
h = lgpio.gpiochip_open(0)
# ... GPIO pins setup ...

def on_message(client, userdata, msg):
    """Handle incoming MQTT messages"""
    try:
        data = json.loads(msg.payload.decode())
        pump_number = data.get('pump', 1)
        action = data.get('action', 'OFF')
        
        # Control pump
        # ... GPIO control code ...
        
    except Exception as e:
        print(f"Error: {e}")

client = mqtt.Client()
client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)
client.on_message = on_message
client.connect(MQTT_BROKER, MQTT_PORT, 60)
client.subscribe(MQTT_TOPIC)
client.loop_forever()
```

#### ขั้นตอนที่ 3: ส่งคำสั่งจาก Render

```python
# ใน server_improve_fixed.py
import paho.mqtt.client as mqtt

def send_mqtt_command(pump_number, action):
    client = mqtt.Client()
    client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)
    client.connect(MQTT_BROKER, MQTT_PORT, 60)
    client.publish(
        MQTT_TOPIC,
        json.dumps({"pump": pump_number, "action": action})
    )
    client.disconnect()
```

---

## 🔌 วิธีที่ 3: WebSocket Bridge

### ใช้ WebSocket สำหรับ real-time communication

```python
# websocket_bridge.py (บน Raspberry Pi)
from flask import Flask
from flask_socketio import SocketIO, emit
import lgpio

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*")

@socketio.on('control_pump')
def handle_pump_control(data):
    pump_number = data['pump']
    action = data['action']
    # Control GPIO
    # ...
    emit('pump_status', {'success': True})

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=8080)
```

---

## 🔗 วิธีที่ 4: Webhook Service

### ใช้ Webhook สำหรับ simple integration

```python
# ใน server_improve_fixed.py (บน Render)
import requests

def send_webhook_command(pump_number, action):
    webhook_url = os.environ.get('RASPBERRY_PI_WEBHOOK_URL')
    api_key = os.environ.get('RASPBERRY_PI_API_KEY')
    
    requests.post(
        webhook_url,
        json={"pump": pump_number, "action": action},
        headers={"X-API-Key": api_key},
        timeout=10
    )
```

---

## 🔐 การตั้งค่า Security

### 1. ใช้ HTTPS สำหรับ Bridge Service

```bash
# ตั้งค่า Nginx + Let's Encrypt
sudo certbot --nginx -d bridge.your-domain.com
```

### 2. ใช้ API Key Authentication

```python
# ตรวจสอบ API Key ในทุก request
def verify_api_key():
    api_key = request.headers.get('X-API-Key')
    return hmac.compare_digest(api_key, SECRET_API_KEY)
```

### 3. ใช้ IP Whitelist (ถ้าจำเป็น)

```python
ALLOWED_IPS = ['render-ip-1', 'render-ip-2']

@app.before_request
def check_ip():
    if request.remote_addr not in ALLOWED_IPS:
        return jsonify({"error": "Forbidden"}), 403
```

### 4. ใช้ Rate Limiting

```python
from flask_limiter import Limiter

limiter = Limiter(
    app,
    key_func=lambda: request.remote_addr,
    default_limits=["100 per hour"]
)
```

---

## 🔍 Troubleshooting

### ปัญหา: ไม่สามารถเชื่อมต่อกับ Raspberry Pi

**ตรวจสอบ:**
1. Bridge Service ทำงานอยู่หรือไม่: `sudo systemctl status bridge-service`
2. Firewall อนุญาต port 8080: `sudo ufw status`
3. Port Forwarding ตั้งค่าถูกต้องหรือไม่
4. Network connectivity: `ping raspberry-pi-ip`

### ปัญหา: API Key ไม่ถูกต้อง

**ตรวจสอบ:**
1. API Key ตรงกันทั้งสองฝั่ง
2. Header name ถูกต้อง: `X-API-Key`
3. ไม่มี whitespace หรือ special characters

### ปัญหา: Timeout

**วิธีแก้:**
1. เพิ่ม timeout ใน requests
2. ตรวจสอบ network latency
3. ใช้ connection pooling

---

## 📝 Checklist

### บน Raspberry Pi:
- [ ] Bridge Service ติดตั้งและรันแล้ว
- [ ] GPIO ทำงานได้
- [ ] Firewall อนุญาต port
- [ ] Port Forwarding ตั้งค่าแล้ว
- [ ] API Key ตั้งค่าแล้ว
- [ ] HTTPS ตั้งค่าแล้ว (แนะนำ)

### บน Render:
- [ ] Environment Variables ตั้งค่าแล้ว
- [ ] REMOTE_GPIO_ENABLED=True
- [ ] REMOTE_GPIO_URL ถูกต้อง
- [ ] REMOTE_GPIO_API_KEY ตรงกัน
- [ ] requests library ติดตั้งแล้ว

---

## 🎯 สรุป

### ✅ **ใช้งานบน Render แล้วควบคุมปั๊มได้!**

**วิธีที่แนะนำ:**
1. **HTTP API Bridge** - ง่ายที่สุด, ใช้งานง่าย
2. **MQTT Bridge** - เหมาะสำหรับ real-time, scalable
3. **WebSocket Bridge** - เหมาะสำหรับ real-time bidirectional
4. **Webhook Service** - เหมาะสำหรับ simple integration

**ขั้นตอนหลัก:**
1. สร้าง Bridge Service บน Raspberry Pi
2. ตั้งค่าให้เข้าถึงได้จากภายนอก
3. แก้ไขโค้ดบน Render ให้ส่งคำสั่งไปยัง Bridge
4. ตั้งค่า Security (API Key, HTTPS)

---

**Happy Bridging! 🌉**

