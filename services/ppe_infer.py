from __future__ import annotations
from dataclasses import dataclass
from typing import List, Optional, Dict, Tuple

import cv2
import numpy as np

try:
    from ultralytics import YOLO
except Exception as e:  # pragma: no cover
    raise RuntimeError("Ultralytics is required: pip install ultralytics") from e

# NEW: lightweight torch import only for device checks (no logic changes)
try:
    import torch
except Exception:  # pragma: no cover
    torch = None


# ───────────────────────── datatypes ─────────────────────────
@dataclass
class DetectorResult:
    any_helmet: bool
    any_vest: bool
    any_gloves: bool
    any_boots: bool
    any_compliant: bool
    hud_text: str
    counts_text: str = ""


# ───────────────────────── geometry ─────────────────────────
def xyxy_area(b: List[float] | Tuple[float, float, float, float]) -> float:
    x1, y1, x2, y2 = b
    return max(0.0, x2 - x1) * max(0.0, y2 - y1)

def iou(a, b) -> float:
    xA, yA = max(a[0], b[0]), max(a[1], b[1])
    xB, yB = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, xB - xA) * max(0.0, yB - yA)
    den = xyxy_area(a) + xyxy_area(b) - inter
    return (inter / den) if den > 0 else 0.0

def center(b) -> Tuple[float, float]:
    x1, y1, x2, y2 = b
    return ((x1 + x2) / 2.0, (y1 + y2) / 2.0)

def within(b, pt) -> bool:
    x1, y1, x2, y2 = b; x, y = pt
    return (x1 <= x <= x2) and (y1 <= y <= y2)

def fscale(h: float) -> float:
    return max(0.4, min(1.2, h / 400.0))


# ───────────────────────── drawing ─────────────────────────
def draw_person_box(img, box, lines, ok=True):
    x1, y1, x2, y2 = map(int, box)
    H, W = img.shape[:2]
    color = (0, 200, 0) if ok else (0, 0, 255)
    cv2.rectangle(img, (x1, y1), (x2, y2), color, 2)

    h = max(1, y2 - y1); fs = fscale(h)
    line_h = int(18 * fs) + 4; pad = 4
    label_h = pad * 2 + line_h * len(lines)

    y0 = max(0, y1 - label_h)
    wbg = 260
    x0 = x1
    if x0 + wbg > W:
        x0 = max(0, W - wbg)

    cv2.rectangle(img, (x0, y0), (x0 + wbg, y0 + label_h), color, -1)
    ty = y0 + pad + line_h - 6
    for t in lines:
        cv2.putText(img, t, (x0 + 6, ty), cv2.FONT_HERSHEY_SIMPLEX, fs, (255, 255, 255), 2, cv2.LINE_AA)
        ty += line_h

def draw_part_box(img, box, color, thickness=2):
    x1, y1, x2, y2 = map(int, box)
    cv2.rectangle(img, (x1, y1), (x2, y2), color, thickness)


# ───────────────────────── NMS + dedup ─────────────────────────
def nms_xyxy(boxes, scores, iou_thr=0.8):
    if len(boxes) == 0:
        return [], []
    boxes = np.array(boxes); scores = np.array(scores)
    keep_idx = []
    order = np.argsort(scores)[::-1]
    while len(order) > 0:
        i = order[0]; keep_idx.append(i)
        if len(order) == 1:
            break
        rest = order[1:]
        ious = np.array([iou(boxes[i], boxes[j]) for j in rest])
        order = rest[ious < iou_thr]
    return np.array(boxes)[keep_idx].tolist(), np.array(scores)[keep_idx].tolist()

