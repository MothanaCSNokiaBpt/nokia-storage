"""
Nokia Storage - Database Module
SQLite database operations for phones and spare parts.
Images stored as BLOB thumbnails for reliable display on Android.
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
                description TEXT,
                image_path TEXT,
                image_data BLOB,
                avg_price REAL DEFAULT 0,
                rarity_score REAL DEFAULT 0,
                created_at TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS wall_items (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                release_date TEXT,
                appearance_condition TEXT,
                working_condition TEXT,
                remarks TEXT,
                image_path TEXT,
                image_data BLOB,
                created_at TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS spare_parts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                phone_id TEXT,
                image_path TEXT,
                image_data BLOB,
                description TEXT,
                created_at TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS phone_gallery (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                phone_id TEXT NOT NULL,
                image_data BLOB NOT NULL,
                created_at TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS spare_gallery (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                spare_id INTEGER NOT NULL,
                image_data BLOB NOT NULL,
                created_at TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS wall_gallery (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                wall_id TEXT NOT NULL,
                image_data BLOB NOT NULL,
                created_at TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS general_gallery (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                image_data BLOB NOT NULL,
                caption TEXT,
                created_at TEXT DEFAULT (datetime('now'))
            );

            CREATE INDEX IF NOT EXISTS idx_phones_name ON phones(name);
            CREATE INDEX IF NOT EXISTS idx_spare_name ON spare_parts(name);
            CREATE INDEX IF NOT EXISTS idx_spare_phone ON spare_parts(phone_id);
            CREATE INDEX IF NOT EXISTS idx_gallery_phone ON phone_gallery(phone_id);
            CREATE INDEX IF NOT EXISTS idx_sgallery_spare ON spare_gallery(spare_id);
            CREATE INDEX IF NOT EXISTS idx_wall_name ON wall_items(name);
        """)
        # Add image_data column if upgrading from old schema
        try:
            self.conn.execute("SELECT image_data FROM phones LIMIT 1")
        except Exception:
            try:
                self.conn.execute("ALTER TABLE phones ADD COLUMN image_data BLOB")
            except Exception:
                pass
        try:
            self.conn.execute("SELECT image_data FROM spare_parts LIMIT 1")
        except Exception:
            try:
                self.conn.execute("ALTER TABLE spare_parts ADD COLUMN image_data BLOB")
            except Exception:
                pass
        # Add price/rarity columns if upgrading
        for col in ['avg_price', 'rarity_score']:
            try:
                self.conn.execute(f"SELECT {col} FROM phones LIMIT 1")
            except Exception:
                try:
                    self.conn.execute(f"ALTER TABLE phones ADD COLUMN {col} REAL DEFAULT 0")
                except Exception:
                    pass
        # Add description column if upgrading
        try:
            self.conn.execute("SELECT description FROM phones LIMIT 1")
        except Exception:
            try:
                self.conn.execute("ALTER TABLE phones ADD COLUMN description TEXT")
            except Exception:
                pass
        self.conn.commit()

    # ── Image helpers ───────────────────────────────────────────

    @staticmethod
    def read_image_file(path):
        """Read an image file and return bytes, or None."""
        if not path:
            return None
        try:
            # Handle Android content:// URIs
            if path.startswith("content://"):
                try:
                    from jnius import autoclass
                    PythonActivity = autoclass("org.kivy.android.PythonActivity")
                    context = PythonActivity.mActivity.getApplicationContext()
                    cr = context.getContentResolver()
                    uri = autoclass("android.net.Uri").parse(path)
                    stream = cr.openInputStream(uri)
                    ByteArrayOutputStream = autoclass("java.io.ByteArrayOutputStream")
                    baos = ByteArrayOutputStream()
                    buf = bytearray(4096)
                    jbuf = autoclass("java.lang.reflect.Array").newInstance(
                        autoclass("java.lang.Byte").TYPE, 4096)
                    while True:
                        n = stream.read(jbuf)
                        if n == -1:
                            break
                        baos.write(jbuf, 0, n)
                    stream.close()
                    return bytes(baos.toByteArray())
                except Exception:
                    return None
            if os.path.exists(path):
                with open(path, "rb") as f:
                    return f.read()
        except Exception:
            pass
        return None

    @staticmethod
    def make_thumbnail(image_bytes, max_size=300):
        """Return image bytes as-is. Compression handled by the app."""
        return image_bytes

    # ── Phone CRUD ──────────────────────────────────────────────

    def add_phone(self, phone_id, name, release_date="", appearance="",
                  working="", remarks="", image_path="", image_bytes=None,
                  avg_price=0, rarity_score=0, description=""):
        if not image_bytes and image_path:
            image_bytes = self.read_image_file(image_path)
            if image_bytes:
                image_bytes = self.make_thumbnail(image_bytes)
        self.conn.execute(
            """INSERT OR REPLACE INTO phones
               (id, name, release_date, appearance_condition,
                working_condition, remarks, description, image_path, image_data,
                avg_price, rarity_score, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (phone_id, name, release_date, appearance, working,
             remarks, description or "", image_path or "", image_bytes,
             avg_price or 0, rarity_score or 0,
             datetime.now().isoformat())
        )
        self.conn.commit()

    def update_phone(self, phone_id, **kwargs):
        allowed = {"name", "release_date", "appearance_condition",
                    "working_condition", "remarks", "description",
                    "image_path", "avg_price", "rarity_score"}
        fields = {k: v for k, v in kwargs.items() if k in allowed}
        # Handle image update
        if "image_path" in kwargs:
            img_bytes = self.read_image_file(kwargs["image_path"])
            if img_bytes:
                img_bytes = self.make_thumbnail(img_bytes)
                fields["image_data"] = img_bytes
        if "image_data" in kwargs:
            fields["image_data"] = kwargs["image_data"]
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
        # Don't load image_data in list queries for performance
        cur = self.conn.execute(
            """SELECT id, name, release_date, appearance_condition,
                      working_condition, remarks, image_path,
                      avg_price, rarity_score,
                      CASE WHEN image_data IS NOT NULL THEN 1 ELSE 0 END as has_image
               FROM phones ORDER BY name, id"""
        )
        return [dict(r) for r in cur.fetchall()]

    def get_phone_image(self, phone_id):
        """Get image BLOB for a specific phone."""
        cur = self.conn.execute(
            "SELECT image_data FROM phones WHERE id = ?", (phone_id,)
        )
        row = cur.fetchone()
        if row and row[0]:
            return bytes(row[0])
        return None

    def search_phones(self, query):
        q = f"%{query}%"
        cur = self.conn.execute(
            """SELECT id, name, release_date, appearance_condition,
                      working_condition, remarks, image_path,
                      avg_price, rarity_score,
                      CASE WHEN image_data IS NOT NULL THEN 1 ELSE 0 END as has_image
               FROM phones
               WHERE name LIKE ? OR id LIKE ? OR release_date LIKE ?
               ORDER BY name, id""",
            (q, q, q)
        )
        return [dict(r) for r in cur.fetchall()]

    # ── Spare Parts CRUD ────────────────────────────────────────

    def add_spare_part(self, name, phone_id="", image_path="", description="",
                       image_bytes=None):
        if not image_bytes and image_path:
            image_bytes = self.read_image_file(image_path)
            if image_bytes:
                image_bytes = self.make_thumbnail(image_bytes)
        self.conn.execute(
            """INSERT INTO spare_parts
               (name, phone_id, image_path, image_data, description, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (name, phone_id, image_path or "", image_bytes,
             description, datetime.now().isoformat())
        )
        self.conn.commit()

    def update_spare_part(self, spare_id, **kwargs):
        allowed = {"name", "phone_id", "image_path", "description"}
        fields = {k: v for k, v in kwargs.items() if k in allowed}
        if "image_path" in kwargs:
            img_bytes = self.read_image_file(kwargs["image_path"])
            if img_bytes:
                img_bytes = self.make_thumbnail(img_bytes)
                fields["image_data"] = img_bytes
        if "image_data" in kwargs:
            fields["image_data"] = kwargs["image_data"]
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

    def get_spare_image(self, spare_id):
        cur = self.conn.execute(
            "SELECT image_data FROM spare_parts WHERE id = ?", (spare_id,)
        )
        row = cur.fetchone()
        if row and row[0]:
            return bytes(row[0])
        return None

    def get_all_spare_parts(self):
        cur = self.conn.execute(
            """SELECT id, name, phone_id, image_path, description,
                      CASE WHEN image_data IS NOT NULL THEN 1 ELSE 0 END as has_image
               FROM spare_parts ORDER BY name"""
        )
        return [dict(r) for r in cur.fetchall()]

    def get_spare_parts_for_phone(self, phone_name):
        cur = self.conn.execute(
            """SELECT id, name, phone_id, image_path, description,
                      CASE WHEN image_data IS NOT NULL THEN 1 ELSE 0 END as has_image
               FROM spare_parts WHERE name LIKE ? ORDER BY created_at""",
            (f"%{phone_name}%",)
        )
        return [dict(r) for r in cur.fetchall()]

    def search_spare_parts(self, query):
        q = f"%{query}%"
        cur = self.conn.execute(
            """SELECT id, name, phone_id, image_path, description,
                      CASE WHEN image_data IS NOT NULL THEN 1 ELSE 0 END as has_image
               FROM spare_parts
               WHERE name LIKE ? OR description LIKE ?
               ORDER BY name""",
            (q, q)
        )
        return [dict(r) for r in cur.fetchall()]

    # ── Wall Items CRUD ──────────────────────────────────────────

    def add_wall_item(self, item_id, name, release_date="", appearance="",
                      working="", remarks="", image_path="", image_bytes=None):
        if not image_bytes and image_path:
            image_bytes = self.read_image_file(image_path)
            if image_bytes:
                image_bytes = self.make_thumbnail(image_bytes)
        self.conn.execute(
            """INSERT OR REPLACE INTO wall_items
               (id, name, release_date, appearance_condition,
                working_condition, remarks, image_path, image_data, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (item_id, name, release_date, appearance, working,
             remarks, image_path or "", image_bytes,
             datetime.now().isoformat())
        )
        self.conn.commit()

    def update_wall_item(self, item_id, **kwargs):
        allowed = {"name", "release_date", "appearance_condition",
                    "working_condition", "remarks", "image_path"}
        fields = {k: v for k, v in kwargs.items() if k in allowed}
        if "image_path" in kwargs:
            img_bytes = self.read_image_file(kwargs["image_path"])
            if img_bytes:
                img_bytes = self.make_thumbnail(img_bytes)
                fields["image_data"] = img_bytes
        if "image_data" in kwargs:
            fields["image_data"] = kwargs["image_data"]
        if not fields:
            return
        set_clause = ", ".join(f"{k} = ?" for k in fields)
        values = list(fields.values()) + [item_id]
        self.conn.execute(
            f"UPDATE wall_items SET {set_clause} WHERE id = ?", values
        )
        self.conn.commit()

    def delete_wall_item(self, item_id):
        self.conn.execute("DELETE FROM wall_items WHERE id = ?", (item_id,))
        self.conn.commit()

    def get_wall_item(self, item_id):
        cur = self.conn.execute("SELECT * FROM wall_items WHERE id = ?", (item_id,))
        row = cur.fetchone()
        return dict(row) if row else None

    def get_all_wall_items(self):
        cur = self.conn.execute(
            """SELECT id, name, release_date, appearance_condition,
                      working_condition, remarks, image_path,
                      CASE WHEN image_data IS NOT NULL THEN 1 ELSE 0 END as has_image
               FROM wall_items ORDER BY name, id"""
        )
        return [dict(r) for r in cur.fetchall()]

    def get_wall_image(self, item_id):
        cur = self.conn.execute(
            "SELECT image_data FROM wall_items WHERE id = ?", (item_id,)
        )
        row = cur.fetchone()
        if row and row[0]:
            return bytes(row[0])
        return None

    def search_wall_items(self, query):
        q = f"%{query}%"
        cur = self.conn.execute(
            """SELECT id, name, release_date, appearance_condition,
                      working_condition, remarks, image_path,
                      CASE WHEN image_data IS NOT NULL THEN 1 ELSE 0 END as has_image
               FROM wall_items
               WHERE name LIKE ? OR id LIKE ? OR release_date LIKE ?
               ORDER BY name, id""",
            (q, q, q)
        )
        return [dict(r) for r in cur.fetchall()]

    def get_wall_count(self):
        cur = self.conn.execute("SELECT COUNT(*) FROM wall_items")
        return cur.fetchone()[0]

    def import_wall_from_rows(self, rows):
        count = 0
        for row in rows:
            try:
                self.conn.execute(
                    """INSERT OR IGNORE INTO wall_items
                       (id, name, release_date, appearance_condition,
                        working_condition, remarks, image_path, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, '', ?)""",
                    (str(row.get("id", "")), str(row.get("name", "")),
                     str(row.get("release_date", "")),
                     str(row.get("appearance_condition", "")),
                     str(row.get("working_condition", "")),
                     str(row.get("remarks", "")),
                     datetime.now().isoformat())
                )
                count += 1
            except Exception:
                continue
        self.conn.commit()
        return count

    # ── Phone Gallery ────────────────────────────────────────────

    def add_gallery_image(self, phone_id, image_data):
        """Add an additional image to a phone's gallery."""
        self.conn.execute(
            "INSERT INTO phone_gallery (phone_id, image_data, created_at) VALUES (?, ?, ?)",
            (phone_id, image_data, datetime.now().isoformat())
        )
        self.conn.commit()

    def get_gallery_images(self, phone_id):
        """Get all gallery image BLOBs for a phone. Returns list of (id, image_data)."""
        cur = self.conn.execute(
            "SELECT id, image_data FROM phone_gallery WHERE phone_id = ? ORDER BY created_at",
            (phone_id,)
        )
        return [(r[0], bytes(r[1])) for r in cur.fetchall() if r[1]]

    def delete_gallery_image(self, gallery_id):
        self.conn.execute("DELETE FROM phone_gallery WHERE id = ?", (gallery_id,))
        self.conn.commit()

    def get_gallery_count(self, phone_id):
        cur = self.conn.execute(
            "SELECT COUNT(*) FROM phone_gallery WHERE phone_id = ?", (phone_id,)
        )
        return cur.fetchone()[0]

    # ── Spare Gallery ──────────────────────────────────────────

    def add_spare_gallery_image(self, spare_id, image_data):
        self.conn.execute(
            "INSERT INTO spare_gallery (spare_id, image_data, created_at) VALUES (?, ?, ?)",
            (spare_id, image_data, datetime.now().isoformat()))
        self.conn.commit()

    def get_spare_gallery_images(self, spare_id):
        cur = self.conn.execute(
            "SELECT id, image_data FROM spare_gallery WHERE spare_id = ? ORDER BY created_at",
            (spare_id,))
        return [(r[0], bytes(r[1])) for r in cur.fetchall() if r[1]]

    def delete_spare_gallery_image(self, gal_id):
        self.conn.execute("DELETE FROM spare_gallery WHERE id = ?", (gal_id,))
        self.conn.commit()

    # ── Wall Gallery ──────────────────────────────────────────

    def add_wall_gallery_image(self, wall_id, image_data):
        self.conn.execute(
            "INSERT INTO wall_gallery (wall_id, image_data, created_at) VALUES (?, ?, ?)",
            (wall_id, image_data, datetime.now().isoformat()))
        self.conn.commit()

    def get_wall_gallery_images(self, wall_id):
        cur = self.conn.execute(
            "SELECT id, image_data FROM wall_gallery WHERE wall_id = ? ORDER BY created_at",
            (wall_id,))
        return [(r[0], bytes(r[1])) for r in cur.fetchall() if r[1]]

    def delete_wall_gallery_image(self, gal_id):
        self.conn.execute("DELETE FROM wall_gallery WHERE id = ?", (gal_id,))
        self.conn.commit()

    # ── Combined Search ─────────────────────────────────────────

    # ── General Gallery ────────────────────────────────────────

    def add_general_gallery(self, image_data, caption=""):
        self.conn.execute(
            "INSERT INTO general_gallery (image_data, caption, created_at) VALUES (?, ?, ?)",
            (image_data, caption, datetime.now().isoformat()))
        self.conn.commit()

    def get_general_gallery(self):
        cur = self.conn.execute(
            "SELECT id, image_data, caption FROM general_gallery ORDER BY created_at DESC")
        return [(r[0], bytes(r[1]), r[2] or "") for r in cur.fetchall() if r[1]]

    def delete_general_gallery(self, gal_id):
        self.conn.execute("DELETE FROM general_gallery WHERE id = ?", (gal_id,))
        self.conn.commit()

    # ── Combined Search ─────────────────────────────────────────

    def search_all(self, query):
        return self.search_phones(query), self.search_spare_parts(query), self.search_wall_items(query)

    # ── Import / Export ─────────────────────────────────────────

    def import_phones_from_rows(self, rows):
        count = 0
        for row in rows:
            try:
                self.conn.execute(
                    """INSERT OR IGNORE INTO phones
                       (id, name, release_date, appearance_condition,
                        working_condition, remarks, description, image_path,
                        avg_price, rarity_score, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, '', ?, ?, ?)""",
                    (str(row.get("id", "")), str(row.get("name", "")),
                     str(row.get("release_date", "")),
                     str(row.get("appearance_condition", "")),
                     str(row.get("working_condition", "")),
                     str(row.get("remarks", "")),
                     str(row.get("description", "") or ""),
                     float(row.get("avg_price", 0) or 0),
                     float(row.get("rarity_score", 0) or 0),
                     datetime.now().isoformat())
                )
                count += 1
            except Exception:
                continue
        self.conn.commit()
        return count

    def export_phones(self):
        cur = self.conn.execute(
            """SELECT id, name, release_date, appearance_condition,
                      working_condition, remarks, description, image_path,
                      avg_price, rarity_score
               FROM phones ORDER BY name, id"""
        )
        return [dict(r) for r in cur.fetchall()]

    def export_spare_parts(self):
        cur = self.conn.execute(
            """SELECT id, name, phone_id, image_path, description
               FROM spare_parts ORDER BY name"""
        )
        return [dict(r) for r in cur.fetchall()]

    def get_phone_count(self):
        cur = self.conn.execute("SELECT COUNT(*) FROM phones")
        return cur.fetchone()[0]

    def get_spare_count(self):
        cur = self.conn.execute("SELECT COUNT(*) FROM spare_parts")
        return cur.fetchone()[0]

    # ── Report / Statistics ─────────────────────────────────────

    def get_report(self):
        report = {}
        report["total_phones"] = self.get_phone_count()
        report["total_spares"] = self.get_spare_count()
        cur = self.conn.execute(
            "SELECT working_condition, COUNT(*) as cnt FROM phones GROUP BY working_condition ORDER BY cnt DESC")
        report["by_working"] = [(r[0] or "Unknown", r[1]) for r in cur.fetchall()]
        cur = self.conn.execute(
            "SELECT appearance_condition, COUNT(*) as cnt FROM phones GROUP BY appearance_condition ORDER BY cnt DESC")
        report["by_appearance"] = [(r[0] or "Unknown", r[1]) for r in cur.fetchall()]
        cur = self.conn.execute(
            "SELECT name, COUNT(*) as cnt FROM phones GROUP BY name ORDER BY cnt DESC LIMIT 20")
        report["by_model"] = [(r[0], r[1]) for r in cur.fetchall()]
        cur = self.conn.execute("SELECT COUNT(DISTINCT name) FROM phones")
        report["unique_models"] = cur.fetchone()[0]
        cur = self.conn.execute(
            "SELECT release_date, COUNT(*) as cnt FROM phones GROUP BY release_date ORDER BY release_date")
        report["by_year"] = [(r[0] or "Unknown", r[1]) for r in cur.fetchall()]
        cur = self.conn.execute(
            "SELECT COUNT(*) FROM phones WHERE image_data IS NOT NULL")
        report["phones_with_images"] = cur.fetchone()[0]
        return report

    def close(self):
        if self.conn:
            self.conn.close()
