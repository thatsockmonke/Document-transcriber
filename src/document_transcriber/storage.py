"""SQLite project storage. Originals are immutable; edits are autosaved locally."""

from __future__ import annotations

import json
import shutil
import sqlite3
from contextlib import nullcontext
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4


@dataclass
class Page:
    id: str
    document_id: str
    number: int
    image_path: Path
    original_path: Path
    text: str
    tokens: list[dict]
    notes: str
    reviewed: bool
    engine: str


class ProjectStore:
    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "images").mkdir(exist_ok=True)
        self.db = sqlite3.connect(self.root / "project.sqlite3")
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS documents (
                id TEXT PRIMARY KEY, title TEXT NOT NULL, source TEXT NOT NULL,
                created TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS pages (
                id TEXT PRIMARY KEY, document_id TEXT NOT NULL REFERENCES documents(id)
                ON DELETE CASCADE, number INTEGER NOT NULL, image_path TEXT NOT NULL,
                original_path TEXT NOT NULL, text TEXT NOT NULL DEFAULT '',
                tokens TEXT NOT NULL DEFAULT '[]', notes TEXT NOT NULL DEFAULT '',
                reviewed INTEGER NOT NULL DEFAULT 0, engine TEXT NOT NULL DEFAULT '',
                updated TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS vocabulary (word TEXT PRIMARY KEY COLLATE NOCASE);
            CREATE TABLE IF NOT EXISTS corrections (
                original TEXT PRIMARY KEY COLLATE NOCASE, replacement TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS preferences (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS revisions (
                id INTEGER PRIMARY KEY, page_id TEXT NOT NULL REFERENCES pages(id) ON DELETE CASCADE,
                text TEXT NOT NULL, source TEXT NOT NULL, created TEXT DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE IF NOT EXISTS queue (
                id INTEGER PRIMARY KEY, page_id TEXT NOT NULL REFERENCES pages(id) ON DELETE CASCADE,
                engine TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'queued', priority INTEGER DEFAULT 0,
                error TEXT DEFAULT '');
        """)

    def close(self):
        self.db.close()

    def add_document(self, title: str, source: str, images: list[Path]) -> str:
        if not images:
            raise ValueError("The document contains no pages.")
        document_id = uuid4().hex
        copied = []
        try:
            with self.db:
                self.db.execute(
                    "INSERT INTO documents(id,title,source) VALUES (?,?,?)",
                    (document_id, title, source),
                )
                for number, image in enumerate(images, 1):
                    page_id = uuid4().hex
                    relative = f"images/{page_id}.png"
                    target = self.root / relative
                    copied.append(target)
                    shutil.copyfile(image, target)
                    self.db.execute(
                        """INSERT INTO pages
                        (id,document_id,number,image_path,original_path) VALUES (?,?,?,?,?)""",
                        (page_id, document_id, number, relative, relative),
                    )
        except Exception:
            for path in copied:
                path.unlink(missing_ok=True)
            raise
        return document_id

    def documents(self, query: str = "") -> list[dict]:
        # instr performs literal search; % and _ are ordinary characters.
        return [
            dict(row)
            for row in self.db.execute(
                """
            SELECT d.*, COUNT(p.id) AS page_count,
            SUM(p.reviewed) AS reviewed_count FROM documents d JOIN pages p
            ON p.document_id=d.id
            WHERE instr(lower(d.title),lower(?))>0 OR EXISTS (
                SELECT 1 FROM pages q WHERE q.document_id=d.id
                AND instr(lower(q.text),lower(?))>0)
            GROUP BY d.id ORDER BY d.created,d.rowid
        """,
                (query, query),
            )
        ]

    def pages(self, document_id: str) -> list[Page]:
        return [
            self._page(row)
            for row in self.db.execute(
                "SELECT * FROM pages WHERE document_id=? ORDER BY number", (document_id,)
            )
        ]

    def page(self, page_id: str) -> Page:
        row = self.db.execute("SELECT * FROM pages WHERE id=?", (page_id,)).fetchone()
        if row is None:
            raise KeyError(page_id)
        return self._page(row)

    def _page(self, row) -> Page:
        return Page(
            row["id"],
            row["document_id"],
            row["number"],
            self.root / row["image_path"],
            self.root / row["original_path"],
            row["text"],
            json.loads(row["tokens"]),
            row["notes"],
            bool(row["reviewed"]),
            row["engine"],
        )

    def save_page(
        self,
        page_id: str,
        text: str,
        tokens: list[dict],
        notes: str,
        reviewed: bool,
        engine: str,
        source: str = "manual",
        _transaction: bool = True,
    ):
        with self.db if _transaction else nullcontext():
            old = self.db.execute("SELECT text FROM pages WHERE id=?", (page_id,)).fetchone()
            if old and old[0] != text:
                if not self.db.execute(
                    "SELECT 1 FROM revisions WHERE page_id=?", (page_id,)
                ).fetchone():
                    self.db.execute(
                        "INSERT INTO revisions(page_id,text,source) VALUES (?,?,?)",
                        (page_id, old[0], "original"),
                    )
                self.db.execute(
                    "INSERT INTO revisions(page_id,text,source) VALUES (?,?,?)",
                    (page_id, text, source),
                )
            self.db.execute(
                """UPDATE pages SET text=?,tokens=?,notes=?,reviewed=?,engine=?,
                updated=CURRENT_TIMESTAMP WHERE id=?""",
                (text, json.dumps(tokens), notes, int(reviewed), engine, page_id),
            )

    def set_image(self, page_id: str, path: Path):
        relative = str(path.resolve().relative_to(self.root))
        with self.db:
            self.db.execute(
                "UPDATE pages SET image_path=?, tokens='[]',reviewed=0 WHERE id=?",
                (relative, page_id),
            )

    def save_ocr_batch(self, results):
        """Apply a completed batch atomically, retaining notes and source scans."""
        with self.db:
            for page_id, result in results:
                if result.text:
                    page = self.page(page_id)
                    self.save_page(
                        page_id,
                        result.text,
                        result.tokens,
                        page.notes,
                        False,
                        result.engine,
                        "OCR",
                        False,
                    )

    def rename_document(self, document_id: str, title: str):
        if not title.strip():
            raise ValueError("A document needs a title.")
        with self.db:
            self.db.execute("UPDATE documents SET title=? WHERE id=?", (title.strip(), document_id))

    def delete_document(self, document_id: str):
        paths = set()
        for page in self.pages(document_id):
            paths.update((page.image_path, page.original_path))
            paths.update((self.root / "images").glob(f"{page.id}-*.png"))
            for prefix in ["fidelity:", "lines:", "regions:"]:
                self.db.execute("DELETE FROM preferences WHERE key=?", (prefix + page.id,))
        with self.db:
            self.db.execute("DELETE FROM documents WHERE id=?", (document_id,))
        for path in paths:
            path.unlink(missing_ok=True)

    def vocabulary(self) -> list[str]:
        return [r[0] for r in self.db.execute("SELECT word FROM vocabulary ORDER BY word")]

    def add_word(self, word: str):
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO vocabulary VALUES (?)", (word.casefold(),))

    def remove_word(self, word: str):
        with self.db:
            self.db.execute("DELETE FROM vocabulary WHERE word=?", (word.casefold(),))

    def corrections(self) -> dict[str, str]:
        return dict(self.db.execute("SELECT original,replacement FROM corrections"))

    def learn_correction(self, original: str, replacement: str):
        with self.db:
            self.db.execute(
                "INSERT OR REPLACE INTO corrections VALUES (?,?)",
                (original.casefold(), replacement),
            )

    def forget_corrections(self):
        with self.db:
            self.db.execute("DELETE FROM corrections")

    def reviewed_texts(self):
        return list(
            self.db.execute(
                "SELECT id,text FROM pages WHERE reviewed=1 ORDER BY updated DESC LIMIT 500"
            )
        )

    def preference(self, key, default=None):
        row = self.db.execute("SELECT value FROM preferences WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def set_preference(self, key, value):
        with self.db:
            self.db.execute(
                "INSERT OR REPLACE INTO preferences VALUES (?,?)", (key, json.dumps(value))
            )

    def writing_rules(self):
        from .rules import default_rules, validate_rules

        data = self.preference("writing_rules")
        return default_rules() if data is None else validate_rules(data)

    def save_rules(self, rules):
        from .rules import validate_rules

        data = [rule.to_dict() for rule in rules]
        validate_rules(data)
        self.set_preference("writing_rules", data)

    def revisions(self, page_id):
        return [
            dict(r)
            for r in self.db.execute(
                "SELECT * FROM revisions WHERE page_id=? ORDER BY id DESC", (page_id,)
            )
        ]

    def enqueue(self, page_ids, engine):
        with self.db:
            for page_id in page_ids:
                if not self.db.execute(
                    "SELECT 1 FROM queue WHERE page_id=? AND status IN ('queued','running')",
                    (page_id,),
                ).fetchone():
                    self.db.execute(
                        "INSERT INTO queue(page_id,engine) VALUES (?,?)", (page_id, engine)
                    )

    def queue_items(self):
        return [
            dict(r)
            for r in self.db.execute(
                "SELECT q.*,d.title,p.number FROM queue q JOIN pages p ON p.id=q.page_id JOIN documents d ON d.id=p.document_id ORDER BY priority DESC,q.id"
            )
        ]

    def queue_update(self, identity, status, error=""):
        with self.db:
            self.db.execute(
                "UPDATE queue SET status=?,error=? WHERE id=?", (status, error, identity)
            )