def dedup_by_center(boxes, scores, W, H, center_eps=0.08, iou_min=0.5):
    if len(boxes) <= 1:
        return boxes
    diag = (W ** 2 + H ** 2) ** 0.5
    keep = [True] * len(boxes)
    for i in range(len(boxes)):
        if not keep[i]:
            continue
        ci = center(boxes[i])
        for j in range(i + 1, len(boxes)):
            if not keep[j]:
                continue
            cj = center(boxes[j])
            dx = ci[0] - cj[0]; dy = ci[1] - cj[1]
            if (dx * dx + dy * dy) ** 0.5 <= center_eps * diag and iou(boxes[i], boxes[j]) >= iou_min:
                si = scores[i] if scores else xyxy_area(boxes[i])
                sj = scores[j] if scores else xyxy_area(boxes[j])
                if si >= sj:
                    keep[j] = False
                else:
                    keep[i] = False
                    break
    return [b for b, k in zip(boxes, keep) if k]


# ───────────────────────── class utils ─────────────────────────
def make_maps(names: Dict[int, str]):
    id2name = {int(k): str(v).lower() for k, v in names.items()}
    name2id = {n: i for i, n in id2name.items()}
    return id2name, name2id

def find_first_id(name2id, *cands):
    for c in cands:
        if c in name2id:
            return name2id[c]
    return None

def find_any_ids(name2id, *cands):
    out = []
    for c in cands:
        if c in name2id:
            out.append(name2id[c])
    return out


# ───────────────────────── helpers (skin / edges / top-k) ─────────────────────────
def _topk_by_iou(cands, person_box, k=2, distinct_iou=0.5):
    if cands is None or len(cands) == 0:
        return []
    scored = sorted(cands, key=lambda b: iou(person_box, b), reverse=True)
    picked = []
    for b in scored:
        if all(iou(b, pb) < distinct_iou for pb in picked):
            picked.append(b)
            if len(picked) >= k:
                break
    return picked

def _safe_crop(frame: np.ndarray, box) -> Optional[np.ndarray]:
    x1, y1, x2, y2 = map(int, box)
    H, W = frame.shape[:2]
    x1 = max(0, min(W - 1, x1)); x2 = max(0, min(W - 1, x2))
    y1 = max(0, min(H - 1, y1)); y2 = max(0, min(H - 1, y2))
    if x2 <= x1 or y2 <= y1:
        return None
    return frame[y1:y2, x1:x2]

def _skin_ratio_bgr(frame: np.ndarray, box, min_side: int = 6) -> float:
    crop = _safe_crop(frame, box)
    if crop is None:
        return 0.0
    h, w = crop.shape[:2]
    if h < min_side or w < min_side:
        return 0.0

    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    ycc = cv2.cvtColor(crop, cv2.COLOR_BGR2YCrCb)

    # HSV hue lobes for skin
    mask1 = cv2.inRange(hsv, (0, 40, 50), (17, 255, 255))
    mask2 = cv2.inRange(hsv, (170, 40, 50), (180, 255, 255))
    mask_hsv = cv2.bitwise_or(mask1, mask2)

    # YCrCb skin window
    mask_ycc = cv2.inRange(ycc, (0, 133, 77), (255, 173, 135))

    mask = cv2.bitwise_or(mask_hsv, mask_ycc)
    return float(cv2.countNonZero(mask)) / float(h * w)

def _edge_density_bgr(frame: np.ndarray, box, min_side: int = 6) -> float:
    crop = _safe_crop(frame, box)
    if crop is None:
        return 0.0
    h, w = crop.shape[:2]
    if h < min_side or w < min_side:
        return 0.0
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 60, 140)
    return float(cv2.countNonZero(edges)) / float(h * w)


