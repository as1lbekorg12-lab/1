# -*- coding: utf-8 -*-
"""
🎬 DRAMA (SERIAL) BOT — aiogram 3, bitta fayl

O'rnatish:
    pip install -U aiogram aiosqlite asyncpg

Muhit o'zgaruvchilari (server ulanayotganda beriladi):
    BOT_TOKEN      — bot tokeni                          (majburiy)
    OWNER_ID       — owner Telegram ID                   (majburiy)
    DATABASE_URL   — Postgres manzili (Neon/Supabase)    (Render uchun TAVSIYA)
                     berilmasa lokal SQLite (drama_bot.db) ishlatiladi
    PORT           — web server porti (Render o'zi beradi, default 10000)
    COLOR_BUTTONS  — 0 bo'lsa rangli tugmalar o'chiriladi (default 1)

Ishga tushirish:
    BOT_TOKEN="123:ABC" OWNER_ID="123456789" DATABASE_URL="postgresql://..." python main.py
"""

import asyncio
import html
import json
import logging
import os
import random
from math import ceil

import aiogram
from aiohttp import web
from aiogram import BaseMiddleware, Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ChatMemberStatus, ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import BaseFilter, Command, CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.base import BaseStorage, StorageKey
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    MessageOriginChannel,
    MessageOriginUser,
)

try:
    import aiosqlite
except ImportError:  # faqat Postgres ishlatilsa shart emas
    aiosqlite = None
try:
    import asyncpg
except ImportError:  # faqat SQLite ishlatilsa shart emas
    asyncpg = None

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("dramabot")

# ====================================================================
#                              SOZLAMALAR
# ====================================================================
DB_PATH = os.getenv("DB_PATH", "drama_bot.db")
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
USE_PG = bool(DATABASE_URL)
COLORED = os.getenv("COLOR_BUTTONS", "1") != "0"

OWNER_ID = 0            # main() ichida to'ldiriladi
BOT_USERNAME = ""       # main() ichida to'ldiriladi
STICKER_SETS = ["HotCherry", "AnimatedEmojies", "UtyaDuck"]
STICKERS: list = []

GENRES = ("action", "romance")
EP_PAGE = 20             # bir sahifada qismlar soni
LIST_PAGE = 8            # bir sahifada dramalar soni
SUB_CACHE_SECONDS = 120  # obuna tekshiruvi keshi (tezlik uchun)
SUB_FAIL_OPEN = True     # True: kanalni tekshirib bo'lmasa foydalanuvchini o'tkazadi (owner'ga xabar beriladi)
EP_BATCH_WAIT = 1.5      # videolar to'plami uchun kutish (soniya)

DEFAULT_CAPTION = (
    "🎬 <b>Drama nomi:</b> {nomi}\n"
    "📅 <b>Drama yili:</b> {yili}\n"
    "🔢 <b>Drama kodi:</b> {kodi}\n"
    "🎭 <b>Drama janri:</b> {janri}"
)

db = None   # sqlite ulanishi
pg = None   # asyncpg pool
EP_LOCK = asyncio.Lock()
EP_BUF: dict = {}
BG_TASKS: set = set()
JOINED_CACHE: dict = {}
LANG_CACHE: dict = {}
ADMINS: set = set()
NOTIFIED: dict = {}

esc = html.escape


def spawn(coro):
    t = asyncio.create_task(coro)
    BG_TASKS.add(t)
    t.add_done_callback(BG_TASKS.discard)
    return t


# ====================================================================
#                           TARJIMALAR (uz/ru/en)
# ====================================================================
T = {
    "uz": {
        "welcome": "🎉 Assalomu alaykum, <b>{name}</b>!\n\n🎬 Eng sara dramalar (seriallar) botiga xush kelibsiz! 🍿\n👇 Kerakli bo'limni tanlang:",
        "menu_title": "🏠 <b>Asosiy menyu</b>\n\n👇 Bo'limni tanlang:",
        "b_search": "🔍 Drama izlash",
        "b_genre": "🎭 Janr bo'yicha",
        "b_fav": "❤️ Sevimli dramalar",
        "b_back": "🔙 Orqaga",
        "b_home": "🏠 Menyu",
        "ask_search": "🔍 <b>Drama kodini yoki nomini yuboring:</b>\n\n✍️ Masalan: <code>5</code> yoki <code>Qirollik</code>",
        "nf": "😔 Hech narsa topilmadi. Qayta urinib ko'ring.",
        "choose_genre": "🎭 <b>Janrni tanlang:</b>",
        "g_action": "⚔️ Jangari",
        "g_romance": "💕 Romantik",
        "empty": "😔 Bu bo'limda hozircha dramalar yo'q.",
        "fav_empty": "💔 Sevimli dramalaringiz yo'q.\n\nDrama sahifasida «❤️ Sevimlilarga qo'shish» tugmasini bosing.",
        "fav_title": "❤️ <b>Sevimli dramalaringiz:</b>",
        "sub_title": "📢 <b>Botdan foydalanish uchun quyidagi kanallarga obuna bo'ling</b>, so'ng «✅ Tasdiqlash» tugmasini bosing 👇",
        "b_check": "✅ Tasdiqlash",
        "not_yet": "❌ Siz hali barcha kanallarga obuna bo'lmadingiz!",
        "card": "🎬 <b>{name}</b>\n\n📅 Yili: <b>{year}</b>\n🔢 Kodi: <b>{id}</b>\n🎭 Janri: <b>{genre}</b>\n📺 Qismlar soni: <b>{n}</b>",
        "no_eps": "\n\n⏳ Qismlar hali yuklanmagan.",
        "choose_ep": "\n\n👇 Qismni tanlang:",
        "b_fav_add": "❤️ Sevimlilarga qo'shish",
        "b_fav_del": "💔 Sevimlilardan o'chirish",
        "fav_added": "❤️ Sevimlilarga qo'shildi!",
        "fav_removed": "💔 Sevimlilardan o'chirildi.",
        "ep_cap": "🎬 <b>{name}</b>\n📺 <b>{num}-qism</b>",
        "b_eps": "📋 Qismlar",
        "gone": "😔 Drama topilmadi yoki o'chirilgan.",
    },
    "ru": {
        "welcome": "🎉 Здравствуйте, <b>{name}</b>!\n\n🎬 Добро пожаловать в бот лучших дорам (сериалов)! 🍿\n👇 Выберите нужный раздел:",
        "menu_title": "🏠 <b>Главное меню</b>\n\n👇 Выберите раздел:",
        "b_search": "🔍 Поиск дорамы",
        "b_genre": "🎭 По жанру",
        "b_fav": "❤️ Избранное",
        "b_back": "🔙 Назад",
        "b_home": "🏠 Меню",
        "ask_search": "🔍 <b>Отправьте код или название дорамы:</b>\n\n✍️ Например: <code>5</code> или <code>Королевство</code>",
        "nf": "😔 Ничего не найдено. Попробуйте ещё раз.",
        "choose_genre": "🎭 <b>Выберите жанр:</b>",
        "g_action": "⚔️ Боевик",
        "g_romance": "💕 Романтика",
        "empty": "😔 В этом разделе пока нет дорам.",
        "fav_empty": "💔 У вас нет избранных дорам.\n\nНажмите «❤️ В избранное» на странице дорамы.",
        "fav_title": "❤️ <b>Ваши избранные дорамы:</b>",
        "sub_title": "📢 <b>Подпишитесь на каналы ниже, чтобы пользоваться ботом</b>, затем нажмите «✅ Подтвердить» 👇",
        "b_check": "✅ Подтвердить",
        "not_yet": "❌ Вы ещё не подписались на все каналы!",
        "card": "🎬 <b>{name}</b>\n\n📅 Год: <b>{year}</b>\n🔢 Код: <b>{id}</b>\n🎭 Жанр: <b>{genre}</b>\n📺 Количество серий: <b>{n}</b>",
        "no_eps": "\n\n⏳ Серии ещё не загружены.",
        "choose_ep": "\n\n👇 Выберите серию:",
        "b_fav_add": "❤️ В избранное",
        "b_fav_del": "💔 Убрать из избранного",
        "fav_added": "❤️ Добавлено в избранное!",
        "fav_removed": "💔 Удалено из избранного.",
        "ep_cap": "🎬 <b>{name}</b>\n📺 <b>{num}-я серия</b>",
        "b_eps": "📋 Серии",
        "gone": "😔 Дорама не найдена или удалена.",
    },
    "en": {
        "welcome": "🎉 Hello, <b>{name}</b>!\n\n🎬 Welcome to the best dramas (series) bot! 🍿\n👇 Choose a section:",
        "menu_title": "🏠 <b>Main menu</b>\n\n👇 Choose a section:",
        "b_search": "🔍 Search drama",
        "b_genre": "🎭 By genre",
        "b_fav": "❤️ Favorites",
        "b_back": "🔙 Back",
        "b_home": "🏠 Menu",
        "ask_search": "🔍 <b>Send the drama code or name:</b>\n\n✍️ Example: <code>5</code> or <code>Kingdom</code>",
        "nf": "😔 Nothing found. Please try again.",
        "choose_genre": "🎭 <b>Choose a genre:</b>",
        "g_action": "⚔️ Action",
        "g_romance": "💕 Romance",
        "empty": "😔 There are no dramas in this section yet.",
        "fav_empty": "💔 You have no favorite dramas.\n\nTap «❤️ Add to favorites» on a drama page.",
        "fav_title": "❤️ <b>Your favorite dramas:</b>",
        "sub_title": "📢 <b>Subscribe to the channels below to use the bot</b>, then tap «✅ Confirm» 👇",
        "b_check": "✅ Confirm",
        "not_yet": "❌ You haven't subscribed to all channels yet!",
        "card": "🎬 <b>{name}</b>\n\n📅 Year: <b>{year}</b>\n🔢 Code: <b>{id}</b>\n🎭 Genre: <b>{genre}</b>\n📺 Episodes: <b>{n}</b>",
        "no_eps": "\n\n⏳ Episodes are not uploaded yet.",
        "choose_ep": "\n\n👇 Choose an episode:",
        "b_fav_add": "❤️ Add to favorites",
        "b_fav_del": "💔 Remove from favorites",
        "fav_added": "❤️ Added to favorites!",
        "fav_removed": "💔 Removed from favorites.",
        "ep_cap": "🎬 <b>{name}</b>\n📺 <b>Episode {num}</b>",
        "b_eps": "📋 Episodes",
        "gone": "😔 Drama not found or deleted.",
    },
}
PICK_LANG = "🌐 <b>Tilni tanlang</b>\nВыберите язык\nChoose your language"


