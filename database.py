"""
Nokia Storage - Database Module
SQLite database operations for phones and spare parts.
"""

import os
import sqlite3
from datetime import datetime


class NokiaDatabase:
    def __init__(self, db_path):
        self.db_path = db_path
        self.conn = None
        self.init_db()

    def init_db(self):
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self._create_tables()

    def _create_tables(self):
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS phones (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                release_date TEXT,
                appearance_condition TEXT,
                working_condition TEXT,
                remarks TEXT,
                image_path TEXT,
                created_at TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS spare_parts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                phone_id TEXT,
                image_path TEXT,
                description TEXT,
                created_at TEXT DEFAULT (datetime('now'))
            );

            CREATE INDEX IF NOT EXISTS idx_phones_name ON phones(name);
            CREATE INDEX IF NOT EXISTS idx_spare_name ON spare_parts(name);
            CREATE INDEX IF NOT EXISTS idx_spare_phone ON spare_parts(phone_id);
        """)
        self.conn.commit()

    # ── Phone CRUD ──────────────────────────────────────────────

    def add_phone(self, phone_id, name, release_date="", appearance="",
                  working="", remarks="", image_path=""):
        self.conn.execute(
            """INSERT OR REPLACE INTO phones
               (id, name, release_date, appearance_condition,
                working_condition, remarks, image_path, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (phone_id, name, release_date, appearance, working,
             remarks, image_path, datetime.now().isoformat())
        )
        self.conn.commit()

    def update_phone(self, phone_id, **kwargs):
        allowed = {"name", "release_date", "appearance_condition",
                    "working_condition", "remarks", "image_path"}
        fields = {k: v for k, v in kwargs.items() if k in allowed}
        if not fields:
            return
        set_clause = ", ".join(f"{k} = ?" for k in fields)
        values = list(fields.values()) + [phone_id]
        self.conn.execute(
            f"UPDATE phones SET {set_clause} WHERE id = ?", values
        )
        self.conn.commit()

    def delete_phone(self, phone_id):
        self.conn.execute("DELETE FROM phones WHERE id = ?", (phone_id,))
        self.conn.commit()

    def get_phone(self, phone_id):
        cur = self.conn.execute("SELECT * FROM phones WHERE id = ?", (phone_id,))
        row = cur.fetchone()
        return dict(row) if row else None

    def get_all_phones(self):
        cur = self.conn.execute(
            "SELECT * FROM phones ORDER BY name, id"
        )
        return [dict(r) for r in cur.fetchall()]

    def search_phones(self, query):
        q = f"%{query}%"
        cur = self.conn.execute(
            """SELECT * FROM phones
               WHERE name LIKE ? OR id LIKE ? OR release_date LIKE ?
               ORDER BY name, id""",
            (q, q, q)
        )
        return [dict(r) for r in cur.fetchall()]

    # ── Spare Parts CRUD ────────────────────────────────────────

    def add_spare_part(self, name, phone_id="", image_path="", description=""):
        self.conn.execute(
            """INSERT INTO spare_parts (name, phone_id, image_path, description, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (name, phone_id, image_path, description, datetime.now().isoformat())
        )
        self.conn.commit()

    def update_spare_part(self, spare_id, **kwargs):
        allowed = {"name", "phone_id", "image_path", "description"}
        fields = {k: v for k, v in kwargs.items() if k in allowed}
        if not fields:
            return
        set_clause = ", ".join(f"{k} = ?" for k in fields)
        values = list(fields.values()) + [spare_id]
        self.conn.execute(
            f"UPDATE spare_parts SET {set_clause} WHERE id = ?", values
        )
        self.conn.commit()

    def delete_spare_part(self, spare_id):
        self.conn.execute("DELETE FROM spare_parts WHERE id = ?", (spare_id,))
        self.conn.commit()

    def get_spare_part(self, spare_id):
        cur = self.conn.execute(
            "SELECT * FROM spare_parts WHERE id = ?", (spare_id,)
        )
        row = cur.fetchone()
        return dict(row) if row else None

    def get_all_spare_parts(self):
        cur = self.conn.execute(
            "SELECT * FROM spare_parts ORDER BY name"
        )
        return [dict(r) for r in cur.fetchall()]

    def get_spare_parts_for_phone(self, phone_name):
        cur = self.conn.execute(
            "SELECT * FROM spare_parts WHERE name LIKE ? ORDER BY created_at",
            (f"%{phone_name}%",)
        )
        return [dict(r) for r in cur.fetchall()]

    def search_spare_parts(self, query):
        q = f"%{query}%"
        cur = self.conn.execute(
            """SELECT * FROM spare_parts
               WHERE name LIKE ? OR description LIKE ?
               ORDER BY name""",
            (q, q)
        )
        return [dict(r) for r in cur.fetchall()]

    # ── Combined Search ─────────────────────────────────────────

    def search_all(self, query):
        phones = self.search_phones(query)
        spares = self.search_spare_parts(query)
        return phones, spares

    # ── Import / Export ─────────────────────────────────────────

    def import_phones_from_rows(self, rows):
        """Import phones from list of dicts with keys:
           id, name, release_date, appearance_condition,
           working_condition, remarks"""
        count = 0
        for row in rows:
            try:
                self.conn.execute(
                    """INSERT OR IGNORE INTO phones
                       (id, name, release_date, appearance_condition,
                        working_condition, remarks, image_path, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, '', ?)""",
                    (
                        str(row.get("id", "")),
                        str(row.get("name", "")),
                        str(row.get("release_date", "")),
                        str(row.get("appearance_condition", "")),
                        str(row.get("working_condition", "")),
                        str(row.get("remarks", "")),
                        datetime.now().isoformat(),
                    )
                )
                count += 1
            except Exception:
                continue
        self.conn.commit()
        return count

    def export_phones(self):
        return self.get_all_phones()

    def export_spare_parts(self):
        return self.get_all_spare_parts()

    def get_phone_count(self):
        cur = self.conn.execute("SELECT COUNT(*) FROM phones")
        return cur.fetchone()[0]

    def get_spare_count(self):
        cur = self.conn.execute("SELECT COUNT(*) FROM spare_parts")
        return cur.fetchone()[0]

    def close(self):
        if self.conn:
            self.conn.close()
