import asyncio
import logging
import os
from datetime import datetime, date, timedelta
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import db
import food as food_module

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")

CATEGORIES = {
    "🏠": "Быт и дом",
    "💰": "Финансы",
    "❤️": "Здоровье",
    "💼": "Работа",
    "🐾": "Животные",
    "🍽️": "Еда",
    "📌": "Другое",
}

PRIORITY_LABELS = {"low": "🟢 Низкий", "medium": "🟡 Средний", "high": "🔴 Высокий"}

def main_menu():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="➕ Новая задача"), KeyboardButton(text="📋 Мои задачи")],
        [KeyboardButton(text="👥 Все задачи"), KeyboardButton(text="✅ Выполненные")],
        [KeyboardButton(text="⏰ Горящие"), KeyboardButton(text="📊 Статистика")],
        [KeyboardButton(text="🍽️ Еда и холодильник")],
    ], resize_keyboard=True)

def category_keyboard():
    buttons = []
    row = []
    for emoji, name in CATEGORIES.items():
        row.append(InlineKeyboardButton(text=f"{emoji} {name}", callback_data=f"cat:{name}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def priority_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🟢 Низкий", callback_data="pri:low"),
            InlineKeyboardButton(text="🟡 Средний", callback_data="pri:medium"),
            InlineKeyboardButton(text="🔴 Высокий", callback_data="pri:high"),
        ],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")],
    ])

