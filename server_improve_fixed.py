import os
import sys
import time
import json
import datetime
import logging
import atexit
import threading
from threading import Thread, Lock, Event
from queue import Queue, Empty
from dataclasses import dataclass
from typing import Optional, Dict, Any, List
import signal
from database_manager import DatabaseManager
from auth_middleware import AuthMiddleware, get_client_ip, get_user_agent
from flask import session, redirect, url_for

# Suppress TensorFlow warnings
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'
import warnings
warnings.filterwarnings('ignore')

from flask import Flask, jsonify, request, render_template, send_from_directory
from werkzeug.utils import secure_filename
import numpy as np
# Optional import for remote GPIO control
try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False
    requests = None
import librosa
# Optional import for sounddevice (not available on cloud platforms like Render)
try:
    import sounddevice as sd
    SOUNDDEVICE_AVAILABLE = True
except (ImportError, OSError):
    SOUNDDEVICE_AVAILABLE = False
    sd = None
import soundfile as sf
import tensorflow as tf
from tensorflow.keras.models import load_model

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('snore_system.log'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# Log sounddevice availability after logger is initialized
if not SOUNDDEVICE_AVAILABLE:
    logger.warning("sounddevice not available - server-side recording disabled (this is normal on cloud platforms)")

db_manager_global = None

# Suppress TensorFlow logging
tf.get_logger().setLevel(logging.ERROR)

# --- Configuration ---
@dataclass
class SystemConfig:
    # GPIO Configuration
    PUMP_RELAY_PIN: int = 17
    PUMP_RELAY_PIN_2: int = 27
    SOLENOID_VALVE_PIN_1: int = 23  # Valve 1 (ทำงานกับ Pump 1)
    SOLENOID_VALVE_PIN_2: int = 24  # Valve 2 (ทำงานกับ Pump 2)
    
    # Audio Configuration
    SAMPLE_RATE: int = 48000
    AUDIO_DURATION: int = 5
    N_MELS: int = 128
    
    # Detection Configuration
    CONFIDENCE_THRESHOLD: float = 0.85  # Increased from 0.6
    DETECTION_DELAY_MINUTES: int = 5
    
    # Snoring Response Configuration
    PUMP1_DURATION: int = 50      # Pump 1 duration in seconds
    WAIT_BETWEEN_PUMPS: int = 60 # Wait time between pump 1 and pump 2 (5 minutes)
    PUMP2_DURATION: int = 20      # Pump 2 duration in seconds
    
    # Remote GPIO Configuration (for Render deployment)
    REMOTE_GPIO_ENABLED: bool = os.environ.get('REMOTE_GPIO_ENABLED', 'False').lower() == 'true'
    REMOTE_GPIO_URL: str = os.environ.get('REMOTE_GPIO_URL', 'http://localhost:8080')
    REMOTE_GPIO_API_KEY: str = os.environ.get('REMOTE_GPIO_API_KEY', '')
    REMOTE_GPIO_TIMEOUT: int = 10  # seconds
    
    # System Configuration
    MAX_DETECTION_HISTORY: int = 50
    MAX_ACTIVITY_LOG: int = 200
    MAX_AUDIO_FILES: int = 20
    
    # File Paths
    MODEL_PATH: str = "snore_detection_model.h5"
    MODEL_METADATA_PATH: str = "model_metadata.json"
    LABEL_MAPPING_PATH: str = "label_mapping.json"
    STATIC_FOLDER: str = "static"
    TEMPLATES_FOLDER: str = "templates"

# --- Custom Exceptions ---
class GPIOError(Exception):
    """GPIO related errors"""
    pass

class AudioProcessingError(Exception):
    """Audio processing related errors"""
    pass

class ModelLoadError(Exception):
    """Model loading related errors"""
    pass

# --- Thread-Safe Data Structures ---
class ThreadSafeData:
    def __init__(self):
        self._lock = Lock()
        self._detection_history: List[Dict] = []
        self._activity_log: List[Dict] = []
        self._system_status = {
            'is_recording': False,
            'pump_status': False,
            'auto_detect_enabled': False,
            'detection_delay': 5,
            'model_loaded': False,
            'gpio_ready': False,
            'snoring_response_active': False
        }
    
    def add_detection_record(self, record: Dict):
        with self._lock:
            self._detection_history.append(record)
            if len(self._detection_history) > SystemConfig.MAX_DETECTION_HISTORY:
                self._detection_history.pop(0)
    
    def add_log_entry(self, message: str):
        with self._lock:
            timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            log_entry = {"timestamp": timestamp, "message": message}
            self._activity_log.append(log_entry)
            if len(self._activity_log) > SystemConfig.MAX_ACTIVITY_LOG:
                self._activity_log.pop(0)
            logger.info(f"[{timestamp}] {message}")
    
    def get_detection_history(self) -> List[Dict]:
        with self._lock:
            return self._detection_history.copy()
    
    def get_activity_log(self) -> List[Dict]:
        with self._lock:
            return self._activity_log.copy()
    
    def update_status(self, **kwargs):
        with self._lock:
            self._system_status.update(kwargs)
    
    def get_status(self) -> Dict:
        with self._lock:
            return self._system_status.copy()

# --- GPIO Controller ---
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
    
    def _initialize_gpio(self):
        """Initialize local GPIO (Raspberry Pi)"""
        try:
            import lgpio
            self.h = lgpio.gpiochip_open(0)
            lgpio.gpio_claim_output(self.h, self.config.PUMP_RELAY_PIN, 0)
            lgpio.gpio_claim_output(self.h, self.config.PUMP_RELAY_PIN_2, 0)
            lgpio.gpio_claim_output(self.h, self.config.SOLENOID_VALVE_PIN_1, 0)
            lgpio.gpio_claim_output(self.h, self.config.SOLENOID_VALVE_PIN_2, 0)
            self.gpio_initialized = True
            self.data_store.update_status(gpio_ready=True)
            self.data_store.add_log_entry(
                f"✅ GPIO initialized (Local) - Pins {self.config.PUMP_RELAY_PIN} and {self.config.PUMP_RELAY_PIN_2}"
            )
        except Exception as e:
            self.gpio_initialized = False
            self.data_store.update_status(gpio_ready=False)
            self.data_store.add_log_entry(f"❌ GPIO initialization failed: {str(e)}")
            logger.warning(f"GPIO not available: {str(e)}")
    
    def _initialize_remote_gpio(self):
        """Initialize remote GPIO connection (for Render deployment)"""
        if not REQUESTS_AVAILABLE:
            self.gpio_initialized = False
            self.data_store.update_status(gpio_ready=False)
            self.data_store.add_log_entry("❌ Remote GPIO requires 'requests' library")
            logger.warning("Remote GPIO requires 'requests' library")
            return
        
        try:
            # Test connection to remote GPIO service
            response = requests.get(
                f"{self.config.REMOTE_GPIO_URL}/health",
                timeout=5
            )
            
            if response.status_code == 200:
                health_data = response.json()
                if health_data.get('gpio_initialized', False):
                    self.gpio_initialized = True
                    self.data_store.update_status(gpio_ready=True)
                    self.data_store.add_log_entry(
                        f"✅ Remote GPIO initialized - {self.config.REMOTE_GPIO_URL}"
                    )
                    logger.info(f"Remote GPIO initialized: {self.config.REMOTE_GPIO_URL}")
                else:
                    raise Exception("Remote GPIO service reports GPIO not initialized")
            else:
                raise Exception(f"Remote GPIO health check failed: HTTP {response.status_code}")
        except Exception as e:
            self.gpio_initialized = False
            self.data_store.update_status(gpio_ready=False)
            self.data_store.add_log_entry(f"❌ Remote GPIO initialization failed: {str(e)}")
            logger.warning(f"Remote GPIO not available: {str(e)}")
    
    def control_pump(self, pin_number: int, action: str) -> Dict[str, Any]:
        """Control pump and valve together with thread safety."""
        if not self.gpio_initialized:
            return {"success": False, "message": "GPIO not available"}
        
        if self.remote_mode:
            return self._control_pump_remote(pin_number, action)
        else:
            return self._control_pump_local(pin_number, action)
    
    def _control_pump_local(self, pin_number: int, action: str) -> Dict[str, Any]:
        """Control pump locally (Raspberry Pi)"""
        with self._lock:
            try:
                import lgpio
                
                # Select pump and valve pins
                if pin_number == 1:
                    pump_pin = self.config.PUMP_RELAY_PIN
                    valve_pin = self.config.SOLENOID_VALVE_PIN_1
                elif pin_number == 2:
                    pump_pin = self.config.PUMP_RELAY_PIN_2
                    valve_pin = self.config.SOLENOID_VALVE_PIN_2
                else:
                    return {"success": False, "message": "Invalid pump number (must be 1 or 2)"}
                
                if action.upper() == "ON":
                    # Turn on valve first, then pump
                    lgpio.gpio_write(self.h, valve_pin, 1)
                    time.sleep(0.1)  # Small delay to ensure valve opens
                    lgpio.gpio_write(self.h, pump_pin, 1)
                    
                    status_msg = f"💨 Pump {pin_number} & Valve {pin_number}: ON"
                    if pin_number == 1:
                        self.data_store.update_status(pump_status=True)
                else:
                    # Turn off pump first, then valve
                    lgpio.gpio_write(self.h, pump_pin, 0)
                    time.sleep(0.1)  # Small delay to ensure pump stops
                    lgpio.gpio_write(self.h, valve_pin, 0)
                    
                    status_msg = f"💨 Pump {pin_number} & Valve {pin_number}: OFF"
                    if pin_number == 1:
                        self.data_store.update_status(pump_status=False)
                
                self.data_store.add_log_entry(status_msg)
                return {"success": True, "message": f"Pump {pin_number} and Valve {pin_number} {action.lower()} successful"}
                
            except Exception as e:
                error_msg = f"❌ Pump {pin_number}/Valve {pin_number} control error: {str(e)}"
                self.data_store.add_log_entry(error_msg)
                return {"success": False, "message": str(e)}
    
    def _control_pump_remote(self, pin_number: int, action: str) -> Dict[str, Any]:
        """Control pump via remote API (for Render deployment)"""
        if not REQUESTS_AVAILABLE:
            return {"success": False, "message": "Remote GPIO requires 'requests' library"}
        
        try:
            response = requests.post(
                f"{self.config.REMOTE_GPIO_URL}/api/pump",
                json={"pump": pin_number, "action": action},
                headers={"X-API-Key": self.config.REMOTE_GPIO_API_KEY},
                timeout=self.config.REMOTE_GPIO_TIMEOUT
            )
            
            if response.status_code == 200:
                result = response.json()
                status_msg = f"💨 Pump {pin_number} & Valve {pin_number}: {action} (Remote)"
                self.data_store.add_log_entry(status_msg)
                if pin_number == 1:
                    self.data_store.update_status(pump_status=(action.upper() == "ON"))
                return result
            elif response.status_code == 401:
                error_msg = "❌ Remote GPIO: Unauthorized (check API key)"
                self.data_store.add_log_entry(error_msg)
                return {"success": False, "message": "Unauthorized - check API key"}
            else:
                error_msg = f"❌ Remote GPIO error: HTTP {response.status_code}"
                self.data_store.add_log_entry(error_msg)
                return {"success": False, "message": f"Remote GPIO error: HTTP {response.status_code}"}
        except requests.exceptions.Timeout:
            error_msg = f"❌ Remote GPIO: Connection timeout"
            self.data_store.add_log_entry(error_msg)
            return {"success": False, "message": "Connection timeout"}
        except requests.exceptions.ConnectionError:
            error_msg = f"❌ Remote GPIO: Connection failed"
            self.data_store.add_log_entry(error_msg)
            return {"success": False, "message": "Connection failed - check REMOTE_GPIO_URL"}
        except Exception as e:
            error_msg = f"❌ Remote GPIO error: {str(e)}"
            self.data_store.add_log_entry(error_msg)
            return {"success": False, "message": str(e)}
    
    def control_valve(self, valve_number: int, action: str) -> Dict[str, Any]:
        """Control solenoid valve independently."""
        if not self.gpio_initialized:
            return {"success": False, "message": "GPIO not available"}
        
        if self.remote_mode:
            return self._control_valve_remote(valve_number, action)
        else:
            return self._control_valve_local(valve_number, action)
    
    def _control_valve_local(self, valve_number: int, action: str) -> Dict[str, Any]:
        """Control valve locally (Raspberry Pi)"""
        with self._lock:
            try:
                import lgpio
                
                # Select valve pin
                if valve_number == 1:
                    valve_pin = self.config.SOLENOID_VALVE_PIN_1
                elif valve_number == 2:
                    valve_pin = self.config.SOLENOID_VALVE_PIN_2
                else:
                    return {"success": False, "message": "Invalid valve number (must be 1 or 2)"}
                
                if action.upper() == "ON":
                    lgpio.gpio_write(self.h, valve_pin, 1)
                    status_msg = f"🔧 Valve {valve_number}: ON"
                else:
                    lgpio.gpio_write(self.h, valve_pin, 0)
                    status_msg = f"🔧 Valve {valve_number}: OFF"
                
                self.data_store.add_log_entry(status_msg)
                return {"success": True, "message": f"Valve {valve_number} {action.lower()} successful"}
                
            except Exception as e:
                error_msg = f"❌ Valve {valve_number} control error: {str(e)}"
                self.data_store.add_log_entry(error_msg)
                return {"success": False, "message": str(e)}
    
    def _control_valve_remote(self, valve_number: int, action: str) -> Dict[str, Any]:
        """Control valve via remote API (for Render deployment)"""
        if not REQUESTS_AVAILABLE:
            return {"success": False, "message": "Remote GPIO requires 'requests' library"}
        
        try:
            response = requests.post(
                f"{self.config.REMOTE_GPIO_URL}/api/valve",
                json={"valve": valve_number, "action": action},
                headers={"X-API-Key": self.config.REMOTE_GPIO_API_KEY},
                timeout=self.config.REMOTE_GPIO_TIMEOUT
            )
            
            if response.status_code == 200:
                result = response.json()
                status_msg = f"🔧 Valve {valve_number}: {action} (Remote)"
                self.data_store.add_log_entry(status_msg)
                return result
            elif response.status_code == 401:
                return {"success": False, "message": "Unauthorized - check API key"}
            else:
                return {"success": False, "message": f"Remote GPIO error: HTTP {response.status_code}"}
        except Exception as e:
            error_msg = f"❌ Remote GPIO error: {str(e)}"
            self.data_store.add_log_entry(error_msg)
            return {"success": False, "message": str(e)}
    
    def cleanup(self):
        """Clean up GPIO resources."""
        if self.gpio_initialized and self.h is not None:
            try:
                import lgpio
                
                # Turn off all pumps and valves
                lgpio.gpio_write(self.h, self.config.PUMP_RELAY_PIN, 0)
                lgpio.gpio_write(self.h, self.config.PUMP_RELAY_PIN_2, 0)
                lgpio.gpio_write(self.h, self.config.SOLENOID_VALVE_PIN_1, 0)
                lgpio.gpio_write(self.h, self.config.SOLENOID_VALVE_PIN_2, 0)
                
                # Free GPIO pins
                lgpio.gpio_free(self.h, self.config.PUMP_RELAY_PIN)
                lgpio.gpio_free(self.h, self.config.PUMP_RELAY_PIN_2)
                lgpio.gpio_free(self.h, self.config.SOLENOID_VALVE_PIN_1)
                lgpio.gpio_free(self.h, self.config.SOLENOID_VALVE_PIN_2)
                
                lgpio.gpiochip_close(self.h)
                self.data_store.add_log_entry("✅ GPIO cleanup completed - All pumps and valves turned off")
            except Exception as e:
                logger.error(f"GPIO cleanup error: {str(e)}")

# --- Audio Processor ---
class AudioProcessor:
    def __init__(self, config: SystemConfig, data_store: ThreadSafeData):
        self.config = config
        self.data_store = data_store
        self._recording_lock = Lock()
    
    def record_audio(self, duration: int = None) -> Optional[str]:
        """Record audio with improved error handling."""
        if duration is None:
            duration = self.config.AUDIO_DURATION
        
        # Check if sounddevice is available (not available on cloud platforms)
        if not SOUNDDEVICE_AVAILABLE:
            error_msg = "❌ Server-side audio recording not available on this platform. Please use client-side recording."
            self.data_store.add_log_entry(error_msg)
            logger.error(error_msg)
            raise AudioProcessingError("Server-side recording requires sounddevice/PortAudio, which is not available on cloud platforms. Use client-side recording instead.")
        
        with self._recording_lock:
            try:
                self.data_store.update_status(is_recording=True)
                self.data_store.add_log_entry(f"🎤 Recording audio ({duration}s @ {self.config.SAMPLE_RATE}Hz)")
                
                # Generate unique filename
                timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"recording_{timestamp}.wav"
                filepath = os.path.join(self.config.STATIC_FOLDER, filename)
                
                # Ensure directory exists
                os.makedirs(self.config.STATIC_FOLDER, exist_ok=True)
                
                # Record audio
                frames = []
                
                def callback(indata, frame_count, time_info, status):
                    if status:
                        logger.warning(f"Audio callback status: {status}")
                    frames.append(indata.copy())
                
                with sd.InputStream(
                    samplerate=self.config.SAMPLE_RATE,
                    channels=1,
                    callback=callback,
                    dtype='float32',
                    blocksize=1024
                ):
                    time.sleep(duration)
                
                # Save recording
                if frames:
                    recording = np.concatenate(frames, axis=0)
                    # Normalize audio
                    recording = recording / np.max(np.abs(recording))
                    sf.write(filepath, recording, self.config.SAMPLE_RATE)
                    self.data_store.add_log_entry(f"✅ Audio saved: {filename} (size: {len(recording)} samples)")
                    logger.info(f"Audio file saved: {filepath}, shape: {recording.shape}")
                    return filepath
                else:
                    raise AudioProcessingError("No audio data recorded")
                    
            except Exception as e:
                error_msg = f"❌ Recording failed: {str(e)}"
                self.data_store.add_log_entry(error_msg)
                logger.error(error_msg)
                raise AudioProcessingError(error_msg)
            finally:
                self.data_store.update_status(is_recording=False)
    
    def save_uploaded_audio(self, audio_file) -> Optional[str]:
        """Save uploaded audio file from client."""
        try:
            # Generate unique filename
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"recording_{timestamp}.wav"
            filepath = os.path.join(self.config.STATIC_FOLDER, filename)
            
            # Ensure directory exists
            os.makedirs(self.config.STATIC_FOLDER, exist_ok=True)
            
            # Save uploaded file
            audio_file.save(filepath)
            
            # Verify file was saved
            if os.path.exists(filepath) and os.path.getsize(filepath) > 0:
                file_size = os.path.getsize(filepath)
                self.data_store.add_log_entry(f"✅ Audio uploaded and saved: {filename} ({file_size} bytes)")
                logger.info(f"Audio file saved: {filepath}, size: {file_size} bytes")
                return filepath
            else:
                raise AudioProcessingError("Failed to save uploaded audio file")
                
        except Exception as e:
            error_msg = f"❌ Failed to save uploaded audio: {str(e)}"
            self.data_store.add_log_entry(error_msg)
            logger.error(error_msg)
            raise AudioProcessingError(error_msg)
    
    def cleanup_old_files(self):
        """Clean up old audio files to prevent disk space issues."""
        try:
            if not os.path.exists(self.config.STATIC_FOLDER):
                return
                
            audio_files = []
            for file in os.listdir(self.config.STATIC_FOLDER):
                if file.startswith('recording_') and file.endswith('.wav'):
                    filepath = os.path.join(self.config.STATIC_FOLDER, file)
                    mtime = os.path.getmtime(filepath)
                    audio_files.append((filepath, mtime))
            
            # Sort by modification time (oldest first)
            audio_files.sort(key=lambda x: x[1])
            
            # Remove excess files
            if len(audio_files) > self.config.MAX_AUDIO_FILES:
                files_to_remove = audio_files[:-self.config.MAX_AUDIO_FILES]
                for filepath, _ in files_to_remove:
                    try:
                        os.remove(filepath)
                        self.data_store.add_log_entry(f"🗑️ Cleaned up: {os.path.basename(filepath)}")
                    except Exception as e:
                        logger.warning(f"Failed to remove {filepath}: {str(e)}")
                        
        except Exception as e:
            logger.warning(f"Cleanup failed: {str(e)}")

# --- AI Model Handler ---
class ModelHandler:
    def __init__(self, config: SystemConfig, data_store: ThreadSafeData):
        self.config = config
        self.data_store = data_store
        self.model = None
        self.model_metadata = None
        self.label_mapping = None
        self.model_type = None  # 'legacy' or 'improved'
        self._prediction_lock = Lock()
        
        self._load_model()
    
    def _load_model(self):
        """Load AI model with automatic compatibility detection"""
        try:
            # Try loading with custom objects to handle deprecated batch_shape
            # First, try standard loading
            try:
                self.model = load_model(self.config.MODEL_PATH, compile=False)
            except Exception as e:
                # If loading fails due to batch_shape issue, try workarounds
                if 'batch_shape' in str(e) or 'Unrecognized keyword arguments' in str(e):
                    logger.warning(f"Standard model loading failed: {e}. Trying workaround for deprecated batch_shape...")
                    
                    # Try loading with a custom InputLayer that handles batch_shape
                    class CustomInputLayer(tf.keras.layers.InputLayer):
                        """Custom InputLayer that handles deprecated batch_shape"""
                        @classmethod
                        def from_config(cls, config):
                            # Remove batch_shape from config if present
                            config_copy = config.copy()
                            if 'batch_shape' in config_copy:
                                # Convert batch_shape to input_shape
                                batch_shape = config_copy.pop('batch_shape')
                                if batch_shape and len(batch_shape) > 1:
                                    config_copy['input_shape'] = batch_shape[1:]
                            return super().from_config(config_copy)
                    
                    # Register CustomInputLayer globally
                    try:
                        tf.keras.utils.register_keras_serializable('custom', 'InputLayer')(CustomInputLayer)
                    except:
                        pass  # May already be registered
                    
                    try:
                        # Try with custom_objects to handle InputLayer
                        custom_objects = {
                            'InputLayer': CustomInputLayer
                        }
                        self.model = tf.keras.models.load_model(
                            self.config.MODEL_PATH, 
                            compile=False,
                            custom_objects=custom_objects
                        )
                    except Exception as e2:
                        logger.warning(f"Custom InputLayer loading failed: {e2}. Trying direct HDF5 load...")
                        # Last resort: try to manually fix the model file config
                        try:
                            import h5py
                            import json
                            
                            # Read the model config and fix batch_shape
                            with h5py.File(self.config.MODEL_PATH, 'r') as f:
                                # Get model_config attribute
                                if 'model_config' not in f.attrs:
                                    raise ValueError("model_config not found in HDF5 file")
                                
                                model_config_str = f.attrs.get('model_config')
                                if model_config_str is None:
                                    raise ValueError("model_config is None in HDF5 file")
                                
                                # Handle both bytes and string
                                if isinstance(model_config_str, bytes):
                                    model_config = json.loads(model_config_str.decode('utf-8'))
                                elif isinstance(model_config_str, str):
                                    model_config = json.loads(model_config_str)
                                else:
                                    # Try to convert to string first
                                    model_config = json.loads(str(model_config_str))
                                
                                if not isinstance(model_config, dict):
                                    raise ValueError(f"model_config is not a dict: {type(model_config)}")
                                
                                # Recursively fix batch_shape and DTypePolicy in config
                                def fix_config(obj, path=""):
                                    """Fix deprecated parameters in model config"""
                                    if isinstance(obj, dict):
                                        # Fix batch_shape in InputLayer
                                        if 'batch_shape' in obj:
                                            if obj.get('class_name') == 'InputLayer':
                                                # Convert batch_shape to input_shape
                                                batch_shape = obj.pop('batch_shape')
                                                if batch_shape and len(batch_shape) > 1:
                                                    input_shape = batch_shape[1:]  # Remove batch dimension
                                                    obj['input_shape'] = input_shape
                                                    logger.debug(f"Fixed batch_shape at {path}: {batch_shape} -> {input_shape}")
                                            else:
                                                # Remove batch_shape from other layers too
                                                obj.pop('batch_shape', None)
                                        
                                        # Fix build_input_shape - CRITICAL for model loading
                                        if 'build_input_shape' in obj:
                                            build_input_shape = obj['build_input_shape']
                                            if isinstance(build_input_shape, list) and len(build_input_shape) > 0:
                                                if build_input_shape[0] is None:
                                                    # Try to get input_shape from first layer
                                                    logger.debug(f"Fixing build_input_shape at {path}: {build_input_shape}")
                                                    # If we have layers, get input_shape from first InputLayer
                                                    if 'layers' in obj and isinstance(obj['layers'], list):
                                                        for layer in obj['layers']:
                                                            if isinstance(layer, dict):
                                                                layer_config = layer.get('config', {})
                                                                if layer_config.get('class_name') == 'InputLayer':
                                                                    input_shape = layer_config.get('input_shape')
                                                                    if input_shape:
                                                                        # Reconstruct build_input_shape with batch dimension
                                                                        build_input_shape[0] = [None] + list(input_shape) if isinstance(input_shape, (list, tuple)) else [None, input_shape]
                                                                        logger.debug(f"Fixed build_input_shape from InputLayer: {build_input_shape}")
                                                                        break
                                                    # If still None, set to a default
                                                    if build_input_shape[0] is None:
                                                        logger.warning(f"Could not determine build_input_shape, using default")
                                                        build_input_shape[0] = [None, 216, 128]  # Default based on error message
                                        
                                        # Fix DTypePolicy - convert to string (in ALL layers and nested configs)
                                        # This must be done BEFORE fixing nested configs to catch all instances
                                        if 'dtype' in obj and obj['dtype'] is not None:
                                            dtype_val = obj['dtype']
                                            if isinstance(dtype_val, dict):
                                                dtype_obj = dtype_val
                                                class_name = dtype_obj.get('class_name') if dtype_obj else None
                                                if class_name == 'DTypePolicy':
                                                    # Extract the actual dtype name
                                                    dtype_config = dtype_obj.get('config') if dtype_obj else None
                                                    if isinstance(dtype_config, dict):
                                                        dtype_name = dtype_config.get('name', 'float32')
                                                    else:
                                                        dtype_name = 'float32'
                                                    obj['dtype'] = dtype_name
                                                    logger.debug(f"Fixed DTypePolicy at {path} -> {dtype_name}")
                                        
                                        # Fix nested config objects (CRITICAL - layers have config inside)
                                        # Must fix config AFTER fixing dtype at this level
                                        if 'config' in obj and isinstance(obj['config'], dict):
                                            # Fix DTypePolicy in config first
                                            config = obj['config']
                                            if 'dtype' in config and config['dtype'] is not None:
                                                dtype_val = config['dtype']
                                                if isinstance(dtype_val, dict):
                                                    dtype_obj = dtype_val
                                                    if dtype_obj.get('class_name') == 'DTypePolicy':
                                                        dtype_config = dtype_obj.get('config', {})
                                                        if isinstance(dtype_config, dict):
                                                            dtype_name = dtype_config.get('name', 'float32')
                                                        else:
                                                            dtype_name = 'float32'
                                                        config['dtype'] = dtype_name
                                                        logger.debug(f"Fixed DTypePolicy in config at {path} -> {dtype_name}")
                                            # Then recursively fix nested configs
                                            fix_config(obj['config'], f"{path}.config")
                                        
                                        # Recursively fix all nested objects
                                        for k, v in list(obj.items()):
                                            if isinstance(v, (dict, list)):
                                                fix_config(v, f"{path}.{k}" if path else k)
                                    elif isinstance(obj, list):
                                        for i, item in enumerate(obj):
                                            fix_config(item, f"{path}[{i}]")
                                
                                logger.info("Fixing model config for compatibility...")
                                
                                # First pass: Fix batch_shape to get input_shape
                                fix_config(model_config)
                                
                                # Second pass: Fix build_input_shape and ensure InputLayer has proper input_shape
                                input_shape_found = None
                                
                                def find_input_shape(obj, path=""):
                                    """Find input_shape from InputLayer - check both config and top level"""
                                    nonlocal input_shape_found
                                    if isinstance(obj, dict):
                                        if obj.get('class_name') == 'InputLayer':
                                            # Check in config first (most common location)
                                            if 'config' in obj and isinstance(obj['config'], dict):
                                                config = obj['config']
                                                # Check for input_shape
                                                input_shape = config.get('input_shape')
                                                if input_shape:
                                                    input_shape_found = input_shape
                                                    logger.info(f"Found input_shape from InputLayer config at {path}: {input_shape}")
                                                # Also check for batch_shape (should have been converted but check anyway)
                                                elif 'batch_shape' in config:
                                                    batch_shape = config.get('batch_shape')
                                                    if batch_shape and len(batch_shape) > 1:
                                                        input_shape_found = list(batch_shape[1:])
                                                        logger.info(f"Found input_shape from batch_shape at {path}: {input_shape_found}")
                                            # Also check at top level
                                            if input_shape_found is None:
                                                input_shape = obj.get('input_shape')
                                                if input_shape:
                                                    input_shape_found = input_shape
                                                    logger.info(f"Found input_shape from InputLayer at {path}: {input_shape}")
                                                # Check for batch_shape at top level
                                                elif 'batch_shape' in obj:
                                                    batch_shape = obj.get('batch_shape')
                                                    if batch_shape and len(batch_shape) > 1:
                                                        input_shape_found = list(batch_shape[1:])
                                                        logger.info(f"Found input_shape from batch_shape at {path}: {input_shape_found}")
                                        # Check in config
                                        if 'config' in obj:
                                            find_input_shape(obj['config'], f"{path}.config" if path else "config")
                                        # Check in layers
                                        if 'layers' in obj:
                                            find_input_shape(obj['layers'], f"{path}.layers" if path else "layers")
                                    elif isinstance(obj, list):
                                        for i, item in enumerate(obj):
                                            find_input_shape(item, f"{path}[{i}]" if path else f"[{i}]")
                                
                                # Find input_shape first (after first pass has converted batch_shape)
                                logger.info("Searching for input_shape in model config...")
                                find_input_shape(model_config)
                                
                                # If not found, use default
                                if input_shape_found is None:
                                    input_shape_found = [216, 128]  # Default from error message
                                    logger.warning(f"Input shape not found, using default: {input_shape_found}")
                                else:
                                    # Ensure it's a list
                                    if not isinstance(input_shape_found, list):
                                        input_shape_found = [input_shape_found]
                                    logger.info(f"Using input_shape: {input_shape_found}")
                                
                                def fix_build_input_shape(obj):
                                    """Fix build_input_shape after input_shape is fixed"""
                                    if isinstance(obj, dict):
                                        if 'build_input_shape' in obj:
                                            build_input_shape = obj['build_input_shape']
                                            if isinstance(build_input_shape, list):
                                                if len(build_input_shape) == 0:
                                                    build_input_shape.append([None] + list(input_shape_found))
                                                    logger.info(f"Added build_input_shape: {build_input_shape[0]}")
                                                else:
                                                    # Always rebuild to ensure correct structure
                                                    # This handles all cases: None, empty list, wrong structure, etc.
                                                    try:
                                                        # Try to access to see if it's valid
                                                        test = build_input_shape[0]
                                                        if test is None or (isinstance(test, list) and (len(test) == 0 or test[0] is None and len(test) != len(input_shape_found) + 1)):
                                                            # Invalid structure, rebuild
                                                            build_input_shape[0] = [None] + list(input_shape_found)
                                                            logger.info(f"Fixed build_input_shape: {build_input_shape[0]}")
                                                        elif isinstance(test, list) and len(test) > 0:
                                                            # Check if structure is correct
                                                            expected = [None] + list(input_shape_found)
                                                            if len(test) != len(expected) or (test[0] is None and test[1:] != list(input_shape_found)):
                                                                build_input_shape[0] = expected
                                                                logger.info(f"Rebuilt build_input_shape: {build_input_shape[0]}")
                                                    except (TypeError, IndexError):
                                                        # Can't access, rebuild
                                                        build_input_shape[0] = [None] + list(input_shape_found)
                                                        logger.info(f"Fixed unaccessible build_input_shape: {build_input_shape[0]}")
                                        
                                        # Also ensure InputLayer has input_shape in config
                                        if obj.get('class_name') == 'InputLayer':
                                            # Check if input_shape is in config
                                            if 'config' in obj and isinstance(obj['config'], dict):
                                                if 'input_shape' not in obj['config']:
                                                    obj['config']['input_shape'] = input_shape_found
                                                    logger.info(f"Added input_shape to InputLayer config: {input_shape_found}")
                                            elif 'input_shape' not in obj:
                                                obj['input_shape'] = input_shape_found
                                                logger.info(f"Added input_shape to InputLayer: {input_shape_found}")
                                        
                                        # Recursively check nested objects
                                        for v in obj.values():
                                            if isinstance(v, (dict, list)):
                                                fix_build_input_shape(v)
                                    elif isinstance(obj, list):
                                        for item in obj:
                                            fix_build_input_shape(item)
                                
                                # Second pass to fix build_input_shape
                                fix_build_input_shape(model_config)
                                
                                logger.info("Model config fixed successfully")
                                
                                # Validate model_config before proceeding
                                if not isinstance(model_config, dict):
                                    raise ValueError(f"model_config is not a dict after fixing: {type(model_config)}")
                                
                                # Check if it's the expected Keras model config structure
                                if 'config' not in model_config and 'layers' not in model_config:
                                    logger.warning(f"model_config keys: {list(model_config.keys())}")
                                    # Try to find the actual structure
                                    if 'model_config' in model_config:
                                        logger.info("Found nested 'model_config', extracting...")
                                        model_config = model_config['model_config']
                                    else:
                                        raise ValueError("model_config missing expected structure (no 'config' or 'layers' key)")
                                
                                # Try loading with fixed config using CustomInputLayer
                                try:
                                    logger.info("Attempting to load model from fixed JSON...")
                                    
                                    # Validate JSON serialization
                                    try:
                                        model_json = json.dumps(model_config)
                                        logger.info(f"Model JSON serialized successfully, length: {len(model_json)} characters")
                                    except Exception as json_error:
                                        logger.error(f"JSON serialization failed: {json_error}")
                                        raise ValueError(f"Cannot serialize model config to JSON: {json_error}")
                                    
                                    self.model = tf.keras.models.model_from_json(
                                        model_json,
                                        custom_objects={'InputLayer': CustomInputLayer}
                                    )
                                    logger.info("Model architecture loaded successfully")
                                    
                                    # Load weights - try different methods
                                    logger.info("Loading model weights...")
                                    try:
                                        # Method 1: Direct load
                                        self.model.load_weights(self.config.MODEL_PATH)
                                        logger.info("Model weights loaded successfully!")
                                    except Exception as weights_error:
                                        logger.warning(f"Direct weight loading failed: {weights_error}")
                                        # Method 2: Try loading from HDF5 group
                                        try:
                                            import h5py
                                            with h5py.File(self.config.MODEL_PATH, 'r') as f:
                                                if 'model_weights' in f:
                                                    logger.info("Loading weights from 'model_weights' group...")
                                                    self.model.load_weights(self.config.MODEL_PATH, by_name=False)
                                                    logger.info("Model weights loaded from group successfully!")
                                                else:
                                                    logger.warning("'model_weights' group not found, trying by_name=True...")
                                                    self.model.load_weights(self.config.MODEL_PATH, by_name=True)
                                                    logger.info("Model weights loaded by name successfully!")
                                        except Exception as weights_error2:
                                            logger.error(f"All weight loading methods failed: {weights_error2}")
                                            raise weights_error2
                                    
                                except Exception as load_error:
                                    logger.error(f"Error loading model from fixed config: {load_error}")
                                    logger.error(f"Error type: {type(load_error).__name__}")
                                    import traceback
                                    logger.error(f"Traceback: {traceback.format_exc()}")
                                    # Check if it's a NoneType error
                                    if "'NoneType' object is not subscriptable" in str(load_error):
                                        logger.error("NoneType error detected - this might be due to incomplete config fix")
                                        # Try to find what's None in the config
                                        def find_none_values(obj, path=""):
                                            if isinstance(obj, dict):
                                                for k, v in obj.items():
                                                    if v is None:
                                                        logger.warning(f"Found None value at {path}.{k}")
                                                    elif isinstance(v, (dict, list)):
                                                        find_none_values(v, f"{path}.{k}" if path else k)
                                            elif isinstance(obj, list):
                                                for i, item in enumerate(obj):
                                                    if item is None:
                                                        logger.warning(f"Found None value at {path}[{i}]")
                                                    elif isinstance(item, (dict, list)):
                                                        find_none_values(item, f"{path}[{i}]")
                                        logger.info("Scanning config for None values...")
                                        find_none_values(model_config)
                                    raise load_error
                        except Exception as e3:
                            logger.error(f"All model loading methods failed. Last error: {e3}")
                            # Set model to None so app can continue
                            self.model = None
                            # Don't raise - allow app to continue without model
                            logger.warning("Model loading failed - app will continue without model")
                else:
                    # For other errors, still try to set model to None and continue
                    logger.error(f"Model loading failed with unexpected error: {e}")
                    self.model = None
            
            # Check if model was successfully loaded
            if self.model is None:
                self.model_type = 'unknown'
                self.data_store.update_status(model_loaded=False)
                self.data_store.add_log_entry("⚠️ Model not loaded - prediction features disabled")
                logger.warning("Model is None - prediction features will be disabled")
                return
            
            # Detect model type based on architecture
            self.model_type = self._detect_model_type()
            
            # Recompile model
            try:
                self.model.compile(
                    optimizer='adam',
                    loss='binary_crossentropy',
                    metrics=['accuracy'],
                    run_eagerly=False
                )
            except Exception as e:
                logger.warning(f"Model compilation failed: {e}. Model may still work for inference.")
            
            # Load metadata if available
            if os.path.exists(self.config.MODEL_METADATA_PATH):
                with open(self.config.MODEL_METADATA_PATH, 'r') as f:
                    self.model_metadata = json.load(f)
                    logger.info(f"Model metadata loaded: {self.model_metadata}")
            
            # Load label mapping if available
            if os.path.exists(self.config.LABEL_MAPPING_PATH):
                with open(self.config.LABEL_MAPPING_PATH, 'r') as f:
                    self.label_mapping = json.load(f)
                    logger.info(f"Label mapping loaded: {self.label_mapping}")
            
            self.data_store.update_status(model_loaded=True)
            self.data_store.add_log_entry(f"✅ AI model loaded successfully (Type: {self.model_type})")
            logger.info(f"Model input shape: {self.model.input_shape}")
            
        except Exception as e:
            self.data_store.update_status(model_loaded=False)
            error_msg = f"❌ Model loading failed: {str(e)}"
            self.data_store.add_log_entry(error_msg)
            logger.error(error_msg)
            # Don't raise error - allow app to start without model (for testing/debugging)
            # raise ModelLoadError(error_msg)
            logger.warning("Continuing without model - some features will be disabled")
    
    def _detect_model_type(self):
        """Detect whether this is a legacy or improved model"""
        try:
            if self.model is None:
                return 'unknown'
            
            input_shape = self.model.input_shape
            logger.info(f"Model input shape: {input_shape}")
            
            if len(input_shape) == 2:  # (batch_size, features)
                if input_shape[1] == 40:  # Legacy MFCC model
                    return 'legacy'
                else:
                    return 'unknown'
            elif len(input_shape) == 3:  # (batch_size, time_steps, features)
                return 'improved'
            else:
                return 'legacy'  # Default to legacy for safety
                
        except Exception as e:
            logger.warning(f"Could not detect model type: {e}")
            return 'legacy'
    
    def extract_features_legacy(self, audio_path: str) -> Optional[np.ndarray]:
        """Extract legacy MFCC features (40 features)"""
        try:
            logger.info(f"Extracting legacy features from: {audio_path}")
            
            # Load and preprocess audio
            audio, sr = librosa.load(audio_path, sr=self.config.SAMPLE_RATE)
            logger.info(f"Loaded audio: shape={audio.shape}, sr={sr}")
            
            # Check if audio is not empty
            if len(audio) == 0:
                raise AudioProcessingError("Empty audio file")
            
            # Trim silence
            audio, _ = librosa.effects.trim(audio, top_db=30)
            logger.info(f"After trim: shape={audio.shape}")
            
            # Normalize length
            target_length = self.config.SAMPLE_RATE * self.config.AUDIO_DURATION
            if len(audio) > target_length:
                audio = audio[:target_length]
            else:
                audio = np.pad(audio, (0, target_length - len(audio)), 'constant')
            
            logger.info(f"After normalize length: shape={audio.shape}")
            
            # Normalize amplitude
            if np.max(np.abs(audio)) > 0:
                audio = librosa.util.normalize(audio)
            
            # Extract MFCC features (legacy method)
            mfccs = librosa.feature.mfcc(y=audio, sr=sr, n_mfcc=40)
            logger.info(f"MFCC shape: {mfccs.shape}")
            
            # Take mean across time (legacy method)
            mfccs_processed = np.mean(mfccs.T, axis=0)
            logger.info(f"Processed MFCC shape: {mfccs_processed.shape}")
            
            return mfccs_processed
            
        except Exception as e:
            error_msg = f"Legacy feature extraction failed: {str(e)}"
            self.data_store.add_log_entry(error_msg)
            logger.error(error_msg)
            raise AudioProcessingError(error_msg)
    
    def extract_features_improved(self, audio_path: str) -> Optional[np.ndarray]:
        """Extract improved mel spectrogram features"""
        try:
            logger.info(f"Extracting improved features from: {audio_path}")
            
            # Load and preprocess audio
            audio, sr = librosa.load(audio_path, sr=self.config.SAMPLE_RATE)
            logger.info(f"Loaded audio: shape={audio.shape}, sr={sr}")
            
            # Check if audio is not empty
            if len(audio) == 0:
                raise AudioProcessingError("Empty audio file")
            
            # Trim silence
            audio, _ = librosa.effects.trim(audio, top_db=20)
            logger.info(f"After trim: shape={audio.shape}")
            
            # Normalize length
            target_length = self.config.SAMPLE_RATE * self.config.AUDIO_DURATION
            if len(audio) > target_length:
                audio = audio[:target_length]
            else:
                audio = np.pad(audio, (0, target_length - len(audio)), 'constant')
            
            logger.info(f"After normalize length: shape={audio.shape}")
            
            # Normalize amplitude
            if np.max(np.abs(audio)) > 0:
                audio = librosa.util.normalize(audio)
            
            # Extract mel spectrogram
            mel_spec = librosa.feature.melspectrogram(
                y=audio,
                sr=sr,
                n_mels=self.config.N_MELS,
                fmax=8000
            )
            
            # Convert to dB and normalize
            mel_spec_db = librosa.power_to_db(mel_spec, ref=np.max)
            mel_spec_db = (mel_spec_db - mel_spec_db.mean()) / (mel_spec_db.std() + 1e-6)
            
            logger.info(f"Mel spectrogram shape: {mel_spec_db.T.shape}")
            
            return mel_spec_db.T  # Shape: (time_steps, n_mels)
            
        except Exception as e:
            error_msg = f"Improved feature extraction failed: {str(e)}"
            self.data_store.add_log_entry(error_msg)
            logger.error(error_msg)
            raise AudioProcessingError(error_msg)

    def extract_features(self, audio_path: str) -> Optional[np.ndarray]:
        """Extract features based on model type"""
        if self.model_type == 'legacy':
            return self.extract_features_legacy(audio_path)
        elif self.model_type == 'improved':
            return self.extract_features_improved(audio_path)
        else:
            # Fallback to legacy
            logger.warning("Unknown model type, falling back to legacy features")
            return self.extract_features_legacy(audio_path)

    def predict(self, audio_path: str) -> Optional[Dict[str, Any]]:
        """Predict audio class with model-specific handling"""
        if self.model is None:
            logger.error("Model is not loaded")
            return None

        with self._prediction_lock:
            try:
                logger.info(f"Starting prediction for: {audio_path}")
                
                # Verify file exists
                if not os.path.exists(audio_path):
                    raise AudioProcessingError(f"Audio file not found: {audio_path}")
                
                # Extract features based on model type
                features = self.extract_features(audio_path)
                if features is None:
                    logger.error("Feature extraction returned None")
                    return None

                logger.info(f"Features extracted: shape={features.shape}, type={type(features)}")
                
                # Prepare features for prediction
                if self.model_type == 'legacy':
                    # Legacy model expects (batch_size, 40)
                    features = np.expand_dims(features, axis=0)
                elif self.model_type == 'improved':
                    # Improved model expects (batch_size, time_steps, n_mels)
                    features = np.expand_dims(features, axis=0)

                logger.info(f"Features prepared for prediction: shape={features.shape}")

                # Predict
                with tf.device('/CPU:0'):
                    prediction = self.model.predict(features, verbose=0)[0]
                    logger.info(f"Raw prediction: {prediction}")

                # Process prediction
                if len(prediction) == 1:
                    # Binary classification
                    confidence = float(prediction[0])
                    class_id = 1 if confidence > 0.5 else 0
                    confidence_percent = confidence * 100 if class_id == 1 else (1 - confidence) * 100
                else:
                    # Multi-class classification
                    class_id = np.argmax(prediction)
                    confidence_percent = float(prediction[class_id]) * 100

                logger.info(f"Class ID: {class_id}, Confidence: {confidence_percent}%")

                # Map to class name
                if self.label_mapping and 'class_to_index' in self.label_mapping:
                    index_to_class = {v: k for k, v in self.label_mapping['class_to_index'].items()}
                    class_name = index_to_class.get(class_id, "Unknown")
                else:
                    class_name = "กรน" if class_id == 1 else "ไม่กรน"

                result = {
                    "class_id": int(class_id),
                    "class_name": class_name,
                    "confidence": float(confidence_percent),
                    "model_type": self.model_type
                }

                logger.info(f"Final prediction result: {result}")
                return result

            except Exception as e:
                error_msg = f"Prediction failed: {str(e)}"
                self.data_store.add_log_entry(error_msg)
                logger.error(error_msg)
                return None
    def cleanup():
        db = DatabaseManager()
        while True:
            try:
                time.sleep(3600)
                db.cleanup_expired_sessions()
                logger.info("Expired sessions cleaned up")
            except Exception as e:
                logger.error(f"Session cleanup error: {str(e)}")

# --- System Controller ---
class SnoreDetectionSystem:
    def __init__(self):
        self.config = SystemConfig()
        self.data_store = ThreadSafeData()
        
        # Initialize components (with error handling)
        try:
            self.gpio_controller = GPIOController(self.config, self.data_store)
        except Exception as e:
            logger.warning(f"GPIO controller initialization failed: {e}")
            self.gpio_controller = None
        
        try:
            self.audio_processor = AudioProcessor(self.config, self.data_store)
        except Exception as e:
            logger.warning(f"Audio processor initialization failed: {e}")
            self.audio_processor = None
        
        try:
            self.model_handler = ModelHandler(self.config, self.data_store)
        except Exception as e:
            logger.warning(f"Model handler initialization failed: {e}")
            self.model_handler = None
        
        # Auto detection
        self._auto_detection_thread = None
        self._auto_detection_stop_event = Event()
        
        # Setup signal handlers
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
        
        # Register cleanup
        atexit.register(self.cleanup)
    
    def _signal_handler(self, signum, frame):
        """Handle system signals for graceful shutdown."""
        logger.info(f"Received signal {signum}, shutting down...")
        self.cleanup()
        sys.exit(0)
    
    def _execute_snoring_response(self):
        """Execute the snoring response sequence in a separate thread."""
        try:
            self.data_store.update_status(snoring_response_active=True)
            self.data_store.add_log_entry("🔄 Starting snoring response sequence")
            
            # Step 1: Activate Pump 1 & Valve 1 for 40 seconds
            self.data_store.add_log_entry(f"💨 Step 1: Activating Pump 1 & Valve 1 for {self.config.PUMP1_DURATION} seconds")
            pump1_result = self.gpio_controller.control_pump(1, "ON")
            
            if pump1_result["success"]:
                # Wait for the duration
                for i in range(self.config.PUMP1_DURATION):
                    if self._auto_detection_stop_event.is_set():
                        self.data_store.add_log_entry("⏹️ Snoring response interrupted during pump 1 operation")
                        self.gpio_controller.control_pump(1, "OFF")
                        return
                    time.sleep(1)
                
                # Turn off pump 1
                self.gpio_controller.control_pump(1, "OFF")
                self.data_store.add_log_entry("✅ Step 1 completed: Pump 1 & Valve 1 turned off")
            else:
                self.data_store.add_log_entry(f"❌ Step 1 failed: {pump1_result['message']}")
                return
            
            # Step 2: Wait 300 seconds (5 minutes)
            self.data_store.add_log_entry(f"⏳ Step 2: Waiting {self.config.WAIT_BETWEEN_PUMPS} seconds (1 minutes) before next action")
            
            # Wait with progress updates and interruption capability
            for i in range(self.config.WAIT_BETWEEN_PUMPS):
                if self._auto_detection_stop_event.is_set():
                    self.data_store.add_log_entry("⏹️ Snoring response interrupted during waiting period")
                    return
                time.sleep(1)
                
                # Log progress every 60 seconds
                if (i + 1) % 60 == 0:
                    remaining_minutes = (self.config.WAIT_BETWEEN_PUMPS - i - 1) // 60
                    self.data_store.add_log_entry(f"⏰ Waiting... {remaining_minutes} minutes remaining")
            
            # Step 3: Activate Pump 2 & Valve 2 for 30 seconds
            self.data_store.add_log_entry(f"💨 Step 3: Activating Pump 2 & Valve 2 for {self.config.PUMP2_DURATION} seconds")
            pump2_result = self.gpio_controller.control_pump(2, "ON")
            
            if pump2_result["success"]:
                # Wait for the duration
                for i in range(self.config.PUMP2_DURATION):
                    if self._auto_detection_stop_event.is_set():
                        self.data_store.add_log_entry("⏹️ Snoring response interrupted during pump 2 operation")
                        self.gpio_controller.control_pump(2, "OFF")
                        return
                    time.sleep(1)
                
                # Turn off pump 2
                self.gpio_controller.control_pump(2, "OFF")
                self.data_store.add_log_entry("✅ Step 3 completed: Pump 2 & Valve 2 turned off")
            else:
                self.data_store.add_log_entry(f"❌ Step 3 failed: {pump2_result['message']}")
            
            self.data_store.add_log_entry("🎯 Snoring response sequence completed successfully")
            
        except Exception as e:
            error_msg = f"❌ Snoring response sequence failed: {str(e)}"
            self.data_store.add_log_entry(error_msg)
            logger.error(error_msg)
            # Ensure all pumps are turned off on error
            try:
                self.gpio_controller.control_pump(1, "OFF")
                self.gpio_controller.control_pump(2, "OFF")
            except:
                pass
        finally:
            self.data_store.update_status(snoring_response_active=False)
    
    def record_and_predict(self) -> Optional[Dict[str, Any]]:
        """Record audio and predict with automatic snoring response."""
        try:
            # Record audio
            audio_path = self.audio_processor.record_audio()
            if not audio_path:
                self.data_store.add_log_entry("❌ Failed to record audio")
                return None
            
            # Verify file was created and has content
            if not os.path.exists(audio_path):
                self.data_store.add_log_entry(f"❌ Audio file was not created: {audio_path}")
                return None
            
            file_size = os.path.getsize(audio_path)
            self.data_store.add_log_entry(f"📁 Audio file created: {os.path.basename(audio_path)} ({file_size} bytes)")
            
            # Predict
            result = self.model_handler.predict(audio_path)
            if not result:
                self.data_store.add_log_entry("❌ Prediction failed")
                return None
            
            # Log prediction with detailed information
            self.data_store.add_log_entry(
                f"🔍 Prediction: {result['class_name']} ({result['confidence']:.2f}%) [Model: {result.get('model_type', 'unknown')}]"
            )
            
            # Debug: Log threshold check
            threshold_check = result["confidence"] > self.config.CONFIDENCE_THRESHOLD * 100
            self.data_store.add_log_entry(
                f"🔬 Debug: Confidence {result['confidence']:.2f}% vs Threshold {self.config.CONFIDENCE_THRESHOLD * 100}% = {threshold_check}"
            )
            
            # Add to history
            timestamp_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            history_entry = {
                "timestamp": timestamp_str,
                "result": result,
                "audio_file": os.path.basename(audio_path)
            }
            self.data_store.add_detection_record(history_entry)
            
            # Auto snoring response - New logic with pump sequence
            # Check for snoring in both Thai and English
            is_snoring = result["class_name"] in ["กรน", "snoring", "Snoring", "SNORING"]
            confidence_above_threshold = result["confidence"] > self.config.CONFIDENCE_THRESHOLD * 100
            
            self.data_store.add_log_entry(
                f"🔬 Debug: class_name='{result['class_name']}', is_snoring={is_snoring}, confidence_above_threshold={confidence_above_threshold}"
            )
            
            if is_snoring and confidence_above_threshold:
                # Check if snoring response is already active
                status = self.data_store.get_status()
                already_active = status.get('snoring_response_active', False)
                
                self.data_store.add_log_entry(
                    f"🔬 Debug: snoring_response_already_active={already_active}"
                )
                
                if already_active:
                    self.data_store.add_log_entry("⚠️ Snoring detected but response sequence already in progress")
                else:
                    self.data_store.add_log_entry(
                        f"🚨 TRIGGERING SNORING RESPONSE: '{result['class_name']}' detected with {result['confidence']:.2f}% confidence > {self.config.CONFIDENCE_THRESHOLD*100}%"
                    )
                    
                    # Start snoring response in separate thread
                    response_thread = Thread(target=self._execute_snoring_response, daemon=True)
                    response_thread.start()
                    self.data_store.add_log_entry("🚀 Snoring response thread started")
            else:
                if is_snoring:
                    self.data_store.add_log_entry(f"ℹ️ Snoring ('{result['class_name']}') detected but confidence too low: {result['confidence']:.2f}% <= {self.config.CONFIDENCE_THRESHOLD*100}%")
                else:
                    self.data_store.add_log_entry(f"ℹ️ No snoring detected - class: '{result['class_name']}' - no action needed")
            
            # Cleanup old files
            self.audio_processor.cleanup_old_files()
            
            return result
            
        except Exception as e:
            error_msg = f"❌ Record and predict failed: {str(e)}"
            self.data_store.add_log_entry(error_msg)
            logger.error(error_msg)
            return None
    
    def start_auto_detection(self):
        """Start automatic detection in separate thread."""
        if self._auto_detection_thread and self._auto_detection_thread.is_alive():
            return {"success": False, "message": "Auto detection already running"}
        
        # Check if server-side recording is available
        if not SOUNDDEVICE_AVAILABLE:
            # Server-side auto detection not available, but client-side can work
            self.data_store.update_status(auto_detect_enabled=True)
            self.data_store.add_log_entry("ℹ️ Server-side auto detection not available (using client-side instead)")
            return {"success": True, "message": "Auto detection enabled (client-side mode)"}
        
        self.data_store.update_status(auto_detect_enabled=True)
        self._auto_detection_stop_event.clear()
        self._auto_detection_thread = Thread(target=self._auto_detection_loop, daemon=True)
        self._auto_detection_thread.start()
        
        self.data_store.add_log_entry("🤖 Auto detection started (server-side mode)")
        return {"success": True, "message": "Auto detection started"}
    
    def stop_auto_detection(self):
        """Stop automatic detection."""
        self.data_store.update_status(auto_detect_enabled=False)
        self._auto_detection_stop_event.set()
        
        if self._auto_detection_thread and self._auto_detection_thread.is_alive():
            self._auto_detection_thread.join(timeout=5)
        
        self.data_store.add_log_entry("🤖 Auto detection stopped")
        return {"success": True, "message": "Auto detection stopped"}
    
    def _auto_detection_loop(self):
        """Auto detection loop with improved control."""
        # Only run if sounddevice is available
        if not SOUNDDEVICE_AVAILABLE:
            self.data_store.add_log_entry("⚠️ Server-side auto detection loop cannot run without sounddevice")
            return
        
        while not self._auto_detection_stop_event.is_set():
            try:
                status = self.data_store.get_status()
                if not status['auto_detect_enabled']:
                    break
                
                # Skip if currently recording or snoring response is active
                if status['is_recording'] or status.get('snoring_response_active', False):
                    time.sleep(2)
                    continue
                
                # Run detection
                result = self.record_and_predict()
                
                # Determine wait time based on result
                if (result and result["class_name"] in ["กรน", "snoring", "Snoring", "SNORING"] and 
                    result["confidence"] > self.config.CONFIDENCE_THRESHOLD * 100):
                    # Wait full delay period after detecting snoring
                    wait_seconds = status['detection_delay'] * 60
                    self.data_store.add_log_entry(
                        f"✅ Snoring detected - Next detection in {status['detection_delay']} minutes"
                    )
                else:
                    # Quick retry if no snoring detected
                    wait_seconds = 5
                
                # Wait with ability to interrupt
                for _ in range(wait_seconds):
                    if self._auto_detection_stop_event.wait(1):
                        return
                    
            except Exception as e:
                self.data_store.add_log_entry(f"❌ Auto detection error: {str(e)}")
                time.sleep(10)  # Wait before retry
    
    def adjust_pillow(self, level: int):
        """Adjust pillow level with improved timing."""
        if level not in [1, 2, 3]:
            return {"success": False, "message": "Level must be 1, 2, or 3"}
        
        try:
            self.data_store.add_log_entry(f"🛏️ Adjusting pillow to level {level}")
            
            # Step 1: Deflate first (pump 2 for 20 seconds)
            result = self.gpio_controller.control_pump(2, "ON")
            if not result["success"]:
                return result
            
            time.sleep(20)
            self.gpio_controller.control_pump(2, "OFF")
            
            # Step 2: Inflate to desired level (pump 1)
            duration_map = {1: 15, 2: 30, 3: 50}
            duration = duration_map[level]
            
            result = self.gpio_controller.control_pump(1, "ON")
            if not result["success"]:
                return result
            
            time.sleep(duration)
            self.gpio_controller.control_pump(1, "OFF")
            
            self.data_store.add_log_entry(f"✅ Pillow adjusted to level {level}")
            return {"success": True, "message": f"Pillow adjusted to level {level}"}
            
        except Exception as e:
            # Ensure pumps are off
            self.gpio_controller.control_pump(1, "OFF")
            self.gpio_controller.control_pump(2, "OFF")
            error_msg = f"❌ Pillow adjustment failed: {str(e)}"
            self.data_store.add_log_entry(error_msg)
            return {"success": False, "message": str(e)}
    
    def deflate_pillow(self):
        """Deflate pillow completely."""
        try:
            self.data_store.add_log_entry("🔄 Deflating pillow")
            
            result = self.gpio_controller.control_pump(2, "ON")
            if not result["success"]:
                return result
            
            time.sleep(30)
            self.gpio_controller.control_pump(2, "OFF")
            
            self.data_store.add_log_entry("✅ Pillow deflated")
            return {"success": True, "message": "Pillow deflated"}
            
        except Exception as e:
            self.gpio_controller.control_pump(2, "OFF")
            error_msg = f"❌ Deflation failed: {str(e)}"
            self.data_store.add_log_entry(error_msg)
            return {"success": False, "message": str(e)}
    
    def set_detection_delay(self, delay_minutes: int):
        """Set detection delay with validation."""
        if not 1 <= delay_minutes <= 60:
            return {"success": False, "message": "Delay must be between 1 and 60 minutes"}
        
        self.data_store.update_status(detection_delay=delay_minutes)
        self.data_store.add_log_entry(f"⏲️ Detection delay set to {delay_minutes} minutes")
        return {"success": True, "message": f"Detection delay set to {delay_minutes} minutes"}
    
    def cleanup(self):
        """Clean up system resources."""
        try:
            self.stop_auto_detection()
            self.gpio_controller.cleanup()
            logger.info("System cleanup completed")
        except Exception as e:
            logger.error(f"Cleanup error: {str(e)}")

# --- Flask Application ---
app = None

def create_app():
    global app, db_manager_global
    
    app = Flask(__name__, static_folder=SystemConfig.STATIC_FOLDER)
    
    # Get secret key from environment or use default (CHANGE IN PRODUCTION!)
    app.secret_key = os.environ.get('SECRET_KEY', 'your-super-secret-key-change-this-in-production')
    app.config['SESSION_TYPE'] = 'filesystem'
    app.config['PERMANENT_SESSION_LIFETIME'] = 86400
    app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024  # 10MB max file size for audio uploads

    # Add security headers and CORS support
    @app.after_request
    def add_security_headers(response):
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-XSS-Protection'] = '1; mode=block'
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        
        # CORS headers - allow access from anywhere (adjust in production if needed)
        origin = request.headers.get('Origin')
        if origin:
            response.headers['Access-Control-Allow-Origin'] = origin
            response.headers['Access-Control-Allow-Credentials'] = 'true'
        else:
            # If no origin header, allow all (for API access)
            response.headers['Access-Control-Allow-Origin'] = '*'
        
        response.headers['Access-Control-Allow-Methods'] = 'GET, POST, PUT, DELETE, OPTIONS'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization, X-Requested-With'
        response.headers['Access-Control-Max-Age'] = '3600'
        
        return response
    
    # Handle CORS preflight requests
    @app.before_request
    def handle_preflight():
        if request.method == "OPTIONS":
            response = jsonify({})
            response.headers.add("Access-Control-Allow-Origin", request.headers.get('Origin', '*'))
            response.headers.add('Access-Control-Allow-Headers', "Content-Type, Authorization, X-Requested-With")
            response.headers.add('Access-Control-Allow-Methods', "GET, POST, PUT, DELETE, OPTIONS")
            response.headers.add('Access-Control-Allow-Credentials', 'true')
            return response
    
    # Create required directories
    os.makedirs(SystemConfig.STATIC_FOLDER, exist_ok=True)
    os.makedirs(SystemConfig.TEMPLATES_FOLDER, exist_ok=True)
    
    # Create js subdirectory
    os.makedirs(os.path.join(SystemConfig.STATIC_FOLDER, 'js'), exist_ok=True)
    os.makedirs(os.path.join(SystemConfig.STATIC_FOLDER, 'css'), exist_ok=True)
    
    # Initialize database - supports both SQLite and PostgreSQL
    db_path = os.environ.get('DATABASE_URL', 'snore_system.db')
    db_manager = DatabaseManager(db_path=db_path)
    db_manager_global = db_manager
    auth_middleware = AuthMiddleware(db_manager)
    
    # Initialize system (with error handling to allow app to start even if system init fails)
    try:
        snore_system = SnoreDetectionSystem()
    except Exception as e:
        logger.error(f"Failed to initialize SnoreDetectionSystem: {e}")
        logger.warning("App will start but system features may be limited")
        # Create a minimal system object to prevent errors
        snore_system = None
    
    @app.route('/')
    @auth_middleware.require_auth
    def index():
        return render_template('index.html')
    
    @app.route('/api/status', methods=['GET'])
    def get_status():
        try:
            status = snore_system.data_store.get_status()
            # Add additional status information
            status.update({
                'recording': status.get('is_recording', False),
                'pump': status.get('pump_status', False),
                'auto_detect': status.get('auto_detect_enabled', False),
                'delay': status.get('detection_delay', 5),
                'model_loaded': status.get('model_loaded', False),
                'gpio_ready': status.get('gpio_ready', False),
                'snoring_response_active': status.get('snoring_response_active', False)
            })
            return jsonify(status)
        except Exception as e:
            logger.error(f"Status API error: {str(e)}")
            return jsonify({"error": str(e)}), 500
    
    @app.route('/api/record', methods=['POST'])
    @auth_middleware.require_auth
    def api_record():
        user = request.current_user
        try:
            status = snore_system.data_store.get_status()
            if status['is_recording']:
                return jsonify({"success": False, "message": "Currently recording"})
            
            if status.get('snoring_response_active', False):
                return jsonify({"success": False, "message": "Snoring response sequence in progress"})
            
            # Start recording in background thread
            def record_task():
                result = snore_system.record_and_predict()
                if result:
                    logger.info(f"Recording task completed: {result}")
                else:
                    logger.error("Recording task failed")
            
            Thread(target=record_task, daemon=True).start()
            return jsonify({"success": True, "message": "Recording started"})
        except Exception as e:
            logger.error(f"Record API error: {str(e)}")
            return jsonify({"success": False, "message": str(e)}), 500
    
    @app.route('/api/upload_audio', methods=['POST'])
    @auth_middleware.require_auth
    def api_upload_audio():
        """Receive audio file from client and process it."""
        user = request.current_user
        try:
            status = snore_system.data_store.get_status()
            if status.get('snoring_response_active', False):
                return jsonify({"success": False, "message": "Snoring response sequence in progress"})
            
            # Check if audio file is in request
            if 'audio' not in request.files:
                return jsonify({"success": False, "message": "No audio file provided"}), 400
            
            audio_file = request.files['audio']
            if audio_file.filename == '':
                return jsonify({"success": False, "message": "No audio file selected"}), 400
            
            # Validate file extension
            if not audio_file.filename.lower().endswith(('.wav', '.mp3', '.ogg', '.webm')):
                return jsonify({"success": False, "message": "Invalid audio format. Please use WAV, MP3, OGG, or WebM"}), 400
            
            # Save uploaded audio file
            snore_system.data_store.update_status(is_recording=True)
            audio_path = snore_system.audio_processor.save_uploaded_audio(audio_file)
            
            if not audio_path:
                snore_system.data_store.update_status(is_recording=False)
                return jsonify({"success": False, "message": "Failed to save audio file"}), 500
            
            # Process audio in background thread
            def process_task():
                try:
                    result = snore_system.model_handler.predict(audio_path)
                    if result:
                        # Add to history
                        timestamp_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        history_entry = {
                            "timestamp": timestamp_str,
                            "result": result,
                            "audio_file": os.path.basename(audio_path)
                        }
                        snore_system.data_store.add_detection_record(history_entry)
                        
                        # Log prediction
                        snore_system.data_store.add_log_entry(
                            f"🔍 Prediction: {result['class_name']} ({result['confidence']:.2f}%) [Model: {result.get('model_type', 'unknown')}]"
                        )
                        
                        # Auto snoring response
                        is_snoring = result["class_name"] in ["กรน", "snoring", "Snoring", "SNORING"]
                        confidence_above_threshold = result["confidence"] > snore_system.config.CONFIDENCE_THRESHOLD * 100
                        
                        if is_snoring and confidence_above_threshold:
                            status = snore_system.data_store.get_status()
                            if not status.get('snoring_response_active', False):
                                snore_system.data_store.add_log_entry(
                                    f"🚨 TRIGGERING SNORING RESPONSE: '{result['class_name']}' detected with {result['confidence']:.2f}% confidence"
                                )
                                response_thread = Thread(target=snore_system._execute_snoring_response, daemon=True)
                                response_thread.start()
                        
                        # Cleanup old files
                        snore_system.audio_processor.cleanup_old_files()
                        
                        logger.info(f"Audio processing completed: {result}")
                    else:
                        logger.error("Audio processing failed")
                except Exception as e:
                    logger.error(f"Error processing audio: {str(e)}")
                finally:
                    snore_system.data_store.update_status(is_recording=False)
            
            Thread(target=process_task, daemon=True).start()
            
            return jsonify({
                "success": True, 
                "message": "Audio uploaded and processing started",
                "filename": os.path.basename(audio_path)
            })
            
        except Exception as e:
            snore_system.data_store.update_status(is_recording=False)
            logger.error(f"Upload audio API error: {str(e)}")
            return jsonify({"success": False, "message": str(e)}), 500
    
    @app.route('/api/auto_detect', methods=['POST'])
    @auth_middleware.require_auth
    def api_auto_detect():
        try:
            data = request.json
            if not data:
                return jsonify({"success": False, "message": "No data provided"}), 400
            
            enabled = data.get('enabled', False)
            
            if enabled:
                result = snore_system.start_auto_detection()
            else:
                result = snore_system.stop_auto_detection()
            
            return jsonify(result)
        except Exception as e:
            logger.error(f"Auto detect API error: {str(e)}")
            return jsonify({"success": False, "message": str(e)}), 500
    
    @app.route('/api/set_delay', methods=['POST'])
    @auth_middleware.require_auth
    def api_set_delay():
        try:
            data = request.json
            if not data:
                return jsonify({"success": False, "message": "No data provided"}), 400
            
            delay = data.get('delay', 5)
            result = snore_system.set_detection_delay(delay)
            return jsonify(result)
        except Exception as e:
            logger.error(f"Set delay API error: {str(e)}")
            return jsonify({"success": False, "message": str(e)}), 500
    
    @app.route('/api/settings', methods=['GET'])
    @auth_middleware.require_auth
    def get_settings():
        try:
            status = snore_system.data_store.get_status()
            return jsonify({
                "auto_detect": status['auto_detect_enabled'],
                "delay": status['detection_delay']
            })
        except Exception as e:
            logger.error(f"Settings API error: {str(e)}")
            return jsonify({"error": str(e)}), 500
    
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
    
    @app.route('/api/pump', methods=['POST'])
    @auth_middleware.require_auth
    def api_pump():
        """Control pump - requires authentication"""
        try:
            user = request.current_user
            data = request.json
            if not data:
                return jsonify({"success": False, "message": "No data provided"}), 400
            
            action = data.get('action', 'OFF')
            pump_number = data.get('pump', 1)
            result = snore_system.gpio_controller.control_pump(pump_number, action)
            
            # Log action
            db_manager.add_system_log(
                message=f"User {user['username']} controlled pump {pump_number}: {action}",
                log_level="INFO",
                user_id=user['user_id']
            )
            
            return jsonify(result)
        except Exception as e:
            logger.error(f"Pump API error: {str(e)}")
            return jsonify({"success": False, "message": str(e)}), 500
    
    @app.route('/api/valve', methods=['POST'])
    @auth_middleware.require_auth
    def api_valve():
        """Control solenoid valve independently - requires authentication"""
        try:
            user = request.current_user
            data = request.json
            if not data:
                return jsonify({"success": False, "message": "No data provided"}), 400
            
            action = data.get('action', 'OFF')
            valve_number = data.get('valve', 1)
            result = snore_system.gpio_controller.control_valve(valve_number, action)
            
            # Log action
            db_manager.add_system_log(
                message=f"User {user['username']} controlled valve {valve_number}: {action}",
                log_level="INFO",
                user_id=user['user_id']
            )
            
            return jsonify(result)
        except Exception as e:
            logger.error(f"Valve API error: {str(e)}")
            return jsonify({"success": False, "message": str(e)}), 500
    
    @app.route('/api/adjust_pillow', methods=['POST'])
    @auth_middleware.require_auth
    def api_adjust_pillow():
        """Adjust pillow level - requires authentication"""
        try:
            user = request.current_user
            data = request.json
            if not data:
                return jsonify({"success": False, "message": "No data provided"}), 400
            
            level = data.get('level', 1)
            
            # Log action
            db_manager.add_system_log(
                message=f"User {user['username']} adjusting pillow to level {level}",
                log_level="INFO",
                user_id=user['user_id']
            )
            
            def adjust_task():
                result = snore_system.adjust_pillow(level)
                logger.info(f"Pillow adjustment completed: {result}")
            
            Thread(target=adjust_task, daemon=True).start()
            return jsonify({"success": True, "message": f"Adjusting pillow to level {level}"})
        except Exception as e:
            logger.error(f"Adjust pillow API error: {str(e)}")
            return jsonify({"success": False, "message": str(e)}), 500
    
    @app.route('/api/deflate_pillow', methods=['POST'])
    @auth_middleware.require_auth
    def api_deflate_pillow():
        """Deflate pillow - requires authentication"""
        try:
            user = request.current_user
            
            # Log action
            db_manager.add_system_log(
                message=f"User {user['username']} deflating pillow",
                log_level="INFO",
                user_id=user['user_id']
            )
            
            def deflate_task():
                result = snore_system.deflate_pillow()
                logger.info(f"Pillow deflation completed: {result}")
            
            Thread(target=deflate_task, daemon=True).start()
            return jsonify({"success": True, "message": "Deflating pillow"})
        except Exception as e:
            logger.error(f"Deflate pillow API error: {str(e)}")
            return jsonify({"success": False, "message": str(e)}), 500
    
    @app.route('/api/logs', methods=['GET'])
    @auth_middleware.require_auth
    def get_logs():
        try:
            logs = snore_system.data_store.get_activity_log()
            return jsonify(logs)
        except Exception as e:
            logger.error(f"Logs API error: {str(e)}")
            return jsonify({"error": str(e)}), 500
    
    @app.route('/api/info', methods=['GET'])
    def get_info():
        try:
            return jsonify({
                "system": "Smart Anti-Snoring Pillow System",
                "version": "2.0",
                "model": SystemConfig.MODEL_PATH,
                "model_type": snore_system.model_handler.model_type if snore_system.model_handler else "unknown",
                "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "snoring_response_config": {
                    "pump1_duration": SystemConfig.PUMP1_DURATION,
                    "wait_between_pumps": SystemConfig.WAIT_BETWEEN_PUMPS,
                    "pump2_duration": SystemConfig.PUMP2_DURATION
                }
            })
        except Exception as e:
            logger.error(f"Info API error: {str(e)}")
            return jsonify({"error": str(e)}), 500
    
    @app.route('/static/<path:filename>')
    def serve_static(filename):
        return send_from_directory(app.static_folder, filename)
    
    @app.route('/favicon.ico')
    def favicon():
        return send_from_directory(app.static_folder, 'favicon.ico', mimetype='image/vnd.microsoft.icon')
    
    # Error handlers
    @app.errorhandler(404)
    def not_found(error):
        return jsonify({"error": "Not found"}), 404
    
    @app.errorhandler(500)
    def internal_error(error):
        return jsonify({"error": "Internal server error"}), 500
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
    
    return app

