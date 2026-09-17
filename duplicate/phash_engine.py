"""
duplicate/phash_engine.py
GPU-accelerated perceptual hash (pHash) using PyTorch FP16 Tensor Cores.
Primary: Pure PyTorch DCT via GEMM FP16 (no kornia required).
Fallback: kornia.dct_2d if available, then CPU imagehash.
Duplicate grouping: GEMM-based Hamming distance vectorized on GPU
using DisjointSetUnion (DSU) for fast cluster merging.
Multi-format: images, RAW camera files (rawpy), video frames (opencv).
"""
from __future__ import annotations

from collections import defaultdict
import os
import concurrent.futures
from pathlib import Path
from typing import Dict, List, Optional, Callable
import math
import numpy as np

try:
    import torch
    import torch.nn.functional as F
    HAS_TORCH = True
except (ImportError, OSError, Exception):
    HAS_TORCH = False

try:
    import kornia
    HAS_KORNIA = True
except ImportError:
    HAS_KORNIA = False

try:
    from PIL import Image as PILImage
    PILImage.MAX_IMAGE_PIXELS = None
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

from utils.cuda_helper import get_torch_device

HASH_SIZE = 8
DCT_SIZE  = 32


class DisjointSetUnion:
    """Union-Find with path compression and union-by-rank."""

    def __init__(self, n: int):
        self.parent = list(range(n))
        self.rank   = [0] * n

    def find(self, i: int) -> int:
        if self.parent[i] != i:
            self.parent[i] = self.find(self.parent[i])
        return self.parent[i]

    def union(self, i: int, j: int) -> None:
        ri, rj = self.find(i), self.find(j)
        if ri == rj:
            return
        if self.rank[ri] < self.rank[rj]:
            self.parent[ri] = rj
        elif self.rank[ri] > self.rank[rj]:
            self.parent[rj] = ri
        else:
            self.parent[rj] = ri
            self.rank[ri] += 1

    def get_groups(self, min_size: int = 1) -> list[list[int]]:
        """Return all clustered groups, optionally filtering by minimum group size."""
        from collections import defaultdict
        groups: dict[int, list[int]] = defaultdict(list)
        for i in range(len(self.parent)):
            groups[self.find(i)].append(i)
        return [g for g in groups.values() if len(g) >= min_size]


