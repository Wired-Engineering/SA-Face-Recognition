"""
PyAV-based Video Capture with Hardware Acceleration
====================================================

High-performance video capture using PyAV with hardware-accelerated decoding.
Replaces OpenCV's VideoCapture for RTSP streams and webcams.

Hardware Acceleration Support:
- NVIDIA CUDA (NVDEC, CUVID)
- Intel QuickSync (QSV)
- VAAPI (Intel/AMD GPUs on Linux)
- VideoToolbox (Apple Silicon/macOS)
- DXVA2/D3D11VA (Windows)
- CPU fallback (software decode)

Environment Variables:
- ENABLE_GPU_ACCELERATION: true/false
- GPU_BACKEND_TYPE: nvidia, vaapi, intel_mfx, videotoolbox, cpu
"""

import av
import numpy as np
import os
import logging
import threading
import queue
from typing import Optional, Tuple, Dict, Any
from pathlib import Path
import time
from urllib.parse import quote, urlparse, urlunparse

logger = logging.getLogger(__name__)

__all__ = ["PyAVCapture", "get_hardware_config"]


def get_hardware_config() -> Tuple[str, Optional[str]]:
    """
    Get hardware acceleration configuration - auto-detects like ONNX Runtime.
    Falls back to environment variables if needed.

    Returns:
        Tuple of (backend_type, codec_name)
        backend_type: nvidia, vaapi, intel_mfx, videotoolbox, cpu
        codec_name: Hardware codec to use or None for auto-detect
    """
    import platform
    import sys

    # First try auto-detection (same as ONNX Runtime)
    try:
        import onnxruntime as ort
        available_providers = ort.get_available_providers()

        # Map ONNX providers to PyAV backends
        if 'CUDAExecutionProvider' in available_providers or \
           'TensorrtExecutionProvider' in available_providers:
            logger.info("🚀 Auto-detected: NVIDIA GPU (CUDA/TensorRT available in ONNX)")
            logger.info("ℹ️ Using CUDA video decode to match ONNX execution")
            return "nvidia", "h264_cuvid"

        elif 'CoreMLExecutionProvider' in available_providers:
            logger.info("🚀 Auto-detected: Apple Silicon (CoreML available in ONNX)")
            logger.info("ℹ️ Using VideoToolbox decode to match ONNX execution")
            return "videotoolbox", "h264_videotoolbox"

        elif 'ROCMExecutionProvider' in available_providers:
            logger.info("🚀 Auto-detected: AMD GPU (ROCm available in ONNX)")
            # AMD GPUs on Linux typically use VAAPI for video
            if platform.system() == 'Linux':
                return "vaapi", "h264_vaapi"
            else:
                return "cpu", None

        elif 'OpenVINOExecutionProvider' in available_providers:
            logger.info("🚀 Auto-detected: Intel GPU/CPU (OpenVINO available in ONNX)")
            # Intel GPUs can use QuickSync
            if platform.system() == 'Windows':
                return "intel_mfx", "h264_qsv"
            elif platform.system() == 'Linux':
                return "vaapi", "h264_vaapi"
            else:
                return "cpu", None

    except ImportError:
        logger.warning("⚠️ ONNX Runtime not available for auto-detection")
    except Exception as e:
        logger.warning(f"⚠️ Auto-detection failed: {e}")

    # Fallback to environment variables (for Docker/custom setups)
    enable_gpu = os.getenv('ENABLE_GPU_ACCELERATION', '').lower() in ('true', '1', 'yes')

    if not enable_gpu:
        logger.info("💻 Using CPU-only video decoding (software decode)")
        logger.info("💡 GPU available but disabled - ONNX Runtime may still use GPU")
        logger.info("💡 To enable GPU for video: set ENABLE_GPU_ACCELERATION=true")
        return "cpu", None

    # Use GPU backend type from environment
    backend_type = os.getenv('GPU_BACKEND_TYPE', 'cpu').lower()

    # Map backend types to PyAV hardware codecs
    hw_codec_map = {
        'nvidia': 'h264_cuvid',  # CUDA/NVDEC
        'vaapi': 'h264_vaapi',   # VAAPI (Intel/AMD)
        'intel_mfx': 'h264_qsv', # Intel QuickSync
        'videotoolbox': 'h264_videotoolbox',  # Apple VideoToolbox
        'dxva2': 'h264_dxva2',   # Windows DXVA2
        'd3d11va': 'h264_d3d11va',  # Windows D3D11
        'cpu': None
    }

    codec_name = hw_codec_map.get(backend_type)

    if backend_type != 'cpu' and codec_name:
        logger.info(f"🚀 Hardware-accelerated video decode: {backend_type} ({codec_name})")
        logger.info(f"ℹ️ Using environment variable GPU_BACKEND_TYPE={backend_type}")
    else:
        logger.info(f"⚠️ Unknown GPU backend type: {backend_type}, falling back to CPU")
        backend_type = "cpu"
        codec_name = None

    return backend_type, codec_name


