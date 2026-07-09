"""The autonomous agent.

Workflow:  PLAN  ->  REFLECT (self-check)  ->  EXECUTE  ->  ASSEMBLE

  1. PLAN     The LLM reads the request and writes its OWN task list:
              document type, title, assumptions, and an ordered list of sections.
  2. REFLECT  *** The mandatory engineering improvement ***
              A second LLM pass critiques the plan — is it complete, is the
              structure right, did it handle ambiguity? — and returns a
              possibly-revised plan. This is what makes the agent "decide" rather
              than blindly execute a first draft.
  3. EXECUTE  Each section is written in turn, with the earlier sections passed
              in as context so the document stays coherent.
  4. ASSEMBLE python-docx renders the sections into a polished .docx.
"""

from __future__ import annotations

from typing import Dict, Iterator, List, Tuple

from . import docgen, llm
from .schemas import Plan, PlanStep


# --------------------------------------------------------------------------- #
# 1. PLAN
# --------------------------------------------------------------------------- #
_PLANNER_SYSTEM = """You are an autonomous planning agent. Given a user's request, \
you design the structure of a professional business document.

Decide the best document type (proposal, report, project plan, meeting minutes, \
SOP, technical design, product spec, etc.), a strong title, the target audience, \
and an ordered list of 4-7 sections that fully cover the request.

If the request is ambiguous or missing details, make reasonable professional \
assumptions and record them — never ask the user questions.

Return ONLY JSON with this exact shape:
{
  "document_type": "string",
  "title": "string",
  "audience": "string",
  "assumptions": ["string", ...],
  "steps": [
    {"id": 1, "title": "Section heading", "instruction": "what to write here"},
    ...
  ]
}"""


def make_plan(request: str) -> Plan:
    """Ask the LLM to produce its own execution plan for the request."""
    data = llm.chat_json(
        [
            {"role": "system", "content": _PLANNER_SYSTEM},
            {"role": "user", "content": f"Request: {request}"},
        ],
        temperature=0.3,
    )
    return Plan(**data)


# --------------------------------------------------------------------------- #
# 2. REFLECT  (the engineering improvement)
# --------------------------------------------------------------------------- #
_REFLECT_SYSTEM = """You are a critical reviewer of document plans. Inspect the \
plan against the original request and improve it.

Check: Does it fully address the request? Is the document type appropriate? Are \
the sections well-ordered and non-overlapping? For ambiguous requests, are the \
assumptions sensible and explicit? Add, remove, reorder, or rename sections as \
needed.

Return ONLY JSON with two keys:
{
  "notes": "one or two sentences on what you changed and why",
  "plan": { ...the full improved plan in the same schema as the input... }
}"""


def reflect_on_plan(request: str, plan: Plan) -> Tuple[Plan, str]:
    """Self-check pass: critique and refine the plan. Returns (plan, notes).

    If reflection fails or returns something malformed, we keep the original
    plan — the agent degrades gracefully instead of crashing.
    """
    try:
        data = llm.chat_json(
            [
                {"role": "system", "content": _REFLECT_SYSTEM},
                {
                    "role": "user",
                    "content": (
                        f"Original request:\n{request}\n\n"
                        f"Current plan (JSON):\n{plan.model_dump_json(indent=2)}"
                    ),
                },
            ],
            temperature=0.2,
        )
        revised = Plan(**data["plan"])
        notes = str(data.get("notes", "")).strip() or "Plan reviewed; no major changes."
        return revised, notes
    except Exception as exc:  # noqa: BLE001
        print(f"[reflect] reflection skipped ({exc}); keeping original plan.")
        return plan, "Reflection pass unavailable; proceeded with the initial plan."


# --------------------------------------------------------------------------- #
# 3. EXECUTE
# --------------------------------------------------------------------------- #
_WRITER_SYSTEM = """You are an expert business writer. Write ONE section of a \
document. Be specific, professional, and concise. Formatting rules: use '- ' for \
bullets and '| a | b |' rows for tables where a table communicates better than \
prose; use **bold** only for inline emphasis. Do NOT output any Markdown heading \
lines (no '#', '##', '###') and do NOT repeat the section title — write the body \
text only. Use realistic mock data where concrete figures help."""


def write_section(
    request: str, plan: Plan, step: PlanStep, prior_titles: List[str]
) -> str:
    """Generate the body text for one section."""
    context = (
        f"Document: {plan.title} ({plan.document_type})\n"
        f"Audience: {plan.audience}\n"
        f"Original request: {request}\n"
        f"Sections already written: {', '.join(prior_titles) or 'none'}\n"
    )
    body = llm.chat(
        [
            {"role": "system", "content": _WRITER_SYSTEM},
            {
                "role": "user",
                "content": (
                    f"{context}\nNow write the section titled "
                    f'"{step.title}". Guidance: {step.instruction}'
                ),
            },
        ],
        temperature=0.6,
    )
    return body.strip()


# --------------------------------------------------------------------------- #
# Orchestration entry point (streaming)
# --------------------------------------------------------------------------- #
def run_agent_events(request: str) -> Iterator[Dict]:
    """Run the agent, yielding a progress event after each stage.

    This is the streaming core used by the Streamlit UI to show the agent
    "thinking" live. Event ``type`` is one of:

      ``plan``    -> {"plan": Plan}                        after PLAN
      ``reflect`` -> {"plan": Plan, "original": Plan,      after REFLECT
                      "notes": str}
      ``section`` -> {"index": int, "total": int,          after each section
                      "title": str, "content": str}
      ``done``    -> {"document_id", "plan", "sections",    after ASSEMBLE
                      "reflection_notes", "message"}

    ``run_agent`` (below) simply drains this generator, so the API and the UI
    share one code path.
    """
    # 1. Plan
    plan = make_plan(request)
    yield {"type": "plan", "plan": plan}

    # 2. Reflect / self-check  (the improvement)
    original_plan = plan
    plan, reflection_notes = reflect_on_plan(request, plan)
    yield {
        "type": "reflect",
        "plan": plan,
        "original": original_plan,
        "notes": reflection_notes,
    }

    # 3. Execute each planned step
    sections: List[Dict[str, str]] = []
    prior_titles: List[str] = []
    total = len(plan.steps)
    for step in plan.steps:
        content = write_section(request, plan, step, prior_titles)
        sections.append({"title": step.title, "content": content})
        prior_titles.append(step.title)
        yield {
            "type": "section",
            "index": len(sections),
            "total": total,
            "title": step.title,
            "content": content,
        }

    # 4. Assemble the .docx
    document_id = docgen.build_document(
        title=plan.title,
        doc_type=plan.document_type,
        audience=plan.audience,
        assumptions=plan.assumptions,
        sections=sections,
    )

    yield {
        "type": "done",
        "message": (
            f"Generated a {len(sections)}-section {plan.document_type.lower()} "
            f"titled '{plan.title}'."
        ),
        "request": request,
        "plan": plan,
        "reflection_notes": reflection_notes,
        "sections": sections,
        "sections_generated": len(sections),
        "document_id": document_id,
    }


def run_agent(request: str) -> Dict:
    """Full agent run. Returns a dict ready to shape into an AgentResponse."""
    final: Dict = {}
    for event in run_agent_events(request):
        if event["type"] == "done":
            final = event

    return {
        "message": final["message"],
        "request": final["request"],
        "plan": final["plan"],
        "reflection_notes": final["reflection_notes"],
        "sections_generated": final["sections_generated"],
        "document_id": final["document_id"],
    }