# ───────────────────────── compliance ─────────────────────────
def match_compliance(
    person_box, helmets, vests, gloves, boots, *,
    frame: Optional[np.ndarray] = None,
    RELAX: bool = True,
    # lenient boots defaults
    strict_boots: bool = False,
    require_two_boots: bool = False,
    skin_reject_ratio: float = 0.85,   # very soft
    boot_relax_fallback: bool = True,
):
    """
    Per-person matching with lenient BOOTS logic and multi-stage fallback.
    Returns:
      helmet_ok, vest_ok, glove_ok, boot_ok,
      best_hb, best_vb, glove_boxes (0..2), boot_boxes (0..2)
    """
    # IoU gates for each class
    HEL_IOU_T, VEST_IOU_T, GLOV_IOU_T, BOOT_IOU_T = 0.08, 0.25, 0.10, 0.05

    # Vertical bands (fractions of person height)
    HEAD_FRAC = 0.55
    HAND_MIN_FRAC, HAND_MAX_FRAC = 0.35, 0.95

    # Foot band & bottom alignment (wider + adaptive)
    FOOT_MIN_FRAC = 0.80 if strict_boots else 0.78
    FOOT_MAX_FRAC = 1.08 if strict_boots else 1.12
    BASE_ALIGN_EPS = 0.10 if strict_boots else 0.14  # |y2_boot - y2_person| <= eps*ph

    px1, py1, px2, py2 = person_box
    ph = (py2 - py1)
    p_area = xyxy_area(person_box)

    # Area sanity (relative to person)
    HEL_MIN_A, HEL_MAX_A = 0.004, 0.10
    VEST_MIN_A, VEST_MAX_A = 0.05, 0.45
    GLOV_MIN_A, GLOV_MAX_A = 0.003, 0.06
    BOOT_MIN_A = 0.0035  # lenient
    BOOT_MAX_A = 0.12

    # Alignment epsilon adapts by scale / cropping
    align_eps = BASE_ALIGN_EPS
    if ph < 160:              # small person box → easier
        align_eps *= 1.8
    if frame is not None and py2 >= 0.98 * frame.shape[0]:  # cropped at frame bottom
        align_eps *= 1.8

    # HELMET (single)
    best_hb = None
    if RELAX:
        best_hb = max(helmets, key=lambda b: iou(person_box, b), default=None)
    else:
        for hb in helmets:
            ha = xyxy_area(hb)
            if ha < HEL_MIN_A * p_area or ha > HEL_MAX_A * p_area:
                continue
            cx, cy = center(hb)
            if within(person_box, (cx, cy)) and cy <= py1 + HEAD_FRAC * ph and iou(person_box, hb) >= HEL_IOU_T:
                best_hb = hb
                break
    helmet_ok = best_hb is not None

    # VEST (single)
    best_vb = None
    if RELAX:
        best_vb = max(vests, key=lambda b: iou(person_box, b), default=None)
    else:
        for vb in vests:
            va = xyxy_area(vb)
            if va < VEST_MIN_A * p_area or va > VEST_MAX_A * p_area:
                continue
            if iou(person_box, vb) >= VEST_IOU_T:
                best_vb = vb
                break
    vest_ok = best_vb is not None

    # GLOVES (multi: up to 2) — keep hand band even in relaxed mode
    glove_boxes: List[List[float]] = []
    valid_g = []
    for gb in gloves:
        ga = xyxy_area(gb)
        if ga < GLOV_MIN_A * p_area or ga > GLOV_MAX_A * p_area:
            continue
        cx, cy = center(gb)
        if (within(person_box, (cx, cy))
            and (py1 + HAND_MIN_FRAC * ph) <= cy <= (py1 + HAND_MAX_FRAC * ph)
            and iou(person_box, gb) >= GLOV_IOU_T):
            valid_g.append(gb)
    glove_boxes = _topk_by_iou(valid_g, person_box, k=2, distinct_iou=0.5)
    glove_ok = len(glove_boxes) >= 1  # any glove is enough

    # BOOTS (multi: up to 2) — lenient filters + fallbacks
    boot_boxes: List[List[float]] = []
    strict_valid = []
    for bb in boots:
        if vest_ok and best_vb is not None and iou(bb, best_vb) >= 0.35:
            continue
        ba = xyxy_area(bb)
        if ba < BOOT_MIN_A * p_area or ba > BOOT_MAX_A * p_area:
            continue

        cx, cy = center(bb)
        if not ((py1 + FOOT_MIN_FRAC * ph) <= cy <= (py1 + FOOT_MAX_FRAC * ph)):
            continue

        y2b = bb[3]
        if abs(float(py2) - float(y2b)) > align_eps * ph:
            continue

        if frame is not None:
            hsv = _safe_crop(frame, bb)
            mean_v = float(np.mean(hsv[..., 2]))/255.0 if hsv is not None else 0.5
            mean_s = float(np.mean(hsv[..., 1]))/255.0 if hsv is not None else 0.5
            ed = _edge_density_bgr(frame, bb)

            skin_ratio = _skin_ratio_bgr(frame, bb)
            # Only reject if very skin-like AND not dark/edgy/colored
            if skin_ratio > skin_reject_ratio and not (mean_v < 0.40 or ed > 0.025 or mean_s > 0.35):
                continue

        if iou(person_box, bb) < 0.05:
            continue

        strict_valid.append(bb)

    boot_boxes = _topk_by_iou(strict_valid, person_box, k=2, distinct_iou=0.5)

    # Fallback 1
    if not boot_boxes and boot_relax_fallback:
        soft_valid = []
        for bb in boots:
            ba = xyxy_area(bb)
            if ba < 0.0032 * p_area or ba > 0.14 * p_area:
                continue
            cx, cy = center(bb)
            if not ((py1 + 0.75 * ph) <= cy <= (py1 + 1.15 * ph)):
                continue
            if iou(person_box, bb) < 0.04:
                continue
            if frame is not None:
                ed = _edge_density_bgr(frame, bb)
                if ed <= 0.015:
                    skin_ratio = _skin_ratio_bgr(frame, bb)
                    if skin_ratio > 0.90:
                        continue
            soft_valid.append(bb)
        boot_boxes = _topk_by_iou(soft_valid, person_box, k=2, distinct_iou=0.5)

    # Fallback 2
    if not boot_boxes and boot_relax_fallback:
        last_valid = []
        for bb in boots:
            cx, cy = center(bb)
            if not (py1 + 0.70 * ph <= cy <= py2 + 0.10 * ph):
                continue
            if iou(person_box, bb) < 0.03:
                continue
            last_valid.append(bb)
        boot_boxes = _topk_by_iou(last_valid, person_box, k=2, distinct_iou=0.5)

    boot_ok = len(boot_boxes) >= (2 if require_two_boots else 1)

    return helmet_ok, vest_ok, glove_ok, boot_ok, best_hb, best_vb, glove_boxes, boot_boxes


