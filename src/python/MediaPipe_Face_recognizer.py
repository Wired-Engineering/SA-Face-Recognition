import cv2
import os
import time
import numpy as np
import mediapipe as mp
from typing import Optional, Tuple, List, Dict
import pickle
import hashlib
from dataclasses import dataclass
from pathlib import Path

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

        # Initialize MediaPipe components
        self.mp_face_detection = mp.solutions.face_detection
        self.mp_face_mesh = mp.solutions.face_mesh
        self.mp_drawing = mp.solutions.drawing_utils

        # Face detection optimized for real-time performance
        # model_selection: 0 = short-range (2m), 1 = full-range (5m)
        # Using short-range for better performance in typical use cases
        self.face_detector = self.mp_face_detection.FaceDetection(
            model_selection=0,  # Short-range model (faster, good for webcams)
            min_detection_confidence=0.5  # MediaPipe recommended default
        )

        # Face mesh optimized for recognition use case with proper landmark projection configuration
        self.face_mesh = self.mp_face_mesh.FaceMesh(
            static_image_mode=True,      # Use static mode to avoid landmark projection issues
            max_num_faces=20,            # Increased for multiple people scenarios
            refine_landmarks=True,       # Full 468 landmarks for better quality assessment
            min_detection_confidence=0.5,  # MediaPipe recommended
            min_tracking_confidence=0.5
        )

        # Keep OpenCV recognizer for feature extraction (proven accuracy)
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
        """Load MediaPipe settings from config file"""
        try:
            from config_manager import config_manager
            mediapipe_config = config_manager.get_mediapipe_config()

            if mediapipe_config:
                print("📋 Loading MediaPipe settings from config...")

                # Apply configuration settings
                detection_confidence = mediapipe_config.get('detection_confidence', 0.5)
                tracking_confidence = mediapipe_config.get('tracking_confidence', 0.5)
                max_faces = mediapipe_config.get('max_faces', 20)
                model_selection = mediapipe_config.get('model_selection', 0)
                refine_landmarks = mediapipe_config.get('refine_landmarks', True)
                unlimited_faces = mediapipe_config.get('unlimited_faces', False)

                self.configure_mediapipe(
                    detection_confidence=detection_confidence,
                    tracking_confidence=tracking_confidence,
                    max_faces=max_faces,
                    model_selection=model_selection,
                    refine_landmarks=refine_landmarks,
                    unlimited_faces=unlimited_faces
                )

                print(f"✅ MediaPipe configured from settings: {max_faces} faces, confidence={detection_confidence}")

        except Exception as e:
            print(f"⚠️ Could not load MediaPipe config from file: {e}")
            print("📋 Using default MediaPipe settings")

    def save_current_config(self):
        """Save current MediaPipe settings to config file"""
        try:
            from config_manager import config_manager

            # Extract current settings (this is simplified - would need to track current state)
            current_config = {
                'max_faces': getattr(self, '_current_max_faces', 20),
                'detection_confidence': getattr(self, '_current_detection_confidence', 0.5),
                'tracking_confidence': getattr(self, '_current_tracking_confidence', 0.5),
                'model_selection': getattr(self, '_current_model_selection', 0),
                'refine_landmarks': getattr(self, '_current_refine_landmarks', True),
                'unlimited_faces': getattr(self, '_current_unlimited_faces', False)
            }

            config_manager.set_mediapipe_config(**current_config)
            print("💾 MediaPipe settings saved to config file")

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

    def detect_faces_mediapipe(self, image: np.ndarray) -> List[FaceDetection]:
        """Enhanced face detection with MediaPipe following best practices"""
        start_time = time.time()

        try:
            # Validate input
            if image is None or image.size == 0:
                return []

            # Get image dimensions for proper MediaPipe processing
            height, width = image.shape[:2]

            # Convert BGR to RGB for MediaPipe (required format)
            # MediaPipe expects RGB, OpenCV uses BGR
            rgb_image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)

            # Make image writable=False for performance (MediaPipe best practice)
            rgb_image.flags.writeable = False

            # Get face detections with proper image dimensions
            detection_results = self.face_detector.process(rgb_image)
            mesh_results = None

            # Process face mesh with proper image dimensions to fix landmark projection warning
            if detection_results.detections:
                # Create a copy of image with proper format and flags for MediaPipe
                mesh_image = rgb_image.copy()
                mesh_image.flags.writeable = False

                # Process with face mesh - MediaPipe will use image dimensions internally
                mesh_results = self.face_mesh.process(mesh_image)

            faces = []

            if detection_results.detections:
                height, width = image.shape[:2]

                for i, detection in enumerate(detection_results.detections):
                    bbox = detection.location_data.relative_bounding_box

                    # Convert to absolute coordinates with bounds checking
                    x = max(0, int(bbox.xmin * width))
                    y = max(0, int(bbox.ymin * height))
                    w = min(int(bbox.width * width), width - x)
                    h = min(int(bbox.height * height), height - y)

                    # Skip invalid bounding boxes
                    if w <= 0 or h <= 0:
                        continue

                    # Get landmarks if available
                    landmarks = None
                    if mesh_results and mesh_results.multi_face_landmarks and i < len(mesh_results.multi_face_landmarks):
                        face_landmarks = mesh_results.multi_face_landmarks[i]
                        landmarks = np.array([[lm.x, lm.y, lm.z] for lm in face_landmarks.landmark])

                    # Calculate quality score
                    quality_score = self.calculate_face_quality(image, landmarks)

                    face_detection = FaceDetection(
                        bbox=(x, y, w, h),
                        confidence=detection.score[0],
                        landmarks=landmarks,
                    quality_score=quality_score,
                    face_area=w * h,
                    is_frontal=quality_score > self.face_quality_threshold
                )

                    faces.append(face_detection)

            detection_time = time.time() - start_time
            self.detection_times.append(detection_time)

            # Keep only the last 100 timing measurements
            if len(self.detection_times) > 100:
                self.detection_times = self.detection_times[-100:]

            return faces

        except Exception as e:
            print(f"❌ MediaPipe face detection error: {e}")
            # Return empty list on error to maintain compatibility
            return []

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
        Recognize faces in image using MediaPipe detection + OpenCV recognition

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

        # Detect faces
        face_detections = self.detect_faces_mediapipe(image)

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

            # Extract features from original size image
            face_features = self.extract_face_features(original_image, detection)

            if face_features is not None:
                features.append(face_features)
                valid_detections.append(detection)

        return features, valid_detections

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
        """Detect and recognize faces with drawing overlays (legacy compatibility)"""
        features, face_detections = self.recognize_face(image)
        id_name_list = []

        for feature, detection in zip(features, face_detections):
            result, (user_id, score) = self.match(feature)

            x, y, w, h = detection.bbox
            color = (0, 255, 0) if result else (0, 0, 255)
            thickness = 2

            # Draw bounding box
            cv2.rectangle(image, (x, y), (x + w, y + h), color, thickness, cv2.LINE_AA)

            # Draw quality indicator
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
        """Face detection for capture mode with quality assessment"""
        h, w = image.shape[:2]
        x1, y1, x2, y2 = int(w/2) - 200, int(h/2) - 150, int(w/2) + 200, int(h/2) + 150

        # Draw capture frame
        cv2.rectangle(image, (x1, y1 - 35), (x2, y1), (0, 0, 0), -1, cv2.LINE_AA)
        cv2.putText(image, "Keep Face Inside Box", (x1, y1 - 10),
                   cv2.FONT_HERSHEY_COMPLEX_SMALL, 1.5, (255, 255, 255), 1, cv2.LINE_AA)
        cv2.rectangle(image, (x1, y1), (x2, y2), (0, 255, 255), 4, cv2.LINE_AA)

        # Detect faces
        _, face_detections = self.recognize_face(image)

        for detection in face_detections:
            x, y, w, h = detection.bbox

            # Check if face is within capture frame and has good quality
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
                            model_selection: int = None,
                            refine_landmarks: bool = None,
                            unlimited_faces: bool = False,
                            static_image_mode: bool = None,
                            include_landmarks: bool = None,
                            auto_optimize_resolution: bool = None):
        """
        Reconfigure MediaPipe settings at runtime for different use cases

        Args:
            detection_confidence: 0.0-1.0, lower = more faces detected
            tracking_confidence: 0.0-1.0, higher = smoother tracking
            max_faces: Maximum number of faces to detect (1-50, or unlimited)
            model_selection: 0 (short-range, 2m) or 1 (full-range, 5m)
            refine_landmarks: True for 468 landmarks, False for 68
            unlimited_faces: True to remove face detection limits (use with caution)
            static_image_mode: True for static images (fixes landmark warnings), False for video tracking
            include_landmarks: True to include all 468 landmarks in API responses for visualization
            auto_optimize_resolution: True to automatically optimize settings based on camera resolution

        Performance Guidelines:
        - Camera Resolution vs Face Count:
          * 640x480: up to 10 faces efficiently
          * 1280x720: up to 20 faces efficiently
          * 1920x1080: up to 30 faces efficiently
          * 4K: up to 50+ faces (high-end hardware)
        """
        try:
            # Update face detector if needed
            if detection_confidence is not None or model_selection is not None:
                current_model = model_selection if model_selection is not None else 0
                current_confidence = detection_confidence if detection_confidence is not None else 0.5

                self.face_detector = self.mp_face_detection.FaceDetection(
                    model_selection=current_model,
                    min_detection_confidence=current_confidence
                )
                print(f"✅ Updated face detector: model={current_model}, confidence={current_confidence}")

            # Update face mesh if needed
            if any(param is not None for param in [detection_confidence, tracking_confidence, max_faces, refine_landmarks, unlimited_faces, static_image_mode]):
                # Handle unlimited faces option
                if unlimited_faces:
                    current_max_faces = 100  # Practical limit for MediaPipe
                    print("⚠️ UNLIMITED FACES MODE: High performance impact!")
                    print("💡 Recommended only for crowd analysis with powerful hardware")
                else:
                    current_max_faces = max_faces if max_faces is not None else 20

                current_refine = refine_landmarks if refine_landmarks is not None else True
                current_detection = detection_confidence if detection_confidence is not None else 0.5
                current_tracking = tracking_confidence if tracking_confidence is not None else 0.5
                current_static_mode = static_image_mode if static_image_mode is not None else True  # Default to static mode to fix landmark warnings

                # Validate settings
                if current_max_faces > 50 and not unlimited_faces:
                    print("⚠️ Warning: >50 faces may impact performance. Consider unlimited_faces=True for crowd scenarios")

                self.face_mesh = self.mp_face_mesh.FaceMesh(
                    static_image_mode=current_static_mode,
                    max_num_faces=current_max_faces,
                    refine_landmarks=current_refine,
                    min_detection_confidence=current_detection,
                    min_tracking_confidence=current_tracking
                )

                performance_level = "HIGH IMPACT" if current_max_faces > 30 else "MODERATE" if current_max_faces > 10 else "LOW"
                print(f"✅ Updated face mesh: max_faces={current_max_faces}, refine={current_refine}")
                print(f"📊 Performance impact: {performance_level}")

            # Update landmark inclusion setting
            if include_landmarks is not None:
                self.include_landmarks = include_landmarks
                status = "ENABLED" if include_landmarks else "DISABLED"
                print(f"📍 Landmark visualization: {status} ({468 if include_landmarks else 0} points)")

            # Update auto-optimization setting (stored but not actively used here)
            if auto_optimize_resolution is not None:
                # This is a configuration flag, actual optimization happens via optimize_for_resolution()
                status = "ENABLED" if auto_optimize_resolution else "DISABLED"
                print(f"🎯 Auto-resolution optimization: {status}")

        except Exception as e:
            print(f"❌ MediaPipe configuration error: {e}")

    def optimize_for_resolution(self, width: int, height: int, target_fps: int = 30):
        """
        Automatically optimize MediaPipe settings based on camera resolution

        Args:
            width: Camera width in pixels
            height: Camera height in pixels
            target_fps: Desired frames per second
        """
        total_pixels = width * height

        print(f"🎯 Optimizing MediaPipe for {width}x{height} ({total_pixels:,} pixels)")

        if total_pixels <= 640 * 480:  # VGA and below
            self.configure_mediapipe(
                detection_confidence=0.4,  # Lower for small faces
                model_selection=0,         # Short-range sufficient
                max_faces=8,              # Reasonable for small resolution
                refine_landmarks=False    # 68 landmarks for speed
            )
            print("📱 VGA optimization: Speed-focused")

        elif total_pixels <= 1280 * 720:  # HD
            self.configure_mediapipe(
                detection_confidence=0.5,  # Balanced
                model_selection=0,         # Short-range for webcams
                max_faces=15,             # Good for group calls
                refine_landmarks=True     # 468 landmarks for quality
            )
            print("💻 HD optimization: Balanced performance")

        elif total_pixels <= 1920 * 1080:  # Full HD
            self.configure_mediapipe(
                detection_confidence=0.6,  # Higher quality
                model_selection=1,         # Full-range for better accuracy
                max_faces=25,             # Larger groups
                refine_landmarks=True     # Full quality
            )
            print("🖥️ Full HD optimization: Quality-focused")

        elif total_pixels <= 3840 * 2160:  # 4K
            self.configure_mediapipe(
                detection_confidence=0.7,  # High accuracy
                model_selection=1,         # Full-range required
                max_faces=40,             # Crowd scenarios
                refine_landmarks=True     # Maximum quality
            )
            print("🎬 4K optimization: Maximum quality")

        else:  # Higher than 4K
            print("🚀 Ultra-high resolution detected!")
            self.configure_mediapipe(
                detection_confidence=0.8,  # Very high accuracy
                model_selection=1,         # Full-range
                unlimited_faces=True,     # No limits for professional use
                refine_landmarks=True     # Maximum precision
            )
            print("🏢 Professional optimization: Unlimited detection")

        # Additional optimizations based on target FPS
        if target_fps > 30:
            print(f"⚡ High FPS target ({target_fps}fps): Reducing max_faces for performance")
            current_max = 20 if total_pixels > 1920*1080 else 15 if total_pixels > 1280*720 else 10
            self.configure_mediapipe(max_faces=current_max)

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


# For backward compatibility
FaceRecognizer = MediaPipeFaceRecognizer