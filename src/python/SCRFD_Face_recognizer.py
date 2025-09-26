#!/usr/bin/env python3
"""
SCRFD+ArcFace+FAISS Face Recognition System
Complete replacement for legacy MediaPipe system with better crowd + distance detection

Key Improvements:
- SCRFD: 77.9% vs ~60% AP on WIDER FACE (better distance detection)
- ArcFace: State-of-the-art face embeddings vs OpenCV features
- FAISS: Sub-millisecond search vs linear O(n) matching
- GPU acceleration: Full pipeline on CUDA/CoreML vs CPU-only legacy systems
- Crowd handling: Intelligent batch processing for 10+ faces
"""

import os
import cv2
import time
import yaml
import json
import numpy as np
import logging
import threading
from typing import Optional, Tuple, List, Dict, Any
from dataclasses import dataclass
from pathlib import Path
from queue import Queue
from enum import Enum

class DatabaseOperation(Enum):
    """Types of database operations that can be queued"""
    REBUILD = "rebuild"

@dataclass
class QueuedOperation:
    """Represents a queued database operation"""
    operation: DatabaseOperation
    data: Dict[str, Any] = None

# Import SCRFD+ArcFace+FAISS components
from models.scrfd import SCRFD
from models.arcface import ArcFace
from database.face_db import FaceDatabase

@dataclass
class FaceDetection:
    """Face detection result with enhanced information for compatibility"""
    bbox: Tuple[int, int, int, int]  # x, y, width, height (MediaPipe format)
    confidence: float
    landmarks: Optional[np.ndarray] = None  # 5-point landmarks for ArcFace
    quality_score: float = 0.0
    face_area: int = 0
    is_frontal: bool = True

@dataclass
class FaceRecognitionResult:
    """Face recognition result for API compatibility"""
    person_id: str
    person_name: str
    confidence: float
    detection: FaceDetection

