import cv2
import numpy as np
from logging import getLogger
from pathlib import Path
from typing import List, Optional

from face_utils.helpers import face_alignment
from models.onnx_utils import (
    create_optimized_session,
    check_batch_support,
    add_batch_axis
)

__all__ = ["ArcFace"]

logger = getLogger(__name__)


class ArcFace:
    """
    ArcFace Model for Face Recognition

    This class implements a face encoder using the ArcFace architecture,
    loading a pre-trained model from an ONNX file.
    """

    def __init__(
        self,
        model_path: str,
        batch_size: Optional[int] = None,
        enable_profiling: bool = False,
        warmup: bool = True
    ) -> None:
        """
        Initializes the ArcFace face encoder model with advanced ONNX features.

        Args:
            model_path (str): Path to ONNX model file.
            batch_size (int, optional): Max batch size for processing. None for dynamic batching.
            enable_profiling (bool): Enable ONNX Runtime profiling for performance analysis.
            warmup (bool): Warm up the model with dummy inputs.

        Raises:
            RuntimeError: If model initialization fails.
        """
        self.model_path = Path(model_path)
        self.batch_size = batch_size
        self.input_size = (112, 112)
        self.normalization_mean = 127.5
        self.normalization_scale = 127.5

        logger.info(f"Initializing ArcFace model from {self.model_path}")
        print(f"🧠 Initializing ArcFace with batch_size={batch_size}")

        try:
            # Create optimized session with advanced features
            self.session = create_optimized_session(
                str(self.model_path),
                enable_profiling=enable_profiling,
                graph_optimization_level=99,  # Maximum optimization
                enable_mem_pattern=True,
                enable_cpu_mem_arena=True
            )

            # Get model configuration
            input_config = self.session.get_inputs()[0]
            self.input_name = input_config.name

            input_shape = input_config.shape
            logger.info(f"Model input shape: {input_shape}")

            # Check if model supports batching
            self.supports_batching = check_batch_support(self.session)

            if not self.supports_batching and (batch_size is None or batch_size > 1):
                logger.info("Model doesn't support batching, attempting to add batch axis...")
                try:
                    # Backup original model
                    backup_path = self.model_path.parent / f"{self.model_path.stem}_original.onnx"
                    if not backup_path.exists():
                        import shutil
                        shutil.copy(self.model_path, backup_path)
                        logger.info(f"Original model backed up to {backup_path}")

                    # Add batch axis
                    add_batch_axis(self.model_path)

                    # Recreate session with updated model
                    self.session = create_optimized_session(
                        str(self.model_path),
                        enable_profiling=enable_profiling,
                        graph_optimization_level=99
                    )

                    self.supports_batching = True
                    logger.info("✓ Batch axis added successfully")
                    print("✓ Dynamic batching enabled for ArcFace")

                except Exception as e:
                    logger.warning(f"Could not add batch axis: {e}. Continuing without batching.")
                    self.batch_size = 1
                    print("⚠️ Batch processing disabled, using single-face mode")

            # Validate input size
            model_input_size = tuple(input_shape[2:4][::-1]) if len(input_shape) >= 4 else self.input_size
            if model_input_size != self.input_size:
                logger.warning(
                    f"Model input size {model_input_size} differs from configured size {self.input_size}"
                )

            # Get output configuration
            self.output_names = [o.name for o in self.session.get_outputs()]
            self.output_shape = self.session.get_outputs()[0].shape
            self.embedding_size = self.output_shape[1] if len(self.output_shape) > 1 else self.output_shape[0]

            assert len(self.output_names) == 1, "Expected only one output node."

            logger.info(
                f"Successfully initialized ArcFace encoder "
                f"(embedding size: {self.embedding_size}, batch support: {self.supports_batching})"
            )
            print(f"✅ ArcFace initialized (embedding_dim={self.embedding_size}, batching={self.supports_batching})")

            # Warm up the session
            if warmup:
                self._warmup()

        except Exception as e:
            logger.error(f"Failed to load ArcFace model from '{self.model_path}'", exc_info=True)
            raise RuntimeError(f"Failed to initialize model session for '{self.model_path}'") from e

    def _warmup(self, num_runs: int = 3):
        """Warm up the model with dummy inputs to initialize GPU kernels"""
        try:
            logger.info("Warming up ArcFace model...")
            dummy_face = np.random.randn(112, 112, 3).astype(np.uint8)
            for _ in range(num_runs):
                self.preprocess(dummy_face)
            logger.info("ArcFace warm-up complete")
        except Exception as e:
            logger.warning(f"Warm-up failed: {e}")

    def preprocess(self, face_image: np.ndarray) -> np.ndarray:
        """
        Preprocess the face image: resize, normalize, and convert to the required format.

        Args:
            face_image (np.ndarray): Input face image in BGR format.

        Returns:
            np.ndarray: Preprocessed image blob ready for inference.
        """
        resized_face = cv2.resize(face_image, self.input_size)

        if isinstance(self.normalization_scale, (list, tuple)):
            # Handle per-channel normalization
            rgb_face = cv2.cvtColor(resized_face, cv2.COLOR_BGR2RGB).astype(np.float32)

            mean_array = np.array(self.normalization_mean, dtype=np.float32)
            scale_array = np.array(self.normalization_scale, dtype=np.float32)
            normalized_face = (rgb_face - mean_array) / scale_array

            # Change to NCHW format (batch, channels, height, width)
            transposed_face = np.transpose(normalized_face, (2, 0, 1))
            face_blob = np.expand_dims(transposed_face, axis=0)
        else:
            # Single-value normalization using cv2.dnn
            face_blob = cv2.dnn.blobFromImage(
                resized_face,
                scalefactor=1.0 / self.normalization_scale,
                size=self.input_size,
                mean=(self.normalization_mean,)*3,
                swapRB=True
            )
        return face_blob

    def get_embedding(
        self,
        image: np.ndarray,
        landmarks: np.ndarray,
        normalized: bool = False
    ) -> np.ndarray:
        """
        Extract face embedding from an image using facial landmarks for alignment.

        Args:
            image (np.ndarray): Input image in BGR format.
            landmarks (np.ndarray): 5-point facial landmarks for alignment.
            normalized (bool): Normalize output vector embedding. Defaults to False.

        Returns:
            np.ndarray: Face embedding vector.

        Raises:
            ValueError: If inputs are invalid.
        """
        if image is None or landmarks is None:
            raise ValueError("Image and landmarks must not be None")

        try:
            aligned_face, _ = face_alignment(image, landmarks)
            face_blob = self.preprocess(aligned_face)
            embedding = self.session.run(self.output_names, {self.input_name: face_blob})[0]

            if normalized:
                # L2 normalization of embedding
                norm = np.linalg.norm(embedding, axis=1, keepdims=True)
                normalized_embedding = embedding / norm
                return normalized_embedding.flatten()

            return embedding.flatten()

        except Exception as e:
            logger.error(f"Error extracting face embedding: {e}")
            raise

    def get_embeddings_batch(
        self,
        image: np.ndarray,
        landmarks_list: List[np.ndarray],
        normalized: bool = False
    ) -> List[np.ndarray]:
        """
        Extract face embeddings for multiple faces in batch mode (when supported).
        Falls back to sequential processing if batching is not supported.

        Args:
            image (np.ndarray): Input image in BGR format.
            landmarks_list (List[np.ndarray]): List of 5-point facial landmarks.
            normalized (bool): Normalize output vector embeddings. Defaults to False.

        Returns:
            List[np.ndarray]: List of face embedding vectors.
        """
        if not landmarks_list:
            return []

        try:
            # If batching not supported or only one face, use sequential processing
            if not self.supports_batching or len(landmarks_list) == 1:
                return [self.get_embedding(image, lm, normalized) for lm in landmarks_list]

            # Batch processing
            aligned_faces = []
            for landmarks in landmarks_list:
                aligned_face, _ = face_alignment(image, landmarks)
                aligned_faces.append(aligned_face)

            # Process in batches
            embeddings = []
            batch_size = self.batch_size if self.batch_size else len(aligned_faces)

            for i in range(0, len(aligned_faces), batch_size):
                batch = aligned_faces[i:i + batch_size]

                # Preprocess batch
                batch_blobs = [self.preprocess(face) for face in batch]
                # Stack into single batch tensor
                batch_input = np.vstack(batch_blobs)

                # Run inference
                batch_embeddings = self.session.run(
                    self.output_names,
                    {self.input_name: batch_input}
                )[0]

                # Normalize if requested
                if normalized:
                    norms = np.linalg.norm(batch_embeddings, axis=1, keepdims=True)
                    batch_embeddings = batch_embeddings / norms

                # Add to results
                for embedding in batch_embeddings:
                    embeddings.append(embedding.flatten())

            return embeddings

        except Exception as e:
            logger.error(f"Error in batch embedding extraction: {e}")
            # Fallback to sequential processing
            logger.warning("Falling back to sequential processing")
            return [self.get_embedding(image, lm, normalized) for lm in landmarks_list]
