"""Streamlit front-end for the Autonomous Document Agent.

Watch the agent work in real time: it plans its own outline, critiques and
rewrites that plan (the reflection step), writes each section, and hands back a
polished Word document — all streamed live.

Run locally:
    streamlit run streamlit_app.py

Deploy free on Streamlit Community Cloud:
    1. Push this repo to GitHub.
    2. share.streamlit.io -> "New app" -> pick the repo -> main file streamlit_app.py
    3. In the app's Settings -> Secrets, add:  GROQ_API_KEY = "gsk_..."
"""

from __future__ import annotations

import os
import time

import streamlit as st

st.set_page_config(
    page_title="Autonomous Document Agent",
    page_icon="🤖",
    layout="centered",
)

# --------------------------------------------------------------------------- #
# Config / secrets
# --------------------------------------------------------------------------- #
# llm.py reads GROQ_API_KEY from the environment at import time. On Streamlit
# Community Cloud, keys live in st.secrets, so bridge them into os.environ
# BEFORE importing the agent. Locally, a .env file is used instead.
for _key in ("GROQ_API_KEY", "GROQ_MODEL", "GROQ_FALLBACK_MODEL"):
    try:
        if _key in st.secrets:
            os.environ.setdefault(_key, str(st.secrets[_key]))
    except Exception:  # no secrets.toml present (local dev) — fall back to .env
        pass

try:
    from app import docgen, orchestrator
except RuntimeError:
    st.error(
        "**GROQ_API_KEY is not configured.**\n\n"
        "- On Streamlit Cloud: open **Settings → Secrets** and add "
        '`GROQ_API_KEY = "gsk_..."`\n'
        "- Locally: copy `.env.example` to `.env` and paste your key "
        "(get one free at https://console.groq.com/keys)."
    )
    st.stop()


EXAMPLES = {
    "📱 Project plan (standard)": (
        "Create a project plan for launching a mobile banking app for a "
        "mid-sized credit union, including timeline, milestones, team roles, "
        "and risks."
    ),
    "🎫 Vague leadership ask (ambiguous)": (
        "We need a document for the new thing we discussed — make it work for "
        "leadership. Something about improving how the team handles support "
        "tickets. Not sure on budget or timeline."
    ),
    "🚀 Go-to-market strategy": (
        "Draft a go-to-market strategy for a B2B AI note-taking tool targeting "
        "startup founders."
    ),
}


def _plan_summary(plan) -> None:
    """Render a plan's metadata and section list.

    Uses plain markdown (no st.expander) because this runs inside st.status,
    which is itself an expander — Streamlit forbids nesting expanders.
    """
    st.markdown(
        f"**{plan.title}**  \n"
        f"`{plan.document_type}` · for *{plan.audience}*"
    )
    if plan.assumptions:
        st.markdown("**Assumptions the agent made**")
        for a in plan.assumptions:
            st.markdown(f"- {a}")
    st.markdown("**Outline**")
    for step in plan.steps:
        st.markdown(f"{step.id}. {step.title}")


def _reflection_diff(original, revised) -> None:
    """Show what the reflection pass changed between two plans."""
    before = [s.title for s in original.steps]
    after = [s.title for s in revised.steps]
    added = [t for t in after if t not in before]
    removed = [t for t in before if t not in after]
    reordered = before != after and not added and not removed

    cols = st.columns(2)
    with cols[0]:
        st.caption("Before reflection")
        for t in before:
            st.markdown(f"- {t}")
    with cols[1]:
        st.caption("After reflection")
        for t in after:
            flag = " 🆕" if t in added else ""
            st.markdown(f"- {t}{flag}")

    chips = []
    if added:
        chips.append(f"➕ added {len(added)}")
    if removed:
        chips.append(f"➖ removed {len(removed)}")
    if reordered:
        chips.append("🔀 reordered")
    if not chips:
        chips.append("✅ plan kept as-is")
    st.info("**Reflection changed:** " + "  ·  ".join(chips))


