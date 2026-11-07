import asyncio
import logging
import os
from dotenv import load_dotenv
from dataclasses import dataclass
from random import uniform

import aiohttp
import aiosqlite
from aiogram import Bot, Dispatcher, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)


load_dotenv(dotenv_path=".env")

BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_PATH = "subscriptions.db"
BINANCE_BASE_URL = "https://api.binance.com"
MONITOR_INTERVAL_SECONDS = 10 * 60
REQUEST_TIMEOUT_SECONDS = 30
DEFAULT_LANGUAGE = "ru"
SUPPORTED_SYMBOLS = {
    "BTC": "BTCUSDT",
    "ETH": "ETHUSDT",
    "TON": "TONUSDT",
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)
router = Router()


@dataclass(frozen=True)
class Listing:
    title: str
    price: str
    url: str
    price_value: float


class UserInput(StatesGroup):
    waiting_query = State()


TEXTS = {
    "ru": {
        "welcome": "Привет! Я слежу за курсами BTC, ETH и TON на Binance.",
        "subscriptions": "📋 Мои подписки",
        "add": "➕ Добавить",
        "remove": "➖ Удалить",
        "browse": "📈 Смотреть курс",
        "filters": "📊 Все курсы",
        "clear": "🗑 Очистить все",
        "language": "🌐 Язык",
        "help": "ℹ️ Помощь",
        "back": "⬅️ Назад",
        "next": "➡️ Следующее",
        "previous": "⬅️ Предыдущее",
        "open": "🔗 Открыть Binance",
        "home": "🏠 Главное меню",
        "language_title": "Выберите язык:",
        "enter_query": "Введите тикер криптовалюты: BTC, ETH или TON",
        "invalid_symbol": "Поддерживаются только BTC, ETH и TON.",
        "no_results": "Не удалось получить курс. Попробуйте позже.",
        "removed": "Подписка удалена.",
        "russian": "Русский",
        "ukrainian": "🇺🇦 Українська",
        "no_subscriptions": "У вас пока нет подписок.",
        "subscriptions_title": "Ваши подписки:",
        "help_text": (
            "Кнопка «Добавить» — подписка на BTC, ETH или TON.\n"
            "Бот проверяет курс Binance каждые 10 минут и сообщает об изменениях."
        ),
        "cleared": "Все ваши подписки удалены.",
        "added": "Подписка на {query} добавлена.",
        "already_added": "Такая подписка уже существует.",
        "missing_query": "Укажите тикер: BTC, ETH или TON.",
        "user_error": "Не удалось определить пользователя.",
        "save_error": "Не удалось сохранить подписку. Попробуйте позже.",
        "new_listing": "📈 {query}/USDT: {price} USDT\nИзменение: {change}\nОткрыть Binance: {url}",
    },
    "uk": {
        "welcome": "Привіт! Я стежу за курсами BTC, ETH і TON на Binance.",
        "subscriptions": "📋 Мої підписки",
        "add": "➕ Додати",
        "remove": "➖ Видалити",
        "browse": "📈 Переглянути курс",
        "filters": "📊 Усі курси",
        "clear": "🗑 Очистити все",
        "language": "🌐 Мова",
        "help": "ℹ️ Допомога",
        "back": "⬅️ Назад",
        "next": "➡️ Наступне",
        "previous": "⬅️ Попереднє",
        "open": "🔗 Відкрити Binance",
        "home": "🏠 Головне меню",
        "language_title": "Оберіть мову:",
        "enter_query": "Введіть тікер криптовалюти: BTC, ETH або TON",
        "invalid_symbol": "Підтримуються лише BTC, ETH і TON.",
        "removed": "Підписку видалено.",
        "russian": "Русский",
        "ukrainian": "🇺🇦 Українська",
        "no_subscriptions": "У вас поки немає підписок.",
        "subscriptions_title": "Ваші підписки:",
        "help_text": (
            "Кнопка «Додати» — підписка на BTC, ETH або TON.\n"
            "Бот перевіряє курс Binance кожні 10 хвилин і повідомляє про зміни."
        ),
        "cleared": "Усі ваші підписки видалено.",
        "added": "Підписку на {query} додано.",
        "already_added": "Така підписка вже існує.",
        "missing_query": "Вкажіть тікер: BTC, ETH або TON.",
        "user_error": "Не вдалося визначити користувача.",
        "save_error": "Не вдалося зберегти підписку. Спробуйте пізніше.",
        "new_listing": "📈 {query}/USDT: {price} USDT\nЗміна: {change}\nВідкрити Binance: {url}",
    },
}


