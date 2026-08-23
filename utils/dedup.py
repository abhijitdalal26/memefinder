import json
from pathlib import Path
from typing import Optional, Set

import numpy as np
import imagehash
from PIL import Image

POPCOUNT_LUT = np.array([bin(i).count("1") for i in range(256)], dtype=np.uint8)
HASH_BYTES = 32  # phash(hash_size=16) -> 16x16 bits -> 64 hex chars -> 32 bytes


class Deduplicator:
    def __init__(self, hash_size: int = 16, threshold: int = 5):
        self.hash_size = hash_size
        self.threshold = threshold
        self.seen_hashes: Set[str] = set()
        self._matrix = np.empty((0, HASH_BYTES), dtype=np.uint8)
        self._load_existing_hashes()

    def _load_existing_hashes(self):
        hash_file = Path(__file__).parent.parent / "config" / "seen_hashes.json"
        if hash_file.exists():
            with open(hash_file, "r") as f:
                data = json.load(f)
                hashes = [h for h in data.get("hashes", []) if len(h) == HASH_BYTES * 2]
                self.seen_hashes = set(hashes)
        self._rebuild_matrix()

    def _rebuild_matrix(self):
        if not self.seen_hashes:
            self._matrix = np.empty((0, HASH_BYTES), dtype=np.uint8)
            return
        buf = b"".join(bytes.fromhex(h) for h in self.seen_hashes)
        self._matrix = np.frombuffer(buf, dtype=np.uint8).reshape(-1, HASH_BYTES)

    def _save_hashes(self):
        hash_file = Path(__file__).parent.parent / "config" / "seen_hashes.json"
        with open(hash_file, "w") as f:
            json.dump({"hashes": list(self.seen_hashes)}, f)

    @staticmethod
    def _prep_img(img: Image.Image) -> Image.Image:
        if img.mode == "RGBA":
            background = Image.new("RGB", img.size, (255, 255, 255))
            background.paste(img, mask=img.split()[3])
            return background
        elif img.mode != "RGB":
            return img.convert("RGB")
        return img

    def compute_hash_from_img(self, img: Image.Image) -> Optional[str]:
        try:
            return str(imagehash.phash(self._prep_img(img), hash_size=self.hash_size))
        except Exception:
            return None

    def compute_hash(self, image_path: str) -> Optional[str]:
        try:
            with Image.open(image_path) as img:
                return self.compute_hash_from_img(img)
        except Exception:
            return None

    def min_distance(self, hash_hex: str) -> int:
        """Minimum hamming distance between hash_hex and all stored hashes."""
        if self._matrix.shape[0] == 0:
            return HASH_BYTES * 8
        v = np.frombuffer(bytes.fromhex(hash_hex), dtype=np.uint8)
        xor = self._matrix ^ v
        dists = POPCOUNT_LUT[xor].sum(axis=1)
        return int(dists.min())

    def is_duplicate(
        self,
        image_path: Optional[str] = None,
        hash_hex: Optional[str] = None,
    ) -> bool:
        h = hash_hex or (self.compute_hash(image_path) if image_path else None)
        if h is None:
            return True
        if h in self.seen_hashes:
            return True
        return self.min_distance(h) <= self.threshold

    def register(
        self,
        image_path: Optional[str] = None,
        hash_hex: Optional[str] = None,
    ) -> bool:
        h = hash_hex or (self.compute_hash(image_path) if image_path else None)
        if h is None or self.is_duplicate(hash_hex=h):
            return False
        self.seen_hashes.add(h)
        row = np.frombuffer(bytes.fromhex(h), dtype=np.uint8).reshape(1, HASH_BYTES)
        self._matrix = np.vstack([self._matrix, row])
        return True

    def save(self):
        self._save_hashes()

    def get_stats(self) -> dict:
        return {"total_hashes": len(self.seen_hashes)}
