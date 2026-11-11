"""Super-admin cost aggregation endpoints (Google pay-as-you-go cost per forest)."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..core.database import get_db
from ..utils.auth import require_super_admin
from ..services.calculation_cost_service import forest_cost_report
from ..schemas.admin.costs import ForestCostsResponse

router = APIRouter(prefix="/admin/costs", tags=["Admin Costs"])


@router.get("/forests", response_model=ForestCostsResponse)
def forest_costs(
    db: Session = Depends(get_db),
    current_user=Depends(require_super_admin),
):
    """Super-admin-only: aggregated pay-as-you-go compute cost per forest."""
    rows = forest_cost_report(db)
    grand_total = round(sum(r["total_cost"] for r in rows), 6)
    currency = next((r["currency"] for r in rows if r.get("currency")), "USD")
    return {"rows": rows, "grand_total": grand_total, "currency": currency}
