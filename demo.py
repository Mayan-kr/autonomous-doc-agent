"""Run the agent end-to-end on the two required test inputs, no server needed.

    python demo.py

Test 1 — a standard, well-specified business request.
Test 2 — a complex/ambiguous request where the agent must make its own
         decisions and reasonable assumptions.
"""

from __future__ import annotations

from app import docgen, orchestrator

TEST_1 = (
    "Create a project plan for launching a mobile banking app for a mid-sized "
    "credit union, including timeline, milestones, team roles, and risks."
)

TEST_2 = (
    "We need a document for the new thing we discussed — make it work for "
    "leadership. Something about improving how the team handles support tickets. "
    "Not sure on budget or timeline."
)


def run(label: str, request: str) -> None:
    print("\n" + "=" * 78)
    print(f"{label}\nREQUEST: {request}")
    print("=" * 78)

    result = orchestrator.run_agent(request)
    plan = result["plan"]

    print(f"\nDocument type : {plan.document_type}")
    print(f"Title         : {plan.title}")
    print(f"Audience      : {plan.audience}")

    if plan.assumptions:
        print("\nAgent's assumptions (for missing/ambiguous info):")
        for a in plan.assumptions:
            print(f"  - {a}")

    print("\nSelf-generated task list:")
    for step in plan.steps:
        print(f"  {step.id}. {step.title}")

    print(f"\nReflection notes : {result['reflection_notes']}")
    print(f"Sections written : {result['sections_generated']}")
    print(f"Saved document   : {docgen.path_for(result['document_id'])}")


if __name__ == "__main__":
    run("TEST 1 — STANDARD REQUEST", TEST_1)
    run("TEST 2 — COMPLEX / AMBIGUOUS REQUEST", TEST_2)
    print("\nDone. Open the .docx files in the output/ folder.\n")
