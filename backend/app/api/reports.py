"""
Report generation API endpoints
"""
# business: report generation endpoints for village-friendly DOCX/HTML
# why: async job queue for long-running report builds
# constraint: polling-based status check (no WebSocket)
import logging
import asyncio

logger = logging.getLogger(__name__)
import json
import uuid
from typing import Dict, Any, Optional, List
from datetime import datetime, timezone
from io import BytesIO

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.database import get_db, SessionLocal
from app.core.rate_limit import limiter
from app.utils.auth import get_current_active_user
from app.models.user import User
from app.services.report.data_collector import collect_all_data
from app.services import forest_metadata_service
from app.services.report.section_templates import REPORT_SECTIONS, COVER_PAGE_FIELDS
from app.services.report.prompt_builder import build_prompt
from app.services.report.ai_generator import get_generator
from app.services.report.document_builder import build_report_document
from app.services.report import map_generator, chart_generator
from app.services.report.job_store import get_job, save_job, is_redis_enabled

router = APIRouter(prefix="/report", tags=["Report Generation"])


# Job state is externalized to a Redis-backed store (falls back to in-memory).
# This lets the arq worker (separate process) share state with the API.


@router.get("/{calculation_id}/data-completeness")
def check_data_completeness(
    calculation_id: str,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Check which tabs have data and which are missing for report generation"""
    try:
        data = collect_all_data(db, calculation_id)
    except Exception as e:
        logger.info(f"[REPORT] Error in data-completeness: {str(e)}")
        logger.exception("Data collection failed")
        raise HTTPException(status_code=500, detail=f"Data collection failed: {str(e)}")

    components = {
        "analysis": {
            "status": "complete" if data.get("raster_analysis", {}).get("elevation", {}).get("mean_m", 0) > 0 else "empty",
            "details": {
                "elevation": data.get("raster_analysis", {}).get("elevation", {}),
                "slope": data.get("raster_analysis", {}).get("slope", {}).get("dominant_class", ""),
                "canopy": data.get("raster_analysis", {}).get("canopy", {}).get("dominant_class", ""),
            }
        },
        "species": {
            "status": "complete" if data.get("species", {}).get("total_species", 0) > 0 else "empty",
            "details": {
                "total_species": data.get("species", {}).get("total_species", 0),
            }
        },
        "sampling": {
            "status": "complete" if data.get("sampling", {}).get("available") else "empty",
            "details": {
                "designs_count": len(data.get("sampling", {}).get("designs", [])),
            }
        },
        "inventory": {
            "status": "complete" if data.get("inventory", {}).get("available") and data.get("inventory", {}).get("total_trees", 0) > 0 else "empty",
            "details": {
                "total_trees": data.get("inventory", {}).get("total_trees", 0),
            }
        },
        "tree_model": {
            "status": "complete" if data.get("tree_model", {}).get("available") else "empty",
            "details": {
                "total_trees": data.get("tree_model", {}).get("total_trees", 0),
            }
        },
        "households": {
            "status": "complete" if data.get("households", {}).get("available") else "empty",
            "details": {
                "total_households": data.get("households", {}).get("total_households", 0),
            }
        },
        "committees": {
            "status": "complete" if data.get("committees", {}).get("user_committee", {}).get("total_members", 0) > 0 else "empty",
            "details": {
                "user_committee_members": data.get("committees", {}).get("user_committee", {}).get("total_members", 0),
            }
        },
        "biodiversity": {
            "status": "complete" if data.get("biodiversity", {}).get("available") else "empty",
            "details": {
                "total_species": data.get("biodiversity", {}).get("total_species", 0),
            }
        },
        "activities": {
            "status": "complete" if data.get("activities", {}).get("available") else "empty",
            "details": {
                "total_activities": data.get("activities", {}).get("total_activities", 0),
                "total_budget": data.get("activities", {}).get("total_budget", 0),
            }
        },
        "user_group": {
            "status": "complete" if data.get("user_group", {}).get("available") else "empty",
            "details": {
                "total_settlements": data.get("user_group", {}).get("total_settlements", 0),
            }
        },
    }

    # Calculate readiness score
    complete_count = sum(1 for c in components.values() if c["status"] == "complete")
    total_count = len(components)

    return {
        "calculation_id": calculation_id,
        "components": components,
        "readiness_score": round(complete_count / total_count, 2),
        "complete_count": complete_count,
        "total_count": total_count,
    }


@router.get("/{calculation_id}/sections-available")
def get_available_sections(
    calculation_id: str,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Get list of sections that can be generated with available data"""
    try:
        data = collect_all_data(db, calculation_id)
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"Calculation not found: {str(e)}")

    available_sections = []

    for section_num_str, section_info in REPORT_SECTIONS.items():
        section_num = int(section_num_str)
        requires = section_info.get("requires_data", [])
        auto_generate = section_info.get("auto_generate", False)

        if not requires:
            # Section doesn't require system data (may need user input)
            status = "manual_input" if section_info.get("needs_user_input") else "available"
            available_sections.append({
                "section": str(section_num),
                "title_ne": section_info.get("title_ne", ""),
                "title_en": section_info.get("title_en", ""),
                "status": status,
                "auto_generate": auto_generate,
            })
            continue

        # Check if all required data is available; keep the names of what is missing so the page can link to it
        missing = []
        for req in requires:
            req_data = data.get(req, {})
            if isinstance(req_data, dict):
                if not req_data or req_data.get("available") is False:
                    missing.append(req)
            elif not req_data:
                missing.append(req)
        all_available = not missing

        available_sections.append({
            "section": str(section_num),
            "title_ne": section_info.get("title_ne", ""),
            "title_en": section_info.get("title_en", ""),
            "status": "available" if all_available else "missing_data",
            "auto_generate": auto_generate,
            "requires": requires,
            "missing": missing,
        })

        # Handle subsections
        if "subsections" in section_info:
            subsections = []
            for sub_key, sub_info in section_info["subsections"].items():
                sub_requires = sub_info.get("requires_data", [])
                sub_all_available = True
                for req in sub_requires:
                    req_data = data.get(req, {})
                    if isinstance(req_data, dict):
                        if not req_data or req_data.get("available") is False:
                            sub_all_available = False
                            break
                    elif not req_data:
                        sub_all_available = False
                        break

                subsections.append({
                    "key": sub_key,
                    "title_ne": sub_info.get("title_ne", ""),
                    "title_en": sub_info.get("title_en", ""),
                    "status": "available" if sub_all_available else "missing_data",
                    "auto_generate": sub_info.get("auto_generate", False),
                })

            available_sections[-1]["subsections"] = subsections

    return {
        "calculation_id": calculation_id,
        "sections": available_sections,
    }


