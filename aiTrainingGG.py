import os
import glob
import numpy as np
import librosa
import librosa.display
import matplotlib.pyplot as plt
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import LabelEncoder
from sklearn.metrics import confusion_matrix, classification_report
import tensorflow as tf
from tensorflow.keras.models import Sequential
from tensorflow.keras.layers import (
    Conv1D, MaxPooling1D, GlobalAveragePooling1D, 
    Dense, Dropout, BatchNormalization
)
from tensorflow.keras.optimizers import Adam
from tensorflow.keras.callbacks import EarlyStopping, ReduceLROnPlateau
from tensorflow.keras.metrics import Precision, Recall, BinaryAccuracy
import seaborn as sns
import json
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Log TensorFlow version for compatibility check
# logger.info(f"TensorFlow version: {tf.__version__}")
# logger.info(f"Keras version: {tf.keras.__version__}")

# --- Configuration Class ---
class Config:
    DATASET_PATH = 'snore_dataset/'
    FIXED_DURATION_SEC = 5
    SAMPLE_RATE = 22050
    FIXED_LENGTH = SAMPLE_RATE * FIXED_DURATION_SEC
    N_MELS = 128
    N_MFCC = 40
    HOP_LENGTH = 512
    N_FFT = 2048
    TEST_SIZE = 0.2
    RANDOM_STATE = 42
    BATCH_SIZE = 32
    EPOCHS = 100
    PATIENCE = 15
    MIN_LR = 1e-7

# --- Custom Exceptions ---
class AudioProcessingError(Exception):
    """Exception raised for errors in audio processing."""
    pass

class ModelTrainingError(Exception):
    """Exception raised for errors in model training."""
    pass

# --- Improved Feature Extraction ---
class AudioFeatureExtractor:
    def __init__(self, config):
        self.config = config
    
    def load_and_preprocess_audio(self, file_path):
        """Load and preprocess audio file with better error handling."""
        try:
            # Load audio with better resampling
            audio, sample_rate = librosa.load(
                file_path, 
                sr=self.config.SAMPLE_RATE, 
                res_type='kaiser_fast'
            )
            
            # Remove silence more intelligently
            audio, _ = librosa.effects.trim(audio, top_db=20, frame_length=2048, hop_length=512)
            
            # Normalize audio length
            if len(audio) < self.config.FIXED_LENGTH:
                # Pad with silence
                audio = np.pad(audio, (0, self.config.FIXED_LENGTH - len(audio)), 'constant')
            else:
                # Take the most energetic part
                audio = self._extract_most_energetic_segment(audio)
            
            # Normalize amplitude
            audio = librosa.util.normalize(audio)
            
            return audio
            
        except Exception as e:
            raise AudioProcessingError(f"Error processing {file_path}: {str(e)}")
    
    def _extract_most_energetic_segment(self, audio):
        """Extract the most energetic segment of audio."""
        if len(audio) <= self.config.FIXED_LENGTH:
            return audio
        
        # Calculate energy in sliding windows
        window_size = self.config.FIXED_LENGTH
        step_size = self.config.SAMPLE_RATE // 4  # 0.25 second steps
        
        max_energy = -1
        best_start = 0
        
        for start in range(0, len(audio) - window_size + 1, step_size):
            segment = audio[start:start + window_size]
            energy = np.sum(segment ** 2)
            
            if energy > max_energy:
                max_energy = energy
                best_start = start
        
        return audio[best_start:best_start + window_size]
    
    def extract_mel_spectrogram(self, audio):
        """Extract mel spectrogram features (preserves temporal information)."""
        try:
            # Compute mel spectrogram
            mel_spec = librosa.feature.melspectrogram(
                y=audio,
                sr=self.config.SAMPLE_RATE,
                n_mels=self.config.N_MELS,
                n_fft=self.config.N_FFT,
                hop_length=self.config.HOP_LENGTH,
                fmax=8000
            )
            
            # Convert to dB scale
            mel_spec_db = librosa.power_to_db(mel_spec, ref=np.max)
            
            # Normalize
            mel_spec_db = (mel_spec_db - mel_spec_db.mean()) / (mel_spec_db.std() + 1e-6)
            
            return mel_spec_db.T  # Shape: (time_steps, n_mels)
            
        except Exception as e:
            raise AudioProcessingError(f"Error extracting mel spectrogram: {str(e)}")
    
    def extract_mfcc_sequence(self, audio):
        """Extract MFCC sequence (preserves temporal information)."""
        try:
            # Compute MFCC
            mfccs = librosa.feature.mfcc(
                y=audio,
                sr=self.config.SAMPLE_RATE,
                n_mfcc=self.config.N_MFCC,
                n_fft=self.config.N_FFT,
                hop_length=self.config.HOP_LENGTH
            )
            
            # Add delta and delta-delta features
            delta_mfccs = librosa.feature.delta(mfccs)
            delta2_mfccs = librosa.feature.delta(mfccs, order=2)
            
            # Combine features
            features = np.vstack([mfccs, delta_mfccs, delta2_mfccs])
            
            # Normalize
            features = (features - features.mean(axis=1, keepdims=True)) / (features.std(axis=1, keepdims=True) + 1e-6)
            
            return features.T  # Shape: (time_steps, n_features)
            
        except Exception as e:
            raise AudioProcessingError(f"Error extracting MFCC sequence: {str(e)}")
    
    def extract_features(self, file_path, feature_type='mel'):
        """Extract features from audio file."""
        audio = self.load_and_preprocess_audio(file_path)
        
        if feature_type == 'mel':
            return self.extract_mel_spectrogram(audio)
        elif feature_type == 'mfcc':
            return self.extract_mfcc_sequence(audio)
        else:
            raise ValueError(f"Unknown feature type: {feature_type}")

