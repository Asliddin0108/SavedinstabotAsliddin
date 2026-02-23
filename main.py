#!/usr/bin/env python3
"""
🎵 Professional Telegram Music Bot
Musiqa yuklash, qidirish, aniqlash va konvertatsiya qilish boti
Author: AI Assistant
Version: 1.0.0
"""

import asyncio
import sqlite3
import os
import re
import uuid
import logging
import hashlib
from pathlib import Path
from typing import Optional, Dict, Any
from datetime import datetime, timedelta
from dataclasses import dataclass
from contextlib import suppress

from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import (
    Message, FSInputFile, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton,
    ContentType
)
from aiogram.filters import Command, CommandStart
from aiogram.enums import ParseMode, ChatAction
from aiogram.client.default import DefaultBotProperties
from aiogram.exceptions import TelegramBadRequest
import aiohttp
import yt_dlp

# Shazam import
try:
    from shazamio import Shazam
    SHAZAM_AVAILABLE = True
except ImportError:
    SHAZAM_AVAILABLE = False
    print("⚠️ shazamio kutubxonasi topilmadi. Musiqa aniqlash ishlamaydi.")


# ╔════════════════ THREAD POOL (SPEED OPTIMIZATION) ════════════════╗
# CPU heavy ishlarni parallel qilish uchun
from concurrent.futures import ThreadPoolExecutor

EXECUTOR = ThreadPoolExecutor(
    max_workers=10  # 4 parallel download
)
# ╚═══════════════════════════════════════════════════════════════════╝


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║                              KONFIGURATSIYA                                   ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

# 🔑 Bot tokeningizni shu yerga qo'ying
BOT_TOKEN = "8331919528:AAEZJCdO6fV31NVnJ9eZacf-rJrEw3HtSww"

# STORAGE GROUP (BOT XOTIRASI)
STORAGE_GROUP_ID = -1003831196510

# BU YERGA O'Z TELEGRAM ID INGNI YOZASAN
ADMINS = [8238730404]  

# ╔════════════════ CHANNEL ADD STATE ════════════════╗
channel_add_state = {}
# ╚═══════════════════════════════════════════════════╝


# 📁 Vaqtinchalik fayllar papkasi
TEMP_DIR = Path("./downloads")
TEMP_DIR.mkdir(exist_ok=True)

# ⚙️ Bot sozlamalari
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB (Telegram limiti)
AUDIO_BITRATE = "320"  # kbps
SEARCH_RESULTS_COUNT = 5
CACHE_TTL = 3600  # 1 soat

# ╔════════════════ FAST AUDIO DOWNLOAD CONFIG ════════════════╗
# tezroq download uchun optimizatsiya
AUDIO_OPTIONS = {

    # eng tez audio formatlar
    'format': 'bestaudio[ext=m4a]/bestaudio[ext=mp3]/bestaudio',

    'quiet': True,
    'noplaylist': True,
    'geo_bypass': True,

    # retry optimizatsiya
    'retries': 3,
    'fragment_retries': 3,

    # SSL skip speed boost
    'nocheckcertificate': True,

    # parallel fragment download
    'concurrent_fragment_downloads': 5,

    'ignoreerrors': True,
}
# ╚═════════════════════════════════════════════════════════════╝


# ╔════════════════ FAST VIDEO DOWNLOAD CONFIG ════════════════╗
VIDEO_OPTIONS = {

    # 720p limit speed boost
    'format': 'best[ext=mp4][height<=720]',

    'quiet': True,
    'noplaylist': True,

    # parallel download
    'concurrent_fragment_downloads': 5,

    'geo_bypass': True,

    'ignoreerrors': True,
}
# ╚═════════════════════════════════════════════════════════════╝

# ╔════════════════ INSTAGRAM FAST DOWNLOAD CONFIG ════════════════╗
INSTAGRAM_OPTIONS = {

    # eng tez video format
    'format': 'best[ext=mp4]/best',

    'quiet': True,

    'noplaylist': True,

    'ignoreerrors': True,

    'geo_bypass': True,

    # instagram extractor optimizatsiya
    'extractor_args': {
        'instagram': {
            'api_version': 'v1',
        }
    },

    # parallel download
    'concurrent_fragment_downloads': 5,

}
# ╚═════════════════════════════════════════════════════════════════╝

# ╔════════════════ BROADCAST STATE ════════════════╗
broadcast_state = {
    "active": False,
    "total": 0,
    "sent": 0,
    "failed": 0,
    "pending": 0,
    "message": None
}

broadcast_waiting_admin = set()
# ╚═════════════════════════════════════════════════╝

# ╔════════════════ THREAD POOL (DOWNLOAD SPEED BOOST) ════════════════╗
# yt-dlp va ffmpeg ishlarini parallel bajarish uchun
from concurrent.futures import ThreadPoolExecutor

EXECUTOR = ThreadPoolExecutor(
    max_workers=10
)
# ╚═════════════════════════════════════════════════════════════════════╝


# 📝 Logging sozlamalari
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(name)s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger("MusicBot")

# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║                               DATA CLASSES                                    ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

@dataclass
class MediaInfo:
    """Media ma'lumotlari"""
    title: str = "Noma'lum"
    artist: str = "Noma'lum"
    duration: int = 0
    thumbnail: Optional[str] = None
    url: Optional[str] = None
    platform: Optional[str] = None

@dataclass
class RecognitionResult:
    """Musiqa aniqlash natijasi"""
    title: str
    artist: str
    album: str = "Noma'lum"
    genre: str = "Noma'lum"
    year: str = "Noma'lum"
    cover_url: Optional[str] = None
    shazam_url: Optional[str] = None

# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║                                BOT SETUP                                      ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)
dp = Dispatcher()
router = Router(name="main_router")
dp.include_router(router)

# Shazam instance
shazam = Shazam() if SHAZAM_AVAILABLE else None

# URL cache (callback uchun)
url_cache: Dict[str, str] = {}
media_cache: Dict[str, str] = {}

# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║                                DATABASE                                      ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

# ╔════════════════ DATABASE (THREAD SAFE VERSION) ════════════════╗

conn = sqlite3.connect(
    "cache.db",
    check_same_thread=False,
    timeout=30
)

# performance boost
conn.execute("PRAGMA journal_mode=WAL")
conn.execute("PRAGMA synchronous=NORMAL")

cursor = conn.cursor()

# database lock (IMPORTANT)
db_lock = asyncio.Lock()

# ╚════════════════════════════════════════════════════════════════╝

cursor.execute("""
CREATE TABLE IF NOT EXISTS cache (
    video_id TEXT PRIMARY KEY,
    audio_file_id TEXT,
    video_file_id TEXT
)
""")

# ╔════════════════ SEARCH CACHE TABLE ════════════════╗
cursor.execute("""
CREATE TABLE IF NOT EXISTS search_cache (

    query TEXT PRIMARY KEY,

    results TEXT,

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP

)
""")
# ╚════════════════════════════════════════════════════╝


# ╔════════════════ RECOGNITION CACHE TABLE ════════════════╗
cursor.execute("""
CREATE TABLE IF NOT EXISTS recognition_cache (

    file_hash TEXT PRIMARY KEY,

    title TEXT,

    artist TEXT,

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP

)
""")
# ╚═════════════════════════════════════════════════════════╝

# ╔════════════════ USERS TABLE ════════════════╗
cursor.execute("""
CREATE TABLE IF NOT EXISTS users (

    user_id INTEGER PRIMARY KEY,

    first_name TEXT,

    username TEXT,

    joined_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    last_active TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    is_blocked INTEGER DEFAULT 0,

    referrer_id INTEGER DEFAULT NULL

)
""")
# ╚═════════════════════════════════════════════╝


# ╔════════════════ CHANNELS TABLE ════════════════╗
cursor.execute("""
CREATE TABLE IF NOT EXISTS channels (

    channel_id TEXT PRIMARY KEY,

    channel_link TEXT,

    added_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP

)
""")
# ╚═══════════════════════════════════════════════╝

conn.commit()



# missing column fix
cursor.execute("PRAGMA table_info(cache)")
columns = [col[1] for col in cursor.fetchall()]

if "video_file_id" not in columns:
    cursor.execute("ALTER TABLE cache ADD COLUMN video_file_id TEXT")

if "audio_file_id" not in columns:
    cursor.execute("ALTER TABLE cache ADD COLUMN audio_file_id TEXT")

conn.commit()


def get_cached_video(video_id):

    cursor.execute(
        "SELECT video_file_id FROM cache WHERE video_id=?",
        (video_id,)
    )

    result = cursor.fetchone()

    return result[0] if result and result[0] else None


def save_video_cache(video_id, file_id):

    cursor.execute("""
        INSERT INTO cache(video_id, video_file_id)
        VALUES(?, ?)
        ON CONFLICT(video_id)
        DO UPDATE SET video_file_id=excluded.video_file_id
    """, (video_id, file_id))

    conn.commit()

