"""FastAPI surface for the autonomous agent.

Endpoints:
  POST /agent            Run the agent on a natural-language request.
  GET  /download/{id}    Download the generated .docx.
  GET  /health           Liveness check.
"""

from __future__ import annotations

import os

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, RedirectResponse

from . import docgen, orchestrator
from .schemas import AgentRequest, AgentResponse

app = FastAPI(
    title="Autonomous Document Agent",
    description="Plans, reasons, and produces a polished Word document from a "
    "natural-language request.",
    version="1.0.0",
)


@app.get("/", include_in_schema=False)
def root() -> RedirectResponse:
    """Redirect the bare root URL to the interactive API docs."""
    return RedirectResponse(url="/docs")


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/agent", response_model=AgentResponse)
def run_agent(body: AgentRequest) -> AgentResponse:
    """Accept a request, run the plan→reflect→execute→assemble loop, return result."""
    try:
        result = orchestrator.run_agent(body.request.strip())
    except Exception as exc:  # noqa: BLE001
        # Surface a clean 500 instead of leaking a stack trace to the client.
        raise HTTPException(status_code=500, detail=f"Agent failed: {exc}") from exc

    doc_id = result["document_id"]
    return AgentResponse(
        message=result["message"],
        request=result["request"],
        plan=result["plan"],
        reflection_notes=result["reflection_notes"],
        sections_generated=result["sections_generated"],
        document_id=doc_id,
        download_url=f"/download/{doc_id}",
    )


@app.get("/download/{document_id}")
def download(document_id: str) -> FileResponse:
    """Return the generated Word document."""
    path = docgen.path_for(document_id)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Document not found.")
    return FileResponse(
        path,
        media_type=(
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        ),
        filename=f"{document_id}.docx",
    )
