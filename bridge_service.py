#!/usr/bin/env python3
"""
GPIO Bridge Service สำหรับรับคำสั่งจาก Render และควบคุม GPIO
รันบน Raspberry Pi เพื่อให้ Render สามารถควบคุมปั๊มได้
"""

from flask import Flask, request, jsonify
from flask_cors import CORS
import os
import hmac
import time
import logging

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)

# Security: API Key สำหรับยืนยันตัวตน
API_KEY = os.environ.get('BRIDGE_API_KEY', 'change-this-secret-key')

# GPIO Configuration
PUMP_RELAY_PIN = int(os.environ.get('PUMP_RELAY_PIN', 17))
PUMP_RELAY_PIN_2 = int(os.environ.get('PUMP_RELAY_PIN_2', 27))
SOLENOID_VALVE_PIN_1 = int(os.environ.get('SOLENOID_VALVE_PIN_1', 23))
SOLENOID_VALVE_PIN_2 = int(os.environ.get('SOLENOID_VALVE_PIN_2', 24))

# GPIO Handler
h = None
gpio_initialized = False

def init_gpio():
    """Initialize GPIO"""
    global h, gpio_initialized
    try:
        import lgpio
        h = lgpio.gpiochip_open(0)
        lgpio.gpio_claim_output(h, PUMP_RELAY_PIN, 0)
        lgpio.gpio_claim_output(h, PUMP_RELAY_PIN_2, 0)
        lgpio.gpio_claim_output(h, SOLENOID_VALVE_PIN_1, 0)
        lgpio.gpio_claim_output(h, SOLENOID_VALVE_PIN_2, 0)
        gpio_initialized = True
        logger.info("✅ GPIO initialized")
        return True
    except Exception as e:
        logger.error(f"❌ GPIO initialization failed: {e}")
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
        "gpio_initialized": gpio_initialized,
        "service": "GPIO Bridge Service"
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
        if not data:
            return jsonify({"success": False, "message": "No data provided"}), 400
        
        pump_number = data.get('pump', 1)
        action = data.get('action', 'OFF').upper()
        
        if action not in ['ON', 'OFF']:
            return jsonify({"success": False, "message": "Invalid action (must be ON or OFF)"}), 400
        
        # Select pins
        if pump_number == 1:
            pump_pin = PUMP_RELAY_PIN
            valve_pin = SOLENOID_VALVE_PIN_1
        elif pump_number == 2:
            pump_pin = PUMP_RELAY_PIN_2
            valve_pin = SOLENOID_VALVE_PIN_2
        else:
            return jsonify({"success": False, "message": "Invalid pump number (must be 1 or 2)"}), 400
        
        # Control pump
        import lgpio
        if action == "ON":
            # Turn on valve first, then pump
            lgpio.gpio_write(h, valve_pin, 1)
            time.sleep(0.1)  # Small delay to ensure valve opens
            lgpio.gpio_write(h, pump_pin, 1)
            logger.info(f"Pump {pump_number} & Valve {pump_number}: ON")
        else:
            # Turn off pump first, then valve
            lgpio.gpio_write(h, pump_pin, 0)
            time.sleep(0.1)  # Small delay to ensure pump stops
            lgpio.gpio_write(h, valve_pin, 0)
            logger.info(f"Pump {pump_number} & Valve {pump_number}: OFF")
        
        return jsonify({
            "success": True,
            "message": f"Pump {pump_number} & Valve {pump_number} {action}"
        })
    except Exception as e:
        logger.error(f"Pump control error: {e}")
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
        if not data:
            return jsonify({"success": False, "message": "No data provided"}), 400
        
        valve_number = data.get('valve', 1)
        action = data.get('action', 'OFF').upper()
        
        if action not in ['ON', 'OFF']:
            return jsonify({"success": False, "message": "Invalid action (must be ON or OFF)"}), 400
        
        if valve_number == 1:
            valve_pin = SOLENOID_VALVE_PIN_1
        elif valve_number == 2:
            valve_pin = SOLENOID_VALVE_PIN_2
        else:
            return jsonify({"success": False, "message": "Invalid valve number (must be 1 or 2)"}), 400
        
        import lgpio
        lgpio.gpio_write(h, valve_pin, 1 if action == "ON" else 0)
        logger.info(f"Valve {valve_number}: {action}")
        
        return jsonify({
            "success": True,
            "message": f"Valve {valve_number} {action}"
        })
    except Exception as e:
        logger.error(f"Valve control error: {e}")
        return jsonify({"success": False, "message": str(e)}), 500

@app.route('/api/status', methods=['GET'])
def get_status():
    """ดูสถานะ"""
    if not verify_api_key():
        return jsonify({"success": False, "message": "Unauthorized"}), 401
    
    return jsonify({
        "success": True,
        "gpio_initialized": gpio_initialized,
        "status": "ready",
        "pins": {
            "pump1": PUMP_RELAY_PIN,
            "pump2": PUMP_RELAY_PIN_2,
            "valve1": SOLENOID_VALVE_PIN_1,
            "valve2": SOLENOID_VALVE_PIN_2
        }
    })

if __name__ == '__main__':
    logger.info("Starting GPIO Bridge Service...")
    logger.info(f"API Key: {'*' * 20} (hidden)")
    logger.info(f"GPIO Pins - Pump1: {PUMP_RELAY_PIN}, Pump2: {PUMP_RELAY_PIN_2}")
    logger.info(f"GPIO Pins - Valve1: {SOLENOID_VALVE_PIN_1}, Valve2: {SOLENOID_VALVE_PIN_2}")
    
    init_gpio()
    
    port = int(os.environ.get('BRIDGE_PORT', 8080))
    host = os.environ.get('BRIDGE_HOST', '0.0.0.0')
    
    logger.info(f"Bridge Service listening on {host}:{port}")
    logger.info("Ready to receive commands from Render...")
    
    app.run(host=host, port=port, debug=False)