# ───────────────────────── parse helpers ─────────────────────────
def _parse_primary_helmet_vest(res, part_conf: float, fix_label_shift: bool):
    names = res.names
    _, name2id = make_maps(names)

    helmet_ids = find_any_ids(name2id, "helmet", "hardhat", "hard_hat")
    vest_ids   = find_any_ids(name2id, "vest", "safety vest", "safety_vest")
    boot_ids   = find_any_ids(name2id, "boots", "boot", "shoe", "shoes", "safety_shoes", "work_boots", "footwear")

    cls_ids = res.boxes.cls.detach().cpu().numpy().astype(int)
    xyxy    = res.boxes.xyxy.detach().cpu().numpy()
    confs   = res.boxes.conf.detach().cpu().numpy()

    raw_helmets, raw_vests, raw_boots = [], [], []
    for c, b, cf in zip(cls_ids, xyxy, confs):
        if c in helmet_ids and cf >= part_conf:
            raw_helmets.append(b.tolist())
        elif c in vest_ids and cf >= part_conf:
            raw_vests.append(b.tolist())
        elif c in boot_ids and cf >= part_conf:
            raw_boots.append(b.tolist())

    if fix_label_shift:
        helmets = raw_vests
        vests   = raw_boots
    else:
        helmets = raw_helmets
        vests   = raw_vests

    return np.array(helmets), np.array(vests)


