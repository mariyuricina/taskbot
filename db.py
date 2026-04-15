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

        CREATE TABLE IF NOT EXISTS fridge (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_group_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            quantity REAL NOT NULL DEFAULT 1,
            unit TEXT NOT NULL DEFAULT 'шт',
            expires_at TEXT,
            added_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS recipes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_group_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            description TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS recipe_ingredients (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            recipe_id INTEGER NOT NULL REFERENCES recipes(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            quantity REAL,
            unit TEXT
        );
        """)

# ── Users ────────────────────────────────────────────────────────────────────

def upsert_user(user_id: int, name: str, username: str | None):
    with get_conn() as conn:
        existing = conn.execute("SELECT id FROM users WHERE id=?", (user_id,)).fetchone()
        if existing:
            conn.execute("UPDATE users SET name=?, username=? WHERE id=?", (name, username, user_id))
        else:
            conn.execute("INSERT INTO users (id, name, username) VALUES (?,?,?)", (user_id, name, username))

def get_user(user_id: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        return dict(row) if row else None

def find_user_by_username(username: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM users WHERE LOWER(username)=LOWER(?)", (username,)).fetchone()
        return dict(row) if row else None

def set_pair(user_id: int, partner_id: int):
    with get_conn() as conn:
        conn.execute("UPDATE users SET partner_id=? WHERE id=?", (partner_id, user_id))
        conn.execute("UPDATE users SET partner_id=? WHERE id=?", (user_id, partner_id))

def get_partner(user_id: int) -> tuple[int | None, str | None]:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT u2.id, u2.name FROM users u1 JOIN users u2 ON u1.partner_id=u2.id WHERE u1.id=?",
            (user_id,)
        ).fetchone()
        return (row[0], row[1]) if row else (None, None)

def get_group_id(user_id: int) -> int:
    """Returns the canonical group id (min of user_id and partner_id)."""
    partner_id, _ = get_partner(user_id)
    if partner_id:
        return min(user_id, partner_id)
    return user_id

# ── Tasks ────────────────────────────────────────────────────────────────────

def add_task(creator_id, assignee_id, assignee_name, title, category, priority, due_date):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO tasks (creator_id,assignee_id,assignee_name,title,category,priority,due_date) VALUES (?,?,?,?,?,?,?)",
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
        rows = conn.execute("SELECT * FROM tasks WHERE due_date=? AND done=0", (due_date,)).fetchall()
        return [dict(r) for r in rows]

def get_tasks_due_range(user_ids: list[int], date_from: str, date_to: str) -> list[dict]:
    placeholders = ",".join("?" * len(user_ids))
    with get_conn() as conn:
        rows = conn.execute(
            f"""SELECT * FROM tasks WHERE assignee_id IN ({placeholders})
               AND due_date IS NOT NULL AND due_date>=? AND due_date<=? AND done=0
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
        open_count = conn.execute("SELECT COUNT(*) FROM tasks WHERE assignee_id=? AND done=0", (user_id,)).fetchone()[0]
        done_count = conn.execute("SELECT COUNT(*) FROM tasks WHERE assignee_id=? AND done=1", (user_id,)).fetchone()[0]
        return {"open": open_count, "done": done_count}

# ── Fridge ───────────────────────────────────────────────────────────────────

def add_fridge_item(user_id: int, name: str, quantity: float, unit: str, expires_at: str | None):
    gid = get_group_id(user_id)
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO fridge (user_group_id,name,quantity,unit,expires_at) VALUES (?,?,?,?,?)",
            (gid, name.strip().lower(), quantity, unit, expires_at)
        )

def get_fridge_items(user_id: int) -> list[dict]:
    gid = get_group_id(user_id)
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM fridge WHERE user_group_id=? ORDER BY expires_at ASC NULLS LAST, name ASC",
            (gid,)
        ).fetchall()
        return [dict(r) for r in rows]

def delete_fridge_item(item_id: int):
    with get_conn() as conn:
        conn.execute("DELETE FROM fridge WHERE id=?", (item_id,))

def update_fridge_quantity(item_id: int, quantity: float):
    with get_conn() as conn:
        conn.execute("UPDATE fridge SET quantity=? WHERE id=?", (quantity, item_id))

def get_expiring_soon(user_id: int, days: int = 2) -> list[dict]:
    gid = get_group_id(user_id)
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT * FROM fridge WHERE user_group_id=?
               AND expires_at IS NOT NULL
               AND expires_at <= date('now', ?||' days')
               ORDER BY expires_at ASC""",
            (gid, str(days))
        ).fetchall()
        return [dict(r) for r in rows]

def get_all_fridge_names(user_id: int) -> list[str]:
    gid = get_group_id(user_id)
    with get_conn() as conn:
        rows = conn.execute("SELECT name FROM fridge WHERE user_group_id=?", (gid,)).fetchall()
        return [r[0] for r in rows]

# ── Recipes ──────────────────────────────────────────────────────────────────

def add_recipe(user_id: int, name: str, description: str | None, ingredients: list[dict]) -> int:
    """ingredients: [{'name': str, 'quantity': float|None, 'unit': str|None}]"""
    gid = get_group_id(user_id)
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO recipes (user_group_id,name,description) VALUES (?,?,?)",
            (gid, name.strip(), description)
        )
        recipe_id = cur.lastrowid
        for ing in ingredients:
            conn.execute(
                "INSERT INTO recipe_ingredients (recipe_id,name,quantity,unit) VALUES (?,?,?,?)",
                (recipe_id, ing["name"].strip().lower(), ing.get("quantity"), ing.get("unit"))
            )
        return recipe_id

def get_recipes(user_id: int) -> list[dict]:
    gid = get_group_id(user_id)
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM recipes WHERE user_group_id=? ORDER BY name ASC", (gid,)
        ).fetchall()
        result = []
        for r in rows:
            recipe = dict(r)
            recipe["ingredients"] = get_recipe_ingredients(recipe["id"])
            result.append(recipe)
        return result

def get_recipe_by_id(recipe_id: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM recipes WHERE id=?", (recipe_id,)).fetchone()
        if not row:
            return None
        recipe = dict(row)
        recipe["ingredients"] = get_recipe_ingredients(recipe_id)
        return recipe

def get_recipe_ingredients(recipe_id: int) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM recipe_ingredients WHERE recipe_id=?", (recipe_id,)
        ).fetchall()
        return [dict(r) for r in rows]

def delete_recipe(recipe_id: int):
    with get_conn() as conn:
        conn.execute("DELETE FROM recipes WHERE id=?", (recipe_id,))

def get_cookable_recipes(user_id: int) -> list[dict]:
    """Returns recipes where ALL ingredients are present in fridge."""
    fridge_names = set(get_all_fridge_names(user_id))
    recipes = get_recipes(user_id)
    cookable = []
    for recipe in recipes:
        needed = {i["name"] for i in recipe["ingredients"]}
        if needed and needed.issubset(fridge_names):
            cookable.append(recipe)
    return cookable
