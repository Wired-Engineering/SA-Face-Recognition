"""
ONNX Runtime Utilities
Enhanced session management with advanced onnxruntime features
Inspired by Immich's approach with additional optimizations
"""

import onnx
import numpy as np
import onnxruntime as ort
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Any
from logging import getLogger
from onnx.tools.update_model_dims import update_inputs_outputs_dims

logger = getLogger(__name__)

__all__ = ["create_optimized_session", "add_batch_axis", "serialize_embedding", "get_provider_options"]


def get_provider_options() -> Tuple[List[Tuple[str, Dict]], List[str]]:
    """
    Get optimized ONNX Runtime execution providers with configuration options.

    Returns:
        Tuple of (providers_with_options, provider_names) for fallback
    """
    available_providers = ort.get_available_providers()
    providers_with_options = []
    provider_names = []

    logger.info(f"Available ONNX providers: {available_providers}")

    # CUDA (NVIDIA GPU) - highest priority for performance
    if "CUDAExecutionProvider" in available_providers:
        cuda_options = {
            'device_id': 0,
            'arena_extend_strategy': 'kNextPowerOfTwo',  # Memory allocation strategy
            # 'gpu_mem_limit': 2 * 1024 * 1024 * 1024,  # Removed - no GPU memory limit
            'cudnn_conv_algo_search': 'EXHAUSTIVE',  # Best convolution algorithm
            'do_copy_in_default_stream': True,
        }
        providers_with_options.append(('CUDAExecutionProvider', cuda_options))
        provider_names.append('CUDAExecutionProvider')
        logger.info("✓ CUDA GPU acceleration enabled (no memory limit)")

    # ROCm (AMD GPU)
    if "ROCMExecutionProvider" in available_providers:
        rocm_options = {
            'device_id': 0,
            'arena_extend_strategy': 'kSameAsRequested',
        }
        providers_with_options.append(('ROCMExecutionProvider', rocm_options))
        provider_names.append('ROCMExecutionProvider')
        logger.info("✓ ROCm AMD GPU acceleration enabled")

    # CoreML (Apple Silicon)
    if "CoreMLExecutionProvider" in available_providers:
        coreml_options = {
            "MLComputeUnits": "ALL",
            "ModelFormat": "MLProgram",
            "EnableOnSubgraphs": 1,
        }
        providers_with_options.append(('CoreMLExecutionProvider', coreml_options))
        provider_names.append('CoreMLExecutionProvider')
        logger.info("✓ CoreML Apple Silicon acceleration enabled")

    # OpenVINO (Intel)
    if "OpenVINOExecutionProvider" in available_providers:
        openvino_options = {
            'device_type': 'CPU_FP32',  # Can be GPU_FP32, GPU_FP16, etc.
        }
        providers_with_options.append(('OpenVINOExecutionProvider', openvino_options))
        provider_names.append('OpenVINOExecutionProvider')
        logger.info("✓ OpenVINO Intel acceleration enabled")

    # CPU fallback - always available with default options for compatibility
    providers_with_options.append(('CPUExecutionProvider', {}))
    provider_names.append('CPUExecutionProvider')

    if len(providers_with_options) == 1:
        logger.info("⚠ No GPU acceleration available, using CPU only")

    return providers_with_options, provider_names


