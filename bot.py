import asyncio
import logging
import os
from dotenv import load_dotenv
from dataclasses import dataclass
from html import unescape
from random import uniform
from urllib.parse import quote, urljoin

import aiohttp
import aiosqlite
from aiogram import Bot, Dispatcher, Router
from aiogram.exceptions import TelegramError
from aiogram.filters import Command, CommandObject
from aiogram.types import Message
from bs4 import BeautifulSoup


load_dotenv(dotenv_path="BOT_TOKEN.env")

BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_PATH = "subscriptions.db"
OLX_BASE_URL = "https://olx.ua"
MONITOR_INTERVAL_SECONDS = 10 * 60
REQUEST_TIMEOUT_SECONDS = 30

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


async def init_database() -> None:
    async with aiosqlite.connect(DATABASE_PATH) as database:
        await database.execute(
            """
            CREATE TABLE IF NOT EXISTS subscriptions (
                user_id INTEGER NOT NULL,
                query_text TEXT NOT NULL,
                last_seen_url TEXT NOT NULL DEFAULT '',
                PRIMARY KEY (user_id, query_text)
            )
            """
        )
        await database.commit()
    logger.info("Database initialized: %s", DATABASE_PATH)


def build_search_url(query_text: str) -> str:
    query = query_text.strip()
    if query.startswith("/"):
        path = query.rstrip("/")
    else:
        slug = quote(query.replace(" ", "-"), safe="-_")
        path = f"/uk/list/q-{slug}"
    return f"{OLX_BASE_URL}{path}/"


def parse_listings(html: str, page_url: str) -> list[Listing]:
    soup = BeautifulSoup(html, "html.parser")
    listings: list[Listing] = []
    seen_urls: set[str] = set()

    cards = soup.select('[data-cy="l-card"]')
    if not cards:
        cards = soup.select("div[data-testid='l-card']")

    for card in cards:
        link_element = card.select_one("a[href]")
        if link_element is None:
            continue

        url = urljoin(page_url, link_element.get("href", "")).split("?")[0]
        if not url.startswith(OLX_BASE_URL) or url in seen_urls:
            continue

        title_element = card.select_one("h6, h4, [data-cy='ad-card-title']")
        price_element = card.select_one(
            "[data-testid='ad-price'], [data-cy='ad-card-price'], p"
        )
        title = (
            title_element.get_text(" ", strip=True)
            if title_element is not None
            else link_element.get_text(" ", strip=True)
        )
        price = (
            price_element.get_text(" ", strip=True)
            if price_element is not None
            else "Цена не указана"
        )
        if not title:
            title = "Без названия"

        listings.append(
            Listing(
                title=unescape(title),
                price=unescape(price),
                url=url,
            )
        )
        seen_urls.add(url)
        if len(listings) == 5:
            break

    return listings


async def fetch_listings(
    session: aiohttp.ClientSession, query_text: str
) -> list[Listing]:
    url = build_search_url(query_text)
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "uk-UA,uk;q=0.9,ru;q=0.8,en;q=0.7",
    }
    logger.info("Fetching OLX search: %s", url)
    try:
        async with session.get(url, headers=headers) as response:
            response.raise_for_status()
            html = await response.text()
    except (aiohttp.ClientError, asyncio.TimeoutError):
        logger.exception("Could not fetch OLX search for %r", query_text)
        return []

    listings = parse_listings(html, url)
    logger.info("Parsed %d listings for %r", len(listings), query_text)
    return listings


async def add_subscription(user_id: int, query_text: str) -> bool:
    async with aiosqlite.connect(DATABASE_PATH) as database:
        cursor = await database.execute(
            """
            INSERT OR IGNORE INTO subscriptions (user_id, query_text)
            VALUES (?, ?)
            """,
            (user_id, query_text),
        )
        await database.commit()
        return cursor.rowcount == 1


@router.message(Command("start"))
async def start_handler(message: Message) -> None:
    await message.answer(
        "Привет! Я слежу за новыми объявлениями OLX.\n\n"
        "Команды:\n"
        "/add <запрос> — добавить подписку\n"
        "/list — показать подписки\n"
        "/clear — удалить все подписки\n\n"
        "Пример: /add /d/uk/q-thinkpad-x280/"
    )


@router.message(Command("add"))
async def add_handler(message: Message, command: CommandObject) -> None:
    query_text = (command.args or "").strip()
    if not query_text:
        await message.answer(
            "Укажите запрос после команды. Пример:\n"
            "/add /d/uk/q-thinkpad-x280/"
        )
        return

    user_id = message.from_user.id if message.from_user else None
    if user_id is None:
        await message.answer("Не удалось определить пользователя.")
        return

    try:
        added = await add_subscription(user_id, query_text)
    except aiosqlite.Error:
        logger.exception("Could not add subscription for user %s", user_id)
        await message.answer("Не удалось сохранить подписку. Попробуйте позже.")
        return

    if added:
        await message.answer(f"Подписка добавлена: {query_text}")
    else:
        await message.answer("Такая подписка уже существует.")


@router.message(Command("list"))
async def list_handler(message: Message) -> None:
    user_id = message.from_user.id if message.from_user else None
    if user_id is None:
        await message.answer("Не удалось определить пользователя.")
        return

    async with aiosqlite.connect(DATABASE_PATH) as database:
        cursor = await database.execute(
            "SELECT query_text FROM subscriptions WHERE user_id = ? ORDER BY query_text",
            (user_id,),
        )
        rows = await cursor.fetchall()

    if not rows:
        await message.answer("У вас пока нет подписок.")
        return
    subscriptions = "\n".join(f"{index}. {row[0]}" for index, row in enumerate(rows, 1))
    await message.answer(f"Ваши подписки:\n{subscriptions}")


@router.message(Command("clear"))
async def clear_handler(message: Message) -> None:
    user_id = message.from_user.id if message.from_user else None
    if user_id is None:
        await message.answer("Не удалось определить пользователя.")
        return

    async with aiosqlite.connect(DATABASE_PATH) as database:
        await database.execute(
            "DELETE FROM subscriptions WHERE user_id = ?", (user_id,)
        )
        await database.commit()
    await message.answer("Все ваши подписки удалены.")


async def monitor_subscriptions(bot: Bot) -> None:
    timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT_SECONDS)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        while True:
            try:
                async with aiosqlite.connect(DATABASE_PATH) as database:
                    cursor = await database.execute(
                        """
                        SELECT user_id, query_text, last_seen_url
                        FROM subscriptions
                        """
                    )
                    subscriptions = await cursor.fetchall()

                for user_id, query_text, last_seen_url in subscriptions:
                    listings = await fetch_listings(session, query_text)
                    if listings:
                        newest = listings[0]
                        if newest.url != last_seen_url:
                            try:
                                await bot.send_message(
                                    user_id,
                                    f"🔥 Найдено новое объявление по запросу "
                                    f"'{query_text}'!\n"
                                    f"Цена: {newest.price}\n"
                                    f"Ссылка: {newest.url}",
                                )
                                async with aiosqlite.connect(
                                    DATABASE_PATH
                                ) as database:
                                    await database.execute(
                                        """
                                        UPDATE subscriptions
                                        SET last_seen_url = ?
                                        WHERE user_id = ? AND query_text = ?
                                        """,
                                        (newest.url, user_id, query_text),
                                    )
                                    await database.commit()
                                logger.info(
                                    "Notification sent to %s for %r",
                                    user_id,
                                    query_text,
                                )
                            except (TelegramError, aiosqlite.Error):
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
                TelegramError,
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
    dispatcher = Dispatcher()
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