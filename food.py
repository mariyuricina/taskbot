"""
food.py — модуль холодильника и рецептов.
Подключается к боту через router.
"""
import os
import json
import logging
from datetime import datetime, date
from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
)
import db

logger = logging.getLogger(__name__)
router = Router()

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

UNITS = ["шт", "г", "кг", "мл", "л", "уп", "пучок", "ст.л", "ч.л"]

# ── States ───────────────────────────────────────────────────────────────────

class AddFridge(StatesGroup):
    name = State()
    quantity = State()
    unit = State()
    expires = State()

class AddRecipe(StatesGroup):
    name = State()
    ingredients = State()
    next_ingredient = State()
    description = State()

# ── Keyboards ────────────────────────────────────────────────────────────────

def food_menu():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="🥦 Холодильник"), KeyboardButton(text="📖 Рецепты")],
        [KeyboardButton(text="👨‍🍳 Что приготовить?"), KeyboardButton(text="🤖 AI-рецепт")],
        [KeyboardButton(text="🔙 Главное меню")],
    ], resize_keyboard=True)

def units_keyboard():
    buttons = []
    row = []
    for u in UNITS:
        row.append(InlineKeyboardButton(text=u, callback_data=f"unit:{u}"))
        if len(row) == 3:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([InlineKeyboardButton(text="❌ Отмена", callback_data="food_cancel")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def fridge_item_keyboard(item_id: int):
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✏️ Изменить кол-во", callback_data=f"fq:{item_id}"),
            InlineKeyboardButton(text="🗑 Удалить", callback_data=f"fdel:{item_id}"),
        ]
    ])

def recipe_keyboard(recipe_id: int):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🗑 Удалить рецепт", callback_data=f"rdel:{recipe_id}")]
    ])

def confirm_keyboard(yes_cb: str):
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Да", callback_data=yes_cb),
            InlineKeyboardButton(text="❌ Нет", callback_data="food_cancel"),
        ]
    ])

# ── Helpers ──────────────────────────────────────────────────────────────────

def format_fridge_item(item: dict) -> str:
    qty = f"{item['quantity']:g} {item['unit']}"
    exp = ""
    if item.get("expires_at"):
        try:
            d = date.fromisoformat(item["expires_at"])
            delta = (d - date.today()).days
            if delta < 0:
                exp = f" ⚠️ просрочено!"
            elif delta == 0:
                exp = f" ⚠️ истекает сегодня"
            elif delta <= 2:
                exp = f" ⚠️ до {item['expires_at']} ({delta}д)"
            else:
                exp = f" · до {item['expires_at']}"
        except Exception:
            exp = f" · до {item['expires_at']}"
    return f"*{item['name'].capitalize()}* — {qty}{exp}"

def format_recipe(recipe: dict) -> str:
    ings = recipe.get("ingredients", [])
    lines = []
    for ing in ings:
        qty = f"{ing['quantity']:g} {ing['unit']}" if ing.get("quantity") and ing.get("unit") else ""
        lines.append(f"  • {ing['name'].capitalize()}" + (f" — {qty}" if qty else ""))
    desc = f"\n_{recipe['description']}_" if recipe.get("description") else ""
    ing_text = "\n".join(lines) if lines else "  _ингредиенты не указаны_"
    return f"📖 *{recipe['name']}*{desc}\n\n*Ингредиенты:*\n{ing_text}"

async def call_claude(prompt: str) -> str:
    """Call Anthropic API for AI recipe suggestions."""
    import aiohttp
    if not ANTHROPIC_API_KEY:
        return "❌ ANTHROPIC_API_KEY не задан. Добавь его в переменные окружения Railway."
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": ANTHROPIC_API_KEY,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": "claude-haiku-4-5-20251001",
                    "max_tokens": 1024,
                    "messages": [{"role": "user", "content": prompt}],
                },
                timeout=aiohttp.ClientTimeout(total=30)
            ) as resp:
                data = await resp.json()
                return data["content"][0]["text"]
    except Exception as e:
        logger.error(f"Claude API error: {e}")
        return f"❌ Ошибка при обращении к AI: {e}"