async def init_database() -> None:
    async with aiosqlite.connect(DATABASE_PATH) as database:
        await database.execute(
            """
            CREATE TABLE IF NOT EXISTS subscriptions (
                user_id INTEGER NOT NULL,
                query_text TEXT NOT NULL,
                last_seen_url TEXT NOT NULL DEFAULT '',
                min_price INTEGER,
                max_price INTEGER,
                last_seen_price REAL,
                PRIMARY KEY (user_id, query_text)
            )
            """
        )
        await database.execute(
            """
            CREATE TABLE IF NOT EXISTS user_settings (
                user_id INTEGER PRIMARY KEY,
                language TEXT NOT NULL DEFAULT 'ru',
                menu_message_id INTEGER
            )
            """
        )
        columns_cursor = await database.execute("PRAGMA table_info(subscriptions)")
        columns = {row[1] for row in await columns_cursor.fetchall()}
        if "min_price" not in columns:
            await database.execute("ALTER TABLE subscriptions ADD COLUMN min_price INTEGER")
        if "max_price" not in columns:
            await database.execute("ALTER TABLE subscriptions ADD COLUMN max_price INTEGER")
        if "last_seen_price" not in columns:
            await database.execute(
                "ALTER TABLE subscriptions ADD COLUMN last_seen_price REAL"
            )
        await database.execute(
            "DELETE FROM subscriptions WHERE query_text NOT IN ('BTC', 'ETH', 'TON')"
        )
        await database.commit()
    logger.info("Database initialized: %s", DATABASE_PATH)


def normalize_symbol(value: str) -> str | None:
    symbol = value.strip().upper().replace("/", "").replace("USDT", "")
    return symbol if symbol in SUPPORTED_SYMBOLS else None


def build_symbol_url(symbol: str) -> str:
    return f"https://www.binance.com/en/trade/{symbol}_USDT"


def parse_binance_price(payload: object, symbol: str) -> Listing | None:
    if not isinstance(payload, dict):
        return None
    raw_price = payload.get("price")
    try:
        price = float(raw_price)
    except (TypeError, ValueError):
        return None
    return Listing(
        title=f"{symbol}/USDT",
        price=f"{price:,.8f}".rstrip("0").rstrip("."),
        url=build_symbol_url(symbol),
        price_value=price,
    )


async def fetch_listings(session: aiohttp.ClientSession, query_text: str) -> list[Listing]:
    symbol = normalize_symbol(query_text)
    if symbol is None:
        return []
    url = f"{BINANCE_BASE_URL}/api/v3/ticker/price"
    headers = {
        "Accept": "application/json",
    }
    try:
        async with session.get(
            url,
            params={"symbol": SUPPORTED_SYMBOLS[symbol]},
            headers=headers,
        ) as response:
            response.raise_for_status()
            payload = await response.json()
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
        logger.exception("Could not fetch Binance price for %s", symbol)
        return []

    listing = parse_binance_price(payload, symbol)
    return [listing] if listing else []


async def add_subscription(user_id: int, query_text: str) -> bool:
    symbol = normalize_symbol(query_text)
    if symbol is None:
        return False
    async with aiosqlite.connect(DATABASE_PATH) as database:
        cursor = await database.execute(
            """
            INSERT OR IGNORE INTO subscriptions (user_id, query_text)
            VALUES (?, ?)
            """,
            (user_id, symbol),
        )
        await database.commit()
        return cursor.rowcount == 1


async def get_user_settings(user_id: int) -> tuple[str, int | None]:
    async with aiosqlite.connect(DATABASE_PATH) as database:
        cursor = await database.execute(
            "SELECT language, menu_message_id FROM user_settings WHERE user_id = ?",
            (user_id,),
        )
        row = await cursor.fetchone()
    if row is None:
        return DEFAULT_LANGUAGE, None
    language = row[0] if row[0] in TEXTS else DEFAULT_LANGUAGE
    return language, row[1]


async def save_user_settings(
    user_id: int, *, language: str | None = None, menu_message_id: int | None = None
) -> None:
    current_language, current_message_id = await get_user_settings(user_id)
    async with aiosqlite.connect(DATABASE_PATH) as database:
        await database.execute(
            """
            INSERT INTO user_settings (user_id, language, menu_message_id)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                language = excluded.language,
                menu_message_id = excluded.menu_message_id
            """,
            (
                user_id,
                language or current_language,
                menu_message_id
                if menu_message_id is not None
                else current_message_id,
            ),
        )
        await database.commit()