def create_optimized_session(
    model_path: str,
    enable_profiling: bool = False,
    graph_optimization_level: int = 99,  # ORT_ENABLE_ALL
    enable_mem_pattern: bool = True,
    enable_cpu_mem_arena: bool = True,
    intra_op_num_threads: Optional[int] = None,
    inter_op_num_threads: Optional[int] = None,
) -> ort.InferenceSession:
    """
    Create an optimized ONNX Runtime inference session with advanced features.

    Args:
        model_path: Path to ONNX model file
        enable_profiling: Enable performance profiling (for debugging)
        graph_optimization_level: Graph optimization level (0=disable, 1=basic, 2=extended, 99=all)
        enable_mem_pattern: Enable memory pattern optimization
        enable_cpu_mem_arena: Enable CPU memory arena
        intra_op_num_threads: Number of threads for intra-op parallelism
        inter_op_num_threads: Number of threads for inter-op parallelism

    Returns:
        Configured InferenceSession
    """
    # Create session options
    sess_options = ort.SessionOptions()

    # Graph optimization
    if graph_optimization_level == 0:
        sess_options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_DISABLE_ALL
    elif graph_optimization_level == 1:
        sess_options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_BASIC
    elif graph_optimization_level == 2:
        sess_options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_EXTENDED
    else:
        sess_options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL

    # Memory optimization
    sess_options.enable_mem_pattern = enable_mem_pattern
    sess_options.enable_cpu_mem_arena = enable_cpu_mem_arena

    # Thread configuration
    if intra_op_num_threads:
        sess_options.intra_op_num_threads = intra_op_num_threads
    if inter_op_num_threads:
        sess_options.inter_op_num_threads = inter_op_num_threads

    # Enable profiling for performance analysis
    if enable_profiling:
        sess_options.enable_profiling = True
        profile_path = Path(model_path).parent / f"{Path(model_path).stem}_profile.json"
        sess_options.profile_file_prefix = str(profile_path)
        logger.info(f"Profiling enabled: {profile_path}")

    # Get optimized providers
    providers_with_options, provider_names = get_provider_options()

    try:
        # Try with provider options first
        session = ort.InferenceSession(
            model_path,
            sess_options=sess_options,
            providers=providers_with_options
        )
        active_providers = session.get_providers()
        logger.info(f"✓ Session created successfully with providers: {active_providers[0]}")
    except Exception as e:
        logger.warning(f"Provider options failed, trying simple provider names: {e}")
        # Fallback to simple provider names without options
        try:
            session = ort.InferenceSession(
                model_path,
                sess_options=sess_options,
                providers=provider_names
            )
            active_providers = session.get_providers()
            logger.info(f"✓ Session created with fallback providers: {active_providers[0]}")
        except Exception as e2:
            # Final fallback to CPU only
            logger.error(f"All providers failed, using CPU only: {e2}")
            session = ort.InferenceSession(
                model_path,
                sess_options=sess_options,
                providers=['CPUExecutionProvider']
            )
            logger.info("✓ Session created with CPU only")

    # Log session info
    _log_session_info(session)

    return session


def _log_session_info(session: ort.InferenceSession):
    """Log detailed session information"""
    try:
        # Input info
        for input_meta in session.get_inputs():
            logger.debug(f"Input: {input_meta.name}, shape: {input_meta.shape}, type: {input_meta.type}")

        # Output info
        for output_meta in session.get_outputs():
            logger.debug(f"Output: {output_meta.name}, shape: {output_meta.shape}, type: {output_meta.type}")

        # Provider info
        logger.info(f"Active providers: {session.get_providers()}")

    except Exception as e:
        logger.warning(f"Could not log session info: {e}")


def add_batch_axis(model_path: Path, save_path: Optional[Path] = None) -> Path:
    """
    Add dynamic batch axis to ONNX model for batch processing.
    Based on Immich's implementation.

    Args:
        model_path: Path to original ONNX model
        save_path: Path to save modified model (defaults to overwriting original)

    Returns:
        Path to modified model
    """
    logger.info(f"Adding batch axis to model: {model_path}")

    try:
        # Load model
        model = onnx.load(str(model_path))

        # Get static dimensions from input
        input_tensor = model.graph.input[0]
        static_input_dims = [
            dim.dim_value for dim in input_tensor.type.tensor_type.shape.dim[1:]
        ]

        # Get static dimensions from output
        output_tensor = model.graph.output[0]
        static_output_dims = [
            dim.dim_value for dim in output_tensor.type.tensor_type.shape.dim[1:]
        ]

        # Create dynamic batch dimensions
        input_dims = {input_tensor.name: ["batch"] + static_input_dims}
        output_dims = {output_tensor.name: ["batch"] + static_output_dims}

        # Update model
        updated_model = update_inputs_outputs_dims(model, input_dims, output_dims)

        # Save
        save_path = save_path or model_path
        onnx.save(updated_model, str(save_path))

        logger.info(f"Batch axis added successfully: {save_path}")
        logger.debug(f"Input dims: {input_dims}")
        logger.debug(f"Output dims: {output_dims}")

        return save_path

    except Exception as e:
        logger.error(f"Failed to add batch axis: {e}")
        raise


