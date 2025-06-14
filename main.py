import asyncpg
import asyncio
import string
import random
import os
import logging
from datetime import datetime
from zoneinfo import ZoneInfo
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher
from aiogram.types import (
    Message, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardRemove
)
from aiogram.filters import Command, CommandObject
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.exceptions import TelegramForbiddenError, TelegramBadRequest
from admin import is_user_admin, admin_router

# Load .env
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
LOG_CHANNEL_ID = os.getenv("LOG_CHANNEL_ID")
ADMIN_URL = os.getenv("ADMIN_URL")
DATABASE_URL = os.getenv("DATABASE_URL")

logging.basicConfig(level=logging.INFO)

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()


# 📘 FSM holatlari
class QuestionStates(StatesGroup):
    waiting_for_question = State()


# 🔐 Token generatsiyasi
def generate_token(length=8):
    return ''.join(random.choices(string.ascii_letters + string.digits, k=length))


# 🔌 PostgreSQL connection pool yaratish
async def init_db():
    pool = await asyncpg.create_pool(DATABASE_URL)
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                username TEXT,
                name TEXT,
                token TEXT UNIQUE,
                is_admin BOOLEAN DEFAULT FALSE,
                is_superuser BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS muted_users(
    user_id     BIGINT PRIMARY KEY REFERENCES users (user_id) ON DELETE CASCADE,
    muted_until TIMESTAMP NOT NULL,
    reason      TEXT,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        await conn.execute("""
                        CREATE TABLE IF NOT EXISTS message_log(
    id          SERIAL PRIMARY KEY,
    sender_id   BIGINT,
    receiver_id BIGINT,
    message     TEXT,
    sent_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
    return pool


# 🔍 Token orqali foydalanuvchini topish
async def get_user_by_token(pool, token: str):
    async with pool.acquire() as conn:
        return await conn.fetchrow("SELECT user_id FROM users WHERE token = $1", token)


# 🚫 Mute tekshirish
async def is_user_muted(pool, user_id: int) -> tuple[bool, datetime | None]:
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT muted_until FROM muted_users WHERE user_id = $1", user_id)
        if row:
            muted_until = row["muted_until"]
            current_time = datetime.now(ZoneInfo("Asia/Tashkent")).replace(tzinfo=None)
            if muted_until > current_time:
                return True, muted_until
            else:
                await conn.execute("DELETE FROM muted_users WHERE user_id = $1", user_id)
        return False, None


# 📝 Xabar log qilish
async def log_message(pool, sender_id, receiver_id, text):
    tashkent_time = datetime.now(ZoneInfo("Asia/Tashkent")).replace(tzinfo=None)
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO message_log (sender_id, receiver_id, message, sent_at)
            VALUES ($1, $2, $3, $4)
        """, sender_id, receiver_id, text, tashkent_time)


# 🚀 /start komandasi
@dp.message(Command("start"))
async def start_handler(message: Message, command: CommandObject, state: FSMContext):
    pool = dp["db"]
    user_id = message.from_user.id
    username = message.from_user.username
    name = message.from_user.full_name

    if command.args:
        is_muted, muted_until = await is_user_muted(pool, user_id)
        if is_muted:
            vaqt_str = muted_until.strftime("%Y-%m-%d %H:%M:%S")
            await message.answer(
                f"⛔ Siz vaqtinchalik xabar yubora olmaysiz.\n"
                f"🕒 Mute Toshkent vaqti bilan {vaqt_str} gacha davom etadi.\n"
                f"Iltimos, kuting."
            )
            return

        target = await get_user_by_token(pool, command.args)
        if target:
            await state.set_state(QuestionStates.waiting_for_question)
            await state.update_data(target_id=target["user_id"])
            await message.answer("<b>Murojaatingizni shu yerga yozing!</b>")
        else:
            await message.answer("<b>⚠️ Noto‘g‘ri havola.</b>")
    else:
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT token FROM users WHERE user_id = $1", user_id)
            if row:
                token = row["token"]
            else:
                token = generate_token()
                tashkent_time = datetime.now(ZoneInfo("Asia/Tashkent")).replace(tzinfo=None)
                await conn.execute(
                    "INSERT INTO users (user_id, username, name, token, created_at) VALUES ($1, $2, $3, $4, $5)",
                    user_id, username, name, token, tashkent_time
                )

        bot_username = (await bot.me()).username
        link = f"https://t.me/{bot_username}?start={token}"
        share_keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📤 Ulashish", url=f"https://t.me/share/url?url={link}")]
        ])

        await message.answer(
            f"<b>👋 Xush kelibsiz, {name}!\n</b>"
            f"<b>Bu sizning shaxsiy havolangiz:\n</b>"
            f"\n🔗 {link}\n\n"
            f"<b>Ulashish orqali anonim suhbat quring!</b>",
            reply_markup=share_keyboard
        )