def get_cached_video(video_id):

    cursor.execute(
        "SELECT video_file_id FROM cache WHERE video_id=?",
        (video_id,)
    )

    result = cursor.fetchone()

    return result[0] if result and result[0] else None


def save_video_cache(video_id, file_id):

    cursor.execute("""
        INSERT INTO cache(video_id, video_file_id)
        VALUES(?, ?)
        ON CONFLICT(video_id)
        DO UPDATE SET video_file_id=excluded.video_file_id
    """, (video_id, file_id))

    conn.commit()

# ╔════════════════ AUDIO CACHE FUNCTIONS ════════════════╗

def get_cached_audio(video_id: str):

    cursor.execute(
        "SELECT audio_file_id FROM cache WHERE video_id=?",
        (video_id,)
    )

    result = cursor.fetchone()

    if result and result[0]:
        return result[0]

    return None


async def save_audio_cache(video_id: str, file_id: str):

    async with db_lock:

        conn.execute(
            """
            INSERT INTO cache(video_id, audio_file_id)
            VALUES(?, ?)
            ON CONFLICT(video_id)
            DO UPDATE SET audio_file_id=excluded.audio_file_id
            """,
            (video_id, file_id)
        )

        conn.commit()

# ╚════════════════════════════════════════════════════════╝

# ╔════════════════ GET ACTIVE USERS (ONLY ACTIVE) ════════════════╗
def get_active_users():

    cursor.execute(
        """
        SELECT user_id
        FROM users
        WHERE is_blocked=0
        """
    )

    return [row[0] for row in cursor.fetchall()]
# ╚═══════════════════════════════════════════════════╝



# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║                            MESSAGE TEMPLATES                                  ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

WELCOME_MESSAGE = """
╭━━━━━━━━━━━━━━━━━━━━━━╮
│  🎵 <b>MUSIC BOT</b> 🎵  │
╰━━━━━━━━━━━━━━━━━━━━━━╯

Salom, <b>{name}</b>! 👋

Men sizga quyidagilarda yordam beraman:

╭─────────────────────────╮
│ 🔍 <b>Musiqa qidirish</b>          │
│ 📥 <b>Video/Audio yuklash</b>     │
│ 🎤 <b>Musiqani aniqlash</b>        │
╰─────────────────────────╯

<b>📱 Qo'llab-quvvatlanadigan platformalar:</b>
├ YouTube (video, shorts, music)
├ Instagram (reels, posts, stories)
└ TikTok (videolar)

<b>🚀 Boshlash uchun:</b>
• Musiqa nomini yozing
• Yoki link yuboring

/help - Batafsil qo'llanma
"""

HELP_MESSAGE = """
╭━━━━━━━━━━━━━━━━━━━━━━━╮
│  📖 <b>QO'LLANMA</b> 📖  │
╰━━━━━━━━━━━━━━━━━━━━━━━╯

<b>1️⃣ MUSIQA QIDIRISH:</b>
┌─────────────────────────
│ Musiqa nomini yozing:
│ <code>Shape of You</code>
│ <code>Believer Imagine Dragons</code>
│ <code>Linkin Park Numb</code>
└─────────────────────────

<b>2️⃣ LINK ORQALI YUKLASH:</b>
┌─────────────────────────
│ <b>YouTube:</b>
│ <code>https://youtube.com/watch?v=xxx</code>
│ <code>https://youtu.be/xxx</code>
│
│ <b>Instagram:</b>
│ <code>https://instagram.com/reel/xxx</code>
│ <code>https://instagram.com/p/xxx</code>
│
│ <b>TikTok:</b>
│ <code>https://tiktok.com/@user/video/xxx</code>
│ <code>https://vm.tiktok.com/xxx</code>
└─────────────────────────

<b>3️⃣ VIDEO YUBORISH:</b>
┌─────────────────────────
│ • Telegram orqali video yuboring
│ • Bot audiosinj ajratib beradi
│ • Musiqani aniqlaydi
└─────────────────────────

<b>4️⃣ MUSIQANI ANIQLASH:</b>
┌─────────────────────────
│ • Audio yoki video yuboring
│ • "🎤 Aniqlash" tugmasini bosing
│ • Qo'shiq nomini bilib olasiz
└─────────────────────────

<b>📋 KOMANDALAR:</b>
├ /start - Botni ishga tushirish
├ /help - Ushbu yordam
└ /stats - Statistika

<b>⚠️ ESLATMA:</b>
• Maksimal fayl hajmi: 50MB
• Audio sifati: 320kbps
• Qo'llab-quvvatlash: @your_support
"""

DOWNLOADING_MESSAGE = """
╭━━━━━━━━━━━━━━━━━━━╮
│  📥 <b>YUKLANMOQDA</b>  │
╰━━━━━━━━━━━━━━━━━━━╯

{status}

<b>⏳ Iltimos kuting...</b>
"""

ERROR_MESSAGE = """
╭━━━━━━━━━━━━━━━━━━╮
│  ❌ <b>XATOLIK</b>  │
╰━━━━━━━━━━━━━━━━━━╯

{error}

<b>💡 Tavsiyalar:</b>
• Linkni tekshiring
• Boshqa qidiruvni sinang
• Keyinroq urinib ko'ring
"""

SUCCESS_MESSAGE = """
╭━━━━━━━━━━━━━━━━━━╮
│  ✅ <b>TAYYOR</b>  │
╰━━━━━━━━━━━━━━━━━━╯

🎵 <b>{title}</b>
👤 {artist}
⏱ {duration}
"""

RECOGNITION_MESSAGE = """
╭━━━━━━━━━━━━━━━━━━━━━╮
│  🎤 <b>MUSIQA ANIQLANDI</b>  │
╰━━━━━━━━━━━━━━━━━━━━━╯

📀 <b>Nom:</b> {title}
👤 <b>Ijrochi:</b> {artist}
💿 <b>Album:</b> {album}
🎭 <b>Janr:</b> {genre}

{extra}
"""

# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║                             HELPER FUNCTIONS                                  ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

def generate_id() -> str:
    """Unikal ID yaratish"""
    return uuid.uuid4().hex[:12]

def hash_url(url: str) -> str:
    """URL uchun qisqa hash"""
    return hashlib.md5(url.encode()).hexdigest()[:10]

def format_duration(seconds: int) -> str:
    """Sekundlarni formatlash"""
    if not seconds:
        return "0:00"
    minutes, secs = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"

def is_url(text: str) -> bool:
    """Matn URL ekanligini tekshirish"""
    url_pattern = re.compile(
        r'^https?://'
        r'(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+[A-Z]{2,6}\.?|'
        r'localhost|'
        r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})'
        r'(?::\d+)?'
        r'(?:/?|[/?]\S+)$', re.IGNORECASE
    )
    return bool(url_pattern.match(text.strip()))

def get_platform(url: str) -> Optional[str]:
    """URL platformasini aniqlash"""
    url_lower = url.lower()

    platforms = {
        'youtube': ['youtube.com', 'youtu.be', 'youtube.com/shorts'],
        'instagram': ['instagram.com', 'instagr.am'],
        'tiktok': ['tiktok.com', 'vm.tiktok.com', 'vt.tiktok.com']
    }

    for platform, domains in platforms.items():
        if any(domain in url_lower for domain in domains):
            return platform
    return None
# ╔════════════════ INSTAGRAM URL NORMALIZER ════════════════╗
def normalize_instagram_url(url: str) -> str:

    if "/reel/" in url:

        return url.split("?")[0]

    if "/p/" in url:

        return url.split("?")[0]

    return url
# ╚═══════════════════════════════════════════════════════════╝
import json


# ╔════════════════ SEARCH CACHE FUNCTIONS ════════════════╗

def get_cached_search(query: str):

    cursor.execute(
        "SELECT results FROM search_cache WHERE query=?",
        (query,)
    )

    row = cursor.fetchone()

    if row:
        return json.loads(row[0])

    return None


def save_search_cache(query: str, results: list):

    cursor.execute(
        """
        INSERT OR REPLACE INTO search_cache(query, results)
        VALUES(?, ?)
        """,
        (query, json.dumps(results))
    )

    conn.commit()

# ╚════════════════════════════════════════════════════════╝
# ╔════════════════ RECOGNITION CACHE ════════════════╗

def get_cached_recognition(file_hash: str):

    cursor.execute(
        """
        SELECT title, artist
        FROM recognition_cache
        WHERE file_hash=?
        """,
        (file_hash,)
    )

    row = cursor.fetchone()

    if row:

        return RecognitionResult(
            title=row[0],
            artist=row[1]
        )

    return None


def save_recognition_cache(
    file_hash: str,
    title: str,
    artist: str
):

    cursor.execute(
        """
        INSERT OR REPLACE INTO recognition_cache
        VALUES(?, ?, ?, CURRENT_TIMESTAMP)
        """,
        (file_hash, title, artist)
    )

    conn.commit()

# ╚════════════════════════════════════════════════════╝