class PyAVCapture:
    """
    PyAV-based video capture with hardware acceleration.
    Drop-in replacement for cv2.VideoCapture with similar API.
    """

    def __init__(self, source: str, hw_backend: Optional[str] = None, buffer_size: int = 1):
        """
        Initialize PyAV video capture.

        Args:
            source: Video source (RTSP URL, file path, or device index)
            hw_backend: Hardware backend (nvidia, vaapi, intel_mfx, cpu) or None for auto
            buffer_size: Frame buffer size (1 = lowest latency)
        """
        self.source = str(source)
        self.original_source = str(source)
        self.container: Optional[av.container.InputContainer] = None
        self.video_stream: Optional[av.video.stream.VideoStream] = None
        self.hw_backend = hw_backend
        self.buffer_size = buffer_size
        self.is_opened = False
        self.is_rtsp = str(source).startswith('rtsp://') or str(source).startswith('rtmp://')

        # Frame buffer for async reading
        self.frame_buffer: queue.Queue = queue.Queue(maxsize=buffer_size)
        self.decode_thread: Optional[threading.Thread] = None
        self.stop_decode = threading.Event()

        # Video properties
        self._width: Optional[int] = None
        self._height: Optional[int] = None
        self._fps: Optional[float] = None
        self._frame_count = 0

        # Performance tracking
        self._last_frame_time = time.time()
        self._decode_times = []

        # Auto-detect hardware if not specified
        if self.hw_backend is None:
            self.hw_backend, _ = get_hardware_config()

        # URL encode credentials if RTSP URL contains special characters
        if self.is_rtsp and '@' in self.source:
            self.source = self._encode_rtsp_url(self.source)

        # Open the video source
        self._open()

    def _encode_rtsp_url(self, url: str) -> str:
        """
        URL encode RTSP credentials to handle special characters.

        Args:
            url: Original RTSP URL

        Returns:
            URL with encoded credentials
        """
        try:
            parsed = urlparse(url)
            if parsed.username and parsed.password:
                # URL encode username and password (safe characters: @ already handled by urlparse)
                encoded_user = quote(parsed.username, safe='')
                encoded_pass = quote(parsed.password, safe='')

                # Reconstruct URL with encoded credentials
                netloc = f"{encoded_user}:{encoded_pass}@{parsed.hostname}"
                if parsed.port:
                    netloc += f":{parsed.port}"

                encoded_url = urlunparse((
                    parsed.scheme,
                    netloc,
                    parsed.path,
                    parsed.params,
                    parsed.query,
                    parsed.fragment
                ))

                logger.info(f"🔒 URL encoded credentials (password contains special chars)")
                return encoded_url
            return url
        except Exception as e:
            logger.warning(f"⚠️ Failed to encode URL, using original: {e}")
            return url

    def _get_codec_options(self) -> Dict[str, Any]:
        """Get codec-specific options for hardware acceleration."""
        # Get hardware config
        backend_type, hw_codec = get_hardware_config()

        options = {
            'rtsp_transport': 'tcp',
            'stimeout': '5000000',         # 5 second socket timeout (microseconds)
        }

        if self.is_rtsp:
            # RTSP-specific options
            options.update({
                'analyzeduration': '5000000',  # 5 seconds for initial probe
                'probesize': '5000000',        # 5MB probe size
                'fflags': 'nobuffer',
                'flags': 'low_delay',
                'max_delay': '500000',         # 500ms max delay
                'reorder_queue_size': '0',
                'buffer_size': '1',
            })
        else:
            # Non-RTSP (files, etc.)
            options.update({
                'analyzeduration': '1000000',
                'probesize': '1000000',
            })

        return options

    def _get_hw_device(self) -> Optional[str]:
        """Get hardware device context for PyAV."""
        backend_type, _ = get_hardware_config()

        # Map backend types to PyAV hardware device types
        hw_device_map = {
            'nvidia': 'cuda',
            'vaapi': 'vaapi',
            'intel_mfx': 'qsv',
            'videotoolbox': 'videotoolbox',
            'dxva2': 'dxva2',
            'd3d11va': 'd3d11va',
        }

        return hw_device_map.get(backend_type)

    def _open(self):
        """Open the video source with hardware acceleration."""
        try:
            options = self._get_codec_options()
            hw_device = self._get_hw_device()

            logger.info(f"📹 Opening video source: {self.source}")
            logger.info(f"🔧 Hardware backend: {self.hw_backend}")
            logger.info(f"🔧 Connection options: {options}")

            # Open container with timeout
            try:
                self.container = av.open(
                    self.source,
                    options=options,
                    timeout=(10.0, 5.0)  # (open timeout, read timeout) in seconds
                )
            except av.error.InvalidDataError as e:
                logger.error(f"❌ Invalid data error - camera may not be accessible or credentials incorrect: {e}")
                raise
            except av.error.HTTPUnauthorizedError as e:
                logger.error(f"❌ Authentication failed - check username/password: {e}")
                raise
            except Exception as e:
                logger.error(f"❌ Failed to open container: {e}")
                raise

            # Get video stream
            if not self.container.streams.video:
                raise ValueError("No video stream found in source")

            self.video_stream = self.container.streams.video[0]

            # Try to set hardware acceleration
            if hw_device and self.hw_backend != 'cpu':
                try:
                    # Set hardware device context
                    self.video_stream.codec_context.options = {
                        'hwaccel': hw_device,
                        'hwaccel_device': '0',  # Device 0
                    }
                    logger.info(f"✅ Hardware decode enabled: {hw_device}")
                except Exception as e:
                    logger.warning(f"⚠️ Hardware decode failed, using software: {e}")

            # Set thread count for decoding
            self.video_stream.thread_type = 'AUTO'
            self.video_stream.thread_count = 0  # Auto

            # Get video properties
            self._width = self.video_stream.codec_context.width
            self._height = self.video_stream.codec_context.height
            self._fps = float(self.video_stream.average_rate) if self.video_stream.average_rate else 30.0

            self.is_opened = True

            logger.info(f"✅ Video opened: {self._width}x{self._height} @ {self._fps:.2f}fps")

            # Start background decoding thread for low latency
            if self.is_rtsp:
                self._start_decode_thread()

        except av.error.InvalidDataError as e:
            logger.error(f"❌ Invalid data from camera. Check: URL format, network connectivity, camera accessibility")
            self.is_opened = False
            raise
        except av.error.HTTPUnauthorizedError as e:
            logger.error(f"❌ Authentication failed. Check username and password in RTSP URL")
            self.is_opened = False
            raise
        except Exception as e:
            logger.error(f"❌ Failed to open video source: {type(e).__name__}: {e}")
            self.is_opened = False
            raise

    def _start_decode_thread(self):
        """Start background thread for decoding frames."""
        if self.decode_thread is not None:
            return

        self.stop_decode.clear()
        self.decode_thread = threading.Thread(
            target=self._decode_loop,
            daemon=True,
            name="PyAV-Decode"
        )
        self.decode_thread.start()
        logger.info("🎬 Background decode thread started")

    def _decode_loop(self):
        """Background loop for decoding frames."""
        try:
            for packet in self.container.demux(self.video_stream):
                if self.stop_decode.is_set():
                    break

                try:
                    frames = packet.decode()
                    for frame in frames:
                        # Convert to numpy array
                        img = frame.to_ndarray(format='bgr24')

                        # Add to buffer (drop oldest if full)
                        if self.frame_buffer.full():
                            try:
                                self.frame_buffer.get_nowait()  # Drop oldest
                            except queue.Empty:
                                pass

                        self.frame_buffer.put_nowait(img)
                        self._frame_count += 1

                except av.AVError as e:
                    logger.debug(f"Decode error (packet): {e}")
                    continue

        except Exception as e:
            logger.error(f"❌ Decode thread error: {e}")
        finally:
            logger.info("🛑 Background decode thread stopped")

    def isOpened(self) -> bool:
        """Check if video source is opened."""
        return self.is_opened and self.container is not None

    def read(self) -> Tuple[bool, Optional[np.ndarray]]:
        """
        Read next frame from video source.

        Returns:
            Tuple of (success, frame)
            success: True if frame was read successfully
            frame: NumPy array (BGR format) or None
        """
        if not self.isOpened():
            return False, None

        try:
            if self.is_rtsp and self.decode_thread:
                # Read from buffer (background thread)
                try:
                    frame = self.frame_buffer.get(timeout=0.5)
                    return True, frame
                except queue.Empty:
                    logger.warning("⚠️ Frame buffer empty")
                    return False, None
            else:
                # Direct decode (for files/webcams)
                for packet in self.container.demux(self.video_stream):
                    for frame in packet.decode():
                        # Convert to numpy array (BGR format for OpenCV compatibility)
                        img = frame.to_ndarray(format='bgr24')
                        self._frame_count += 1
                        return True, img

                # End of stream
                return False, None

        except av.AVError as e:
            logger.error(f"❌ Read error: {e}")
            return False, None
        except Exception as e:
            logger.error(f"❌ Unexpected error in read(): {e}")
            return False, None

    def grab(self) -> bool:
        """
        Grab next frame (decode but don't retrieve).
        For compatibility with OpenCV API.

        For PyAV, we just check if a frame is available.
        """
        if not self.isOpened():
            return False

        if self.is_rtsp and self.decode_thread:
            return not self.frame_buffer.empty()
        else:
            # For non-RTSP, always return True (will decode on retrieve)
            return True

    def retrieve(self) -> Tuple[bool, Optional[np.ndarray]]:
        """
        Retrieve previously grabbed frame.
        For compatibility with OpenCV API.

        For PyAV, we just call read().
        """
        return self.read()

    def get(self, prop_id: int) -> float:
        """
        Get video property.

        Args:
            prop_id: Property ID (use cv2.CAP_PROP_* constants)

        Returns:
            Property value
        """
        # Map OpenCV property IDs to PyAV properties
        # cv2.CAP_PROP_FRAME_WIDTH = 3
        # cv2.CAP_PROP_FRAME_HEIGHT = 4
        # cv2.CAP_PROP_FPS = 5
        # cv2.CAP_PROP_FRAME_COUNT = 7

        if prop_id == 3:  # CAP_PROP_FRAME_WIDTH
            return float(self._width or 0)
        elif prop_id == 4:  # CAP_PROP_FRAME_HEIGHT
            return float(self._height or 0)
        elif prop_id == 5:  # CAP_PROP_FPS
            return float(self._fps or 30.0)
        elif prop_id == 7:  # CAP_PROP_FRAME_COUNT
            return float(self._frame_count)
        else:
            logger.warning(f"⚠️ Property {prop_id} not supported")
            return 0.0

    def set(self, prop_id: int, value: float) -> bool:
        """
        Set video property.

        Args:
            prop_id: Property ID (use cv2.CAP_PROP_* constants)
            value: Property value

        Returns:
            True if successful
        """
        # Most properties cannot be set for PyAV streams
        # This is here for API compatibility
        logger.debug(f"⚠️ Setting property {prop_id} = {value} (may not be supported)")
        return False

    def release(self):
        """Release video source and cleanup resources."""
        if not self.isOpened():
            return

        logger.info("🛑 Releasing PyAV video capture")

        # Stop decode thread
        if self.decode_thread:
            self.stop_decode.set()
            self.decode_thread.join(timeout=2.0)
            self.decode_thread = None

        # Close container
        if self.container:
            try:
                self.container.close()
            except Exception as e:
                logger.error(f"❌ Error closing container: {e}")

        self.container = None
        self.video_stream = None
        self.is_opened = False

        logger.info("✅ PyAV video capture released")

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.release()

    def __del__(self):
        """Cleanup on deletion."""
        self.release()


