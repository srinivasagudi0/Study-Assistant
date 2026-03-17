# Study Assistant

Study Assistant is a Streamlit-first local study workspace with profile isolation, subject organization, note ingestion, tutoring, quizzes, flashcards, study plans, revision sheets, and progress tracking.

## What It Includes

- Local profiles protected by a 4-8 digit PIN
- Subject-scoped tutoring memory
- Pasted text notes and text-based PDF ingestion
- Dashboard metrics for streaks, due cards, quiz averages, notes, and recent activity
- Study plans built from weak areas, due flashcards, and saved material
- Flashcards with spaced repetition review
- Quiz Lab with multiple choice, short answer, true/false, and optional timers
- Explain-differently actions for the latest assistant response
- Revision sheet generation and markdown download
- CLI support for profile/subject switching, chat, quizzes, memory/history, and due-card review

## Project Structure

```text
.
├── app.py                  # Streamlit UI
├── main.py                 # CLI interface
├── assistant.py            # Compatibility export for StudyAssistant
├── memory_db.py            # Compatibility export for MemoryDB
├── requirements.txt
├── studyflow/
│   ├── __init__.py
│   ├── service.py          # Assistant service layer
│   └── storage.py          # SQLite repository, migration, retrieval, metrics
└── tests/
    ├── conftest.py
    └── test_studyflow.py
```

## Requirements

- Python 3.10+
- `OPENAI_API_KEY` for generation features
- Python packages from `requirements.txt`

## Installation

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export OPENAI_API_KEY="your_api_key_here"
```

## Run the Streamlit App

```bash
streamlit run app.py
```

## Run the CLI

```bash
python main.py
```

## Default Local Profile

The app seeds one local profile automatically:

- Profile: `Default`
- PIN: `0000`
- Default subject: `General`

Create more profiles and subjects from the UI or CLI.

## Streamlit Tabs

- `Dashboard` - Metrics, weak areas, recent activity, latest plan, and recent materials
- `Tutor` - Memory-aware tutoring plus explain-differently actions
- `Plans` - Generate and review dated study plans
- `Flashcards` - Generate cards and review due items with spaced repetition
- `Quiz Lab` - Generate quizzes, take timed or untimed attempts, and review feedback
- `Library` - Upload notes, search materials, and generate revision sheets

## CLI Commands

- `/help` - Show commands
- `/profiles` - Unlock a different profile
- `/new-profile` - Create a local profile
- `/subjects` - Switch subjects
- `/new-subject` - Create a subject in the active profile
- `/memory` - View recent subject memory
- `/history` - View prior prompts in the active subject
- `/clear-memory` - Clear conversation memory for the active subject
- `/quiz` - Generate and take a quiz
- `/review-cards` - Review due flashcards
- `/scope` - Show the active profile and subject
- `/exit` - Quit

## Notes

- Data is stored locally in `study_assistant.db`.
- Uploaded PDFs are stored under `uploads/<profile_id>/<subject_id>/`.
- PDF ingestion is limited to text-based PDFs. OCR is not included.
- If `OPENAI_API_KEY` is missing, storage and browsing features still work, but generation features will be unavailable.

## Tests

```bash
pytest -q
```