def assignee_keyboard(user_id: int):
    partner_id, partner_name = db.get_partner(user_id)
    buttons = [[InlineKeyboardButton(text="👤 Себе", callback_data="assign:me")]]
    if partner_id:
        buttons.append([InlineKeyboardButton(text=f"👤 {partner_name}", callback_data="assign:partner")])
    buttons.append([InlineKeyboardButton(text="👥 Обоим", callback_data="assign:both")])
    buttons.append([InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def task_actions_keyboard(task_id: int, done: bool = False):
    buttons = []
    if not done:
        buttons.append([InlineKeyboardButton(text="✅ Выполнено", callback_data=f"done:{task_id}")])
    buttons.append([
        InlineKeyboardButton(text="✏️ Изменить", callback_data=f"edit:{task_id}"),
        InlineKeyboardButton(text="🗑 Удалить", callback_data=f"del:{task_id}"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def format_task(task: dict, show_assignee: bool = True) -> str:
    emoji = next((e for e, n in CATEGORIES.items() if n == task["category"]), "📌")
    pri = PRIORITY_LABELS.get(task["priority"], "🟡 Средний")
    due = f"\n📅 До: {task['due_date']}" if task.get("due_date") else ""
    assignee = f"\n👤 {task['assignee_name']}" if show_assignee and task.get("assignee_name") else ""
    return f"*{task['title']}*\n{emoji} {task['category']} · {pri}{due}{assignee}"

async def send_task_list(message: Message, tasks: list, title: str, show_assignee: bool = True):
    if not tasks:
        await message.answer(f"_{title}_\n\nПока пусто 🙂", parse_mode="Markdown")
        return
    for task in tasks:
        text = format_task(task, show_assignee)
        await message.answer(
            text, parse_mode="Markdown",
            reply_markup=task_actions_keyboard(task["id"], task.get("done", False))
        )

class AddTask(StatesGroup):
    title = State()
    category = State()
    priority = State()
    assignee = State()
    due_date = State()

class EditTask(StatesGroup):
    choose_field = State()
    new_value = State()

async def check_reminders(bot: Bot):
    today = date.today().isoformat()
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    tasks_today = db.get_tasks_due(today)
    tasks_tomorrow = db.get_tasks_due(tomorrow)

    notified = {}
    for task in tasks_today + tasks_tomorrow:
        uid = task["assignee_id"]
        if uid not in notified:
            notified[uid] = []
        notified[uid].append(task)

    for uid, tasks in notified.items():
        lines = []
        for t in tasks:
            label = "сегодня" if t["due_date"] == today else "завтра"
            lines.append(f"• *{t['title']}* — {label}")
        text = "⏰ *Напоминание о задачах:*\n\n" + "\n".join(lines)
        try:
            await bot.send_message(uid, text, parse_mode="Markdown")
        except Exception as e:
            logger.warning(f"Reminder error for {uid}: {e}")

    await food_module.check_expiry(bot)

async def main():
    if not BOT_TOKEN:
        raise ValueError("BOT_TOKEN не задан! Добавь его в переменные окружения.")

    db.init_db()
    bot = Bot(token=BOT_TOKEN)
    storage = MemoryStorage()
    dp = Dispatcher(storage=storage)

    dp.include_router(food_module.router)

    scheduler = AsyncIOScheduler(timezone="Europe/Moscow")
    scheduler.add_job(check_reminders, "cron", hour=9, minute=0, args=[bot])
    scheduler.start()

    @dp.message(CommandStart())
    async def cmd_start(message: Message):
        user = message.from_user
        db.upsert_user(user.id, user.full_name, user.username)
        await message.answer(
            f"Привет, {user.first_name}! 👋\n\n"
            "Я помогу держать дела и холодильник под контролем 🙂\n\n"
            "Чтобы связать аккаунт с партнёром:\n`/pair @username`",
            parse_mode="Markdown",
            reply_markup=main_menu()
        )

    @dp.message(Command("pair"))
    async def cmd_pair(message: Message):
        args = message.text.split(maxsplit=1)
        if len(args) < 2:
            await message.answer("Использование: `/pair @username`", parse_mode="Markdown")
            return
        username = args[1].lstrip("@")
        partner = db.find_user_by_username(username)
        if not partner:
            await message.answer(
                f"Пользователь @{username} не найден.\n"
                "Попроси партнёра сначала написать /start, а потом повтори."
            )
            return
        if partner["id"] == message.from_user.id:
            await message.answer("Нельзя связаться с самим собой 😅")
            return
        db.set_pair(message.from_user.id, partner["id"])
        await message.answer(
            f"✅ Теперь ты связан с *{partner['name']}*!",
            parse_mode="Markdown"
        )
        try:
            await bot.send_message(
                partner["id"],
                f"✅ *{message.from_user.full_name}* связал(а) с тобой аккаунт!",
                parse_mode="Markdown"
            )
        except Exception:
            pass

    @dp.message(F.text == "➕ Новая задача")
    async def new_task_start(message: Message, state: FSMContext):
        await state.set_state(AddTask.title)
        await message.answer("📝 Введи название задачи:", reply_markup=ReplyKeyboardRemove())

    @dp.message(AddTask.title)
    async def new_task_title(message: Message, state: FSMContext):
        await state.update_data(title=message.text.strip())
        await state.set_state(AddTask.category)
        await message.answer("Выбери категорию:", reply_markup=category_keyboard())

    @dp.callback_query(F.data.startswith("cat:"), AddTask.category)
    async def new_task_category(callback: CallbackQuery, state: FSMContext):
        await state.update_data(category=callback.data[4:])
        await state.set_state(AddTask.priority)
        await callback.message.edit_text("Выбери приоритет:", reply_markup=priority_keyboard())

    @dp.callback_query(F.data.startswith("pri:"), AddTask.priority)
    async def new_task_priority(callback: CallbackQuery, state: FSMContext):
        await state.update_data(priority=callback.data[4:])
        await state.set_state(AddTask.assignee)
        await callback.message.edit_text(
            "Кому назначить?",
            reply_markup=assignee_keyboard(callback.from_user.id)
        )

    @dp.callback_query(F.data.startswith("assign:"), AddTask.assignee)
    async def new_task_assignee(callback: CallbackQuery, state: FSMContext):
        choice = callback.data[7:]
        uid = callback.from_user.id
        partner_id, partner_name = db.get_partner(uid)
        user = db.get_user(uid)
        if choice == "me":
            assignees = [(uid, user["name"])]
        elif choice == "partner" and partner_id:
            assignees = [(partner_id, partner_name)]
        else:
            assignees = [(uid, user["name"])]
            if partner_id:
                assignees.append((partner_id, partner_name))
        await state.update_data(assignees=assignees)
        await state.set_state(AddTask.due_date)
        await callback.message.edit_text(
            "📅 Дедлайн (ДД.ММ.ГГГГ) или *нет*:",
            parse_mode="Markdown"
        )

    @dp.message(AddTask.due_date)
    async def new_task_due(message: Message, state: FSMContext):
        text = message.text.strip().lower()
        due_date = None
        if text != "нет":
            try:
                due_date = datetime.strptime(text, "%d.%m.%Y").date().isoformat()
            except ValueError:
                await message.answer("Неверный формат. Введи дату как ДД.ММ.ГГГГ или напиши *нет*:", parse_mode="Markdown")
                return
        data = await state.get_data()
        await state.clear()
        for assignee_id, assignee_name in data["assignees"]:
            db.add_task(
                creator_id=message.from_user.id,
                assignee_id=assignee_id,
                assignee_name=assignee_name,
                title=data["title"],
                category=data["category"],
                priority=data["priority"],
                due_date=due_date,
            )
        names = ", ".join(n for _, n in data["assignees"])
        await message.answer(
            f"✅ *{data['title']}* добавлена! Назначено: {names}",
            parse_mode="Markdown",
            reply_markup=main_menu()
        )

    @dp.callback_query(F.data == "cancel")
    async def cancel_action(callback: CallbackQuery, state: FSMContext):
        await state.clear()
        await callback.message.delete()
        await callback.message.answer("Отменено.", reply_markup=main_menu())

    @dp.message(F.text == "📋 Мои задачи")
    async def my_tasks(message: Message):
        tasks = db.get_tasks(assignee_id=message.from_user.id, done=False)
        await send_task_list(message, tasks, "Мои задачи", show_assignee=False)

    @dp.message(F.text == "👥 Все задачи")
    async def all_tasks(message: Message):
        uid = message.from_user.id
        partner_id, _ = db.get_partner(uid)
        ids = [uid] + ([partner_id] if partner_id else [])
        tasks = db.get_tasks_for_users(ids, done=False)
        await send_task_list(message, tasks, "Все задачи")

    @dp.message(F.text == "✅ Выполненные")
    async def done_tasks(message: Message):
        uid = message.from_user.id
        partner_id, _ = db.get_partner(uid)
        ids = [uid] + ([partner_id] if partner_id else [])
        tasks = db.get_tasks_for_users(ids, done=True)
        await send_task_list(message, tasks, "Выполненные")

    @dp.message(F.text == "⏰ Горящие")
    async def urgent_tasks(message: Message):
        uid = message.from_user.id
        partner_id, _ = db.get_partner(uid)
        ids = [uid] + ([partner_id] if partner_id else [])
        today = date.today().isoformat()
        soon = (date.today() + timedelta(days=3)).isoformat()
        tasks = db.get_tasks_due_range(ids, today, soon)
        await send_task_list(message, tasks, "⏰ Горящие (дедлайн ≤ 3 дня)")

    @dp.message(F.text == "📊 Статистика")
    async def stats(message: Message):
        uid = message.from_user.id
        partner_id, partner_name = db.get_partner(uid)
        user = db.get_user(uid)
        my = db.get_stats(uid)
        text = f"📊 *Статистика*\n\n👤 *{user['name']}*\nОткрытых: {my['open']} · Выполнено: {my['done']}\n"
        if partner_id:
            p = db.get_stats(partner_id)
            text += f"\n👤 *{partner_name}*\nОткрытых: {p['open']} · Выполнено: {p['done']}\n"
        await message.answer(text, parse_mode="Markdown")

    @dp.callback_query(F.data.startswith("done:"))
    async def mark_done(callback: CallbackQuery):
        task_id = int(callback.data[5:])
        db.set_task_done(task_id)
        await callback.answer("✅ Выполнено!")
        await callback.message.edit_reply_markup(reply_markup=task_actions_keyboard(task_id, done=True))

    @dp.callback_query(F.data.startswith("del:"))
    async def delete_task(callback: CallbackQuery):
        task_id = int(callback.data[4:])
        db.delete_task(task_id)
        await callback.answer("Удалено.")
        await callback.message.delete()

    @dp.callback_query(F.data.startswith("edit:"))
    async def edit_task_start(callback: CallbackQuery, state: FSMContext):
        task_id = int(callback.data[5:])
        await state.set_state(EditTask.choose_field)
        await state.update_data(task_id=task_id)
        await callback.message.answer(
            "Что изменить?",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="📝 Название", callback_data="ef:title")],
                [InlineKeyboardButton(text="📅 Дедлайн", callback_data="ef:due_date")],
                [InlineKeyboardButton(text="🔴 Приоритет", callback_data="ef:priority")],
                [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")],
            ])
        )

    @dp.callback_query(F.data.startswith("ef:"), EditTask.choose_field)
    async def edit_task_field(callback: CallbackQuery, state: FSMContext):
        field = callback.data[3:]
        await state.update_data(field=field)
        await state.set_state(EditTask.new_value)
        if field == "priority":
            await callback.message.edit_text("Выбери новый приоритет:", reply_markup=priority_keyboard())
        elif field == "due_date":
            await callback.message.edit_text("Введи новую дату (ДД.ММ.ГГГГ) или *нет*:", parse_mode="Markdown")
        else:
            await callback.message.edit_text("Введи новое название:")

    @dp.callback_query(F.data.startswith("pri:"), EditTask.new_value)
    async def edit_task_priority_done(callback: CallbackQuery, state: FSMContext):
        data = await state.get_data()
        db.update_task_field(data["task_id"], "priority", callback.data[4:])
        await state.clear()
        await callback.message.edit_text("✅ Приоритет обновлён!")

    @dp.message(EditTask.new_value)
    async def edit_task_value(message: Message, state: FSMContext):
        data = await state.get_data()
        field = data["field"]
        value = message.text.strip()
        if field == "due_date":
            if value.lower() == "нет":
                value = None
            else:
                try:
                    value = datetime.strptime(value, "%d.%m.%Y").date().isoformat()
                except ValueError:
                    await message.answer("Неверный формат. Введи дату как ДД.ММ.ГГГГ или напиши *нет*:", parse_mode="Markdown")
                    return
        db.update_task_field(data["task_id"], field, value)
        await state.clear()
        await message.answer("✅ Задача обновлена!", reply_markup=main_menu())

    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