def menu_keyboard(language: str) -> InlineKeyboardMarkup:
    text = TEXTS[language]
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=text["add"], callback_data="add"),
                InlineKeyboardButton(text=text["subscriptions"], callback_data="menu:subscriptions"),
            ],
            [
                InlineKeyboardButton(text=text["browse"], callback_data="browse:list"),
                InlineKeyboardButton(text=text["remove"], callback_data="remove:list"),
            ],
            [InlineKeyboardButton(text=text["clear"], callback_data="clear")],
            [
                InlineKeyboardButton(text=text["language"], callback_data="menu:language"),
                InlineKeyboardButton(text=text["filters"], callback_data="filters:list"),
            ],
            [InlineKeyboardButton(text=text["help"], callback_data="menu:help")],
        ]
    )


def back_keyboard(language: str) -> InlineKeyboardMarkup:
    text = TEXTS[language]
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=text["back"], callback_data="menu:home")]
        ]
    )


def language_keyboard(language: str) -> InlineKeyboardMarkup:
    text = TEXTS[language]
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=text["russian"], callback_data="language:ru"),
                InlineKeyboardButton(text=text["ukrainian"], callback_data="language:uk"),
            ],
            [InlineKeyboardButton(text=text["back"], callback_data="menu:home")],
        ]
    )


def skip_keyboard(language: str, action: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=TEXTS[language]["skip"], callback_data=f"{action}:skip")],
            [InlineKeyboardButton(text=TEXTS[language]["back"], callback_data="menu:home")],
        ]
    )


async def get_subscriptions(user_id: int) -> list[tuple[str, int | None, int | None]]:
    async with aiosqlite.connect(DATABASE_PATH) as database:
        cursor = await database.execute(
            "SELECT query_text, min_price, max_price FROM subscriptions "
            "WHERE user_id = ? ORDER BY query_text",
            (user_id,),
        )
        rows = await cursor.fetchall()
    return [(row[0], row[1], row[2]) for row in rows]


def subscription_keyboard(
    language: str,
    subscriptions: list[tuple[str, int | None, int | None]],
    action: str,
) -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton(
                text=f"{index}. {query[:28]}",
                callback_data=f"{action}:{index - 1}",
            )
        ]
        for index, (query, _, _) in enumerate(subscriptions, 1)
    ]
    buttons.append(
        [InlineKeyboardButton(text=TEXTS[language]["back"], callback_data="menu:home")]
    )
    return InlineKeyboardMarkup(inline_keyboard=buttons)


async def render_menu(
    message: Message, user_id: int, *, text: str, markup: InlineKeyboardMarkup
) -> None:
    _, old_message_id = await get_user_settings(user_id)
    if old_message_id and old_message_id != message.message_id:
        try:
            await message.bot.delete_message(user_id, old_message_id)
        except TelegramAPIError:
            logger.warning("Could not delete old menu message %s", old_message_id)
    new_message = await message.answer(text, reply_markup=markup)
    await save_user_settings(user_id, menu_message_id=new_message.message_id)


async def edit_menu(
    callback: CallbackQuery, user_id: int, *, text: str, markup: InlineKeyboardMarkup
) -> None:
    if callback.message is None:
        await callback.answer()
        return
    await callback.message.edit_text(text, reply_markup=markup)
    await save_user_settings(user_id, menu_message_id=callback.message.message_id)
    await callback.answer()


async def edit_saved_menu(
    message: Message,
    user_id: int,
    language: str,
    text: str,
    markup: InlineKeyboardMarkup,
) -> None:
    _, menu_message_id = await get_user_settings(user_id)
    if menu_message_id is None:
        await render_menu(message, user_id, text=text, markup=markup)
        return
    try:
        await message.bot.edit_message_text(
            chat_id=user_id,
            message_id=menu_message_id,
            text=text,
            reply_markup=markup,
        )
    except TelegramAPIError:
        logger.exception("Could not edit saved menu for user %s", user_id)
        await render_menu(message, user_id, text=text, markup=markup)


