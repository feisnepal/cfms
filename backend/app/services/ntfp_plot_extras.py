"""What is kept about a sample plot besides its counts: the "I am here" check and the photos taken there (NTFP inventory, owner requirement 2026-10-22).

Both work in either way of recording (uploaded form or entered on the map). The check never blocks anything (see ``ntfp_presence``). A photo is a file under
``uploads/ntfp_photos/<forest id>/`` named by a random id; the name the camera gave it is kept only to show. Only real images are taken: the first bytes are looked at,
not the file name or the type the browser claims.
"""
from __future__ import annotations

import logging
import os
import shutil
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.calculation import Calculation
from app.models.ntfp_method import NtfpPlotPhoto, NtfpSamplePlot, NtfpSamplingDesign
from app.services import ntfp_presence as presence
from app.services.ntfp_design_service import DesignError

logger = logging.getLogger(__name__)

MAX_PHOTOS_PER_PLOT = 10
MAX_PHOTO_BYTES = 10 * 1024 * 1024
#: magic bytes -> content type
_SIGNATURES = ((b"\xff\xd8\xff", "image/jpeg"), (b"\x89PNG\r\n\x1a\n", "image/png"))


def photo_root() -> str:
    return os.path.join(settings.UPLOAD_DIR, "ntfp_photos")


def forest_photo_dir(calc_id: UUID) -> str:
    return os.path.join(photo_root(), str(calc_id))


def sniff(data: bytes) -> Optional[str]:
    for sig, ctype in _SIGNATURES:
        if data.startswith(sig):
            return ctype
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def _ext(ctype: str) -> str:
    return {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}[ctype]


def _plot(db: Session, calc_id: UUID, plot_number: int) -> NtfpSamplePlot:
    row = (db.query(NtfpSamplePlot).join(NtfpSamplingDesign, NtfpSamplePlot.design_id == NtfpSamplingDesign.id)
           .filter(NtfpSamplingDesign.calculation_id == calc_id, NtfpSamplePlot.plot_number == plot_number).first())
    if row is None:
        raise DesignError("unknown_plot", f"Plot {plot_number} is not in the design.")
    return row


def _presence_dict(p: NtfpSamplePlot) -> Optional[Dict[str, Any]]:
    if p.here_at is None:
        return None
    return {"latitude": p.here_latitude, "longitude": p.here_longitude, "accuracy_m": p.here_accuracy_m, "distance_m": p.here_distance_m, "verdict": p.here_verdict,
            "checked_at": p.here_at.isoformat(), "near_m": presence.NEAR_M}


def record_presence(db: Session, calc: Calculation, plot_number: int, latitude: float, longitude: float, accuracy_m: Optional[float]) -> Dict[str, Any]:
    """Compare the person's position with the plot's and keep the answer (the latest check of the plot replaces the earlier)."""
    from geoalchemy2.shape import to_shape

    plot = _plot(db, calc.id, plot_number)
    pt = to_shape(plot.location)
    distance = presence.haversine_m(latitude, longitude, pt.y, pt.x)
    plot.here_latitude, plot.here_longitude, plot.here_accuracy_m = latitude, longitude, accuracy_m
    plot.here_distance_m = round(distance, 1)
    plot.here_verdict = presence.verdict(distance, accuracy_m)
    plot.here_at = datetime.now(timezone.utc)
    db.flush()
    return _presence_dict(plot) or {}


def _photo_dict(ph: NtfpPlotPhoto) -> Dict[str, Any]:
    return {"id": str(ph.id), "file_name": ph.file_name, "content_type": ph.content_type, "size_bytes": ph.size_bytes, "caption": ph.caption,
            "latitude": ph.latitude, "longitude": ph.longitude, "created_at": ph.created_at.isoformat() if ph.created_at else None}


def plot_extras(db: Session, calc_id: UUID, plot_number: int) -> Dict[str, Any]:
    plot = _plot(db, calc_id, plot_number)
    photos = db.query(NtfpPlotPhoto).filter(NtfpPlotPhoto.plot_id == plot.id).order_by(NtfpPlotPhoto.created_at).all()
    return {"plot_number": plot_number, "presence": _presence_dict(plot), "photos": [_photo_dict(p) for p in photos]}


