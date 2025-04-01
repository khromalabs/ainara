#!/usr/bin/env python3

import os
import sys
import torch
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def check_cuda():
    logger.info("=== CUDA Diagnostic Report ===")

    # Check PyTorch installation
    logger.info(f"PyTorch version: {torch.__version__}")

    # Check CUDA availability
    cuda_available = torch.cuda.is_available()
    logger.info(f"CUDA available: {cuda_available}")

    if not cuda_available:
        logger.info("CUDA is not available. Check NVIDIA drivers and PyTorch CUDA installation.")
        return False

    # Check CUDA version
    cuda_version = torch.version.cuda
    logger.info(f"CUDA version: {cuda_version}")

    # Check cuDNN version if available
    if hasattr(torch.backends, 'cudnn'):
        cudnn_enabled = torch.backends.cudnn.enabled
        logger.info(f"cuDNN enabled: {cudnn_enabled}")
        if hasattr(torch.backends.cudnn, 'version'):
            logger.info(f"cuDNN version: {torch.backends.cudnn.version()}")

    # Check GPU devices
    device_count = torch.cuda.device_count()
    logger.info(f"GPU device count: {device_count}")

    for i in range(device_count):
        logger.info(f"GPU {i}: {torch.cuda.get_device_name(i)}")
        logger.info(f"  Memory: {torch.cuda.get_device_properties(i).total_memory / 1e9:.2f} GB")

    # Test CUDA tensor operations
    try:
        logger.info("Testing CUDA tensor operations...")
        x = torch.rand(1000, 1000).cuda()
        y = torch.rand(1000, 1000).cuda()
        z = torch.matmul(x, y)
        logger.info(f"CUDA tensor test successful. Result shape: {z.shape}")
    except Exception as e:
        logger.error(f"CUDA tensor test failed: {e}")
        return False

    # Test CTranslate2 with CUDA
    try:
        logger.info("Testing CTranslate2 with CUDA...")
        import ctranslate2

        # Create a simple model to test CUDA support
        logger.info("CTranslate2 version: " + ctranslate2.__version__)

        # Check if CUDA is supported in the build
        logger.info("CTranslate2 CUDA support: " + str(ctranslate2.contains_cuda_device()))

        # Try to get device info
        devices_info = ctranslate2.get_devices_info()
        for device in devices_info:
            logger.info(f"Device: {device}")

        logger.info("CTranslate2 CUDA test successful")
    except Exception as e:
        logger.error(f"CTranslate2 CUDA test failed: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False

    # Test faster-whisper with CUDA
    try:
        logger.info("Testing faster-whisper with CUDA...")
        from faster_whisper import WhisperModel

        # Try to load a tiny model with CUDA
        logger.info("Loading tiny model with CUDA...")
        model = WhisperModel("tiny", device="cuda", compute_type="float16")

        logger.info("faster-whisper CUDA test successful")
    except Exception as e:
        logger.error(f"faster-whisper CUDA test failed: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False

    logger.info("=== All CUDA tests passed ===")
    return True

if __name__ == "__main__":
    check_cuda()
