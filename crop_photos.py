from __future__ import annotations

import io
from pathlib import Path

import piexif
from PIL import Image, UnidentifiedImageError

SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png"}


def load_yolo_model(model_path: str):
    from ultralytics import YOLO
    return YOLO(model_path)


def detect_butterfly(model, image_path: Path) -> tuple[tuple[int, int, int, int], float, str | None] | None:
    results = model(str(image_path), verbose=False)
    if not results:
        return None
    boxes = results[0].boxes
    if boxes is None or len(boxes) == 0:
        return None

    best_idx = int(boxes.conf.argmax())
    conf = float(boxes.conf[best_idx])
    xyxy = boxes.xyxy[best_idx].tolist()
    box = (int(xyxy[0]), int(xyxy[1]), int(xyxy[2]), int(xyxy[3]))

    class_label = None
    if boxes.cls is not None and hasattr(model, "names"):
        cls_id = int(boxes.cls[best_idx])
        class_label = model.names.get(cls_id)

    return box, conf, class_label


def add_padding_and_square(
    box: tuple[int, int, int, int],
    img_w: int,
    img_h: int,
    padding: float = 0.20,
) -> tuple[int, int, int, int]:
    x1, y1, x2, y2 = box
    w = x2 - x1
    h = y2 - y1

    pad_x = int(w * padding)
    pad_y = int(h * padding)
    x1 -= pad_x
    y1 -= pad_y
    x2 += pad_x
    y2 += pad_y

    w = x2 - x1
    h = y2 - y1
    if w > h:
        diff = w - h
        y1 -= diff // 2
        y2 += diff - diff // 2
    elif h > w:
        diff = h - w
        x1 -= diff // 2
        x2 += diff - diff // 2

    x1 = max(0, x1)
    y1 = max(0, y1)
    x2 = min(img_w, x2)
    y2 = min(img_h, y2)
    return x1, y1, x2, y2


def _copy_exif(source_path: Path, output_bytes: bytes) -> bytes:
    try:
        exif_dict = piexif.load(str(source_path))
        exif_bytes = piexif.dump(exif_dict)
        buf = io.BytesIO(output_bytes)
        piexif.insert(exif_bytes, buf.getvalue())
        out = io.BytesIO()
        img = Image.open(io.BytesIO(output_bytes))
        img.save(out, format="JPEG", quality=92, exif=exif_bytes)
        return out.getvalue()
    except Exception:
        return output_bytes


def crop_photo(
    image_path: Path,
    output_dir: Path,
    model,
    fallback: str = "full",
) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / image_path.name

    img = Image.open(image_path).convert("RGB")
    img_w, img_h = img.size

    detection = detect_butterfly(model, image_path)

    if detection is not None:
        box, conf, class_label = detection
        sq_box = add_padding_and_square(box, img_w, img_h)
        cropped = img.crop(sq_box)
        used_fallback = False
    elif fallback == "full":
        cropped = img
        conf = None
        class_label = None
        used_fallback = True
    else:
        return {"source": image_path, "cropped": None, "confidence": None, "class_label": None, "fallback": True}

    buf = io.BytesIO()
    cropped.save(buf, format="JPEG", quality=92)
    final_bytes = _copy_exif(image_path, buf.getvalue())

    output_path.write_bytes(final_bytes)

    return {
        "source": image_path,
        "cropped": output_path,
        "confidence": conf if detection else None,
        "class_label": class_label if detection else None,
        "fallback": used_fallback if detection is None else False,
    }


def get_supported_photos(folder: Path) -> list[Path]:
    photos = []
    for ext in SUPPORTED_EXTENSIONS:
        photos.extend(folder.glob(f"*{ext}"))
        photos.extend(folder.glob(f"*{ext.upper()}"))
    valid = []
    for p in sorted(set(photos)):
        try:
            Image.open(p).verify()
            valid.append(p)
        except (UnidentifiedImageError, Exception):
            pass
    return valid


def batch_crop(
    input_dir: Path,
    output_dir: Path,
    model,
    fallback: str = "full",
) -> list[dict]:
    photos = get_supported_photos(input_dir)
    results = []
    for photo in photos:
        record = crop_photo(photo, output_dir, model, fallback=fallback)
        results.append(record)
    return results