@router.message(UserInput.waiting_query)
async def query_input_handler(message: Message, state: FSMContext) -> None:
    user_id = message.from_user.id if message.from_user else None
    if user_id is None:
        return
    language, _ = await get_user_settings(user_id)
    query_text = (message.text or "").strip()
    if not query_text:
        return
    symbol = normalize_symbol(query_text)
    if symbol is None:
        await edit_saved_menu(
            message,
            user_id,
            language,
            TEXTS[language]["invalid_symbol"],
            back_keyboard(language),
        )
        return
    await add_subscription(user_id, symbol)
    await state.clear()
    try:
        await message.delete()
    except TelegramAPIError:
        logger.warning("Could not delete query input from user %s", user_id)
    await edit_saved_menu(
        message,
        user_id,
        language,
        TEXTS[language]["added"].format(query=query_text),
        back_keyboard(language),
    )


@router.message(Command("start"))
async def start_handler(message: Message) -> None:
    user_id = message.from_user.id if message.from_user else None
    if user_id is None:
        await message.answer(TEXTS[DEFAULT_LANGUAGE]["user_error"])
        return
    language, _ = await get_user_settings(user_id)
    await render_menu(
        message,
        user_id,
        text=TEXTS[language]["welcome"],
        markup=menu_keyboard(language),
    )


@router.message(Command("add"))
async def add_handler(message: Message, command: CommandObject) -> None:
    user_id = message.from_user.id if message.from_user else None
    if user_id is None:
        await message.answer(TEXTS[DEFAULT_LANGUAGE]["user_error"])
        return
    language, _ = await get_user_settings(user_id)
    text = TEXTS[language]
    query_text = (command.args or "").strip()
    if not query_text:
        await render_menu(
            message,
            user_id,
            text=text["missing_query"],
            markup=back_keyboard(language),
        )
        return

    symbol = normalize_symbol(query_text)
    if symbol is None:
        await render_menu(
            message,
            user_id,
            text=text["invalid_symbol"],
            markup=back_keyboard(language),
        )
        return

    try:
        added = await add_subscription(user_id, symbol)
    except aiosqlite.Error:
        logger.exception("Could not add subscription for user %s", user_id)
        await render_menu(
            message,
            user_id,
            text=text["save_error"],
            markup=back_keyboard(language),
        )
        return

    result_text = (
        text["added"].format(query=symbol) if added else text["already_added"]
    )
    await render_menu(
        message,
        user_id,
        text=result_text,
        markup=back_keyboard(language),
    )


@router.message(Command("list"))
async def list_handler(message: Message) -> None:
    user_id = message.from_user.id if message.from_user else None
    if user_id is None:
        await message.answer(TEXTS[DEFAULT_LANGUAGE]["user_error"])
        return

    language, _ = await get_user_settings(user_id)
    await show_subscriptions(message, user_id, language)


@router.message(Command("clear"))
async def clear_handler(message: Message) -> None:
    user_id = message.from_user.id if message.from_user else None
    if user_id is None:
        await message.answer(TEXTS[DEFAULT_LANGUAGE]["user_error"])
        return

    async with aiosqlite.connect(DATABASE_PATH) as database:
        await database.execute(
            "DELETE FROM subscriptions WHERE user_id = ?", (user_id,)
        )
        await database.commit()
    language, _ = await get_user_settings(user_id)
    await render_menu(
        message,
        user_id,
        text=TEXTS[language]["cleared"],
        markup=back_keyboard(language),
    )


async def show_subscriptions(
    message: Message | CallbackQuery, user_id: int, language: str
) -> None:
    text = TEXTS[language]
    subscriptions = await get_subscriptions(user_id)
    body = text["no_subscriptions"]
    if subscriptions:
        body = text["subscriptions_title"]
        markup = subscription_keyboard(language, subscriptions, "sub")
    else:
        markup = back_keyboard(language)
    if isinstance(message, CallbackQuery):
        await edit_menu(
            message,
            user_id,
            text=body,
            markup=markup,
        )
    else:
        await render_menu(
            message,
            user_id,
            text=body,
            markup=markup,
        )


async def show_subscription_action(
    callback: CallbackQuery, user_id: int, language: str, action: str
) -> None:
    subscriptions = await get_subscriptions(user_id)
    if not subscriptions:
        await edit_menu(
            callback,
            user_id,
            text=TEXTS[language]["no_subscriptions"],
            markup=back_keyboard(language),
        )
        return
    await edit_menu(
        callback,
        user_id,
        text=TEXTS[language]["subscriptions_title"],
        markup=subscription_keyboard(language, subscriptions, action),
    )