class PHashEngine:
    """
    Perceptual hash engine with GPU GEMM FP16, DSU grouping, RAW+Video support.

    GPU path (primary):
        DCT via GEMM: D = M @ X @ M^T using FP16 Tensor Cores.
        Hamming GEMM: dist = sum(Hi) + sum(Hj) - 2*(Hi @ Hj^T).

    Fallback:
        CPU imagehash library (images only).
    """

    def __init__(self, device: Optional[str] = "cuda"):
        self.torch_device = get_torch_device(device) if HAS_TORCH else None
        self._use_gpu = (
            HAS_TORCH and HAS_PIL and
            self.torch_device is not None and
            str(self.torch_device) != "cpu"
        )
        self._dtype = torch.float16 if (self._use_gpu and HAS_TORCH) else (
            torch.float32 if HAS_TORCH else None
        )
        self._dct_matrix: Optional["torch.Tensor"] = None
        if HAS_TORCH:
            self._dct_matrix = self._build_dct_matrix(DCT_SIZE).to(
                device=self.torch_device, dtype=self._dtype
            )

    @staticmethod
    def _build_dct_matrix(n: int = 32) -> "torch.Tensor":
        """Build NxN orthonormal DCT-II matrix in float32."""
        mat = torch.zeros((n, n), dtype=torch.float32)
        for k in range(n):
            for i in range(n):
                if k == 0:
                    mat[k, i] = 1.0 / (n ** 0.5)
                else:
                    mat[k, i] = ((2.0 / n) ** 0.5) * math.cos(
                        (2 * i + 1) * k * math.pi / (2 * n)
                    )
        return mat

    def _compute_hashes_from_tensors(
        self, tensors: "torch.Tensor", batch_chunk: int = 8192
    ) -> "torch.Tensor":
        """Compute pHash for [N,1,32,32] tensors using GEMM FP16."""
        n = tensors.shape[0]
        hash_list = []
        for i in range(0, n, batch_chunk):
            sub = tensors[i : i + batch_chunk].to(device=self.torch_device, dtype=self._dtype)
            b = sub.shape[0]
            x = sub.view(b, DCT_SIZE, DCT_SIZE)
            M = self._dct_matrix
            dct = torch.matmul(torch.matmul(M, x), M.t())
            dct_crop = dct[:, :HASH_SIZE, :HASH_SIZE]
            dct_flat = dct_crop.contiguous().view(b, 64)
            median = torch.median(dct_flat[:, 1:], dim=1, keepdim=True).values
            hash_list.append((dct_flat > median).to(self._dtype))
        return torch.cat(hash_list, dim=0)

    def compute_batch_gpu(
        self,
        image_paths: List[Path],
        batch_size: int = 128,
        on_progress: Optional[Callable[[int, int, str], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> Dict[Path, np.ndarray]:
        """GPU pHash with RAW/Video support via MediaExtractor and parallel tensor extraction."""
        from utils.media_extractor import MediaExtractor
        results: Dict[Path, np.ndarray] = {}
        total = len(image_paths)
        done_count = 0
        workers = min(8, max(2, (os.cpu_count() or 4)))

        for i in range(0, total, batch_size):
            if cancel_check and cancel_check():
                break
            batch_paths = image_paths[i : i + batch_size]
            with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
                extracted = list(executor.map(MediaExtractor.extract_tensor, batch_paths))

            tensors, valid_paths = [], []
            for p, t in zip(batch_paths, extracted):
                if cancel_check and cancel_check():
                    break
                done_count += 1
                if t is not None:
                    tensors.append(t)
                    valid_paths.append(p)
                if on_progress:
                    on_progress(done_count, total, f"Tính pHash (GPU): {p.name}")

            if not tensors:
                continue

            batch = torch.cat(tensors, dim=0)
            with torch.inference_mode():
                hashes_gpu = self._compute_hashes_from_tensors(batch)
            hashes_np = (hashes_gpu.cpu().numpy() > 0.5)
            for path, h in zip(valid_paths, hashes_np):
                results[path] = h.astype(bool)

            if cancel_check and cancel_check():
                break

        if self._use_gpu:
            torch.cuda.empty_cache()
        return results

    def compute_batch_cpu(
        self,
        image_paths: List[Path],
        batch_size: int = 64,
        on_progress: Optional[Callable[[int, int, str], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> Dict[Path, np.ndarray]:
        """CPU fallback using pure NumPy 2D DCT with ThreadPool parallel extraction."""
        results: Dict[Path, np.ndarray] = {}
        if not HAS_PIL:
            return results

        from utils.media_extractor import MediaExtractor

        # Pre-build NxN orthonormal DCT matrix for fast matrix multiplication
        M = np.zeros((DCT_SIZE, DCT_SIZE), dtype=np.float32)
        for k in range(DCT_SIZE):
            for i in range(DCT_SIZE):
                if k == 0:
                    M[k, i] = 1.0 / math.sqrt(DCT_SIZE)
                else:
                    M[k, i] = math.sqrt(2.0 / DCT_SIZE) * math.cos((2 * i + 1) * k * math.pi / (2 * DCT_SIZE))

        total = len(image_paths)
        done_count = 0
        workers = min(8, max(2, (os.cpu_count() or 4)))

        for i in range(0, total, batch_size):
            if cancel_check and cancel_check():
                break
            batch_paths = image_paths[i : i + batch_size]
            with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
                extracted = list(executor.map(MediaExtractor.extract_tensor, batch_paths))

            for p, t in zip(batch_paths, extracted):
                if cancel_check and cancel_check():
                    break
                done_count += 1
                if on_progress:
                    on_progress(done_count, total, f"Tính pHash: {p.name}")
                if t is None:
                    continue
                try:
                    if hasattr(t, "cpu"):
                        pixels = t.squeeze().cpu().numpy().astype(np.float32)
                    elif isinstance(t, np.ndarray):
                        pixels = t.squeeze().astype(np.float32)
                    else:
                        continue
                    if pixels.max() <= 1.0:
                        pixels = pixels * 255.0
                    dct = M @ pixels @ M.T
                    dct_low = dct[:HASH_SIZE, :HASH_SIZE]
                    median = np.median(dct_low.flatten()[1:])
                    results[p] = (dct_low.flatten() > median)
                except Exception:
                    pass

            if cancel_check and cancel_check():
                break

        return results

    def compute_batch(
        self,
        image_paths: List[Path],
        batch_size: int = 128,
        on_progress: Optional[Callable[[int, int, str], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> Dict[Path, np.ndarray]:
        """Auto-select GPU or CPU with real-time progress and cancellation support."""
        if self._use_gpu and HAS_TORCH:
            return self.compute_batch_gpu(image_paths, batch_size, on_progress=on_progress, cancel_check=cancel_check)
        return self.compute_batch_cpu(image_paths, batch_size, on_progress=on_progress, cancel_check=cancel_check)

    def hamming_distance(self, h1: np.ndarray, h2: np.ndarray) -> int:
        """Hamming distance between two 64-bit hashes."""
        return int(np.count_nonzero(h1 != h2))

    def find_duplicate_groups_gpu(
        self,
        hashes: Dict[Path, np.ndarray],
        threshold: int = 10,
        chunk_size: int = 8192,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> List[List[Path]]:
        """GPU GEMM vectorized Hamming + DSU grouping."""
        paths = list(hashes.keys())
        n = len(paths)
        if n < 2:
            return []
        hash_arr = np.stack([hashes[p] for p in paths]).astype(
            np.float16 if self._use_gpu else np.float32
        )
        dtype = torch.float16 if self._use_gpu else torch.float32
        H = torch.from_numpy(hash_arr).to(device=self.torch_device, dtype=dtype)
        row_sums = H.sum(dim=1)
        dsu = DisjointSetUnion(n)
        with torch.inference_mode():
            for i in range(0, n, chunk_size):
                if cancel_check and cancel_check():
                    return []
                end_i = min(i + chunk_size, n)
                H_chunk = H[i:end_i]
                sums_chunk = row_sums[i:end_i].unsqueeze(1)
                dot = torch.mm(H_chunk, H.t())
                dist = sums_chunk + row_sums.unsqueeze(0) - 2.0 * dot
                mask = dist <= float(threshold)
                for r in range(end_i - i):
                    mask[r, i + r] = False
                pairs = torch.nonzero(mask).cpu().numpy()
                for r_idx, c_idx in pairs:
                    dsu.union(i + int(r_idx), int(c_idx))
        del H, row_sums
        if self._use_gpu:
            torch.cuda.empty_cache()
        groups: Dict[int, List[int]] = defaultdict(list)
        for i in range(n):
            groups[dsu.find(i)].append(i)
        return [
            [paths[idx] for idx in sorted(members)]
            for members in groups.values()
            if len(members) > 1
        ]

    def find_duplicate_groups_cpu(
        self,
        hashes: Dict[Path, np.ndarray],
        threshold: int = 10,
        chunk_size: int = 1024,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> List[List[Path]]:
        """Vectorized NumPy GEMM Hamming + DSU grouping (O(N*C) BLAS instead of slow Python loop)."""
        paths = list(hashes.keys())
        n = len(paths)
        if n < 2:
            return []
        H = np.stack([hashes[p] for p in paths]).astype(np.float32)
        row_sums = H.sum(axis=1, keepdims=True)
        dsu = DisjointSetUnion(n)

        for i in range(0, n, chunk_size):
            if cancel_check and cancel_check():
                return []
            end_i = min(i + chunk_size, n)
            H_chunk = H[i:end_i]
            sums_chunk = row_sums[i:end_i]
            dot = H_chunk @ H.T
            dist = sums_chunk + row_sums.T - 2.0 * dot
            for r in range(end_i - i):
                dist[r, i + r] = 999.0
            pairs = np.argwhere(dist <= float(threshold))
            for r_idx, c_idx in pairs:
                dsu.union(i + int(r_idx), int(c_idx))

        groups: Dict[int, List[int]] = defaultdict(list)
        for i in range(n):
            groups[dsu.find(i)].append(i)
        return [
            [paths[idx] for idx in sorted(members)]
            for members in groups.values()
            if len(members) > 1
        ]

    def find_duplicate_groups(
        self,
        hashes: Dict[Path, np.ndarray],
        threshold: int = 10,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> List[List[Path]]:
        """Auto-select GPU GEMM or CPU vectorized GEMM."""
        if self._use_gpu and HAS_TORCH and len(hashes) > 1:
            return self.find_duplicate_groups_gpu(hashes, threshold, cancel_check=cancel_check)
        return self.find_duplicate_groups_cpu(hashes, threshold, cancel_check=cancel_check)

    def _load_to_tensor(self, path: Path) -> "Optional[torch.Tensor]":
        """Load image to [1,32,32] tensor (CPU, legacy compat)."""
        try:
            with PILImage.open(path) as img:
                img = img.convert("L").resize(
                    (DCT_SIZE, DCT_SIZE), PILImage.Resampling.BILINEAR
                )
                arr = np.array(img, dtype=np.float32) / 255.0
            return torch.from_numpy(arr).unsqueeze(0)
        except Exception:
            return None
