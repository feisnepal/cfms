from pydantic import BaseModel


class DfoApproveRequest(BaseModel):
    notes: str | None = None


class DfoRejectRequest(BaseModel):
    reason: str