# ╔════════════════ SAVE USER FUNCTION (AUTO UNBLOCK FIX) ════════════════╗
def save_user(user):

    # agar user yangi bo‘lsa qo‘shiladi
    cursor.execute(
        """
        INSERT OR IGNORE INTO users(
            user_id,
            first_name,
            username
        )
        VALUES (?, ?, ?)
        """,
        (
            user.id,
            user.first_name,
            user.username
        )
    )

    # har safar user yozsa:
    # last_active yangilanadi
    # agar oldin block bo‘lgan bo‘lsa → unblock qilinadi
    cursor.execute(
        """
        UPDATE users
        SET
            last_active=CURRENT_TIMESTAMP,
            is_blocked=0
        WHERE user_id=?
        """,
        (user.id,)
    )

    conn.commit()
# ╚════════════════════════════════════════════════════╝

# ╔════════════════ STATISTICS FUNCTION ════════════════╗
def get_statistics():

    cursor.execute(
        "SELECT COUNT(*) FROM users WHERE is_blocked=0"
    )
    active = cursor.fetchone()[0]


    cursor.execute(
        """
        SELECT COUNT(*) FROM users
        WHERE last_active >= datetime('now','-1 day')
        """
    )
    day = cursor.fetchone()[0]


    cursor.execute(
        """
        SELECT COUNT(*) FROM users
        WHERE last_active >= datetime('now','-7 day')
        """
    )
    week = cursor.fetchone()[0]


    cursor.execute(
        """
        SELECT COUNT(*) FROM users
        WHERE last_active >= datetime('now','-30 day')
        """
    )
    month = cursor.fetchone()[0]


    cursor.execute(
        "SELECT COUNT(*) FROM users"
    )
    total = cursor.fetchone()[0]


    return active, day, week, month, total
# ╚════════════════════════════════════════════════════╝
# ╔════════════════ CHANNEL DATABASE FUNCTIONS ════════════════╗

def add_channel(channel_id: str, channel_link: str):

    cursor.execute(
        """
        INSERT OR REPLACE INTO channels(
            channel_id,
            channel_link
        )
        VALUES (?, ?)
        """,
        (channel_id, channel_link)
    )

    conn.commit()


def remove_channel(channel_id: str):

    cursor.execute(
        "DELETE FROM channels WHERE channel_id=?",
        (channel_id,)
    )

    conn.commit()


def get_channels():

    cursor.execute(
        "SELECT channel_id, channel_link FROM channels"
    )

    return cursor.fetchall()

# ╚════════════════════════════════════════════════════════════╝


async def cleanup_file(file_path: Path) -> None:
    """Faylni xavfsiz o'chirish"""
    try:
        if file_path and file_path.exists():
            file_path.unlink()
            logger.debug(f"Fayl o'chirildi: {file_path}")
    except Exception as e:
        logger.warning(f"Fayl o'chirishda xato: {e}")

async def cleanup_files(*paths: Path) -> None:
    """Bir nechta fayllarni o'chirish"""
    for path in paths:
        await cleanup_file(path)

async def cleanup_old_files(max_age_hours: int = 1) -> None:
    """Eski fayllarni tozalash"""
    cutoff = datetime.now() - timedelta(hours=max_age_hours)

    for file in TEMP_DIR.glob("*"):
        try:
            if datetime.fromtimestamp(file.stat().st_mtime) < cutoff:
                file.unlink()
                logger.debug(f"Eski fayl o'chirildi: {file}")
        except Exception:
            pass

# ╔════════════════ INSTAGRAM ULTRA FAST DOWNLOADER ════════════════╗
async def download_instagram_fast(url: str) -> Optional[Path]:

    file_id = generate_id()

    output_path = TEMP_DIR / f"{file_id}.mp4"


    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 Chrome/120 Safari/537.36"
        )
    }


    try:

        async with aiohttp.ClientSession(headers=headers) as session:

            # Instagram page ni olish
            async with session.get(url) as resp:

                html = await resp.text()


            # video url ni extract qilish
            import re

            match = re.search(
                r'"video_url":"([^"]+)"',
                html
            )


            if not match:
                return None


            video_url = match.group(1).replace("\\u0026", "&")


            # video download qilish
            async with session.get(video_url) as resp:

                with open(output_path, "wb") as f:

                    while True:

                        chunk = await resp.content.read(1024 * 1024)

                        if not chunk:
                            break

                        f.write(chunk)


        if output_path.exists():
            return output_path


    except Exception as e:

        logger.error(f"Instagram fast download error: {e}")


    return None

# ╚═══════════════════════════════════════════════════════════════════╝
# ╔════════════════ PROFESSIONAL SEARCH RESULT UI ════════════════╗
async def send_search_results(status_msg, results):

    if not results:

        await status_msg.edit_text("❌ Natija topilmadi")

        return


    text = "🎵 <b>Natijalar:</b>\n\n"

    keyboard = []

    row = []


    for i, item in enumerate(results[:5], start=1):

        title = item.get("title", "Noma'lum")

        duration = int(item.get("duration") or 0)

        video_id = item.get("id")


        text += f"{i}. {title} ({format_duration(duration)})\n"


        row.append(

            InlineKeyboardButton(

                text=str(i),

                callback_data=f"dl:{video_id}"

            )

        )


        if len(row) == 3:

            keyboard.append(row)

            row = []


    if row:

        keyboard.append(row)


    await status_msg.edit_text(

        text,

        reply_markup=InlineKeyboardMarkup(

            inline_keyboard=keyboard

        )

    )

# ╚════════════════════════════════════════════════════════════╝

# ╔════════════════ CHECK SUBSCRIBE FUNCTION (FIXED) ════════════════╗
async def check_subscriptions(user_id: int):

    channels = get_channels()

    # agar kanal yo‘q bo‘lsa → empty list qaytaradi
    if not channels:
        return []

    not_joined = []

    for channel_id, link in channels:

        try:

            member = await bot.get_chat_member(
                channel_id,
                user_id
            )

            if member.status in ["left", "kicked"]:
                not_joined.append(link)

        except:
            not_joined.append(link)

    return not_joined
# ╚═══════════════════════════════════════════════════════════════════╝

# ╔════════════════ PROFESSIONAL BROADCAST PROCESS (OPTIMIZED) ════════════════╗
async def run_broadcast(status_msg: Message):

    users = get_active_users()

    broadcast_state["total"] = len(users)
    broadcast_state["pending"] = len(users)
    broadcast_state["sent"] = 0
    broadcast_state["failed"] = 0

    # status keyboard
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="⛔ To‘xtatish",
                    callback_data="broadcast_stop"
                )
            ]
        ]
    )

    try:

        for index, user_id in enumerate(users, start=1):

            # STOP bosilgan bo‘lsa darhol to‘xtaydi
            if not broadcast_state["active"]:
                break

            try:

                await broadcast_state["message"].copy_to(user_id)

                broadcast_state["sent"] += 1


            # USER BOTNI BLOCK QILGAN
            except TelegramBadRequest:

                broadcast_state["failed"] += 1

                # database dan inactive qilish
                cursor.execute(
                    """
                    UPDATE users
                    SET is_blocked=1
                    WHERE user_id=?
                    """,
                    (user_id,)
                )

                conn.commit()


            # boshqa xatoliklar
            except Exception as e:

                logger.error(f"Broadcast user error: {e}")

                broadcast_state["failed"] += 1


            finally:

                broadcast_state["pending"] -= 1


            # ╔════════ STATUS UPDATE EVERY 5 USERS ════════╗
            if index % 5 == 0:

                text = f"""
📡 <b>Broadcast Status</b>

Status: <b>yuborilayapti</b>

📤 Yuborilganlar: <code>{broadcast_state['sent']}</code>
❌ Yuborilmaganlar: <code>{broadcast_state['failed']}</code>
⏳ Kutilayotganlar: <code>{broadcast_state['pending']}</code>

📊 Jami: <code>{broadcast_state['total']}</code>
"""

                with suppress(Exception):
                    await status_msg.edit_text(
                        text,
                        reply_markup=keyboard
                    )
            # ╚═════════════════════════════════════════════╝


            # Flood protection
            await asyncio.sleep(0.03)


    except Exception as e:

        logger.error(f"Broadcast fatal error: {e}")


    # broadcast finished
    broadcast_state["active"] = False


    # ╔════════ FINAL RESULT MESSAGE ════════╗
    final_text = f"""
✅ <b>Broadcast tugadi</b>

📤 Yuborilganlar: <code>{broadcast_state['sent']}</code>
❌ Yuborilmaganlar: <code>{broadcast_state['failed']}</code>

📊 Jami: <code>{broadcast_state['total']}</code>
"""


    with suppress(Exception):
        await status_msg.edit_text(
            final_text,
            reply_markup=get_back_keyboard()
        )
# ╚═══════════════════════════════════════════════════════════════════════════╝
# ╔════════════════ USER RATE LIMIT ════════════════╗

user_rate_limit = {}

