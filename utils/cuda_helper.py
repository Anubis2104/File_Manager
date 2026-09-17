"""
utils/cuda_helper.py
CUDA device detection, fallback logic, and device management.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class CudaInfo:
    available: bool
    device_id: int
    device_name: str
    total_memory_gb: float
    compute_capability: tuple[int, int]
    torch_version: str
    cuda_version: str

    def __str__(self) -> str:
        if not self.available:
            return "CUDA: Not available (using CPU)"
        return (
            f"CUDA: {self.device_name} | "
            f"{self.total_memory_gb:.1f} GB | "
            f"CC {self.compute_capability[0]}.{self.compute_capability[1]} | "
            f"CUDA {self.cuda_version}"
        )


_cuda_info: Optional[CudaInfo] = None


def get_cuda_info(device_id: int = 0) -> CudaInfo:
    """Detect CUDA device info. Cached after first call."""
    global _cuda_info
    if _cuda_info is not None:
        return _cuda_info

    try:
        import torch

        if not torch.cuda.is_available():
            _cuda_info = CudaInfo(
                available=False,
                device_id=-1,
                device_name="CPU",
                total_memory_gb=0.0,
                compute_capability=(0, 0),
                torch_version=torch.__version__,
                cuda_version="N/A",
            )
        else:
            props = torch.cuda.get_device_properties(device_id)
            mem_gb = props.total_memory / (1024**3)
            cc = (props.major, props.minor)
            _cuda_info = CudaInfo(
                available=True,
                device_id=device_id,
                device_name=props.name,
                total_memory_gb=mem_gb,
                compute_capability=cc,
                torch_version=torch.__version__,
                cuda_version=torch.version.cuda or "N/A",
            )
    except (ImportError, OSError, Exception):
        logger.debug("PyTorch not installed or blocked by OS — using CPU mode.")
        _cuda_info = CudaInfo(
            available=False,
            device_id=-1,
            device_name="CPU (PyTorch unavailable)",
            total_memory_gb=0.0,
            compute_capability=(0, 0),
            torch_version="N/A",
            cuda_version="N/A",
        )

    logger.info(str(_cuda_info))
    return _cuda_info


def get_torch_device(preferred: str = "cuda", device_id: int = 0):
    """
    Return a torch.device. Falls back to CPU if CUDA unavailable.
    preferred: 'cuda' | 'cpu'
    """
    try:
        import torch

        info = get_cuda_info(device_id)
        if preferred == "cuda" and info.available:
            return torch.device(f"cuda:{device_id}")
        return torch.device("cpu")
    except (ImportError, OSError, Exception):
        return None


def cuda_available() -> bool:
    return get_cuda_info().available


def reset_cache() -> None:
    """Force re-detection (useful after driver changes)."""
    global _cuda_info
    _cuda_info = None
