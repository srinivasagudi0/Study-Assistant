from __future__ import annotations

from getpass import getpass

from assistant import StudyAssistant


HELP_TEXT = """
Available commands:
/help            Show this help message
/profiles        Switch profiles
/new-profile     Create a local profile
/subjects        Switch subjects
/new-subject     Create a subject under the active profile
/memory          View recent memory in the active subject
/history         Show prior user prompts in the active subject
/clear-memory    Clear conversation memory for the active subject
/quiz            Generate and take a quiz
/review-cards    Review due flashcards
/scope           Show the active profile and subject
/exit            Quit the assistant
""".strip()


def prompt_for_choice(items: list[dict], label: str) -> dict:
    """Print numbered options and return the selected record."""
    if not items:
        raise ValueError(f"No {label} available.")
    print(f"\nChoose {label}:")
    for index, item in enumerate(items, start=1):
        print(f"{index}. {item['name']}")
    while True:
        choice = input("> ").strip()
        if choice.isdigit() and 1 <= int(choice) <= len(items):
            return items[int(choice) - 1]
        print(f"Enter a number from 1 to {len(items)}.")


def unlock_profile(assistant: StudyAssistant) -> tuple[int, int]:
    """Ask for a profile and keep prompting until the PIN is correct."""
    profiles = assistant.memory_db.list_profiles()
    profile = prompt_for_choice(profiles, "a profile")
    while True:
        pin = getpass(f"PIN for {profile['name']}: ")
        if assistant.memory_db.verify_profile(profile["id"], pin):
            subject = assistant.memory_db.get_default_subject(profile["id"])
            assistant.set_scope(profile["id"], subject["id"])
            return profile["id"], subject["id"]
        print("Invalid PIN.")


def switch_subject(assistant: StudyAssistant, profile_id: int) -> int:
    """Switch the active subject inside the current profile."""
    subjects = assistant.memory_db.list_subjects(profile_id)
    subject = prompt_for_choice(subjects, "a subject")
    assistant.set_scope(profile_id, subject["id"])
    return subject["id"]


def create_profile(assistant: StudyAssistant) -> tuple[int, int]:
    """Create a profile and immediately move the session into it."""
    print("\nCreate profile")
    name = input("Name: ").strip()
    pin = getpass("PIN (4-8 digits): ")
    confirm_pin = getpass("Confirm PIN: ")
    if pin != confirm_pin:
        raise ValueError("PIN confirmation does not match.")
    profile = assistant.memory_db.create_profile(name, pin)
    subject = assistant.memory_db.get_default_subject(profile["id"])
    assistant.set_scope(profile["id"], subject["id"])
    return profile["id"], subject["id"]


def create_subject(assistant: StudyAssistant, profile_id: int) -> int:
    """Create a subject and make it the active one."""
    print("\nCreate subject")
    name = input("Subject name: ").strip()
    subject = assistant.memory_db.create_subject(profile_id, name)
    assistant.set_scope(profile_id, subject["id"])
    return subject["id"]


def take_quiz(assistant: StudyAssistant, subject_id: int) -> None:
    """Walk through quiz setup, answer entry, and feedback printing."""
    print("\nQuiz setup")
    mode = input("Mode [multiple_choice/short_answer/true_false] (default short_answer): ").strip() or "short_answer"
    difficulty = input("Difficulty [easy/medium/hard] (default medium): ").strip() or "medium"
    count_input = input("Question count (default 3): ").strip()
    timer_input = input("Timer minutes [blank/5/10/15]: ").strip()
    count = int(count_input) if count_input.isdigit() else 3
    time_limit = int(timer_input) if timer_input.isdigit() else None

    quiz = assistant.generate_quiz(
        subject_id=subject_id,
        mode=mode,
        difficulty=difficulty,
        question_count=count,
        time_limit_minutes=time_limit,
    )

    print(f"\n{quiz['title']}")
    responses: dict[str, str] = {}
    for index, question in enumerate(quiz["questions"], start=1):
        print(f"\n{index}. {question['prompt']}")
        if quiz["mode"] in {"multiple_choice", "true_false"}:
            for option_index, option in enumerate(question["options"], start=1):
                print(f"   {option_index}. {option}")
            choice = input("Your answer: ").strip()
            if choice.isdigit() and 1 <= int(choice) <= len(question["options"]):
                responses[str(index - 1)] = question["options"][int(choice) - 1]
            else:
                responses[str(index - 1)] = choice
        else:
            responses[str(index - 1)] = input("Your answer: ").strip()

    result = assistant.grade_quiz_attempt(quiz["id"], responses)
    print(f"\nScore: {result['score']:.1f}/{result['max_score']:.1f} ({result['percent']:.1f}%)")
    for item in result["feedback"]:
        print(f"\nQuestion {item['index'] + 1}")
        print(f"Your answer: {item['response'] or '[blank]'}")
        print(f"Correct answer: {item['correct_answer']}")
        print(f"Feedback: {item['feedback']}")