def check_rate_limit(user_id):

    now = datetime.now()

    if user_id in user_rate_limit:

        diff = (now - user_rate_limit[user_id]).total_seconds()

        if diff < 2:
            return False

    user_rate_limit[user_id] = now

    return True

# ╚══════════════════════════════════════════════════╝

# ╔════════════════ DOWNLOAD QUEUE SYSTEM ════════════════╗

download_queue = asyncio.Queue()

MAX_DOWNLOAD_WORKERS = 3

download_workers_started = False

async def add_to_download_queue(callback: CallbackQuery, video_id: str):
    """
    Download taskni queue ga qo‘shadi
    """
    await download_queue.put((callback, video_id))

# ╚═══════════════════════════════════════════════════════╝


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║                            DOWNLOAD FUNCTIONS                                 ║
# ╚══════════════════════════════════════════════════════════════════════════════╝
DOWNLOAD_SEMAPHORE = asyncio.Semaphore(7)
async def search_youtube(query: str):

    # CACHE CHECK FIRST
    cached = get_cached_search(query)

    if cached:
        return cached


    # normal search
    def _search():

        with yt_dlp.YoutubeDL({
            'quiet': True,
            'extract_flat': True,
            'default_search': 'ytsearch',
        }) as ydl:

            result = ydl.extract_info(
                f"ytsearch10:{query}",
                download=False
            )

            return result.get("entries", [])


    loop = asyncio.get_running_loop()

    results = await loop.run_in_executor(
        EXECUTOR,
        _search
    )


    # SAVE CACHE
    save_search_cache(query, results)


    return results


# ╔════════════════ ULTRA FAST AUDIO DOWNLOAD FUNCTION (FINAL) ════════════════╗
async def download_audio(url: str) -> tuple[Optional[Path], Optional[MediaInfo]]:
    """
    ULTRA FAST audio downloader
    YouTube, Instagram, TikTok optimized
    """

    # ╔════════ GENERATE FILE ID ════════╗
    file_id = generate_id()

    output_template = str(TEMP_DIR / f"{file_id}.%(ext)s")
    # ╚══════════════════════════════════╝


    # ╔════════ PLATFORM DETECTION ════════╗
    platform = get_platform(url)
    # ╚════════════════════════════════════╝


    # ╔════════ PLATFORM BASED CONFIG ════════╗
    if platform == "instagram":

        # Instagram uchun avval video yuklab, keyin audio extract qilamiz
        video_path = await download_instagram_fast(url)

        if not video_path:
            return None, None

        audio_path = await extract_audio_from_video(video_path)

        await cleanup_file(video_path)

        if not audio_path:
            return None, None

        media_info = MediaInfo(
            title="Instagram Audio",
            artist="Instagram",
            duration=0,
            url=url,
            platform="instagram"
        )

        return audio_path, media_info


    # YouTube / TikTok uchun yt-dlp ishlatamiz
    opts = AUDIO_OPTIONS.copy()

    opts["outtmpl"] = output_template
    # ╚════════════════════════════════════╝


    # ╔════════ THREAD POOL DOWNLOAD ════════╗
    def _download():

        try:

            with yt_dlp.YoutubeDL(opts) as ydl:

                info = ydl.extract_info(
                    url,
                    download=True
                )

                return info

        except Exception as e:

            logger.error(f"Audio yuklash xatosi: {e}")

            return None
    # ╚══════════════════════════════════════╝


    # ╔════════ RUN IN THREAD POOL ════════╗
    loop = asyncio.get_running_loop()

    async with DOWNLOAD_SEMAPHORE:

        info = await loop.run_in_executor(
            EXECUTOR,
            _download
        )
    # ╚════════════════════════════════════╝


    if not info:
        return None, None


    # ╔════════ FAST FILE DETECTION ════════╗
    possible_ext = ["mp3", "m4a", "webm", "opus", "ogg"]

    found_path = None

    for ext in possible_ext:

        path = TEMP_DIR / f"{file_id}.{ext}"

        if path.exists():

            found_path = path

            break
    # ╚════════════════════════════════════╝


    if not found_path:
        return None, None


    # ╔════════ CONVERT ONLY IF NEEDED ════════╗
    if found_path.suffix != ".mp3":

        converted = await convert_to_mp3(found_path)

        if not converted:
            return None, None

        await cleanup_file(found_path)

        found_path = converted
    # ╚══════════════════════════════════════╝


    # ╔════════ BUILD MEDIA INFO ════════╗
    media_info = MediaInfo(

        title=info.get(
            "title",
            "Audio"
        )[:100],

        artist=info.get(
            "uploader",
            info.get(
                "channel",
                "Noma'lum"
            )
        )[:50],

        duration=int(
            info.get("duration") or 0
        ),

        thumbnail=info.get("thumbnail"),

        url=url,

        platform=platform
    )
    # ╚══════════════════════════════════╝


    return found_path, media_info
# ╚═════════════════════════════════════════════════════════════════════╝


# ╔════════════════ ULTRA FAST VIDEO DOWNLOAD FUNCTION ════════════════╗
async def download_video(url: str) -> tuple[Optional[Path], Optional[MediaInfo]]:
    """
    ULTRA FAST video downloader
    YouTube, Instagram, TikTok optimized
    """

    # ╔════════ GENERATE UNIQUE FILE ID ════════╗
    file_id = generate_id()

    output_template = str(TEMP_DIR / f"{file_id}.%(ext)s")
    # ╚═════════════════════════════════════════╝


    # ╔════════ PLATFORM DETECTION ════════╗
    platform = get_platform(url)
    # ╚════════════════════════════════════╝


    # ╔════════ PLATFORM BASED CONFIG ════════╗
    if platform == "instagram":

        opts = {
            'format': 'best[ext=mp4]/best',

            'quiet': True,

            'noplaylist': True,

            'ignoreerrors': True,

            'geo_bypass': True,

            'concurrent_fragment_downloads': 5,

            # instagram speed boost
            'extractor_args': {
                'instagram': {
                    'api_version': 'v1',
                }
            }
        }

    elif platform == "tiktok":

        opts = {
            'format': 'best[ext=mp4]/best',

            'quiet': True,

            'noplaylist': True,

            'ignoreerrors': True,

            'geo_bypass': True,

            'concurrent_fragment_downloads': 5,
        }

    else:
        # YouTube default fast config
        opts = VIDEO_OPTIONS.copy()
    # ╚════════════════════════════════════════╝


    # output template qo‘shish
    opts['outtmpl'] = output_template


    # ╔════════ THREAD POOL DOWNLOAD FUNCTION ════════╗
    def _download():

        try:

            with yt_dlp.YoutubeDL(opts) as ydl:

                info = ydl.extract_info(
                    url,
                    download=True
                )

                return info

        except Exception as e:

            logger.error(f"Video yuklash xatosi: {e}")

            return None
    # ╚═══════════════════════════════════════════════╝


    # ╔════════ RUN DOWNLOAD IN THREAD POOL ════════╗
    loop = asyncio.get_running_loop()

    async with DOWNLOAD_SEMAPHORE:

        info = await loop.run_in_executor(
            EXECUTOR,
            _download
        )
    # ╚═════════════════════════════════════════════╝


    if not info:
        return None, None


    # ╔════════ FAST FILE DETECTION ════════╗
    possible_ext = ['mp4', 'webm', 'mkv', 'avi', 'mov']

    found_path = None

    for ext in possible_ext:

        path = TEMP_DIR / f"{file_id}.{ext}"

        if path.exists():

            found_path = path

            break
    # ╚════════════════════════════════════╝


    if not found_path:
        return None, None


    # ╔════════ BUILD MEDIA INFO ════════╗
    media_info = MediaInfo(

        title=info.get(
            "title",
            "Video"
        )[:100],

        artist=info.get(
            "uploader",
            info.get(
                "channel",
                "Noma'lum"
            )
        )[:50],

        duration=int(
            info.get("duration") or 0
        ),

        thumbnail=info.get(
            "thumbnail"
        ),

        url=url,

        platform=platform
    )
    # ╚══════════════════════════════════╝


    # ╔════════ RETURN RESULT ════════╗
    return found_path, media_info
    # ╚══════════════════════════════╝

# ╚═════════════════════════════════════════════════════════════════════╝




async def convert_to_mp3(input_path: Path) -> Optional[Path]:
    """Faylni MP3 ga convert qilish"""
    output_path = input_path.with_suffix('.mp3')

    cmd = [
        'ffmpeg', '-y', '-i', str(input_path),
        '-vn', '-acodec', 'libmp3lame',
        '-ab', f'{AUDIO_BITRATE}k',
        '-ar', '44100',
        '-ac', '2',
        str(output_path)
    ]

    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL
        )
        await asyncio.wait_for(process.wait(), timeout=300)

        if output_path.exists() and output_path.stat().st_size > 0:
            return output_path
    except asyncio.TimeoutError:
        logger.error("FFmpeg timeout")
    except Exception as e:
        logger.error(f"Convert xatosi: {e}")

    return None

