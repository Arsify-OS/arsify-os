"""
Pydantic models — exact mirror of SDD Data Models section.
No additions. No renames. No extras.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field, field_validator


# ── Enums ─────────────────────────────────────────────────────────────────────

class PipelineStatus(str, Enum):
    QUEUED                  = "queued"
    GENERATING_PRD          = "generating_prd"
    GENERATING_SDD          = "generating_sdd"
    GENERATING_API_SPEC     = "generating_api_spec"
    VALIDATING_CONSISTENCY  = "validating_consistency"
    COMPLETE                = "complete"
    FAILED                  = "failed"


class ConflictSeverity(str, Enum):
    CRITICAL = "critical"
    WARNING  = "warning"


class ConflictType(str, Enum):
    ENTITY_MISMATCH   = "entity_mismatch"
    ENDPOINT_MISMATCH = "endpoint_mismatch"
    FIELD_MISMATCH    = "field_mismatch"
    FEATURE_MISSING   = "feature_missing"


# ── SDD: Conflict ──────────────────────────────────────────────────────────────

class Conflict(BaseModel):
    type:          ConflictType
    description:   str
    prd_reference: str
    sdd_reference: str
    severity:      ConflictSeverity


# ── SDD: ConsistencyResult ────────────────────────────────────────────────────

class ConsistencyResult(BaseModel):
    consistent: bool
    score:      int = Field(ge=0, le=100)
    conflicts:  list[Conflict] = Field(default_factory=list)
    summary:    str


# ── SDD: PipelineRequest ──────────────────────────────────────────────────────

class PipelineRequest(BaseModel):
    brief: str = Field(..., min_length=50, max_length=2000)

    @field_validator("brief")
    @classmethod
    def brief_must_meet_minimum(cls, v: str) -> str:
        stripped = v.strip()
        if len(stripped) < 50:
            raise ValueError(
                "Brief must be at least 50 characters. Add more context about your product."
            )
        return stripped


# ── SDD: PipelineResponse (run) ───────────────────────────────────────────────

class PipelineRunResponse(BaseModel):
    session_id: str
    status:     PipelineStatus = PipelineStatus.QUEUED


# ── SDD: Session ─────────────────────────────────────────────────────────────

class Session(BaseModel):
    session_id:          str
    brief:               str
    status:              PipelineStatus
    step:                int = 0
    attempt:             int = 0
    created_at:          str
    updated_at:          str
    completed_at:        Optional[str]              = None
    consistency_score:   Optional[int]              = None
    consistency_result:  Optional[ConsistencyResult] = None
    error:               Optional[str]              = None


# ── SDD: OutputBundle ────────────────────────────────────────────────────────

class OutputBundle(BaseModel):
    session_id:         str
    status:             PipelineStatus
    consistency_score:  Optional[int]              = None
    consistency_result: Optional[ConsistencyResult] = None
    outputs:            dict[str, str]              = Field(default_factory=dict)