async def update_price_filter(
    user_id: int, query_text: str, minimum: int | None, maximum: int | None
) -> None:
    async with aiosqlite.connect(DATABASE_PATH) as database:
        await database.execute(
            "UPDATE subscriptions SET min_price = ?, max_price = ? "
            "WHERE user_id = ? AND query_text = ?",
            (minimum, maximum, user_id, query_text),
        )
        await database.commit()


def listings_keyboard(
    language: str, listing: Listing, index: int, total: int, query_index: int
) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text=TEXTS[language]["open"], url=listing.url)],
    ]
    navigation = []
    if index > 0:
        navigation.append(
            InlineKeyboardButton(
                text=TEXTS[language]["previous"],
                callback_data=f"browse:{query_index}:{index - 1}",
            )
        )
    if index + 1 < total:
        navigation.append(
            InlineKeyboardButton(
                text=TEXTS[language]["next"],
                callback_data=f"browse:{query_index}:{index + 1}",
            )
        )
    if navigation:
        buttons.append(navigation)
    buttons.append(
        [InlineKeyboardButton(text=TEXTS[language]["back"], callback_data="browse:list")]
    )
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def search_link_keyboard(language: str, query_text: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=TEXTS[language]["open"],
                    url=build_symbol_url(normalize_symbol(query_text) or "BTC"),
                )
            ],
            [InlineKeyboardButton(text=TEXTS[language]["back"], callback_data="menu:home")],
        ]
    )


async def show_listing(
    callback: CallbackQuery, user_id: int, language: str, query_index: int, page: int
) -> None:
    subscriptions = await get_subscriptions(user_id)
    if query_index >= len(subscriptions):
        await callback.answer()
        return
    query_text, _, _ = subscriptions[query_index]
    async with aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT_SECONDS)
    ) as session:
        listings = await fetch_listings(session, query_text)
    if not listings:
        await edit_menu(
            callback,
            user_id,
            text=TEXTS[language]["no_results"],
            markup=search_link_keyboard(language, query_text),
        )
        return
    page = max(0, min(page, len(listings) - 1))
    listing = listings[page]
    await edit_menu(
        callback,
        user_id,
        text=f"{listing.title}\n💰 {listing.price} USDT\n\n{page + 1}/{len(listings)}",
        markup=listings_keyboard(language, listing, page, len(listings), query_index),
    )


@router.callback_query()
async def menu_callback_handler(callback: CallbackQuery, state: FSMContext) -> None:
    user_id = callback.from_user.id
    language, _ = await get_user_settings(user_id)
    data = callback.data or ""

    if data == "add":
        await state.set_state(UserInput.waiting_query)
        await edit_menu(
            callback,
            user_id,
            text=TEXTS[language]["enter_query"],
            markup=back_keyboard(language),
        )
    elif data == "menu:home":
        await state.clear()
        await edit_menu(
            callback,
            user_id,
            text=TEXTS[language]["welcome"],
            markup=menu_keyboard(language),
        )
    elif data == "menu:subscriptions":
        await show_subscriptions(callback, user_id, language)
    elif data == "browse:list":
        await show_subscription_action(callback, user_id, language, "browse")
    elif data == "remove:list":
        await show_subscription_action(callback, user_id, language, "remove")
    elif data == "filters:list":
        await show_subscription_action(callback, user_id, language, "sub")
    elif data == "clear":
        async with aiosqlite.connect(DATABASE_PATH) as database:
            await database.execute(
                "DELETE FROM subscriptions WHERE user_id = ?", (user_id,)
            )
            await database.commit()
        await edit_menu(
            callback,
            user_id,
            text=TEXTS[language]["cleared"],
            markup=back_keyboard(language),
        )
    elif data.startswith("browse:"):
        parts = data.split(":")
        if len(parts) == 2:
            query_index, page = parts[1], 0
        elif len(parts) == 3:
            _, query_index, page = parts
        else:
            await callback.answer()
            return
        await show_listing(callback, user_id, language, int(query_index), int(page))
    elif data.startswith("sub:"):
        query_index = int(data.split(":")[1])
        await show_listing(callback, user_id, language, query_index, 0)
    elif data.startswith("remove:") and data != "remove:list":
        subscriptions = await get_subscriptions(user_id)
        query_index = int(data.split(":")[1])
        if query_index < len(subscriptions):
            query_text = subscriptions[query_index][0]
            async with aiosqlite.connect(DATABASE_PATH) as database:
                await database.execute(
                    "DELETE FROM subscriptions WHERE user_id = ? AND query_text = ?",
                    (user_id, query_text),
                )
                await database.commit()
        await show_subscriptions(callback, user_id, language)
    elif data == "menu:language":
        await edit_menu(
            callback,
            user_id,
            text=TEXTS[language]["language_title"],
            markup=language_keyboard(language),
        )
    elif data == "menu:help":
        await edit_menu(
            callback,
            user_id,
            text=TEXTS[language]["help_text"],
            markup=back_keyboard(language),
        )
    elif data.startswith("language:"):
        selected_language = data.split(":", 1)[1]
        if selected_language not in TEXTS:
            await callback.answer("Unknown language", show_alert=True)
            return
        await save_user_settings(user_id, language=selected_language)
        await edit_menu(
            callback,
            user_id,
            text=TEXTS[selected_language]["welcome"],
            markup=menu_keyboard(selected_language),
        )
    else:
        await callback.answer()


