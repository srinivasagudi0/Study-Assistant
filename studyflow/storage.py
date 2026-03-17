from __future__ import annotations

import hashlib
import json
import re
import secrets
import sqlite3
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable


DEFAULT_PROFILE_NAME = "Default"
DEFAULT_PROFILE_PIN = "0000"
DEFAULT_SUBJECT_NAME = "General"


class MemoryDB:
    """SQLite-backed store for profiles, study content, and progress data."""

    def __init__(self, db_path: str = "study_assistant.db", upload_root: str = "uploads"):
        self.db_path = Path(db_path)
        self.upload_root = Path(upload_root)
        self.upload_root.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self._conversation_fts_enabled = False
        self._document_fts_enabled = False
        self.create_tables()

    def create_tables(self) -> None:
        """Create the current schema and backfill old conversation-only databases."""
        cursor = self.conn.cursor()
        self._create_profile_table(cursor)
        default_profile_id = self._ensure_default_profile(cursor)
        self._create_subject_table(cursor)
        default_subject_id = self._ensure_default_subject(cursor, default_profile_id)
        self._migrate_legacy_conversations(cursor, default_profile_id, default_subject_id)
        self._create_learning_tables(cursor)
        self.conn.commit()
        self._rebuild_search_indexes()

    def _create_profile_table(self, cursor: sqlite3.Cursor) -> None:
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS profiles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE COLLATE NOCASE,
                pin_hash TEXT NOT NULL,
                pin_salt TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

    def _create_subject_table(self, cursor: sqlite3.Cursor) -> None:
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS subjects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                profile_id INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
                name TEXT NOT NULL COLLATE NOCASE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(profile_id, name)
            )
            """
        )

    def _create_learning_tables(self, cursor: sqlite3.Cursor) -> None:
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                profile_id INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
                subject_id INTEGER NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
                user_message TEXT NOT NULL,
                assistant_message TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                profile_id INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
                subject_id INTEGER NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
                title TEXT NOT NULL,
                source_type TEXT NOT NULL,
                original_filename TEXT,
                stored_path TEXT,
                body TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS document_chunks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
                profile_id INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
                subject_id INTEGER NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
                chunk_index INTEGER NOT NULL,
                content TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS study_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                profile_id INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
                subject_id INTEGER NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
                session_type TEXT NOT NULL,
                ref_kind TEXT,
                ref_id INTEGER,
                duration_minutes INTEGER DEFAULT 0,
                summary TEXT,
                score REAL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS study_plans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                profile_id INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
                subject_id INTEGER NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
                goal TEXT NOT NULL,
                exam_date TEXT,
                days_per_week INTEGER NOT NULL,
                minutes_per_day INTEGER NOT NULL,
                focus_mode TEXT NOT NULL,
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                plan_json TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS flashcards (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                profile_id INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
                subject_id INTEGER NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
                front TEXT NOT NULL,
                back TEXT NOT NULL,
                tags_json TEXT NOT NULL,
                source_scope TEXT NOT NULL,
                ease_factor REAL DEFAULT 2.5,
                interval_days INTEGER DEFAULT 0,
                repetitions INTEGER DEFAULT 0,
                next_due_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_reviewed_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS flashcard_reviews (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                card_id INTEGER NOT NULL REFERENCES flashcards(id) ON DELETE CASCADE,
                profile_id INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
                subject_id INTEGER NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
                rating TEXT NOT NULL,
                interval_days INTEGER NOT NULL,
                ease_factor REAL NOT NULL,
                next_due_at TIMESTAMP NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS quizzes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                profile_id INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
                subject_id INTEGER NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
                mode TEXT NOT NULL,
                difficulty TEXT NOT NULL,
                question_count INTEGER NOT NULL,
                time_limit_minutes INTEGER,
                title TEXT NOT NULL,
                questions_json TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS quiz_attempts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                quiz_id INTEGER NOT NULL REFERENCES quizzes(id) ON DELETE CASCADE,
                profile_id INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
                subject_id INTEGER NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
                responses_json TEXT NOT NULL,
                score REAL NOT NULL,
                max_score REAL NOT NULL,
                feedback_json TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS weak_areas (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                profile_id INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
                subject_id INTEGER NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
                concept TEXT NOT NULL COLLATE NOCASE,
                source TEXT NOT NULL,
                severity REAL NOT NULL DEFAULT 1.0,
                hit_count INTEGER NOT NULL DEFAULT 1,
                last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(profile_id, subject_id, concept)
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS revision_sheets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                profile_id INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
                subject_id INTEGER NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

    def _migrate_legacy_conversations(
        self,
        cursor: sqlite3.Cursor,
        default_profile_id: int,
        default_subject_id: int,
    ) -> None:
        if not self._table_exists("conversations"):
            return

        columns = set(self._get_columns("conversations"))
        if {"profile_id", "subject_id"}.issubset(columns):
            return

        cursor.execute("ALTER TABLE conversations RENAME TO conversations_legacy")
        cursor.execute("DROP TABLE IF EXISTS conversation_search")
        cursor.execute(
            """
            CREATE TABLE conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                profile_id INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
                subject_id INTEGER NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
                user_message TEXT NOT NULL,
                assistant_message TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        cursor.execute(
            """
            INSERT INTO conversations (
                profile_id,
                subject_id,
                user_message,
                assistant_message,
                created_at
            )
            SELECT ?, ?, user_message, assistant_message, created_at
            FROM conversations_legacy
            """,
            (default_profile_id, default_subject_id),
        )
        cursor.execute("DROP TABLE conversations_legacy")

    def _table_exists(self, table_name: str) -> bool:
        row = self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table_name,),
        ).fetchone()
        return row is not None

    def _get_columns(self, table_name: str) -> list[str]:
        return [row["name"] for row in self.conn.execute(f"PRAGMA table_info({table_name})")]

    def _rebuild_search_indexes(self) -> None:
        cursor = self.conn.cursor()
        try:
            cursor.execute("DROP TABLE IF EXISTS conversation_search")
            cursor.execute("DROP TABLE IF EXISTS document_chunk_search")
            cursor.execute(
                """
                CREATE VIRTUAL TABLE conversation_search USING fts5(
                    user_message,
                    assistant_message
                )
                """
            )
            cursor.execute(
                """
                INSERT INTO conversation_search(rowid, user_message, assistant_message)
                SELECT id, user_message, assistant_message FROM conversations
                """
            )
            self._conversation_fts_enabled = True
        except sqlite3.OperationalError:
            self._conversation_fts_enabled = False

        try:
            cursor.execute(
                """
                CREATE VIRTUAL TABLE document_chunk_search USING fts5(
                    content
                )
                """
            )
            cursor.execute(
                """
                INSERT INTO document_chunk_search(rowid, content)
                SELECT id, content FROM document_chunks
                """
            )
            self._document_fts_enabled = True
        except sqlite3.OperationalError:
            self._document_fts_enabled = False
        self.conn.commit()

    def _ensure_default_profile(self, cursor: sqlite3.Cursor) -> int:
        existing = cursor.execute(
            "SELECT id FROM profiles WHERE name = ? COLLATE NOCASE",
            (DEFAULT_PROFILE_NAME,),
        ).fetchone()
        if existing:
            return int(existing["id"])
        pin_hash, pin_salt = self._hash_pin(DEFAULT_PROFILE_PIN)
        cursor.execute(
            """
            INSERT INTO profiles (name, pin_hash, pin_salt)
            VALUES (?, ?, ?)
            """,
            (DEFAULT_PROFILE_NAME, pin_hash, pin_salt),
        )
        return int(cursor.lastrowid)

    def _ensure_default_subject(self, cursor: sqlite3.Cursor, profile_id: int) -> int:
        existing = cursor.execute(
            """
            SELECT id FROM subjects
            WHERE profile_id = ? AND name = ? COLLATE NOCASE
            """,
            (profile_id, DEFAULT_SUBJECT_NAME),
        ).fetchone()
        if existing:
            return int(existing["id"])
        cursor.execute(
            """
            INSERT INTO subjects (profile_id, name)
            VALUES (?, ?)
            """,
            (profile_id, DEFAULT_SUBJECT_NAME),
        )
        return int(cursor.lastrowid)

    def _hash_pin(self, pin: str, salt_hex: str | None = None) -> tuple[str, str]:
        salt = bytes.fromhex(salt_hex) if salt_hex else secrets.token_bytes(16)
        hashed = hashlib.scrypt(
            pin.encode("utf-8"),
            salt=salt,
            n=2**14,
            r=8,
            p=1,
        )
        return hashed.hex(), salt.hex()

    def validate_pin(self, pin: str) -> None:
        if not re.fullmatch(r"\d{4,8}", pin):
            raise ValueError("PIN must be 4 to 8 digits.")

    def list_profiles(self) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT id, name, created_at FROM profiles ORDER BY created_at ASC"
        ).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def get_profile(self, profile_id: int) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT id, name, created_at FROM profiles WHERE id = ?",
            (profile_id,),
        ).fetchone()
        return self._row_to_dict(row) if row else None

    def create_profile(self, name: str, pin: str) -> dict[str, Any]:
        """Create a new local profile and seed it with a default subject."""
        cleaned_name = name.strip()
        if not cleaned_name:
            raise ValueError("Profile name is required.")
        self.validate_pin(pin)
        pin_hash, pin_salt = self._hash_pin(pin)
        cursor = self.conn.cursor()
        cursor.execute(
            """
            INSERT INTO profiles (name, pin_hash, pin_salt)
            VALUES (?, ?, ?)
            """,
            (cleaned_name, pin_hash, pin_salt),
        )
        profile_id = int(cursor.lastrowid)
        self._ensure_default_subject(cursor, profile_id)
        self.conn.commit()
        return self.get_profile(profile_id) or {}

    def verify_profile(self, profile_id: int, pin: str) -> bool:
        row = self.conn.execute(
            "SELECT pin_hash, pin_salt FROM profiles WHERE id = ?",
            (profile_id,),
        ).fetchone()
        if not row:
            return False
        candidate_hash, _ = self._hash_pin(pin, row["pin_salt"])
        return secrets.compare_digest(candidate_hash, row["pin_hash"])

    def get_default_subject(self, profile_id: int) -> dict[str, Any]:
        row = self.conn.execute(
            """
            SELECT id, profile_id, name, created_at
            FROM subjects
            WHERE profile_id = ?
            ORDER BY CASE WHEN name = ? COLLATE NOCASE THEN 0 ELSE 1 END, created_at ASC
            LIMIT 1
            """,
            (profile_id, DEFAULT_SUBJECT_NAME),
        ).fetchone()
        if not row:
            cursor = self.conn.cursor()
            subject_id = self._ensure_default_subject(cursor, profile_id)
            self.conn.commit()
            return self.get_subject(subject_id) or {}
        return self._row_to_dict(row)

    def get_subject(self, subject_id: int) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT id, profile_id, name, created_at FROM subjects WHERE id = ?",
            (subject_id,),
        ).fetchone()
        return self._row_to_dict(row) if row else None

    def list_subjects(self, profile_id: int) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT id, profile_id, name, created_at
            FROM subjects
            WHERE profile_id = ?
            ORDER BY CASE WHEN name = ? COLLATE NOCASE THEN 0 ELSE 1 END, created_at ASC
            """,
            (profile_id, DEFAULT_SUBJECT_NAME),
        ).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def create_subject(self, profile_id: int, name: str) -> dict[str, Any]:
        """Create a subject under a specific profile."""
        cleaned_name = name.strip()
        if not cleaned_name:
            raise ValueError("Subject name is required.")
        cursor = self.conn.cursor()
        cursor.execute(
            """
            INSERT INTO subjects (profile_id, name)
            VALUES (?, ?)
            """,
            (profile_id, cleaned_name),
        )
        self.conn.commit()
        return self.get_subject(int(cursor.lastrowid)) or {}

    def rename_subject(self, subject_id: int, name: str) -> dict[str, Any]:
        cleaned_name = name.strip()
        if not cleaned_name:
            raise ValueError("Subject name is required.")
        self.conn.execute(
            "UPDATE subjects SET name = ? WHERE id = ?",
            (cleaned_name, subject_id),
        )
        self.conn.commit()
        return self.get_subject(subject_id) or {}

    def delete_subject(self, subject_id: int) -> None:
        subject = self.get_subject(subject_id)
        if not subject:
            return
        subjects = self.list_subjects(subject["profile_id"])
        if len(subjects) <= 1:
            raise ValueError("A profile must keep at least one subject.")
        self.conn.execute("DELETE FROM subjects WHERE id = ?", (subject_id,))
        self.conn.commit()
        self._rebuild_search_indexes()

    def add_interaction(
        self,
        profile_id: int,
        subject_id: int,
        user_message: str,
        assistant_message: str,
    ) -> dict[str, Any]:
        """Save a chat turn for one profile and one subject."""
        cursor = self.conn.cursor()
        cursor.execute(
            """
            INSERT INTO conversations (
                profile_id,
                subject_id,
                user_message,
                assistant_message
            )
            VALUES (?, ?, ?, ?)
            """,
            (profile_id, subject_id, user_message.strip(), assistant_message.strip()),
        )
        conversation_id = int(cursor.lastrowid)
        if self._conversation_fts_enabled:
            cursor.execute(
                """
                INSERT INTO conversation_search(rowid, user_message, assistant_message)
                VALUES (?, ?, ?)
                """,
                (conversation_id, user_message.strip(), assistant_message.strip()),
            )
        self.conn.commit()
        return self.get_conversation(conversation_id) or {}

    def get_conversation(self, conversation_id: int) -> dict[str, Any] | None:
        row = self.conn.execute(
            """
            SELECT id, profile_id, subject_id, user_message, assistant_message, created_at
            FROM conversations
            WHERE id = ?
            """,
            (conversation_id,),
        ).fetchone()
        return self._row_to_dict(row) if row else None

    def list_conversations(
        self,
        profile_id: int,
        subject_id: int,
        limit: int = 40,
    ) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT id, profile_id, subject_id, user_message, assistant_message, created_at
            FROM conversations
            WHERE profile_id = ? AND subject_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (profile_id, subject_id, limit),
        ).fetchall()
        return [self._row_to_dict(row) for row in reversed(rows)]

    def get_recent(
        self,
        profile_id: int,
        subject_id: int,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        return self.list_conversations(profile_id, subject_id, limit=limit)

    def get_last_conversation(self, profile_id: int, subject_id: int) -> dict[str, Any] | None:
        row = self.conn.execute(
            """
            SELECT id, profile_id, subject_id, user_message, assistant_message, created_at
            FROM conversations
            WHERE profile_id = ? AND subject_id = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (profile_id, subject_id),
        ).fetchone()
        return self._row_to_dict(row) if row else None

    def search_relevant(
        self,
        query: str,
        profile_id: int,
        subject_id: int,
        limit: int = 4,
    ) -> list[dict[str, Any]]:
        query = query.strip()
        if not query:
            return []

        if self._conversation_fts_enabled:
            search_query = self._build_fts_query(query)
            if search_query:
                try:
                    rows = self.conn.execute(
                        """
                        SELECT c.id, c.profile_id, c.subject_id, c.user_message, c.assistant_message, c.created_at
                        FROM conversation_search cs
                        JOIN conversations c ON c.id = cs.rowid
                        WHERE conversation_search MATCH ?
                          AND c.profile_id = ?
                          AND c.subject_id = ?
                        ORDER BY bm25(conversation_search)
                        LIMIT ?
                        """,
                        (search_query, profile_id, subject_id, limit),
                    ).fetchall()
                    return [self._row_to_dict(row) for row in rows]
                except sqlite3.OperationalError:
                    pass

        like_terms = [f"%{term}%" for term in self._tokenize(query)]
        if not like_terms:
            return []
        where_clause = " OR ".join(
            "(user_message LIKE ? OR assistant_message LIKE ?)" for _ in like_terms
        )
        params: list[Any] = [profile_id, subject_id]
        for term in like_terms:
            params.extend([term, term])
        params.append(limit)
        rows = self.conn.execute(
            f"""
            SELECT id, profile_id, subject_id, user_message, assistant_message, created_at
            FROM conversations
            WHERE profile_id = ? AND subject_id = ? AND ({where_clause})
            ORDER BY id DESC
            LIMIT ?
            """,
            params,
        ).fetchall()
        return [self._row_to_dict(row) for row in reversed(rows)]

    def clear_conversations(self, profile_id: int, subject_id: int) -> None:
        cursor = self.conn.cursor()
        cursor.execute(
            "DELETE FROM conversations WHERE profile_id = ? AND subject_id = ?",
            (profile_id, subject_id),
        )
        self.conn.commit()
        self._rebuild_search_indexes()

    def show_history(self, profile_id: int, subject_id: int) -> list[str]:
        rows = self.conn.execute(
            """
            SELECT user_message
            FROM conversations
            WHERE profile_id = ? AND subject_id = ?
            ORDER BY id DESC
            """,
            (profile_id, subject_id),
        ).fetchall()
        return [row["user_message"] for row in rows]

    def add_document(
        self,
        profile_id: int,
        subject_id: int,
        title: str,
        source_type: str,
        body: str,
        original_filename: str | None = None,
        stored_path: str | None = None,
    ) -> dict[str, Any]:
        """Save a note or uploaded document and index it in chunks for retrieval."""
        cleaned_title = title.strip() or "Untitled Notes"
        cleaned_body = body.strip()
        if not cleaned_body:
            raise ValueError("Document body is empty.")
        cursor = self.conn.cursor()
        cursor.execute(
            """
            INSERT INTO documents (
                profile_id,
                subject_id,
                title,
                source_type,
                original_filename,
                stored_path,
                body
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                profile_id,
                subject_id,
                cleaned_title,
                source_type,
                original_filename,
                stored_path,
                cleaned_body,
            ),
        )
        document_id = int(cursor.lastrowid)
        for chunk_index, chunk in enumerate(self._split_into_chunks(cleaned_body)):
            cursor.execute(
                """
                INSERT INTO document_chunks (
                    document_id,
                    profile_id,
                    subject_id,
                    chunk_index,
                    content
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (document_id, profile_id, subject_id, chunk_index, chunk),
            )
            chunk_id = int(cursor.lastrowid)
            if self._document_fts_enabled:
                cursor.execute(
                    """
                    INSERT INTO document_chunk_search(rowid, content)
                    VALUES (?, ?)
                    """,
                    (chunk_id, chunk),
                )
        self.conn.commit()
        return self.get_document(document_id) or {}

    def get_document(self, document_id: int) -> dict[str, Any] | None:
        row = self.conn.execute(
            """
            SELECT id, profile_id, subject_id, title, source_type, original_filename, stored_path, body, created_at
            FROM documents
            WHERE id = ?
            """,
            (document_id,),
        ).fetchone()
        return self._row_to_dict(row) if row else None

    def list_documents(self, profile_id: int, subject_id: int, limit: int = 30) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT id, profile_id, subject_id, title, source_type, original_filename, stored_path, body, created_at
            FROM documents
            WHERE profile_id = ? AND subject_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (profile_id, subject_id, limit),
        ).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def search_document_chunks(
        self,
        query: str,
        profile_id: int,
        subject_id: int,
        limit: int = 4,
    ) -> list[dict[str, Any]]:
        query = query.strip()
        if not query:
            return []
        if self._document_fts_enabled:
            search_query = self._build_fts_query(query)
            if search_query:
                try:
                    rows = self.conn.execute(
                        """
                        SELECT dc.id, dc.document_id, dc.profile_id, dc.subject_id, dc.chunk_index, dc.content, d.title
                        FROM document_chunk_search dcs
                        JOIN document_chunks dc ON dc.id = dcs.rowid
                        JOIN documents d ON d.id = dc.document_id
                        WHERE document_chunk_search MATCH ?
                          AND dc.profile_id = ?
                          AND dc.subject_id = ?
                        ORDER BY bm25(document_chunk_search)
                        LIMIT ?
                        """,
                        (search_query, profile_id, subject_id, limit),
                    ).fetchall()
                    return [self._row_to_dict(row) for row in rows]
                except sqlite3.OperationalError:
                    pass

        like_terms = [f"%{term}%" for term in self._tokenize(query)]
        if not like_terms:
            return []
        where_clause = " OR ".join("content LIKE ?" for _ in like_terms)
        params: list[Any] = [profile_id, subject_id]
        params.extend(like_terms)
        params.append(limit)
        rows = self.conn.execute(
            f"""
            SELECT dc.id, dc.document_id, dc.profile_id, dc.subject_id, dc.chunk_index, dc.content, d.title
            FROM document_chunks dc
            JOIN documents d ON d.id = dc.document_id
            WHERE dc.profile_id = ? AND dc.subject_id = ? AND ({where_clause})
            ORDER BY dc.id DESC
            LIMIT ?
            """,
            params,
        ).fetchall()
        return [self._row_to_dict(row) for row in reversed(rows)]

    def search_library(
        self,
        query: str,
        profile_id: int,
        subject_id: int,
        limit: int = 5,
    ) -> dict[str, list[dict[str, Any]]]:
        return {
            "conversations": self.search_relevant(query, profile_id, subject_id, limit=limit),
            "documents": self.search_document_chunks(query, profile_id, subject_id, limit=limit),
        }

    def build_study_context(
        self,
        profile_id: int,
        subject_id: int,
        query: str,
        recent_limit: int = 4,
        relevant_limit: int = 4,
        chunk_limit: int = 4,
        weak_limit: int = 5,
    ) -> str:
        """Assemble the blended context used for tutoring, plans, quizzes, and sheets."""
        sections: list[str] = []
        recent_rows = self.get_recent(profile_id, subject_id, limit=recent_limit)
        recent_keys = {
            (row["user_message"], row["assistant_message"]) for row in recent_rows
        }
        relevant_rows = [
            row
            for row in self.search_relevant(query, profile_id, subject_id, limit=relevant_limit)
            if (row["user_message"], row["assistant_message"]) not in recent_keys
        ]
        weak_areas = self.get_weak_areas(profile_id, subject_id, limit=weak_limit)
        chunks = self.search_document_chunks(query, profile_id, subject_id, limit=chunk_limit)

        if recent_rows:
            sections.append("Recent conversation:")
            sections.extend(self._conversation_lines(recent_rows))
        if relevant_rows:
            sections.append("Relevant past study context:")
            sections.extend(self._conversation_lines(relevant_rows))
        if chunks:
            sections.append("Relevant notes:")
            for chunk in chunks:
                sections.append(f"{chunk['title']}: {chunk['content']}")
        if weak_areas:
            sections.append("Known weak areas to reinforce:")
            for weak in weak_areas:
                sections.append(
                    f"{weak['concept']} (severity {weak['severity']:.1f}, hits {weak['hit_count']})"
                )
        return "\n".join(sections)

    def create_study_plan(
        self,
        profile_id: int,
        subject_id: int,
        goal: str,
        exam_date: str | None,
        days_per_week: int,
        minutes_per_day: int,
        focus_mode: str,
        title: str,
        content: str,
        plan_data: dict[str, Any],
    ) -> dict[str, Any]:
        cursor = self.conn.cursor()
        cursor.execute(
            """
            INSERT INTO study_plans (
                profile_id,
                subject_id,
                goal,
                exam_date,
                days_per_week,
                minutes_per_day,
                focus_mode,
                title,
                content,
                plan_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                profile_id,
                subject_id,
                goal.strip(),
                exam_date,
                days_per_week,
                minutes_per_day,
                focus_mode,
                title,
                content,
                json.dumps(plan_data),
            ),
        )
        self.conn.commit()
        return self.get_study_plan(int(cursor.lastrowid)) or {}

    def get_study_plan(self, plan_id: int) -> dict[str, Any] | None:
        row = self.conn.execute(
            """
            SELECT id, profile_id, subject_id, goal, exam_date, days_per_week, minutes_per_day,
                   focus_mode, title, content, plan_json, created_at
            FROM study_plans
            WHERE id = ?
            """,
            (plan_id,),
        ).fetchone()
        if not row:
            return None
        data = self._row_to_dict(row)
        data["plan_data"] = self._load_json(data.pop("plan_json"), {})
        return data

    def list_study_plans(self, profile_id: int, subject_id: int, limit: int = 10) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT id, profile_id, subject_id, goal, exam_date, days_per_week, minutes_per_day,
                   focus_mode, title, content, plan_json, created_at
            FROM study_plans
            WHERE profile_id = ? AND subject_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (profile_id, subject_id, limit),
        ).fetchall()
        plans = []
        for row in rows:
            data = self._row_to_dict(row)
            data["plan_data"] = self._load_json(data.pop("plan_json"), {})
            plans.append(data)
        return plans

    def bulk_create_flashcards(
        self,
        profile_id: int,
        subject_id: int,
        cards: list[dict[str, Any]],
        source_scope: str,
    ) -> list[dict[str, Any]]:
        cursor = self.conn.cursor()
        created_ids: list[int] = []
        for card in cards:
            cursor.execute(
                """
                INSERT INTO flashcards (
                    profile_id,
                    subject_id,
                    front,
                    back,
                    tags_json,
                    source_scope,
                    ease_factor,
                    interval_days,
                    repetitions,
                    next_due_at
                )
                VALUES (?, ?, ?, ?, ?, ?, 2.5, 0, 0, CURRENT_TIMESTAMP)
                """,
                (
                    profile_id,
                    subject_id,
                    card["front"].strip(),
                    card["back"].strip(),
                    json.dumps(card.get("tags", [])),
                    source_scope,
                ),
            )
            created_ids.append(int(cursor.lastrowid))
        self.conn.commit()
        return [self.get_flashcard(card_id) for card_id in created_ids if self.get_flashcard(card_id)]

    def get_flashcard(self, card_id: int) -> dict[str, Any] | None:
        row = self.conn.execute(
            """
            SELECT id, profile_id, subject_id, front, back, tags_json, source_scope, ease_factor,
                   interval_days, repetitions, next_due_at, last_reviewed_at, created_at
            FROM flashcards
            WHERE id = ?
            """,
            (card_id,),
        ).fetchone()
        if not row:
            return None
        data = self._row_to_dict(row)
        data["tags"] = self._load_json(data.pop("tags_json"), [])
        return data

    def list_flashcards(
        self,
        profile_id: int,
        subject_id: int,
        limit: int = 50,
        due_only: bool = False,
    ) -> list[dict[str, Any]]:
        condition = "AND next_due_at <= CURRENT_TIMESTAMP" if due_only else ""
        rows = self.conn.execute(
            f"""
            SELECT id, profile_id, subject_id, front, back, tags_json, source_scope, ease_factor,
                   interval_days, repetitions, next_due_at, last_reviewed_at, created_at
            FROM flashcards
            WHERE profile_id = ? AND subject_id = ? {condition}
            ORDER BY CASE WHEN next_due_at <= CURRENT_TIMESTAMP THEN 0 ELSE 1 END,
                     next_due_at ASC, id DESC
            LIMIT ?
            """,
            (profile_id, subject_id, limit),
        ).fetchall()
        cards = []
        for row in rows:
            data = self._row_to_dict(row)
            data["tags"] = self._load_json(data.pop("tags_json"), [])
            cards.append(data)
        return cards

    def update_flashcard_schedule(
        self,
        card_id: int,
        rating: str,
        interval_days: int,
        ease_factor: float,
        repetitions: int,
        next_due_at: str,
    ) -> dict[str, Any]:
        card = self.get_flashcard(card_id)
        if not card:
            raise ValueError("Flashcard not found.")
        cursor = self.conn.cursor()
        cursor.execute(
            """
            UPDATE flashcards
            SET interval_days = ?,
                ease_factor = ?,
                repetitions = ?,
                next_due_at = ?,
                last_reviewed_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (interval_days, ease_factor, repetitions, next_due_at, card_id),
        )
        cursor.execute(
            """
            INSERT INTO flashcard_reviews (
                card_id,
                profile_id,
                subject_id,
                rating,
                interval_days,
                ease_factor,
                next_due_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                card_id,
                card["profile_id"],
                card["subject_id"],
                rating,
                interval_days,
                ease_factor,
                next_due_at,
            ),
        )
        self.conn.commit()
        return self.get_flashcard(card_id) or {}

    def create_quiz(
        self,
        profile_id: int,
        subject_id: int,
        mode: str,
        difficulty: str,
        question_count: int,
        time_limit_minutes: int | None,
        title: str,
        questions: list[dict[str, Any]],
    ) -> dict[str, Any]:
        cursor = self.conn.cursor()
        cursor.execute(
            """
            INSERT INTO quizzes (
                profile_id,
                subject_id,
                mode,
                difficulty,
                question_count,
                time_limit_minutes,
                title,
                questions_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                profile_id,
                subject_id,
                mode,
                difficulty,
                question_count,
                time_limit_minutes,
                title,
                json.dumps(questions),
            ),
        )
        self.conn.commit()
        return self.get_quiz(int(cursor.lastrowid)) or {}

    def get_quiz(self, quiz_id: int) -> dict[str, Any] | None:
        row = self.conn.execute(
            """
            SELECT id, profile_id, subject_id, mode, difficulty, question_count, time_limit_minutes,
                   title, questions_json, created_at
            FROM quizzes
            WHERE id = ?
            """,
            (quiz_id,),
        ).fetchone()
        if not row:
            return None
        data = self._row_to_dict(row)
        data["questions"] = self._load_json(data.pop("questions_json"), [])
        return data

    def list_quizzes(self, profile_id: int, subject_id: int, limit: int = 10) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT id, profile_id, subject_id, mode, difficulty, question_count, time_limit_minutes,
                   title, questions_json, created_at
            FROM quizzes
            WHERE profile_id = ? AND subject_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (profile_id, subject_id, limit),
        ).fetchall()
        quizzes = []
        for row in rows:
            data = self._row_to_dict(row)
            data["questions"] = self._load_json(data.pop("questions_json"), [])
            quizzes.append(data)
        return quizzes

    def create_quiz_attempt(
        self,
        quiz_id: int,
        profile_id: int,
        subject_id: int,
        responses: dict[str, Any],
        score: float,
        max_score: float,
        feedback: list[dict[str, Any]],
    ) -> dict[str, Any]:
        cursor = self.conn.cursor()
        cursor.execute(
            """
            INSERT INTO quiz_attempts (
                quiz_id,
                profile_id,
                subject_id,
                responses_json,
                score,
                max_score,
                feedback_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                quiz_id,
                profile_id,
                subject_id,
                json.dumps(responses),
                score,
                max_score,
                json.dumps(feedback),
            ),
        )
        self.conn.commit()
        return self.get_quiz_attempt(int(cursor.lastrowid)) or {}

    def get_quiz_attempt(self, attempt_id: int) -> dict[str, Any] | None:
        row = self.conn.execute(
            """
            SELECT id, quiz_id, profile_id, subject_id, responses_json, score, max_score, feedback_json, created_at
            FROM quiz_attempts
            WHERE id = ?
            """,
            (attempt_id,),
        ).fetchone()
        if not row:
            return None
        data = self._row_to_dict(row)
        data["responses"] = self._load_json(data.pop("responses_json"), {})
        data["feedback"] = self._load_json(data.pop("feedback_json"), [])
        return data

    def list_quiz_attempts(
        self,
        profile_id: int,
        subject_id: int,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT id, quiz_id, profile_id, subject_id, responses_json, score, max_score, feedback_json, created_at
            FROM quiz_attempts
            WHERE profile_id = ? AND subject_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (profile_id, subject_id, limit),
        ).fetchall()
        attempts = []
        for row in rows:
            data = self._row_to_dict(row)
            data["responses"] = self._load_json(data.pop("responses_json"), {})
            data["feedback"] = self._load_json(data.pop("feedback_json"), [])
            attempts.append(data)
        return attempts

    def upsert_weak_area(
        self,
        profile_id: int,
        subject_id: int,
        concept: str,
        source: str,
        severity_delta: float = 1.0,
    ) -> None:
        cleaned_concept = concept.strip()
        if not cleaned_concept:
            return
        self.conn.execute(
            """
            INSERT INTO weak_areas (
                profile_id,
                subject_id,
                concept,
                source,
                severity,
                hit_count,
                last_seen
            )
            VALUES (?, ?, ?, ?, ?, 1, CURRENT_TIMESTAMP)
            ON CONFLICT(profile_id, subject_id, concept)
            DO UPDATE SET
                source = excluded.source,
                severity = weak_areas.severity + excluded.severity,
                hit_count = weak_areas.hit_count + 1,
                last_seen = CURRENT_TIMESTAMP
            """,
            (profile_id, subject_id, cleaned_concept, source, severity_delta),
        )
        self.conn.commit()

    def get_weak_areas(
        self,
        profile_id: int,
        subject_id: int,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT id, profile_id, subject_id, concept, source, severity, hit_count, last_seen
            FROM weak_areas
            WHERE profile_id = ? AND subject_id = ?
            ORDER BY severity DESC, last_seen DESC
            LIMIT ?
            """,
            (profile_id, subject_id, limit),
        ).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def save_revision_sheet(
        self,
        profile_id: int,
        subject_id: int,
        title: str,
        content: str,
    ) -> dict[str, Any]:
        cursor = self.conn.cursor()
        cursor.execute(
            """
            INSERT INTO revision_sheets (profile_id, subject_id, title, content)
            VALUES (?, ?, ?, ?)
            """,
            (profile_id, subject_id, title.strip(), content),
        )
        self.conn.commit()
        return self.get_revision_sheet(int(cursor.lastrowid)) or {}

    def get_revision_sheet(self, sheet_id: int) -> dict[str, Any] | None:
        row = self.conn.execute(
            """
            SELECT id, profile_id, subject_id, title, content, created_at
            FROM revision_sheets
            WHERE id = ?
            """,
            (sheet_id,),
        ).fetchone()
        return self._row_to_dict(row) if row else None

    def list_revision_sheets(
        self,
        profile_id: int,
        subject_id: int,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT id, profile_id, subject_id, title, content, created_at
            FROM revision_sheets
            WHERE profile_id = ? AND subject_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (profile_id, subject_id, limit),
        ).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def log_session(
        self,
        profile_id: int,
        subject_id: int,
        session_type: str,
        ref_kind: str | None = None,
        ref_id: int | None = None,
        duration_minutes: int = 0,
        summary: str | None = None,
        score: float | None = None,
    ) -> dict[str, Any]:
        cursor = self.conn.cursor()
        cursor.execute(
            """
            INSERT INTO study_sessions (
                profile_id,
                subject_id,
                session_type,
                ref_kind,
                ref_id,
                duration_minutes,
                summary,
                score
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                profile_id,
                subject_id,
                session_type,
                ref_kind,
                ref_id,
                duration_minutes,
                summary,
                score,
            ),
        )
        self.conn.commit()
        return self.get_study_session(int(cursor.lastrowid)) or {}

    def get_study_session(self, session_id: int) -> dict[str, Any] | None:
        row = self.conn.execute(
            """
            SELECT id, profile_id, subject_id, session_type, ref_kind, ref_id, duration_minutes, summary, score, created_at
            FROM study_sessions
            WHERE id = ?
            """,
            (session_id,),
        ).fetchone()
        return self._row_to_dict(row) if row else None

    def list_recent_sessions(
        self,
        profile_id: int,
        subject_id: int,
        limit: int = 12,
    ) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT id, profile_id, subject_id, session_type, ref_kind, ref_id, duration_minutes, summary, score, created_at
            FROM study_sessions
            WHERE profile_id = ? AND subject_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (profile_id, subject_id, limit),
        ).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def get_dashboard_stats(self, profile_id: int, subject_id: int) -> dict[str, Any]:
        """Return the small set of numbers and recent items shown on the dashboard."""
        total_interactions = self.conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM conversations
            WHERE profile_id = ? AND subject_id = ?
            """,
            (profile_id, subject_id),
        ).fetchone()["count"]
        notes_count = self.conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM documents
            WHERE profile_id = ? AND subject_id = ?
            """,
            (profile_id, subject_id),
        ).fetchone()["count"]
        due_cards = self.conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM flashcards
            WHERE profile_id = ? AND subject_id = ? AND next_due_at <= CURRENT_TIMESTAMP
            """,
            (profile_id, subject_id),
        ).fetchone()["count"]
        total_cards = self.conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM flashcards
            WHERE profile_id = ? AND subject_id = ?
            """,
            (profile_id, subject_id),
        ).fetchone()["count"]
        quizzes_taken = self.conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM quiz_attempts
            WHERE profile_id = ? AND subject_id = ?
            """,
            (profile_id, subject_id),
        ).fetchone()["count"]
        avg_row = self.conn.execute(
            """
            SELECT AVG(CASE WHEN max_score = 0 THEN 0 ELSE (score / max_score) * 100 END) AS avg_score
            FROM quiz_attempts
            WHERE profile_id = ? AND subject_id = ?
            """,
            (profile_id, subject_id),
        ).fetchone()
        plans_count = self.conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM study_plans
            WHERE profile_id = ? AND subject_id = ?
            """,
            (profile_id, subject_id),
        ).fetchone()["count"]
        sheets_count = self.conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM revision_sheets
            WHERE profile_id = ? AND subject_id = ?
            """,
            (profile_id, subject_id),
        ).fetchone()["count"]
        session_rows = self.conn.execute(
            """
            SELECT duration_minutes, created_at
            FROM study_sessions
            WHERE profile_id = ? AND subject_id = ?
            ORDER BY created_at DESC
            """,
            (profile_id, subject_id),
        ).fetchall()
        total_minutes = int(
            sum(int(row["duration_minutes"] or 0) for row in session_rows)
        )
        streak = self._compute_streak([row["created_at"] for row in session_rows])
        return {
            "interactions": total_interactions,
            "notes_count": notes_count,
            "due_cards": due_cards,
            "total_cards": total_cards,
            "quizzes_taken": quizzes_taken,
            "average_score": float(avg_row["avg_score"] or 0.0),
            "plans_count": plans_count,
            "revision_sheets_count": sheets_count,
            "time_spent_minutes": total_minutes,
            "streak_days": streak,
            "weak_areas": self.get_weak_areas(profile_id, subject_id, limit=6),
            "recent_activity": self.list_recent_sessions(profile_id, subject_id, limit=8),
            "documents": self.list_documents(profile_id, subject_id, limit=5),
            "plans": self.list_study_plans(profile_id, subject_id, limit=3),
        }

    def close(self) -> None:
        self.conn.close()

    def _tokenize(self, text: str) -> list[str]:
        return [token for token in re.findall(r"[a-zA-Z0-9]+", text.lower()) if len(token) > 2]

    def _build_fts_query(self, text: str) -> str:
        tokens = self._tokenize(text)
        return " OR ".join(f'"{token}"' for token in tokens)

    def _split_into_chunks(
        self,
        text: str,
        chunk_words: int = 140,
        overlap_words: int = 35,
    ) -> list[str]:
        normalized = " ".join(text.split())
        if not normalized:
            return []
        words = normalized.split(" ")
        if len(words) <= chunk_words:
            return [normalized]
        chunks: list[str] = []
        start = 0
        while start < len(words):
            end = min(start + chunk_words, len(words))
            chunk = " ".join(words[start:end]).strip()
            if chunk:
                chunks.append(chunk)
            if end >= len(words):
                break
            start = max(end - overlap_words, start + 1)
        return chunks

    def _conversation_lines(self, rows: Iterable[dict[str, Any]]) -> list[str]:
        lines = []
        for row in rows:
            lines.append(f"User: {row['user_message']}")
            lines.append(f"Assistant: {row['assistant_message']}")
        return lines

    def _compute_streak(self, created_values: Iterable[str]) -> int:
        days = {
            self._parse_datetime(value).date()
            for value in created_values
            if value
        }
        if not days:
            return 0
        current = date.today()
        streak = 0
        while current in days:
            streak += 1
            current = current.fromordinal(current.toordinal() - 1)
        return streak

    def _parse_datetime(self, value: str) -> datetime:
        return datetime.fromisoformat(value)

    def _row_to_dict(self, row: sqlite3.Row | None) -> dict[str, Any]:
        """Keep row conversion in one place so cursor results stay consistent."""
        return dict(row) if row is not None else {}

    def _load_json(self, value: str | None, default: Any) -> Any:
        if not value:
            return default
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return default