# ── Menu entry ────────────────────────────────────────────────────────────────

@router.message(F.text == "🍽️ Еда и холодильник")
@router.message(F.text == "🥗 Еда")
async def food_section(message: Message):
    await message.answer("🍽️ Раздел еды:", reply_markup=food_menu())

@router.message(F.text == "🔙 Главное меню")
async def back_to_main(message: Message, state: FSMContext):
    await state.clear()
    from bot import main_menu
    await message.answer("Главное меню:", reply_markup=main_menu())

# ── Fridge ───────────────────────────────────────────────────────────────────

@router.message(F.text == "🥦 Холодильник")
async def show_fridge(message: Message):
    items = db.get_fridge_items(message.from_user.id)
    if not items:
        await message.answer(
            "🥦 *Холодильник пуст*\n\nДобавь продукты кнопкой ниже.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="➕ Добавить продукт", callback_data="fridge_add")]
            ])
        )
        return

    await message.answer("🥦 *Содержимое холодильника:*", parse_mode="Markdown")
    for item in items:
        await message.answer(
            format_fridge_item(item),
            parse_mode="Markdown",
            reply_markup=fridge_item_keyboard(item["id"])
        )
    await message.answer(
        "Добавить ещё?",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="➕ Добавить продукт", callback_data="fridge_add")]
        ])
    )

@router.callback_query(F.data == "fridge_add")
async def fridge_add_start(callback: CallbackQuery, state: FSMContext):
    await state.set_state(AddFridge.name)
    await callback.message.answer("Введи название продукта:", reply_markup=ReplyKeyboardRemove())
    await callback.answer()

@router.message(AddFridge.name)
async def fridge_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text.strip())
    await state.set_state(AddFridge.quantity)
    await message.answer("Сколько? Введи число (например: 500 или 2):")

@router.message(AddFridge.quantity)
async def fridge_quantity(message: Message, state: FSMContext):
    try:
        qty = float(message.text.strip().replace(",", "."))
    except ValueError:
        await message.answer("Введи число, например: 1 или 500")
        return
    await state.update_data(quantity=qty)
    await state.set_state(AddFridge.unit)
    await message.answer("Выбери единицу измерения:", reply_markup=units_keyboard())

@router.callback_query(F.data.startswith("unit:"), AddFridge.unit)
async def fridge_unit(callback: CallbackQuery, state: FSMContext):
    await state.update_data(unit=callback.data[5:])
    await state.set_state(AddFridge.expires)
    await callback.message.edit_text(
        "📅 Введи срок годности в формате ДД.ММ.ГГГГ\nили напиши *нет* если не важно:",
        parse_mode="Markdown"
    )

@router.message(AddFridge.expires)
async def fridge_expires(message: Message, state: FSMContext):
    text = message.text.strip().lower()
    expires = None
    if text != "нет":
        try:
            expires = datetime.strptime(text, "%d.%m.%Y").date().isoformat()
        except ValueError:
            await message.answer("Неверный формат. Введи дату как ДД.ММ.ГГГГ или напиши *нет*:", parse_mode="Markdown")
            return

    data = await state.get_data()
    await state.clear()
    db.add_fridge_item(message.from_user.id, data["name"], data["quantity"], data["unit"], expires)

    exp_text = f" до {expires}" if expires else ""
    await message.answer(
        f"✅ *{data['name'].capitalize()}* — {data['quantity']:g} {data['unit']}{exp_text} добавлен в холодильник!",
        parse_mode="Markdown",
        reply_markup=food_menu()
    )

@router.callback_query(F.data.startswith("fdel:"))
async def fridge_delete(callback: CallbackQuery):
    item_id = int(callback.data[5:])
    db.delete_fridge_item(item_id)
    await callback.answer("Удалено!")
    await callback.message.delete()

@router.callback_query(F.data.startswith("fq:"))
async def fridge_edit_qty_ask(callback: CallbackQuery, state: FSMContext):
    item_id = int(callback.data[3:])
    await state.set_state(AddFridge.quantity)
    await state.update_data(edit_item_id=item_id)
    await callback.message.answer("Введи новое количество:")
    await callback.answer()

