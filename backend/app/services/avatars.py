from io import BytesIO

from fastapi import HTTPException, status
from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy import select
from sqlalchemy.orm import Session, undefer

from app.core.time import utc_now
from app.models.organization import User
from app.services.audit import record_audit_event
from app.services.auth import AuthContext

MAX_AVATAR_BYTES = 5 * 1024 * 1024
MAX_AVATAR_PIXELS = 25_000_000
AVATAR_SIZE = (512, 512)
AVATAR_CONTENT_TYPE = "image/webp"


def avatar_url(user: User) -> str | None:
    if user.avatar_updated_at is None:
        return None
    version = int(user.avatar_updated_at.timestamp())
    return f"/auth/users/{user.id}/avatar?v={version}"


def _normalize_image(raw_image: bytes) -> bytes:
    if not raw_image:
        raise HTTPException(status_code=422, detail="Choose an image to upload.")
    if len(raw_image) > MAX_AVATAR_BYTES:
        raise HTTPException(status_code=413, detail="Profile photo must be 5 MB or smaller.")
    try:
        with Image.open(BytesIO(raw_image)) as source:
            width, height = source.size
            if width * height > MAX_AVATAR_PIXELS:
                raise HTTPException(
                    status_code=422,
                    detail="Profile photo dimensions are too large.",
                )
            source.verify()
        with Image.open(BytesIO(raw_image)) as source:
            normalized = ImageOps.exif_transpose(source)
            normalized = ImageOps.fit(
                normalized,
                AVATAR_SIZE,
                method=Image.Resampling.LANCZOS,
                centering=(0.5, 0.5),
            )
            if normalized.mode not in {"RGB", "RGBA"}:
                target_mode = "RGBA" if "transparency" in normalized.info else "RGB"
                normalized = normalized.convert(target_mode)
            output = BytesIO()
            normalized.save(output, format="WEBP", quality=86, method=6)
            return output.getvalue()
    except HTTPException:
        raise
    except (Image.DecompressionBombError, UnidentifiedImageError, OSError, ValueError) as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Upload a valid PNG, JPEG, or WebP image.",
        ) from error


def update_avatar(db: Session, current: AuthContext, raw_image: bytes) -> User:
    normalized = _normalize_image(raw_image)
    current.user.avatar_image = normalized
    current.user.avatar_content_type = AVATAR_CONTENT_TYPE
    current.user.avatar_updated_at = utc_now()
    record_audit_event(
        db,
        agency_id=current.user.agency_id,
        actor_user_id=current.user.id,
        event_type="PROFILE_PHOTO_UPDATED",
        description=f"{current.user.full_name} updated their profile photo",
    )
    db.commit()
    db.refresh(current.user)
    return current.user


def remove_avatar(db: Session, current: AuthContext) -> User:
    current.user.avatar_image = None
    current.user.avatar_content_type = None
    current.user.avatar_updated_at = None
    record_audit_event(
        db,
        agency_id=current.user.agency_id,
        actor_user_id=current.user.id,
        event_type="PROFILE_PHOTO_REMOVED",
        description=f"{current.user.full_name} removed their profile photo",
    )
    db.commit()
    db.refresh(current.user)
    return current.user


def get_agency_avatar(db: Session, current: AuthContext, user_id: int) -> tuple[bytes, str]:
    user = db.scalar(
        select(User)
        .options(undefer(User.avatar_image))
        .where(
            User.id == user_id,
            User.agency_id == current.user.agency_id,
            User.removed_at.is_(None),
        )
    )
    if user is None or user.avatar_image is None or user.avatar_content_type is None:
        raise HTTPException(status_code=404, detail="Profile photo not found.")
    return user.avatar_image, user.avatar_content_type