# Create app instance for gunicorn (production)
# Always create app for gunicorn, but skip if running with Flask dev server
# Gunicorn doesn't set WERKZEUG_RUN_MAIN, so we create the app here
# Flask dev server sets it, so we skip here and create in __main__
if os.environ.get('WERKZEUG_RUN_MAIN') != 'true':
    try:
        app = create_app()
        if app is None:
            logger.error("create_app() returned None")
            # Force app creation
            app = create_app()
    except Exception as e:
        logger.error(f"Failed to create app: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        # Try one more time
        try:
            app = create_app()
        except Exception as e2:
            logger.error(f"Failed to create app on retry: {str(e2)}")
            logger.error(traceback.format_exc())
            # Create a minimal Flask app so gunicorn doesn't fail
            app = Flask(__name__)
            @app.route('/')
            def health():
                return jsonify({"status": "error", "message": "App initialization failed"}), 500
else:
    # Running with Flask dev server, app will be created in __main__
    app = None

# --- Main Entry Point ---
if __name__ == "__main__":
    def cleanup_sessions_periodically():
        """Cleanup expired sessions periodically"""
        while True:
            try:
                time.sleep(3600)  # รอ 1 ชั่วโมง
                if db_manager_global:
                    db_manager_global.cleanup_expired_sessions()
                logger.info("Expired sessions cleaned up")
            except Exception as e:
                logger.error(f"Session cleanup error: {str(e)}")
    
    try:
        app = create_app()
        
        # Check for required files
        if not os.path.exists(os.path.join(SystemConfig.TEMPLATES_FOLDER, 'index.html')):
            logger.error("index.html not found in templates folder")
        else:
            logger.info("index.html found in templates folder")
        
        # Check model file
        if not os.path.exists(SystemConfig.MODEL_PATH):
            logger.warning(f"Model file not found: {SystemConfig.MODEL_PATH}")
        else:
            logger.info(f"Model file found: {SystemConfig.MODEL_PATH}")
        
        # Start cleanup task
        cleanup_thread = threading.Thread(target=cleanup_sessions_periodically, daemon=True)
        cleanup_thread.start()
        
        # Get port from environment variable or use default
        port = int(os.environ.get('PORT', 5000))
        host = os.environ.get('HOST', '0.0.0.0')
        debug = os.environ.get('DEBUG', 'False').lower() == 'true'
        
        logger.info(f"Starting server on {host}:{port}")
        logger.info(f"Model path: {SystemConfig.MODEL_PATH}")
        logger.info(f"Static folder: {SystemConfig.STATIC_FOLDER}")
        logger.info(f"Snoring response config - Pump1: {SystemConfig.PUMP1_DURATION}s, Wait: {SystemConfig.WAIT_BETWEEN_PUMPS}s, Pump2: {SystemConfig.PUMP2_DURATION}s")
        
        app.run(host=host, port=port, debug=debug, threaded=True)
        
    except Exception as e:
        logger.error(f"Server startup failed: {str(e)}")
        sys.exit(1)
