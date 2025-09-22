# Suppress MediaPipe warning messages - MUST be set before any imports
import os
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'  # Suppress all TensorFlow/MediaPipe logs
os.environ['GLOG_minloglevel'] = '3'      # Suppress Google logging (MediaPipe internal)
os.environ['GLOG_v'] = '0'                # Disable verbose logging
os.environ['GLOG_logtostderr'] = '0'      # Disable stderr logging

import cv2
import time
import numpy as np
import mediapipe as mp
from typing import Optional, Tuple, List, Dict
import pickle
import hashlib
from dataclasses import dataclass
from pathlib import Path
import logging

# Set logging levels after imports
logging.getLogger('mediapipe').setLevel(logging.ERROR)
logging.getLogger('tensorflow').setLevel(logging.ERROR)

@dataclass
class FaceDetection:
    """Face detection result with enhanced information"""
    bbox: Tuple[int, int, int, int]  # x, y, width, height
    confidence: float
    landmarks: Optional[np.ndarray] = None
    quality_score: float = 0.0
    face_area: int = 0
    is_frontal: bool = True

@dataclass
class FaceRecognitionResult:
    """Face recognition result"""
    person_id: str
    person_name: str
    confidence: float
    detection: FaceDetection

class MediaPipeFaceRecognizer:
    """
    Modern MediaPipe-based face recognition system with enhanced accuracy and performance.

    Features:
    - MediaPipe face detection and mesh for high accuracy
    - Face quality assessment for better matching
    - Modern face encoding techniques
    - Backward compatibility with existing photo dictionary
    - Performance monitoring and optimization
    """

    def __init__(self, thresold=0.5, draw=True, cache_encodings=True, include_landmarks=False):
        self.threshold = thresold
        self.draw = draw
        self.cache_encodings = cache_encodings
        self.include_landmarks = include_landmarks  # Option to include 468 landmarks in API response
        self.unknownmatch = 0

        # Performance tracking
        self.detection_times = []
        self.recognition_times = []

        # Initialize MediaPipe components (video-only mode)
        self.mp_face_mesh = mp.solutions.face_mesh
        self.mp_drawing = mp.solutions.drawing_utils

        # FaceMesh for video-optimized detection + landmarks
        self.face_mesh = self.mp_face_mesh.FaceMesh(
            static_image_mode=False,     # Always video mode for tracking optimization
            max_num_faces=20,            # Multiple people scenarios
            refine_landmarks=True,       # Full 468 landmarks for quality assessment
            min_detection_confidence=0.5,  # MediaPipe recommended
            min_tracking_confidence=0.7   # Higher for stable video tracking
        )

        # Video processing state (always active)
        self.frame_cache = {}
        self.face_tracking_data = {}
        self.last_processed_time = 0

        # Keep OpenCV recognizer for feature extraction
        weights_recognition = "model/face_recognizer_fast.onnx"
        self.face_recognizer = cv2.FaceRecognizerSF_create(weights_recognition, "")

        # Face encodings cache
        self.encodings_cache_file = "system/face_encodings_cache.pkl"
        self.dictionary = {}
        self.face_quality_threshold = 0.3

        print("✅ MediaPipe Face Recognition System initialized")
        print(f"🔧 Detection: MediaPipe | Recognition: OpenCV | Caching: {cache_encodings}")

        # Load MediaPipe configuration from config file if available
        self.load_config_settings()

        # Load existing face dictionary
        self.create_features()

    def load_config_settings(self):
        """Load MediaPipe video settings from config file"""
        try:
            from config_manager import config_manager
            mediapipe_config = config_manager.get_mediapipe_config()

            if mediapipe_config:
                print("📋 Loading MediaPipe video settings from config...")

                # Apply video-only configuration settings
                detection_confidence = mediapipe_config.get('detection_confidence', 0.5)
                tracking_confidence = mediapipe_config.get('tracking_confidence', 0.7)
                max_faces = mediapipe_config.get('max_faces', 20)
                refine_landmarks = mediapipe_config.get('refine_landmarks', True)
                unlimited_faces = mediapipe_config.get('unlimited_faces', False)

                self.configure_mediapipe(
                    detection_confidence=detection_confidence,
                    tracking_confidence=tracking_confidence,
                    max_faces=max_faces,
                    refine_landmarks=refine_landmarks,
                    unlimited_faces=unlimited_faces
                )

                print(f"✅ MediaPipe video mode configured: {max_faces} faces, confidence={detection_confidence}")

        except Exception as e:
            print(f"⚠️ Could not load MediaPipe config from file: {e}")
            print("📋 Using default MediaPipe video settings")

    def save_current_config(self):
        """Save current MediaPipe video settings to config file"""
        try:
            from config_manager import config_manager

            # Extract current video settings
            current_config = {
                'max_faces': getattr(self, '_current_max_faces', 20),
                'detection_confidence': getattr(self, '_current_detection_confidence', 0.5),
                'tracking_confidence': getattr(self, '_current_tracking_confidence', 0.7),
                'refine_landmarks': getattr(self, '_current_refine_landmarks', True),
                'unlimited_faces': getattr(self, '_current_unlimited_faces', False)
            }

            config_manager.set_mediapipe_config(**current_config)
            print("💾 MediaPipe video settings saved to config file")

        except Exception as e:
            print(f"❌ Failed to save MediaPipe config: {e}")

    def calculate_face_quality(self, image: np.ndarray, landmarks: np.ndarray) -> float:
        """
        Calculate face quality score based on:
        - Face size relative to image
        - Pose estimation (frontality)
        - Landmark confidence
        - Image sharpness
        """
        height, width = image.shape[:2]
        total_pixels = height * width

        # Calculate face area using landmarks
        if landmarks is not None and len(landmarks) > 0:
            x_coords = landmarks[:, 0] * width
            y_coords = landmarks[:, 1] * height

            face_width = np.max(x_coords) - np.min(x_coords)
            face_height = np.max(y_coords) - np.min(y_coords)
            face_area = face_width * face_height

            # Size score (larger faces are better, up to a point)
            size_ratio = face_area / total_pixels
            size_score = min(size_ratio * 10, 1.0)  # Cap at 1.0

            # Pose score (frontality check using specific landmarks)
            # Use nose tip (1), left eye (33), right eye (362)
            if len(landmarks) > 362:
                nose_tip = landmarks[1]
                left_eye = landmarks[33]
                right_eye = landmarks[362]

                # Calculate symmetry
                nose_x = nose_tip[0] * width
                left_eye_x = left_eye[0] * width
                right_eye_x = right_eye[0] * width

                # Ideal nose should be centered between eyes
                eye_center_x = (left_eye_x + right_eye_x) / 2
                nose_offset = abs(nose_x - eye_center_x)
                eye_distance = abs(right_eye_x - left_eye_x)

                if eye_distance > 0:
                    symmetry_ratio = 1.0 - min(nose_offset / eye_distance, 1.0)
                    pose_score = symmetry_ratio
                else:
                    pose_score = 0.5
            else:
                pose_score = 0.5

            # Sharpness score using Laplacian variance
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if len(image.shape) == 3 else image
            laplacian_var = cv2.Laplacian(gray, cv2.CV_64F).var()
            sharpness_score = min(laplacian_var / 1000, 1.0)  # Normalize

            # Combined quality score
            quality = (size_score * 0.4 + pose_score * 0.4 + sharpness_score * 0.2)
            return min(quality, 1.0)

        return 0.3  # Default for faces without landmarks


    def calculate_landmark_confidence(self, landmarks: np.ndarray) -> float:
        """Calculate confidence score from landmark consistency and geometry"""
        if landmarks is None or len(landmarks) < 468:
            return 0.5

        try:
            # Check landmark spread (more spread = more confident detection)
            x_coords = landmarks[:, 0]
            y_coords = landmarks[:, 1]
            z_coords = landmarks[:, 2]

            # Face should have good spread in x,y dimensions
            x_spread = np.max(x_coords) - np.min(x_coords)
            y_spread = np.max(y_coords) - np.min(y_coords)

            # Z-depth consistency (less variation = more frontal/stable)
            z_variation = np.std(z_coords)

            # Combine metrics for confidence score
            spread_score = min((x_spread + y_spread) * 2, 1.0)  # Normalize spread
            depth_score = max(0.3, 1.0 - z_variation * 10)     # Penalize high z variation

            confidence = (spread_score * 0.7 + depth_score * 0.3)
            return min(max(confidence, 0.1), 1.0)  # Clamp between 0.1 and 1.0

        except Exception:
            return 0.5

    def detect_faces(self, image: np.ndarray) -> List[FaceDetection]:
        """
        Video-optimized face detection with tracking and motion analysis
        Uses MediaPipe's video tracking capabilities for best performance
        """
        start_time = time.time()
        current_time = time.time()

        try:
            if image is None or image.size == 0:
                return []

            height, width = image.shape[:2]

            # Convert BGR to RGB for MediaPipe
            rgb_image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
            rgb_image.flags.writeable = False

            # Process with FaceMesh in video mode (automatic tracking)
            results = self.face_mesh.process(rgb_image)

            faces = []
            if results.multi_face_landmarks:
                for i, face_landmarks in enumerate(results.multi_face_landmarks):
                    landmarks = np.array([[lm.x, lm.y, lm.z] for lm in face_landmarks.landmark])

                    # Calculate bounding box from landmarks
                    x_coords = landmarks[:, 0] * width
                    y_coords = landmarks[:, 1] * height

                    x = max(0, int(np.min(x_coords)))
                    y = max(0, int(np.min(y_coords)))
                    w = min(int(np.max(x_coords) - x), width - x)
                    h = min(int(np.max(y_coords) - y), height - y)

                    if w <= 0 or h <= 0:
                        continue

                    # Enhanced quality assessment for video
                    quality_score = self.calculate_face_quality(image, landmarks)
                    confidence = self.calculate_landmark_confidence(landmarks)

                    # Motion analysis for video tracking
                    motion_score = self.analyze_face_motion(landmarks, i, current_time)

                    # Combine quality with motion stability
                    video_quality = (quality_score * 0.7 + motion_score * 0.3)

                    face_detection = FaceDetection(
                        bbox=(x, y, w, h),
                        confidence=confidence,
                        landmarks=landmarks,
                        quality_score=video_quality,
                        face_area=w * h,
                        is_frontal=video_quality > self.face_quality_threshold
                    )

                    faces.append(face_detection)

            # Update timing
            detection_time = time.time() - start_time
            self.detection_times.append(detection_time)
            self.last_processed_time = current_time

            if len(self.detection_times) > 100:
                self.detection_times = self.detection_times[-100:]

            return faces

        except Exception as e:
            print(f"❌ Video face detection error: {e}")
            return []

    def analyze_face_motion(self, landmarks: np.ndarray, face_id: int, current_time: float) -> float:
        """
        Analyze face motion between frames for stability assessment
        Higher score = more stable (better for recognition)
        """
        if landmarks is None or len(landmarks) < 468:
            return 0.5

        try:
            face_key = f"face_{face_id}"

            # Store current landmark positions
            if face_key not in self.face_tracking_data:
                self.face_tracking_data[face_key] = {
                    'last_landmarks': landmarks.copy(),
                    'last_time': current_time,
                    'motion_history': []
                }
                return 0.8  # New face, assume good quality

            prev_data = self.face_tracking_data[face_key]
            prev_landmarks = prev_data['last_landmarks']
            time_diff = current_time - prev_data['last_time']

            # Calculate motion between frames
            if time_diff > 0:
                # Use key facial points for motion calculation
                key_points = [1, 33, 362, 13, 14, 17]  # nose tip, eyes, chin points

                motion_distances = []
                for point_idx in key_points:
                    if point_idx < len(landmarks) and point_idx < len(prev_landmarks):
                        curr_point = landmarks[point_idx]
                        prev_point = prev_landmarks[point_idx]

                        # Calculate 2D distance (ignore z for motion)
                        distance = np.sqrt((curr_point[0] - prev_point[0])**2 +
                                         (curr_point[1] - prev_point[1])**2)
                        motion_distances.append(distance)

                if motion_distances:
                    avg_motion = np.mean(motion_distances)

                    # Motion score: lower motion = higher stability
                    # Normalize motion to 0-1 range (0.05 = significant motion threshold)
                    motion_score = max(0.1, 1.0 - (avg_motion / 0.05))

                    # Update tracking data
                    prev_data['motion_history'].append(motion_score)
                    if len(prev_data['motion_history']) > 10:
                        prev_data['motion_history'] = prev_data['motion_history'][-10:]

                    # Smooth motion score over recent history
                    smoothed_score = np.mean(prev_data['motion_history'])

                    # Update for next frame
                    prev_data['last_landmarks'] = landmarks.copy()
                    prev_data['last_time'] = current_time

                    return smoothed_score

            return 0.5

        except Exception as e:
            print(f"❌ Motion analysis error: {e}")
            return 0.5

    def extract_face_features(self, image: np.ndarray, face_detection: FaceDetection) -> Optional[np.ndarray]:
        """
        Extract face features using OpenCV recognizer with MediaPipe face alignment

        Key Points:
        - face_recognizer_fast.onnx expects 112x112 aligned face crops
        - MediaPipe provides high-quality landmarks for better alignment
        - Higher camera resolution → better landmark accuracy → better recognition
        """
        try:
            x, y, w, h = face_detection.bbox
            height, width = image.shape[:2]

            # face_recognizer_fast.onnx works optimally with:
            # - Face size: minimum 60x60 pixels (larger is better up to 300x300)
            # - Alignment: precise eye/nose/mouth positions from MediaPipe landmarks
            # - Input resolution: internally normalized to 112x112

            # Create a face array compatible with OpenCV format
            # Format: [x, y, w, h, right_eye_x, right_eye_y, left_eye_x, left_eye_y,
            #          nose_x, nose_y, right_mouth_x, right_mouth_y, left_mouth_x, left_mouth_y, confidence]
            face_array = np.array([x, y, w, h, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, face_detection.confidence], dtype=np.float32)

            # Enhanced landmark processing with MediaPipe's 468 points
            if face_detection.landmarks is not None and len(face_detection.landmarks) > 0:
                # MediaPipe landmark indices for face alignment (468-point model)
                # These indices are more precise than the 68-point model
                landmark_indices = {
                    'right_eye': 33,   # Right eye center
                    'left_eye': 362,   # Left eye center
                    'nose_tip': 1,     # Nose tip
                    'right_mouth': 61, # Right mouth corner
                    'left_mouth': 291  # Left mouth corner
                }

                landmarks_array = [
                    landmark_indices['right_eye'], landmark_indices['left_eye'],
                    landmark_indices['nose_tip'], landmark_indices['right_mouth'],
                    landmark_indices['left_mouth']
                ]

                for i, landmark_idx in enumerate(landmarks_array):
                    if landmark_idx < len(face_detection.landmarks):
                        landmark = face_detection.landmarks[landmark_idx]
                        # Convert normalized coordinates to absolute pixels
                        abs_x = landmark[0] * width
                        abs_y = landmark[1] * height

                        # Store in face_array for OpenCV recognizer
                        face_array[4 + i*2] = abs_x
                        face_array[5 + i*2] = abs_y

            # Extract features using OpenCV recognizer
            # This internally:
            # 1. Crops face using MediaPipe bounding box
            # 2. Aligns face using MediaPipe landmarks (much more precise than OpenCV's)
            # 3. Resizes to 112x112 for the neural network
            # 4. Extracts 512-dimensional feature vector
            aligned_face = self.face_recognizer.alignCrop(image, face_array)
            features = self.face_recognizer.feature(aligned_face)

            return features

        except Exception as e:
            print(f"❌ Feature extraction failed: {e}")
            return None

    def load_cached_encodings(self) -> bool:
        """Load cached face encodings if available"""
        if not self.cache_encodings or not os.path.exists(self.encodings_cache_file):
            return False

        try:
            with open(self.encodings_cache_file, 'rb') as f:
                cache_data = pickle.load(f)

            # Verify cache is still valid by checking image modification times
            current_hashes = self.get_image_hashes()
            cached_hashes = cache_data.get('image_hashes', {})

            if current_hashes == cached_hashes:
                self.dictionary = cache_data['encodings']
                print(f"✅ Loaded {len(self.dictionary)} cached face encodings")
                return True
            else:
                print("🔄 Image files changed, cache invalidated")
                return False

        except Exception as e:
            print(f"⚠️ Failed to load encoding cache: {e}")
            return False

    def save_cached_encodings(self):
        """Save face encodings to cache"""
        if not self.cache_encodings:
            return

        try:
            os.makedirs(os.path.dirname(self.encodings_cache_file), exist_ok=True)

            cache_data = {
                'encodings': self.dictionary,
                'image_hashes': self.get_image_hashes(),
                'created_at': time.time()
            }

            with open(self.encodings_cache_file, 'wb') as f:
                pickle.dump(cache_data, f)

            print(f"💾 Saved {len(self.dictionary)} face encodings to cache")

        except Exception as e:
            print(f"⚠️ Failed to save encoding cache: {e}")

    def get_image_hashes(self) -> Dict[str, str]:
        """Get MD5 hashes of all face images for cache validation"""
        hashes = {}
        images_dir = Path("images")

        if images_dir.exists():
            for image_file in images_dir.glob("*.png"):
                try:
                    with open(image_file, 'rb') as f:
                        content = f.read()
                        hashes[image_file.name] = hashlib.md5(content).hexdigest()
                except Exception:
                    continue

        return hashes

    def create_features(self):
        """Create face features dictionary with caching support"""
        # Try to load from cache first
        if self.load_cached_encodings():
            return

        print("🔄 Creating face encodings from images...")
        self.dictionary = {}

        script_dir = os.path.dirname(os.path.abspath(__file__))
        images_dir = os.path.join(script_dir, "images")

        if not os.path.exists(images_dir):
            print(f"Warning: Images directory not found at {images_dir}")
            return

        files = [f for f in os.listdir(images_dir) if f.lower().endswith(('.png', '.jpg', '.jpeg'))]
        processed_count = 0
        failed_count = 0

        for file in files:
            if file.startswith('.'):
                continue

            image_path = os.path.join(images_dir, file)
            image = cv2.imread(image_path)

            if image is None:
                print(f"Warning: Could not load image {file}")
                failed_count += 1
                continue

            # Detect faces using MediaPipe
            face_detections = self.detect_faces_mediapipe(image)

            if not face_detections:
                print(f"Warning: No face detected in {file}")
                failed_count += 1
                continue

            if len(face_detections) > 1:
                print(f"Warning: Multiple faces detected in {file}, using best quality face")
                # Use the face with highest quality score
                face_detections = [max(face_detections, key=lambda f: f.quality_score)]

            face_detection = face_detections[0]

            # Check face quality
            if face_detection.quality_score < self.face_quality_threshold:
                print(f"Warning: Low quality face in {file} (score: {face_detection.quality_score:.2f})")

            # Extract features
            features = self.extract_face_features(image, face_detection)

            if features is not None:
                user_id = os.path.splitext(file)[0]
                self.dictionary[user_id] = features
                processed_count += 1
                print(f"✅ Processed {file} (quality: {face_detection.quality_score:.2f})")
            else:
                print(f"❌ Failed to extract features from {file}")
                failed_count += 1

        print(f"🎯 Face encoding complete: {processed_count} successful, {failed_count} failed")

        # Save to cache
        if processed_count > 0:
            self.save_cached_encodings()

    def recognize_face(self, image: np.ndarray, file_name: Optional[str] = None) -> Tuple[List[np.ndarray], List[FaceDetection]]:
        """
        Recognize faces using video-optimized MediaPipe detection + OpenCV recognition
        Always uses video mode for maximum performance and tracking

        Args:
            image: Input image
            file_name: Optional filename for validation and logging

        Returns:
            features: List of face feature vectors
            face_detections: List of FaceDetection objects
        """
        if image is None:
            print(f"Error: Image is None for file {file_name}")
            return [], []

        # Normalize image format
        channels = 1 if len(image.shape) == 2 else image.shape[2]
        if channels == 1:
            image = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
        if channels == 4:
            image = cv2.cvtColor(image, cv2.COLOR_BGRA2BGR)

        # Resize large images for performance
        original_image = image.copy()
        if image.shape[0] > 1000:
            scale_factor = 500 / image.shape[0]
            image = cv2.resize(image, (0, 0), fx=scale_factor, fy=scale_factor)
        else:
            scale_factor = 1.0

        # Always use video-optimized detection
        face_detections = self.detect_faces(image)

        if file_name:
            print(f"🔍 MediaPipe detected {len(face_detections)} face(s) in {file_name}")

        # Validation for registration
        if file_name is not None:
            if not face_detections:
                raise AssertionError(f'No face detected in {file_name}')
            if len(face_detections) > 1:
                raise AssertionError(f'Multiple faces detected in {file_name}. Please use an image with only one face.')

        # Extract features for each detected face
        features = []
        valid_detections = []

        for detection in face_detections:
            # Scale detection back to original image size if we resized
            if scale_factor != 1.0:
                x, y, w, h = detection.bbox
                detection.bbox = (
                    int(x / scale_factor),
                    int(y / scale_factor),
                    int(w / scale_factor),
                    int(h / scale_factor)
                )

            # Extract features with caching for stable faces
            face_features = self.extract_face_features_cached(original_image, detection, True)

            if face_features is not None:
                features.append(face_features)
                valid_detections.append(detection)

        return features, valid_detections

    def extract_face_features_cached(self, image: np.ndarray, face_detection: FaceDetection, use_caching: bool = False) -> Optional[np.ndarray]:
        """
        Extract face features with optional caching for stable video faces
        """
        if not use_caching:
            return self.extract_face_features(image, face_detection)

        try:
            # Generate cache key from face position and quality
            x, y, w, h = face_detection.bbox
            cache_key = f"{x}_{y}_{w}_{h}_{face_detection.quality_score:.2f}"

            # Check if we have recent cached features for this stable face
            if cache_key in self.frame_cache:
                cache_entry = self.frame_cache[cache_key]
                current_time = time.time()

                # Use cached features if face is stable (within 1 second)
                if current_time - cache_entry['timestamp'] < 1.0:
                    return cache_entry['features']

            # Extract new features
            features = self.extract_face_features(image, face_detection)

            # Cache features for stable, high-quality faces
            if features is not None and face_detection.quality_score > 0.7:
                self.frame_cache[cache_key] = {
                    'features': features,
                    'timestamp': time.time()
                }

                # Clean old cache entries (keep last 20)
                if len(self.frame_cache) > 20:
                    oldest_key = min(self.frame_cache.keys(),
                                   key=lambda k: self.frame_cache[k]['timestamp'])
                    del self.frame_cache[oldest_key]

            return features

        except Exception as e:
            print(f"❌ Cached feature extraction error: {e}")
            return self.extract_face_features(image, face_detection)

    def match(self, feature1: np.ndarray) -> Tuple[bool, Tuple[str, float]]:
        """Match face feature against database using cosine similarity"""
        if not self.dictionary:
            return False, ("", 0.0)

        max_score = 0.0
        best_match_id = ""

        for user_id, feature2 in self.dictionary.items():
            try:
                score = self.face_recognizer.match(feature1, feature2, cv2.FaceRecognizerSF_FR_COSINE)
                if score > max_score:
                    max_score = score
                    best_match_id = user_id
            except Exception as e:
                print(f"❌ Matching error for {user_id}: {e}")
                continue

        if max_score >= self.threshold:
            return True, (best_match_id, max_score)
        else:
            return False, ("", max_score)

    def detect_glasses_from_landmarks(self, landmarks: np.ndarray) -> bool:
        """Detect if person is wearing glasses/sunglasses using landmark analysis"""
        if landmarks is None or len(landmarks) < 468:
            return False

        try:
            # Key landmark indices for eye region analysis
            left_eye_landmarks = [33, 7, 163, 144, 145, 153, 154, 155]
            right_eye_landmarks = [362, 382, 381, 380, 374, 373, 390, 249]

            # Calculate average landmark confidence/visibility in eye region
            eye_region_scores = []

            for idx in left_eye_landmarks + right_eye_landmarks:
                if idx < len(landmarks):
                    # Check z-depth and position consistency for occlusion detection
                    landmark = landmarks[idx]
                    # Higher z-values or unusual positioning may indicate glasses
                    eye_region_scores.append(abs(landmark[2]))  # z-depth analysis

            if eye_region_scores:
                avg_z_depth = np.mean(eye_region_scores)
                # Threshold for glasses detection (empirically determined)
                return avg_z_depth > 0.02  # Adjust threshold as needed

        except Exception as e:
            print(f"❌ Glasses detection error: {e}")

        return False

    def calculate_template_weight(self, template_index: int, has_glasses: bool = False) -> float:
        """Calculate weight for ensemble voting based on template type and context"""

        # Template type weights (assuming ordered storage)
        base_weights = {
            0: 1.0,    # no_accessories (front face, clear)
            1: 0.9,    # with_glasses (regular glasses)
            2: 0.7,    # with_sunglasses (heavily occluded)
            3: 0.8,    # profile_left (side view)
            4: 0.85,   # different_lighting
        }

        base_weight = base_weights.get(template_index, 0.8)

        # Context-aware weight adjustment
        if has_glasses:
            # Boost weight of templates with glasses when query has glasses
            if template_index == 1:  # with_glasses
                base_weight *= 1.3
            elif template_index == 2:  # with_sunglasses
                base_weight *= 1.4
            else:
                base_weight *= 0.8  # Reduce weight of templates without glasses

        return base_weight

    def calculate_agreement_bonus(self, scores: List[float]) -> float:
        """Calculate confidence bonus when multiple templates agree"""
        high_scores = [s for s in scores if s > self.threshold]

        if len(high_scores) >= 2:
            # Multiple templates agree - boost confidence
            agreement_strength = len(high_scores) / len(scores)
            return 0.1 * agreement_strength  # Up to 10% bonus

        return 0.0

    def ensemble_match(self, query_feature: np.ndarray, query_landmarks: np.ndarray = None) -> Tuple[bool, Tuple[str, float]]:
        """Enhanced matching with ensemble voting for multiple templates per person"""
        if not self.dictionary:
            return False, ("", 0.0)

        # Detect context clues from query
        has_glasses = False
        if query_landmarks is not None:
            has_glasses = self.detect_glasses_from_landmarks(query_landmarks)

        max_ensemble_score = 0.0
        best_match_id = ""

        # Group templates by person (assuming naming convention: person_id%template_type)
        person_templates = {}
        for user_id, feature in self.dictionary.items():
            if '%' in user_id:
                person_id, template_type = user_id.split('%', 1)
            else:
                person_id, template_type = user_id, "main"

            if person_id not in person_templates:
                person_templates[person_id] = []
            person_templates[person_id].append((feature, template_type, user_id))

        # Calculate ensemble scores for each person
        for person_id, templates in person_templates.items():
            if len(templates) == 1:
                # Single template - use standard matching
                feature, _, user_id = templates[0]
                score = self.face_recognizer.match(query_feature, feature, cv2.FaceRecognizerSF_FR_COSINE)
            else:
                # Multiple templates - use ensemble voting
                scores = []
                weights = []

                for i, (feature, template_type, user_id) in enumerate(templates):
                    score = self.face_recognizer.match(query_feature, feature, cv2.FaceRecognizerSF_FR_COSINE)
                    weight = self.calculate_template_weight(i, has_glasses)

                    scores.append(score)
                    weights.append(weight)

                # Calculate weighted ensemble score
                if weights:
                    weighted_score = np.average(scores, weights=weights)
                    agreement_bonus = self.calculate_agreement_bonus(scores)
                    score = weighted_score + agreement_bonus
                else:
                    score = max(scores) if scores else 0.0

            # Track best match across all persons
            if score > max_ensemble_score:
                max_ensemble_score = score
                best_match_id = person_id

        if max_ensemble_score >= self.threshold:
            return True, (best_match_id, max_ensemble_score)
        else:
            return False, ("", max_ensemble_score)

    def detect(self, image: np.ndarray) -> List[str]:
        """Detect and recognize faces with drawing overlays using video-optimized processing"""
        features, face_detections = self.recognize_face(image)
        id_name_list = []

        for feature, detection in zip(features, face_detections):
            result, (user_id, score) = self.match(feature)

            x, y, w, h = detection.bbox
            color = (0, 255, 0) if result else (0, 0, 255)
            thickness = 2

            # Draw bounding box
            cv2.rectangle(image, (x, y), (x + w, y + h), color, thickness, cv2.LINE_AA)

            # Draw quality indicator (includes motion stability)
            quality_color = (0, 255, 0) if detection.quality_score > self.face_quality_threshold else (0, 255, 255)
            cv2.circle(image, (x + w - 10, y + 10), 5, quality_color, -1)

            if result and self.draw:
                # Draw label background
                label = user_id.split('%')[-1]
                cv2.rectangle(image, (x, y - 25), (x + 200, y), (0, 0, 0), -1, cv2.LINE_AA)
                # Draw label text with confidence
                cv2.putText(image, f"{label} ({score:.2f})", (x, y - 5),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2, cv2.LINE_AA)

            id_name_list.append(user_id if result else "Unknown")

        return id_name_list

    def detect_for_capture(self, image: np.ndarray) -> bool:
        """Face detection for capture mode with video-optimized quality assessment"""
        h, w = image.shape[:2]
        x1, y1, x2, y2 = int(w/2) - 200, int(h/2) - 150, int(w/2) + 200, int(h/2) + 150

        # Draw capture frame
        cv2.rectangle(image, (x1, y1 - 35), (x2, y1), (0, 0, 0), -1, cv2.LINE_AA)
        cv2.putText(image, "Keep Face Inside Box", (x1, y1 - 10),
                   cv2.FONT_HERSHEY_COMPLEX_SMALL, 1.5, (255, 255, 255), 1, cv2.LINE_AA)
        cv2.rectangle(image, (x1, y1), (x2, y2), (0, 255, 255), 4, cv2.LINE_AA)

        # Detect faces using video-optimized detection
        _, face_detections = self.recognize_face(image)

        for detection in face_detections:
            x, y, w, h = detection.bbox

            # Check if face is within capture frame and has good quality (includes motion stability)
            if (x > x1 and y > y1 and x + w < x2 and y + h < y2 and
                detection.quality_score > self.face_quality_threshold):

                cv2.rectangle(image, (x1, y1), (x2, y2), (0, 255, 0), 4, cv2.LINE_AA)
                cv2.rectangle(image, (0, 0), (w, 80), (0, 0, 0), -1, cv2.LINE_AA)

                quality_text = f"Quality: {detection.quality_score:.2f}"
                cv2.putText(image, "You can capture Now", (10, 30),
                           cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 0), 2, cv2.LINE_AA)
                cv2.putText(image, quality_text, (10, 60),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2, cv2.LINE_AA)
                return True

        return False

    def configure_mediapipe(self,
                            detection_confidence: float = None,
                            tracking_confidence: float = None,
                            max_faces: int = None,
                            refine_landmarks: bool = None,
                            unlimited_faces: bool = False,
                            include_landmarks: bool = None):
        """
        Reconfigure MediaPipe video settings at runtime

        Args:
            detection_confidence: 0.0-1.0, lower = more faces detected
            tracking_confidence: 0.0-1.0, higher = smoother tracking
            max_faces: Maximum number of faces to detect (1-50, or unlimited)
            refine_landmarks: True for 468 landmarks, False for 68
            unlimited_faces: True to remove face detection limits (use with caution)
            include_landmarks: True to include all 468 landmarks in API responses

        Performance Guidelines:
        - Camera Resolution vs Face Count:
          * 640x480: up to 10 faces efficiently
          * 1280x720: up to 20 faces efficiently
          * 1920x1080: up to 30 faces efficiently
          * 4K: up to 50+ faces (high-end hardware)
        """
        try:
            # Update face mesh video configuration
            if any(param is not None for param in [detection_confidence, tracking_confidence, max_faces, refine_landmarks, unlimited_faces]):
                # Handle unlimited faces option
                if unlimited_faces:
                    current_max_faces = 100  # Practical limit for MediaPipe
                    print("⚠️ UNLIMITED FACES MODE: High performance impact!")
                    print("💡 Recommended only for crowd analysis with powerful hardware")
                else:
                    current_max_faces = max_faces if max_faces is not None else 20

                current_refine = refine_landmarks if refine_landmarks is not None else True
                current_detection = detection_confidence if detection_confidence is not None else 0.5
                current_tracking = tracking_confidence if tracking_confidence is not None else 0.7

                # Validate settings
                if current_max_faces > 50 and not unlimited_faces:
                    print("⚠️ Warning: >50 faces may impact performance. Consider unlimited_faces=True for crowd scenarios")

                # Always use video mode
                self.face_mesh = self.mp_face_mesh.FaceMesh(
                    static_image_mode=False,  # Always video mode
                    max_num_faces=current_max_faces,
                    refine_landmarks=current_refine,
                    min_detection_confidence=current_detection,
                    min_tracking_confidence=current_tracking
                )

                performance_level = "HIGH IMPACT" if current_max_faces > 30 else "MODERATE" if current_max_faces > 10 else "LOW"
                print(f"✅ Updated video face mesh: max_faces={current_max_faces}, refine={current_refine}")
                print(f"📊 Performance impact: {performance_level}")

            # Update landmark inclusion setting
            if include_landmarks is not None:
                self.include_landmarks = include_landmarks
                status = "ENABLED" if include_landmarks else "DISABLED"
                print(f"📍 Landmark visualization: {status} ({468 if include_landmarks else 0} points)")

        except Exception as e:
            print(f"❌ MediaPipe configuration error: {e}")


    def get_performance_stats(self) -> Dict:
        """Get performance statistics"""
        avg_detection_time = np.mean(self.detection_times) if self.detection_times else 0
        avg_recognition_time = np.mean(self.recognition_times) if self.recognition_times else 0

        return {
            "detection_method": "MediaPipe",
            "recognition_method": "OpenCV",
            "registered_faces": len(self.dictionary),
            "threshold": self.threshold,
            "avg_detection_time_ms": avg_detection_time * 1000,
            "avg_recognition_time_ms": avg_recognition_time * 1000,
            "face_quality_threshold": self.face_quality_threshold,
            "cache_enabled": self.cache_encodings
        }

    def invalidate_cache(self):
        """Invalidate and remove face encoding cache"""
        if os.path.exists(self.encodings_cache_file):
            os.remove(self.encodings_cache_file)
            print("🗑️ Face encoding cache invalidated")

    def reset_video_tracking(self):
        """Reset video tracking data (call when switching contexts)"""
        self.face_tracking_data.clear()
        self.frame_cache.clear()
        self.last_processed_time = 0
        print("🔄 Video tracking data reset")

    def get_video_performance_stats(self) -> Dict:
        """Get enhanced performance statistics including video tracking"""
        base_stats = self.get_performance_stats()

        video_stats = {
            "tracked_faces": len(self.face_tracking_data),
            "cached_features": len(self.frame_cache),
            "processing_mode": "Video-Optimized"
        }

        return {**base_stats, **video_stats}


# For backward compatibility
FaceRecognizer = MediaPipeFaceRecognizer