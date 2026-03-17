from __future__ import annotations

from datetime import datetime, timedelta
from html import escape
from typing import Any

import streamlit as st
import streamlit.components.v1 as components

from assistant import StudyAssistant


st.set_page_config(
    page_title="StudyFlow",
    page_icon="SF",
    layout="wide",
    initial_sidebar_state="expanded",
)


SUGGESTED_PROMPTS = [
    "Explain the main topic I am studying in simpler language.",
    "Quiz me on the weakest concept in this subject.",
    "Give me a step-by-step way to solve this topic.",
    "Summarize what I should remember for an exam.",
]

TRANSFORM_ACTIONS = [
    ("simpler", "Simpler"),
    ("example", "Example"),
    ("step_by_step", "Step by Step"),
    ("real_life", "Real Life"),
    ("exam_summary", "Exam Summary"),
]


def inject_styles() -> None:
    st.markdown(
        """
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;700&family=Manrope:wght@400;500;600;700&display=swap');

        :root {
            --bg-panel: rgba(15, 23, 42, 0.78);
            --bg-panel-strong: rgba(15, 23, 42, 0.92);
            --line-soft: rgba(255, 255, 255, 0.08);
            --line-strong: rgba(255, 255, 255, 0.14);
            --text-main: #f8fafc;
            --text-soft: #cbd5e1;
            --text-muted: #94a3b8;
            --mint: #99f6e4;
            --mint-soft: rgba(45, 212, 191, 0.18);
            --blue-soft: rgba(56, 189, 248, 0.16);
            --shadow-soft: 0 18px 50px rgba(0, 0, 0, 0.25);
        }

        html, body, [class*="css"] {
            font-family: "Manrope", sans-serif;
        }

        [data-testid="stHeader"] {
            background: rgba(8, 17, 31, 0.72);
            border-bottom: 1px solid var(--line-soft);
            backdrop-filter: blur(18px);
        }

        [data-testid="stAppViewContainer"] {
            background:
                radial-gradient(circle at top left, rgba(74, 222, 128, 0.12), transparent 24%),
                radial-gradient(circle at top right, rgba(56, 189, 248, 0.14), transparent 25%),
                linear-gradient(150deg, #08111f 0%, #0f1a2f 55%, #08111f 100%);
        }

        [data-testid="stSidebar"] {
            background: linear-gradient(180deg, rgba(8, 17, 31, 0.98), rgba(15, 23, 42, 0.94));
            border-right: 1px solid rgba(255, 255, 255, 0.08);
        }

        [data-testid="stSidebar"] * {
            color: #edf2f7;
        }

        .block-container {
            max-width: 1380px;
            padding-top: 4.9rem;
            padding-bottom: 2.75rem;
        }

        .hero {
            padding: 1.5rem 1.6rem;
            border-radius: 26px;
            background: linear-gradient(135deg, rgba(15, 23, 42, 0.92), rgba(14, 116, 144, 0.55));
            border: 1px solid var(--line-soft);
            box-shadow: var(--shadow-soft);
            margin-bottom: 1.1rem;
        }

        .hero h1, .hero h3, .hero p {
            margin: 0;
            color: var(--text-main);
        }

        .hero p {
            margin-top: 0.65rem;
            color: var(--text-soft);
            line-height: 1.65;
        }

        .section-card {
            border: 1px solid var(--line-soft);
            border-radius: 22px;
            padding: 1rem 1.1rem;
            background: var(--bg-panel);
            margin-bottom: 0.9rem;
            box-shadow: var(--shadow-soft);
        }

        .section-card h3, .section-card h4, .section-card p {
            color: var(--text-main);
        }

        .section-card p {
            color: var(--text-soft);
            line-height: 1.6;
        }

        .pill {
            display: inline-block;
            padding: 0.2rem 0.55rem;
            border-radius: 999px;
            background: var(--mint-soft);
            color: var(--mint);
            font-size: 0.8rem;
            margin-bottom: 0.5rem;
        }

        .workspace-banner {
            display: grid;
            grid-template-columns: minmax(0, 1.25fr) minmax(280px, 0.95fr);
            gap: 1rem;
            padding: 1.15rem;
            margin: 0 0 1.25rem;
            border-radius: 28px;
            background:
                linear-gradient(135deg, rgba(15, 23, 42, 0.96), rgba(9, 67, 92, 0.72)),
                linear-gradient(90deg, rgba(255, 255, 255, 0.04), transparent);
            border: 1px solid var(--line-strong);
            box-shadow: var(--shadow-soft);
        }

        .workspace-banner h2,
        .workspace-banner p {
            margin: 0;
            color: var(--text-main);
        }

        .workspace-banner p {
            margin-top: 0.45rem;
            color: var(--text-soft);
            line-height: 1.65;
            max-width: 58ch;
        }

        .workspace-grid {
            display: grid;
            grid-template-columns: repeat(2, minmax(0, 1fr));
            gap: 0.75rem;
        }

        .workspace-stat {
            padding: 0.9rem 0.95rem;
            border-radius: 20px;
            background: rgba(8, 17, 31, 0.48);
            border: 1px solid var(--line-soft);
        }

        .workspace-stat span {
            display: block;
            color: var(--text-muted);
            font-size: 0.75rem;
            text-transform: uppercase;
            letter-spacing: 0.08em;
            margin-bottom: 0.25rem;
        }

        .workspace-stat strong {
            color: var(--text-main);
            font-size: 1.2rem;
            font-family: "Space Grotesk", sans-serif;
        }

        .mini-note {
            color: var(--text-muted);
            font-size: 0.9rem;
        }

        [data-baseweb="tab-list"] {
            position: sticky;
            top: 3.9rem;
            z-index: 25;
            padding: 0.5rem;
            margin: 0 0 1.15rem;
            border: 1px solid var(--line-soft);
            border-radius: 999px;
            background: rgba(8, 17, 31, 0.88);
            backdrop-filter: blur(18px);
            box-shadow: 0 14px 30px rgba(0, 0, 0, 0.18);
            gap: 0.45rem;
        }

        [data-baseweb="tab-border"] {
            display: none;
        }

        button[role="tab"] {
            min-height: 44px;
            border: 0 !important;
            border-radius: 999px !important;
            background: transparent !important;
            color: var(--text-soft) !important;
            font-family: "Space Grotesk", sans-serif !important;
            font-weight: 600 !important;
            letter-spacing: 0.01em;
            padding: 0.65rem 1rem !important;
            transition: background 0.2s ease, color 0.2s ease, transform 0.2s ease;
        }

        button[role="tab"]:hover {
            background: rgba(255, 255, 255, 0.06) !important;
            color: var(--text-main) !important;
            transform: translateY(-1px);
        }

        button[role="tab"][aria-selected="true"] {
            background: linear-gradient(90deg, rgba(45, 212, 191, 0.28), rgba(56, 189, 248, 0.26)) !important;
            color: var(--text-main) !important;
            box-shadow: inset 0 0 0 1px rgba(153, 246, 228, 0.14);
        }

        [data-testid="stMetric"] {
            background: rgba(8, 17, 31, 0.35);
            border: 1px solid var(--line-soft);
            padding: 0.85rem 0.9rem;
            border-radius: 18px;
        }

        [data-testid="stMetricLabel"],
        [data-testid="stMetricValue"] {
            color: var(--text-main);
        }

        [data-testid="stExpander"] {
            border: 1px solid var(--line-soft);
            border-radius: 18px;
            background: rgba(15, 23, 42, 0.6);
        }

        .stChatMessage {
            border: 1px solid var(--line-soft);
            border-radius: 22px;
            background: rgba(15, 23, 42, 0.56);
            box-shadow: var(--shadow-soft);
            padding: 0.2rem 0.35rem;
        }

        [data-testid="stForm"],
        .stAlert,
        .stTextInput > div,
        .stTextArea > div,
        .stSelectbox > div {
            border-radius: 18px;
        }

        .stTextInput input,
        .stTextArea textarea,
        .stSelectbox [data-baseweb="select"] > div {
            background: rgba(8, 17, 31, 0.72) !important;
            border: 1px solid var(--line-soft) !important;
            color: var(--text-main) !important;
        }

        .stButton > button,
        .stFormSubmitButton > button,
        .stDownloadButton > button {
            border: 0;
            border-radius: 16px;
            background: linear-gradient(90deg, rgba(45, 212, 191, 0.95), rgba(56, 189, 248, 0.92));
            color: #04111c;
            font-family: "Space Grotesk", sans-serif;
            font-weight: 700;
            box-shadow: 0 12px 26px rgba(45, 212, 191, 0.18);
        }

        .stButton > button:hover,
        .stFormSubmitButton > button:hover,
        .stDownloadButton > button:hover {
            transform: translateY(-1px);
            box-shadow: 0 16px 32px rgba(45, 212, 191, 0.22);
        }

        @media (max-width: 1100px) {
            .workspace-banner {
                grid-template-columns: 1fr;
            }
        }

        @media (max-width: 900px) {
            .block-container {
                padding-top: 5.4rem;
            }

            .workspace-grid {
                grid-template-columns: 1fr;
            }

            [data-baseweb="tab-list"] {
                top: 3.6rem;
                overflow-x: auto;
                white-space: nowrap;
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_workspace_banner(dashboard: dict[str, Any]) -> None:
    """Show a compact top-level summary before the tab sections."""
    st.markdown(
        f"""
        <section class="workspace-banner">
            <div>
                <div class="pill">Active Workspace</div>
                <h2>{escape(dashboard['subject']['name'])}</h2>
                <p>
                    {escape(dashboard['profile']['name'])} is active. Jump between tutoring, plans, flashcards,
                    quizzes, and library tools without losing subject context.
                </p>
            </div>
            <div class="workspace-grid">
                <div class="workspace-stat">
                    <span>Due Now</span>
                    <strong>{dashboard['due_cards']}</strong>
                </div>
                <div class="workspace-stat">
                    <span>Quiz Average</span>
                    <strong>{dashboard['average_score']:.0f}%</strong>
                </div>
                <div class="workspace-stat">
                    <span>Study Streak</span>
                    <strong>{dashboard['streak_days']} days</strong>
                </div>
                <div class="workspace-stat">
                    <span>Saved Notes</span>
                    <strong>{dashboard['notes_count']}</strong>
                </div>
            </div>
        </section>
        """,
        unsafe_allow_html=True,
    )


def init_ui_state() -> None:
    """Create the Streamlit session keys used across the workspace."""
    st.session_state.setdefault("assistant_error", "")
    st.session_state.setdefault("active_profile_id", None)
    st.session_state.setdefault("active_subject_id", None)
    st.session_state.setdefault("auth_error", "")
    st.session_state.setdefault("current_quiz_id", None)
    st.session_state.setdefault("quiz_started_at", None)
    st.session_state.setdefault("quiz_result", None)
    st.session_state.setdefault("active_flashcard_id", None)
    st.session_state.setdefault("show_flashcard_answer", False)

    if "assistant" not in st.session_state:
        try:
            st.session_state.assistant = StudyAssistant()
        except Exception as exc:  # pragma: no cover - defensive UI guard
            st.session_state.assistant = None
            st.session_state.assistant_error = str(exc)


def reset_workspace_state() -> None:
    """Clear per-tab state whenever the active scope changes."""
    st.session_state.current_quiz_id = None
    st.session_state.quiz_started_at = None
    st.session_state.quiz_result = None
    st.session_state.active_flashcard_id = None
    st.session_state.show_flashcard_answer = False


def render_unlock_screen() -> bool:
    """Render the local unlock screen until a profile is active."""
    assistant = st.session_state.assistant
    if assistant is None:
        st.error(st.session_state.assistant_error or "Assistant failed to initialize.")
        return False
    if st.session_state.active_profile_id is not None:
        return True

    profiles = assistant.memory_db.list_profiles()
    selected_profile_id = profiles[0]["id"] if profiles else None

    st.markdown(
        """
        <div class="hero">
            <div class="pill">Local Profiles</div>
            <h1>Unlock your study workspace.</h1>
            <p>Profiles stay local to this machine. Notes, quizzes, flashcards, plans, and weak areas are isolated per profile and per subject.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    left, right = st.columns([1.1, 0.9], gap="large")
    with left:
        st.subheader("Unlock a profile")
        selected_profile_id = st.selectbox(
            "Profile",
            options=[profile["id"] for profile in profiles],
            format_func=lambda profile_id: next(
                profile["name"] for profile in profiles if profile["id"] == profile_id
            ),
            key="login_profile_id",
        )
        pin = st.text_input("PIN", type="password", key="login_pin")
        if st.button("Unlock", use_container_width=True):
            if assistant.memory_db.verify_profile(selected_profile_id, pin):
                default_subject = assistant.memory_db.get_default_subject(selected_profile_id)
                st.session_state.active_profile_id = selected_profile_id
                st.session_state.active_subject_id = default_subject["id"]
                assistant.set_scope(selected_profile_id, default_subject["id"])
                st.session_state.auth_error = ""
                reset_workspace_state()
                st.rerun()
            else:
                st.session_state.auth_error = "Invalid PIN."

        if st.session_state.auth_error:
            st.error(st.session_state.auth_error)
        st.caption("Default seeded profile: `Default` with PIN `0000`.")

    with right:
        st.subheader("Create a new profile")
        with st.form("create_profile_form", clear_on_submit=True):
            name = st.text_input("Profile name")
            pin = st.text_input("PIN (4-8 digits)", type="password")
            confirm_pin = st.text_input("Confirm PIN", type="password")
            submitted = st.form_submit_button("Create profile", use_container_width=True)
        if submitted:
            try:
                if pin != confirm_pin:
                    raise ValueError("PIN confirmation does not match.")
                profile = assistant.memory_db.create_profile(name, pin)
                default_subject = assistant.memory_db.get_default_subject(profile["id"])
                st.session_state.active_profile_id = profile["id"]
                st.session_state.active_subject_id = default_subject["id"]
                assistant.set_scope(profile["id"], default_subject["id"])
                reset_workspace_state()
                st.rerun()
            except Exception as exc:
                st.error(str(exc))

    return False


def get_active_session() -> tuple[StudyAssistant, int, int]:
    """Return the active assistant plus the selected profile and subject ids."""
    assistant = st.session_state.assistant
    if assistant is None:
        raise RuntimeError(st.session_state.assistant_error or "Assistant unavailable.")
    profile_id = st.session_state.active_profile_id
    subject_id = st.session_state.active_subject_id
    if profile_id is None or subject_id is None:
        raise RuntimeError("No active profile or subject.")
    assistant.set_scope(profile_id, subject_id)
    return assistant, profile_id, subject_id


def render_sidebar_controls(assistant: StudyAssistant, dashboard: dict[str, Any]) -> None:
    """Render sidebar actions for profile switching, subject switching, and quick stats."""
    profile_id = st.session_state.active_profile_id
    subject_id = st.session_state.active_subject_id
    profile = dashboard["profile"]
    subjects = assistant.memory_db.list_subjects(profile_id)
    profiles = assistant.memory_db.list_profiles()

    with st.sidebar:
        st.markdown("## StudyFlow")
        st.caption("Profile and subject-scoped study workspace")

        st.markdown(
            f"""
            <div class="section-card">
                <div class="pill">Active Profile</div>
                <h3>{escape(profile['name'])}</h3>
                <p>Current subject: <strong>{escape(dashboard['subject']['name'])}</strong></p>
            </div>
            """,
            unsafe_allow_html=True,
        )

        st.markdown("### Quick Stats")
        top_left, top_right = st.columns(2)
        top_left.metric("Due", dashboard["due_cards"])
        top_right.metric("Avg Quiz", f"{dashboard['average_score']:.0f}%")
        bottom_left, bottom_right = st.columns(2)
        bottom_left.metric("Notes", dashboard["notes_count"])
        bottom_right.metric("Streak", dashboard["streak_days"])

        st.markdown("### Switch Profile")
        switch_profile_id = st.selectbox(
            "Select profile",
            options=[item["id"] for item in profiles],
            format_func=lambda item_id: next(item["name"] for item in profiles if item["id"] == item_id),
            index=next(index for index, item in enumerate(profiles) if item["id"] == profile_id),
            key="sidebar_profile_selector",
        )
        switch_pin = st.text_input("PIN to switch", type="password", key="sidebar_switch_pin")
        if st.button("Switch profile", use_container_width=True):
            if assistant.memory_db.verify_profile(switch_profile_id, switch_pin):
                new_subject = assistant.memory_db.get_default_subject(switch_profile_id)
                st.session_state.active_profile_id = switch_profile_id
                st.session_state.active_subject_id = new_subject["id"]
                reset_workspace_state()
                st.rerun()
            else:
                st.error("Invalid PIN.")

        with st.expander("Create profile"):
            with st.form("sidebar_create_profile", clear_on_submit=True):
                new_name = st.text_input("Name", key="sidebar_profile_name")
                new_pin = st.text_input("PIN", type="password", key="sidebar_profile_pin")
                new_pin_confirm = st.text_input(
                    "Confirm PIN", type="password", key="sidebar_profile_pin_confirm"
                )
                created = st.form_submit_button("Add profile", use_container_width=True)
            if created:
                try:
                    if new_pin != new_pin_confirm:
                        raise ValueError("PIN confirmation does not match.")
                    assistant.memory_db.create_profile(new_name, new_pin)
                    st.rerun()
                except Exception as exc:
                    st.error(str(exc))

        st.markdown("### Subject")
        subject_ids = [item["id"] for item in subjects]
        selected_subject_id = st.selectbox(
            "Active subject",
            options=subject_ids,
            format_func=lambda item_id: next(item["name"] for item in subjects if item["id"] == item_id),
            index=subject_ids.index(subject_id),
            key="sidebar_subject_selector",
        )
        if selected_subject_id != subject_id:
            st.session_state.active_subject_id = selected_subject_id
            reset_workspace_state()
            st.rerun()

        with st.expander("Manage subjects"):
            with st.form("create_subject_form", clear_on_submit=True):
                new_subject_name = st.text_input("New subject name")
                add_subject = st.form_submit_button("Create subject", use_container_width=True)
            if add_subject:
                try:
                    subject = assistant.memory_db.create_subject(profile_id, new_subject_name)
                    st.session_state.active_subject_id = subject["id"]
                    reset_workspace_state()
                    st.rerun()
                except Exception as exc:
                    st.error(str(exc))

            current_subject = assistant.memory_db.get_subject(subject_id)
            renamed = st.text_input(
                "Rename current subject",
                value=current_subject["name"],
                key=f"rename_subject_value_{subject_id}",
            )
            if st.button("Rename subject", use_container_width=True):
                try:
                    assistant.memory_db.rename_subject(subject_id, renamed)
                    st.rerun()
                except Exception as exc:
                    st.error(str(exc))

            delete_disabled = len(subjects) <= 1
            if st.button(
                "Delete current subject",
                use_container_width=True,
                disabled=delete_disabled,
            ):
                try:
                    assistant.memory_db.delete_subject(subject_id)
                    new_subject = assistant.memory_db.get_default_subject(profile_id)
                    st.session_state.active_subject_id = new_subject["id"]
                    reset_workspace_state()
                    st.rerun()
                except Exception as exc:
                    st.error(str(exc))

        if st.button("Log out", use_container_width=True):
            st.session_state.active_profile_id = None
            st.session_state.active_subject_id = None
            st.session_state.auth_error = ""
            reset_workspace_state()
            st.rerun()


def render_message(role: str, content: str, caption: str | None = None) -> None:
    with st.chat_message("user" if role == "user" else "assistant"):
        if caption:
            st.caption(caption)
        st.markdown(content)


def render_dashboard_tab(assistant: StudyAssistant, profile_id: int, subject_id: int) -> None:
    dashboard = assistant.get_dashboard(profile_id, subject_id)
    st.markdown(
        f"""
        <div class="hero">
            <div class="pill">{escape(dashboard['profile']['name'])} / {escape(dashboard['subject']['name'])}</div>
            <h1>Dashboard</h1>
            <p>Track progress, spot weak areas, and see what needs review next for the active subject.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    metric_columns = st.columns(6)
    metric_columns[0].metric("Streak", dashboard["streak_days"])
    metric_columns[1].metric("Quiz Avg", f"{dashboard['average_score']:.0f}%")
    metric_columns[2].metric("Due Cards", dashboard["due_cards"])
    metric_columns[3].metric("Notes", dashboard["notes_count"])
    metric_columns[4].metric("Chats", dashboard["interactions"])
    metric_columns[5].metric("Minutes", dashboard["time_spent_minutes"])

    left, right = st.columns([1.05, 0.95], gap="large")
    with left:
        st.subheader("Top Weak Areas")
        weak_areas = dashboard["weak_areas"]
        if weak_areas:
            for item in weak_areas:
                st.markdown(
                    f"""
                    <div class="section-card">
                        <div class="pill">Severity {item['severity']:.1f}</div>
                        <h4>{escape(item['concept'])}</h4>
                        <p>Hits: {item['hit_count']} · Last seen: {escape(item['last_seen'])} · Source: {escape(item['source'])}</p>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
        else:
            st.info("Weak areas will appear after missed quiz answers or low-confidence flashcard reviews.")

        st.subheader("Recent Activity")
        if dashboard["recent_activity"]:
            for session in dashboard["recent_activity"]:
                score_text = f" · Score {session['score']:.0f}%" if session["score"] is not None else ""
                st.markdown(
                    f"- `{session['created_at']}` `{session['session_type']}` {session['summary'] or ''}{score_text}"
                )
        else:
            st.caption("No study activity logged for this subject yet.")

    with right:
        st.subheader("Current Focus")
        if dashboard["due_cards"] or dashboard["weak_areas"]:
            st.markdown(
                f"""
                <div class="section-card">
                    <h3>Today</h3>
                    <p>Due flashcards: <strong>{dashboard['due_cards']}</strong></p>
                    <p>Priority topics: {escape(', '.join(item['concept'] for item in dashboard['weak_areas']) or 'Start a quiz to discover gaps.')}</p>
                </div>
                """,
                unsafe_allow_html=True,
            )
        if dashboard["plans"]:
            latest_plan = dashboard["plans"][0]
            st.subheader("Latest Study Plan")
            st.markdown(latest_plan["content"])
        else:
            st.info("Generate a study plan from the Plans tab.")

        st.subheader("Latest Materials")
        if dashboard["documents"]:
            for doc in dashboard["documents"]:
                st.markdown(
                    f"""
                    <div class="section-card">
                        <div class="pill">{escape(doc['source_type'])}</div>
                        <h4>{escape(doc['title'])}</h4>
                        <p class="mini-note">Added {escape(doc['created_at'])}</p>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
        else:
            st.caption("Upload notes in Library to build the study context.")


def render_tutor_tab(assistant: StudyAssistant, profile_id: int, subject_id: int) -> None:
    st.subheader("Tutor")
    st.caption("Chat with subject-scoped memory, uploaded materials, and one-click explain-differently actions.")

    prompt_columns = st.columns(4)
    selected_prompt = ""
    for index, suggestion in enumerate(SUGGESTED_PROMPTS):
        if prompt_columns[index].button(suggestion, key=f"prompt_{index}"):
            selected_prompt = suggestion

    turns = assistant.memory_db.list_conversations(profile_id, subject_id, limit=40)
    if not turns:
        st.info("No conversation yet. Ask a question or use one of the prompts above.")
    for turn in turns:
        user_message = turn["user_message"]
        if user_message.startswith("[Action:"):
            action_label = user_message.split("]", 1)[0].replace("[Action:", "")
            render_message("assistant", turn["assistant_message"], caption=f"Transform: {action_label}")
            continue
        render_message("user", user_message)
        render_message("assistant", turn["assistant_message"])

    if turns:
        st.markdown("### Explain Differently")
        action_columns = st.columns(len(TRANSFORM_ACTIONS))
        for index, (mode, label) in enumerate(TRANSFORM_ACTIONS):
            if action_columns[index].button(label, key=f"transform_{mode}", use_container_width=True):
                try:
                    assistant.transform_last_response(mode)
                    st.rerun()
                except Exception as exc:
                    st.error(str(exc))

    user_prompt = st.chat_input("Ask a question about the active subject...")
    selected_prompt = user_prompt or selected_prompt
    if selected_prompt:
        try:
            assistant.chat(selected_prompt, subject_id=subject_id)
            st.rerun()
        except Exception as exc:
            st.error(str(exc))


def render_plans_tab(assistant: StudyAssistant, subject_id: int) -> None:
    st.subheader("Plans")
    st.caption("Generate dated study plans from weak areas, uploaded notes, and recent tutoring history.")

    with st.form("study_plan_form", clear_on_submit=False):
        goal = st.text_input("Goal", placeholder="Example: Prepare for a biology quiz on cell respiration")
        exam_date = st.text_input("Exam date (optional YYYY-MM-DD)")
        days_per_week = st.slider("Days per week", min_value=1, max_value=7, value=5)
        minutes_per_day = st.slider("Minutes per day", min_value=15, max_value=180, step=5, value=45)
        focus_mode = st.selectbox("Focus mode", options=["weakness_first", "balanced", "coverage_first"])
        submitted = st.form_submit_button("Generate plan", use_container_width=True)
    if submitted:
        try:
            assistant.generate_study_plan(
                subject_id=subject_id,
                goal=goal,
                exam_date=exam_date.strip() or None,
                days_per_week=days_per_week,
                minutes_per_day=minutes_per_day,
                focus_mode=focus_mode,
            )
            st.rerun()
        except Exception as exc:
            st.error(str(exc))

    plans = assistant.memory_db.list_study_plans(assistant.profile_id, subject_id, limit=8)
    if not plans:
        st.info("No study plans yet.")
        return
    for plan in plans:
        with st.expander(f"{plan['title']} · {plan['created_at']}", expanded=False):
            st.markdown(plan["content"])


def render_flashcards_tab(assistant: StudyAssistant, profile_id: int, subject_id: int) -> None:
    st.subheader("Flashcards")
    st.caption("Generate cards from subject material and review the due queue with spaced repetition.")

    card_columns = st.columns([0.8, 0.6, 0.6, 0.8])
    source_scope = card_columns[0].selectbox(
        "Source scope",
        options=["hybrid", "documents", "conversations"],
        key="flashcard_source_scope",
    )
    count = card_columns[1].slider("Card count", min_value=3, max_value=20, value=6, key="flashcard_count")
    total_cards = len(assistant.memory_db.list_flashcards(profile_id, subject_id, limit=100))
    due_cards = assistant.memory_db.list_flashcards(profile_id, subject_id, due_only=True, limit=20)
    card_columns[2].metric("Due today", len(due_cards))
    card_columns[3].metric("Total cards", total_cards)

    if st.button("Generate flashcards", use_container_width=True):
        try:
            assistant.generate_flashcards(subject_id=subject_id, source_scope=source_scope, count=count)
            reset_workspace_state()
            st.rerun()
        except Exception as exc:
            st.error(str(exc))

    due_cards = assistant.memory_db.list_flashcards(profile_id, subject_id, due_only=True, limit=20)
    if not due_cards:
        st.info("No flashcards are due. Generate cards or come back after the next review date.")
        return

    due_card_ids = [card["id"] for card in due_cards]
    if st.session_state.active_flashcard_id not in due_card_ids:
        st.session_state.active_flashcard_id = due_card_ids[0]
        st.session_state.show_flashcard_answer = False

    card = assistant.memory_db.get_flashcard(st.session_state.active_flashcard_id)
    st.markdown(
        f"""
        <div class="section-card">
            <div class="pill">Due Card</div>
            <h3>{escape(card['front'])}</h3>
            <p>Tags: {escape(', '.join(card['tags']) or 'No tags')}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if st.button(
        "Show answer" if not st.session_state.show_flashcard_answer else "Hide answer",
        use_container_width=True,
    ):
        st.session_state.show_flashcard_answer = not st.session_state.show_flashcard_answer
        st.rerun()

    if st.session_state.show_flashcard_answer:
        st.markdown(
            f"""
            <div class="section-card">
                <div class="pill">Back</div>
                <p>{escape(card['back'])}</p>
            </div>
            """,
            unsafe_allow_html=True,
        )
        rating_columns = st.columns(4)
        for index, rating in enumerate(["again", "hard", "good", "easy"]):
            if rating_columns[index].button(rating.title(), key=f"rate_{rating}", use_container_width=True):
                try:
                    assistant.review_flashcard(card["id"], rating)
                    st.session_state.show_flashcard_answer = False
                    st.session_state.active_flashcard_id = None
                    st.rerun()
                except Exception as exc:
                    st.error(str(exc))

    st.markdown("### Upcoming Queue")
    for queued_card in assistant.memory_db.list_flashcards(profile_id, subject_id, limit=6):
        st.markdown(
            f"- `{queued_card['next_due_at']}` {queued_card['front']}"
        )


def question_state_key(quiz_id: int, index: int) -> str:
    return f"quiz_{quiz_id}_{index}"


def collect_quiz_responses(quiz: dict[str, Any]) -> dict[str, Any]:
    return {
        str(index): st.session_state.get(question_state_key(quiz["id"], index), "")
        for index, _question in enumerate(quiz["questions"])
    }


def render_quiz_countdown(quiz: dict[str, Any]) -> bool:
    """Show the timer for timed quizzes and signal when it has expired."""
    time_limit = quiz.get("time_limit_minutes")
    if not time_limit or not st.session_state.quiz_started_at:
        return False
    started_at = datetime.fromisoformat(st.session_state.quiz_started_at)
    expires_at = started_at + timedelta(minutes=time_limit)  # type: ignore[name-defined]
    remaining = int((expires_at - datetime.now()).total_seconds())
    if remaining <= 0:
        st.warning("Time expired. Your quiz has been auto-submitted.")
        return True
    minutes, seconds = divmod(remaining, 60)
    st.info(f"Time remaining: {minutes:02d}:{seconds:02d}")
    components.html(
        """
        <script>
        setTimeout(function () {
            window.parent.location.reload();
        }, 1000);
        </script>
        """,
        height=0,
    )
    return False


def render_quiz_tab(assistant: StudyAssistant, profile_id: int, subject_id: int) -> None:
    st.subheader("Quiz Lab")
    st.caption("Generate multiple choice, short answer, or true/false quizzes with optional timing.")

    settings = st.columns(4)
    mode = settings[0].selectbox(
        "Mode",
        options=["multiple_choice", "short_answer", "true_false"],
        key="quiz_mode",
    )
    difficulty = settings[1].selectbox("Difficulty", options=["easy", "medium", "hard"], key="quiz_difficulty")
    question_count = settings[2].slider("Questions", min_value=1, max_value=8, value=4, key="quiz_count")
    time_limit_option = settings[3].selectbox("Timer", options=["None", "5", "10", "15"], key="quiz_timer")

    if st.button("Generate quiz", use_container_width=True):
        try:
            time_limit = None if time_limit_option == "None" else int(time_limit_option)
            quiz = assistant.generate_quiz(
                subject_id=subject_id,
                mode=mode,
                difficulty=difficulty,
                question_count=question_count,
                time_limit_minutes=time_limit,
            )
            st.session_state.current_quiz_id = quiz["id"]
            st.session_state.quiz_started_at = datetime.now().isoformat()
            st.session_state.quiz_result = None
            st.rerun()
        except Exception as exc:
            st.error(str(exc))

    current_quiz_id = st.session_state.current_quiz_id
    if current_quiz_id:
        quiz = assistant.memory_db.get_quiz(current_quiz_id)
        if quiz and quiz["subject_id"] == subject_id and quiz["profile_id"] == profile_id:
            st.markdown(
                f"""
                <div class="section-card">
                    <div class="pill">{escape(quiz['mode'].replace('_', ' ').title())}</div>
                    <h3>{escape(quiz['title'])}</h3>
                    <p>{quiz['difficulty'].title()} difficulty · {quiz['question_count']} questions</p>
                </div>
                """,
                unsafe_allow_html=True,
            )

            auto_submit = False
            if st.session_state.quiz_result is None:
                auto_submit = render_quiz_countdown(quiz)

            for index, question in enumerate(quiz["questions"]):
                st.markdown(f"### Question {index + 1}")
                if quiz["mode"] in {"multiple_choice", "true_false"}:
                    st.radio(
                        question["prompt"],
                        options=question["options"],
                        index=None,
                        key=question_state_key(quiz["id"], index),
                    )
                else:
                    st.text_area(
                        question["prompt"],
                        height=120,
                        key=question_state_key(quiz["id"], index),
                    )

            if auto_submit and st.session_state.quiz_result is None:
                try:
                    st.session_state.quiz_result = assistant.grade_quiz_attempt(
                        quiz["id"],
                        collect_quiz_responses(quiz),
                    )
                    st.rerun()
                except Exception as exc:
                    st.error(str(exc))

            if st.session_state.quiz_result is None and st.button("Submit quiz", use_container_width=True):
                try:
                    st.session_state.quiz_result = assistant.grade_quiz_attempt(
                        quiz["id"],
                        collect_quiz_responses(quiz),
                    )
                    st.rerun()
                except Exception as exc:
                    st.error(str(exc))

    if st.session_state.quiz_result:
        result = st.session_state.quiz_result
        st.success(
            f"Score: {result['score']:.1f} / {result['max_score']:.1f} ({result['percent']:.1f}%)"
        )
        for item in result["feedback"]:
            with st.expander(f"Question {item['index'] + 1}: {item['prompt']}", expanded=False):
                st.markdown(f"**Your answer:** {item['response'] or '_blank_'}")
                st.markdown(f"**Correct answer:** {item['correct_answer']}")
                st.markdown(f"**Feedback:** {item['feedback']}")
                st.caption(f"Score: {item['score']:.2f}")

    attempts = assistant.memory_db.list_quiz_attempts(profile_id, subject_id, limit=5)
    if attempts:
        st.markdown("### Recent Attempts")
        for attempt in attempts:
            percent = 0.0 if attempt["max_score"] == 0 else (attempt["score"] / attempt["max_score"]) * 100
            st.markdown(f"- `{attempt['created_at']}` score `{percent:.1f}%`")


def render_library_tab(assistant: StudyAssistant, profile_id: int, subject_id: int) -> None:
    st.subheader("Library")
    st.caption("Upload notes, search memory and materials, and generate saved revision sheets.")

    left, right = st.columns(2, gap="large")
    with left:
        st.markdown("### Paste notes")
        with st.form("paste_notes_form", clear_on_submit=True):
            title = st.text_input("Title", placeholder="Chapter 4 notes")
            body = st.text_area("Notes", height=200, placeholder="Paste lecture notes or a study guide")
            submitted = st.form_submit_button("Save notes", use_container_width=True)
        if submitted:
            try:
                assistant.ingest_text(subject_id, title, body)
                st.rerun()
            except Exception as exc:
                st.error(str(exc))

    with right:
        st.markdown("### Upload PDF")
        uploaded_pdf = st.file_uploader("PDF notes", type=["pdf"], key="pdf_upload")
        if uploaded_pdf is not None and st.button("Process PDF", use_container_width=True):
            try:
                assistant.ingest_pdf(subject_id, uploaded_pdf)
                st.rerun()
            except Exception as exc:
                st.error(str(exc))

        st.markdown("### Revision Sheet")
        sheet_title = st.text_input("Revision sheet title", placeholder="Midterm Revision Sheet")
        if st.button("Generate revision sheet", use_container_width=True):
            try:
                assistant.generate_revision_sheet(subject_id, title=sheet_title or None)
                st.rerun()
            except Exception as exc:
                st.error(str(exc))

    st.markdown("### Search Subject Library")
    query = st.text_input(
        "Search conversations and note chunks",
        placeholder="Search a concept such as mitochondria or quadratic formula",
    )
    if query.strip():
        results = assistant.memory_db.search_library(query, profile_id, subject_id, limit=6)
        if results["conversations"]:
            st.markdown("#### Conversation Matches")
            for row in results["conversations"]:
                st.markdown(
                    f"""
                    <div class="section-card">
                        <h4>{escape(row['user_message'])}</h4>
                        <p>{escape(row['assistant_message'])}</p>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
        if results["documents"]:
            st.markdown("#### Note Matches")
            for row in results["documents"]:
                st.markdown(
                    f"""
                    <div class="section-card">
                        <div class="pill">{escape(row['title'])}</div>
                        <p>{escape(row['content'])}</p>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
        if not results["conversations"] and not results["documents"]:
            st.info("No matches found.")

    st.markdown("### Notes")
    documents = assistant.memory_db.list_documents(profile_id, subject_id, limit=12)
    if documents:
        for doc in documents:
            with st.expander(f"{doc['title']} · {doc['source_type']} · {doc['created_at']}"):
                st.text(doc["body"][:3000])
                if len(doc["body"]) > 3000:
                    st.caption("Content truncated in preview.")
    else:
        st.caption("No notes uploaded yet.")

    st.markdown("### Revision Sheets")
    sheets = assistant.memory_db.list_revision_sheets(profile_id, subject_id, limit=10)
    if sheets:
        for sheet in sheets:
            with st.expander(f"{sheet['title']} · {sheet['created_at']}", expanded=False):
                st.markdown(sheet["content"])
                st.download_button(
                    "Download markdown",
                    data=sheet["content"],
                    file_name=f"{sheet['title'].replace(' ', '_').lower()}.md",
                    mime="text/markdown",
                    key=f"download_sheet_{sheet['id']}",
                )
    else:
        st.caption("No revision sheets saved yet.")


def main() -> None:
    inject_styles()
    init_ui_state()

    if not render_unlock_screen():
        return

    assistant, profile_id, subject_id = get_active_session()
    dashboard = assistant.get_dashboard(profile_id, subject_id)
    render_sidebar_controls(assistant, dashboard)

    if not assistant.is_ready:
        st.warning("`OPENAI_API_KEY` is not set. Data storage, search, and profiles still work, but generation features are disabled.")

    render_workspace_banner(dashboard)

    tab_dashboard, tab_tutor, tab_plans, tab_flashcards, tab_quiz, tab_library = st.tabs(
        ["Dashboard", "Tutor", "Plans", "Flashcards", "Quiz Lab", "Library"]
    )

    with tab_dashboard:
        render_dashboard_tab(assistant, profile_id, subject_id)

    with tab_tutor:
        render_tutor_tab(assistant, profile_id, subject_id)

    with tab_plans:
        render_plans_tab(assistant, subject_id)

    with tab_flashcards:
        render_flashcards_tab(assistant, profile_id, subject_id)

    with tab_quiz:
        render_quiz_tab(assistant, profile_id, subject_id)

    with tab_library:
        render_library_tab(assistant, profile_id, subject_id)


if __name__ == "__main__":
    main()