def review_due_cards(assistant: StudyAssistant, profile_id: int, subject_id: int) -> None:
    """Review every flashcard that is currently due for the active subject."""
    cards = assistant.memory_db.list_flashcards(profile_id, subject_id, due_only=True, limit=20)
    if not cards:
        print("No flashcards are due.")
        return

    print(f"\nReviewing {len(cards)} due card(s).")
    for card in cards:
        print("\nFront:")
        print(card["front"])
        input("Press Enter to show the answer...")
        print("Back:")
        print(card["back"])
        rating = input("Rating [again/hard/good/easy]: ").strip().lower() or "good"
        if rating not in {"again", "hard", "good", "easy"}:
            rating = "good"
        assistant.review_flashcard(card["id"], rating)
    print("Flashcard review complete.")


def print_scope(assistant: StudyAssistant) -> None:
    """Display the currently selected profile and subject."""
    profile = assistant.memory_db.get_profile(assistant.profile_id)
    subject = assistant.memory_db.get_subject(assistant.subject_id)
    if profile and subject:
        print(f"Profile: {profile['name']} | Subject: {subject['name']}")


def main() -> None:
    assistant = StudyAssistant()
    profile_id, subject_id = unlock_profile(assistant)

    print("Study Assistant CLI")
    print("Type /help for commands.")
    print_scope(assistant)

    try:
        while True:
            user_input = input("\nYou: ").strip()
            if not user_input:
                continue
            if user_input in {"exit", "quit", "/exit"}:
                print("Goodbye.")
                break
            if user_input == "/help":
                print(HELP_TEXT)
                continue
            if user_input == "/profiles":
                profile_id, subject_id = unlock_profile(assistant)
                print_scope(assistant)
                continue
            if user_input == "/new-profile":
                profile_id, subject_id = create_profile(assistant)
                print_scope(assistant)
                continue
            if user_input == "/subjects":
                subject_id = switch_subject(assistant, profile_id)
                print_scope(assistant)
                continue
            if user_input == "/new-subject":
                subject_id = create_subject(assistant, profile_id)
                print_scope(assistant)
                continue
            if user_input == "/memory":
                memory_entries = assistant.show_memory()
                if not memory_entries:
                    print("Memory is empty.")
                else:
                    print("\nRecent memory:")
                    for entry in memory_entries:
                        print(entry)
                        print()
                continue
            if user_input == "/history":
                history = assistant.memory_db.show_history(profile_id, subject_id)
                if not history:
                    print("No question history in this subject.")
                else:
                    print("\nQuestion history:")
                    for question in history:
                        print(f"- {question}")
                continue
            if user_input == "/clear-memory":
                assistant.clear_memory()
                print("Conversation memory cleared for the active subject.")
                continue
            if user_input == "/quiz":
                try:
                    take_quiz(assistant, subject_id)
                except Exception as exc:
                    print(f"Quiz failed: {exc}")
                continue
            if user_input == "/review-cards":
                try:
                    review_due_cards(assistant, profile_id, subject_id)
                except Exception as exc:
                    print(f"Flashcard review failed: {exc}")
                continue
            if user_input == "/scope":
                print_scope(assistant)
                continue

            try:
                response = assistant.chat(user_input, subject_id=subject_id)
                print(f"\nAssistant: {response}")
            except Exception as exc:
                print(f"Request failed: {exc}")
    finally:
        assistant.close()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nGoodbye.")