def flush_rtsp_buffer(cap: PyAVCapture, num_frames: int = 5) -> Tuple[bool, Optional[np.ndarray]]:
    """
    Flush RTSP buffer by grabbing multiple frames and only retrieving the latest.
    Ensures we're always processing the most recent frame.

    Args:
        cap: PyAVCapture instance
        num_frames: Number of frames to flush (default 5)

    Returns:
        Tuple of (success, frame)
    """
    if not cap.isOpened():
        return False, None

    # For PyAV with background thread, just read the latest from buffer
    if cap.is_rtsp and cap.decode_thread:
        # Clear buffer and get freshest frame
        latest_frame = None
        frames_flushed = 0

        while frames_flushed < num_frames:
            try:
                frame = cap.frame_buffer.get_nowait()
                latest_frame = frame
                frames_flushed += 1
            except queue.Empty:
                break

        if latest_frame is not None:
            return True, latest_frame
        else:
            # No frames in buffer, try regular read
            return cap.read()
    else:
        # For non-RTSP, just read normally
        return cap.read()


# Backward compatibility function
def create_pyav_capture(source: str, hw_backend: Optional[str] = None) -> PyAVCapture:
    """
    Create PyAV video capture with hardware acceleration.

    Args:
        source: Video source (RTSP URL, file path, or device index)
        hw_backend: Hardware backend or None for auto-detect

    Returns:
        PyAVCapture instance
    """
    return PyAVCapture(source, hw_backend=hw_backend, buffer_size=1)