async def extract_audio_from_video(video_path: Path) -> Optional[Path]:
    """Videodan audio ajratish"""
    audio_path = video_path.with_suffix('.mp3')

    cmd = [
        'ffmpeg', '-y', '-i', str(video_path),
        '-vn', '-acodec', 'libmp3lame',
        '-ab', f'{AUDIO_BITRATE}k',
        '-ar', '44100',
        '-ac', '2',
        str(audio_path)
    ]

    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL
        )
        await asyncio.wait_for(process.wait(), timeout=300)

        if audio_path.exists() and audio_path.stat().st_size > 0:
            logger.info(f"Audio ajratildi: {audio_path}")
            return audio_path
    except asyncio.TimeoutError:
        logger.error("Audio ajratish timeout")
    except Exception as e:
        logger.error(f"Audio ajratish xatosi: {e}")

    return None

async def recognize_music(file_path: Path) -> Optional[RecognitionResult]:
    """Musiqani aniqlash (Shazam)"""
    if not SHAZAM_AVAILABLE or not shazam:
        return None

    try:
        result = await shazam.recognize(str(file_path))

        if result and 'track' in result:
            track = result['track']

            # Album ma'lumotini olish
            album = "Noma'lum"
            sections = track.get('sections', [])
            for section in sections:
                if section.get('type') == 'SONG':
                    metadata = section.get('metadata', [])
                    for meta in metadata:
                        if meta.get('title') == 'Album':
                            album = meta.get('text', "Noma'lum")
                            break

            return RecognitionResult(
                title=track.get('title', "Noma'lum"),
                artist=track.get('subtitle', "Noma'lum"),
                album=album,
                genre=track.get('genres', {}).get('primary', "Noma'lum"),
                cover_url=track.get('images', {}).get('coverart'),
                shazam_url=track.get('url')
            )
    except Exception as e:
        logger.error(f"Musiqa aniqlash xatosi: {e}")

    return None


# ╔════════════════ DOWNLOAD QUEUE WORKER ════════════════╗

async def download_queue_worker():
    """
    Queue dan download tasklarni olib bajaradi
    """

    while True:

        callback, video_id = await download_queue.get()

        status_msg = None
        audio_path = None

        try:

            # CACHE check
            cached_audio = get_cached_audio(video_id)

            if cached_audio:

                await callback.message.answer_audio(
                    audio=cached_audio
                )

                continue


            status_msg = await callback.message.answer(
                "⚡ Audio yuklanmoqda..."
            )

            url = f"https://youtube.com/watch?v={video_id}"


            # DOWNLOAD
            audio_path, info = await download_audio(url)

            if not audio_path:

                await status_msg.edit_text(
                    "❌ Audio yuklab bo‘lmadi"
                )

                continue


            # STORAGE
            storage_msg = await bot.send_audio(

                chat_id=STORAGE_GROUP_ID,

                audio=FSInputFile(audio_path),

                title=info.title,

                performer=info.artist

            )


            file_id = storage_msg.audio.file_id


            # CACHE SAVE
            await save_audio_cache(
                video_id,
                file_id
            )


            # SEND USER
            await callback.message.answer_audio(
                audio=file_id
            )


            await status_msg.delete()


        except Exception as e:

            logger.error(f"Queue download error: {e}")

            if status_msg:

                with suppress(Exception):

                    await status_msg.edit_text(
                        "❌ Yuklashda xato"
                    )


        finally:

            if audio_path:

                await cleanup_file(audio_path)

            download_queue.task_done()

# ╚═══════════════════════════════════════════════════════╝

# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║                               KEYBOARDS                                       ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

def get_search_keyboard(results: list) -> InlineKeyboardMarkup:
    """Qidiruv natijalari klaviaturasi"""
    buttons = []

    for result in results[:5]:
        if not result:
            continue

        title = result.get('title', 'Noma\'lum')[:45]
        video_id = result.get('id', '')
        duration = result.get('duration', 0)
        duration_str = format_duration(duration) if duration else ""

        buttons.append([
            InlineKeyboardButton(
                text=f"🎵 {title} [{duration_str}]" if duration_str else f"🎵 {title}",
                callback_data=f"dl:{video_id}"
            )
        ])

    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_url_keyboard(url_hash: str) -> InlineKeyboardMarkup:
    """URL yuklash variantlari"""

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🎬 Video yuklash",
                    callback_data=f"vid:{url_hash}"
                ),
                InlineKeyboardButton(
                    text="🎵 Audio yuklash",
                    callback_data=f"aud:{url_hash}"
                ),
            ],
            [
                InlineKeyboardButton(
                    text="📥 Video + Audio",
                    callback_data=f"both:{url_hash}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🎤 Musiqani aniqlash",
                    callback_data=f"recurl:{url_hash}"
                )
            ]
        ]
    )


def get_media_keyboard(file_hash: str) -> InlineKeyboardMarkup:
    """Telegram video uchun knopkalar"""

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🎤 Musiqani aniqlash",
                    callback_data=f"rec:{file_hash}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🎵 Audio ajratish",
                    callback_data=f"ext:{file_hash}"
                )
            ]
        ]
    )

# ╔════════════════ ADMIN KEYBOARD ════════════════╗
def get_admin_keyboard():

    return InlineKeyboardMarkup(
        inline_keyboard=[

            [
                InlineKeyboardButton(
                    text="📊 Statistika",
                    callback_data="admin_stats"
                )
            ],

            [
                InlineKeyboardButton(
                    text="📢 Majburiy obuna",
                    callback_data="admin_channels"
                )
            ],

            [
                InlineKeyboardButton(
                    text="✉️ Xabar yuborish",
                    callback_data="admin_broadcast"
                )
            ],

            [
                InlineKeyboardButton(
                    text="👥 Referal link",
                    callback_data="admin_ref"
                )
            ],

            [
                InlineKeyboardButton(
                    text="🗄 Ma'lumotlar ombori",
                    callback_data="admin_db"
                )
            ]

        ]
    )
# ╚═══════════════════════════════════════════════╝

# ╔════════════════ SUBSCRIBE KEYBOARD ════════════════╗
def get_subscribe_keyboard(links):

    keyboard = []

    for link in links:

        keyboard.append(
            [
                InlineKeyboardButton(
                    text="📢 Obuna bo‘lish",
                    url=link
                )
            ]
        )


    keyboard.append(
        [
            InlineKeyboardButton(
                text="✅ Tekshirish",
                callback_data="check_sub"
            )
        ]
    )


    return InlineKeyboardMarkup(
        inline_keyboard=keyboard
    )
# ╚════════════════════════════════════════════════════╝


# ╔════════════════ BACK BUTTON ════════════════╗
def get_back_keyboard():

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🔙 Orqaga",
                    callback_data="admin_back"
                )
            ]
        ]
    )
# ╚═════════════════════════════════════════════╝




# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║                              MESSAGE HANDLERS                                 ║
# ╚══════════════════════════════════════════════════════════════════════════════╝



# ╔════════════════ START WITH SUBSCRIBE CHECK ════════════════╗
@router.message(CommandStart())
async def cmd_start(message: Message):

    save_user(message.from_user)


    not_joined = await check_subscriptions(
        message.from_user.id
    )


    if not_joined:

        await message.answer(
            "❌ Botdan foydalanish uchun quyidagi kanalga obuna bo‘ling:",
            reply_markup=get_subscribe_keyboard(not_joined)
        )

        return


    await message.answer(
        WELCOME_MESSAGE.format(
            name=message.from_user.first_name
        )
    )
# ╚════════════════════════════════════════════════════════════╝



@router.message(Command("help"))
async def cmd_help(message: Message):
    """Help komandasi"""
    await message.answer(HELP_MESSAGE)

@router.message(Command("stats"))
async def cmd_stats(message: Message):
    """Statistika"""
    files_count = len(list(TEMP_DIR.glob("*")))
    await message.answer(
        f"📊 <b>Bot statistikasi</b>\n\n"
        f"📁 Vaqtinchalik fayllar: {files_count}\n"
        f"🎵 Shazam: {'✅ Faol' if SHAZAM_AVAILABLE else '❌ O\'chirilgan'}"
    )

# ╔════════════════ CAPTURE BROADCAST MESSAGE ════════════════╗
@router.message(lambda message: message.from_user.id in broadcast_waiting_admin)
async def capture_broadcast_message(message: Message):

    broadcast_waiting_admin.remove(message.from_user.id)

    broadcast_state["message"] = message
    broadcast_state["active"] = True
    broadcast_state["sent"] = 0
    broadcast_state["failed"] = 0

    users = get_active_users()

    broadcast_state["total"] = len(users)
    broadcast_state["pending"] = len(users)

    status_msg = await message.answer(
        "📡 Broadcast boshlanmoqda..."
    )

    asyncio.create_task(
        run_broadcast(status_msg)
    )
