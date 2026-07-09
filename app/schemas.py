"""Pydantic models — the typed contracts between the API, the agent, and the LLM.

Keeping these in one place means the shape of the agent's "plan" is validated
(not just trusted) every time the LLM returns JSON.
"""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


# ---- API request / response ------------------------------------------------

class AgentRequest(BaseModel):
    """Incoming body for POST /agent."""
    request: str = Field(..., min_length=3, description="Natural-language ask.")


class PlanStep(BaseModel):
    """One section the agent decided to write."""
    id: int
    title: str = Field(..., description="Heading for this section of the document.")
    instruction: str = Field(
        ..., description="What the agent should write in this section."
    )


class Plan(BaseModel):
    """The agent's self-generated execution plan (its TODO list)."""
    document_type: str = Field(
        ..., description="e.g. 'Project Plan', 'Business Report', 'SOP'."
    )
    title: str = Field(..., description="Title of the final document.")
    audience: str = Field(
        default="General business stakeholders",
        description="Who the document is for — drives tone.",
    )
    assumptions: List[str] = Field(
        default_factory=list,
        description="Assumptions the agent made for ambiguous/missing info.",
    )
    steps: List[PlanStep] = Field(..., description="Ordered sections to produce.")


class AgentResponse(BaseModel):
    """What POST /agent returns to the caller."""
    message: str
    request: str
    plan: Plan
    reflection_notes: Optional[str] = None
    sections_generated: int
    document_id: str
    download_url: str
