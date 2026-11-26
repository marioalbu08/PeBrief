"""Cât timp se vede logo-ul în clip, și unde.

Metoda: puncte SIFT pe logo + potrivire în fiecare cadru eșantionat, filtru de
raport Lowe, apoi o omografie RANSAC. O potrivire contează doar dacă
omografia are sens fizic: patrulater convex, nu prea mic, nu turtit. Asta
taie aproape toate alarmele false pe care le dau potrivirile izolate.

La final, detecțiile pe cadre devin intervale (cu goluri de un cadru umplute
și detecții izolate slabe aruncate), iar secundele vizibile se adună din ele.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np

RATIO = 0.75
MIN_INLIERS = 10
NCC_MIN = float(__import__("os").environ.get("PEBRIEF_NCC", "0.6"))  # adevărate >= 0,93, false <= 0,35 pe setul de reglaj
NCC_W = 120  # lățimea la care comparăm pixel cu pixel


@dataclass
class LogoModel:
    kps: list
    desc: np.ndarray
    w: int
    h: int
    corners: np.ndarray = field(repr=False)
    tmpl: np.ndarray = field(default=None, repr=False)
    tmask: np.ndarray = field(default=None, repr=False)


def _sift():
    return cv2.SIFT_create(nfeatures=0, contrastThreshold=0.03)


def load_logo(path: str, scales=(360, 180, 100)) -> LogoModel:
    # Trei scări: logo-urile mici și încețoșate se potrivesc cu descriptorii de la
    # scara mică (pe setul nevăzut, recall 0,68 -> 0,86; eval/REZULTATE.md).
    img = cv2.imread(path, cv2.IMREAD_UNCHANGED)
    if img is None:
        raise ValueError("logo-ul nu poate fi citit")
    if img.ndim == 2:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGRA)
    if img.shape[2] == 3:
        img = cv2.cvtColor(img, cv2.COLOR_BGR2BGRA)
    # decupăm marginile transparente
    a = img[:, :, 3]
    ys, xs = np.where(a > 10)
    if len(xs):
        img = img[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    base = img
    kps_all, desc_all = [], []
    sift = _sift()
    w0 = scales[0]
    for tw in scales:
        s = tw / base.shape[1]
        im = cv2.resize(base, None, fx=s, fy=s, interpolation=cv2.INTER_AREA if s < 1 else cv2.INTER_CUBIC)
        alpha = im[:, :, 3:4].astype(np.float32) / 255
        back = w0 / tw  # coordonatele se raportează la scara de referință
        # Descriptori pe fundal deschis și pe fundal închis: logo-ul real apare pe
        # orice, iar descriptorii de lângă margini depind de fundal.
        for bg in (255, 30):
            comp = (im[:, :, :3].astype(np.float32) * alpha + bg * (1 - alpha)).astype(np.uint8)
            gray = cv2.cvtColor(comp, cv2.COLOR_BGR2GRAY)
            pad = 24
            gray = cv2.copyMakeBorder(gray, pad, pad, pad, pad, cv2.BORDER_CONSTANT, value=bg)
            kps, desc = sift.detectAndCompute(gray, None)
            if desc is None:
                continue
            for kp in kps:
                kp.pt = ((kp.pt[0] - pad) * back, (kp.pt[1] - pad) * back)
            kps_all += list(kps)
            desc_all.append(desc)
    h = int(round(base.shape[0] * w0 / base.shape[1]))
    w = w0
    if not desc_all:
        raise ValueError("logo-ul nu are destule detalii pentru recunoaștere")
    corners = np.float32([[0, 0], [w, 0], [w, h], [0, h]]).reshape(-1, 1, 2)
    # Șablonul pentru verificarea fotometrică: logo-ul în gri, cu masca lui.
    th = max(8, int(round(NCC_W * h / w)))
    small = cv2.resize(base, (NCC_W, th), interpolation=cv2.INTER_AREA)
    tg = cv2.GaussianBlur(cv2.cvtColor(small[:, :, :3], cv2.COLOR_BGR2GRAY).astype(np.float32), (0, 0), 1.0)
    tmask = small[:, :, 3] > 128
    return LogoModel(kps_all, np.vstack(desc_all), w, h, corners, tg, tmask)


def _ncc(a: np.ndarray, b: np.ndarray, mask: np.ndarray) -> float:
    x, y = a[mask], b[mask]
    x = x - x.mean()
    y = y - y.mean()
    d = np.sqrt((x * x).sum() * (y * y).sum())
    return float((x * y).sum() / d) if d > 1e-6 else 0.0


def _plausible(quad: np.ndarray, frame_area: float) -> bool:
    q = quad.reshape(4, 2)
    if not cv2.isContourConvex(q.astype(np.float32)):
        return False
    area = cv2.contourArea(q.astype(np.float32))
    if area < 0.002 * frame_area or area > 0.95 * frame_area:
        return False
    sides = [np.linalg.norm(q[i] - q[(i + 1) % 4]) for i in range(4)]
    if min(sides) < 6:
        return False
    if max(sides[0], sides[2]) / max(min(sides[0], sides[2]), 1) > 3.5:
        return False
    if max(sides[1], sides[3]) / max(min(sides[1], sides[3]), 1) > 3.5:
        return False
    return True


class LogoDetector:
    def __init__(self, logo: LogoModel):
        self.logo = logo
        self.sift = _sift()
        self.matcher = cv2.FlannBasedMatcher({"algorithm": 1, "trees": 5}, {"checks": 64})

    def detect(self, frame: np.ndarray) -> dict:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        kps, desc = self.sift.detectAndCompute(gray, None)
        res = {"found": False, "inliers": 0, "quad": None}
        if desc is None or len(kps) < 4:
            return res
        cv2.setRNGSeed(0)  # FLANN folosește arbori aleatori; vrem rezultate reproductibile
        matches = self.matcher.knnMatch(self.logo.desc, desc, k=2)
        good = [m for m, *rest in matches if rest and m.distance < RATIO * rest[0].distance]
        if len(good) < MIN_INLIERS:
            return res
        src = np.float32([self.logo.kps[m.queryIdx].pt for m in good]).reshape(-1, 1, 2)
        dst = np.float32([kps[m.trainIdx].pt for m in good]).reshape(-1, 1, 2)
        H, mask = cv2.findHomography(src, dst, cv2.RANSAC, 5.0)
        if H is None:
            return res
        inl = int(mask.sum())
        res["inliers"] = inl
        if inl < MIN_INLIERS:
            return res
        quad = cv2.perspectiveTransform(self.logo.corners, H)
        if not _plausible(quad, gray.shape[0] * gray.shape[1]):
            return res
        # Verificarea fotometrică: readucem zona găsită în forma logo-ului și o
        # comparăm cu logo-ul. Potrivirile SIFT pe texturi oarecare sau pe alt logo
        # trec de geometrie, dar nu seamănă pixel cu pixel.
        L = self.logo
        S = np.diag([L.w / NCC_W, L.h / L.tmpl.shape[0], 1.0])  # șablon -> coordonatele logo-ului
        back = cv2.warpPerspective(gray, H @ S, (NCC_W, L.tmpl.shape[0]),
                                   flags=cv2.INTER_AREA | cv2.WARP_INVERSE_MAP)
        back = cv2.GaussianBlur(back.astype(np.float32), (0, 0), 1.0)
        ncc = _ncc(back, L.tmpl, L.tmask)
        res["ncc"] = round(ncc, 3)
        if ncc < NCC_MIN:
            return res
        h, w = gray.shape
        res.update(found=True, quad=(quad.reshape(4, 2) / [w, h]).round(4).tolist())
        return res


def to_intervals(samples: list[dict], step: float) -> list[dict]:
    """samples: [{t, found, inliers}] în ordine. Întoarce intervale [t0, t1)."""
    flags = [s["found"] for s in samples]
    n = len(flags)
    # umple golurile de un singur cadru
    for i in range(1, n - 1):
        if not flags[i] and flags[i - 1] and flags[i + 1]:
            flags[i] = True
    # aruncă detecțiile izolate slabe
    for i in range(n):
        if flags[i] and not (i > 0 and flags[i - 1]) and not (i < n - 1 and flags[i + 1]):
            if samples[i]["inliers"] < 2 * MIN_INLIERS:
                flags[i] = False
    out, start = [], None
    for i, f in enumerate(flags + [False]):
        if f and start is None:
            start = i
        if not f and start is not None:
            t0 = samples[start]["t"]
            t1 = samples[i - 1]["t"] + step
            best = max(range(start, i), key=lambda j: samples[j]["inliers"])
            out.append({"t0": round(t0, 2), "t1": round(t1, 2), "best_t": samples[best]["t"]})
            start = None
    return out