# override quantity state to handle edit mode
@router.message(AddFridge.quantity)
async def fridge_quantity_or_edit(message: Message, state: FSMContext):
    data = await state.get_data()
    try:
        qty = float(message.text.strip().replace(",", "."))
    except ValueError:
        await message.answer("Введи число, например: 1 или 500")
        return

    if "edit_item_id" in data:
        db.update_fridge_quantity(data["edit_item_id"], qty)
        await state.clear()
        await message.answer("✅ Количество обновлено!", reply_markup=food_menu())
    else:
        await state.update_data(quantity=qty)
        await state.set_state(AddFridge.unit)
        await message.answer("Выбери единицу измерения:", reply_markup=units_keyboard())

# ── Recipes ──────────────────────────────────────────────────────────────────

@router.message(F.text == "📖 Рецепты")
async def show_recipes(message: Message):
    recipes = db.get_recipes(message.from_user.id)
    if not recipes:
        await message.answer(
            "📖 *Рецептов пока нет*\n\nДобавь свой рецепт:",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="➕ Добавить рецепт", callback_data="recipe_add")]
            ])
        )
        return

    await message.answer(f"📖 *Рецептов: {len(recipes)}*", parse_mode="Markdown")
    for recipe in recipes:
        await message.answer(
            format_recipe(recipe),
            parse_mode="Markdown",
            reply_markup=recipe_keyboard(recipe["id"])
        )
    await message.answer(
        "Добавить ещё?",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="➕ Добавить рецепт", callback_data="recipe_add")]
        ])
    )

@router.callback_query(F.data == "recipe_add")
async def recipe_add_start(callback: CallbackQuery, state: FSMContext):
    await state.set_state(AddRecipe.name)
    await state.update_data(ingredients=[])
    await callback.message.answer("Введи название рецепта:")
    await callback.answer()

@router.message(AddRecipe.name)
async def recipe_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text.strip())
    await state.set_state(AddRecipe.next_ingredient)
    await message.answer(
        "Теперь добавляй ингредиенты по одному.\n\n"
        "Формат: *название количество единица*\n"
        "Например: `молоко 500 мл` или просто `соль`\n\n"
        "Когда все ингредиенты добавлены — напиши *готово*",
        parse_mode="Markdown"
    )

@router.message(AddRecipe.next_ingredient)
async def recipe_ingredient(message: Message, state: FSMContext):
    text = message.text.strip()
    if text.lower() == "готово":
        await state.set_state(AddRecipe.description)
        await message.answer(
            "Добавь краткое описание или шаги приготовления (необязательно).\n"
            "Или напиши *нет*:",
            parse_mode="Markdown"
        )
        return

    parts = text.split()
    ing = {"name": parts[0].lower()}
    if len(parts) >= 3:
        try:
            ing["quantity"] = float(parts[1].replace(",", "."))
            ing["unit"] = parts[2]
        except ValueError:
            pass
    elif len(parts) == 2:
        ing["unit"] = parts[1]

    data = await state.get_data()
    ingredients = data.get("ingredients", [])
    ingredients.append(ing)
    await state.update_data(ingredients=ingredients)
    await message.answer(f"✅ *{ing['name'].capitalize()}* добавлен. Следующий или *готово*:", parse_mode="Markdown")

@router.message(AddRecipe.description)
async def recipe_description(message: Message, state: FSMContext):
    desc = message.text.strip()
    if desc.lower() == "нет":
        desc = None

    data = await state.get_data()
    recipe_id = db.add_recipe(
        message.from_user.id,
        data["name"],
        desc,
        data.get("ingredients", [])
    )
    await state.clear()
    recipe = db.get_recipe_by_id(recipe_id)
    await message.answer(
        f"✅ Рецепт сохранён!\n\n{format_recipe(recipe)}",
        parse_mode="Markdown",
        reply_markup=food_menu()
    )

@router.callback_query(F.data.startswith("rdel:"))
async def recipe_delete(callback: CallbackQuery):
    recipe_id = int(callback.data[5:])
    db.delete_recipe(recipe_id)
    await callback.answer("Рецепт удалён!")
    await callback.message.delete()