# ====================================================================
#                            HOLATLAR (FSM)
# ====================================================================
class UserSearch(StatesGroup):
    q = State()


class AdminFind(StatesGroup):
    query = State()


class AddDrama(StatesGroup):
    name = State()
    year = State()
    genre = State()


class AddEp(StatesGroup):
    videos = State()


class EditDrama(StatesGroup):
    value = State()


class PostFlow(StatesGroup):
    media = State()
    caption = State()
    channels = State()


class OwnerAddAdmin(StatesGroup):
    uid = State()


class OwnerAddChannel(StatesGroup):
    ref = State()


class OwnerCaption(StatesGroup):
    text = State()


# ====================================================================
#                 BAZA (Postgres yoki SQLite) — bitta interfeys
# ====================================================================
SCHEMA_SQLITE = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, lang TEXT);
CREATE TABLE IF NOT EXISTS admins(id INTEGER PRIMARY KEY);
CREATE TABLE IF NOT EXISTS channels(id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER, title TEXT, link TEXT, kind TEXT);
CREATE TABLE IF NOT EXISTS dramas(id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, year TEXT, genre TEXT);
CREATE TABLE IF NOT EXISTS episodes(id INTEGER PRIMARY KEY AUTOINCREMENT, drama_id INTEGER, num INTEGER, file_id TEXT, kind TEXT);
CREATE TABLE IF NOT EXISTS favorites(id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, drama_id INTEGER, UNIQUE(user_id, drama_id));
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS fsm(k TEXT PRIMARY KEY, state TEXT, data TEXT);
CREATE INDEX IF NOT EXISTS idx_ep ON episodes(drama_id, num);
"""

SCHEMA_PG = """
CREATE TABLE IF NOT EXISTS users(id BIGINT PRIMARY KEY, lang TEXT);
CREATE TABLE IF NOT EXISTS admins(id BIGINT PRIMARY KEY);
CREATE TABLE IF NOT EXISTS channels(id BIGSERIAL PRIMARY KEY, chat_id BIGINT, title TEXT, link TEXT, kind TEXT);
CREATE TABLE IF NOT EXISTS dramas(id BIGSERIAL PRIMARY KEY, name TEXT, year TEXT, genre TEXT);
CREATE TABLE IF NOT EXISTS episodes(id BIGSERIAL PRIMARY KEY, drama_id BIGINT, num INTEGER, file_id TEXT, kind TEXT);
CREATE TABLE IF NOT EXISTS favorites(id BIGSERIAL PRIMARY KEY, user_id BIGINT, drama_id BIGINT, UNIQUE(user_id, drama_id));
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS fsm(k TEXT PRIMARY KEY, state TEXT, data TEXT);
CREATE INDEX IF NOT EXISTS idx_ep ON episodes(drama_id, num);
"""


def _pgsql(sql: str) -> str:
    """'?' belgilarini $1, $2... ga almashtiradi."""
    out, n = [], 0
    for ch in sql:
        if ch == "?":
            n += 1
            out.append(f"${n}")
        else:
            out.append(ch)
    return "".join(out)


async def init_db():
    global db, pg
    if USE_PG:
        if asyncpg is None:
            raise SystemExit("asyncpg o'rnatilmagan: pip install asyncpg")
        pg = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=5, statement_cache_size=0)
        await pg.execute(SCHEMA_PG)
        log.info("Baza: PostgreSQL (doimiy)")
    else:
        if aiosqlite is None:
            raise SystemExit("aiosqlite o'rnatilmagan: pip install aiosqlite")
        db = await aiosqlite.connect(DB_PATH)
        db.row_factory = aiosqlite.Row
        await db.executescript(SCHEMA_SQLITE)
        await db.commit()
        log.info("Baza: SQLite (%s)", DB_PATH)
        if os.getenv("RENDER"):
            log.warning("⚠️ Render'da SQLite fayli har restartda o'chadi! DATABASE_URL (Neon/Supabase) bering.")
    await q_exec("INSERT INTO settings(key, value) VALUES('caption', ?) ON CONFLICT DO NOTHING", (DEFAULT_CAPTION,))


async def close_db():
    if pg:
        await pg.close()
    if db:
        await db.close()


async def q_all(sql, args=()):
    if USE_PG:
        return await pg.fetch(_pgsql(sql), *args)
    async with db.execute(sql, args) as cur:
        return await cur.fetchall()


async def q_one(sql, args=()):
    if USE_PG:
        return await pg.fetchrow(_pgsql(sql), *args)
    async with db.execute(sql, args) as cur:
        return await cur.fetchone()


async def q_exec(sql, args=()):
    if USE_PG:
        await pg.execute(_pgsql(sql), *args)
        return None
    cur = await db.execute(sql, args)
    await db.commit()
    return cur.lastrowid


async def q_insert(sql, args=()):
    """INSERT qilib, yangi qator ID sini qaytaradi."""
    if USE_PG:
        return await pg.fetchval(_pgsql(sql) + " RETURNING id", *args)
    return await q_exec(sql, args)


# ====================================================================
#            FSM HOLATLARINI BAZADA SAQLASH (restartda yo'qolmaydi)
# ====================================================================
class DBStorage(BaseStorage):
    @staticmethod
    def _k(key: StorageKey) -> str:
        return f"{key.bot_id}:{key.chat_id}:{key.user_id}:{getattr(key, 'thread_id', None)}:{key.destiny}"

    async def set_state(self, key: StorageKey, state=None) -> None:
        s = state.state if isinstance(state, State) else state
        await q_exec(
            "INSERT INTO fsm(k, state, data) VALUES(?, ?, '{}') ON CONFLICT(k) DO UPDATE SET state=excluded.state",
            (self._k(key), s),
        )

    async def get_state(self, key: StorageKey):
        r = await q_one("SELECT state FROM fsm WHERE k=?", (self._k(key),))
        return r["state"] if r else None

    async def set_data(self, key: StorageKey, data) -> None:
        k = self._k(key)
        if not data:
            await q_exec("UPDATE fsm SET data='{}' WHERE k=?", (k,))
            await q_exec("DELETE FROM fsm WHERE k=? AND state IS NULL", (k,))
            return
        await q_exec(
            "INSERT INTO fsm(k, state, data) VALUES(?, NULL, ?) ON CONFLICT(k) DO UPDATE SET data=excluded.data",
            (k, json.dumps(data)),
        )

    async def get_data(self, key: StorageKey):
        r = await q_one("SELECT data FROM fsm WHERE k=?", (self._k(key),))
        try:
            return json.loads(r["data"]) if r and r["data"] else {}
        except Exception:
            return {}

    async def close(self) -> None:
        return None


# ====================================================================
#                           YORDAMCHI FUNKSIYALAR
# ====================================================================
def btn(text, cb=None, style=None, url=None):
    """Rangli tugma: style = primary (ko'k) | success (yashil) | danger (qizil)."""
    if style and COLORED:
        return InlineKeyboardButton(text=text, callback_data=cb, url=url, style=style)
    return InlineKeyboardButton(text=text, callback_data=cb, url=url)


def kb(rows):
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def show(ev, text, markup=None):
    """Callback bo'lsa xabarni tahrirlaydi (iloji bo'lmasa o'chirib qayta yuboradi), bo'lmasa yangi xabar."""
    if isinstance(ev, CallbackQuery):
        msg = ev.message
        if isinstance(msg, Message):  # InaccessibleMessage bo'lmasa
            try:
                await msg.edit_text(text, reply_markup=markup)
                return
            except TelegramBadRequest as e:
                if "not modified" in str(e):
                    return
            try:
                await msg.delete()
            except Exception:
                pass
        await ev.bot.send_message(ev.from_user.id, text, reply_markup=markup)
    else:
        await ev.answer(text, reply_markup=markup)


async def load_admins():
    ADMINS.clear()
    for r in await q_all("SELECT id FROM admins"):
        ADMINS.add(r["id"])


async def is_admin(uid: int) -> bool:
    return uid == OWNER_ID or uid in ADMINS


async def user_lang(uid: int):
    if uid in LANG_CACHE:
        return LANG_CACHE[uid]
    r = await q_one("SELECT lang FROM users WHERE id=?", (uid,))
    if r and r["lang"] in T:
        LANG_CACHE[uid] = r["lang"]
        return r["lang"]
    return None


async def get_lang(uid: int) -> str:
    return await user_lang(uid) or "uz"


async def get_drama(did: int):
    return await q_one("SELECT * FROM dramas WHERE id=?", (did,))


async def find_dramas(text: str):
    text = text.strip()
    if text.isdigit():
        r = await q_all("SELECT * FROM dramas WHERE id=?", (int(text),))
        if r:
            return r
    low = text.casefold()
    rows = await q_all("SELECT * FROM dramas ORDER BY id")
    return [r for r in rows if low in r["name"].casefold()]


async def load_stickers(bot: Bot):
    for name in STICKER_SETS:
        try:
            s = await bot.get_sticker_set(name)
            STICKERS.extend(st.file_id for st in s.stickers)
        except Exception as e:
            log.warning("Stiker to'plami olinmadi (%s): %s", name, e)


async def send_sticker(bot: Bot, chat_id: int):
    if STICKERS:
        try:
            await bot.send_sticker(chat_id, random.choice(STICKERS))
        except Exception:
            pass


async def render_caption(d) -> str:
    row = await q_one("SELECT value FROM settings WHERE key='caption'")
    tpl = row["value"] if row else DEFAULT_CAPTION
    return (
        tpl.replace("{nomi}", esc(d["name"]))
        .replace("{yili}", esc(d["year"]))
        .replace("{kodi}", str(d["id"]))
        .replace("{janri}", T["uz"]["g_" + d["genre"]])
    )


# ====================================================================
#                         MAJBURIY OBUNA
# ====================================================================
async def notify_owner(bot: Bot, text: str):
    try:
        await bot.send_message(OWNER_ID, text)
    except Exception:
        pass


async def _is_member(bot: Bot, chat_id: int, uid: int) -> bool:
    try:
        m = await bot.get_chat_member(chat_id, uid)
        return m.status in (
            ChatMemberStatus.CREATOR,
            ChatMemberStatus.ADMINISTRATOR,
            ChatMemberStatus.MEMBER,
        ) or (m.status == ChatMemberStatus.RESTRICTED and getattr(m, "is_member", False))
    except Exception as e:
        log.warning("Obunani tekshirib bo'lmadi (chat %s): %s", chat_id, e)
        now = asyncio.get_event_loop().time()
        if now - NOTIFIED.get(chat_id, -1e9) > 3600:  # owner'ga soatiga 1 marta xabar
            NOTIFIED[chat_id] = now
            spawn(
                notify_owner(
                    bot,
                    f"⚠️ <b>Majburiy obuna kanalini tekshirib bo'lmadi</b> (chat_id: <code>{chat_id}</code>)\n"
                    "Bot kanalda admin ekanligini tekshiring yoki kanalni ro'yxatdan o'chiring.\n"
                    f"Sabab: <code>{esc(str(e))}</code>\n\n"
                    + ("Hozircha bu kanal bo'yicha tekshiruv o'tkazib yuborilmoqda." if SUB_FAIL_OPEN else "Foydalanuvchilar vaqtincha bloklanmoqda."),
                )
            )
        return SUB_FAIL_OPEN


async def not_joined(bot: Bot, uid: int, force: bool = False):
    now = asyncio.get_event_loop().time()
    if not force and now - JOINED_CACHE.get(uid, -1e9) < SUB_CACHE_SECONDS:
        return []
    chans = await q_all("SELECT * FROM channels WHERE kind='sub'")
    if not chans:
        return []
    res = await asyncio.gather(*[_is_member(bot, ch["chat_id"], uid) for ch in chans])
    missing = [ch for ch, ok in zip(chans, res) if not ok]
    if not missing:
        JOINED_CACHE[uid] = now
    else:
        JOINED_CACHE.pop(uid, None)
    return missing


def sub_kb(lang, missing):
    rows = [[btn("📢 " + ch["title"], url=ch["link"], style="primary")] for ch in missing]
    rows.append([btn(T[lang]["b_check"], "check_sub", "success")])
    return kb(rows)


async def send_sub_prompt(bot: Bot, chat_id: int, lang: str, missing):
    await bot.send_message(chat_id, T[lang]["sub_title"], reply_markup=sub_kb(lang, missing))


class SubMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        user = data.get("event_from_user")
        bot: Bot = data["bot"]
        if user is None or user.is_bot:
            return await handler(event, data)
        if isinstance(event, Message):
            if event.chat.type != "private":
                return await handler(event, data)
            if event.text and event.text.startswith(("/start", "/til")):
                return await handler(event, data)
        elif isinstance(event, CallbackQuery):
            d = event.data or ""
            if d == "check_sub" or d.startswith("lang:"):
                return await handler(event, data)
        if await is_admin(user.id):
            return await handler(event, data)
        lang = await user_lang(user.id)
        if not lang:
            return await handler(event, data)
        missing = await not_joined(bot, user.id)
        if not missing:
            return await handler(event, data)
        await send_sub_prompt(bot, user.id, lang, missing)
        if isinstance(event, CallbackQuery):
            await event.answer()
        return None


# ====================================================================
#                            FILTRLAR
# ====================================================================
class IsAdmin(BaseFilter):
    async def __call__(self, event) -> bool:
        u = getattr(event, "from_user", None)
        return bool(u) and await is_admin(u.id)


class IsOwner(BaseFilter):
    async def __call__(self, event) -> bool:
        u = getattr(event, "from_user", None)
        return bool(u) and u.id == OWNER_ID


TXT = F.text & ~F.text.startswith("/")  # buyruqlar (/start, /admin) holat kiritishi bo'lib ketmasin

owner_r = Router()
admin_r = Router()
user_r = Router()
owner_r.message.filter(IsOwner())
owner_r.callback_query.filter(IsOwner())
admin_r.message.filter(IsAdmin())
admin_r.callback_query.filter(IsAdmin())


# ====================================================================
#                          FOYDALANUVCHI QISMI
# ====================================================================
def lang_kb():
    return kb(
        [
            [btn("🇺🇿 O'zbekcha", "lang:uz", "primary")],
            [btn("🇷🇺 Русский", "lang:ru", "success")],
            [btn("🇬🇧 English", "lang:en", "danger")],
        ]
    )


def menu_kb(lang):
    t = T[lang]
    return kb(
        [
            [btn(t["b_search"], "m:search", "primary")],
            [btn(t["b_genre"], "m:genre", "success")],
            [btn(t["b_fav"], "m:fav", "danger")],
        ]
    )


async def card_view(did: int, lang: str, uid: int, page: int = 0):
    d = await get_drama(did)
    if not d:
        return None
    t = T[lang]
    eps = await q_all("SELECT id, num FROM episodes WHERE drama_id=? ORDER BY num", (did,))
    text = t["card"].format(name=esc(d["name"]), year=esc(d["year"]), id=d["id"], genre=t["g_" + d["genre"]], n=len(eps))
    text += t["choose_ep"] if eps else t["no_eps"]
    pages = max(1, ceil(len(eps) / EP_PAGE))
    page = max(0, min(page, pages - 1))
    chunk = eps[page * EP_PAGE:(page + 1) * EP_PAGE]
    rows = []
    for i in range(0, len(chunk), 5):
        rows.append([btn(str(e["num"]), f"ep:{e['id']}", "primary") for e in chunk[i:i + 5]])
    if pages > 1:
        nav = []
        if page > 0:
            nav.append(btn("⬅️", f"dp:{did}:{page - 1}"))
        nav.append(btn(f"{page + 1}/{pages}", "noop"))
        if page < pages - 1:
            nav.append(btn("➡️", f"dp:{did}:{page + 1}"))
        rows.append(nav)
    fav = await q_one("SELECT 1 FROM favorites WHERE user_id=? AND drama_id=?", (uid, did))
    rows.append([btn(t["b_fav_del"] if fav else t["b_fav_add"], f"fav:{did}:{page}", "danger" if fav else "success")])
    rows.append([btn(t["b_home"], "m:menu")])
    return text, kb(rows)


def list_kb(lang, rows, page, prefix, back_cb):
    total = max(1, ceil(len(rows) / LIST_PAGE))
    page = max(0, min(page, total - 1))
    chunk = rows[page * LIST_PAGE:(page + 1) * LIST_PAGE]
    out = [[btn(f"🎬 {r['name']} • {r['year']} • #{r['id']}", f"d:{r['id']}", "primary")] for r in chunk]
    if total > 1:
        nav = []
        if page > 0:
            nav.append(btn("⬅️", f"{prefix}:{page - 1}"))
        nav.append(btn(f"{page + 1}/{total}", "noop"))
        if page < total - 1:
            nav.append(btn("➡️", f"{prefix}:{page + 1}"))
        out.append(nav)
    out.append([btn(T[lang]["b_back"], back_cb)])
    return kb(out)


async def proceed(bot: Bot, chat_id: int, uid: int, name: str, lang: str, state: FSMContext):
    """Obuna tasdiqlangach: deep-link bo'lsa dramani, aks holda menyuni ko'rsatadi."""
    data = await state.get_data()
    pending = data.get("pending")
    if pending:
        await state.update_data(pending=None)
        if pending.startswith("drama_") and pending[6:].isdigit():
            v = await card_view(int(pending[6:]), lang, uid)
            if v:
                await bot.send_message(chat_id, v[0], reply_markup=v[1])
                return
    await send_sticker(bot, chat_id)
    await bot.send_message(chat_id, T[lang]["welcome"].format(name=esc(name)), reply_markup=menu_kb(lang))


@user_r.message(CommandStart())
async def cmd_start(m: Message, state: FSMContext, command: CommandObject, bot: Bot):
    uid = m.from_user.id
    await state.clear()
    if command.args:
        await state.update_data(pending=command.args)
    lang = await user_lang(uid)
    if not lang:
        await q_exec("INSERT INTO users(id, lang) VALUES(?, NULL) ON CONFLICT DO NOTHING", (uid,))
        await send_sticker(bot, m.chat.id)
        await m.answer(PICK_LANG, reply_markup=lang_kb())
        return
    if not await is_admin(uid):
        missing = await not_joined(bot, uid)
        if missing:
            await send_sub_prompt(bot, m.chat.id, lang, missing)
            return
    await proceed(bot, m.chat.id, uid, m.from_user.first_name, lang, state)


@user_r.message(Command("til"))
async def cmd_til(m: Message):
    await m.answer(PICK_LANG, reply_markup=lang_kb())


@user_r.callback_query(F.data.startswith("lang:"))
async def cb_lang(c: CallbackQuery, state: FSMContext, bot: Bot):
    lang = c.data.split(":")[1]
    if lang not in T:
        return await c.answer()
    uid = c.from_user.id
    await q_exec("INSERT INTO users(id, lang) VALUES(?, ?) ON CONFLICT(id) DO UPDATE SET lang=excluded.lang", (uid, lang))
    LANG_CACHE[uid] = lang
    try:
        await c.message.delete()
    except Exception:
        pass
    await c.answer("✅")
    if not await is_admin(uid):
        missing = await not_joined(bot, uid, force=True)
        if missing:
            await send_sub_prompt(bot, uid, lang, missing)
            return
    await proceed(bot, uid, uid, c.from_user.first_name, lang, state)


@user_r.callback_query(F.data == "check_sub")
async def cb_check_sub(c: CallbackQuery, state: FSMContext, bot: Bot):
    uid = c.from_user.id
    lang = await get_lang(uid)
    missing = [] if await is_admin(uid) else await not_joined(bot, uid, force=True)
    if missing:
        await c.answer(T[lang]["not_yet"], show_alert=True)
        try:
            await c.message.edit_reply_markup(reply_markup=sub_kb(lang, missing))
        except Exception:
            pass
        return
    try:
        await c.message.delete()
    except Exception:
        pass
    await c.answer("✅")
    await proceed(bot, uid, uid, c.from_user.first_name, lang, state)


@user_r.callback_query(F.data == "noop")
async def cb_noop(c: CallbackQuery):
    await c.answer()


@user_r.callback_query(F.data == "m:menu")
async def cb_menu(c: CallbackQuery, state: FSMContext):
    await state.set_state(None)
    lang = await get_lang(c.from_user.id)
    await show(c, T[lang]["menu_title"], menu_kb(lang))
    await c.answer()


# ---------- Izlash ----------
@user_r.callback_query(F.data == "m:search")
async def cb_search(c: CallbackQuery, state: FSMContext):
    lang = await get_lang(c.from_user.id)
    await state.set_state(UserSearch.q)
    await show(c, T[lang]["ask_search"], kb([[btn(T[lang]["b_back"], "m:menu", "danger")]]))
    await c.answer()


@user_r.message(UserSearch.q, TXT)
async def do_search(m: Message, state: FSMContext):
    lang = await get_lang(m.from_user.id)
    rows = await find_dramas(m.text)
    back = kb([[btn(T[lang]["b_back"], "m:menu", "danger")]])
    if not rows:
        return await m.answer(T[lang]["nf"], reply_markup=back)
    if len(rows) == 1:
        text, markup = await card_view(rows[0]["id"], lang, m.from_user.id)
        return await m.answer(text, reply_markup=markup)
    await state.update_data(sq=m.text.strip())
    await m.answer("🔎 " + T[lang]["b_search"] + ":", reply_markup=list_kb(lang, rows, 0, "s", "m:menu"))


@user_r.callback_query(F.data.regexp(r"^s:\d+$"))
async def cb_search_page(c: CallbackQuery, state: FSMContext):
    lang = await get_lang(c.from_user.id)
    data = await state.get_data()
    sq = data.get("sq")
    if not sq:
        return await c.answer()
    rows = await find_dramas(sq)
    if not rows:
        return await c.answer(T[lang]["nf"], show_alert=True)
    await show(c, "🔎 " + T[lang]["b_search"] + ":", list_kb(lang, rows, int(c.data.split(":")[1]), "s", "m:menu"))
    await c.answer()


# ---------- Janr ----------
@user_r.callback_query(F.data == "m:genre")
async def cb_genre_menu(c: CallbackQuery, state: FSMContext):
    await state.set_state(None)
    lang = await get_lang(c.from_user.id)
    t = T[lang]
    markup = kb(
        [
            [btn(t["g_action"], "g:action:0", "danger")],
            [btn(t["g_romance"], "g:romance:0", "success")],
            [btn(t["b_back"], "m:menu")],
        ]
    )
    await show(c, t["choose_genre"], markup)
    await c.answer()


@user_r.callback_query(F.data.startswith("g:"))
async def cb_genre_list(c: CallbackQuery):
    _, g, page = c.data.split(":")
    if g not in GENRES:
        return await c.answer()
    lang = await get_lang(c.from_user.id)
    rows = await q_all("SELECT * FROM dramas WHERE genre=? ORDER BY id", (g,))
    if not rows:
        await show(c, T[lang]["empty"], kb([[btn(T[lang]["b_back"], "m:genre")]]))
    else:
        await show(c, f"<b>{T[lang]['g_' + g]}</b>", list_kb(lang, rows, int(page), f"g:{g}", "m:genre"))
    await c.answer()


# ---------- Sevimlilar ----------
async def fav_view(c: CallbackQuery, page: int):
    lang = await get_lang(c.from_user.id)
    rows = await q_all(
        "SELECT d.* FROM dramas d JOIN favorites f ON f.drama_id=d.id WHERE f.user_id=? ORDER BY f.id DESC",
        (c.from_user.id,),
    )
    if not rows:
        await show(c, T[lang]["fav_empty"], kb([[btn(T[lang]["b_back"], "m:menu")]]))
    else:
        await show(c, T[lang]["fav_title"], list_kb(lang, rows, page, "f", "m:menu"))
    await c.answer()


@user_r.callback_query(F.data == "m:fav")
async def cb_fav_menu(c: CallbackQuery, state: FSMContext):
    await state.set_state(None)
    await fav_view(c, 0)


@user_r.callback_query(F.data.regexp(r"^f:\d+$"))
async def cb_fav_page(c: CallbackQuery):
    await fav_view(c, int(c.data.split(":")[1]))


@user_r.callback_query(F.data.startswith("fav:"))
async def cb_fav_toggle(c: CallbackQuery):
    _, did, page = c.data.split(":")
    did, page = int(did), int(page)
    uid = c.from_user.id
    lang = await get_lang(uid)
    exists = await q_one("SELECT 1 FROM favorites WHERE user_id=? AND drama_id=?", (uid, did))
    if exists:
        await q_exec("DELETE FROM favorites WHERE user_id=? AND drama_id=?", (uid, did))
        await c.answer(T[lang]["fav_removed"])
    else:
        await q_exec("INSERT INTO favorites(user_id, drama_id) VALUES(?, ?) ON CONFLICT DO NOTHING", (uid, did))
        await c.answer(T[lang]["fav_added"])
    v = await card_view(did, lang, uid, page)
    if v:
        try:
            await c.message.edit_reply_markup(reply_markup=v[1])
        except Exception:
            pass


# ---------- Drama kartasi va qismlar ----------
@user_r.callback_query(F.data.regexp(r"^d:\d+$"))
async def cb_drama(c: CallbackQuery):
    lang = await get_lang(c.from_user.id)
    v = await card_view(int(c.data.split(":")[1]), lang, c.from_user.id)
    if not v:
        await c.answer(T[lang]["gone"], show_alert=True)
        return
    await show(c, v[0], v[1])
    await c.answer()


@user_r.callback_query(F.data.startswith("dp:"))
async def cb_drama_page(c: CallbackQuery):
    _, did, page = c.data.split(":")
    lang = await get_lang(c.from_user.id)
    v = await card_view(int(did), lang, c.from_user.id, int(page))
    if v:
        try:
            await c.message.edit_reply_markup(reply_markup=v[1])
        except Exception:
            pass
    await c.answer()


@user_r.callback_query(F.data.regexp(r"^ep:\d+$"))
async def cb_episode(c: CallbackQuery, bot: Bot):
    # Tugma qism ID siga bog'langan — qism o'chirilib raqamlar siljisa ham eski tugmalar to'g'ri ishlaydi
    eid = int(c.data.split(":")[1])
    lang = await get_lang(c.from_user.id)
    t = T[lang]
    ep = await q_one("SELECT * FROM episodes WHERE id=?", (eid,))
    d = await get_drama(ep["drama_id"]) if ep else None
    if not ep or not d:
        return await c.answer(t["gone"], show_alert=True)
    did, num = ep["drama_id"], ep["num"]
    prev_ep = await q_one("SELECT id FROM episodes WHERE drama_id=? AND num=?", (did, num - 1))
    next_ep = await q_one("SELECT id FROM episodes WHERE drama_id=? AND num=?", (did, num + 1))
    nav = []
    if prev_ep:
        nav.append(btn(f"⬅️ {num - 1}", f"ep:{prev_ep['id']}", "primary"))
    if next_ep:
        nav.append(btn(f"{num + 1} ➡️", f"ep:{next_ep['id']}", "success"))
    rows = []
    if nav:
        rows.append(nav)
    rows.append([btn(t["b_eps"], f"d:{did}")])
    caption = t["ep_cap"].format(name=esc(d["name"]), num=num)
    chat_id = c.from_user.id
    if ep["kind"] == "document":
        await bot.send_document(chat_id, ep["file_id"], caption=caption, reply_markup=kb(rows))
    else:
        await bot.send_video(chat_id, ep["file_id"], caption=caption, reply_markup=kb(rows))
    await c.answer()


# ====================================================================
#                              ADMIN PANEL
# ====================================================================
def cancel_kb():
    return kb([[btn("🔙 Bekor qilish", "a:cancel", "danger")]])


def panel_btn():
    return kb([[btn("🛠 Panel", "a:panel", "primary")]])


def done_kb():
    return kb([[btn("✅ Tugatish", "a:done", "success")]])


def panel_kb(uid):
    rows = [
        [btn("➕ Drama qo'shish", "a:adddrama", "success"), btn("🗑 Drama o'chirish", "a:deldrama", "danger")],
        [btn("🎞 Qism qo'shish", "a:addep", "success"), btn("❌ Qism o'chirish", "a:delep", "danger")],
        [btn("✏️ Drama tahrirlash", "a:edit", "primary")],
        [btn("📣 Post qilish", "a:post", "primary")],
    ]
    if uid == OWNER_ID:
        rows += [
            [btn("👤 Admin qo'shish", "o:addadmin", "success"), btn("🚫 Admin o'chirish", "o:deladmin", "danger")],
            [btn("📢 Post kanal qo'shish", "o:addpost", "success")],
            [btn("🔔 Majburiy obuna qo'shish", "o:addsub", "success")],
            [btn("🗂 Kanallar ro'yxati", "o:channels", "primary")],
            [btn("📝 Post captionini o'zgartirish", "o:caption", "primary")],
        ]
    return kb(rows)


def panel_title(uid):
    return "👑 <b>Owner paneli</b>" if uid == OWNER_ID else "🛠 <b>Admin paneli</b>"


@admin_r.message(Command("admin"))
async def cmd_admin(m: Message, state: FSMContext):
    await state.clear()
    await m.answer(panel_title(m.from_user.id), reply_markup=panel_kb(m.from_user.id))


@admin_r.callback_query(F.data.in_(("a:cancel", "a:panel")))
async def a_cancel(c: CallbackQuery, state: FSMContext):
    await state.clear()
    await show(c, panel_title(c.from_user.id), panel_kb(c.from_user.id))
    await c.answer()


# ---------- Drama qo'shish ----------
@admin_r.callback_query(F.data == "a:adddrama")
async def a_add_drama(c: CallbackQuery, state: FSMContext):
    await state.clear()
    await state.set_state(AddDrama.name)
    await show(c, "🎬 <b>Drama nomini yuboring:</b>", cancel_kb())
    await c.answer()


@admin_r.message(AddDrama.name, TXT)
async def ad_name(m: Message, state: FSMContext):
    await state.update_data(name=m.text.strip())
    await state.set_state(AddDrama.year)
    await m.answer("📅 <b>Drama yilini yuboring:</b>", reply_markup=cancel_kb())


@admin_r.message(AddDrama.year, TXT)
async def ad_year(m: Message, state: FSMContext):
    await state.update_data(year=m.text.strip()[:20])
    await state.set_state(AddDrama.genre)
    await m.answer(
        "🎭 <b>Drama janrini tanlang:</b>",
        reply_markup=kb(
            [
                [btn(T["uz"]["g_action"], "ag:action", "danger"), btn(T["uz"]["g_romance"], "ag:romance", "success")],
                [btn("🔙 Bekor qilish", "a:cancel")],
            ]
        ),
    )


@admin_r.callback_query(AddDrama.genre, F.data.startswith("ag:"))
async def ad_genre(c: CallbackQuery, state: FSMContext):
    g = c.data.split(":")[1]
    if g not in GENRES:
        return await c.answer()
    data = await state.get_data()
    did = await q_insert("INSERT INTO dramas(name, year, genre) VALUES(?, ?, ?)", (data["name"], data["year"], g))
    await state.clear()
    text = (
        "✅ <b>Drama qo'shildi!</b>\n\n"
        f"🎬 Nomi: <b>{esc(data['name'])}</b>\n📅 Yili: <b>{esc(data['year'])}</b>\n"
        f"🔢 Kodi: <b>{did}</b>\n🎭 Janri: <b>{T['uz']['g_' + g]}</b>"
    )
    await show(c, text, kb([[btn("🎞 Qism qo'shish", f"adde:{did}", "success")], [btn("🛠 Panel", "a:panel", "primary")]]))
    await c.answer()


@admin_r.callback_query(F.data.startswith("adde:"))
async def a_add_ep_quick(c: CallbackQuery, state: FSMContext):
    await state.clear()
    await state.update_data(action="addep")
    await run_action(c, state, int(c.data.split(":")[1]))
    await c.answer()


# ---------- Drama topish (umumiy) ----------
ACTIONS = {
    "a:addep": "addep",
    "a:deldrama": "deldrama",
    "a:delep": "delep",
    "a:edit": "edit",
    "a:post": "post",
}


@admin_r.callback_query(F.data.in_(tuple(ACTIONS)))
async def a_find(c: CallbackQuery, state: FSMContext):
    await state.clear()
    await state.set_state(AdminFind.query)
    await state.update_data(action=ACTIONS[c.data])
    await show(c, "🔎 <b>Drama ID raqamini yoki nomini yuboring:</b>", cancel_kb())
    await c.answer()


@admin_r.message(AdminFind.query, TXT)
async def a_find_q(m: Message, state: FSMContext):
    rows = await find_dramas(m.text)
    if not rows:
        return await m.answer("😔 Topilmadi. ID yoki nomni qayta yuboring:", reply_markup=cancel_kb())
    if len(rows) == 1:
        return await run_action(m, state, rows[0]["id"])
    out = [[btn(f"🎬 {r['name']} • #{r['id']}", f"pick:{r['id']}", "primary")] for r in rows[:30]]
    out.append([btn("🔙 Bekor qilish", "a:cancel", "danger")])
    note = "Quyidagilardan birini tanlang:" if len(rows) <= 30 else f"Ko'p natija ({len(rows)} ta), dastlabki 30 tasi. Aniqroq nom yoki ID yozing:"
    await m.answer(note, reply_markup=kb(out))


@admin_r.callback_query(AdminFind.query, F.data.startswith("pick:"))
async def a_pick(c: CallbackQuery, state: FSMContext):
    await run_action(c, state, int(c.data.split(":")[1]))
    await c.answer()


async def ep_del_view(ev, did: int, page: int = 0):
    d = await get_drama(did)
    if not d:
        return await show(ev, "❌ Drama topilmadi.", panel_btn())
    eps = await q_all("SELECT id, num FROM episodes WHERE drama_id=? ORDER BY num", (did,))
    if not eps:
        return await show(ev, f"🎬 <b>{esc(d['name'])}</b>\n\n😔 Qismlar yo'q.", panel_btn())
    pages = max(1, ceil(len(eps) / EP_PAGE))
    page = max(0, min(page, pages - 1))
    chunk = eps[page * EP_PAGE:(page + 1) * EP_PAGE]
    rows = [[btn(f"❌ {e['num']}", f"dele:{e['id']}:{page}", "danger") for e in chunk[i:i + 5]] for i in range(0, len(chunk), 5)]
    if pages > 1:
        nav = []
        if page > 0:
            nav.append(btn("⬅️", f"delp:{did}:{page - 1}"))
        nav.append(btn(f"{page + 1}/{pages}", "noop"))
        if page < pages - 1:
            nav.append(btn("➡️", f"delp:{did}:{page + 1}"))
        rows.append(nav)
    rows.append([btn("🛠 Panel", "a:panel", "primary")])
    await show(ev, f"🎬 <b>{esc(d['name'])}</b> — {len(eps)} ta qism\n\n🗑 O'chiriladigan qismni tanlang:", kb(rows))


async def run_action(ev, state: FSMContext, did: int):
    data = await state.get_data()
    action = data.get("action")
    d = await get_drama(did)
    if not d:
        return await show(ev, "❌ Drama topilmadi.", panel_btn())
    name = esc(d["name"])

    if action == "addep":
        r = await q_one("SELECT COALESCE(MAX(num),0) AS m FROM episodes WHERE drama_id=?", (did,))
        await state.set_state(AddEp.videos)
        await state.update_data(drama_id=did)
        await show(
            ev,
            f"🎞 <b>{name}</b> (kod: {did})\nHozirgi qismlar: <b>{r['m']}</b> ta\n\n"
            f"📹 Videolarni yuboring — <b>{r['m'] + 1}-qismdan</b> boshlab avtomatik raqamlanadi.\n"
            "Ko'p video birdaniga tashlansa ham, yuborilgan tartibi bo'yicha saqlanadi.\n"
            "Tugagach «✅ Tugatish» tugmasini bosing.",
            done_kb(),
        )
    elif action == "deldrama":
        await show(
            ev,
            f"🗑 <b>{name}</b> (kod: {did}) dramasi barcha qismlari bilan o'chiriladi.\n\nIshonchingiz komilmi?",
            kb([[btn("✅ Ha, o'chirish", f"deld:{did}", "danger"), btn("🔙 Yo'q", "a:cancel", "primary")]]),
        )
    elif action == "delep":
        await state.set_state(None)
        await ep_del_view(ev, did, 0)
    elif action == "edit":
        await state.set_state(None)
        await show(
            ev,
            f"✏️ <b>{name}</b> (kod: {did})\n\nNimani o'zgartirmoqchisiz?",
            kb(
                [
                    [btn("📝 Nomi", f"ef:{did}:name", "primary"), btn("📅 Yili", f"ef:{did}:year", "primary")],
                    [btn("🎭 Janri", f"ef:{did}:genre", "primary")],
                    [btn("🔙 Bekor qilish", "a:cancel", "danger")],
                ]
            ),
        )
    elif action == "post":
        await state.set_state(PostFlow.media)
        await state.update_data(drama_id=did, sel=[])
        await show(ev, f"🎬 <b>{name}</b> (kod: {did})\n\n🖼 Post uchun <b>rasm yoki video</b> yuboring:", cancel_kb())


# ---------- Qism qo'shish (message_id bo'yicha tartiblab saqlanadi) ----------
async def save_ep_batch(bot: Bot, chat_id: int):
    buf = EP_BUF.pop(chat_id, None)
    if not buf or not buf["items"]:
        return
    items = sorted(buf["items"], key=lambda x: x[0])  # xabar ID si bo'yicha — yuborilgan tartib
    did = buf["did"]
    async with EP_LOCK:
        r = await q_one("SELECT COALESCE(MAX(num),0) AS m FROM episodes WHERE drama_id=?", (did,))
        n = r["m"]
        first = n + 1
        for _, fid, kind in items:
            n += 1
            await q_exec("INSERT INTO episodes(drama_id, num, file_id, kind) VALUES(?, ?, ?, ?)", (did, n, fid, kind))
    if len(items) == 1:
        text = f"✅ <b>{first}-qism</b> saqlandi"
    else:
        text = f"✅ <b>{first}–{n}-qismlar</b> saqlandi ({len(items)} ta)"
    try:
        await bot.send_message(chat_id, text, reply_markup=done_kb())
    except Exception:
        pass


async def ep_flush_task(bot: Bot, chat_id: int):
    try:
        loop = asyncio.get_event_loop()
        while True:
            await asyncio.sleep(EP_BATCH_WAIT)
            buf = EP_BUF.get(chat_id)
            if not buf:
                return
            if loop.time() - buf["last"] >= EP_BATCH_WAIT:
                break
        await save_ep_batch(bot, chat_id)
    except Exception:
        log.exception("Qismlarni saqlashda xato")


@admin_r.message(AddEp.videos, F.video | F.document)
async def ep_video(m: Message, state: FSMContext, bot: Bot):
    if m.video:
        file_id, kind = m.video.file_id, "video"
    elif m.document and (m.document.mime_type or "").startswith("video/"):
        file_id, kind = m.document.file_id, "document"
    else:
        return await m.answer("⚠️ Faqat video yuboring.", reply_markup=done_kb())
    data = await state.get_data()
    did = data["drama_id"]
    loop = asyncio.get_event_loop()
    buf = EP_BUF.get(m.chat.id)
    if buf and buf["did"] != did:
        await save_ep_batch(bot, m.chat.id)
        buf = None
    if not buf:
        buf = EP_BUF[m.chat.id] = {"did": did, "items": [], "last": 0.0, "task": None}
    buf["items"].append((m.message_id, file_id, kind))
    buf["last"] = loop.time()
    if buf["task"] is None or buf["task"].done():
        buf["task"] = spawn(ep_flush_task(bot, m.chat.id))


@admin_r.message(AddEp.videos, TXT)
async def ep_video_text(m: Message):
    await m.answer("⚠️ Faqat video yuboring.", reply_markup=done_kb())


@admin_r.callback_query(F.data == "a:done")
async def a_done(c: CallbackQuery, state: FSMContext, bot: Bot):
    await save_ep_batch(bot, c.from_user.id)  # to'planib turgan videolar bo'lsa, darhol saqlaydi
    await state.clear()
    await show(c, "✅ Qismlar saqlandi.\n\n" + panel_title(c.from_user.id), panel_kb(c.from_user.id))
    await c.answer()


# ---------- Drama o'chirish ----------
@admin_r.callback_query(F.data.startswith("deld:"))
async def a_del_drama(c: CallbackQuery, state: FSMContext):
    did = int(c.data.split(":")[1])
    await q_exec("DELETE FROM episodes WHERE drama_id=?", (did,))
    await q_exec("DELETE FROM favorites WHERE drama_id=?", (did,))
    await q_exec("DELETE FROM dramas WHERE id=?", (did,))
    await state.clear()
    await show(c, "✅ Drama o'chirildi.", panel_btn())
    await c.answer()


# ---------- Qism o'chirish (sahifalangan) ----------
@admin_r.callback_query(F.data.startswith("delp:"))
async def a_del_ep_page(c: CallbackQuery):
    _, did, page = c.data.split(":")
    await ep_del_view(c, int(did), int(page))
    await c.answer()


@admin_r.callback_query(F.data.startswith("dele:"))
async def a_del_ep(c: CallbackQuery):
    _, eid, page = c.data.split(":")
    ep = await q_one("SELECT * FROM episodes WHERE id=?", (int(eid),))
    if not ep:
        return await c.answer("Qism allaqachon o'chirilgan", show_alert=True)
    did, num = ep["drama_id"], ep["num"]
    await q_exec("DELETE FROM episodes WHERE id=?", (int(eid),))
    await q_exec("UPDATE episodes SET num=num-1 WHERE drama_id=? AND num>?", (did, num))  # ketma-ketlik buzilmasin
    await c.answer(f"✅ {num}-qism o'chirildi")
    await ep_del_view(c, did, int(page))


# ---------- Drama tahrirlash ----------
@admin_r.callback_query(F.data.startswith("ef:"))
async def a_edit_field(c: CallbackQuery, state: FSMContext):
    _, did, field = c.data.split(":")
    did = int(did)
    if field == "genre":
        await show(
            c,
            "🎭 <b>Yangi janrni tanlang:</b>",
            kb(
                [
                    [btn(T["uz"]["g_action"], f"eg:{did}:action", "danger"), btn(T["uz"]["g_romance"], f"eg:{did}:romance", "success")],
                    [btn("🔙 Bekor qilish", "a:cancel")],
                ]
            ),
        )
    elif field in ("name", "year"):
        await state.set_state(EditDrama.value)
        await state.update_data(did=did, field=field)
        label = "nomini" if field == "name" else "yilini"
        await show(c, f"✍️ Dramaning yangi <b>{label}</b> yuboring:", cancel_kb())
    await c.answer()


@admin_r.callback_query(F.data.startswith("eg:"))
async def a_edit_genre(c: CallbackQuery, state: FSMContext):
    _, did, g = c.data.split(":")
    if g not in GENRES:
        return await c.answer()
    await q_exec("UPDATE dramas SET genre=? WHERE id=?", (g, int(did)))
    await state.clear()
    await show(c, "✅ Janr yangilandi.", panel_btn())
    await c.answer()


@admin_r.message(EditDrama.value, TXT)
async def a_edit_value(m: Message, state: FSMContext):
    data = await state.get_data()
    field = data["field"]
    if field not in ("name", "year"):
        return
    await q_exec(f"UPDATE dramas SET {field}=? WHERE id=?", (m.text.strip(), data["did"]))
    await state.clear()
    await m.answer("✅ Yangilandi.", reply_markup=panel_btn())


# ---------- Post qilish ----------
def watch_kb(did: int):
    return kb([[btn("▶️ Tomosha qilish", url=f"https://t.me/{BOT_USERNAME}?start=drama_{did}", style="success")]])


@admin_r.message(PostFlow.media, F.photo | F.video)
async def post_media(m: Message, state: FSMContext):
    if m.photo:
        mtype, fid = "photo", m.photo[-1].file_id
    else:
        mtype, fid = "video", m.video.file_id
    data = await state.get_data()
    d = await get_drama(data["drama_id"])
    caption = await render_caption(d)
    await state.update_data(mtype=mtype, mfile=fid, caption=caption)
    await state.set_state(PostFlow.caption)
    await m.answer(
        "📝 <b>Caption shu ko'rinishda.</b>\nO'zgartirmoqchi bo'lsangiz to'ldirib yuboring, yoki tasdiqlang:\n\n" + caption,
        reply_markup=kb([[btn("✅ Shunday qoldirish", "pcap_ok", "success")], [btn("🔙 Bekor qilish", "a:cancel", "danger")]]),
    )


@admin_r.message(PostFlow.caption, TXT)
async def post_caption(m: Message, state: FSMContext):
    await state.update_data(caption=m.html_text)
    await post_channels_view(m, state)


@admin_r.callback_query(PostFlow.caption, F.data == "pcap_ok")
async def post_caption_ok(c: CallbackQuery, state: FSMContext):
    await post_channels_view(c, state)
    await c.answer()


async def post_channels_view(ev, state: FSMContext):
    chans = await q_all("SELECT * FROM channels WHERE kind='post'")
    if not chans:
        await state.clear()
        return await show(ev, "❌ Post kanallari yo'q. Owner avval post kanal qo'shishi kerak.", panel_btn())
    data = await state.get_data()
    sel = set(data.get("sel", []))
    rows = [[btn(("✅ " if ch["id"] in sel else "⬜️ ") + ch["title"], f"pc:{ch['id']}", "success" if ch["id"] in sel else None)] for ch in chans]
    rows.append([btn("🚀 Yuborish", "pcs", "primary")])
    rows.append([btn("🔙 Bekor qilish", "a:cancel", "danger")])
    await state.set_state(PostFlow.channels)
    await show(ev, "📢 <b>Qaysi kanallarga yuborilsin?</b>\nKanallarni tanlang, so'ng «🚀 Yuborish» ni bosing:", kb(rows))


@admin_r.callback_query(PostFlow.channels, F.data.startswith("pc:"))
async def post_toggle(c: CallbackQuery, state: FSMContext):
    cid = int(c.data.split(":")[1])
    data = await state.get_data()
    sel = set(data.get("sel", []))
    sel.symmetric_difference_update({cid})
    await state.update_data(sel=list(sel))
    await post_channels_view(c, state)
    await c.answer()


@admin_r.callback_query(PostFlow.channels, F.data == "pcs")
async def post_send(c: CallbackQuery, state: FSMContext, bot: Bot):
    data = await state.get_data()
    sel = data.get("sel", [])
    if not sel:
        return await c.answer("⚠️ Kamida bitta kanal tanlang!", show_alert=True)
    await c.answer("🚀 Yuborilmoqda...")
    ok, fail = 0, []
    for cid in sel:
        ch = await q_one("SELECT * FROM channels WHERE id=?", (cid,))
        if not ch:
            continue
        try:
            if data["mtype"] == "photo":
                await bot.send_photo(ch["chat_id"], data["mfile"], caption=data["caption"], reply_markup=watch_kb(data["drama_id"]))
            else:
                await bot.send_video(ch["chat_id"], data["mfile"], caption=data["caption"], reply_markup=watch_kb(data["drama_id"]))
            ok += 1
        except Exception as e:
            log.warning("Post yuborilmadi (%s): %s", ch["title"], e)
            fail.append(ch["title"])
    await state.clear()
    text = f"✅ Yuborildi: <b>{ok}</b> ta kanal"
    if fail:
        text += "\n❌ Xatolik: " + ", ".join(esc(f) for f in fail) + "\n(Bot kanalda admin ekanligini tekshiring)"
    await show(c, text, panel_btn())


# ====================================================================
#                              OWNER PANELI
# ====================================================================
# ---------- Admin qo'shish / o'chirish ----------
@owner_r.callback_query(F.data == "o:addadmin")
async def o_add_admin(c: CallbackQuery, state: FSMContext):
    await state.clear()
    await state.set_state(OwnerAddAdmin.uid)
    await show(c, "👤 Yangi adminning <b>Telegram ID</b> raqamini yuboring (yoki uning xabarini forward qiling):", cancel_kb())
    await c.answer()


@owner_r.message(OwnerAddAdmin.uid, F.forward_origin | TXT)
async def o_add_admin_id(m: Message, state: FSMContext):
    uid = None
    if m.forward_origin and isinstance(m.forward_origin, MessageOriginUser):
        uid = m.forward_origin.sender_user.id
    elif m.text and m.text.strip().isdigit():
        uid = int(m.text.strip())
    if not uid:
        return await m.answer("⚠️ ID raqam yuboring.", reply_markup=cancel_kb())
    await q_exec("INSERT INTO admins(id) VALUES(?) ON CONFLICT DO NOTHING", (uid,))
    ADMINS.add(uid)
    await state.clear()
    await m.answer(f"✅ <code>{uid}</code> admin qilindi.", reply_markup=panel_btn())


async def admins_view(ev):
    rows = await q_all("SELECT id FROM admins")
    if not rows:
        return await show(ev, "😔 Adminlar yo'q.", panel_btn())
    out = [[btn(f"🗑 {r['id']}", f"dela:{r['id']}", "danger")] for r in rows]
    out.append([btn("🛠 Panel", "a:panel", "primary")])
    await show(ev, "🚫 <b>O'chiriladigan adminni tanlang:</b>", kb(out))


@owner_r.callback_query(F.data == "o:deladmin")
async def o_del_admin(c: CallbackQuery, state: FSMContext):
    await state.clear()
    await admins_view(c)
    await c.answer()


@owner_r.callback_query(F.data.startswith("dela:"))
async def o_del_admin_do(c: CallbackQuery):
    uid = int(c.data.split(":")[1])
    await q_exec("DELETE FROM admins WHERE id=?", (uid,))
    ADMINS.discard(uid)
    await c.answer("✅ O'chirildi")
    await admins_view(c)


# ---------- Kanal qo'shish (post / majburiy obuna) ----------
@owner_r.callback_query(F.data.in_(("o:addpost", "o:addsub")))
async def o_add_channel(c: CallbackQuery, state: FSMContext):
    kind = "post" if c.data == "o:addpost" else "sub"
    await state.clear()
    await state.set_state(OwnerAddChannel.ref)
    await state.update_data(kind=kind)
    title = "📢 Post kanal" if kind == "post" else "🔔 Majburiy obuna kanali"
    await show(
        c,
        f"{title} qo'shish\n\nKanalning <b>@username</b>i, <b>ID</b>si (<code>-100...</code>) ni yuboring yoki kanaldan biror xabarni <b>forward</b> qiling.\n\n"
        "⚠️ Bot avval o'sha kanalga <b>admin</b> qilib qo'shilgan bo'lishi kerak.",
        cancel_kb(),
    )
    await c.answer()


@owner_r.message(OwnerAddChannel.ref, F.forward_origin | TXT)
async def o_add_channel_ref(m: Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    kind = data["kind"]
    ref = None
    if m.forward_origin and isinstance(m.forward_origin, MessageOriginChannel):
        ref = m.forward_origin.chat.id
    elif m.text:
        t = m.text.strip()
        if t.startswith("https://t.me/"):
            t = "@" + t.split("/")[-1]
        if t.lstrip("-").isdigit():
            ref = int(t)
        elif t.startswith("@"):
            ref = t
    if ref is None:
        return await m.answer("⚠️ @username, ID yoki forward xabar yuboring.", reply_markup=cancel_kb())
    try:
        chat = await bot.get_chat(ref)
        me = await bot.get_chat_member(chat.id, bot.id)
        if me.status not in (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR):
            return await m.answer("⚠️ Bot bu kanalda admin emas. Avval botni admin qiling.", reply_markup=cancel_kb())
    except Exception as e:
        return await m.answer(f"❌ Kanal topilmadi yoki bot unda yo'q.\n<code>{esc(str(e))}</code>", reply_markup=cancel_kb())
    link = None
    if chat.username:
        link = f"https://t.me/{chat.username}"
    else:
        try:
            link = (await bot.create_chat_invite_link(chat.id)).invite_link
        except Exception:
            link = chat.invite_link
    if not link:
        return await m.answer("❌ Havola olinmadi. Botga «Invite users» huquqini bering.", reply_markup=cancel_kb())
    title = chat.title or str(chat.id)
    old = await q_one("SELECT id FROM channels WHERE chat_id=? AND kind=?", (chat.id, kind))
    if old:
        await q_exec("UPDATE channels SET title=?, link=? WHERE id=?", (title, link, old["id"]))
    else:
        await q_exec("INSERT INTO channels(chat_id, title, link, kind) VALUES(?, ?, ?, ?)", (chat.id, title, link, kind))
    JOINED_CACHE.clear()
    await state.clear()
    label = "Post kanal" if kind == "post" else "Majburiy obuna kanali"
    await m.answer(f"✅ <b>{label}</b> qo'shildi: {esc(title)}", reply_markup=panel_btn())


async def channels_view(ev):
    rows = await q_all("SELECT * FROM channels ORDER BY kind, id")
    if not rows:
        return await show(ev, "😔 Kanallar yo'q.", panel_btn())
    out = [[btn(f"🗑 {'🔔' if r['kind'] == 'sub' else '📢'} {r['title']}", f"delc:{r['id']}", "danger")] for r in rows]
    out.append([btn("🛠 Panel", "a:panel", "primary")])
    await show(ev, "🗂 <b>Kanallar</b>\n🔔 — majburiy obuna, 📢 — post kanal\n\nO'chirish uchun tugmani bosing:", kb(out))


@owner_r.callback_query(F.data == "o:channels")
async def o_channels(c: CallbackQuery, state: FSMContext):
    await state.clear()
    await channels_view(c)
    await c.answer()


@owner_r.callback_query(F.data.startswith("delc:"))
async def o_del_channel(c: CallbackQuery):
    await q_exec("DELETE FROM channels WHERE id=?", (int(c.data.split(":")[1]),))
    JOINED_CACHE.clear()
    await c.answer("✅ O'chirildi")
    await channels_view(c)


# ---------- Caption o'zgartirish ----------
@owner_r.callback_query(F.data == "o:caption")
async def o_caption(c: CallbackQuery, state: FSMContext):
    await state.clear()
    await state.set_state(OwnerCaption.text)
    row = await q_one("SELECT value FROM settings WHERE key='caption'")
    await show(
        c,
        "📝 <b>Hozirgi caption:</b>\n\n" + row["value"] + "\n\n"
        "✍️ Yangi caption yuboring. O'zgaruvchilar:\n"
        "<code>{nomi}</code> — drama nomi\n<code>{yili}</code> — drama yili\n"
        "<code>{kodi}</code> — drama kodi\n<code>{janri}</code> — drama janri",
        cancel_kb(),
    )
    await c.answer()


@owner_r.message(OwnerCaption.text, TXT)
async def o_caption_set(m: Message, state: FSMContext):
    await q_exec("UPDATE settings SET value=? WHERE key='caption'", (m.html_text,))
    await state.clear()
    await m.answer("✅ Standart caption yangilandi.", reply_markup=panel_btn())


# ====================================================================
#                      WEB SERVER (Render / UptimeRobot uchun)
# ====================================================================
async def start_web():
    app = web.Application()
    app.router.add_get("/", lambda r: web.Response(text="ok"))
    app.router.add_get("/health", lambda r: web.Response(text="ok"))
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.getenv("PORT", 10000))
    try:
        await web.TCPSite(runner, "0.0.0.0", port).start()
        log.info("Web server ishga tushdi: port %s", port)
    except OSError as e:
        log.warning("Web server ochilmadi (port %s): %s", port, e)
    return runner


# ====================================================================
#                                MAIN
# ====================================================================
async def main():
    global OWNER_ID, BOT_USERNAME
    token = os.getenv("BOT_TOKEN") or input("🤖 Bot token: ").strip()
    OWNER_ID = int(os.getenv("OWNER_ID") or input("👑 Owner Telegram ID: ").strip())

    log.info("aiogram %s", aiogram.__version__)
    await init_db()
    await load_admins()

    runner = await start_web()  # Render'da port ochiq bo'lishi uchun polling'dan oldin

    bot = Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    me = await bot.get_me()
    BOT_USERNAME = me.username
    await load_stickers(bot)

    dp = Dispatcher(storage=DBStorage())
    mw = SubMiddleware()
    dp.message.outer_middleware(mw)
    dp.callback_query.outer_middleware(mw)
    dp.include_router(owner_r)
    dp.include_router(admin_r)
    dp.include_router(user_r)

    log.info("Bot ishga tushdi: @%s", BOT_USERNAME)
    await bot.delete_webhook(drop_pending_updates=True)
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await runner.cleanup()
        await close_db()
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        log.info("Bot to'xtatildi")
