"""
duplicate/embedding_engine.py
Deep Learning embedding engine using DINOv2 or CLIP + FAISS-GPU for similarity search.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import numpy as np

try:
    import torch
    import torchvision.transforms as T
    from PIL import Image as PILImage
    PILImage.MAX_IMAGE_PIXELS = None
    HAS_TORCH = True
except (ImportError, OSError, Exception):
    HAS_TORCH = False

try:
    import faiss
    HAS_FAISS = True
except ImportError:
    HAS_FAISS = False

from utils.cuda_helper import get_torch_device, cuda_available
from duplicate.phash_engine import DisjointSetUnion


SUPPORTED_MODELS = {
    "dinov2_vits14": {"dim": 384,  "hub": ("facebookresearch/dinov2", "dinov2_vits14")},
    "dinov2_vitb14": {"dim": 768,  "hub": ("facebookresearch/dinov2", "dinov2_vitb14")},
    "dinov2_vitl14": {"dim": 1024, "hub": ("facebookresearch/dinov2", "dinov2_vitl14")},
}

CLIP_MODELS = {
    "clip-ViT-B-32": {"dim": 512},
}


class EmbeddingEngine:
    """
    Extract image embeddings using DINOv2 or CLIP, then search for
    similar images using FAISS (GPU or CPU index).
    """

    def __init__(
        self,
        model_name: str = "dinov2_vits14",
        device: str = "cuda",
        batch_size: int = 32,
    ):
        if not HAS_TORCH:
            raise RuntimeError("PyTorch not installed. Cannot use EmbeddingEngine.")

        self.model_name = model_name
        self.batch_size = batch_size
        self.device = get_torch_device(device) or torch.device("cpu")
        self.model = None
        self.embedding_dim = 384
        self._paths: list[Path] = []
        self._index = None          # FAISS index
        self._embeddings: Optional[np.ndarray] = None

        self._transform = T.Compose([
            T.Resize(256, interpolation=T.InterpolationMode.BICUBIC),
            T.CenterCrop(224),
            T.ToTensor(),
            T.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
        ])

    def load_model(self):
        """Download and load the model (called once, lazily)."""
        if self.model is not None:
            return

        if self.model_name in SUPPORTED_MODELS:
            cfg = SUPPORTED_MODELS[self.model_name]
            self.embedding_dim = cfg["dim"]
            repo, name = cfg["hub"]
            self.model = torch.hub.load(repo, name, pretrained=True)
        else:
            raise ValueError(f"Unsupported model: {self.model_name}")

        self.model.eval().to(self.device)

    # ─────────────────────────────────────────────
    # Embedding extraction
    # ─────────────────────────────────────────────

    def extract_embeddings(
        self,
        image_paths: list[Path],
        on_progress: Optional[callable] = None,
        cancel_check: Optional[callable] = None,
    ) -> np.ndarray:
        """
        Extract normalized embeddings for all images.
        Tracks valid_paths so self._paths stays 1-to-1 with self._embeddings.
        Returns: float32 array of shape [N, D]
        """
        self.load_model()
        all_embs = []
        valid_paths = []
        total = len(image_paths)

        for i in range(0, total, self.batch_size):
            if cancel_check and cancel_check():
                break
            batch_paths = image_paths[i : i + self.batch_size]
            tensors = []
            for p in batch_paths:
                t = self._load_image(p)
                if t is not None:
                    tensors.append(t)
                    valid_paths.append(p)

            if not tensors:
                continue

            batch = torch.stack(tensors).to(self.device)
            with torch.no_grad():
                embs = self.model(batch)            # [B, D]
            # L2 normalize → cosine similarity = dot product
            embs = torch.nn.functional.normalize(embs, p=2, dim=1)
            all_embs.append(embs.cpu().numpy())

            # Free GPU memory cache between batches
            if str(self.device).startswith("cuda"):
                torch.cuda.empty_cache()

            if on_progress:
                on_progress(min(i + self.batch_size, total), total)

            if cancel_check and cancel_check():
                break

        self._paths = valid_paths
        if not all_embs:
            return np.empty((0, self.embedding_dim), dtype=np.float32)
        return np.concatenate(all_embs, axis=0).astype(np.float32)

    # ─────────────────────────────────────────────
    # Index & Similarity Search (FAISS or PyTorch/NumPy native)
    # ─────────────────────────────────────────────

    def build_index(self, image_paths: list[Path], on_progress=None, cancel_check=None):
        """Extract embeddings and build search index (FAISS or Native)."""
        self._embeddings = self.extract_embeddings(image_paths, on_progress, cancel_check=cancel_check)

        if HAS_FAISS:
            try:
                index = faiss.IndexFlatIP(self.embedding_dim)
                if cuda_available():
                    try:
                        res = faiss.StandardGpuResources()
                        self._index = faiss.index_cpu_to_gpu(res, 0, index)
                    except Exception:
                        self._index = index
                else:
                    self._index = index
                self._index.add(self._embeddings)
            except Exception:
                self._index = None
        else:
            self._index = None

    def find_similar(
        self,
        query_embedding: np.ndarray,
        top_k: int = 10,
    ) -> list[tuple[Path, float]]:
        """
        Find top-k most similar images.
        Returns list of (path, similarity_score).
        """
        if self._embeddings is None or not self._paths:
            return []

        n = min(len(self._paths), len(self._embeddings))
        if n == 0:
            return []
        self._paths = self._paths[:n]
        self._embeddings = self._embeddings[:n]

        q = query_embedding.reshape(1, -1).astype(np.float32)

        if self._index is not None and HAS_FAISS:
            scores, indices = self._index.search(q, min(top_k, n))
            results = []
            for score, idx in zip(scores[0], indices[0]):
                if 0 <= idx < n:
                    results.append((self._paths[idx], float(score)))
            return results

        # Native NumPy dot-product fallback (Cosine similarity for L2-normalized vectors)
        sims = np.dot(self._embeddings, q.T).flatten()
        top_indices = np.argsort(sims)[::-1][:top_k]
        return [(self._paths[idx], float(sims[idx])) for idx in top_indices if idx < n]

    def find_all_duplicates(
        self,
        threshold: float = 0.95,
    ) -> list[list[tuple[Path, float]]]:
        """
        Find all duplicate groups.
        Returns list of groups; each group is list of (path, similarity).
        Guarantees strict bounds check so index out of bounds cannot occur.
        """
        if self._embeddings is None or not self._paths:
            return []

        n = min(len(self._paths), len(self._embeddings))
        if n < 2:
            return []

        self._paths = self._paths[:n]
        self._embeddings = self._embeddings[:n]

        from collections import defaultdict

        dsu = DisjointSetUnion(n)
        pair_scores: dict[tuple[int, int], float] = {}

        # If FAISS available
        if self._index is not None and HAS_FAISS:
            k = min(n, 50)
            scores_all, indices_all = self._index.search(self._embeddings, k)
            for i in range(n):
                for j, score in zip(indices_all[i], scores_all[i]):
                    if 0 <= j < n and j != i and float(score) >= threshold:
                        dsu.union(i, j)
                        pair_scores[(min(i, j), max(i, j))] = float(score)
        else:
            # Native PyTorch / NumPy pairwise Cosine Similarity Matrix: S = E . E^T
            if HAS_TORCH and self.device is not None:
                with torch.no_grad():
                    t_emb = torch.from_numpy(self._embeddings).to(self.device)
                    sim_matrix = torch.mm(t_emb, t_emb.t()).cpu().numpy()
            else:
                sim_matrix = np.dot(self._embeddings, self._embeddings.T)

            # Vectorized: np.argwhere thay thế O(N²) Python loop → ~100x nhanh hơn với N lớn
            np.fill_diagonal(sim_matrix, 0.0)  # Loại self-similarity để argwhere không nhặt (i,i)
            above_thresh = np.argwhere(sim_matrix >= threshold)  # shape [M, 2]
            for i, j in above_thresh:
                i, j = int(i), int(j)
                if i < j:   # Chỉ xét upper-triangle để tránh duplicate
                    dsu.union(i, j)
                    pair_scores[(i, j)] = float(sim_matrix[i, j])

        clusters = defaultdict(list)
        for idx in range(n):
            clusters[dsu.find(idx)].append(idx)

        groups = []
        for root_id, member_indices in clusters.items():
            if len(member_indices) > 1:
                group = []
                primary = member_indices[0]
                for idx in member_indices:
                    sim = 1.0 if idx == primary else pair_scores.get(
                        (min(primary, idx), max(primary, idx)), threshold
                    )
                    group.append((self._paths[idx], sim))
                groups.append(group)

        return groups

    # ─────────────────────────────────────────────
    # Internal
    # ─────────────────────────────────────────────

    def _load_image(self, path: Path) -> Optional["torch.Tensor"]:
        """Load image or video frame with memory safety and CPU pre-scaling for massive photos."""
        try:
            with PILImage.open(path) as img:
                img = img.convert("RGB")
                if max(img.size) > 1024:
                    img.thumbnail((512, 512), PILImage.Resampling.BILINEAR)
                return self._transform(img)
        except Exception:
            # Fallback 1: Video frame extraction via OpenCV
            try:
                import cv2
                cap = cv2.VideoCapture(str(path))
                if cap.isOpened():
                    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
                    if total_frames > 1:
                        cap.set(cv2.CAP_PROP_POS_FRAMES, min(10, total_frames // 2))
                    ret, frame = cap.read()
                    cap.release()
                    if ret and frame is not None:
                        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                        img = PILImage.fromarray(rgb)
                        if max(img.size) > 1024:
                            img.thumbnail((512, 512), PILImage.Resampling.BILINEAR)
                        return self._transform(img)
            except Exception as _bare_exc:
                try:
                    from core.app_logcat import logcat
                    logcat.w("EMBEDDING_EN", f"Loi im lang [duplicate/embedding_engine.py:300]: {_bare_exc}")
                except Exception:
                    pass

            # Fallback 2: RAW camera formats via rawpy
            try:
                import rawpy
                import io
                with rawpy.imread(str(path)) as raw:
                    try:
                        thumb = raw.extract_thumb()
                        with PILImage.open(io.BytesIO(thumb.data)) as img:
                            img = img.convert("RGB")
                            if max(img.size) > 1024:
                                img.thumbnail((512, 512), PILImage.Resampling.BILINEAR)
                            return self._transform(img)
                    except Exception:
                        rgb = raw.postprocess(half_size=True)
                        img = PILImage.fromarray(rgb).convert("RGB")
                        if max(img.size) > 1024:
                            img.thumbnail((512, 512), PILImage.Resampling.BILINEAR)
                        return self._transform(img)
            except Exception:
                return None