@router.post("/{calculation_id}/generate")
@limiter.limit("3/minute")
async def generate_report(
    request: Request,
    calculation_id: str,
    metadata: Optional[Dict[str, Any]] = None,
    current_user: User = Depends(get_current_active_user),
    sections: Optional[List[str]] = None,
    include_images: bool = True,
    db: Session = Depends(get_db),
):
    """Generate report sections using AI

    Args:
        calculation_id: The calculation ID
        metadata: Cover page metadata (forest_name, district, etc.). Now
            *optional* and no longer authoritative -- see below.
        sections: List of section numbers to generate (e.g., ["1", "2", "3", "7"])
                  If None, generate all available sections
        include_images: Whether to generate map/chart images

    Returns:
        job_id for tracking progress

    The cover page is a record, not a form submission
    ------------------------------------------------
    `metadata` used to be whatever the browser posted, which meant the .docx for a
    given forest depended on who pressed Generate. It is now optional and
    subordinate: `forest_metadata_service.get_for_report` overlays the saved row
    on top, and a posted value only fills a gap the record leaves. So an old
    client keeps working, and a tampered one cannot restate a forest's official
    details on a statutory document.

    A failure to read the record must not stop a report being produced, so the
    lookup is wrapped: on any error it logs and falls back to the posted values.
    Losing the cover-page guarantee is bad; refusing to export is worse.
    """
    posted = metadata or {}
    try:
        cover_metadata = forest_metadata_service.get_for_report(
            db, uuid.UUID(str(calculation_id)), posted
        )
    except Exception:
        logger.warning(
            "[REPORT] falling back to posted metadata for %s", calculation_id, exc_info=True
        )
        cover_metadata = posted

    job_id = str(uuid.uuid4())

    job = {
        "calculation_id": calculation_id,
        "metadata": cover_metadata,
        "sections_requested": sections,
        "include_images": include_images,
        "status": "processing",
        "progress": 0,
        "sections_completed": [],
        "sections_total": 0,
        "result": None,
        "error": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    save_job(job_id, job)

    if is_redis_enabled():
        # Offload to the arq worker (separate process, Redis-backed state).
        try:
            from arq import create_pool
            from arq.connections import RedisSettings
            from app.core.redis_config import redis_dsn

            pool = await create_pool(RedisSettings.from_dsn(redis_dsn()))
            await pool.enqueue_job("generate_report_task", job_id)
            logger.info(f"[REPORT] Enqueued arq job {job_id}")
        except Exception as e:  # noqa: BLE001
            # Not a warning: the worker exists precisely so generation does not
            # run on the request thread. Falling back here means it silently does.
            logger.error(
                "[REPORT] arq enqueue failed, running generation inline on the "
                "request thread: %s", e, exc_info=True,
            )
            asyncio.create_task(_run_report_generation(job_id, db))
    else:
        # No Redis: run in-process (existing behaviour).
        asyncio.create_task(_run_report_generation(job_id, db))

    return {
        "job_id": job_id,
        "status": "processing",
        "message": "Report generation started. Use /report/{job_id}/status to check progress.",
    }


async def _run_report_generation(job_id: str, db: Session):
    """Generate a report. Safe to call from the API thread or the arq worker.

    Reads/writes shared job state via the job store (Redis or in-memory).
    """
    job = get_job(job_id)
    if not job:
        logger.error(f"[REPORT] job {job_id} not found in store")
        return

    try:
        # Collect data
        data = collect_all_data(db, job["calculation_id"])

        # Determine which sections to generate
        sections_to_generate = job.get("sections_requested")
        if not sections_to_generate:
            sections_to_generate = list(REPORT_SECTIONS.keys())
        else:
            sections_to_generate = [int(s) for s in sections_to_generate]

        job["sections_total"] = len(sections_to_generate)

        generator = get_generator()
        sections_result = {}

        for idx, section_num in enumerate(sections_to_generate):
            section_key = str(section_num)
            section_info = REPORT_SECTIONS.get(section_num, {})

            # Skip sections that need manual input and weren't specifically requested
            if section_info.get("needs_user_input") and not section_info.get("auto_generate"):
                sections_result[section_key] = {
                    "title_ne": section_info.get("title_ne", ""),
                    "title_en": section_info.get("title_en", ""),
                    "content": "[This section requires manual input. Please add content later.]",
                    "status": "skipped_manual",
                }
                job["sections_completed"].append(section_key)
                job["progress"] = round((idx + 1) / job["sections_total"] * 100)
                save_job(job_id, job)
                continue

            # Handle sections with subsections
            if "subsections" in section_info:
                subsections_result = {}
                for sub_key, sub_info in section_info["subsections"].items():
                    prompt = build_prompt(section_num, sub_key, job["metadata"], data)

                    content = await generator.generate_section(prompt)

                    images = []
                    if job.get("include_images"):
                        # Generate relevant images for this subsection
                        images = _generate_subsection_images(
                            section_num, sub_key, job["metadata"], data
                        )

                    subsections_result[sub_key] = {
                        "title_ne": sub_info.get("title_ne", ""),
                        "title_en": sub_info.get("title_en", ""),
                        "content": content,
                        "images": images,
                    }

                sections_result[section_key] = {
                    "title_ne": section_info.get("title_ne", ""),
                    "title_en": section_info.get("title_en", ""),
                    "subsections": subsections_result,
                    "status": "completed",
                }
            else:
                prompt = build_prompt(section_num, None, job["metadata"], data)
                content = await generator.generate_section(prompt)

                images = []
                if job.get("include_images"):
                    images = _generate_section_images(section_num, job["metadata"], data)

                sections_result[section_key] = {
                    "title_ne": section_info.get("title_ne", ""),
                    "title_en": section_info.get("title_en", ""),
                    "content": content,
                    "images": images,
                    "status": "completed",
                }

            job["sections_completed"].append(section_key)
            job["progress"] = round((idx + 1) / job["sections_total"] * 100)
            save_job(job_id, job)

        job["status"] = "completed"
        job["progress"] = 100
        job["result"] = sections_result
        save_job(job_id, job)

    except Exception as e:
        # The job records `failed` and str(e), which the user sees - but
        # str(e) alone loses the traceback, and this is a background job
        # nobody is watching.
        logger.exception("report job %s failed", job_id)
        job["status"] = "failed"
        job["error"] = str(e)
        save_job(job_id, job)


def _generate_section_images(section_num: int, metadata: Dict, data: Dict) -> List[Dict]:
    """Generate images for a section"""
    images = []
    forest_name = metadata.get("forest_name", data.get("basic_info", {}).get("forest_name", ""))
    raster = data.get("raster_analysis", {})
    species = data.get("species", {})
    boundary = data.get("boundary", {})

    if section_num == 2:
        # Boundary map
        calc_data = data.get("basic_info", {})
        blocks = boundary.get("blocks", [])
        img = map_generator.generate_boundary_map(
            {"type": "Polygon", "coordinates": []},  # Would need actual GeoJSON
            forest_name,
            blocks
        )
        if img:
            images.append({"data": img, "caption": f"नक्सा १: {forest_name} को सीमाङ्कन नक्सा"})

    elif section_num == 3:
        # Species pie chart
        img = map_generator.generate_species_pie_chart(
            species.get("species_list", []), forest_name
        )
        if img:
            images.append({"data": img, "caption": f"चित्र १: प्रजाति संरचना"})

        # Forest type pie
        img = chart_generator.generate_forest_type_pie(
            raster.get("forest_type", {}).get("percentages", {}), forest_name
        )
        if img:
            images.append({"data": img, "caption": f"चित्र २: वन प्रकार वितरण"})

    return images


def _generate_subsection_images(section_num: int, sub_key: str, metadata: Dict, data: Dict) -> List[Dict]:
    """Generate images for a subsection"""
    images = []
    forest_name = metadata.get("forest_name", data.get("basic_info", {}).get("forest_name", ""))
    raster = data.get("raster_analysis", {})
    blocks = data.get("blocks", {})

    if section_num == 7:
        if sub_key == "क":
            # Slope pie
            img = chart_generator.generate_slope_pie(
                raster.get("slope", {}).get("percentages", {}),
                raster.get("slope", {}).get("dominant_class", ""),
                forest_name
            )
            if img:
                images.append({"data": img, "caption": f"चित्र: ढलाव वर्गीकरण"})

            # Canopy pie
            img = chart_generator.generate_canopy_pie(
                raster.get("canopy", {}).get("percentages", {}),
                raster.get("canopy", {}).get("dominant_class", ""),
                forest_name
            )
            if img:
                images.append({"data": img, "caption": f"चित्र: क्यानोपी आवरण"})

            # Landcover pie
            img = chart_generator.generate_landcover_pie(
                raster.get("landcover", {}).get("percentages", {}),
                raster.get("landcover", {}).get("dominant", ""),
                forest_name
            )
            if img:
                images.append({"data": img, "caption": f"चित्र: भू-आवरण"})

        elif sub_key == "ख":
            # Block area bar
            img = chart_generator.generate_block_area_bar(
                blocks.get("blocks", []), forest_name
            )
            if img:
                images.append({"data": img, "caption": f"चित्र: ब्लक-वार क्षेत्रफल"})

    return images


@router.get("/{job_id}/status")
def get_report_status(
    job_id: str,
    current_user: User = Depends(get_current_active_user),
):
    """Check report generation progress"""
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    return {
        "job_id": job_id,
        "status": job["status"],
        "progress": job["progress"],
        "sections_completed": job["sections_completed"],
        "sections_total": job["sections_total"],
        "error": job.get("error"),
        "created_at": job["created_at"],
    }


@router.get("/{job_id}/sections/{section_key}")
def get_section(
    job_id: str,
    section_key: str,
    current_user: User = Depends(get_current_active_user),
):
    """Get a specific section's generated content"""
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job["status"] != "completed":
        raise HTTPException(status_code=400, detail="Report not yet completed")

    result = job.get("result", {})
    section = result.get(section_key)

    if not section:
        raise HTTPException(status_code=404, detail=f"Section {section_key} not found")

    return section


@router.put("/{job_id}/sections/{section_key}")
def update_section(
    job_id: str,
    section_key: str,
    updated_data: Dict[str, Any],
    current_user: User = Depends(get_current_active_user),
):
    """Update/edit a section's content"""
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job["status"] != "completed":
        raise HTTPException(status_code=400, detail="Report not yet completed")

    result = job.get("result", {})
    section = result.get(section_key)

    if not section:
        raise HTTPException(status_code=404, detail=f"Section {section_key} not found")

    # Update content
    if "content" in updated_data:
        section["content"] = updated_data["content"]

    return {"status": "updated", "section": section_key}


@router.get("/{job_id}/download")
def download_report(
    job_id: str,
    format: str = "docx",
    current_user: User = Depends(get_current_active_user),
):
    """Download the complete report as .docx"""
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job["status"] != "completed":
        raise HTTPException(status_code=400, detail="Report not yet completed")

    try:
        logger.info(f"[REPORT] Generating .docx for job {job_id}")
        doc_buffer = build_report_document(
            metadata=job["metadata"],
            sections=job.get("result", {}),
            include_images=job.get("include_images", True),
        )

        from app.utils.file_export import build_disposition

        forest_name = job["metadata"].get("forest_name", "Community_Forest")
        _, disposition = build_disposition(forest_name, "OperationalPlan", "Report", "docx")
        doc_size = doc_buffer.tell()
        logger.info(f"[REPORT] Document generated: {doc_size} bytes")

        return StreamingResponse(
            iter([doc_buffer.getvalue()]),
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers={"Content-Disposition": disposition},
        )

    except Exception as e:
        logger.info(f"[REPORT] Document generation failed: {str(e)}")
        logger.exception("Document generation failed")
        raise HTTPException(status_code=500, detail=f"Failed to generate document: {str(e)}")


@router.get("/{job_id}/preview")
def preview_report(
    job_id: str,
    current_user: User = Depends(get_current_active_user),
):
    """Preview report as HTML"""
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job["status"] != "completed":
        raise HTTPException(status_code=400, detail="Report not yet completed")

    result = job.get("result", {})

    html_parts = ["""<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<style>
    body { font-family: 'Segoe UI', Arial, sans-serif; max-width: 900px; margin: 0 auto; padding: 20px; line-height: 1.6; }
    h1 { color: #006400; border-bottom: 2px solid #006400; padding-bottom: 10px; }
    h2 { color: #008000; margin-top: 30px; }
    h3 { color: #00a000; }
    p { margin: 10px 0; }
    img { max-width: 100%; border: 1px solid #ddd; margin: 10px 0; }
    .caption { text-align: center; color: #666; font-style: italic; font-size: 12px; }
    .manual { background: #fff3cd; padding: 10px; border-left: 4px solid #ffc107; }
</style>
</head>
<body>"""]

    # Cover page
    metadata = job["metadata"]
    html_parts.append(f"""
    <div style="text-align: center; padding: 60px 20px;">
        <h1 style="font-size: 28px; color: #006400;">सामुदायिक वन कार्य योजना</h1>
        <p style="font-size: 18px; color: #666;">COMMUNITY FOREST OPERATIONAL PLAN</p>
        <p><strong>वनको नाम:</strong> {metadata.get('forest_name', '')}</p>
        <p><strong>समूह:</strong> {metadata.get('group_name', '')}</p>
        <p><strong>अवधि:</strong> {metadata.get('fy_start', '')} देखि {metadata.get('fy_end', '')} सम्म</p>
    </div>
    <hr>""")

    # Sections
    for section_num in sorted(result.keys(), key=lambda x: int(x.split('.')[0]) if '.' not in x else int(x.split('.')[0])):
        section_data = result[section_num]

        if 'subsections' in section_data:
            html_parts.append(f'<h1>{section_num}. {section_data.get("title_ne", "")}</h1>')
            html_parts.append(f'<h3>{section_data.get("title_en", "")}</h3>')

            for sub_key, sub_data in section_data['subsections'].items():
                html_parts.append(f'<h2>{section_num}({sub_key}) {sub_data.get("title_ne", "")}</h2>')
                content = sub_data.get("content", "")
                html_parts.append(f"<p>{content}</p>")

                for img in sub_data.get("images", []):
                    html_parts.append(f'<img src="{img.get("data", "")}" alt="{img.get("caption", "")}">')
                    html_parts.append(f'<p class="caption">{img.get("caption", "")}</p>')
        else:
            html_parts.append(f'<h1>{section_num}. {section_data.get("title_ne", "")}</h1>')
            html_parts.append(f'<h3>{section_data.get("title_en", "")}</h3>')

            content = section_data.get("content", "")
            if "requires manual input" in content:
                html_parts.append(f'<div class="manual"><p>{content}</p></div>')
            else:
                html_parts.append(f"<p>{content}</p>")

            for img in section_data.get("images", []):
                html_parts.append(f'<img src="{img.get("data", "")}" alt="{img.get("caption", "")}">')
                html_parts.append(f'<p class="caption">{img.get("caption", "")}</p>')

        html_parts.append("<hr>")

    html_parts.append("</body></html>")

    return {
        "job_id": job_id,
        "html": "".join(html_parts),
    }