def all_extras(db: Session, calc_id: UUID) -> Dict[str, Any]:
    """Per plot: the verdict of its last check and how many photos it has, for the map."""
    from sqlalchemy import func

    plots = (db.query(NtfpSamplePlot).join(NtfpSamplingDesign, NtfpSamplePlot.design_id == NtfpSamplingDesign.id)
             .filter(NtfpSamplingDesign.calculation_id == calc_id).all())
    counts = dict(db.query(NtfpPlotPhoto.plot_id, func.count(NtfpPlotPhoto.id)).filter(NtfpPlotPhoto.plot_id.in_([p.id for p in plots])).group_by(NtfpPlotPhoto.plot_id).all()) if plots else {}
    return {"plots": {str(p.plot_number): {"verdict": p.here_verdict, "photos": int(counts.get(p.id, 0))} for p in plots}}


def add_photo(db: Session, calc: Calculation, user_id, plot_number: int, file_name: str, data: bytes, caption: Optional[str] = None,
              latitude: Optional[float] = None, longitude: Optional[float] = None) -> Dict[str, Any]:
    plot = _plot(db, calc.id, plot_number)
    if not data:
        raise DesignError("photo.empty", "The photo is empty.")
    if len(data) > MAX_PHOTO_BYTES:
        raise DesignError("photo.too_large", f"A photo can be at most {MAX_PHOTO_BYTES // (1024 * 1024)} MB.")
    ctype = sniff(data)
    if ctype is None:
        raise DesignError("photo.wrong_type", "Only JPEG, PNG or WebP photos are taken.")
    have = db.query(NtfpPlotPhoto).filter(NtfpPlotPhoto.plot_id == plot.id).count()
    if have >= MAX_PHOTOS_PER_PLOT:
        raise DesignError("photo.too_many", f"A plot can have at most {MAX_PHOTOS_PER_PLOT} photos. Delete one first.")
    stored = f"{uuid.uuid4().hex}{_ext(ctype)}"
    folder = forest_photo_dir(calc.id)
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, stored), "wb") as f:
        f.write(data)
    row = NtfpPlotPhoto(plot_id=plot.id, file_name=(os.path.basename(file_name or "photo") or "photo")[:255], stored_name=stored, content_type=ctype, size_bytes=len(data),
                        caption=(caption or "").strip()[:300] or None, latitude=latitude, longitude=longitude, uploaded_by=user_id)
    db.add(row)
    db.flush()
    return _photo_dict(row)


def _photo_row(db: Session, calc_id: UUID, photo_id: UUID) -> NtfpPlotPhoto:
    row = (db.query(NtfpPlotPhoto).join(NtfpSamplePlot, NtfpPlotPhoto.plot_id == NtfpSamplePlot.id).join(NtfpSamplingDesign, NtfpSamplePlot.design_id == NtfpSamplingDesign.id)
           .filter(NtfpPlotPhoto.id == photo_id, NtfpSamplingDesign.calculation_id == calc_id).first())
    if row is None:
        raise DesignError("unknown_photo", "That photo is not in this forest.")
    return row


def photo_file(db: Session, calc_id: UUID, photo_id: UUID) -> Dict[str, str]:
    row = _photo_row(db, calc_id, photo_id)
    path = os.path.join(forest_photo_dir(calc_id), row.stored_name)
    if not os.path.isfile(path):
        raise DesignError("unknown_photo", "The photo file is missing.")
    return {"path": path, "content_type": row.content_type, "file_name": row.file_name}


def delete_photo(db: Session, calc_id: UUID, photo_id: UUID) -> None:
    row = _photo_row(db, calc_id, photo_id)
    path = os.path.join(forest_photo_dir(calc_id), row.stored_name)
    db.delete(row)
    db.flush()
    try:
        os.remove(path)
    except FileNotFoundError:  # noqa: BLE001 -- already gone: the aim of the delete
        pass
    except OSError:
        logger.warning("Could not remove the photo file %s", path, exc_info=True)


def remove_forest_photos(calc_id: UUID) -> None:
    """Every photo file of a forest (the rows go with the design or the forest). Best effort: a leftover file is logged, never raised."""
    folder = forest_photo_dir(calc_id)
    if os.path.isdir(folder):
        shutil.rmtree(folder, ignore_errors=True)
