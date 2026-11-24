import uuid
from io import BytesIO
from pathlib import Path

from fastapi import HTTPException, UploadFile, status
from PIL import Image, UnidentifiedImageError

from app.config import BASE_DIR, settings

MEDIA_ROOT = BASE_DIR / settings.MEDIA_DIR        # ochiq (/media orqali beriladi)
PRIVATE_ROOT = BASE_DIR / settings.PRIVATE_DIR    # yopiq (faqat API orqali)
IMAGE_FORMATS = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp"}
IMAGE_MIMES = {".jpg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}
AUDIO_MIMES = {
    ".m4a": "audio/mp4",
    ".mp4": "audio/mp4",
    ".webm": "audio/webm",
    ".ogg": "audio/ogg",
    ".wav": "audio/wav",
    ".mp3": "audio/mpeg",
    ".aac": "audio/aac",
}
SAFE_FILE_EXTS = {
    ".pdf": "application/pdf",
    ".txt": "text/plain; charset=utf-8",
    ".csv": "text/csv; charset=utf-8",
    ".doc": "application/msword",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xls": "application/vnd.ms-excel",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".ppt": "application/vnd.ms-powerpoint",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".zip": "application/zip",
}


def _read(file: UploadFile, limit_mb: int) -> bytes:
    limit = limit_mb * 1024 * 1024
    data = file.file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            f"Fayl hajmi {limit_mb} MB dan oshmasligi kerak",
        )
    if not data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Fayl bo'sh")
    return data


def _image_ext(data: bytes) -> str | None:
    """Rasmning haqiqiy turini aniqlaydi (fayl nomiga ishonilmaydi)."""
    try:
        with Image.open(BytesIO(data)) as img:
            fmt = img.format
            img.verify()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
        return None
    return IMAGE_FORMATS.get(fmt)


def _write(root: Path, folder: str, data: bytes, ext: str) -> str:
    target_dir = root / folder
    target_dir.mkdir(parents=True, exist_ok=True)
    name = f"{uuid.uuid4().hex}{ext}"
    (target_dir / name).write_bytes(data)
    return f"{folder}/{name}"


def save_image(file: UploadFile, folder: str) -> str:
    """Ochiq rasm (avatar, logo, tour). Nisbiy yo'l qaytaradi."""
    data = _read(file, settings.MAX_IMAGE_MB)
    ext = _image_ext(data)
    if not ext:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Faqat JPG, PNG yoki WEBP rasm qabul qilinadi"
        )
    return _write(MEDIA_ROOT, folder, data, ext)


def save_document(file: UploadFile, folder: str) -> str:
    """Maxfiy hujjat (PDF yoki rasm). private/ ga yoziladi."""
    data = _read(file, settings.MAX_DOCUMENT_MB)
    ext = ".pdf" if data.startswith(b"%PDF-") else _image_ext(data)
    if not ext:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Faqat PDF, JPG, PNG yoki WEBP qabul qilinadi"
        )
    return _write(PRIVATE_ROOT, folder, data, ext)


def _safe_path(root: Path, path: str | None) -> Path | None:
    if not path:
        return None
    target = (root / path).resolve()
    # root dan tashqariga chiqib ketishdan himoya
    if root.resolve() in target.parents and target.is_file():
        return target
    return None


def delete_file(path: str | None, private: bool = False) -> None:
    target = _safe_path(PRIVATE_ROOT if private else MEDIA_ROOT, path)
    if target:
        target.unlink(missing_ok=True)


def private_file(path: str | None) -> Path | None:
    return _safe_path(PRIVATE_ROOT, path)


def _audio_ext(data: bytes, filename: str | None) -> tuple[str, str] | None:
    # M4A / MP4: [size][ftyp...]
    if len(data) >= 12 and data[4:8] == b"ftyp":
        return ".m4a", "audio/mp4"
    # WebM / Matroska (EBML header)
    if data.startswith(b"\x1a\x45\xdf\xa3"):
        return ".webm", "audio/webm"
    if data.startswith(b"OggS"):
        return ".ogg", "audio/ogg"
    if data.startswith(b"RIFF") and len(data) >= 12 and data[8:12] == b"WAVE":
        return ".wav", "audio/wav"
    if data.startswith(b"ID3") or (len(data) >= 2 and data[0] == 0xFF and (data[1] & 0xE0) == 0xE0):
        ext = Path(filename or "").suffix.lower()
        if ext == ".aac":
            return ".aac", "audio/aac"
        return ".mp3", "audio/mpeg"
    return None


def save_chat_attachment(file: UploadFile, folder: str, kind: str) -> tuple[str, str, int]:
    """Chat media faylini `private/` ichiga saqlaydi: (nisbiy_yo'l, mime, hajm)."""
    if kind == "image":
        data = _read(file, max(settings.MAX_IMAGE_MB, 10))
        ext = _image_ext(data)
        if not ext:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, "Faqat JPG, PNG yoki WEBP rasm qabul qilinadi"
            )
        return _write(PRIVATE_ROOT, folder, data, ext), IMAGE_MIMES[ext], len(data)

    if kind == "voice":
        data = _read(file, 10)
        detected = _audio_ext(data, file.filename)
        if not detected:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, "Audio formati qo'llab-quvvatlanmaydi"
            )
        ext, mime = detected
        return _write(PRIVATE_ROOT, folder, data, ext), mime, len(data)

    # Hujjat / fayl (HTML/SVG/JS/EXE kabi xavfli turlar rad etiladi)
    data = _read(file, max(settings.MAX_DOCUMENT_MB, 15))
    if data.startswith(b"%PDF-"):
        return _write(PRIVATE_ROOT, folder, data, ".pdf"), "application/pdf", len(data)
    img_ext = _image_ext(data)
    if img_ext:
        return _write(PRIVATE_ROOT, folder, data, img_ext), IMAGE_MIMES[img_ext], len(data)

    ext = Path(file.filename or "").suffix.lower()
    if ext not in SAFE_FILE_EXTS:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Faqat PDF, rasm, Word/Excel/PowerPoint, TXT, CSV yoki ZIP fayllari ruxsat etiladi",
        )
    if ext in (".docx", ".xlsx", ".pptx", ".zip") and not data.startswith(b"PK\x03\x04"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Fayl tuzilmasi kengaytmasiga mos emas")
    return _write(PRIVATE_ROOT, folder, data, ext), SAFE_FILE_EXTS[ext], len(data)


def media_url(path: str | None) -> str | None:
    if not path:
        return None
    return f"{settings.PUBLIC_BASE_URL.rstrip('/')}/media/{path}"