# --------------------------------------------------------------------------- #
# Header
# --------------------------------------------------------------------------- #
st.title("🤖 Autonomous Document Agent")
st.markdown(
    "Give it a one-line request. It **plans its own outline**, "
    "**critiques and rewrites that plan**, writes every section, and returns a "
    "polished **Word document** — watch it think below."
)

with st.sidebar:
    st.header("How it works")
    st.markdown(
        "1. **Plan** — the LLM designs its own outline\n"
        "2. **Reflect** ★ — a 2nd pass critiques & improves the plan\n"
        "3. **Execute** — writes each section in context\n"
        "4. **Assemble** — renders a styled `.docx`\n\n"
        "★ The reflection step is the key idea: the agent *decides* rather "
        "than blindly executing its first draft."
    )
    st.divider()
    st.caption("Powered by Groq · Llama 3.3 70B · python-docx")


# --------------------------------------------------------------------------- #
# Input
# --------------------------------------------------------------------------- #
if "request_text" not in st.session_state:
    st.session_state.request_text = EXAMPLES["📱 Project plan (standard)"]

st.markdown("**Try an example:**")
ex_cols = st.columns(len(EXAMPLES))
for col, (label, text) in zip(ex_cols, EXAMPLES.items()):
    if col.button(label, use_container_width=True):
        st.session_state.request_text = text

request = st.text_area(
    "Your request",
    key="request_text",
    height=120,
    placeholder="e.g. Write a Q3 marketing report for our SaaS product…",
)

generate = st.button("✨ Generate document", type="primary", use_container_width=True)


# --------------------------------------------------------------------------- #
# Run
# --------------------------------------------------------------------------- #
if generate:
    if not request or len(request.strip()) < 3:
        st.warning("Please enter a request (at least a few words).")
        st.stop()

    start = time.perf_counter()
    done_event = None

    with st.status("🧠 Agent is working…", expanded=True) as status:
        try:
            for event in orchestrator.run_agent_events(request.strip()):
                kind = event["type"]

                if kind == "plan":
                    st.markdown("#### 🧠 Planned its own outline")
                    _plan_summary(event["plan"])

                elif kind == "reflect":
                    st.markdown("#### 🔍 Reflected on the plan ★")
                    st.markdown(f"> {event['notes']}")
                    _reflection_diff(event["original"], event["plan"])
                    st.markdown("#### ✍️ Writing sections")

                elif kind == "section":
                    st.markdown(
                        f"✅ **{event['index']}/{event['total']}** · "
                        f"{event['title']}"
                    )

                elif kind == "done":
                    done_event = event

            status.update(label="✅ Document ready", state="complete")
        except Exception as exc:  # noqa: BLE001
            status.update(label="❌ Agent failed", state="error")
            st.error(f"Something went wrong: {exc}")
            st.stop()

    if done_event:
        elapsed = time.perf_counter() - start
        plan = done_event["plan"]

        st.success(done_event["message"])

        m1, m2, m3 = st.columns(3)
        m1.metric("Sections", done_event["sections_generated"])
        m2.metric("Time", f"{elapsed:.1f}s")
        m3.metric("Doc type", plan.document_type)

        # Download the generated .docx.
        doc_path = docgen.path_for(done_event["document_id"])
        with open(doc_path, "rb") as fh:
            st.download_button(
                "⬇️ Download .docx",
                data=fh.read(),
                file_name=f"{plan.title.replace(' ', '_')}.docx",
                mime=(
                    "application/vnd.openxmlformats-officedocument."
                    "wordprocessingml.document"
                ),
                type="primary",
                use_container_width=True,
            )

        # Live preview of the written content.
        st.markdown("### 📄 Preview")
        if plan.assumptions:
            with st.expander("Assumptions", expanded=False):
                for a in plan.assumptions:
                    st.markdown(f"- {a}")
        for section in done_event["sections"]:
            with st.expander(section["title"], expanded=False):
                st.markdown(section["content"])