# ── What to cook ─────────────────────────────────────────────────────────────

@router.message(F.text == "👨‍🍳 Что приготовить?")
async def what_to_cook(message: Message):
    cookable = db.get_cookable_recipes(message.from_user.id)
    fridge = db.get_fridge_items(message.from_user.id)

    if not fridge:
        await message.answer("🥦 Холодильник пуст. Сначала добавь продукты!")
        return

    if not cookable:
        all_recipes = db.get_recipes(message.from_user.id)
        if not all_recipes:
            await message.answer(
                "📖 Рецептов нет. Добавь рецепты в разделе *Рецепты* или попроси AI придумать!",
                parse_mode="Markdown"
            )
        else:
            fridge_list = ", ".join(i["name"] for i in fridge)
            await message.answer(
                f"😕 Ни один рецепт из {len(all_recipes)} не подходит под продукты в холодильнике.\n\n"
                f"Есть: {fridge_list}\n\n"
                "Попробуй *🤖 AI-рецепт* — он предложит что-то из того, что есть!",
                parse_mode="Markdown"
            )
        return

    await message.answer(f"👨‍🍳 *Можно приготовить прямо сейчас ({len(cookable)}):*", parse_mode="Markdown")
    for recipe in cookable:
        await message.answer(format_recipe(recipe), parse_mode="Markdown")

# ── AI recipe ────────────────────────────────────────────────────────────────

@router.message(F.text == "🤖 AI-рецепт")
async def ai_recipe(message: Message):
    fridge = db.get_fridge_items(message.from_user.id)
    if not fridge:
        await message.answer("🥦 Холодильник пуст. Добавь продукты, и я попрошу AI придумать рецепт!")
        return

    items_text = "\n".join(
        f"- {i['name'].capitalize()}: {i['quantity']:g} {i['unit']}" for i in fridge
    )
    await message.answer("🤖 Думаю над рецептом...")

    prompt = (
        f"У меня в холодильнике есть:\n{items_text}\n\n"
        "Предложи 2-3 простых рецепта которые можно приготовить из этих продуктов "
        "(можно использовать не все, можно добавить базовые специи/соль/масло). "
        "Для каждого рецепта укажи: название, список ингредиентов с количеством, "
        "краткие шаги приготовления (3-5 шагов). Отвечай на русском языке."
    )

    response = await call_claude(prompt)
    await message.answer(f"🤖 *AI предлагает:*\n\n{response}", parse_mode="Markdown")

# ── Expiry reminders (called from scheduler) ─────────────────────────────────

async def check_expiry(bot):
    """Check for expiring products and notify users."""
    import sqlite3
    with db.get_conn() as conn:
        user_ids = [r[0] for r in conn.execute("SELECT id FROM users").fetchall()]

    notified_groups = set()
    for uid in user_ids:
        gid = db.get_group_id(uid)
        if gid in notified_groups:
            continue
        notified_groups.add(gid)

        expiring = db.get_expiring_soon(uid, days=2)
        if not expiring:
            continue

        lines = []
        for item in expiring:
            if item["expires_at"]:
                d = date.fromisoformat(item["expires_at"])
                delta = (d - date.today()).days
                if delta < 0:
                    label = "просрочено!"
                elif delta == 0:
                    label = "истекает сегодня"
                else:
                    label = f"истекает завтра"
                lines.append(f"• *{item['name'].capitalize()}* {item['quantity']:g}{item['unit']} — {label}")

        if lines:
            text = "🧊 *Продукты скоро испортятся:*\n\n" + "\n".join(lines)
            # notify all users in this group
            with db.get_conn() as conn:
                members = conn.execute(
                    "SELECT id FROM users WHERE id=? OR partner_id=?", (uid, uid)
                ).fetchall()
            for member in members:
                try:
                    await bot.send_message(member[0], text, parse_mode="Markdown")
                except Exception as e:
                    logger.warning(f"Could not send expiry notice to {member[0]}: {e}")

# ── Cancel ───────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "food_cancel")
async def food_cancel(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.delete()
    await callback.message.answer("Отменено.", reply_markup=food_menu())
