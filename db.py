import sqlite3
import os

DB_PATH = os.environ.get("DB_PATH", "tasks.db")

def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_conn() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            username TEXT,
            partner_id INTEGER
        );

        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            creator_id INTEGER NOT NULL,
            assignee_id INTEGER NOT NULL,
            assignee_name TEXT NOT NULL,
            title TEXT NOT NULL,
            category TEXT NOT NULL,
            priority TEXT NOT NULL DEFAULT 'medium',
            due_date TEXT,
            done INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        """)

def upsert_user(user_id: int, name: str, username: str | None):
    with get_conn() as conn:
        existing = conn.execute("SELECT id FROM users WHERE id=?", (user_id,)).fetchone()
        if existing:
            conn.execute(
                "UPDATE users SET name=?, username=? WHERE id=?",
                (name, username, user_id)
            )
        else:
            conn.execute(
                "INSERT INTO users (id, name, username) VALUES (?,?,?)",
                (user_id, name, username)
            )

def get_user(user_id: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        return dict(row) if row else None

def find_user_by_username(username: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE LOWER(username)=LOWER(?)", (username,)
        ).fetchone()
        return dict(row) if row else None

def set_pair(user_id: int, partner_id: int):
    with get_conn() as conn:
        conn.execute("UPDATE users SET partner_id=? WHERE id=?", (partner_id, user_id))
        conn.execute("UPDATE users SET partner_id=? WHERE id=?", (user_id, partner_id))

def get_partner(user_id: int) -> tuple[int | None, str | None]:
    with get_conn() as conn:
        row = conn.execute(
            """SELECT u2.id, u2.name
               FROM users u1 JOIN users u2 ON u1.partner_id = u2.id
               WHERE u1.id=?""",
            (user_id,)
        ).fetchone()
        if row:
            return row[0], row[1]
        return None, None

def add_task(creator_id, assignee_id, assignee_name, title, category, priority, due_date):
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO tasks (creator_id, assignee_id, assignee_name, title, category, priority, due_date)
               VALUES (?,?,?,?,?,?,?)""",
            (creator_id, assignee_id, assignee_name, title, category, priority, due_date)
        )

def get_tasks(assignee_id: int, done: bool) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT * FROM tasks WHERE assignee_id=? AND done=?
               ORDER BY CASE priority WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END,
               due_date ASC NULLS LAST""",
            (assignee_id, int(done))
        ).fetchall()
        return [dict(r) for r in rows]

def get_tasks_for_users(user_ids: list[int], done: bool) -> list[dict]:
    placeholders = ",".join("?" * len(user_ids))
    with get_conn() as conn:
        rows = conn.execute(
            f"""SELECT * FROM tasks WHERE assignee_id IN ({placeholders}) AND done=?
               ORDER BY CASE priority WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END,
               due_date ASC NULLS LAST""",
            (*user_ids, int(done))
        ).fetchall()
        return [dict(r) for r in rows]

def get_tasks_due(due_date: str) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM tasks WHERE due_date=? AND done=0",
            (due_date,)
        ).fetchall()
        return [dict(r) for r in rows]

def get_tasks_due_range(user_ids: list[int], date_from: str, date_to: str) -> list[dict]:
    placeholders = ",".join("?" * len(user_ids))
    with get_conn() as conn:
        rows = conn.execute(
            f"""SELECT * FROM tasks
               WHERE assignee_id IN ({placeholders})
               AND due_date IS NOT NULL
               AND due_date >= ? AND due_date <= ?
               AND done=0
               ORDER BY due_date ASC""",
            (*user_ids, date_from, date_to)
        ).fetchall()
        return [dict(r) for r in rows]

def set_task_done(task_id: int):
    with get_conn() as conn:
        conn.execute("UPDATE tasks SET done=1 WHERE id=?", (task_id,))

def delete_task(task_id: int):
    with get_conn() as conn:
        conn.execute("DELETE FROM tasks WHERE id=?", (task_id,))

def update_task_field(task_id: int, field: str, value):
    allowed = {"title", "category", "priority", "due_date"}
    if field not in allowed:
        raise ValueError(f"Field {field} not allowed")
    with get_conn() as conn:
        conn.execute(f"UPDATE tasks SET {field}=? WHERE id=?", (value, task_id))

def get_stats(user_id: int) -> dict:
    with get_conn() as conn:
        open_count = conn.execute(
            "SELECT COUNT(*) FROM tasks WHERE assignee_id=? AND done=0", (user_id,)
        ).fetchone()[0]
        done_count = conn.execute(
            "SELECT COUNT(*) FROM tasks WHERE assignee_id=? AND done=1", (user_id,)
        ).fetchone()[0]
        return {"open": open_count, "done": done_count}
