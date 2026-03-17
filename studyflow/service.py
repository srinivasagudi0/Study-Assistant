from __future__ import annotations

import io
import json
import re
from datetime import date, datetime, timedelta
from typing import Any

try:
    from openai import OpenAI
except ImportError:  # pragma: no cover - handled in runtime
    OpenAI = None  # type: ignore[assignment]

try:
    from pypdf import PdfReader
except ImportError:  # pragma: no cover - handled in runtime
    PdfReader = None  # type: ignore[assignment]

from .storage import MemoryDB


REWRITE_STYLES = {
    "simpler": "Rewrite the explanation in simpler words for a student who is new to the topic.",
    "example": "Give a concrete example that makes the explanation easier to understand.",
    "step_by_step": "Break the explanation into step-by-step reasoning.",
    "real_life": "Connect the explanation to a real-life analogy or everyday situation.",
    "exam_summary": "Turn the explanation into a concise exam-ready summary with bullet points.",
}


class StudyAssistant:
    """High-level study workflow service used by both the app and the CLI."""

    def __init__(
        self,
        profile_id: int | None = None,
        subject_id: int | None = None,
        model: str = "gpt-4o",
        memory_db: MemoryDB | None = None,
        db_path: str = "study_assistant.db",
        upload_root: str = "uploads",
        client: Any | None = None,
    ):
        self.memory_db = memory_db or MemoryDB(db_path=db_path, upload_root=upload_root)
        self.model = model
        self.client = client or self._make_client()
        profiles = self.memory_db.list_profiles()
        default_profile_id = profile_id or (profiles[0]["id"] if profiles else None)
        self.profile_id = default_profile_id
        self.subject_id = subject_id
        if self.profile_id is not None and self.subject_id is None:
            default_subject = self.memory_db.get_default_subject(self.profile_id)
            self.subject_id = default_subject["id"]

    @property
    def is_ready(self) -> bool:
        return self.client is not None

    def _make_client(self) -> Any | None:
        """Create the OpenAI client only when the dependency and API key are available."""
        if OpenAI is None:
            return None
        import os

        token = os.getenv("OPENAI_API_KEY")
        if not token:
            return None
        return OpenAI(api_key=token)

    def set_scope(self, profile_id: int, subject_id: int | None = None) -> tuple[int, int]:
        """Update the active profile/subject pair used by later calls."""
        self.profile_id = profile_id
        if subject_id is None:
            subject_id = self.memory_db.get_default_subject(profile_id)["id"]
        self.subject_id = subject_id
        return profile_id, subject_id

    def _resolve_scope(self, subject_id: int | None = None) -> tuple[int, int]:
        if self.profile_id is None:
            profiles = self.memory_db.list_profiles()
            if not profiles:
                raise ValueError("No profiles are available.")
            self.profile_id = profiles[0]["id"]
        if subject_id is not None:
            self.subject_id = subject_id
        if self.subject_id is None:
            self.subject_id = self.memory_db.get_default_subject(self.profile_id)["id"]
        return self.profile_id, self.subject_id

    def _require_client(self, feature: str) -> None:
        if self.client is None:
            raise RuntimeError(f"{feature} requires OPENAI_API_KEY.")

    def chat(self, question: str, subject_id: int | None = None, retrieval_mode: str = "hybrid") -> str:
        """Answer a study question using the active subject as context."""
        profile_id, resolved_subject_id = self._resolve_scope(subject_id)
        cleaned_question = question.strip()
        if not cleaned_question:
            raise ValueError("Question is required.")
        context = self.memory_db.build_study_context(
            profile_id,
            resolved_subject_id,
            cleaned_question if retrieval_mode == "hybrid" else "",
        )
        prompt = cleaned_question
        if context:
            prompt = (
                "Use the provided study context only when it helps answer the student.\n\n"
                f"{context}\n\nCurrent question: {cleaned_question}"
            )
        answer = self._ask_text_model(
            system_prompt=(
                "You are a helpful study assistant. Teach clearly, stay accurate, and adapt explanations "
                "to the student's level. Use headings or bullets when useful."
            ),
            user_prompt=prompt,
        )
        self.memory_db.add_interaction(profile_id, resolved_subject_id, cleaned_question, answer)
        self.memory_db.log_session(
            profile_id,
            resolved_subject_id,
            session_type="chat",
            ref_kind="conversation",
            duration_minutes=8,
            summary=cleaned_question[:120],
        )
        return answer

    def respond(self, question: str) -> str:
        return self.chat(question)

    def transform_last_response(self, mode: str) -> str:
        """Rephrase the most recent answer without discarding the original."""
        if mode not in REWRITE_STYLES:
            raise ValueError("Unsupported transform mode.")
        profile_id, subject_id = self._resolve_scope()
        last_turn = self.memory_db.get_last_conversation(profile_id, subject_id)
        if not last_turn:
            raise ValueError("No conversation is available to transform.")
        prompt = (
            f"Original student question: {last_turn['user_message']}\n\n"
            f"Original assistant answer: {last_turn['assistant_message']}\n\n"
            f"{REWRITE_STYLES[mode]}"
        )
        transformed = self._ask_text_model(
            system_prompt=(
                "You rewrite existing explanations while preserving correctness. Keep the response focused on "
                "the latest answer only."
            ),
            user_prompt=prompt,
        )
        self.memory_db.add_interaction(
            profile_id,
            subject_id,
            f"[Action:{mode}] {last_turn['user_message']}",
            transformed,
        )
        self.memory_db.log_session(
            profile_id,
            subject_id,
            session_type="transform",
            ref_kind="conversation",
            duration_minutes=3,
            summary=mode,
        )
        return transformed

    def ingest_text(self, subject_id: int, title: str, body: str) -> dict[str, Any]:
        """Store pasted notes for the active profile and subject."""
        profile_id, resolved_subject_id = self._resolve_scope(subject_id)
        document = self.memory_db.add_document(
            profile_id,
            resolved_subject_id,
            title=title,
            source_type="text",
            body=body,
        )
        self.memory_db.log_session(
            profile_id,
            resolved_subject_id,
            session_type="upload",
            ref_kind="document",
            ref_id=document["id"],
            duration_minutes=5,
            summary=document["title"],
        )
        return document

    def ingest_pdf(self, subject_id: int, uploaded_file: Any) -> dict[str, Any]:
        """Save a PDF locally, extract its text, and add it to the search index."""
        profile_id, resolved_subject_id = self._resolve_scope(subject_id)
        if PdfReader is None:
            raise RuntimeError("PDF upload requires `pypdf`.")
        file_name = getattr(uploaded_file, "name", "notes.pdf")
        file_bytes = uploaded_file.read()
        if not file_bytes:
            raise ValueError("Uploaded PDF is empty.")
        profile_dir = self.memory_db.upload_root / str(profile_id) / str(resolved_subject_id)
        profile_dir.mkdir(parents=True, exist_ok=True)
        safe_name = re.sub(r"[^a-zA-Z0-9._-]+", "_", file_name).strip("_") or "notes.pdf"
        destination = profile_dir / safe_name
        destination.write_bytes(file_bytes)

        reader = PdfReader(io.BytesIO(file_bytes))
        pages = [(page.extract_text() or "").strip() for page in reader.pages]
        extracted_text = "\n\n".join(page for page in pages if page)
        if not extracted_text.strip():
            raise ValueError("This PDF does not contain extractable text.")
        document = self.memory_db.add_document(
            profile_id,
            resolved_subject_id,
            title=Path(file_name).stem,
            source_type="pdf",
            body=extracted_text,
            original_filename=file_name,
            stored_path=str(destination),
        )
        self.memory_db.log_session(
            profile_id,
            resolved_subject_id,
            session_type="upload",
            ref_kind="document",
            ref_id=document["id"],
            duration_minutes=6,
            summary=document["title"],
        )
        return document

    def generate_quiz(
        self,
        subject_id: int,
        mode: str,
        difficulty: str,
        question_count: int,
        time_limit_minutes: int | None = None,
    ) -> dict[str, Any]:
        """Build and persist a quiz for the active subject."""
        profile_id, resolved_subject_id = self._resolve_scope(subject_id)
        context = self.memory_db.build_study_context(
            profile_id,
            resolved_subject_id,
            f"{difficulty} {mode} quiz",
            recent_limit=4,
            relevant_limit=5,
            chunk_limit=5,
        )
        prompt = (
            "Generate a study quiz as JSON with keys `title` and `questions`.\n"
            f"Mode: {mode}\nDifficulty: {difficulty}\nQuestion count: {question_count}\n"
            "Each question must include `prompt`, `concept_tags`, and `explanation`.\n"
        )
        if mode == "multiple_choice":
            prompt += (
                "For multiple_choice questions also include `options` as a list of 4 strings "
                "and `answer` equal to the correct option text.\n"
            )
        elif mode == "true_false":
            prompt += (
                "For true_false questions include `options` as ['True', 'False'] and `answer` as 'True' or 'False'.\n"
            )
        else:
            prompt += (
                "For short_answer questions include `answer` with the ideal answer and `rubric` with grading guidance.\n"
            )
        prompt += f"\nContext:\n{context or 'No saved study context yet.'}"
        data = self._ask_json_model(
            system_prompt=(
                "You create clean quiz JSON for a study app. Keep questions directly grounded in the provided context."
            ),
            user_prompt=prompt,
            fallback=lambda: self._make_quiz_fallback(mode, difficulty, question_count, context),
        )
        questions = self._clean_quiz_questions(mode, data.get("questions", []), question_count)
        if not questions:
            questions = self._make_quiz_fallback(mode, difficulty, question_count, context)["questions"]
        quiz = self.memory_db.create_quiz(
            profile_id,
            resolved_subject_id,
            mode=mode,
            difficulty=difficulty,
            question_count=len(questions),
            time_limit_minutes=time_limit_minutes,
            title=data.get("title", f"{difficulty.title()} {mode.replace('_', ' ').title()} Quiz"),
            questions=questions,
        )
        self.memory_db.log_session(
            profile_id,
            resolved_subject_id,
            session_type="quiz_generate",
            ref_kind="quiz",
            ref_id=quiz["id"],
            duration_minutes=4,
            summary=quiz["title"],
        )
        return quiz

    def grade_quiz_attempt(self, quiz_id: int, responses: dict[str, Any]) -> dict[str, Any]:
        """Score a saved quiz attempt and raise weak-area signals for misses."""
        quiz = self.memory_db.get_quiz(quiz_id)
        if not quiz:
            raise ValueError("Quiz not found.")
        feedback: list[dict[str, Any]] = []
        total_score = 0.0
        questions = quiz["questions"]
        for index, question in enumerate(questions):
            response_value = (responses.get(str(index)) or responses.get(index) or "").strip()
            question_type = quiz["mode"]
            if question_type in {"multiple_choice", "true_false"}:
                answer = str(question.get("answer", "")).strip()
                is_correct = response_value.lower() == answer.lower()
                score = 1.0 if is_correct else 0.0
                feedback.append(
                    {
                        "index": index,
                        "prompt": question["prompt"],
                        "response": response_value,
                        "correct_answer": answer,
                        "score": score,
                        "feedback": "Correct." if is_correct else question.get("explanation", "Review this concept."),
                        "concept_tags": question.get("concept_tags", []),
                    }
                )
            else:
                graded = self._grade_short_answer(question, response_value)
                score = float(graded["score"])
                feedback.append(
                    {
                        "index": index,
                        "prompt": question["prompt"],
                        "response": response_value,
                        "correct_answer": graded["correct_answer"],
                        "score": score,
                        "feedback": graded["feedback"],
                        "concept_tags": question.get("concept_tags", []),
                    }
                )
            total_score += score

        attempt = self.memory_db.create_quiz_attempt(
            quiz_id=quiz_id,
            profile_id=quiz["profile_id"],
            subject_id=quiz["subject_id"],
            responses=responses,
            score=total_score,
            max_score=float(len(questions)),
            feedback=feedback,
        )
        percent = 0.0 if not questions else round((total_score / len(questions)) * 100, 1)
        self.memory_db.log_session(
            quiz["profile_id"],
            quiz["subject_id"],
            session_type="quiz_attempt",
            ref_kind="quiz_attempt",
            ref_id=attempt["id"],
            duration_minutes=quiz.get("time_limit_minutes") or max(5, len(questions) * 2),
            summary=quiz["title"],
            score=percent,
        )
        for item in feedback:
            if item["score"] >= 0.99:
                continue
            tags = item.get("concept_tags") or [item["prompt"][:60]]
            severity_delta = 2.0 if item["score"] == 0 else 1.0
            for tag in tags:
                self.memory_db.upsert_weak_area(
                    quiz["profile_id"],
                    quiz["subject_id"],
                    tag,
                    source=f"quiz:{quiz_id}",
                    severity_delta=severity_delta,
                )
        attempt["percent"] = percent
        return attempt

    def generate_study_plan(
        self,
        subject_id: int,
        goal: str,
        exam_date: str | None,
        days_per_week: int,
        minutes_per_day: int,
        focus_mode: str = "weakness_first",
    ) -> dict[str, Any]:
        """Create a dated study plan, then save the rendered markdown and raw JSON."""
        profile_id, resolved_subject_id = self._resolve_scope(subject_id)
        dashboard = self.memory_db.get_dashboard_stats(profile_id, resolved_subject_id)
        context = self.memory_db.build_study_context(
            profile_id,
            resolved_subject_id,
            goal,
            recent_limit=3,
            relevant_limit=4,
            chunk_limit=5,
        )
        prompt = (
            "Create a study plan as JSON with keys `title`, `summary`, and `days`.\n"
            "Each day must include `date`, `focus`, `tasks`, and `estimated_minutes`.\n"
            f"Goal: {goal}\nExam date: {exam_date or 'none'}\nDays per week: {days_per_week}\n"
            f"Minutes per day: {minutes_per_day}\nFocus mode: {focus_mode}\n"
            f"Due cards: {dashboard['due_cards']}\n"
            f"Weak areas: {', '.join(item['concept'] for item in dashboard['weak_areas']) or 'none'}\n\n"
            f"Context:\n{context or 'No context available.'}"
        )
        data = self._ask_json_model(
            system_prompt=(
                "You create realistic study plans that use weak areas, due review cards, and available notes."
            ),
            user_prompt=prompt,
            fallback=lambda: self._make_plan_fallback(goal, exam_date, days_per_week, minutes_per_day, dashboard),
        )
        plan_data = data if data.get("days") else self._make_plan_fallback(
            goal, exam_date, days_per_week, minutes_per_day, dashboard
        )
        title = plan_data.get("title", f"Plan for {goal.strip()[:40]}")
        content = self._render_plan_markdown(plan_data, minutes_per_day)
        plan = self.memory_db.create_study_plan(
            profile_id,
            resolved_subject_id,
            goal=goal,
            exam_date=exam_date,
            days_per_week=days_per_week,
            minutes_per_day=minutes_per_day,
            focus_mode=focus_mode,
            title=title,
            content=content,
            plan_data=plan_data,
        )
        self.memory_db.log_session(
            profile_id,
            resolved_subject_id,
            session_type="plan",
            ref_kind="study_plan",
            ref_id=plan["id"],
            duration_minutes=10,
            summary=title,
        )
        return plan

    def generate_flashcards(
        self,
        subject_id: int,
        source_scope: str,
        count: int,
    ) -> list[dict[str, Any]]:
        """Turn saved subject material into flashcards ready for review."""
        profile_id, resolved_subject_id = self._resolve_scope(subject_id)
        context = self.memory_db.build_study_context(
            profile_id,
            resolved_subject_id,
            f"flashcards {source_scope}",
            recent_limit=4,
            relevant_limit=5,
            chunk_limit=6,
        )
        data = self._ask_json_model(
            system_prompt=(
                "You create concise flashcards from study material. Return JSON with `cards`."
            ),
            user_prompt=(
                "Generate flashcards as JSON with key `cards`.\n"
                f"Source scope: {source_scope}\nCard count: {count}\n"
                "Each card must include `front`, `back`, and `tags`.\n\n"
                f"Context:\n{context or 'No study context.'}"
            ),
            fallback=lambda: self._make_flashcard_fallback(source_scope, count, context),
        )
        cards = self._clean_flashcards(data.get("cards", []), count)
        if not cards:
            cards = self._make_flashcard_fallback(source_scope, count, context)["cards"]
        created = self.memory_db.bulk_create_flashcards(
            profile_id,
            resolved_subject_id,
            cards=cards,
            source_scope=source_scope,
        )
        self.memory_db.log_session(
            profile_id,
            resolved_subject_id,
            session_type="flashcards_generate",
            ref_kind="flashcards",
            duration_minutes=6,
            summary=f"{len(created)} cards",
        )
        return created

    def review_flashcard(self, card_id: int, rating: str) -> dict[str, Any]:
        """Apply one spaced-repetition rating and save the next due date."""
        if rating not in {"again", "hard", "good", "easy"}:
            raise ValueError("Invalid flashcard rating.")
        card = self.memory_db.get_flashcard(card_id)
        if not card:
            raise ValueError("Flashcard not found.")
        interval_days, ease_factor, repetitions = self._schedule_next_review(card, rating)
        next_due_at = (
            datetime.now() + timedelta(days=interval_days)
        ).replace(microsecond=0).isoformat(sep=" ")
        updated = self.memory_db.update_flashcard_schedule(
            card_id=card_id,
            rating=rating,
            interval_days=interval_days,
            ease_factor=ease_factor,
            repetitions=repetitions,
            next_due_at=next_due_at,
        )
        self.memory_db.log_session(
            card["profile_id"],
            card["subject_id"],
            session_type="flashcard_review",
            ref_kind="flashcard",
            ref_id=card_id,
            duration_minutes=2,
            summary=rating,
        )
        if rating in {"again", "hard"}:
            delta = 2.0 if rating == "again" else 1.0
            for tag in updated.get("tags", []) or [updated["front"][:60]]:
                self.memory_db.upsert_weak_area(
                    updated["profile_id"],
                    updated["subject_id"],
                    tag,
                    source=f"flashcard:{card_id}",
                    severity_delta=delta,
                )
        return updated

    def generate_revision_sheet(self, subject_id: int, title: str | None = None) -> dict[str, Any]:
        """Create and save a markdown revision sheet for the active subject."""
        profile_id, resolved_subject_id = self._resolve_scope(subject_id)
        subject = self.memory_db.get_subject(resolved_subject_id) or {"name": "General"}
        dashboard = self.memory_db.get_dashboard_stats(profile_id, resolved_subject_id)
        context = self.memory_db.build_study_context(
            profile_id,
            resolved_subject_id,
            "revision sheet",
            recent_limit=4,
            relevant_limit=5,
            chunk_limit=6,
        )
        sheet_title = title or f"{subject['name']} Revision Sheet"
        content = self._ask_text_model(
            system_prompt=(
                "You create concise markdown revision sheets with sections for key ideas, common mistakes, and review prompts."
            ),
            user_prompt=(
                f"Create a markdown revision sheet titled '{sheet_title}'.\n"
                f"Top weak areas: {', '.join(item['concept'] for item in dashboard['weak_areas']) or 'none'}\n\n"
                f"Context:\n{context or 'No context available.'}"
            ),
            fallback=self._make_sheet_fallback(sheet_title, dashboard),
        )
        sheet = self.memory_db.save_revision_sheet(
            profile_id,
            resolved_subject_id,
            title=sheet_title,
            content=content,
        )
        self.memory_db.log_session(
            profile_id,
            resolved_subject_id,
            session_type="revision_sheet",
            ref_kind="revision_sheet",
            ref_id=sheet["id"],
            duration_minutes=8,
            summary=sheet_title,
        )
        return sheet

    def get_dashboard(self, profile_id: int | None = None, subject_id: int | None = None) -> dict[str, Any]:
        """Fetch the dashboard payload for the current scope."""
        if profile_id is not None:
            self.profile_id = profile_id
        profile_id, resolved_subject_id = self._resolve_scope(subject_id)
        subject = self.memory_db.get_subject(resolved_subject_id)
        profile = self.memory_db.get_profile(profile_id)
        data = self.memory_db.get_dashboard_stats(profile_id, resolved_subject_id)
        data["subject"] = subject
        data["profile"] = profile
        return data

    def show_memory(self, limit: int = 10) -> list[str]:
        """Return recent subject history in a CLI-friendly plain-text format."""
        profile_id, subject_id = self._resolve_scope()
        rows = self.memory_db.get_recent(profile_id, subject_id, limit=limit)
        return [
            f"[{row['created_at']}] User: {row['user_message']}\n[{row['created_at']}] Assistant: {row['assistant_message']}"
            for row in rows
        ]

    def clear_memory(self) -> None:
        profile_id, subject_id = self._resolve_scope()
        self.memory_db.clear_conversations(profile_id, subject_id)

    def test(self) -> str:
        quiz = self.generate_quiz(self._resolve_scope()[1], "short_answer", "medium", 3)
        parts = []
        for index, question in enumerate(quiz["questions"], start=1):
            parts.append(f"{index}. {question['prompt']}")
        return "\n".join(parts)

    def correct(self, question: str, answer: str) -> str:
        prompt = (
            f"Question: {question}\nStudent answer: {answer}\n"
            "Give concise feedback, explain if it is correct, and provide the right answer if needed."
        )
        return self._ask_text_model(
            system_prompt="You are a helpful study assistant giving answer feedback.",
            user_prompt=prompt,
        )

    def close(self) -> None:
        self.memory_db.close()

    def _ask_text_model(
        self,
        system_prompt: str,
        user_prompt: str,
        fallback: str | None = None,
    ) -> str:
        if self.client is None:
            if fallback is not None:
                return fallback
            raise RuntimeError("This feature requires OPENAI_API_KEY.")
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        return (response.choices[0].message.content or "").strip()

    def _ask_json_model(
        self,
        system_prompt: str,
        user_prompt: str,
        fallback: Any,
    ) -> dict[str, Any]:
        if self.client is None:
            return fallback()
        response_text = self._ask_text_model(
            system_prompt=system_prompt,
            user_prompt=user_prompt + "\n\nReturn valid JSON only.",
        )
        try:
            return json.loads(response_text)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", response_text, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group(0))
                except json.JSONDecodeError:
                    pass
        return fallback()

    def _clean_quiz_questions(
        self,
        mode: str,
        questions: list[dict[str, Any]],
        question_count: int,
    ) -> list[dict[str, Any]]:
        normalized = []
        for question in questions[:question_count]:
            prompt = str(question.get("prompt", "")).strip()
            if not prompt:
                continue
            item = {
                "prompt": prompt,
                "concept_tags": [str(tag).strip() for tag in question.get("concept_tags", []) if str(tag).strip()],
                "explanation": str(question.get("explanation", "")).strip() or "Review the matching study material.",
            }
            if mode in {"multiple_choice", "true_false"}:
                options = [str(option).strip() for option in question.get("options", []) if str(option).strip()]
                answer = str(question.get("answer", "")).strip()
                if mode == "true_false":
                    options = ["True", "False"]
                    answer = "True" if answer.lower().startswith("t") else "False"
                if not options or not answer:
                    continue
                item["options"] = options
                item["answer"] = answer
            else:
                item["answer"] = str(question.get("answer", "")).strip() or "Review the relevant notes."
                item["rubric"] = str(question.get("rubric", "")).strip() or "State the key idea clearly."
            normalized.append(item)
        return normalized

    def _clean_flashcards(
        self,
        cards: list[dict[str, Any]],
        count: int,
    ) -> list[dict[str, Any]]:
        normalized = []
        for card in cards[:count]:
            front = str(card.get("front", "")).strip()
            back = str(card.get("back", "")).strip()
            if not front or not back:
                continue
            normalized.append(
                {
                    "front": front,
                    "back": back,
                    "tags": [str(tag).strip() for tag in card.get("tags", []) if str(tag).strip()],
                }
            )
        return normalized

    def _grade_short_answer(self, question: dict[str, Any], response: str) -> dict[str, Any]:
        answer_key = str(question.get("answer", "")).strip()
        if not response.strip():
            return {
                "score": 0.0,
                "feedback": "No answer provided.",
                "correct_answer": answer_key,
            }
        if self.client is None:
            return self._heuristic_short_answer_grade(answer_key, response)
        data = self._ask_json_model(
            system_prompt=(
                "You grade student short answers. Return JSON with `score` from 0 to 1, `feedback`, and `correct_answer`."
            ),
            user_prompt=(
                f"Question: {question['prompt']}\n"
                f"Ideal answer: {answer_key}\n"
                f"Rubric: {question.get('rubric', '')}\n"
                f"Student answer: {response}"
            ),
            fallback=lambda: self._heuristic_short_answer_grade(answer_key, response),
        )
        score = max(0.0, min(1.0, float(data.get("score", 0.0))))
        return {
            "score": score,
            "feedback": str(data.get("feedback", "Review the ideal answer.")),
            "correct_answer": str(data.get("correct_answer", answer_key)),
        }

    def _heuristic_short_answer_grade(self, answer_key: str, response: str) -> dict[str, Any]:
        answer_tokens = set(self._tokenize(answer_key))
        response_tokens = set(self._tokenize(response))
        if not answer_tokens:
            return {
                "score": 0.0,
                "feedback": "No grading rubric was available.",
                "correct_answer": answer_key,
            }
        overlap = len(answer_tokens & response_tokens)
        score = round(overlap / max(1, len(answer_tokens)), 2)
        feedback = "Good coverage." if score >= 0.7 else "Your answer missed some key ideas."
        return {
            "score": score,
            "feedback": feedback,
            "correct_answer": answer_key,
        }

    def _make_quiz_fallback(
        self,
        mode: str,
        difficulty: str,
        question_count: int,
        context: str,
    ) -> dict[str, Any]:
        focus_terms = self._collect_focus_terms(context)
        questions = []
        for index in range(question_count):
            topic = focus_terms[index % len(focus_terms)] if focus_terms else f"core idea {index + 1}"
            if mode == "multiple_choice":
                questions.append(
                    {
                        "prompt": f"Which statement best describes {topic}?",
                        "options": [
                            f"{topic} is a core concept to remember.",
                            f"{topic} is unrelated to the subject.",
                            f"{topic} means the opposite of the lesson.",
                            f"{topic} should be ignored during revision.",
                        ],
                        "answer": f"{topic} is a core concept to remember.",
                        "explanation": f"Review why {topic} matters in the active subject.",
                        "concept_tags": [topic],
                    }
                )
            elif mode == "true_false":
                questions.append(
                    {
                        "prompt": f"True or false: {topic} is important for this subject.",
                        "options": ["True", "False"],
                        "answer": "True",
                        "explanation": f"{topic} was selected from the current study context.",
                        "concept_tags": [topic],
                    }
                )
            else:
                questions.append(
                    {
                        "prompt": f"Explain {topic} in your own words.",
                        "answer": f"{topic} is a key idea from the current study context.",
                        "rubric": f"Define {topic} and explain why it matters.",
                        "explanation": f"Focus on the definition and importance of {topic}.",
                        "concept_tags": [topic],
                    }
                )
        return {
            "title": f"{difficulty.title()} {mode.replace('_', ' ').title()} Quiz",
            "questions": questions,
        }

    def _make_plan_fallback(
        self,
        goal: str,
        exam_date: str | None,
        days_per_week: int,
        minutes_per_day: int,
        dashboard: dict[str, Any],
    ) -> dict[str, Any]:
        weak_topics = [item["concept"] for item in dashboard.get("weak_areas", [])]
        note_titles = [doc["title"] for doc in dashboard.get("documents", [])]
        focus_terms = weak_topics or note_titles or ["Recent study topics"]
        start = date.today()
        if exam_date:
            try:
                end_date = date.fromisoformat(exam_date)
                span = max(1, (end_date - start).days + 1)
            except ValueError:
                span = 7
        else:
            span = 7
        days = []
        for offset in range(min(span, 10)):
            focus = focus_terms[offset % len(focus_terms)]
            days.append(
                {
                    "date": (start + timedelta(days=offset)).isoformat(),
                    "focus": focus,
                    "tasks": [
                        f"Review notes related to {focus}",
                        f"Complete one quiz or flashcard session for {focus}",
                        f"Summarize {focus} in 3-5 bullet points",
                    ],
                    "estimated_minutes": minutes_per_day,
                }
            )
        return {
            "title": f"Study Plan: {goal[:40]}",
            "summary": (
                f"Study {days_per_week} days per week at about {minutes_per_day} minutes per day. "
                "Prioritize weak areas first."
            ),
            "days": days,
        }

    def _render_plan_markdown(self, plan_data: dict[str, Any], minutes_per_day: int) -> str:
        lines = [f"# {plan_data.get('title', 'Study Plan')}", "", plan_data.get("summary", "")]
        for day in plan_data.get("days", []):
            lines.append("")
            lines.append(f"## {day.get('date', 'Day')} - {day.get('focus', 'Focus')}")
            lines.append(f"Estimated time: {day.get('estimated_minutes', minutes_per_day)} minutes")
            for task in day.get("tasks", []):
                lines.append(f"- {task}")
        return "\n".join(lines).strip()

    def _make_flashcard_fallback(self, source_scope: str, count: int, context: str) -> dict[str, Any]:
        terms = self._collect_focus_terms(context)
        cards = []
        for index in range(count):
            topic = terms[index % len(terms)] if terms else f"Topic {index + 1}"
            cards.append(
                {
                    "front": f"What should you remember about {topic}?",
                    "back": f"{topic} is a key part of the current study context. Review its definition and why it matters.",
                    "tags": [topic, source_scope],
                }
            )
        return {"cards": cards}

    def _make_sheet_fallback(self, title: str, dashboard: dict[str, Any]) -> str:
        weak_topics = [item["concept"] for item in dashboard.get("weak_areas", [])]
        due_cards = dashboard.get("due_cards", 0)
        lines = [
            f"# {title}",
            "",
            "## Key Priorities",
            f"- Due flashcards: {due_cards}",
            f"- Focus weak areas: {', '.join(weak_topics) if weak_topics else 'No weak areas logged yet'}",
            "",
            "## What To Review",
            "- Revisit uploaded notes and recent tutoring conversations.",
            "- Practice one quiz and one flashcard session.",
            "",
            "## Common Mistakes To Avoid",
            "- Memorizing definitions without connecting them to examples.",
            "- Skipping review of concepts you previously answered incorrectly.",
            "",
            "## Quick Self-Test",
            "- Can you explain the main concept in simple language?",
            "- Can you solve a question without looking at notes?",
        ]
        return "\n".join(lines)

    def _collect_focus_terms(self, context: str, limit: int = 6) -> list[str]:
        tokens = self._tokenize(context)
        seen: list[str] = []
        for token in tokens:
            if token not in seen:
                seen.append(token)
            if len(seen) >= limit:
                break
        return [token.replace("_", " ") for token in seen]

    def _tokenize(self, text: str) -> list[str]:
        return [token for token in re.findall(r"[a-zA-Z][a-zA-Z0-9_-]{2,}", text.lower())]

    def _schedule_next_review(self, card: dict[str, Any], rating: str) -> tuple[int, float, int]:
        ease_factor = float(card.get("ease_factor", 2.5) or 2.5)
        interval_days = int(card.get("interval_days", 0) or 0)
        repetitions = int(card.get("repetitions", 0) or 0)

        if rating == "again":
            repetitions = 0
            interval_days = 1
            ease_factor = max(1.3, ease_factor - 0.2)
        elif rating == "hard":
            repetitions = max(1, repetitions + 1)
            interval_days = 1 if interval_days <= 1 else max(2, round(interval_days * 1.2))
            ease_factor = max(1.3, ease_factor - 0.15)
        elif rating == "good":
            repetitions += 1
            if repetitions == 1:
                interval_days = 1
            elif repetitions == 2:
                interval_days = 3
            else:
                interval_days = max(4, round(interval_days * ease_factor))
        else:  # easy
            repetitions += 1
            ease_factor += 0.1
            if repetitions == 1:
                interval_days = 2
            elif repetitions == 2:
                interval_days = 5
            else:
                interval_days = max(6, round(interval_days * ease_factor * 1.3))

        return interval_days, round(ease_factor, 2), repetitions