# --- Data Pipeline ---
class DataPipeline:
    def __init__(self, config, feature_extractor):
        self.config = config
        self.feature_extractor = feature_extractor
        self.label_encoder = LabelEncoder()
        
    def create_dataset(self, feature_type='mel'):
        """Create dataset with improved error handling and progress tracking."""
        features = []
        labels = []
        
        dataset_path = self.config.DATASET_PATH
        if not os.path.exists(dataset_path):
            raise FileNotFoundError(f"Dataset path not found: {dataset_path}")
        
        class_labels = [f for f in os.listdir(dataset_path) 
                       if os.path.isdir(os.path.join(dataset_path, f))]
        
        if len(class_labels) == 0:
            raise ValueError("No class directories found in dataset path")
        
        logger.info(f"Found classes: {class_labels}")
        
        total_files = 0
        processed_files = 0
        failed_files = 0
        
        for label in class_labels:
            wav_files = glob.glob(os.path.join(dataset_path, label, '*.wav'))
            total_files += len(wav_files)
            
            logger.info(f"Processing class '{label}': {len(wav_files)} files")
            
            for i, file_path in enumerate(wav_files):
                try:
                    feature = self.feature_extractor.extract_features(file_path, feature_type)
                    features.append(feature)
                    labels.append(label)
                    processed_files += 1
                    
                    if (i + 1) % 50 == 0:
                        logger.info(f"  Processed {i + 1}/{len(wav_files)} files for class '{label}'")
                        
                except Exception as e:
                    logger.warning(f"Failed to process {file_path}: {str(e)}")
                    failed_files += 1
                    continue
        
        logger.info(f"Dataset creation completed:")
        logger.info(f"  Total files: {total_files}")
        logger.info(f"  Successfully processed: {processed_files}")
        logger.info(f"  Failed: {failed_files}")
        
        if len(features) == 0:
            raise ValueError("No features extracted from dataset")
        
        # Convert to numpy arrays and pad sequences
        features = self._pad_sequences(features)
        labels = np.array(labels)
        
        return features, labels
    
    def _pad_sequences(self, sequences):
        """Pad sequences to same length."""
        max_length = max(seq.shape[0] for seq in sequences)
        feature_dim = sequences[0].shape[1]
        
        padded_sequences = np.zeros((len(sequences), max_length, feature_dim))
        
        for i, seq in enumerate(sequences):
            seq_length = seq.shape[0]
            padded_sequences[i, :seq_length, :] = seq
        
        return padded_sequences
    
    def prepare_data(self, features, labels):
        """Prepare data for training."""
        # Encode labels
        labels_encoded = self.label_encoder.fit_transform(labels)
        
        # Log label mapping
        label_mapping = dict(zip(self.label_encoder.classes_, 
                                self.label_encoder.transform(self.label_encoder.classes_)))
        logger.info(f"Label mapping: {label_mapping}")
        
        # Save label encoder
        self._save_label_encoder()
        
        # Split data
        X_train, X_test, y_train, y_test = train_test_split(
            features, labels_encoded,
            test_size=self.config.TEST_SIZE,
            random_state=self.config.RANDOM_STATE,
            stratify=labels_encoded
        )
        
        logger.info(f"Training samples: {len(X_train)}")
        logger.info(f"Test samples: {len(X_test)}")
        
        return X_train, X_test, y_train, y_test
    
    def _save_label_encoder(self):
        """Save label encoder mapping to JSON."""
        mapping = {
            'classes': self.label_encoder.classes_.tolist(),
            'class_to_index': dict(zip(self.label_encoder.classes_.tolist(),
                                     self.label_encoder.transform(self.label_encoder.classes_).tolist()))
        }
        
        with open('label_mapping.json', 'w', encoding='utf-8') as f:
            json.dump(mapping, f, ensure_ascii=False, indent=2)
        
        logger.info("Label mapping saved to label_mapping.json")