# ╚═══════════════════════════════════════════════════════════╝

@router.message(F.text & ~F.text.startswith("/"))
async def handle_text(message: Message):

    # RATE LIMIT CHECK
    if not check_rate_limit(message.from_user.id):

        await message.answer("⏳ Iltimos 2 sekund kuting...")

        return

    text = message.text.strip()

    if is_url(text):
        await handle_url_message(message, text)
    else:
        await handle_search_message(message, text)
# ╔════════════════ ADMIN PANEL COMMAND ════════════════╗
@router.message(Command("admin"))
async def admin_panel(message: Message):

    if message.from_user.id not in ADMINS:
        return

    await message.answer(
        "⚙️ Admin panel",
        reply_markup=get_admin_keyboard()
    )
# ╚════════════════════════════════════════════════════╝



async def handle_search_message(message: Message, query: str):
    """Musiqa qidirish va natijalarni chiqarish"""

    status_msg = await message.answer(
        f"🔍 <b>Qidirilmoqda:</b> {query}"
    )

    try:

        results = await search_youtube(query)

        if not results:
            await status_msg.edit_text(
                "❌ Hech narsa topilmadi"
            )
            return

        text = "🎵 <b>Natijalar:</b>\n\n"

        row1 = []
        row2 = []

        for i, result in enumerate(results[:10], start=1):

            title = result.get("title", "Noma'lum")

            duration = int(result.get("duration") or 0)
            duration_text = format_duration(duration)

            video_id = result.get("id")

            if not video_id:
                continue

            text += f"{i}. {title} ({duration_text})\n"

            button = InlineKeyboardButton(
                text=str(i),
                callback_data=f"dl:{video_id}"
            )

            if i <= 5:
                row1.append(button)
            else:
                row2.append(button)

        keyboard = []

        if row1:
            keyboard.append(row1)

        if row2:
            keyboard.append(row2)

        await status_msg.edit_text(
            text,
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=keyboard
            )
        )

    except Exception as e:

        logger.error(f"Search error: {e}")

        await status_msg.edit_text(
            f"❌ Xatolik yuz berdi\n\n{e}"
        )


async def handle_url_message(message: Message, url: str):
    """URL orqali yuklash (VIDEO CACHE + STORAGE SYSTEM)"""

    platform = get_platform(url)

    if not platform:
        await message.answer(
            ERROR_MESSAGE.format(error="Bu platforma qo'llab-quvvatlanmaydi")
        )
        return

    # URL hash
    url_hash = hash_url(url)
    url_cache[url_hash] = url

    status_msg = await message.answer(
        DOWNLOADING_MESSAGE.format(
            status=f"📥 {platform.title()} dan yuklanmoqda..."
        )
    )

    await bot.send_chat_action(message.chat.id, ChatAction.UPLOAD_VIDEO)

    try:

        # video unique id
        video_id = hash_url(url)

        # CACHE check
        cached_file_id = get_cached_video(video_id)

        if cached_file_id:

            await status_msg.delete()

            await message.answer_video(
                video=cached_file_id,
                caption=f"🎬 <b>Cached video</b>\n📱 {platform.title()}",
                supports_streaming=True,
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[
                        [
                            InlineKeyboardButton(
                                text="🎤 Musiqani aniqlash",
                                callback_data=f"recurl:{url_hash}"
                            )
                        ]
                    ]
                )
            )

            return

        # download video
        video_path, video_info = await download_video(url)

        if video_path and video_path.exists() and video_info:

            duration = int(video_info.duration) if video_info.duration else None

            await status_msg.edit_text(
                DOWNLOADING_MESSAGE.format(status="💾 Storage ga saqlanmoqda...")
            )

            # STORAGE GROUP ga yuborish
            storage_msg = await bot.send_video(
                chat_id=STORAGE_GROUP_ID,
                video=FSInputFile(video_path),
                caption=video_info.title,
                supports_streaming=True
            )

            file_id = storage_msg.video.file_id

            print("VIDEO STORAGE SAVED:", file_id)

            # DATABASE ga yozish
            save_video_cache(video_id, file_id)

            await status_msg.edit_text(
                DOWNLOADING_MESSAGE.format(status="📤 Video yuborilmoqda...")
            )

            # USER ga yuborish (FAQAT BITTA KNOPKA)
            await message.answer_video(
                video=file_id,
                caption=f"🎬 <b>{video_info.title}</b>\n📱 {platform.title()}",
                duration=duration,
                supports_streaming=True,
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[
                        [
                            InlineKeyboardButton(
                                text="🎤 Musiqani aniqlash",
                                callback_data=f"recurl:{url_hash}"
                            )
                        ]
                    ]
                )
            )

            await status_msg.delete()
            await cleanup_file(video_path)

        else:

            await status_msg.edit_text(
                ERROR_MESSAGE.format(error="Video yuklab bo'lmadi")
            )

    except Exception as e:

        logger.error(f"URL yuklash xatosi: {e}")

        await status_msg.edit_text(
            ERROR_MESSAGE.format(error=str(e))
        )




@router.message(F.video | F.video_note)
async def handle_video_message(message: Message):
    """Video xabar"""
    video = message.video or message.video_note
    file_hash = hash_url(video.file_id)
    media_cache[file_hash] = video.file_id

    await message.reply(
        "🎬 <b>Video qabul qilindi!</b>\n\n"
        "Nima qilishni xohlaysiz?",
        reply_markup=get_media_keyboard(file_hash)
    )

@router.message(F.audio | F.voice)
async def handle_audio_message(message: Message):
    """Audio xabar - avtomatik aniqlash"""
    audio = message.audio or message.voice

    if not SHAZAM_AVAILABLE:
        await message.reply(
            "❌ Musiqa aniqlash funksiyasi mavjud emas.\n"
            "shazamio kutubxonasini o'rnating."
        )
        return

    status_msg = await message.reply("🎤 <b>Musiqa aniqlanmoqda...</b>")

    try:
        # Faylni yuklash
        file = await bot.get_file(audio.file_id)
        file_path = TEMP_DIR / f"{generate_id()}.mp3"
        await bot.download_file(file.file_path, file_path)

        # Aniqlash
        result = await recognize_music(file_path)

        if result:
            extra = ""
            if result.shazam_url:
                extra = f"🔗 <a href='{result.shazam_url}'>Shazamda ochish</a>"

            await status_msg.edit_text(
                RECOGNITION_MESSAGE.format(
                    title=result.title,
                    artist=result.artist,
                    album=result.album,
                    genre=result.genre,
                    extra=extra
                ),
                disable_web_page_preview=True
            )
        else:
            await status_msg.edit_text(
                "❌ <b>Musiqani aniqlab bo'lmadi</b>\n\n"
                "Iltimos, aniqroq yoki uzunroq audio yuboring."
            )

        await cleanup_file(file_path)

    except Exception as e:
        logger.error(f"Audio aniqlash xatosi: {e}")
        await status_msg.edit_text(
            ERROR_MESSAGE.format(error=f"Xato: {str(e)[:50]}")
        )


# ╔════════════════ CHANNEL ADD START ════════════════╗
@router.callback_query(F.data == "channel_add")
async def channel_add(callback: CallbackQuery):

    if callback.from_user.id not in ADMINS:
        return

    channel_add_state[callback.from_user.id] = "wait_id"

    await callback.message.edit_text(
        "📢 Kanal ID ni yuboring:\n\nMisol: -1001234567890"
    )
# ╚═══════════════════════════════════════════════════╝

# ╔════════════════ CHANNEL REMOVE MENU ════════════════╗
@router.callback_query(F.data == "channel_remove")
async def channel_remove(callback: CallbackQuery):

    if callback.from_user.id not in ADMINS:
        return

    channels = get_channels()

    keyboard = []

    for channel_id, link in channels:

        keyboard.append(
            [
                InlineKeyboardButton(
                    text=link,
                    callback_data=f"remove:{channel_id}"
                )
            ]
        )

    keyboard.append(
        [
            InlineKeyboardButton(
                text="🔙 Orqaga",
                callback_data="admin_channels"
            )
        ]
    )

    await callback.message.edit_text(
        "O‘chirish uchun kanalni tanlang:",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=keyboard
        )
    )
# ╚════════════════════════════════════════════════════╝

# ╔════════════════ CHANNEL REMOVE ACTION ════════════════╗
@router.callback_query(F.data.startswith("remove:"))
async def remove_channel_callback(callback: CallbackQuery):

    if callback.from_user.id not in ADMINS:
        return

    channel_id = callback.data.split(":")[1]

    remove_channel(channel_id)

    await callback.answer("✅ Kanal o‘chirildi")

    await admin_channels(callback)
# ╚══════════════════════════════════════════════════════╝