def _parse_secondary_glove_boot(res, gb_part_conf: float):
    names = res.names
    _, name2id = make_maps(names)

    glove_ids = find_any_ids(name2id, "gloves", "glove", "hand_glove")
    boot_ids  = find_any_ids(name2id, "boots", "boot", "shoe", "shoes", "safety_shoe", "safety_shoes", "work_boots", "footwear")

    cls_ids = res.boxes.cls.detach().cpu().numpy().astype(int)
    xyxy = res.boxes.xyxy.detach().cpu().numpy()
    confs = res.boxes.conf.detach().cpu().numpy()

    raw_gloves, raw_boots = [], []
    for c, b, cf in zip(cls_ids, xyxy, confs):
        if c in glove_ids and cf >= gb_part_conf:
            raw_gloves.append(b.tolist())
        elif c in boot_ids and cf >= gb_part_conf:
            raw_boots.append(b.tolist())

    return np.array(raw_gloves), np.array(raw_boots)


def parse_person_only(res, conf_thr=0.25):
    _, name2id = make_maps(res.names)
    pid = find_first_id(name2id, "person")
    cls_ids = res.boxes.cls.detach().cpu().numpy().astype(int)
    xyxy = res.boxes.xyxy.detach().cpu().numpy()
    confs = res.boxes.conf.detach().cpu().numpy()
    persons, scores = [], []
    for c, b, cf in zip(cls_ids, xyxy, confs):
        if pid is not None and c == pid and cf >= conf_thr:
            persons.append(b.tolist()); scores.append(float(cf))
    return np.array(persons), np.array(scores)


# ───────────────────────── temporal smoothing ─────────────────────────
class _ClassState:
    def __init__(self, name: str, on_frames: int, off_frames: int, track_iou: float = 0.30):
        self.name = name
        self.need_on = max(1, on_frames)
        self.need_off = max(1, off_frames)
        self.track_iou = track_iou
        self.present = False
        self.on_count = 0
        self.off_count = 0
        self.prev_boxes: List[List[float]] = []

    def update(self, boxes: List[List[float]]):
        linked = False
        if boxes and self.prev_boxes:
            for b in boxes:
                for pb in self.prev_boxes:
                    if iou(b, pb) >= self.track_iou:
                        linked = True
                        break
                if linked:
                    break

        present_now = bool(boxes) or (linked and self.present)

        if present_now:
            self.on_count += 1
            self.off_count = 0
            if not self.present and self.on_count >= self.need_on:
                self.present = True
        else:
            self.off_count += 1
            self.on_count = 0
            if self.present and self.off_count >= self.need_off:
                self.present = False

        self.prev_boxes = boxes[:] if boxes else []
        return self.present