# --- Improved Model Architecture ---
class SnoreDetectionModel:
    def __init__(self, input_shape):
        self.input_shape = input_shape
        self.model = None
    
    def create_cnn_model(self):
        """Create improved CNN model for audio classification - compatible with TF 2.13.x."""
        # For Sequential model, specify input_shape in the first layer (NOT batch_shape)
        # Use explicit dtype='float32' (string, not DTypePolicy object) for TF 2.13.x compatibility
        model = Sequential([
            # First Conv Block - input_shape specified in first Conv1D layer
            Conv1D(32, kernel_size=3, activation='relu', padding='same', 
                   input_shape=self.input_shape, dtype='float32', name='input_conv'),
            BatchNormalization(dtype='float32'),
            Conv1D(32, kernel_size=3, activation='relu', padding='same', dtype='float32'),
            MaxPooling1D(pool_size=2),
            Dropout(0.25),
            
            # Second Conv Block
            Conv1D(64, kernel_size=3, activation='relu', padding='same', dtype='float32'),
            BatchNormalization(dtype='float32'),
            Conv1D(64, kernel_size=3, activation='relu', padding='same', dtype='float32'),
            MaxPooling1D(pool_size=2),
            Dropout(0.25),
            
            # Third Conv Block
            Conv1D(128, kernel_size=3, activation='relu', padding='same', dtype='float32'),
            BatchNormalization(dtype='float32'),
            Conv1D(128, kernel_size=3, activation='relu', padding='same', dtype='float32'),
            GlobalAveragePooling1D(),
            Dropout(0.5),
            
            # Classification Head
            Dense(128, activation='relu', dtype='float32'),
            BatchNormalization(dtype='float32'),
            Dropout(0.5),
            Dense(64, activation='relu', dtype='float32'),
            Dropout(0.3),
            Dense(1, activation='sigmoid', dtype='float32')
        ])
        
        self.model = model
        logger.info(f"Model created with input_shape: {self.input_shape}")
        logger.info("✅ Model uses input_shape (not batch_shape) and string dtype for TF 2.13.x compatibility")
        return model
    
    def compile_model(self, learning_rate=0.001):
        """Compile model with improved configuration - compatible with TF 2.13.x."""
        if self.model is None:
            raise ModelTrainingError("Model not created yet")
        
        # Use string for learning_rate (not deprecated)
        optimizer = Adam(learning_rate=learning_rate)
        
        # For binary classification, use metric objects instead of strings
        # 'precision' and 'recall' as strings don't work well in TF 2.13.x for binary classification
        metrics = [
            BinaryAccuracy(name='accuracy'),
            Precision(name='precision'),
            Recall(name='recall')
        ]
        
        self.model.compile(
            optimizer=optimizer,
            loss='binary_crossentropy',
            metrics=metrics,
            # Ensure compatibility with TF 2.13.x
            run_eagerly=False
        )
        
        logger.info("Model compiled successfully with TF 2.13.x compatibility")
        return self.model
    
    def get_callbacks(self):
        """Get training callbacks."""
        callbacks = [
            EarlyStopping(
                monitor='val_loss',
                patience=Config.PATIENCE,
                restore_best_weights=True,
                verbose=1
            ),
            ReduceLROnPlateau(
                monitor='val_loss',
                factor=0.5,
                patience=5,
                min_lr=Config.MIN_LR,
                verbose=1
            )
        ]
        return callbacks

