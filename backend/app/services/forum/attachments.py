"""Screenshots on forum posts (``FORUM_SPEC.md`` decision 6).

Only real images are taken (the bytes are decoded, the file name is ignored). Every upload is decoded and written again, which drops EXIF
(GPS position, device) and anything hidden after the image data, turns a rotated phone photo upright, and shrinks it to a sensible size.
A member below ``FORUM_REP_UPLOAD`` may upload, but the picture stays hidden from other people until a moderator approves it
(approving the post approves its pictures).
"""
from __future__ import annotations

import io
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ...core import forum_rules as rules
from ...core.config import settings
from ...models.forum import ForumAttachment, ForumPost
from ...models.user import User
from .ledger import ForumPermissionError, ForumRuleError, get_profile, is_moderator

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def post_dir(post_id: uuid.UUID) -> str:
    return os.path.join(settings.UPLOAD_DIR, "forum", str(post_id))


def _reencode(data: bytes) -> tuple[bytes, str, str, int, int]:
    """(bytes, content type, extension, width, height) of the picture written again, or a ForumRuleError."""
    try:
        probe = Image.open(io.BytesIO(data))
        fmt = probe.format
        probe.verify()  # a second open is needed to read pixels after verify()
        image = Image.open(io.BytesIO(data))
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, SyntaxError, ValueError) as exc:
        logger.info("forum upload refused: not a readable image (%s)", type(exc).__name__)
        raise ForumRuleError("only PNG, JPEG or WebP pictures are taken") from exc
    if fmt not in rules.ATTACHMENT_TYPES:
        raise ForumRuleError("only PNG, JPEG or WebP pictures are taken")
    if image.width * image.height > rules.FORUM_IMAGE_MAX_PIXELS:
        raise ForumRuleError("that picture is too large; shrink it first")
    content_type, ext = rules.ATTACHMENT_TYPES[fmt]
    try:
        image = ImageOps.exif_transpose(image)
        image.thumbnail((rules.FORUM_IMAGE_MAX_SIDE_PX, rules.FORUM_IMAGE_MAX_SIDE_PX))
        out = io.BytesIO()
        if fmt == "JPEG":
            image.convert("RGB").save(out, "JPEG", quality=85, optimize=True)
        elif fmt == "PNG":
            image.save(out, "PNG", optimize=True)
        else:
            image.save(out, "WEBP", quality=85)
    except (OSError, ValueError) as exc:
        logger.info("forum upload refused: could not be re-encoded (%s)", type(exc).__name__)
        raise ForumRuleError("that picture could not be read") from exc
    return out.getvalue(), content_type, ext, image.width, image.height


def add_attachment(db: Session, user: User, post: ForumPost, file_name: str, data: bytes) -> ForumAttachment:
    if post.deleted_at is not None:
        raise ForumRuleError("this post is deleted")
    moderator = is_moderator(db, user)
    if post.author_id != user.id and not moderator:
        raise ForumPermissionError("only the author of a post can add pictures to it")
    if not data:
        raise ForumRuleError("the file is empty")
    if len(data) > rules.FORUM_MAX_UPLOAD_BYTES:
        raise ForumRuleError(f"a picture can be at most {rules.FORUM_MAX_UPLOAD_BYTES // (1024 * 1024)} MB")
    on_post = db.execute(select(func.count()).select_from(ForumAttachment).where(ForumAttachment.post_id == post.id)).scalar_one()
    if on_post >= rules.FORUM_MAX_ATTACHMENTS_PER_POST:
        raise ForumRuleError(f"a post can have at most {rules.FORUM_MAX_ATTACHMENTS_PER_POST} pictures")
    if not moderator:
        today = db.execute(select(func.count()).select_from(ForumAttachment).where(
            ForumAttachment.uploader_id == user.id, ForumAttachment.created_at >= _now() - timedelta(hours=24))).scalar_one()
        if today >= rules.FORUM_MAX_ATTACHMENTS_PER_DAY:
            raise ForumRuleError(f"at most {rules.FORUM_MAX_ATTACHMENTS_PER_DAY} pictures a day")
    body, content_type, ext, width, height = _reencode(data)
    stored = f"{uuid.uuid4().hex}.{ext}"
    folder = post_dir(post.id)
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, stored), "wb") as fh:
        fh.write(body)
    trusted = moderator or get_profile(db, user.id).reputation >= rules.FORUM_REP_UPLOAD
    row = ForumAttachment(post_id=post.id, uploader_id=user.id, file_name=(os.path.basename(file_name or "screenshot") or "screenshot")[:255],
                          stored_name=stored, content_type=content_type, size_bytes=len(body), width=width, height=height,
                          approved_at=_now() if trusted else None)
    db.add(row)
    db.flush()
    return row


def can_see(att: ForumAttachment, viewer: Optional[User], moderator: bool) -> bool:
    return att.approved_at is not None or moderator or (viewer is not None and att.uploader_id == viewer.id)


def for_posts(db: Session, post_ids: list[uuid.UUID], viewer: Optional[User], moderator: bool) -> dict[uuid.UUID, list[ForumAttachment]]:
    """post id -> the pictures the viewer may see, oldest first."""
    if not post_ids:
        return {}
    rows = db.execute(select(ForumAttachment).where(ForumAttachment.post_id.in_(post_ids)).order_by(ForumAttachment.created_at)).scalars().all()
    out: dict[uuid.UUID, list[ForumAttachment]] = {}
    for att in rows:
        if can_see(att, viewer, moderator):
            out.setdefault(att.post_id, []).append(att)
    return out


def file_path(att: ForumAttachment) -> Optional[str]:
    path = os.path.join(post_dir(att.post_id), att.stored_name)
    return path if os.path.isfile(path) else None


def delete_attachment(db: Session, actor: User, att: ForumAttachment) -> None:
    if att.uploader_id != actor.id and not is_moderator(db, actor):
        raise ForumPermissionError("only the uploader or a moderator can delete a picture")
    path = file_path(att)
    db.delete(att)
    db.flush()
    if path:
        try:
            os.remove(path)
        except OSError:
            logger.warning("forum picture %s: the row is gone but the file could not be removed", att.id, exc_info=True)


def approve_attachment(db: Session, actor: User, att: ForumAttachment) -> ForumAttachment:
    if not is_moderator(db, actor):
        raise ForumPermissionError("only a moderator can approve a picture")
    if att.approved_at is None:
        att.approved_at = _now()
        db.flush()
    return att


def approve_all_on_post(db: Session, post_id: uuid.UUID) -> None:
    """Approving a held post lets its pictures through too: the moderator has seen them."""
    for att in db.execute(select(ForumAttachment).where(ForumAttachment.post_id == post_id, ForumAttachment.approved_at.is_(None))).scalars():
        att.approved_at = _now()
    db.flush()