async def monitor_subscriptions(bot: Bot) -> None:
    timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT_SECONDS)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        while True:
            try:
                async with aiosqlite.connect(DATABASE_PATH) as database:
                    cursor = await database.execute(
                        """
                        SELECT user_id, query_text, last_seen_price
                        FROM subscriptions
                        """
                    )
                    subscriptions = await cursor.fetchall()

                for user_id, query_text, last_seen_price in subscriptions:
                    listings = await fetch_listings(session, query_text)
                    if listings:
                        current = listings[0]
                        if last_seen_price is None:
                            async with aiosqlite.connect(
                                DATABASE_PATH
                            ) as database:
                                await database.execute(
                                    """
                                    UPDATE subscriptions
                                    SET last_seen_price = ?
                                    WHERE user_id = ? AND query_text = ?
                                    """,
                                    (current.price_value, user_id, query_text),
                                )
                                await database.commit()
                        elif current.price_value != last_seen_price:
                            try:
                                language, _ = await get_user_settings(user_id)
                                change = current.price_value - last_seen_price
                                await bot.send_message(
                                    user_id,
                                    TEXTS[language]["new_listing"].format(
                                        query=query_text,
                                        price=current.price,
                                        change=f"{change:+.8f} USDT",
                                    )
                                    ,
                                    reply_markup=InlineKeyboardMarkup(
                                        inline_keyboard=[
                                            [
                                                InlineKeyboardButton(
                                                    text=TEXTS[language]["open"],
                                                    url=current.url,
                                                )
                                            ]
                                        ]
                                    ),
                                )
                                async with aiosqlite.connect(
                                    DATABASE_PATH
                                ) as database:
                                    await database.execute(
                                        """
                                        UPDATE subscriptions
                                        SET last_seen_price = ?
                                        WHERE user_id = ? AND query_text = ?
                                        """,
                                        (current.price_value, user_id, query_text),
                                    )
                                    await database.commit()
                                logger.info(
                                    "Notification sent to %s for %r",
                                    user_id,
                                    query_text,
                                )
                            except (TelegramAPIError, aiosqlite.Error):
                                logger.exception(
                                    "Could not notify user %s for %r",
                                    user_id,
                                    query_text,
                                )

                    await asyncio.sleep(uniform(3, 5))
            except asyncio.CancelledError:
                logger.info("Subscription monitor stopped")
                raise
            except (
                aiosqlite.Error,
                aiohttp.ClientError,
                asyncio.TimeoutError,
                TelegramAPIError,
            ):
                logger.exception("Monitor iteration failed")

            await asyncio.sleep(MONITOR_INTERVAL_SECONDS)


async def main() -> None:
    if not BOT_TOKEN:
        raise RuntimeError(
            "Set the BOT_TOKEN constant or the BOT_TOKEN environment variable."
        )

    await init_database()
    bot = Bot(token=BOT_TOKEN)
    dispatcher = Dispatcher(storage=MemoryStorage())
    dispatcher.include_router(router)
    monitor_task = asyncio.create_task(monitor_subscriptions(bot))

    try:
        logger.info("Bot started")
        await dispatcher.start_polling(bot)
    finally:
        monitor_task.cancel()
        await asyncio.gather(monitor_task, return_exceptions=True)
        await bot.session.close()
        logger.info("Bot stopped")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot interrupted by user")