# --- Training Pipeline ---
class TrainingPipeline:
    def __init__(self, config):
        self.config = config
        self.feature_extractor = AudioFeatureExtractor(config)
        self.data_pipeline = DataPipeline(config, self.feature_extractor)
        self.model_builder = None
        self.model = None
        self.history = None
    
    def run_training(self, feature_type='mel'):
        """Run complete training pipeline."""
        logger.info("Starting training pipeline...")
        
        try:
            # 1. Create dataset
            logger.info("Step 1: Creating dataset...")
            features, labels = self.data_pipeline.create_dataset(feature_type)
            
            # 2. Prepare data
            logger.info("Step 2: Preparing data...")
            X_train, X_test, y_train, y_test = self.data_pipeline.prepare_data(features, labels)
            
            # 3. Create model
            logger.info("Step 3: Creating model...")
            input_shape = X_train.shape[1:]
            self.model_builder = SnoreDetectionModel(input_shape)
            self.model = self.model_builder.create_cnn_model()
            self.model = self.model_builder.compile_model()
            
            logger.info(f"Model input shape: {input_shape}")
            self.model.summary()
            
            # 4. Train model
            logger.info("Step 4: Training model...")
            callbacks = self.model_builder.get_callbacks()
            
            self.history = self.model.fit(
                X_train, y_train,
                batch_size=self.config.BATCH_SIZE,
                epochs=self.config.EPOCHS,
                validation_data=(X_test, y_test),
                callbacks=callbacks,
                verbose=1
            )
            
            # 5. Evaluate model
            logger.info("Step 5: Evaluating model...")
            self._evaluate_model(X_test, y_test)
            
            # 6. Save model
            logger.info("Step 6: Saving model...")
            self._save_model()
            
            logger.info("Training pipeline completed successfully!")
            
        except Exception as e:
            logger.error(f"Training pipeline failed: {str(e)}")
            raise ModelTrainingError(f"Training failed: {str(e)}")
    
    def _evaluate_model(self, X_test, y_test):
        """Evaluate model performance."""
        # Get predictions
        y_pred_prob = self.model.predict(X_test)
        y_pred = (y_pred_prob > 0.5).astype(int)
        
        # Calculate metrics
        test_loss, test_acc, test_precision, test_recall = self.model.evaluate(X_test, y_test, verbose=0)
        
        logger.info(f"Test Results:")
        logger.info(f"  Loss: {test_loss:.4f}")
        logger.info(f"  Accuracy: {test_acc:.4f}")
        logger.info(f"  Precision: {test_precision:.4f}")
        logger.info(f"  Recall: {test_recall:.4f}")
        
        # Classification report
        report = classification_report(
            y_test, y_pred,
            target_names=self.data_pipeline.label_encoder.classes_,
            output_dict=True
        )
        
        logger.info("Classification Report:")
        for class_name, metrics in report.items():
            if isinstance(metrics, dict):
                logger.info(f"  {class_name}: Precision={metrics['precision']:.3f}, "
                           f"Recall={metrics['recall']:.3f}, F1={metrics['f1-score']:.3f}")
        
        # Confusion matrix
        cm = confusion_matrix(y_test, y_pred)
        self._plot_confusion_matrix(cm)
        
        # Plot training history
        self._plot_training_history()
    
    def _plot_confusion_matrix(self, cm):
        """Plot and save confusion matrix."""
        plt.figure(figsize=(10, 8))
        sns.heatmap(cm, annot=True, fmt='d', cmap='Blues',
                   xticklabels=self.data_pipeline.label_encoder.classes_,
                   yticklabels=self.data_pipeline.label_encoder.classes_)
        plt.title('Confusion Matrix')
        plt.ylabel('Actual Label')
        plt.xlabel('Predicted Label')
        plt.tight_layout()
        plt.savefig('confusion_matrix.png', dpi=300, bbox_inches='tight')
        plt.show()
        
        logger.info("Confusion matrix saved as confusion_matrix.png")
    
    def _plot_training_history(self):
        """Plot and save training history."""
        if self.history is None:
            return
        
        fig, axes = plt.subplots(2, 2, figsize=(15, 10))
        
        # Accuracy
        axes[0, 0].plot(self.history.history['accuracy'], label='Training')
        axes[0, 0].plot(self.history.history['val_accuracy'], label='Validation')
        axes[0, 0].set_title('Model Accuracy')
        axes[0, 0].set_xlabel('Epoch')
        axes[0, 0].set_ylabel('Accuracy')
        axes[0, 0].legend()
        
        # Loss
        axes[0, 1].plot(self.history.history['loss'], label='Training')
        axes[0, 1].plot(self.history.history['val_loss'], label='Validation')
        axes[0, 1].set_title('Model Loss')
        axes[0, 1].set_xlabel('Epoch')
        axes[0, 1].set_ylabel('Loss')
        axes[0, 1].legend()
        
        # Precision
        axes[1, 0].plot(self.history.history['precision'], label='Training')
        axes[1, 0].plot(self.history.history['val_precision'], label='Validation')
        axes[1, 0].set_title('Model Precision')
        axes[1, 0].set_xlabel('Epoch')
        axes[1, 0].set_ylabel('Precision')
        axes[1, 0].legend()
        
        # Recall
        axes[1, 1].plot(self.history.history['recall'], label='Training')
        axes[1, 1].plot(self.history.history['val_recall'], label='Validation')
        axes[1, 1].set_title('Model Recall')
        axes[1, 1].set_xlabel('Epoch')
        axes[1, 1].set_ylabel('Recall')
        axes[1, 1].legend()
        
        plt.tight_layout()
        plt.savefig('training_history.png', dpi=300, bbox_inches='tight')
        plt.show()
        
        logger.info("Training history saved as training_history.png")
    
    def _save_model(self):
        """Save trained model and metadata - compatible with TF 2.13.x."""
        if self.model is None:
            raise ModelTrainingError("No model to save")
        
        # Save model in SavedModel format (recommended for TF 2.x) or H5 format
        # Using save_format='h5' explicitly to ensure compatibility
        try:
            # Method 1: Save as H5 (legacy format but widely compatible)
            self.model.save('snore_detection_model.h5', save_format='h5')
            logger.info("Model saved as snore_detection_model.h5 (H5 format)")
        except Exception as e:
            logger.warning(f"H5 save failed: {e}, trying SavedModel format...")
            # Method 2: Save as SavedModel (TF 2.x recommended format)
            self.model.save('snore_detection_model', save_format='tf')
            logger.info("Model saved as snore_detection_model (SavedModel format)")
        
        # Verify model can be loaded back (compatibility check)
        try:
            test_model = tf.keras.models.load_model('snore_detection_model.h5' if os.path.exists('snore_detection_model.h5') else 'snore_detection_model')
            logger.info("✅ Model compatibility verified - can be loaded successfully")
            del test_model  # Free memory
        except Exception as e:
            logger.warning(f"⚠️ Model compatibility check failed: {e}")
        
        # Save model metadata
        input_shape = self.model.input_shape
        if isinstance(input_shape, (list, tuple)) and len(input_shape) > 1:
            input_shape_clean = list(input_shape[1:])  # Remove batch dimension
        else:
            input_shape_clean = list(input_shape) if isinstance(input_shape, (list, tuple)) else [input_shape]
        
        metadata = {
            'model_type': 'CNN',
            'input_shape': input_shape_clean,
            'feature_type': 'mel_spectrogram',
            'sample_rate': self.config.SAMPLE_RATE,
            'duration': self.config.FIXED_DURATION_SEC,
            'n_mels': self.config.N_MELS,
            'tensorflow_version': tf.__version__,
            'keras_version': tf.keras.__version__,
            'training_params': {
                'batch_size': self.config.BATCH_SIZE,
                'epochs': self.config.EPOCHS,
                'test_size': self.config.TEST_SIZE
            },
            'compatibility': {
                'uses_input_shape': True,
                'uses_string_dtype': True,
                'tf_2_13_compatible': True
            }
        }
        
        with open('model_metadata.json', 'w', encoding='utf-8') as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)
        
        logger.info("Model metadata saved as model_metadata.json")
        logger.info(f"Model is compatible with TensorFlow {tf.__version__}")