def check_batch_support(session: ort.InferenceSession) -> bool:
    """
    Check if model supports dynamic batching.

    Args:
        session: ONNX Runtime session

    Returns:
        True if batch dimension is dynamic
    """
    try:
        input_shape = session.get_inputs()[0].shape
        # Check if first dimension is dynamic (string or None)
        return isinstance(input_shape[0], str) or input_shape[0] is None
    except Exception:
        return False


def serialize_embedding(embedding: np.ndarray) -> List[float]:
    """
    Serialize face embedding for JSON/API responses.
    Based on Immich's approach.

    Args:
        embedding: Face embedding vector

    Returns:
        List of floats for JSON serialization
    """
    if embedding is None:
        return []

    # Ensure float32 for consistency and size
    embedding = embedding.astype(np.float32)

    # Flatten if needed
    if len(embedding.shape) > 1:
        embedding = embedding.flatten()

    return embedding.tolist()


def deserialize_embedding(embedding_list: List[float]) -> np.ndarray:
    """
    Deserialize face embedding from JSON/API.

    Args:
        embedding_list: List of floats from JSON

    Returns:
        NumPy array (float32)
    """
    return np.array(embedding_list, dtype=np.float32)


def validate_model(model_path: Path) -> Dict[str, Any]:
    """
    Validate ONNX model and return metadata.

    Args:
        model_path: Path to ONNX model

    Returns:
        Dictionary with model metadata
    """
    try:
        model = onnx.load(str(model_path))
        onnx.checker.check_model(model)

        # Extract metadata
        input_info = []
        for input_tensor in model.graph.input:
            shape = [dim.dim_value if hasattr(dim, 'dim_value') else str(dim.dim_param)
                    for dim in input_tensor.type.tensor_type.shape.dim]
            input_info.append({
                'name': input_tensor.name,
                'shape': shape,
                'type': input_tensor.type.tensor_type.elem_type
            })

        output_info = []
        for output_tensor in model.graph.output:
            shape = [dim.dim_value if hasattr(dim, 'dim_value') else str(dim.dim_param)
                    for dim in output_tensor.type.tensor_type.shape.dim]
            output_info.append({
                'name': output_tensor.name,
                'shape': shape,
                'type': output_tensor.type.tensor_type.elem_type
            })

        return {
            'valid': True,
            'inputs': input_info,
            'outputs': output_info,
            'opset_version': model.opset_import[0].version if model.opset_import else None
        }

    except Exception as e:
        return {
            'valid': False,
            'error': str(e)
        }


def get_model_input_shape(session: ort.InferenceSession) -> Tuple[int, ...]:
    """Get the input shape of a model session"""
    return tuple(session.get_inputs()[0].shape)


def get_model_output_shape(session: ort.InferenceSession) -> Tuple[int, ...]:
    """Get the output shape of a model session"""
    return tuple(session.get_outputs()[0].shape)


def warmup_session(session: ort.InferenceSession, input_shape: Tuple[int, ...], num_runs: int = 3):
    """
    Warm up the session with dummy inputs to initialize GPU kernels.

    Args:
        session: ONNX Runtime session
        input_shape: Shape of input tensor
        num_runs: Number of warm-up runs
    """
    logger.info(f"Warming up session with {num_runs} runs...")

    input_name = session.get_inputs()[0].name
    dummy_input = np.random.randn(*input_shape).astype(np.float32)

    for i in range(num_runs):
        session.run(None, {input_name: dummy_input})

    logger.info("Session warm-up complete")