@dp.message(QuestionStates.waiting_for_question)
async def handle_question(message: Message, state: FSMContext):
    pool = dp["db"]
    data = await state.get_data()
    target_id = data.get("target_id")

    user_id = message.from_user.id
    username = message.from_user.username
    name = message.from_user.full_name

    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT token FROM users WHERE user_id = $1", user_id)
        if row:
            sender_token = row["token"]
        else:
            sender_token = generate_token()
            tashkent_time = datetime.now(ZoneInfo("Asia/Tashkent")).replace(tzinfo=None)
            await conn.execute(
                "INSERT INTO users (user_id, username, name, token, created_at) VALUES ($1, $2, $3, $4, $5)",
                user_id, username, name, sender_token, tashkent_time
            )

    bot_username = (await bot.me()).username
    link = f"https://t.me/{bot_username}?start={sender_token}"
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="↩️ Javob berish", url=link)]
    ])

    try:
        if message.text:
            await bot.send_message(
                chat_id=target_id,
                text=f"<b>📨 Sizga yangi anonim xabar bor!</b>\n\n{message.text}",
                reply_markup=keyboard
            )
            await log_message(pool, user_id, target_id, message.text)

        else:
            if message.photo:
                await bot.send_photo(target_id, message.photo[-1].file_id,
                                     caption="<b>📨 Sizga yangi anonim xabar bor!</b>", reply_markup=keyboard)
            elif message.video:
                await bot.send_video(target_id, message.video.file_id, caption="<b>📨 Sizga yangi anonim xabar bor!</b>",
                                     reply_markup=keyboard)
            elif message.voice:
                await bot.send_voice(target_id, message.voice.file_id, caption="<b>📨 Sizga yangi anonim xabar bor!</b>",
                                     reply_markup=keyboard)
            elif message.document:
                await bot.send_document(target_id, message.document.file_id,
                                        caption="<b>📨 Sizga yangi anonim xabar bor!</b>", reply_markup=keyboard)
            else:
                await message.answer("<b>⚠️ Ushbu turdagi xabar qo‘llab-quvvatlanmaydi.</b>")
                return

            sender_link = f'<a href="tg://user?id={user_id}">{name}</a>'
            receiver_link = f'<a href="tg://user?id={target_id}">{target_id}</a>'

            log_caption = (
                f"📥 <b>Yuboruvchi:</b> {sender_link}\n\n"
                f"👤 <b>Qabul qiluvchi:</b> {receiver_link}"
            )

            if message.photo:
                await bot.send_photo(LOG_CHANNEL_ID, message.photo[-1].file_id, caption=log_caption, parse_mode='HTML')
            elif message.video:
                await bot.send_video(LOG_CHANNEL_ID, message.video.file_id, caption=log_caption, parse_mode='HTML')
            elif message.voice:
                await bot.send_voice(LOG_CHANNEL_ID, message.voice.file_id, caption=log_caption, parse_mode='HTML')
            elif message.document:
                await bot.send_document(LOG_CHANNEL_ID, message.document.file_id, caption=log_caption,
                                        parse_mode='HTML')

        await message.answer("✅ Xabaringiz yuborildi!", reply_markup=ReplyKeyboardRemove())

    except TelegramForbiddenError:
        await message.answer("❌ Xabar yuborilmadi. Foydalanuvchi botni bloklagan.")
    except TelegramBadRequest as e:
        await message.answer(f"⚠️ Xatolik yuz berdi: {e.message}")

    await state.clear()


@dp.message(Command("help"))
async def send_help(message: Message, bot: Bot, dispatcher: Dispatcher):
    pool = dispatcher["db"]
    user_id = message.from_user.id

    if await is_user_admin(pool, user_id):
        # 👨‍💻 Admin uchun
        await message.answer(
            "<b>🛠 Admin Yordam</b>\n\n"
            "Siz admin hisobidasiz. Quyidagilarni bajarishingiz mumkin:\n"
            "• /admin — admin panel\n"
        )
    else:
        await message.answer(
            "<b>❓ Yordam</b>\n\n"
            "Quyidagi komandalar mavjud:\n"
            "• /start — botni ishga tushurish\n"
            "• /help — yordam oynasi\n\n"
            f"Agar sizga qo‘shimcha yordam kerak bo‘lsa, <a href='{ADMIN_URL}'>admin</a> bilan bog‘laning."
        )


async def main():
    pool = await init_db()
    dp["db"] = pool
    dp.include_router(admin_router)
    try:
        await dp.start_polling(bot)
    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