# ╔════════════════ CHANNEL ADD PROCESS (FIXED SAFE VERSION) ════════════════╗
@router.message(F.text)
async def channel_add_process(message: Message):

    # faqat admin uchun
    if message.from_user.id not in ADMINS:
        return

    state = channel_add_state.get(message.from_user.id)

    if not state:
        return


    # STEP 1: CHANNEL ID
    if state == "wait_id":

        channel_add_state[message.from_user.id] = {
            "id": message.text.strip(),
            "state": "wait_link"
        }

        await message.answer(
            "🔗 Kanal linkini yuboring:\n\nMisol:\nhttps://t.me/kanal"
        )

        return


    # STEP 2: CHANNEL LINK
    if isinstance(state, dict) and state["state"] == "wait_link":

        channel_id = state["id"]
        channel_link = message.text.strip()

        add_channel(channel_id, channel_link)

        del channel_add_state[message.from_user.id]

        await message.answer(
            "✅ Kanal muvaffaqiyatli qo‘shildi!"
        )

        return
# ╚═══════════════════════════════════════════════════════════════════════════╝


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║                             CALLBACK HANDLERS                                 ║
# ╚══════════════════════════════════════════════════════════════════════════════╝



# ╔════════════════ ADMIN CHANNEL MENU ════════════════╗
@router.callback_query(F.data == "admin_channels")
async def admin_channels(callback: CallbackQuery):

    if callback.from_user.id not in ADMINS:
        return

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[

            [
                InlineKeyboardButton(
                    text="➕ Kanal qo‘shish",
                    callback_data="channel_add"
                )
            ],

            [
                InlineKeyboardButton(
                    text="➖ Kanal o‘chirish",
                    callback_data="channel_remove"
                )
            ],

            [
                InlineKeyboardButton(
                    text="🔙 Orqaga",
                    callback_data="admin_back"
                )
            ]
        ]
    )

    await callback.message.edit_text(
        "📢 Majburiy obuna sozlamalari:",
        reply_markup=keyboard
    )
# ╚════════════════════════════════════════════════════╝


# ╔════════════════ CHECK SUB CALLBACK ════════════════╗
@router.callback_query(F.data == "check_sub")
async def check_sub(callback: CallbackQuery):

    not_joined = await check_subscriptions(
        callback.from_user.id
    )


    if not not_joined:

        await callback.message.edit_text(
            "✅ Obuna tasdiqlandi!"
        )

        await callback.message.answer(
            WELCOME_MESSAGE.format(
                name=callback.from_user.first_name
            )
        )

    else:

        await callback.answer(
            "❌ Hali obuna bo‘lmagansiz",
            show_alert=True
        )

# ╚════════════════════════════════════════════════════╝



# ╔════════════════ ADMIN STATISTICS CALLBACK (BLUE STYLE) ════════════════╗
@router.callback_query(F.data == "admin_stats")
async def admin_stats(callback: CallbackQuery):

    if callback.from_user.id not in ADMINS:
        return


    active, day, week, month, total = get_statistics()


    text = f"""
📊 <b>Bot statistikasi</b>

Botdagi faol obunachilar soni: <code>{active}</code>

Oxirgi 24 soat ichida kirganlar: <code>{day}</code>
Oxirgi 7 kun ichida kirganlar: <code>{week}</code>
Oxirgi 30 kun ichida kirganlar: <code>{month}</code>

Jami botdagi foydalanuvchilar soni: <code>{total}</code>

📅 Sana: <code>{datetime.now().strftime("%Y-%m-%d %H:%M")}</code>
"""


    await callback.message.edit_text(
        text,
        reply_markup=get_back_keyboard()
    )

# ╚════════════════════════════════════════════════════════════════════════╝

# ╔════════════════ ADMIN BACK BUTTON ════════════════╗
@router.callback_query(F.data == "admin_back")
async def admin_back(callback: CallbackQuery):

    if callback.from_user.id not in ADMINS:
        return

    await callback.message.edit_text(
        "⚙️ Admin panel",
        reply_markup=get_admin_keyboard()
    )
# ╚═══════════════════════════════════════════════════╝



# ╔════════════════ AUDIO DOWNLOAD CALLBACK (QUEUE VERSION) ════════════════╗
@router.callback_query(F.data.startswith("dl:"))
async def callback_download(callback: CallbackQuery):

    video_id = callback.data.split(":")[1]

    await callback.answer(
        "📥 Navbatga qo‘shildi"
    )

    await add_to_download_queue(
        callback,
        video_id
    )
# ╚══════════════════════════════════════════════════════════════════════════╝

    # ╔════════ CACHE CHECK FIRST (INSTANT SEND) ════════╗
    cached_audio = get_cached_audio(video_id)

    if cached_audio:

        await callback.message.answer_audio(
            audio=cached_audio
        )

        return
    # ╚══════════════════════════════════════════════════╝


    status_msg = await callback.message.answer(
        "⚡ Audio yuklanmoqda..."
    )


    url = f"https://youtube.com/watch?v={video_id}"


    try:

        # ╔════════ FAST DOWNLOAD ════════╗
        audio_path, info = await download_audio(url)

        if not audio_path:

            await status_msg.edit_text(
                "❌ Audio yuklab bo‘lmadi"
            )

            return
        # ╚══════════════════════════════╝


        # ╔════════ SEND TO STORAGE FIRST ════════╗
        storage_msg = await bot.send_audio(

            chat_id=STORAGE_GROUP_ID,

            audio=FSInputFile(audio_path),

            title=info.title,

            performer=info.artist

        )

        file_id = storage_msg.audio.file_id
        # ╚══════════════════════════════════════╝


        # ╔════════ SAVE CACHE ════════╗
        await save_audio_cache(video_id, file_id)
        # ╚═══════════════════════════╝


        # ╔════════ SEND TO USER (INSTANT) ════════╗
        await callback.message.answer_audio(
            audio=file_id
        )
        # ╚═══════════════════════════════════════╝


        await cleanup_file(audio_path)

        await status_msg.delete()


    except Exception as e:

        logger.error(e)

        await status_msg.edit_text(
            "❌ Xatolik yuz berdi"
        )

# ╚═══════════════════════════════════════════════════════════════════╝


@router.callback_query(F.data.startswith("vid:"))
async def callback_video_download(callback: CallbackQuery):

    url_hash = callback.data.split(":")[1]

    url = url_cache.get(url_hash)

    if not url:
        await callback.answer("❌ URL topilmadi", show_alert=True)
        return

    await callback.answer()

    video_id = hash_url(url)

    # CACHE check
    cached_file_id = get_cached_video(video_id)

    if cached_file_id:

        await callback.message.answer_video(
            video=cached_file_id
        )

        return

    status_msg = await callback.message.answer("📥 Video yuklanmoqda...")

    try:

        video_path, info = await download_video(url)

        if not video_path:

            await status_msg.edit_text("❌ Yuklab bo‘lmadi")
            return

        # STORAGE GROUP ga yuborish
        storage_msg = await bot.send_video(
            chat_id=STORAGE_GROUP_ID,
            video=FSInputFile(video_path),
            caption=info.title
        )

        file_id = storage_msg.video.file_id

        # CACHE save
        save_video_cache(video_id, file_id)

        # USER ga yuborish
        await callback.message.answer_video(
            video=file_id
        )

        await cleanup_file(video_path)

        await status_msg.delete()

    except Exception as e:

        logger.error(e)

        await status_msg.edit_text("❌ Xatolik yuz berdi")


@router.callback_query(F.data.startswith("ext:"))
async def callback_extract(callback: CallbackQuery):
    """Videodan audio ajratish"""

    file_hash = callback.data.split(":")[1]
    file_id = media_cache.get(file_hash)

    if not file_id:
        await callback.answer("❌ Fayl topilmadi", show_alert=True)
        return

    await callback.answer("🎵 Audio ajratilmoqda...")

    status_msg = await callback.message.answer(
        DOWNLOADING_MESSAGE.format(status="📥 Video yuklanmoqda...")
    )

    try:

        file = await bot.get_file(file_id)

        video_path = TEMP_DIR / f"{generate_id()}.mp4"

        await bot.download_file(file.file_path, video_path)

        await status_msg.edit_text(
            DOWNLOADING_MESSAGE.format(status="🎵 Audio ajratilmoqda...")
        )

        audio_path = await extract_audio_from_video(video_path)

        if audio_path and audio_path.exists():

            await callback.message.answer_audio(
                audio=FSInputFile(audio_path, filename="audio.mp3"),
                caption="🎵 <b>Audio ajratildi!</b>"
            )

            await status_msg.delete()

        else:

            await status_msg.edit_text(
                ERROR_MESSAGE.format(error="Audio ajratib bo'lmadi")
            )

        await cleanup_files(video_path, audio_path)

    except Exception as e:

        logger.error(f"Audio ajratish xatosi: {e}")

        await status_msg.edit_text(
            ERROR_MESSAGE.format(error=str(e)[:50])
        )