# ───────────────────────── main detector ─────────────────────────
class PPEDetector:
    def __init__(
        self,
        ppe_model: str,                     # primary (helmet/vest)
        person_model: str = "yolov8n.pt",
        glove_boot_model: Optional[str] = None,  # secondary (gloves/boots)
        device: str = "cpu",
        imgsz: int = 832,
        conf: float = 0.30,         # confidence for primary (HV)
        gb_conf: float = 0.25,      # confidence for secondary (GB) — easier
        iou: float = 0.70,
        part_conf: float = 0.55,    # per-box filter for PRIMARY
        gb_part_conf: float = 0.35, # per-box filter for SECONDARY (lenient)
        relax: bool = True,
        fix_label_shift: bool = True,
        show_parts: bool = True,
        person_conf: float = 0.25,
        person_iou_nms: float = 0.80,
        person_center_eps: float = 0.08,
        prefer_person_from_parts: bool = False,
        # temporal smoothing
        on_frames_helmet: int = 3,
        off_frames_helmet: int = 5,
        on_frames_other: int = 2,
        off_frames_other: int = 4,
        track_iou: float = 0.30,
        # boots settings (lenient by default)
        strict_boots: bool = False,
        require_two_boots: bool = False,
        skin_reject_ratio: float = 0.85,
        boot_relax_fallback: bool = True,
    ):
        self.imgsz = imgsz
        self.conf = conf
        self.gb_conf = gb_conf
        self.iou = iou
        self.part_conf = part_conf
        self.gb_part_conf = gb_part_conf
        self.relax = relax
        self.fix_label_shift = fix_label_shift
        self.show_parts = show_parts

        self.person_conf = person_conf
        self.person_iou_nms = person_iou_nms
        self.person_center_eps = person_center_eps
        self.prefer_person_from_parts = prefer_person_from_parts

        self.strict_boots = bool(strict_boots)
        self.require_two_boots = bool(require_two_boots)
        self.skin_reject_ratio = float(skin_reject_ratio)
        self.boot_relax_fallback = bool(boot_relax_fallback)

        # load models
        self.ppe = YOLO(ppe_model)                 # primary HV
        self.person = YOLO(person_model)           # person
        self.ppe2 = YOLO(glove_boot_model) if glove_boot_model else None  # secondary GB

        # ── Device placement with safe fallback (no logic change) ──
        # If caller asked for cuda but it's not available, fall back to cpu.
        want_cuda = str(device).startswith("cuda")
        if want_cuda and (torch is not None) and torch.cuda.is_available():
            self.device = "cuda:0"
        else:
            self.device = "cpu"

        try:
            self.ppe.to(self.device); self.person.to(self.device)
            if self.ppe2: self.ppe2.to(self.device)
        except Exception:
            self.device = "cpu"

        # Small speedup
        for m in (self.ppe, self.person, self.ppe2):
            if m is None:
                continue
            try: m.fuse()
            except Exception: pass

        # debouncers
        self._helmet_state = _ClassState("helmet", on_frames_helmet, off_frames_helmet, track_iou)
        self._vest_state   = _ClassState("vest",   on_frames_other,  off_frames_other,  track_iou)
        self._glove_state  = _ClassState("gloves", on_frames_other,  off_frames_other,  track_iou)
        self._boot_state   = _ClassState("boots",  on_frames_other,  off_frames_other,  track_iou)

    def infer(self, frame_bgr: np.ndarray):
        frame = frame_bgr.copy()
        H, W = frame.shape[:2]

        # Ultralytics can still use CPU if you don't pass device/half here,
        # so we forward the chosen device and float16 on GPU. (No logic change.)
        use_half = (self.device.startswith("cuda"))

        # PERSON pass
        r_person = self.person.predict(
            source=frame, imgsz=self.imgsz, conf=self.person_conf, iou=self.iou,
            agnostic_nms=True, verbose=False, device=self.device, half=use_half
        )[0]
        persons_p, p_scores = parse_person_only(r_person, conf_thr=self.person_conf)
        persons, _ = nms_xyxy(persons_p.tolist(),
                              p_scores.tolist() if len(persons_p)==len(p_scores) else [0]*len(persons_p),
                              iou_thr=self.person_iou_nms)
        persons = dedup_by_center(persons,
                                  p_scores.tolist() if len(persons_p)==len(p_scores) else [0]*len(persons),
                                  W, H, center_eps=self.person_center_eps, iou_min=0.5)

        # PRIMARY PPE (helmet & vest)
        r_ppe = self.ppe.predict(
            source=frame, imgsz=self.imgsz, conf=self.conf, iou=self.iou,
            agnostic_nms=True, verbose=False, device=self.device, half=use_half
        )[0]
        helmets, vests = _parse_primary_helmet_vest(
            r_ppe, self.part_conf, fix_label_shift=self.fix_label_shift
        )

        # SECONDARY PPE (gloves & boots)
        gloves = np.empty((0,4)); boots = np.empty((0,4))
        if self.ppe2 is not None:
            r_ppe2 = self.ppe2.predict(
                source=frame, imgsz=self.imgsz, conf=self.gb_conf, iou=self.iou,
                agnostic_nms=True, verbose=False, device=self.device, half=use_half
            )[0]
            gloves, boots = _parse_secondary_glove_boot(r_ppe2, self.gb_part_conf)

        counts_text = (
            f"P:{len(persons)} H:{len(helmets)} V:{len(vests)} "
            f"G:{len(gloves)} B:{len(boots)} | RELAX:{self.relax} | FIX:{self.fix_label_shift}"
        )

        # per-person matching and drawing
        matched_helmet_boxes: List[List[float]] = []
        matched_vest_boxes:   List[List[float]] = []
        matched_glove_boxes:  List[List[float]] = []
        matched_boot_boxes:   List[List[float]] = []

        any_compliant = False

        for pb in persons:
            helmet_ok, vest_ok, glove_ok, boot_ok, hb, vb, gbs, bbs = match_compliance(
                pb, helmets, vests, gloves, boots,
                frame=frame,
                RELAX=self.relax,
                strict_boots=self.strict_boots,
                require_two_boots=self.require_two_boots,
                skin_reject_ratio=self.skin_reject_ratio,
                boot_relax_fallback=self.boot_relax_fallback,
            )

            if hb is not None: matched_helmet_boxes.append(hb)
            if vb is not None: matched_vest_boxes.append(vb)
            for gb in gbs: matched_glove_boxes.append(gb)
            for bb in bbs: matched_boot_boxes.append(bb)

            if self.show_parts and hb is not None: draw_part_box(frame, hb, (60, 220, 60))
            if self.show_parts and vb is not None: draw_part_box(frame, vb, (0, 255, 255))
            if self.show_parts and gbs:
                for gb in gbs: draw_part_box(frame, gb, (255, 255, 0))
            if self.show_parts and bbs:
                for bb in bbs: draw_part_box(frame, bb, (40, 180, 255))

            draw_person_box(
                frame, pb,
                [
                    "Person",
                    f"helmet: {'ok' if helmet_ok else 'no'}",
                    f"vest:   {'ok' if vest_ok else 'no'}",
                    f"gloves: {'ok' if glove_ok else 'no'}",
                    f"boots:  {'ok' if boot_ok else 'no'}",
                ],
                ok=(helmet_ok and vest_ok and glove_ok and boot_ok)
            )

            any_compliant |= (helmet_ok and vest_ok and glove_ok and boot_ok)

        # temporal smoothing (class presence for gating)
        sm_helmet = self._helmet_state.update(matched_helmet_boxes)
        sm_vest   = self._vest_state.update(matched_vest_boxes)
        sm_glove  = self._glove_state.update(matched_glove_boxes)
        sm_boot   = self._boot_state.update(matched_boot_boxes)

        any_helmet = sm_helmet if persons else False
        any_vest   = sm_vest   if persons else False
        any_gloves = sm_glove  if persons else False
        any_boots  = sm_boot   if persons else False

        hud = (
            f"imgsz:{self.imgsz} conf:{self.conf:.2f} gb_conf:{self.gb_conf:.2f} "
            f"iou:{self.iou:.2f} part_conf:{self.part_conf:.2f} gb_part:{self.gb_part_conf:.2f} "
            f"device:{self.device} strict_boots:{self.strict_boots} "
            f"two_boots:{self.require_two_boots} relax_fallback:{self.boot_relax_fallback}"
        )

        return frame, DetectorResult(
            any_helmet=any_helmet,
            any_vest=any_vest,
            any_gloves=any_gloves,
            any_boots=any_boots,
            any_compliant=any_compliant,
            hud_text=hud,
            counts_text=counts_text,
        )