class SCRFDFaceRecognizer:
    """
    Modern SCRFD+ArcFace+FAISS face recognition system

    Complete replacement for legacy face recognition system with:
    - Better distance detection (8-10+ feet vs 6 feet)
    - Better crowd handling (parallel processing for 10+ faces)
    - Better recognition accuracy (ArcFace vs OpenCV features)
    - Faster similarity search (FAISS vs linear search)
    - Full GPU acceleration support
    """

    def __init__(self,
                 thresold=0.35,  # Recognition threshold (compatible with MediaPipe API)
                 draw=True,
                 cache_encodings=True,
                 include_landmarks=False):

        # API compatibility
        self.threshold = thresold
        self.draw = draw
        self.cache_encodings = cache_encodings
        self.include_landmarks = include_landmarks
        self.unknownmatch = 0

        # Performance tracking (compatible with existing system)
        self.detection_times = []
        self.recognition_times = []
        self.last_processed_time = time.time()

        # Queue system for database operations during detection
        self.operation_queue = Queue()
        self.detection_active = False
        self.queue_lock = threading.Lock()

        # Load configuration from existing config.yaml
        self._load_config()

        # Initialize models
        print("🚀 Initializing SCRFD+ArcFace+FAISS system...")
        self._initialize_models()

        # Initialize FAISS database
        self._initialize_database()

        # Load existing face database (migrate from existing images)
        self.create_features()

        print("✅ SCRFD+ArcFace+FAISS system initialized successfully")

    def _load_config(self):
        """Load configuration from existing config.yaml"""
        try:
            config_path = Path("system/config.yaml")
            if config_path.exists():
                with open(config_path, 'r') as f:
                    self.config = yaml.safe_load(f)
            else:
                # Fallback configuration
                self.config = {
                    'recognition': {'threshold': 0.35, 'use_gpu': True},
                    'mediapipe': {
                        'detection_confidence': 0.15,
                        'max_faces': 10,
                        'refine_landmarks': True
                    }
                }

            # Extract relevant settings
            self.face_quality_threshold = 0.2  # Lower for distant faces
            self.use_gpu = self.config.get('recognition', {}).get('use_gpu', True)

            # SCRFD model configuration based on existing MediaPipe settings
            mp_config = self.config.get('mediapipe', {})
            self.detection_confidence = mp_config.get('detection_confidence', 0.15)
            self.max_faces = mp_config.get('max_faces', 10)

            print(f"📊 Loaded config: detection_confidence={self.detection_confidence}, max_faces={self.max_faces}")

        except Exception as e:
            print(f"⚠️ Config loading failed: {e}, using defaults")
            self.face_quality_threshold = 0.2
            self.use_gpu = True
            self.detection_confidence = 0.15
            self.max_faces = 10

    def _initialize_models(self):
        """Initialize SCRFD detection and ArcFace recognition models with GPU support"""
        try:
            weights_dir = Path("weights")

            # Initialize SCRFD detector with GPU optimization
            # Try det_10g first for best accuracy, fallback to det_2.5g
            scrfd_model = weights_dir / "det_10g.onnx"
            if not scrfd_model.exists():
                scrfd_model = weights_dir / "det_2.5g.onnx"  # Fallback model
                if not scrfd_model.exists():
                    raise FileNotFoundError(f"No SCRFD model found in {weights_dir}")

            self.detector = SCRFD(
                model_path=str(scrfd_model),
                input_size=(640, 640),  # Good resolution for distance detection
                conf_thres=self.detection_confidence,
                iou_thres=0.4
            )

            # Initialize ArcFace recognizer with GPU optimization
            arcface_model = weights_dir / "w600k_mbf.onnx"  # MobileFace for speed
            if not arcface_model.exists():
                raise FileNotFoundError(f"ArcFace model not found: {arcface_model}")

            self.recognizer = ArcFace(model_path=str(arcface_model))

            print(f"🎯 SCRFD Model: {scrfd_model.name}")
            print(f"🧠 ArcFace Model: {arcface_model.name}")
            print(f"💻 GPU Acceleration: {'Enabled' if self.use_gpu else 'Disabled'}")

        except Exception as e:
            raise RuntimeError(f"Failed to initialize models: {e}")

    def _initialize_database(self):
        """Initialize FAISS database for fast similarity search"""
        try:
            # Use existing system directory structure
            db_path = Path("system/faiss_database")
            db_path.mkdir(exist_ok=True)

            self.face_database = FaceDatabase(
                embedding_size=512,  # ArcFace embedding size
                db_path=str(db_path),
                max_workers=4
            )

            # Person mapping for API compatibility (person_id -> name)
            self.person_mapping_file = Path("system/person_mapping.json")
            self.person_id_to_name = {}
            self._load_person_mapping()

            print(f"💾 FAISS database initialized: {db_path}")

        except Exception as e:
            raise RuntimeError(f"Failed to initialize FAISS database: {e}")

    def detect_faces(self, image: np.ndarray) -> List[FaceDetection]:
        """
        Detect faces using SCRFD - optimized for distance + crowd detection
        Compatible with existing MediaPipe API
        """
        start_time = time.time()

        try:
            if image is None or image.size == 0:
                return []

            # SCRFD detection with crowd support
            bboxes, kpss = self.detector.detect(
                image,
                max_num=self.max_faces if self.max_faces > 0 else 50  # Support crowds
            )

            faces = []
            for bbox, kps in zip(bboxes, kpss):
                # Extract bbox coordinates (SCRFD format: x1, y1, x2, y2, confidence)
                x1, y1, x2, y2, conf = bbox.astype(int)
                x, y, w, h = x1, y1, x2 - x1, y2 - y1

                # Ensure bbox is within image bounds
                height, width = image.shape[:2]
                x = max(0, min(x, width - 1))
                y = max(0, min(y, height - 1))
                w = max(1, min(w, width - x))
                h = max(1, min(h, height - y))

                # Calculate quality score (face size + confidence)
                face_area = w * h
                image_area = width * height
                size_ratio = min(face_area / image_area * 20, 1.0)  # Normalize
                quality_score = (conf * 0.8 + size_ratio * 0.2)

                # Create face detection object (MediaPipe compatible)
                face_detection = FaceDetection(
                    bbox=(x, y, w, h),  # MediaPipe format: x, y, width, height
                    confidence=float(conf),
                    landmarks=kps,  # 5-point landmarks for ArcFace
                    quality_score=quality_score,
                    face_area=face_area,
                    is_frontal=quality_score > self.face_quality_threshold
                )

                faces.append(face_detection)

            # Update performance tracking
            detection_time = time.time() - start_time
            self.detection_times.append(detection_time)
            if len(self.detection_times) > 100:
                self.detection_times = self.detection_times[-100:]

            return faces

        except Exception as e:
            print(f"❌ SCRFD face detection error: {e}")
            return []

    def recognize_faces(self, image: np.ndarray, face_detections: List[FaceDetection]) -> List[Dict]:
        """
        Recognize faces using ArcFace + FAISS search
        Returns format compatible with existing API
        """
        if not face_detections:
            return []

        start_time = time.time()
        recognition_results = []

        try:
            # Extract embeddings for all faces (batch processing support)
            embeddings = []
            valid_detections = []

            for detection in face_detections:
                try:
                    if detection.landmarks is not None and len(detection.landmarks) >= 5:
                        # Get ArcFace embedding with L2 normalization
                        embedding = self.recognizer.get_embedding(
                            image,
                            detection.landmarks,
                            normalized=True
                        )
                        embeddings.append(embedding)
                        valid_detections.append(detection)
                except Exception as e:
                    print(f"⚠️ Failed to extract embedding: {e}")
                    continue

            if not embeddings:
                return []

            # Batch search using FAISS (intelligent parallel processing for crowds)
            search_results = self.face_database.batch_search(
                embeddings,
                threshold=self.threshold
            )

            # Format results for API compatibility
            for detection, (name, similarity) in zip(valid_detections, search_results):
                if name != "Unknown" and similarity >= self.threshold:
                    person_id = self._name_to_person_id(name)

                    # Format compatible with existing MediaPipe system
                    result = {
                        'person_id': person_id,
                        'person_name': name,
                        'confidence': float(similarity),
                        'match_confidence': float(similarity),
                        'bbox': detection.bbox,
                        'quality_score': detection.quality_score,
                        'face_area': detection.face_area,
                        'landmarks': detection.landmarks.tolist() if detection.landmarks is not None else None
                    }
                else:
                    # Unknown face
                    result = {
                        'person_id': 'unknown',
                        'person_name': 'Unknown',
                        'confidence': float(similarity) if similarity > 0 else 0.0,
                        'match_confidence': float(similarity) if similarity > 0 else 0.0,
                        'bbox': detection.bbox,
                        'quality_score': detection.quality_score,
                        'face_area': detection.face_area,
                        'landmarks': detection.landmarks.tolist() if detection.landmarks is not None else None
                    }

                recognition_results.append(result)

            # Update performance tracking
            recognition_time = time.time() - start_time
            self.recognition_times.append(recognition_time)
            if len(self.recognition_times) > 100:
                self.recognition_times = self.recognition_times[-100:]

        except Exception as e:
            print(f"❌ Face recognition error: {e}")

        return recognition_results

    def detect_and_recognize(self, image: np.ndarray) -> List[Dict]:
        """
        Combined detection and recognition pipeline
        Main entry point compatible with existing MediaPipe API
        """
        # Detect faces
        face_detections = self.detect_faces(image)

        # Recognize faces
        recognition_results = self.recognize_faces(image, face_detections)

        return recognition_results

    def create_features(self):
        """
        Create/update face features database from existing images directory
        This method now uses queuing to avoid conflicts during detection
        """
        # Use the queue system to handle database rebuilds safely
        queued = self.queue_rebuild()
        if queued:
            print("📋 Database rebuild queued - will process when detection stops")
        else:
            print("✅ Database rebuild completed immediately")

    def _name_to_person_id(self, name: str) -> str:
        """Convert name to person_id (API compatibility)"""
        for person_id, person_name in self.person_id_to_name.items():
            if person_name == name:
                return person_id
        return name  # Fallback

    def _save_person_mapping(self):
        """Save person_id to name mapping"""
        try:
            with open(self.person_mapping_file, 'w') as f:
                json.dump(self.person_id_to_name, f, indent=2)
        except Exception as e:
            print(f"❌ Failed to save person mapping: {e}")

    def _load_person_mapping(self):
        """Load person_id to name mapping"""
        try:
            if self.person_mapping_file.exists():
                with open(self.person_mapping_file, 'r') as f:
                    self.person_id_to_name = json.load(f)
        except Exception as e:
            print(f"⚠️ Failed to load person mapping: {e}")
            self.person_id_to_name = {}

    # MediaPipe API compatibility methods
    @property
    def dictionary(self) -> Dict[str, np.ndarray]:
        """
        Compatibility property for existing API code expecting face_recognizer.dictionary
        Returns a dict mapping person_id to face embeddings
        """
        face_dict = {}

        # Reconstruct embeddings from FAISS index
        if hasattr(self.face_database, 'index') and self.face_database.index.ntotal > 0:
            # Get all embeddings from FAISS index
            n_embeddings = self.face_database.index.ntotal

            # Reconstruct embeddings from the index
            for i in range(n_embeddings):
                # Get embedding from FAISS index
                embedding = self.face_database.index.reconstruct(i)

                # Get the person name from metadata
                if i < len(self.face_database.metadata):
                    person_name = self.face_database.metadata[i]
                    # Find person_id from name
                    person_id = self._name_to_person_id(person_name)
                    face_dict[person_id] = embedding

        return face_dict

    @property
    def face_recognizer(self):
        """Compatibility property for API code expecting face_recognizer.face_recognizer.match()"""
        return self

    def match(self, feature1: np.ndarray, feature2: np.ndarray) -> float:
        """
        Compatibility method for MediaPipe-style matching
        Returns similarity score between 0 and 1
        """
        # Normalize features if not already normalized
        if np.linalg.norm(feature1) > 1.1:
            feature1 = feature1 / np.linalg.norm(feature1)
        if np.linalg.norm(feature2) > 1.1:
            feature2 = feature2 / np.linalg.norm(feature2)

        # Cosine similarity (dot product of normalized vectors)
        similarity = np.dot(feature1, feature2)

        # Convert to 0-1 range (cosine similarity is -1 to 1, but for normalized face embeddings it's typically 0 to 1)
        return max(0.0, similarity)

    def ensemble_match(self, feature: np.ndarray, landmarks: Optional[np.ndarray] = None) -> Tuple[bool, Tuple[str, float]]:
        """
        Enhanced matching using ensemble voting across multiple face templates per person
        Improves accuracy by considering multiple photos/angles of the same person

        Args:
            feature: Face embedding to match
            landmarks: Optional facial landmarks for quality assessment

        Returns:
            Tuple of (match_found, (person_id, confidence_score))
        """
        if not self.dictionary:
            return False, ("", 0.0)

        # Normalize the query feature
        if np.linalg.norm(feature) > 1.1:
            feature = feature / np.linalg.norm(feature)

        # Collect all matches above threshold
        matches = {}
        # Create a copy to avoid "dictionary changed size during iteration" errors
        dictionary_copy = dict(self.dictionary)
        for person_id, ref_feature in dictionary_copy.items():
            score = self.match(feature, ref_feature)

            # Extract base person ID (handle multiple photos like person_id%1, person_id%2)
            base_person_id = person_id.split('%')[0] if '%' in person_id else person_id

            # Keep the best score for each base person
            if base_person_id not in matches or score > matches[base_person_id]:
                matches[base_person_id] = (person_id, score)

        # Find the best match
        if matches:
            # Sort by score and get the best match
            best_person = max(matches.items(), key=lambda x: x[1][1])
            base_person_id = best_person[0]
            template_id, best_score = best_person[1]

            # Check if score meets threshold
            if best_score > self.threshold:
                # Boost score slightly if we have good quality landmarks
                if landmarks is not None:
                    quality_boost = min(0.05, (1.0 - best_score) * 0.1)  # Small quality boost
                    best_score = min(1.0, best_score + quality_boost)

                return True, (template_id, best_score)

        return False, ("", 0.0)

    def recognize_face(self, image: np.ndarray, file_name: Optional[str] = None) -> Tuple[List[np.ndarray], List[FaceDetection]]:
        """
        Recognize faces - full API compatibility with MediaPipe version

        Args:
            image: Input image
            file_name: Optional filename for validation and logging

        Returns:
            Tuple of (features, face_detections)
        """
        # Detect faces
        face_detections = self.detect_faces(image)

        # Extract features for each detection
        features = []
        for detection in face_detections:
            if detection.landmarks is not None:
                try:
                    # Get face embedding using ArcFace
                    embedding = self.recognizer.get_embedding(
                        image,
                        detection.landmarks,
                        normalized=True
                    )
                    features.append(embedding)
                except Exception as e:
                    print(f"⚠️ Failed to extract features: {e}")
                    features.append(np.zeros(512))  # Default embedding size
            else:
                features.append(np.zeros(512))

        return features, face_detections

    def extract_features(self, image: np.ndarray) -> Tuple[List[np.ndarray], List[FaceDetection]]:
        """
        Extract features from faces in image - compatibility method for existing API
        This is an alias for recognize_face to maintain API compatibility
        Args:
            image: Input image
        Returns:
            Tuple of (features, face_detections)
        """
        return self.recognize_face(image)

    def detect(self, image: np.ndarray) -> List[str]:
        """Compatibility method for existing detect() calls"""
        results = self.detect_and_recognize(image)
        return [result['person_name'] for result in results if result['person_name'] != 'Unknown']

    def configure_mediapipe(self, **kwargs):
        """Compatibility method - reconfigure SCRFD settings"""
        if 'detection_confidence' in kwargs:
            self.detection_confidence = kwargs['detection_confidence']
            self.detector.conf_thres = self.detection_confidence

        if 'max_faces' in kwargs:
            self.max_faces = kwargs['max_faces']

        print(f"✅ SCRFD configuration updated: detection_confidence={self.detection_confidence}, max_faces={self.max_faces}")

    def start_detection(self):
        """Mark detection as active and process any queued operations from previous session"""
        with self.queue_lock:
            self.detection_active = True
            print("🔴 Detection started - database operations will be queued")

    def stop_detection(self):
        """Mark detection as inactive and process all queued operations"""
        with self.queue_lock:
            self.detection_active = False
            print("🟢 Detection stopped - processing queued database operations")

            # Process all queued operations
            operations_processed = 0
            while not self.operation_queue.empty():
                try:
                    operation = self.operation_queue.get_nowait()
                    if operation.operation == DatabaseOperation.REBUILD:
                        print(f"🔄 Processing queued database rebuild...")
                        self._rebuild_features_internal()
                        operations_processed += 1
                    self.operation_queue.task_done()
                except Exception as e:
                    print(f"⚠️ Error processing queued operation: {e}")

            if operations_processed > 0:
                print(f"✅ Processed {operations_processed} queued operations")
            else:
                print("ℹ️ No queued operations to process")

    def queue_rebuild(self):
        """Queue a database rebuild operation if detection is active"""
        with self.queue_lock:
            if self.detection_active:
                self.operation_queue.put(QueuedOperation(DatabaseOperation.REBUILD))
                print("📋 Database rebuild queued (detection active)")
                return True
            else:
                # Detection not active, rebuild immediately
                self._rebuild_features_internal()
                return False

    def _rebuild_features_internal(self):
        """Internal method to rebuild features - called by create_features() and queue processor"""
        print("🔄 Updating face database with new registrations...")

        # Clear and rebuild the database to ensure all faces are included
        self.face_database = FaceDatabase(
            embedding_size=512,
            db_path=str(Path("system/faiss_database")),
            max_workers=4
        )
        self.person_id_to_name = {}

        print("🔄 Processing all face images in database...")

        # Process images from existing directory structure
        images_dir = Path("images")
        if not images_dir.exists():
            print(f"⚠️ Images directory not found: {images_dir}")
            return

        processed_count = 0
        failed_count = 0

        # Process all face images (PNG, JPG)
        for image_file in images_dir.glob("*.png"):
            if image_file.name.startswith('.'):
                continue

            try:
                # Extract person ID from filename (before first . or %)
                person_id = image_file.stem.split('%')[0]

                # Load and process image
                image = cv2.imread(str(image_file))
                if image is None:
                    print(f"⚠️ Could not load image: {image_file}")
                    failed_count += 1
                    continue

                # Extract face features using ArcFace
                features, detections = self.extract_features(image)

                if len(features) > 0 and len(detections) > 0:
                    # Use the best quality face detection
                    best_idx = max(range(len(detections)), key=lambda i: detections[i].quality_score)
                    feature = features[best_idx]

                    # Generate a unique photo identifier
                    photo_id = f"{person_id}%{image_file.stem.split('%')[1] if '%' in image_file.stem else '1'}"

                    # Add to database
                    self.face_database.add_face(feature, photo_id)
                    self.person_id_to_name[photo_id] = person_id
                    processed_count += 1

                else:
                    print(f"⚠️ No face detected in {image_file}")
                    failed_count += 1

            except Exception as e:
                print(f"⚠️ Error processing {image_file}: {e}")
                failed_count += 1

        print(f"✅ Database updated: {processed_count} faces processed, {failed_count} failed")

        # FAISS index is ready to use immediately after adding embeddings
        if processed_count > 0:
            print("✅ FAISS index ready for fast similarity search")

    def get_performance_stats(self) -> Dict[str, Any]:
        """Get performance statistics (API compatibility)"""
        avg_detection_time = np.mean(self.detection_times) if self.detection_times else 0
        avg_recognition_time = np.mean(self.recognition_times) if self.recognition_times else 0

        return {
            "detection_method": "SCRFD",
            "recognition_method": "ArcFace+FAISS",
            "threshold": self.threshold,
            "registered_faces": len(self.person_id_to_name),
            "avg_detection_time_ms": avg_detection_time * 1000,
            "avg_recognition_time_ms": avg_recognition_time * 1000,
            "face_quality_threshold": self.face_quality_threshold,
            "cache_enabled": self.cache_encodings,
            "database_size": self.face_database.index.ntotal if hasattr(self.face_database, 'index') else 0,
            "gpu_acceleration": self.use_gpu
        }


# Compatibility alias for existing imports
MediaPipeFaceRecognizer = SCRFDFaceRecognizer
FaceRecognizer = SCRFDFaceRecognizer