# ╔════════════════ FINAL SAFE RECOGNIZE CALLBACK ════════════════╗
@router.callback_query(F.data.startswith("rec:"))
async def callback_recognize(callback: CallbackQuery):

    if not SHAZAM_AVAILABLE:
        await callback.answer("❌ Shazam mavjud emas", show_alert=True)
        return


    file_hash = callback.data.split(":")[1]

    file_id = media_cache.get(file_hash)


    if not file_id:
        await callback.answer("❌ Video topilmadi", show_alert=True)
        return


    await callback.answer("🎤 Aniqlanmoqda...")


    status_msg = await callback.message.answer(
        "📥 Video yuklanmoqda..."
    )


    video_path = None
    audio_path = None


    try:

        # ╔════════ CACHE CHECK FIRST ════════╗
        cached = get_cached_recognition(file_hash)

        if cached:

            query = f"{cached.title} {cached.artist}"

            results = await search_youtube(query)

            await send_search_results(status_msg, results)

            return
        # ╚══════════════════════════════════╝


        # ╔════════ DOWNLOAD VIDEO ════════╗
        file = await bot.get_file(file_id)

        video_path = TEMP_DIR / f"{generate_id()}.mp4"

        await bot.download_file(
            file.file_path,
            video_path
        )
        # ╚════════════════════════════════╝


        await status_msg.edit_text(
            "🎵 Audio ajratilmoqda..."
        )


        # ╔════════ EXTRACT AUDIO (IMPORTANT FIX) ════════╗
        audio_path = await extract_audio_from_video(video_path)

        if not audio_path or not audio_path.exists():

            await status_msg.edit_text(
                "❌ Audio ajratib bo‘lmadi"
            )

            return
        # ╚══════════════════════════════════════════════╝


        await status_msg.edit_text(
            "🎤 Musiqa aniqlanmoqda..."
        )


        # ╔════════ RECOGNIZE ════════╗
        result = await recognize_music(audio_path)

        if not result:

            await status_msg.edit_text(
                "❌ Musiqa aniqlanmadi"
            )

            return
        # ╚═══════════════════════════╝


        # ╔════════ SAVE CACHE (SAFE) ════════╗
        save_recognition_cache(
            file_hash,
            result.title,
            result.artist
        )
        # ╚══════════════════════════════════╝


        query = f"{result.title} {result.artist}"


        await status_msg.edit_text(
            f"🎤 <b>Aniqlandi:</b>\n"
            f"{result.title} — {result.artist}\n\n"
            f"🔍 Qidirilmoqda..."
        )


        results = await search_youtube(query)


        await send_search_results(
            status_msg,
            results
        )


    except Exception as e:

        logger.error(e)

        await status_msg.edit_text(
            "❌ Xatolik yuz berdi"
        )


    finally:

        await cleanup_files(video_path, audio_path)

# ╚════════════════════════════════════════════════════════════╝




# ╔════════════════ ULTRA FAST RECOGNIZE (URL) ════════════════╗
@router.callback_query(F.data.startswith("recurl:"))
async def callback_recognize_url(callback: CallbackQuery):

    if not SHAZAM_AVAILABLE:
        await callback.answer("❌ Shazam mavjud emas", show_alert=True)
        return


    url_hash = callback.data.split(":")[1]

    url = url_cache.get(url_hash)


    if not url:
        await callback.answer("❌ URL topilmadi", show_alert=True)
        return


    await callback.answer("🎤 Aniqlanmoqda...")


    status_msg = await callback.message.answer(
        "⚡ Tekshirilmoqda..."
    )


    video_path = None
    audio_path = None


    try:

        # ╔════════ CACHE CHECK ════════╗
        cached = get_cached_recognition(url_hash)

        if cached:

            query = f"{cached.title} {cached.artist}"

            results = await search_youtube(query)

            await send_search_results(
                status_msg,
                results
            )

            return
        # ╚═════════════════════════════╝


        # ╔════════ DOWNLOAD VIDEO ════════╗
        video_path, info = await download_video(url)

        if not video_path:

            await status_msg.edit_text(
                "❌ Video yuklab bo‘lmadi"
            )

            return
        # ╚════════════════════════════════╝


        await status_msg.edit_text(
            "🎵 Audio ajratilmoqda..."
        )


        # ╔════════ EXTRACT AUDIO ════════╗
        audio_path = await extract_audio_from_video(
            video_path
        )
        # ╚═══════════════════════════════╝


        if not audio_path:

            await status_msg.edit_text(
                "❌ Audio ajratib bo‘lmadi"
            )

            return


        await status_msg.edit_text(
            "🎤 Musiqa aniqlanmoqda..."
        )


        result = await recognize_music(audio_path)


        if not result:

            await status_msg.edit_text(
                "❌ Musiqa aniqlanmadi"
            )

            return


        # ╔════════ SAVE CACHE ════════╗
        save_recognition_cache(
            url_hash,
            result.title,
            result.artist
        )
        # ╚════════════════════════════╝


        query = f"{result.title} {result.artist}"


        await status_msg.edit_text(
            f"🎤 <b>Aniqlandi:</b>\n"
            f"{result.title} — {result.artist}\n\n"
            f"⚡ Natijalar yuklanmoqda..."
        )


        results = await search_youtube(query)


        await send_search_results(
            status_msg,
            results
        )


    except Exception as e:

        logger.error(e)

        await status_msg.edit_text(
            "❌ Xatolik yuz berdi"
        )


    finally:

        await cleanup_files(video_path, audio_path)

# ╚═══════════════════════════════════════════════════════════╝


# ╔════════════════ BROADCAST BUTTON ════════════════╗
@router.callback_query(F.data == "admin_broadcast")
async def admin_broadcast(callback: CallbackQuery):

    if callback.from_user.id not in ADMINS:
        return

    # agar broadcast ishlayotgan bo‘lsa
    if broadcast_state["active"]:

        text = f"""
📡 <b>Broadcast Status</b>

Status: <b>yuborilayapti</b>

Yuborilganlar: <code>{broadcast_state['sent']}</code>
Yuborilmaganlar: <code>{broadcast_state['failed']}</code>
Kutilayotganlar: <code>{broadcast_state['pending']}</code>
"""

        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="⛔ To‘xtatish",
                        callback_data="broadcast_stop"
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="🔙 Orqaga",
                        callback_data="admin_back"
                    )
                ]
            ]
        )

        await callback.message.edit_text(text, reply_markup=keyboard)
        return


    broadcast_waiting_admin.add(callback.from_user.id)

    await callback.message.edit_text(
        "✉️ Yubormoqchi bo‘lgan xabarni yuboring:",
        reply_markup=get_back_keyboard()
    )
# ╚══════════════════════════════════════════════════╝


# ╔════════════════ STOP BROADCAST ════════════════╗
@router.callback_query(F.data == "broadcast_stop")
async def stop_broadcast(callback: CallbackQuery):

    if callback.from_user.id not in ADMINS:
        return

    broadcast_state["active"] = False

    await callback.answer("⛔ Broadcast to‘xtatildi")

    await callback.message.edit_text(
        "⛔ Broadcast to‘xtatildi",
        reply_markup=get_back_keyboard()
    )
# ╚══════════════════════════════════════════════════╝


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║                              ERROR HANDLER                                    ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

from aiogram.types import ErrorEvent

@router.error()
async def error_handler(event: ErrorEvent):
    exception = event.exception

    logger.error(
        f"Global xato: {exception}",
        exc_info=True
    )

    return True



# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║                              MAIN FUNCTION                                    ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

async def on_startup(bot: Bot):
    """Bot ishga tushganda"""
    logger.info("=" * 50)
    logger.info("🎵 Music Bot ishga tushdi!")
    logger.info(f"📁 Temp papka: {TEMP_DIR.absolute()}")
    logger.info(f"🎤 Shazam: {'✅ Faol' if SHAZAM_AVAILABLE else '❌ Ochirilgan'}")
    logger.info("=" * 50)

    # Eski fayllarni tozalash
    await cleanup_old_files()


    # ╔════════ START DOWNLOAD WORKERS ════════╗

    global download_workers_started

    if not download_workers_started:

        for _ in range(MAX_DOWNLOAD_WORKERS):

            asyncio.create_task(
                download_queue_worker()
            )

        download_workers_started = True

    # ╚═══════════════════════════════════════╝

async def on_shutdown(bot: Bot):
    """Bot to'xtaganda"""
    logger.info("Bot to'xtatilmoqda...")

    # Barcha fayllarni tozalash
    for file in TEMP_DIR.glob("*"):
        with suppress(Exception):
            file.unlink()

    logger.info("Bot to'xtatildi")

async def main():
    """Asosiy funksiya"""
    # Event handlerlarni ro'yxatdan o'tkazish
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    # Botni ishga tushirish
    try:
        await dp.start_polling(
            bot,
            allowed_updates=dp.resolve_used_update_types(),
            drop_pending_updates=True
        )
    except Exception as e:
        logger.error(f"Bot ishga tushmadi: {e}")
        raise

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot foydalanuvchi tomonidan to'xtatildi")
    except Exception as e:
        logger.error(f"Kritik xato: {e}")