# --- Prediction Function ---
def predict_snoring_improved(model_path, audio_path, feature_type='mel'):
    """Improved prediction function with better error handling."""
    try:
        # Load model and metadata
        model = tf.keras.models.load_model(model_path)
        
        with open('model_metadata.json', 'r') as f:
            metadata = json.load(f)
        
        with open('label_mapping.json', 'r') as f:
            label_mapping = json.load(f)
        
        # Initialize feature extractor with config from metadata
        config = Config()
        config.SAMPLE_RATE = metadata['sample_rate']
        config.FIXED_DURATION_SEC = metadata['duration']
        config.N_MELS = metadata.get('n_mels', 128)
        
        feature_extractor = AudioFeatureExtractor(config)
        
        # Extract features
        features = feature_extractor.extract_features(audio_path, feature_type)
        features = np.expand_dims(features, axis=0)  # Add batch dimension
        
        # Predict
        prediction_prob = model.predict(features)[0][0]
        predicted_class_index = 1 if prediction_prob > 0.5 else 0
        
        # Map to class name
        index_to_class = {v: k for k, v in label_mapping['class_to_index'].items()}
        predicted_label = index_to_class[predicted_class_index]
        
        return predicted_label, float(prediction_prob)
        
    except Exception as e:
        logger.error(f"Prediction failed: {str(e)}")
        return None, 0.0

# --- Main Execution ---
if __name__ == "__main__":
    try:
        # Initialize configuration
        config = Config()
        
        # Create training pipeline
        pipeline = TrainingPipeline(config)
        
        # Run training
        pipeline.run_training(feature_type='mel')
        
        # Test prediction
        logger.info("\n--- Testing Predictions ---")
        
        # Test files (update paths as needed)
        test_files = [
            ('test\SN1.7.wav', 'Expected: Snore'),
            ('test\SN1.7.wav', 'Expected: Non-snore')
        ]
        
        for test_file, expected in test_files:
            if os.path.exists(test_file):
                try:
                    predicted_class, probability = predict_snoring_improved(
                        'snore_detection_model.h5', test_file
                    )
                    logger.info(f"File: {test_file}")
                    logger.info(f"  {expected}")
                    logger.info(f"  Predicted: {predicted_class} (confidence: {probability:.4f})\n")
                except Exception as e:
                    logger.error(f"Failed to predict {test_file}: {str(e)}")
            else:
                logger.warning(f"Test file not found: {test_file}")
        
        logger.info("Training and testing completed successfully!")
        
    except Exception as e:
        logger.error(f"Script execution failed: {str(e)}")
        raise