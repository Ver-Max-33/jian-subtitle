from __future__ import annotations

from collections.abc import Sequence
from collections import OrderedDict
from dataclasses import dataclass
import math
from pathlib import Path
import threading

import cv2
import numpy as np
from PIL import Image, ImageOps


Region = tuple[int, int, int, int]


@dataclass(frozen=True)
class LayoutAnalysis:
    image_size: tuple[int, int]
    grid_size: tuple[int, int]
    regions: tuple[Region, ...]
    detail: np.ndarray
    protected: np.ndarray

    @property
    def nbytes(self):
        return self.detail.nbytes + self.protected.nbytes


@dataclass(frozen=True)
class LayoutResult:
    positions: tuple[tuple[float, float], ...] | None
    overlaps_people: bool = False


class LayoutService:
    """Chooses a readable caption position while avoiding detected people and faces."""

    ANALYSIS_SIDE = 640
    GRID_SIDE = 320
    CACHE_BYTES = 16 * 1024 * 1024
    CACHE_ENTRIES = 64

    def __init__(self):
        self._cache = OrderedDict()
        self._cache_bytes = 0
        self._lock = threading.RLock()
        self._face_detector = None
        self._people_detector = None

    def analyze_path(self, path: Path) -> LayoutAnalysis:
        path = Path(path).resolve()
        stat = path.stat()
        key = (str(path), stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                return self._cache[key]
            with Image.open(path) as opened:
                dimensions = opened.size
                if opened.getexif().get(274) in {5, 6, 7, 8}:
                    dimensions = dimensions[::-1]
                opened.draft("RGB", (self.ANALYSIS_SIDE, self.ANALYSIS_SIDE))
                opened.thumbnail((self.ANALYSIS_SIDE, self.ANALYSIS_SIDE), Image.Resampling.BILINEAR)
                thumbnail = ImageOps.exif_transpose(opened).convert("RGB")
            detected = self.detect_protected_regions(thumbnail)
            sx, sy = dimensions[0] / thumbnail.width, dimensions[1] / thumbnail.height
            regions = [(round(x*sx), round(y*sy), math.ceil(w*sx), math.ceil(h*sy)) for x, y, w, h in detected]
            analysis = self.analyze(thumbnail, regions, image_size=dimensions)
            self._cache[key] = analysis
            self._cache_bytes += analysis.nbytes
            while len(self._cache) > self.CACHE_ENTRIES or self._cache_bytes > self.CACHE_BYTES:
                self._cache_bytes -= self._cache.popitem(last=False)[1].nbytes
            return analysis

    def analyze(self, image: Image.Image, protected_regions: Sequence[Region] = (), *, image_size=None) -> LayoutAnalysis:
        dimensions = image_size or image.size
        thumbnail = image.copy()
        thumbnail.thumbnail((self.GRID_SIDE, self.GRID_SIDE), Image.Resampling.BILINEAR)
        gray = np.asarray(thumbnail.convert("L"), dtype=np.float32) / 255
        dx = cv2.Sobel(gray, cv2.CV_32F, 1, 0)
        dy = cv2.Sobel(gray, cv2.CV_32F, 0, 1)
        detail = np.clip(cv2.magnitude(dx, dy), 0, 1)
        # A union mask avoids counting the same face/body overlap more than once.
        mask = self._region_mask(thumbnail.size, dimensions, protected_regions)
        return LayoutAnalysis(dimensions, thumbnail.size, tuple(protected_regions),
                              cv2.integral(detail, sdepth=cv2.CV_32F), cv2.integral(mask, sdepth=cv2.CV_32F))

    @staticmethod
    def _region_mask(grid_size, image_size, regions, padding=0):
        width, height = grid_size
        sx, sy = width / image_size[0], height / image_size[1]
        mask = np.zeros((height, width), dtype=np.float32)
        for x, y, w, h in regions:
            left, top = max(0, math.floor((x-padding)*sx)), max(0, math.floor((y-padding)*sy))
            right, bottom = min(width, math.ceil((x+w+padding)*sx)), min(height, math.ceil((y+h+padding)*sy))
            if right > left and bottom > top:
                mask[top:bottom, left:right] = 1
        return mask

    @staticmethod
    def _window_sum(integral, width, height):
        return integral[height:, width:] - integral[:-height, width:] - integral[height:, :-width] + integral[:-height, :-width]

    def arrange(self, analysis: LayoutAnalysis, text_sizes: Sequence[tuple[int, int]], occupied: Sequence[Region] = ()) -> LayoutResult:
        """Joint top-to-bottom placement, never overlapping fixed or automatic captions.

        Minimize cost on a bounded thumbnail grid with dynamic programming. For each
        possible row only the best horizontal position is needed: captions occupy
        separate vertical bands, so no exponential search over combinations is needed.
        """
        if not text_sizes:
            return LayoutResult(())
        gw, gh = analysis.grid_size
        iw, ih = analysis.image_size
        gap = max(4, round(min(iw, ih) * .012))
        margin = max(12, round(min(iw, ih) * .02))
        mx, my = math.ceil(margin * gw / iw), math.ceil(margin * gh / ih)
        gy = math.ceil(gap * gh / ih)
        sizes = [(max(1, math.ceil(w * gw / iw)), max(1, math.ceil(h * gh / ih))) for w, h in text_sizes]
        if any(w > gw - 2*mx for w, _ in sizes) or sum(h for _, h in sizes) + gy*(len(sizes)-1) > gh - 2*my:
            return LayoutResult(None)
        fixed = cv2.integral(self._region_mask((gw, gh), (iw, ih), occupied, padding=gap), sdepth=cv2.CV_32F)
        costs = []
        for w, h in sizes:
            area = w*h
            people = self._window_sum(analysis.protected, w, h)
            detail = np.maximum(0, self._window_sum(analysis.detail, w, h)) / area
            rows, cols = detail.shape
            x = (np.arange(cols) + w/2) / gw
            y = (np.arange(rows) + h/2) / gh
            cost = detail * .6 + (1-y[:, None]) * .12 + np.abs(x[None, :]-.5) * .08
            invalid = self._window_sum(fixed, w, h) > .5
            invalid[:my] = True; invalid[max(0, rows-my):] = True
            invalid[:, :mx] = True; invalid[:, max(0, cols-mx):] = True
            cost[invalid] = np.inf
            costs.append((cost, people / area))

        for strict in (True, False):
            row_costs, columns = [], []
            for cost, people in costs:
                scored = cost.copy() + people * 20
                if strict:
                    scored[people > 0] = np.inf
                xs = scored.argmin(axis=1)
                row_costs.append(scored[np.arange(len(xs)), xs])
                columns.append(xs)
            previous = row_costs[0]
            parents = []
            for index in range(1, len(sizes)):
                prefix_values = np.minimum.accumulate(previous)
                prefix_indices = np.empty(len(previous), dtype=np.int32)
                best = 0
                for row in range(len(previous)):
                    if previous[row] < previous[best]:
                        best = row
                    prefix_indices[row] = best
                limits = np.arange(len(row_costs[index])) - sizes[index-1][1] - gy
                valid = limits >= 0
                bounded = np.clip(limits, 0, len(previous)-1)
                current = row_costs[index] + np.where(valid, prefix_values[bounded], np.inf)
                parents.append(np.where(valid, prefix_indices[bounded], -1))
                previous = current
            row = int(previous.argmin())
            if not np.isfinite(previous[row]):
                continue
            placements = []
            overlaps_people = False
            for index in range(len(sizes)-1, -1, -1):
                col = int(columns[index][row])
                w, h = sizes[index]
                placements.append(((col+w/2)/gw, (row+h/2)/gh))
                overlaps_people |= bool(costs[index][1][row, col] > 0)
                if index:
                    row = int(parents[index-1][row])
            return LayoutResult(tuple(reversed(placements)), overlaps_people)
        return LayoutResult(None)

    def choose_position(
        self,
        image: Image.Image,
        text_size: tuple[int, int],
        protected_regions: Sequence[Region] | None = None,
    ) -> tuple[float, float]:
        regions = (
            list(protected_regions)
            if protected_regions is not None
            else self.detect_protected_regions(image)
        )
        result = self.arrange(self.analyze(image, regions), [text_size])
        if result.positions is None:
            raise ValueError("没有足够空间放置字幕，请减小字号或调整手动字幕")
        return result.positions[0]

    def detect_protected_regions(self, image: Image.Image) -> list[Region]:
        original_width, original_height = image.size
        thumbnail = image.copy()
        thumbnail.thumbnail((self.ANALYSIS_SIDE, self.ANALYSIS_SIDE), Image.Resampling.BILINEAR)
        working = np.asarray(thumbnail.convert("RGB"))
        scale = min(1.0, self.ANALYSIS_SIDE / max(original_width, original_height))
        gray = cv2.cvtColor(working, cv2.COLOR_RGB2GRAY)
        regions: list[Region] = []

        cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        if self._face_detector is None:
            self._face_detector = cv2.CascadeClassifier(cascade_path)
        face_detector = self._face_detector
        if not face_detector.empty():
            for x, y, width, height in face_detector.detectMultiScale(
                gray, scaleFactor=1.1, minNeighbors=4, minSize=(20, 20)
            ):
                regions.append(
                    self._expanded_scaled_region(
                        (int(x), int(y), int(width), int(height)),
                        scale,
                        original_width,
                        original_height,
                        expansion=0.45,
                    )
                )

        if self._people_detector is None:
            self._people_detector = cv2.HOGDescriptor()
            self._people_detector.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())
        hog = self._people_detector
        people = []
        if working.shape[1] >= 64 and working.shape[0] >= 128:
            people, _ = hog.detectMultiScale(
                cv2.cvtColor(working, cv2.COLOR_RGB2BGR),
                winStride=(8, 8), padding=(8, 8), scale=1.08,
            )
        for x, y, width, height in people:
            regions.append(
                self._expanded_scaled_region(
                    (int(x), int(y), int(width), int(height)),
                    scale,
                    original_width,
                    original_height,
                    expansion=0.12,
                )
            )
        return regions

    @staticmethod
    def _expanded_scaled_region(
        region: Region,
        scale: float,
        image_width: int,
        image_height: int,
        *,
        expansion: float,
    ) -> Region:
        x, y, width, height = region
        inverse = 1 / max(scale, 1e-9)
        x *= inverse
        y *= inverse
        width *= inverse
        height *= inverse
        x -= width * expansion
        y -= height * expansion
        width *= 1 + expansion * 2
        height *= 1 + expansion * 2
        left = max(0, round(x))
        top = max(0, round(y))
        right = min(image_width, round(x + width))
        bottom = min(image_height, round(y + height))
        return (left, top, max(0, right - left), max(0, bottom - top))

    @staticmethod
    def _intersection_area(first: Region, second: Region) -> int:
        first_left, first_top, first_width, first_height = first
        second_left, second_top, second_width, second_height = second
        left = max(first_left, second_left)
        top = max(first_top, second_top)
        right = min(first_left + first_width, second_left + second_width)
        bottom = min(first_top + first_height, second_top + second_height)
        return max(0, right - left) * max(0, bottom - top)
