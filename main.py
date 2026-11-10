"""
Airdrop / oyun bot radari (v3 + Groq)

Otomatik olanlar:
  - Dinledigin gruplarda yeni oyun botu linki yakalar, Turkce rehber yazar, sana ozelden atar.
  - Yeni botu bulunca ona /start yazar, cevabini okur, "ne yapilir" raporu atar (INSPECT=1).
Senin onayinla olanlar (rapordaki butonlar):
  - Botun mesajindaki bir butona bas
  - Istenen kanala katil
  - "Her gun otomatik" rutini ekle (gunde bir /start + o butona basma)
Yapmadigi seyler: mini uygulama ici gorevler, odeme/cuzdan/deposit butonlari, referans uretme.

Komutlar: /add /del /list  /incele botadi  /rutin  /bil botadi  /status
"""

from __future__ import annotations

import faulthandler
import sys

faulthandler.enable()  # ani cokmelerde (segfault) iz birakir
print(f"[BOOT] main.py okunmaya basladi (Python {sys.version.split()[0]})", flush=True)

import asyncio
import hashlib
import json
import os
import random
import re
import time
import unicodedata
from typing import Optional, Set
from urllib.parse import parse_qs, urljoin, urlparse

import aiohttp
from aiohttp import web
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.tl.functions.channels import GetParticipantRequest, JoinChannelRequest
from telethon.tl.functions.messages import ImportChatInviteRequest
from telethon.utils import get_peer_id
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (Application, CommandHandler, CallbackQueryHandler, ContextTypes,
                          MessageHandler, filters)

# ===================== ENV =====================

API_ID = int(os.getenv("API_ID", "0") or 0)
API_HASH = os.getenv("API_HASH", "").strip()
STRING_SESSION = os.getenv("STRING_SESSION", "").strip()

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
_adm_list = [int(x) for x in re.split(r"[,\s;]+", os.getenv("ADMIN_USER_ID", "")) if x.strip().lstrip("-").isdigit()]
ADMIN_USER_ID = _adm_list[0] if _adm_list else int(os.getenv("ADMIN_CHAT_ID", "0") or 0)  # asil sahip (yetki verebilen)
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID", "0") or ADMIN_USER_ID or 0)
ADMIN_IDS = set(_adm_list) | ({ADMIN_USER_ID} if ADMIN_USER_ID else set())  # botu kullanabilen herkes
ADMINS_KEY = os.getenv("ADMINS_KEY", "radar:admins:v1").strip()
ADMINS_FILE = os.getenv("ADMINS_FILE", "/tmp/radar_admins.json")

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile").strip()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip()
DEDUP_TTL = int(os.getenv("DEDUP_TTL", "86400") or 86400)
PORT = int(os.getenv("PORT", "10000") or 10000)

ONLY_BOTS = os.getenv("ONLY_BOTS", "1").strip() != "0"
KEEPALIVE = os.getenv("KEEPALIVE", "1").strip() != "0"
RENDER_URL = os.getenv("RENDER_EXTERNAL_URL", "").strip().rstrip("/")

# v3 ayarlari (hepsi istege bagli)
INSPECT = os.getenv("INSPECT", "1").strip() != "0"                 # yeni botu otomatik incele
INSPECT_MIN_INTERVAL = int(os.getenv("INSPECT_MIN_INTERVAL", "120") or 120)  # iki inceleme arasi sn
INSPECT_HOURLY_MAX = int(os.getenv("INSPECT_HOURLY_MAX", "10") or 10)
INSPECT_WAIT = int(os.getenv("INSPECT_WAIT", "7") or 7)            # /start'tan sonra cevap bekleme sn
JOIN_DAILY_MAX = int(os.getenv("JOIN_DAILY_MAX", "0") or 0)        # 24 saatte en fazla kanal katilimi (0 = sinirsiz)
ROUTINES_ON = os.getenv("ROUTINES", "1").strip() != "0"

SOURCE_CHATS_EXTRA = os.getenv("SOURCE_CHATS_EXTRA", "").strip()
UPSTASH_REDIS_REST_URL = os.getenv("UPSTASH_REDIS_REST_URL", "").strip().rstrip("/")
UPSTASH_REDIS_REST_TOKEN = os.getenv("UPSTASH_REDIS_REST_TOKEN", "").strip()
SOURCES_KEY = os.getenv("SOURCES_KEY", "radar:source_chats:v1").strip()
SOURCES_FILE = os.getenv("SOURCES_FILE", "/tmp/radar_sources.json")
SEEN_KEY = os.getenv("SEEN_KEY", "radar:seen_bots:v1").strip()
SEEN_FILE = os.getenv("SEEN_FILE", "/tmp/radar_seen.json")
SEEN_MAX = int(os.getenv("SEEN_MAX", "3000") or 3000)
ROUTINES_KEY = os.getenv("ROUTINES_KEY", "radar:routines:v1").strip()
ROUTINES_FILE = os.getenv("ROUTINES_FILE", "/tmp/radar_routines.json")
JOINS_KEY = os.getenv("JOINS_KEY", "radar:joins:v1").strip()
JOINS_FILE = os.getenv("JOINS_FILE", "/tmp/radar_joins.json")
AUTOPILOT_KEY = os.getenv("AUTOPILOT_KEY", "radar:autopilot:v1").strip()
AUTOPILOT_FILE = os.getenv("AUTOPILOT_FILE", "/tmp/radar_autopilot.json")
LEAVE_AFTER_HOURS = int(os.getenv("LEAVE_AFTER_HOURS", "180") or 180)   # 7 gun + 12 saat guvenlik payi
AUTOPILOT_MIN_MINUTES = int(os.getenv("AUTOPILOT_MIN_MINUTES", "30") or 30)
AUTOPILOT_MAX_MINUTES = int(os.getenv("AUTOPILOT_MAX_MINUTES", "60") or 60)

# ===================== FILTRE =====================

BOT_LINK_RE = re.compile(r"(?:t\.me|telegram\.me)/([A-Za-z0-9_]{2,}bot)\b", re.I)


def parse_bot_arg(a: str) -> str:
    """'@ad', 'ad' ya da t.me/ad linkinden kullanici adini alir (adi 'bot' ile bitmeyen mini uygulama botlari dahil)."""
    a = (a or "").strip()
    m = re.search(r"(?:t\.me|telegram\.me)/([A-Za-z0-9_]{4,32})", a, re.I)
    name = (m.group(1) if m else a.lstrip("@")).lower()
    return name if re.fullmatch(r"[a-z0-9_]{4,32}", name) else ""

# Kanal / grup linkleri (bot olmayanlar): t.me/kanaladi, t.me/+davetkodu, t.me/joinchat/kod
CH_RE = re.compile(
    r"(?:https?://)?(?:t\.me|telegram\.me)/"
    r"(\+[A-Za-z0-9_-]{6,}|joinchat/[A-Za-z0-9_-]{6,}|[A-Za-z][A-Za-z0-9_]{3,})",
    re.I,
)

LINK_RE = re.compile(
    r"(https?://(?:t\.me|telegram\.me)/[A-Za-z0-9_+/]+|"
    r"https?://(?:www\.)?(?:zealy\.io|galxe\.com|questn\.com|layer3\.xyz|"
    r"crew3\.xyz|intract\.io|taskon\.xyz|whop\.com|"
    r"gumroad\.com|linktr\.ee|bit\.ly|tinyurl\.com)/[^\s]+|"
    r"https?://[^\s]*airdrop[^\s]*)",
    re.I,
)
KEYWORD_RE = re.compile(
    r"\b("
    r"airdrop|air\s*drop|claim|whitelist|wl\b|mint|snapshot|"
    r"free\s*token|testnet|mainnet|points|xp\b|quest|campaign|"
    r"bot\b|mini\s*app|telegram\s*bot|play\s*to\s*earn|p2e|"
    r"аирдроп|раздача|квест|"
    r"ücretsiz|ödül|görev|odul|gorev"
    r")\b",
    re.I,
)

BAD_WORDS = [
    "seed phrase", "secret phrase", "recovery phrase", "mnemonic",
    "private key", "wallet connect", "connect wallet", "connect your wallet",
    "deposit", "cüzdan bağla", "yatırım yap",
]

# Bu kelimeleri iceren butonlara bot ASLA basmaz (ve onay butonu da koymaz)
DANGER_BTN_RE = re.compile(
    r"wallet|cüzdan|cuzdan|deposit|withdraw|çekim|cekim|yatır|yatir|buy|satın|satin|"
    r"\bpay\b|ödeme|odeme|stake|invest|premium|stars|usdt|swap|\bton\b|"
    r"tanıt|tanit|promot|advert|reklam|çekler|cekler|\bchecks?\b|"
    r"оплат|выплат|вывод|куп[ий]|пополн|реклам|продвиж|кошел|депозит|\bчек[иа]?\b|şikayet|sikayet|\breport\b|жалоб|coin",
    re.I,
)


def norm_label(s: str) -> str:
    """Etiketteki degisen sayilari (ornek: 'Kanallar · 446') yok sayarak karsilastirmak icin."""
    return re.sub(r"\s+", " ", re.sub(r"[\d·•.,:%+\-]+", " ", s or "")).strip().lower()

# ===================== STATE =====================

seen: dict[str, float] = {}
ACTIVE_SOURCES: Set[int] = set()
SOURCE_META: dict[int, str] = {}
ACTIONS: dict[str, dict] = {}       # onay bekleyen islemler (bellekte; yeniden baslayinca silinir)
ACTION_N = 0
ROUTINES: dict[str, dict] = {}      # gunluk rutinler (kalici)
INSPECT_TIMES: list = []
INSPECT_COOLDOWN: dict = {}
JOIN_TIMES: list = []
JOINS: dict = {}          # kanal id -> {"t": katilma zamani, "target": ad}  (suresi dolunca cikmak icin)
AUTOPILOT: dict = {}      # {"on": bool, "bot": ad, "steps": [...], "last": zaman}
EXTRA_ADMINS: dict = {}   # sonradan yetki verilenler: id -> {"name": ..., "t": ...}
ADMIN_ASKED: dict = {}    # yetki isteyenler (10 dk tekrar sormasin)
FLOOD_UNTIL = 0.0         # Telegram bekletiyorsa bu zamana kadar katilma denemez
LAST_EMPTY_NOTICE = 0.0
LAST_INSPECT = 0.0
http_session: Optional[aiohttp.ClientSession] = None
tg_client: Optional[TelegramClient] = None
bot_app: Optional[Application] = None
APP_LOCK: Optional[asyncio.Lock] = None      # mini uygulama acma (sohbet islemlerinden bagimsiz)
TG_LOCK: Optional[asyncio.Lock] = None       # Telegram hesabiyla yapilan islemler sirayla
INSPECT_LOCK: Optional[asyncio.Lock] = None  # incelemeler sirayla + aralikli
BG_TASKS: list = []


def spawn(coro):
    t = asyncio.create_task(coro)
    BG_TASKS.append(t)
    t.add_done_callback(lambda x: BG_TASKS.remove(x) if x in BG_TASKS else None)
    return t


def parse_id_list(raw: str) -> list:
    items = []
    for part in re.split(r"[\s,;]+", raw or ""):
        part = part.strip()
        if not part:
            continue
        if re.fullmatch(r"-?\d+", part):
            items.append(int(part))
        else:
            items.append(part.lstrip("@"))
    return items


async def ask_admin_access(user):
    """Yetkisiz biri yazinca asil sahibe 'yetki ver' butonlu istek gonderir (10 dk'da bir)."""
    now = time.time()
    if now - ADMIN_ASKED.get(user.id, 0) < 600:
        return
    ADMIN_ASKED[user.id] = now
    name = " ".join(x for x in (user.first_name, user.last_name) if x) or "?"
    uname = f"@{user.username}" if user.username else "kullanıcı adı yok"
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Yetki ver", callback_data=f"adm:ok:{user.id}"),
        InlineKeyboardButton("❌ Reddet", callback_data=f"adm:no:{user.id}"),
    ]])
    try:
        await bot_app.bot.send_message(
            ADMIN_CHAT_ID,
            f"🔑 Bot kullanım isteği\n{name} ({uname})\nID: {user.id}\n\n"
            f"Yetki verirsen bu hesap botun TÜM komutlarını kullanabilir.",
            reply_markup=kb,
        )
    except Exception as e:
        print("[ADMIN ISTEK]", repr(e))


def admin_only(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        if user and user.id in ADMIN_IDS:
            return await func(update, context)
        if user and update.effective_message:
            await update.effective_message.reply_text(
                f"Yetkin yok. Sahibine erişim isteği gönderdim.\nSenin ID'n: {user.id}")
            await ask_admin_access(user)
    return wrapper


def new_action(d: dict) -> str:
    global ACTION_N
    ACTION_N += 1
    aid = str(ACTION_N)
    ACTIONS[aid] = d
    if len(ACTIONS) > 400:
        for k in list(ACTIONS)[:100]:
            ACTIONS.pop(k, None)
    return aid


# ===================== DEPO =====================

async def upstash_cmd(*cmd):
    if not UPSTASH_REDIS_REST_URL or not UPSTASH_REDIS_REST_TOKEN:
        return None
    assert http_session is not None
    try:
        async with http_session.post(
            UPSTASH_REDIS_REST_URL,
            headers={"Authorization": f"Bearer {UPSTASH_REDIS_REST_TOKEN}"},
            json=list(cmd),
            timeout=aiohttp.ClientTimeout(total=10),
        ) as r:
            data = await r.json()
            return data.get("result")
    except Exception as e:
        print("[UPSTASH]", repr(e))
        return None


def file_read(path: str):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def file_write(path: str, obj):
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(obj, f)
    except Exception as e:
        print("[FILE SAVE]", repr(e))


async def load_json(key: str, path: str):
    raw = await upstash_cmd("GET", key)
    if raw:
        try:
            return json.loads(raw)
        except Exception:
            pass
    return file_read(path)


async def save_json(key: str, path: str, obj):
    file_write(path, obj)
    await upstash_cmd("SET", key, json.dumps(obj))


async def persist_sources():
    await save_json(SOURCES_KEY, SOURCES_FILE, sorted(ACTIVE_SOURCES))


async def load_persisted_sources() -> list:
    data = await load_json(SOURCES_KEY, SOURCES_FILE)
    if isinstance(data, list):
        print("[KAYNAK] yuklendi:", len(data))
        return data
    return []


async def persist_seen():
    bots = {k: v for k, v in seen.items() if k.startswith("bot:")}
    if len(bots) > SEEN_MAX:
        for k, _ in sorted(bots.items(), key=lambda kv: kv[1])[: len(bots) - SEEN_MAX]:
            bots.pop(k, None)
            seen.pop(k, None)
    await save_json(SEEN_KEY, SEEN_FILE, bots)


async def load_seen():
    data = await load_json(SEEN_KEY, SEEN_FILE)
    if isinstance(data, dict):
        for k, v in data.items():
            if str(k).startswith("bot:"):
                seen[k] = float(v)
    print("[GORULEN BOT]", sum(1 for k in seen if k.startswith("bot:")))


async def persist_routines():
    await save_json(ROUTINES_KEY, ROUTINES_FILE, ROUTINES)


async def load_routines():
    data = await load_json(ROUTINES_KEY, ROUTINES_FILE)
    if isinstance(data, dict):
        ROUTINES.update(data)
    print("[RUTIN]", len(ROUTINES))


async def persist_joins():
    await save_json(JOINS_KEY, JOINS_FILE, JOINS)


async def load_joins():
    data = await load_json(JOINS_KEY, JOINS_FILE)
    if isinstance(data, dict):
        JOINS.update(data)
    print("[KATILIM KAYDI]", len(JOINS))


async def persist_autopilot():
    await save_json(AUTOPILOT_KEY, AUTOPILOT_FILE, AUTOPILOT)


async def load_autopilot():
    data = await load_json(AUTOPILOT_KEY, AUTOPILOT_FILE)
    if isinstance(data, dict):
        AUTOPILOT.update(data)
    print("[OTOPILOT]", "acik" if AUTOPILOT.get("on") else "kapali", AUTOPILOT.get("bot", ""))


async def persist_admins():
    await save_json(ADMINS_KEY, ADMINS_FILE, EXTRA_ADMINS)


async def load_admins():
    data = await load_json(ADMINS_KEY, ADMINS_FILE)
    if isinstance(data, dict):
        for k, v in data.items():
            if str(k).lstrip("-").isdigit():
                EXTRA_ADMINS[str(k)] = v if isinstance(v, dict) else {}
                ADMIN_IDS.add(int(k))
    print("[YETKILI]", sorted(ADMIN_IDS))


# ===================== KAYNAKLAR =====================

async def resolve_entity(item):
    assert tg_client is not None
    key = int(item) if str(item).lstrip("-").isdigit() else item
    try:
        return await tg_client.get_entity(key)
    except ValueError:
        if not isinstance(key, int):
            raise
        await tg_client.get_dialogs()
        return await tg_client.get_entity(key)


async def add_source(item) -> str:
    try:
        entity = await resolve_entity(item)
        chat_id = get_peer_id(entity)
    except Exception as e:
        return f"Bulunamadi / hesap uye degil: {item}\n{e}"

    title = getattr(entity, "title", None) or getattr(entity, "username", None) or str(chat_id)
    if chat_id in ACTIVE_SOURCES:
        return f"Zaten listede: {title} ({chat_id})"

    ACTIVE_SOURCES.add(chat_id)
    SOURCE_META[chat_id] = str(title)
    await persist_sources()
    return f"Eklendi: {title}\nID: `{chat_id}`\nToplam: {len(ACTIVE_SOURCES)}"


async def del_source(item) -> str:
    try:
        if str(item).lstrip("-").isdigit():
            chat_id = int(item)
        else:
            entity = await resolve_entity(item)
            chat_id = get_peer_id(entity)
    except Exception as e:
        return f"Silinemedi: {item} ({e})"

    if chat_id not in ACTIVE_SOURCES:
        return f"Listede yok: {chat_id}"
    title = SOURCE_META.pop(chat_id, str(chat_id))
    ACTIVE_SOURCES.discard(chat_id)
    await persist_sources()
    return f"Silindi: {title}\nID: `{chat_id}`\nToplam: {len(ACTIVE_SOURCES)}"


def list_sources_text() -> str:
    if not ACTIVE_SOURCES:
        return "Liste bos.\n\nEkle: /add -1001234567890"
    lines = [f"Dinlenen gruplar ({len(ACTIVE_SOURCES)}):"]
    for i, cid in enumerate(sorted(ACTIVE_SOURCES), 1):
        name = SOURCE_META.get(cid) or str(cid)
        lines.append(f"{i}. {name}\n   `{cid}`")
    lines.append("\nEkle: /add -100...\nSil: /del -100... veya asagidaki buton")
    return "\n".join(lines)


async def enrich_source_titles():
    if not tg_client:
        return
    for cid in list(ACTIVE_SOURCES):
        if SOURCE_META.get(cid):
            continue
        try:
            ent = await resolve_entity(cid)
            SOURCE_META[cid] = (
                getattr(ent, "title", None) or getattr(ent, "username", None) or str(cid)
            )
        except Exception:
            SOURCE_META[cid] = str(cid)


def build_list_keyboard():
    rows = []
    for cid in sorted(ACTIVE_SOURCES):
        name = SOURCE_META.get(cid) or str(cid)
        label = name if len(name) <= 28 else name[:25] + "..."
        rows.append([InlineKeyboardButton(f"Sil: {label}", callback_data=f"del:{cid}")])
    return InlineKeyboardMarkup(rows) if rows else None


# ===================== GEMINI =====================

GUIDE_PROMPT = (
    "Asagidaki Telegram mesaji bir oyun / airdrop botunu tanitiyor. Mesaj HANGI DILDE olursa "
    "olsun cevabi TURKCE yaz. SADECE mesajdaki bilgiyi kullan, hicbir sey uydurma. Format:\n"
    "🎮 Oyun: <ad>\n"
    "📌 Ne yapilir: <1-2 cumle>\n"
    "👣 Baslangic:\n1. ...\n2. ...\n"
    "💰 Token/airdrop: <varsa yaz, yoksa 'belirsiz'>\n"
    "Mesajda bilgi yoksa o satira 'mesajda yok' yaz. En fazla 900 karakter.\n\n"
    "MESAJ:\n"
)

INSPECT_PROMPT = (
    "Asagida bir Telegram oyun/airdrop botunun /start cevabi ve buton adlari var. Metin HANGI "
    "DILDE olursa olsun cevabi TURKCE yaz. SADECE verilen bilgiyi kullan, uydurma. Format:\n"
    "🎮 Bu ne: <1 cumle>\n"
    "✅ Yapilacaklar:\n1. ...\n2. ...\n"
    "⚠️ Dikkat: <cuzdan / odeme / telefon numarasi / ekstra kanal istiyorsa yaz, yoksa 'yok'>\n"
    "En fazla 700 karakter.\n\n"
    "BILGI:\n"
)


async def _groq(prompt_full: str):
    """Groq'tan cevap alir. (metin | None, hata_notu) doner."""
    assert http_session is not None
    last = "Groq hata"
    for attempt in range(2):
        try:
            async with http_session.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
                json={
                    "model": GROQ_MODEL,
                    "messages": [
                        {"role": "system", "content": "Kisa net Turkce yaz. Uydurma."},
                        {"role": "user", "content": prompt_full},
                    ],
                    "temperature": 0.2,
                    "max_tokens": 1024,
                },
                timeout=aiohttp.ClientTimeout(total=45),
            ) as resp:
                data = await resp.json()
                if resp.status in (429, 500, 502, 503, 504):
                    print("[GROQ]", resp.status, "tekrar denenecek")
                    last = f"Groq {resp.status}"
                    await asyncio.sleep(2 + attempt * 4)
                    continue
                if resp.status >= 400:
                    print("[GROQ]", resp.status, str(data)[:300])
                    return None, f"Groq {resp.status}"
                raw = ((data.get("choices") or [{}])[0].get("message", {}).get("content", "") or "").strip()
                return (raw or None), ("" if raw else "Groq bos cevap")
        except Exception as e:
            print("[GROQ EX]", repr(e))
            last = f"Groq {type(e).__name__}"
            await asyncio.sleep(2)
    return None, last


async def _gemini(prompt_full: str):
    """Gemini'den cevap alir (yedek). (metin | None, hata_notu) doner."""
    assert http_session is not None
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
    )
    payload = {
        "contents": [{"parts": [{"text": prompt_full}]}],
        "generationConfig": {"temperature": 0.2, "maxOutputTokens": 1024},
    }
    last = "Gemini hata"
    for attempt in range(3):
        try:
            async with http_session.post(
                url, json=payload, timeout=aiohttp.ClientTimeout(total=60)
            ) as resp:
                data = await resp.json()
                if resp.status in (429, 500, 502, 503, 504):
                    print("[GEMINI]", resp.status, "tekrar denenecek")
                    last = f"Gemini {resp.status}"
                    await asyncio.sleep(3 + attempt * 5)
                    continue
                if resp.status >= 400:
                    print("[GEMINI]", resp.status, str(data)[:200])
                    return None, f"Gemini {resp.status}"
                parts = (data.get("candidates") or [{}])[0].get("content", {}).get("parts", [])
                raw = "\n".join(p.get("text", "") for p in parts).strip()
                return (raw or None), ("" if raw else "Gemini bos cevap")
        except Exception as e:
            print("[GEMINI EX]", repr(e))
            last = f"Gemini {type(e).__name__}"
            await asyncio.sleep(3)
    return None, last


async def ai_guide(text: str, prompt: str = GUIDE_PROMPT) -> str:
    """Once Groq, olmazsa Gemini. Basarisizsa '(' ile baslayan kisa bir hata notu doner."""
    full = prompt + (text or "").strip()[:6000]
    notes = []
    if GROQ_API_KEY:
        raw, note = await _groq(full)
        if raw:
            return raw
        notes.append(note)
    if GEMINI_API_KEY:
        raw, note = await _gemini(full)
        if raw:
            return raw
        notes.append(note)
    if not notes:
        return "(Ozet yok - GROQ_API_KEY / GEMINI_API_KEY yok)"
    return "(Ozet cikarilamadi: " + ", ".join(n for n in notes if n) + ")"


gemini_guide = ai_guide  # eski ad


# ===================== BILDIRIM =====================

def fingerprint(text: str, links: list) -> str:
    base = "|".join(sorted(links)) if links else text[:400]
    return hashlib.sha1(base.encode("utf-8", "ignore")).hexdigest()


def cleanup_seen():
    now = time.time()
    for k in [k for k, ts in seen.items() if k.startswith("fp:") and now - ts > DEDUP_TTL]:
        seen.pop(k, None)


def extract_links(text: str) -> list:
    return list(
        dict.fromkeys(m.group(0).rstrip(").,]>\"'") for m in LINK_RE.finditer(text or ""))
    )


async def send_admin(text: str, kb=None):
    if len(text) > 4000:
        text = text[:3900] + "\n..."
    if bot_app and bot_app.bot:
        await bot_app.bot.send_message(
            ADMIN_CHAT_ID, text, reply_markup=kb, disable_web_page_preview=True
        )
        for uid in list(ADMIN_IDS):
            if uid != ADMIN_CHAT_ID:
                try:
                    await bot_app.bot.send_message(uid, text, reply_markup=kb, disable_web_page_preview=True)
                except Exception:
                    pass  # o hesap botu henuz baslatmamis olabilir
    elif tg_client:
        await tg_client.send_message(ADMIN_CHAT_ID, text, link_preview=False)


async def notify_admin(source_title, text, bots, links, guide, warn):
    lines = ["🆕 YENİ OYUN BULUNDU", f"📍 Grup: {source_title}", ""]
    lines.append(guide or "(Mesajda açıklama yok, sadece link var.)")
    if warn:
        lines += ["", "⚠️ Dikkat, mesajda şu ifadeler geçiyor: " + ", ".join(warn)]
    lines.append("")
    if bots:
        lines += [f"🔗 https://t.me/{b}" for b in bots]
    else:
        lines += [f"🔗 {u}" for u in links[:6]]
    lines += ["", "Orijinal mesaj:", (text or "")[:500]]
    rows = []
    for b in bots[:3]:
        rows.append([InlineKeyboardButton(f"🔍 İncele @{b}"[:60], callback_data=f"ins:{b}")])
        rows.append([InlineKeyboardButton(f"🤖 Aç @{b}"[:60], url=f"https://t.me/{b}")])
    await send_admin("\n".join(lines), InlineKeyboardMarkup(rows) if rows else None)
    print("[BILDIRIM]", source_title, bots or links[:2])


# ===================== BOT INCELEME =====================

def raw_url(b) -> str:
    """Butonun linkini (varsa) dondurur: hem URL hem mini uygulama butonlarinda calisir."""
    return (getattr(b, "url", None) or getattr(getattr(b, "button", None), "url", None) or "") or ""


def classify_button(b) -> str:
    """Buton turunu ozelliklerinden anlar (Telethon surumu/sinif adlari farkli olsa da calisir)."""
    raw = getattr(b, "button", None)
    name = type(raw).__name__.lower()
    url = raw_url(b)
    if "webview" in name or "webapp" in name or getattr(raw, "web_app", None):
        return "webapp"
    if "request" in name or "phone" in name or "geo" in name or "location" in name or "contact" in name:
        return "private"
    if any(x in name for x in ("buy", "game", "copy", "login", "auth", "switch")):
        return "other"  # odeme, oyun, giris, inline degistirme: basilmaz
    if url:
        return "url"
    if "callback" in name or "inline" in name or name == "keyboardbutton" or getattr(raw, "data", None) is not None:
        return "click"
    return "other"


def summarize_msgs(msgs, bot: str) -> dict:
    """msgs: eskiden yeniye. Mesajlardaki metin, buton ve kanal linklerini ayiklar."""
    texts, webs, blocked, privs, chans = [], [], [], [], []
    linkbtns, others = [], []
    total = 0
    clicks: dict[str, int] = {}  # etiket -> mesaj id (ayni etiket varsa en yenisi)
    for m in msgs:
        t = (m.message or "").strip()
        if t:
            texts.append(t[:700])
        urls = [str(e.url) for e in (m.entities or []) if getattr(e, "url", None)]
        urls.append(t)
        for row in (m.buttons or []):
            for b in row:
                total += 1
                label = (b.text or "").strip()
                kind = classify_button(b)
                if kind == "url":
                    u0 = raw_url(b)
                    urls.append(u0)
                    linkbtns.append((label, u0))
                elif kind == "other":
                    others.append((label, type(b.button).__name__))
                elif kind == "webapp":
                    webs.append(label)
                elif kind == "private":
                    privs.append(label)
                elif kind == "click" and label:
                    if DANGER_BTN_RE.search(label):
                        blocked.append(label)
                    else:
                        clicks[label] = m.id
        for u in urls:
            for tgt in CH_RE.findall(u):
                low = tgt.lower()
                if low.endswith("bot") or low == bot.lower() or low in ("share", "proxy", "socks", "addstickers"):
                    continue
                chans.append(tgt)
    return {
        "total": total,
        "linkbtns": linkbtns[:6],
        "others": others[:6],
        "texts": texts,
        "clicks": list(clicks.items()),
        "webs": list(dict.fromkeys(webs)),
        "blocked": list(dict.fromkeys(blocked)),
        "privs": list(dict.fromkeys(privs)),
        "chans": list(dict.fromkeys(chans))[:4],
    }


async def send_report(bot: str, msgs, header: str, routine_label: Optional[str] = None):
    info = summarize_msgs(msgs, bot)
    raw_text = "\n\n".join(info["texts"])
    labels = [l for l, _ in info["clicks"]] + info["webs"] + info["blocked"] + info["privs"]
    combo = raw_text + "\nBUTONLAR: " + ", ".join(labels)
    warn = [w for w in BAD_WORDS if w in combo.lower()]
    guide = await ai_guide(combo, INSPECT_PROMPT) if len(raw_text) >= 20 else ""

    lines = [f"{header}: @{bot}", ""]
    ozet_yok = (not guide) or guide.startswith("(")
    if ozet_yok:
        if guide:
            lines.append(guide)
        lines.append(("Botun mesajı:\n" + raw_text[:700]) if raw_text else "(Bot metin göndermedi.)")
    else:
        lines.append(guide)
    lines.append(f"ℹ️ Bot {len(msgs)} mesaj gönderdi, mesajlarda {info['total']} buton gördüm.")
    if info["total"] == 0:
        lines.append("Not: Çoğu oyun botunun 'Oyna' tuşu mesajda değil, sohbetin altındaki menü tuşunda durur. "
                     "Onu otomatik göremiyorum.")
    if info["clicks"]:
        lines += ["", "▶️ Basılabilir: " + ", ".join(l for l, _ in info["clicks"])]
    if info["webs"]:
        lines.append("📱 Mini uygulama (sen açarsın): " + ", ".join(info["webs"]))
    if info["linkbtns"]:
        lines.append("🔗 Link butonları: " + " | ".join(f"{l} → {u}" for l, u in info["linkbtns"]))
    if info["others"]:
        lines.append("❔ Diğer butonlar: " + ", ".join(f"{l} ({t})" for l, t in info["others"]))
    if info["blocked"]:
        lines.append("⛔ Ödeme/cüzdan butonları atlandı: " + ", ".join(info["blocked"]))
    if info["privs"]:
        lines.append("🚫 Telefon/konum isteyen buton var: " + ", ".join(info["privs"]))
    if warn:
        lines += ["", "⚠️ Dikkat, şu ifadeler geçiyor: " + ", ".join(warn),
                  "Güvenlik için otomatik işlem butonu koymadım."]

    if bot in REFS:
        lines += ["", f"🔗 Senin referans linkin: {REFS[bot]['link']}"]

    rows = []
    if not warn:
        n_tasks, task_msg = 0, None
        for m_ in msgs:
            tk = parse_tasks(m_)
            if tk:
                n_tasks, task_msg = len(tk), m_
        if n_tasks and task_msg is not None:
            aid = new_action({"t": "autotasks", "bot": bot, "msg_id": task_msg.id, "cap": 0})
            rows.append([InlineKeyboardButton(f"🤖 Görevleri otomatik yap ({n_tasks}+ görev, sayfaları gezer)", callback_data=f"a:{aid}")])
        if routine_label:
            aid = new_action({"t": "routine", "bot": bot, "label": routine_label})
            rows.append([InlineKeyboardButton(f"🔁 Her gün otomatik: {routine_label[:22]}", callback_data=f"a:{aid}")])
        for label, mid in info["clicks"][:8]:
            aid = new_action({"t": "click", "bot": bot, "msg_id": mid, "label": label})
            rows.append([InlineKeyboardButton(f"▶️ Bas: {label[:28]}", callback_data=f"a:{aid}")])
        for tgt in info["chans"]:
            aid = new_action({"t": "join", "target": tgt})
            rows.append([InlineKeyboardButton(f"📢 Katıl: {tgt[:22]}", callback_data=f"a:{aid}")])
    if not warn and bot not in REFS:
        aid = new_action({"t": "findref", "bot": bot})
        rows.append([InlineKeyboardButton("🔗 Referans linkimi bul", callback_data=f"a:{aid}")])
    rows.append([InlineKeyboardButton("🤖 Botu aç", url=f"https://t.me/{bot}")])
    await send_admin("\n".join(lines), InlineKeyboardMarkup(rows))


async def fetch_incoming(ent, after_id: int, limit: int = 8):
    assert tg_client is not None
    msgs = [m for m in await tg_client.get_messages(ent, limit=limit) if not m.out and m.id >= after_id]
    msgs.reverse()
    for m in msgs:
        try:
            await m.get_buttons()
        except Exception:
            pass
    return msgs


async def inspect_bot(username: str, start: str = ""):
    """Bota /start yazar, cevabini okur, rapor gonderir."""
    global LAST_INSPECT
    assert tg_client is not None
    try:
        t0 = time.time()
        left = INSPECT_MIN_INTERVAL - (t0 - INSPECT_COOLDOWN.get(username, 0))
        if left > 0:
            await send_admin(f"⏳ @{username} az önce incelendi, {int(left)} sn sonra tekrar dene.")
            return
        INSPECT_COOLDOWN[username] = t0
        async with INSPECT_LOCK:  # incelemeler sirayla ve aralikli
            now = time.time()
            INSPECT_TIMES[:] = [t for t in INSPECT_TIMES if now - t < 3600]
            if len(INSPECT_TIMES) >= INSPECT_HOURLY_MAX:
                await send_admin(
                    f"⏸ @{username} incelenmedi: saatlik limit ({INSPECT_HOURLY_MAX}) doldu.\n"
                    f"Biraz sonra /incele {username} yaz."
                )
                return
            wait = INSPECT_MIN_INTERVAL - (now - LAST_INSPECT)
            if wait > 0:
                await asyncio.sleep(wait)
            async with TG_LOCK:
                ent = await resolve_entity(username)
                if not getattr(ent, "bot", False):
                    await send_admin(f"ℹ️ @{username} bir bot değil (kanal, grup ya da kişi). /start yazmadım.")
                    return
                sent = await tg_client.send_message(ent, ("/start " + start).strip())
                LAST_INSPECT = time.time()
                INSPECT_TIMES.append(LAST_INSPECT)
                await asyncio.sleep(INSPECT_WAIT)
                msgs = await fetch_incoming(ent, sent.id + 1)
        if not msgs:
            await send_admin(f"🔍 @{username} /start'a cevap vermedi.")
            return
        await send_report(username, msgs, "🔍 İNCELEME")
    except Exception as e:
        print("[INSPECT]", repr(e))
        try:
            await send_admin(f"⚠️ @{username} incelenemedi: {e}")
        except Exception:
            pass


async def do_click(bot: str, msg_id: int, label: str):
    """Onaylanan butona basar. (yeni_mesajlar, not) doner."""
    assert tg_client is not None
    ent = await resolve_entity(bot)
    msg = await tg_client.get_messages(ent, ids=msg_id)
    if not msg:
        return None, "Mesaj bulunamadı (silinmiş olabilir). /incele ile yeniden bak."
    try:
        await msg.get_buttons()
    except Exception:
        pass
    def match(b):
        t = (b.text or "").strip()
        return t == label or (norm_label(t) != "" and norm_label(t) == norm_label(label))

    if not any(match(b) for row in (msg.buttons or []) for b in row):
        return None, "Buton artık yok (bot mesajı değiştirmiş). /incele ile yeniden bak."
    await asyncio.sleep(random.uniform(1.5, 4))
    try:
        await msg.click(filter=match)
    except Exception as e:
        return None, f"Basılamadı: {e}"
    await asyncio.sleep(4)
    return await fetch_incoming(ent, msg_id), "ok"


async def was_member(ent) -> bool:
    """Kanala zaten uye miydik? (7 gun sonra yalniz KENDI katildigim kanallardan cikmak icin)"""
    assert tg_client is not None
    try:
        await tg_client(GetParticipantRequest(channel=ent, participant="me"))
        return True
    except Exception as e:
        if "NotParticipant" in type(e).__name__:
            return False
        return getattr(ent, "left", None) is False  # emin degilsek: 'left' bayragina bak


async def do_join(target: str) -> str:
    global FLOOD_UNTIL
    assert tg_client is not None
    now = time.time()
    JOIN_TIMES[:] = [t for t in JOIN_TIMES if now - t < 86400]
    if JOIN_DAILY_MAX > 0 and len(JOIN_TIMES) >= JOIN_DAILY_MAX:
        return f"Günlük katılım limiti doldu ({JOIN_DAILY_MAX}). Hesabı korumak için yarın dene."
    pid = None
    try:
        await asyncio.sleep(random.uniform(2, 6))
        if target.startswith("+") or target.lower().startswith("joinchat/"):
            code = target.lstrip("+")
            if code.lower().startswith("joinchat/"):
                code = code[9:]
            res = await tg_client(ImportChatInviteRequest(code))
            chats = getattr(res, "chats", None) or []
            if chats:
                pid = get_peer_id(chats[0])
        else:
            ent = await tg_client.get_entity(target)
            member_before = await was_member(ent)
            await tg_client(JoinChannelRequest(ent))
            pid = None if member_before else get_peer_id(ent)  # zaten uyeysem kaydetme (sonra cikmayayim)
        JOIN_TIMES.append(time.time())
        if pid is not None:  # 7 gun sonra cikabilmek icin kaydet
            JOINS[str(pid)] = {"t": time.time(), "target": target}
            await persist_joins()
        return "Katıldım ✅"
    except Exception as e:
        name = type(e).__name__
        if "FloodWait" in name:
            sec = int(getattr(e, "seconds", 0) or 0)
            FLOOD_UNTIL = time.time() + sec
            return f"Telegram şimdilik bekletiyor: yaklaşık {max(1, sec // 60)} dk sonra tekrar dene."
        if "InviteRequestSent" in name:
            return "Katılma isteği gönderildi (kanal onay istiyor), atladım."
        if "AlreadyParticipant" in name:
            return "Katıldım ✅ (zaten üyeydin)"
        if "TooMuch" in name:
            return "Hesap Telegram'ın kanal/grup üyelik sınırına ulaştı, bazı kanallardan çıkman gerekir."
        return f"Katılamadım: {name} {e}"


async def handle_action(act: dict):
    t = act.get("t")
    if t == "click":
        async with TG_LOCK:
            new, note = await do_click(act["bot"], act["msg_id"], act["label"])
        if new is None:
            await send_admin(f"⚠️ @{act['bot']}: {note}")
            return
        if not new:
            await send_admin(f"✅ @{act['bot']}: '{act['label']}' basıldı, yeni mesaj gelmedi.")
            return
        await send_report(act["bot"], new, f"✅ '{act['label'][:24]}' basıldı → CEVAP",
                          routine_label=act["label"])
    elif t == "autotasks":
        await send_admin(f"🤖 @{act['bot']}: görevler otomatik başlıyor (sayfaları gezer, bitince özet gelir). Durdurmak için /dur")
        spawn(run_autotasks(act["bot"], [], act["cap"], msg_id=act["msg_id"]))
    elif t == "findref":
        spawn(ref_finder(act["bot"]))
    elif t == "claimtry":
        spawn(claim_try(act))
    elif t == "claimauto":
        key = f"{act['bot']}|{act['path']}"
        CLAIMS[key] = {"bot": act["bot"], "base": act["base"], "path": act["path"], "mode": act["mode"],
                       "auth": act["auth"], "every": CLAIM_EVERY_MIN, "last": time.time(), "on": True,
                       "n_ok": 1, "n_err": 0, "cls": "ok", "when": time.time()}
        await persist_claims()
        await send_admin(f"🔁 Otomatik toplama açıldı: @{act['bot']} POST {act['path']} her {CLAIM_EVERY_MIN} dk. "
                         f"Hata olursa haber veririm. Liste / kapatma: /topla")
    elif t == "join":
        async with TG_LOCK:
            note = await do_join(act["target"])
        await send_admin(f"📢 {act['target']}: {note}")
    elif t == "routine":
        for r in ROUTINES.values():
            if r["bot"] == act["bot"] and norm_label(r["label"]) == norm_label(act["label"]):
                await send_admin("🔁 Bu rutin zaten var. /rutin ile bak.")
                return
        rid = str(int(time.time() * 1000))
        ROUTINES[rid] = {"bot": act["bot"], "label": act["label"],
                         "last": time.time(), "jitter": random.randint(0, 1800)}
        await persist_routines()
        await send_admin(f"🔁 Rutin eklendi: @{act['bot']} → '{act['label']}' her gün otomatik basılacak.\n"
                         f"Silmek için /rutin")


# ===================== OYUN KESFI (mini uygulama) =====================

DESKTOP_UA = ("Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/120.0 Mobile Safari/537.36")
SCRIPT_RE = re.compile(r"""<script[^>]+src=["']([^"']+)["']""", re.I)
HOST_RE = re.compile(r"https?://[A-Za-z0-9.-]+\.[A-Za-z]{2,}(?::\d+)?(?:/[A-Za-z0-9_\-./]*)?")
PATH_RE = re.compile(
    r"""["'`](/(?:api|v\d|auth|users?|game|tasks?|claim|mine|mining|farm|rewards?|daily|upgrade|boost|referrals?|me(?![a-z])|profile|sessions?|state|config|init|bootstrap|wallet|forge|clash|invite|friends|stats|blocks?|leaderboard|shop|tickets?|crews?|levels?|trpc|graphql|rpc|rest)"""
    r"""[A-Za-z0-9_\-/.]{0,60})["'`]""",
    re.I,
)
NOISE_HOSTS = (
    "w3.org", "github.com", "reactjs.org", "fb.me", "google", "gstatic", "telegram.org", "t.me",
    "cloudflare", "apple.com", "mozilla.org", "npmjs", "sentry", "facebook", "twitter.com", "x.com",
    "youtube", "unpkg", "jsdelivr", "cdnjs", "yandex", "jquery", "schema.org", "w.org",
    "game.com", "example.com", "example.org", "localhost",
)


async def fetch_text(url: str, limit: int = 3_000_000):
    assert http_session is not None
    try:
        async with http_session.get(
            url, headers={"User-Agent": DESKTOP_UA}, timeout=aiohttp.ClientTimeout(total=25)
        ) as r:
            if r.status >= 400:
                return None
            data = await r.content.read(limit)
            return data.decode("utf-8", "ignore")
    except Exception as e:
        print("[FETCH]", repr(e))
        return None


async def try_lock(lock, timeout: float = 10) -> bool:
    """Kilidi en cok 'timeout' sn bekleyerek almaya calisir (alinamazsa False)."""
    try:
        await asyncio.wait_for(lock.acquire(), timeout)
        return True
    except asyncio.TimeoutError:
        return False


def friendly_err(e) -> str:
    n = type(e).__name__
    if "BotInvalid" in n:
        return "bu botun (ana) mini uygulaması tanımlı değil"
    if "AppInvalid" in n:
        return "mini uygulama kısa adı geçersiz"
    if "FloodWait" in n:
        return f"Telegram bekletiyor ({int(getattr(e, 'seconds', 0) or 0)} sn)"
    if "PeerIdInvalid" in n or "UsernameNotOccupied" in n or "UsernameInvalid" in n:
        return "kullanıcı adı bulunamadı"
    if "Blocked" in n:
        return "bot engellenmiş"
    return f"{n} {str(e)[:80]}"


# Ana uygulamasi tanimli olmayan botlarda sik kullanilan mini uygulama kisa adlari (t.me/bot/<kisaad>)
GUESS_SHORTS = ("app", "play", "game", "start", "main", "web", "webapp", "miniapp", "launch", "open", "home", "mine")


async def get_webview_url(ent, username: str, short: str = "", start: str = "", _retry: bool = False):
    """Mini uygulamayi Telegram'in actigi gibi acar. (adres, aciklama, acik_siteler) doner.
    Adres kimlik verisi icerir: SADECE bellekte kalir, sohbete yazilmaz."""
    assert tg_client is not None
    from telethon.tl.functions import messages as M

    notes = []
    msgs = await fetch_incoming(ent, 0, limit=5)
    esc = re.escape(username)
    pat_short = re.compile(r"(?:t\.me|telegram\.me)/" + esc + r"/([A-Za-z0-9_]+)", re.I)
    pat_main = re.compile(r"https?://(?:t\.me|telegram\.me)/" + esc + r"/?(?:\?([^#\s]*))?$", re.I)
    shorts, wv_urls, main_params, seen_btns, pub_urls = [], [], [], [], []
    for m in msgs:
        shorts += pat_short.findall(m.message or "")
        for row in (m.buttons or []):
            for b in row:
                u = raw_url(b).strip()
                kind = classify_button(b)
                raw = getattr(b, "button", None)
                desc = f"{(b.text or '').strip()[:20]} [{kind}/{type(raw).__name__}]"
                if u:
                    desc += f" {u[:70]}"
                elif len(seen_btns) < 4:
                    desc += f" {repr(raw)[:90]}"
                seen_btns.append(desc)
                if kind == "webapp" and u:
                    wv_urls.append(u)
                shorts += pat_short.findall(u)
                mm = pat_main.match(u) if u else None
                if mm:
                    qs = parse_qs(mm.group(1) or "")
                    main_params.append((qs.get("startapp") or [None])[0])
                if u and not re.match(r"https?://(?:t\.me|telegram\.me)/", u, re.I):
                    pub_urls.append(u)
    pub_urls = list(dict.fromkeys(pub_urls))
    if short:
        shorts.insert(0, short)

    # 1) t.me/bot/kisaad linki ile tanimli mini uygulama
    for sn in dict.fromkeys(shorts):
        try:
            from telethon.tl.types import InputBotAppShortName
            from telethon.utils import get_input_user
            res = await tg_client(M.RequestAppWebViewRequest(
                peer=ent,
                app=InputBotAppShortName(bot_id=get_input_user(ent), short_name=sn),
                platform="android",
                write_allowed=True,
                **({"start_param": start} if start else {}),
            ))
            return res.url, f"mini uygulama '{sn}' açıldı", pub_urls
        except Exception as e:
            notes.append(f"'{sn}': {friendly_err(e)}")

    # 2) mesajdaki mini uygulama (webview) butonu
    for u in dict.fromkeys(wv_urls):
        try:
            res = await tg_client(M.RequestWebViewRequest(peer=ent, bot=ent, platform="android", url=u))
            return res.url, "mesajdaki mini uygulama butonundan açıldı", pub_urls
        except Exception as e:
            notes.append(f"webview butonu: {friendly_err(e)}")

    # 3) botun ana mini uygulamasi
    for sp in list(dict.fromkeys(([start] if start else []) + main_params)) or [None]:
        try:
            res = await tg_client(M.RequestMainWebViewRequest(
                peer=ent, bot=ent, platform="android", start_param=sp))
            return res.url, "ana mini uygulama açıldı", pub_urls
        except AttributeError:
            notes.append("Telethon sürümü eski (ana mini uygulama desteği yok)")
            break
        except Exception as e:
            notes.append(f"ana uygulama: {friendly_err(e)}")

    # 4) menu tusu
    try:
        res = await tg_client(M.RequestWebViewRequest(peer=ent, bot=ent, platform="android", from_bot_menu=True))
        return res.url, "menü tuşundan açıldı", pub_urls
    except Exception as e:
        notes.append(f"menü tuşu: {friendly_err(e)}")

    # 5) yaygin kisa adlari dene (ana uygulama tanimli degilse t.me/bot/<kisaad> seklinde olabilir)
    tried = set(shorts)
    for sn in GUESS_SHORTS:
        if sn in tried:
            continue
        try:
            from telethon.tl.types import InputBotAppShortName
            from telethon.utils import get_input_user
            res = await tg_client(M.RequestAppWebViewRequest(
                peer=ent,
                app=InputBotAppShortName(bot_id=get_input_user(ent), short_name=sn),
                platform="android",
                write_allowed=True,
                **({"start_param": start} if start else {}),
            ))
            return res.url, f"mini uygulama '{sn}' açıldı (kısa ad tahminle bulundu)", pub_urls
        except Exception as e:
            if "FloodWait" in type(e).__name__:
                notes.append(friendly_err(e))
                break

    # 6) sohbet hic baslatilmamissa bota /start yazip mesajindaki mini uygulama butonuna bak
    if not msgs and not _retry:
        try:
            await tg_client.send_message(ent, f"/start {start}".strip())
            await asyncio.sleep(INSPECT_WAIT)
            return await get_webview_url(ent, username, short, start, _retry=True)
        except Exception as e:
            notes.append(f"/start: {friendly_err(e)}")

    msg = "Açılamadı: " + " | ".join(notes)
    if seen_btns:
        msg += "\nGördüğüm butonlar: " + "; ".join(seen_btns[:8])
    else:
        msg += "\nBotun mesajında hiç buton görmedim."
    return None, msg, pub_urls


async def scan_site(lines: list, pages: list):
    """Sayfalari ve JS dosyalarini okuyup sunucu adreslerini / API yollarini listeler."""
    blobs, scripts, ok_pages = [], [], []
    for pg in pages[:4]:
        t = await fetch_text(pg)
        if t:
            ok_pages.append(pg)
            blobs.append(t)
            scripts += [urljoin(pg, x) for x in SCRIPT_RE.findall(t)[:6]]
    n_html = len(blobs)
    for sj in list(dict.fromkeys(scripts))[:8]:
        t = await fetch_text(sj)
        if t:
            blobs.append(t)
    if not blobs:
        lines.append("Sayfalar indirilemedi.")
        await send_admin("\n".join(lines))
        return

    hosts, paths, tg_hint = [], [], False
    for t in blobs:
        low = t.lower()
        if "telegram-web-app" in low or "tgwebapp" in low:
            tg_hint = True
        for h in HOST_RE.findall(t):
            h = h.rstrip(".,;)")
            if any(n in h.lower() for n in NOISE_HOSTS):
                continue
            hosts.append(h[:90])
        paths += PATH_RE.findall(t)
    hosts = list(dict.fromkeys(hosts))[:20]
    paths = list(dict.fromkeys(paths))[:40]

    lines.append("")
    lines.append("Okunan: " + ", ".join(p.split("?")[0] for p in ok_pages))
    lines.append(f"Toplam {n_html} sayfa, {len(blobs) - n_html} script okundu")
    lines.append("Telegram mini uygulaması belirtisi: " + ("var" if tg_hint else "yok"))
    lines.append("")
    lines.append("Sunucu adresleri:")
    lines += [f"- {h}" for h in hosts] or ["- bulunamadı"]
    lines.append("")
    lines.append("API yolu adayları:")
    lines += [f"- {p}" for p in paths] or ["- bulunamadı"]
    await send_admin("\n".join(lines))


async def recon_game(target: str):
    """target: bot adi (...bot) ya da http(s) adresi."""
    try:
        if target.lower().startswith("http"):
            clean = target.split("#")[0]
            await scan_site(["🧪 SİTE KEŞFİ", "Adres: " + clean.split("?")[0]], [clean])
            return

        username = target
        ent = await resolve_entity(username)
        if not getattr(ent, "bot", False):
            await send_admin(f"ℹ️ @{username} bir bot değil, mini uygulama araması yapmadım.")
            return
        async with APP_LOCK:
            url, how, pub = await get_webview_url(ent, username)
        lines = [f"🧪 OYUN KEŞFİ: @{username}", how]
        pages = []
        if url:
            base = url.split("#")[0]  # kimlik verisi (#...) asla kullanilmaz / yazilmaz
            pu = urlparse(base)
            lines.append(f"Adres: {pu.scheme}://{pu.netloc}{pu.path}")
            pages.append(base)
        else:
            lines.append("Mini uygulamayı açamadım; botun butonlarındaki sitelere bakıyorum.")
        for u in pub:
            clean = u.split("#")[0]
            pu = urlparse(clean)
            pages += [clean, f"{pu.scheme}://{pu.netloc}/"]
        pages = list(dict.fromkeys(pages))[:4]
        if not pages:
            await send_admin("\n".join(lines))
            return
        await scan_site(lines, pages)
    except Exception as e:
        print("[RECON]", repr(e))
        try:
            await send_admin(f"⚠️ {target} keşfi başarısız: {type(e).__name__} {e}")
        except Exception:
            pass


# ===================== OTOMATIK GOREV (URL + "Kontrol et" cifti olan listeler) =====================

AUTO_DEFAULT_CAP = int(os.getenv("AUTO_TASKS_DEFAULT", "0") or 0)  # 0 = sinirsiz
AUTO_RUNNING = False
AUTO_STOP = False
CHECK_WORDS = ("kontrol", "check", "проверить", "проверка", "verify", "dogrula")


def fold(s: str) -> str:
    """Buyuk/kucuk harf ve Turkce harf farkini yok sayarak karsilastirmak icin."""
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return s.replace("ı", "i").lower()


CHECK_FOLDED = tuple(fold(w) for w in CHECK_WORDS)


def parse_tasks(msg) -> list:
    """Ayni satirda [t.me linki butonu] + [Kontrol et butonu] olan gorevleri bulur."""
    tasks = []
    for i, row in enumerate(msg.buttons or []):
        url_btn, chk = None, None
        for j, b in enumerate(row):
            kind = classify_button(b)
            u = raw_url(b)
            if kind == "url" and re.match(r"https?://", u or "", re.I):
                url_btn = b
            elif kind == "click" and any(w in fold(b.text or "") for w in CHECK_FOLDED):
                chk = (i, j)
        if url_btn is not None and chk is not None:
            tasks.append({
                "url": raw_url(url_btn).split("#")[0],
                "label": (url_btn.text or "").strip(),
                "pos": chk,
            })
    return tasks


async def nav_click(ent, keyword: str) -> bool:
    """En yeni bot mesajlarinda etiketi 'keyword' iceren butona basar (menude gezinme)."""
    assert tg_client is not None
    kw = fold(keyword)
    msgs = [m for m in await tg_client.get_messages(ent, limit=8) if not m.out]
    for m in msgs:  # en yeniden eskiye
        try:
            await m.get_buttons()
        except Exception:
            pass
        for row in (m.buttons or []):
            for b in row:
                label = (b.text or "").strip()
                if classify_button(b) == "click" and kw in fold(label) and not DANGER_BTN_RE.search(label):
                    await asyncio.sleep(random.uniform(1.5, 3.5))
                    await m.click(filter=lambda x, lab=label: (x.text or "").strip() == lab)
                    await asyncio.sleep(4)
                    return True
    return False


async def latest_task_msg(ent, prefer_id=None):
    """Gorev cifti iceren en yeni bot mesajini bulur."""
    assert tg_client is not None
    cands = []
    if prefer_id:
        try:
            m = await tg_client.get_messages(ent, ids=prefer_id)
            if m:
                cands.append(m)
        except Exception:
            pass
    cands += [m for m in await tg_client.get_messages(ent, limit=8) if not m.out]
    for m in cands:
        try:
            await m.get_buttons()
        except Exception:
            pass
        if parse_tasks(m):
            return m
    return None


async def next_page(cur) -> bool:
    for i, row in enumerate(cur.buttons or []):
        for j, b in enumerate(row):
            if (b.text or "").strip() == ">" and classify_button(b) == "click":
                await asyncio.sleep(random.uniform(1.5, 3.5))
                try:
                    await cur.click(i, j)
                except Exception:
                    return False
                await asyncio.sleep(4)
                return True
    return False


async def resolve_tme(url: str) -> str:
    """t.me olmayan (takip / yonlendirme) linki en fazla 4 adimda t.me adresine cozer; olmazsa ''."""
    assert http_session is not None
    cur = url
    for _ in range(4):
        host = urlparse(cur).netloc.lower().split(":")[0]
        if host in ("t.me", "telegram.me", "www.t.me"):
            return cur
        try:
            async with http_session.get(
                cur, allow_redirects=False, headers={"User-Agent": DESKTOP_UA},
                timeout=aiohttp.ClientTimeout(total=15),
            ) as r:
                loc = r.headers.get("Location")
                if loc:
                    cur = urljoin(cur, loc)
                    continue
                if r.status < 400:  # bazi siteler sayfa icinden yonlendirir
                    txt = (await r.content.read(200_000)).decode("utf-8", "ignore")
                    mm = re.search(r"https?://(?:t\.me|telegram\.me)/[A-Za-z0-9_+/?=&%.\-]+", txt)
                    return mm.group(0) if mm else ""
                return ""
        except Exception as e:
            print("[RESOLVE]", repr(e))
            return ""
    return ""


async def dump_buttons(ent) -> str:
    """Teshis: botun son mesajlarindaki butonlari (tur + link) kisaca listeler."""
    assert tg_client is not None
    lines = ["Botun son mesajlarındaki butonlar (teşhis):"]
    try:
        msgs = [m for m in await tg_client.get_messages(ent, limit=4) if not m.out]
        for m in msgs[:3]:
            try:
                await m.get_buttons()
            except Exception:
                pass
            lines.append(f"— mesaj {m.id}: {(m.message or '')[:40]!r}")
            for i, row in enumerate((m.buttons or [])[:6]):
                parts = []
                for b in row:
                    u = raw_url(b)
                    parts.append(f"{(b.text or '').strip()[:18]} [{classify_button(b)}]" + (f" {u[:50]}" if u else ""))
                lines.append(f"  {i + 1}. " + " | ".join(parts))
    except Exception as e:
        lines.append(f"(okunamadı: {type(e).__name__})")
    return "\n".join(lines)


async def do_task_action(url: str) -> str:
    """Linke gore: kanala katil ya da bota /start yaz. 'STOP:' ile baslarsa calisma durur."""
    assert tg_client is not None
    p = urlparse(url)
    if p.netloc.lower().split(":")[0] not in ("t.me", "telegram.me", "www.t.me"):
        real = await resolve_tme(url)
        if not real:
            return "t.me linkine çözülemedi, atladım"
        url = real
        p = urlparse(url)
    segs = [x for x in p.path.split("/") if x]
    qs = parse_qs(p.query)
    if not segs:
        return "link boş, atladım"
    first = segs[0]
    if first.startswith("+") or first.lower() == "joinchat":
        target = first if first.startswith("+") else "joinchat/" + (segs[1] if len(segs) > 1 else "")
    elif re.fullmatch(r"[A-Za-z0-9_]{3,}bot", first, re.I):
        if len(segs) > 1 or "startapp" in qs:
            return "mini uygulama görevi, atladım"
        ent = await resolve_entity(first)
        if not getattr(ent, "bot", False):
            return "bot değil, atladım"
        param = (qs.get("start") or [""])[0]
        await tg_client.send_message(ent, f"/start {param}".strip())
        await asyncio.sleep(random.uniform(2, 4))
        return "Başlattım ✅"
    elif first == "c":
        return "özel gönderi linki, atladım"
    else:
        target = first
    note = await do_join(target)
    if note.startswith("Telegram şimdilik") or "sınırına" in note or "limiti" in note:
        return "STOP:" + note
    return note


def task_title(url: str, label: str) -> str:
    """Ozette gosterilecek kisa ad: kanal/bot adi + odul."""
    p = urlparse(url)
    segs = [x for x in p.path.split("/") if x]
    name = segs[0] if segs else p.netloc
    shown = "özel kanal" if name.startswith("+") else f"@{name}"
    reward = re.search(r"\+\s*[\d.,]+", label or "")
    return shown + (f" ({reward.group(0).replace(' ', '')})" if reward else "")


async def open_list(ent, steps) -> Optional[str]:
    """/start yazip menude steps butonlarina sirayla basar. Bulunamayan adimi doner, basariliysa None."""
    assert tg_client is not None
    await tg_client.send_message(ent, "/start")
    await asyncio.sleep(INSPECT_WAIT)
    for kw in steps:
        if AUTO_STOP or not await nav_click(ent, kw):
            return kw
    return None


REFRESH_WORDS = ("yenile", "refresh", "обнов")


def parse_recover(msg):
    """Gorev erisimi kilitlenince cikan ekran: yalniz 'Abone ol' link satirlari + 'Listeyi yenile'.
    (linkler, yenile_konumu) doner."""
    links, refresh = [], None
    for i, row in enumerate(msg.buttons or []):
        for j, b in enumerate(row):
            kind = classify_button(b)
            u = raw_url(b)
            label = fold(b.text or "")
            if kind == "url" and re.match(r"https?://", u or "", re.I):
                if any(x in label for x in ("abone", "subscribe", "подпис", "katil", "join")):
                    links.append(u.split("#")[0])
            elif kind == "click" and any(w in label for w in REFRESH_WORDS):
                refresh = (i, j)
    return links, refresh


async def try_recover(ent) -> str:
    """Gorev erisimi kilitliyse: listedeki kanallara abone olup 'Listeyi yenile'ye basar.
    GRAM odeyen 'Coinleri geri al'a ASLA basmaz. Aciklama doner, kilit yoksa ''."""
    assert tg_client is not None
    msgs = [m for m in await tg_client.get_messages(ent, limit=8) if not m.out]
    for m in msgs:
        try:
            await m.get_buttons()
        except Exception:
            pass
        if parse_tasks(m):
            continue  # normal gorev listesi
        links, refresh = parse_recover(m)
        if not links or refresh is None:
            continue
        ok = skipped = 0
        for u in dict.fromkeys(links):
            if AUTO_STOP:
                break
            note = await do_task_action(u)
            if note.startswith("STOP:"):
                return f"🛟 Görev erişimi kilitli, ama durdum: {note[5:]}"
            if note.startswith(("Katıldım", "Başlattım")):
                ok += 1
            else:
                skipped += 1
            await asyncio.sleep(random.uniform(3, 6))
        await asyncio.sleep(3)
        try:
            await m.click(*refresh)
        except Exception as e:
            return f"🛟 Kilitli listedeki {ok} kanala abone oldum ama 'Listeyi yenile' basılamadı: {type(e).__name__}"
        await asyncio.sleep(4)
        return (f"🛟 Görev erişimi kilitliydi: {ok} kanala abone oldum, {skipped} atlandı, "
                f"'Listeyi yenile'ye bastım (GRAM ödemedim).")
    return ""


async def run_autotasks(bot: str, steps: list, cap: int, msg_id: Optional[int] = None, quiet: bool = False):
    """Gorev listesindeki gorevleri sirayla yapar: katil/start -> bekle -> Kontrol et -> sonucu dogrula.
    quiet=True (otopilot): bos turlarda ve hatalarda en fazla 6 saatte bir mesaj atar."""
    global AUTO_RUNNING, AUTO_STOP
    if AUTO_RUNNING:
        if not quiet:
            await send_admin("⏳ Zaten bir otomatik görev çalışıyor. Durdurmak için /dur yaz.")
        return
    AUTO_RUNNING, AUTO_STOP = True, False
    results = []  # (baslik, not, cevap)

    async def notice(text: str):
        global LAST_EMPTY_NOTICE
        if quiet and time.time() - LAST_EMPTY_NOTICE < 6 * 3600:
            return
        LAST_EMPTY_NOTICE = time.time()
        await send_admin(text)

    try:
        assert tg_client is not None
        ent = await resolve_entity(bot)
        if not getattr(ent, "bot", False):
            await send_admin(f"ℹ️ @{bot} bir bot değil, otomatik görev başlatmadım.")
            return
        if steps:
            async with TG_LOCK:
                bad = await open_list(ent, steps)
            if bad:
                await notice(f"⚠️ @{bot}: '{bad}' butonunu bulamadım, durdum. "
                             f"Menüyü görmek için /incele {bot}\n\n" + await dump_buttons(ent))
                return
        mid = msg_id
        done, pages, reopens = set(), 0, 0
        announced, last_progress = False, 0
        while (cap <= 0 or len(results) < cap) and not AUTO_STOP:
            if (not quiet) and results and len(results) % 5 == 0 and len(results) != last_progress:
                last_progress = len(results)
                await send_admin(f"⏳ {len(results)} görev işlendi, devam ediyorum... (durdurmak için /dur)")
            async with TG_LOCK:  # her gorevden sonra birakilir: /incele, butonlar, cikis takibi bekletilmez
                cur = await latest_task_msg(ent, mid)
                if cur is None and reopens < 3:
                    reopens += 1
                    rec = await try_recover(ent)  # kilitliyse: abone ol + listeyi yenile
                    if rec:
                        await send_admin(rec)
                    elif steps:
                        await open_list(ent, steps)  # liste kaybolduysa menuden yeniden ac
                    cur = await latest_task_msg(ent, None)
                if cur is None:
                    if not results:
                        await notice(f"⚠️ @{bot}: görev listesi bulunamadı (link + 'Kontrol et' çiftleri yok).\n\n"
                                     + await dump_buttons(ent))
                    break
                mid = cur.id
                tasks = [t for t in parse_tasks(cur) if t["url"] not in done]
                if tasks and not announced and not quiet:
                    announced = True
                    await send_admin(f"📋 @{bot}: görev listesi bulundu, bu sayfada {len(tasks)} görev var. "
                                     f"Başlıyorum... (durdurmak için /dur)")
                if not tasks:
                    if pages >= 30:
                        break
                    sig = tuple(x["url"] for x in parse_tasks(cur))
                    if not await next_page(cur):
                        break
                    pages += 1
                    nxt = await latest_task_msg(ent, mid)
                    if nxt is not None and tuple(x["url"] for x in parse_tasks(nxt)) == sig:
                        break  # sayfa degismedi: son sayfa
                    continue
                t = tasks[0]
                done.add(t["url"])
                title = task_title(t["url"], t["label"])
                note = await do_task_action(t["url"])
                if note.startswith("STOP:"):
                    results.append((title, note[5:], ""))
                    break
                if not (note.startswith("Katıldım") or note.startswith("Başlattım")):
                    results.append((title, note, ""))
                    continue
                await asyncio.sleep(random.uniform(4, 9))
                cur = await latest_task_msg(ent, mid)
                again = [x for x in parse_tasks(cur) if x["url"] == t["url"]] if cur else []
                if not again:
                    results.append((title, note, "liste değişti, Kontrol et basılmadı"))
                    continue
                try:
                    ans = await cur.click(*again[0]["pos"])
                    reply = (getattr(ans, "message", None) or "").strip()
                    await asyncio.sleep(3)
                    chk = await latest_task_msg(ent, mid)
                    if chk is None:
                        verdict = "❓ liste değişti"
                    elif any(x["url"] == t["url"] for x in parse_tasks(chk)):
                        verdict = "❌ kontrol geçmedi (hâlâ listede)"
                    else:
                        verdict = "✅ kontrol geçti"
                    reply = (reply + " · " if reply else "") + verdict
                except Exception as e:
                    reply = f"Kontrol basılamadı: {type(e).__name__}"
                results.append((title, note, reply))
            await asyncio.sleep(random.uniform(3, 6))
    except Exception as e:
        print("[AUTO]", repr(e))
        results.append(("hata", f"{type(e).__name__} {e}", ""))
    finally:
        AUTO_RUNNING = False

    if not results:
        if not quiet:
            await send_admin(f"🤖 @{bot}: bu turda yapılacak görev bulunamadı.")
        return
    joined = sum(1 for _, n, _r in results if n.startswith(("Katıldım", "Başlattım")))
    passed = sum(1 for _, _n, r in results if "✅" in r)
    lines = [f"🤖 OTOMATİK GÖREV TURU BİTTİ: @{bot}",
             f"{len(results)} görev işlendi · {joined} katılma/başlatma · {passed} kontrol geçti", ""]
    for title, note, reply in results[:25]:
        lines.append(f"• {title[:28]} → {note[:45]}" + (f" → {reply[:80]}" if reply else ""))
    if len(results) > 25:
        lines.append(f"... ve {len(results) - 25} görev daha")
    lines += ["", f"ℹ️ Katıldığım kanallardan {LEAVE_AFTER_HOURS // 24} gün {LEAVE_AFTER_HOURS % 24} saat sonra "
                  f"kendim çıkarım, erken çıkmam (kayıtlı kanal: {len(JOINS)})."]
    await send_admin("\n".join(lines))


# ===================== 7 GUN SONRA CIKIS + OTOPILOT =====================

async def leave_due():
    """LEAVE_AFTER_HOURS dolan kanallardan ayrilir. (ayrilanlar, hatalar) doner."""
    global FLOOD_UNTIL
    assert tg_client is not None
    now = time.time()
    due = sorted(
        ((k, v) for k, v in JOINS.items() if now - float(v.get("t", now)) >= LEAVE_AFTER_HOURS * 3600),
        key=lambda kv: float(kv[1].get("t", 0)),
    )
    left, failed = [], []
    for k, v in due[:15]:  # tek turda en fazla 15 (flood onlemi)
        label = str(v.get("target", k))
        try:
            async with TG_LOCK:
                ent = await resolve_entity(int(k))
                await tg_client.delete_dialog(ent)  # kanaldan / gruptan cikar
            JOINS.pop(k, None)
            left.append(label)
        except Exception as e:
            name = type(e).__name__
            if "FloodWait" in name:
                FLOOD_UNTIL = time.time() + int(getattr(e, "seconds", 0) or 0)
                failed.append(f"{label}: Telegram bekletiyor")
                break
            if isinstance(e, ValueError) or any(x in name for x in ("ChannelPrivate", "UserNotParticipant", "ChannelInvalid", "PeerIdInvalid")):
                JOINS.pop(k, None)  # zaten ayrilmis ya da erisim yok
                left.append(f"{label} (zaten yoktu)")
            else:
                failed.append(f"{label}: {name}")
        await asyncio.sleep(random.uniform(5, 12))
    if left or failed:
        await persist_joins()
    return left, failed


async def membership_watch():
    """Kayitli kanallardan atilmis / dusmus olan var mi? Varsa yeniden katilmayi dener
    (PR GRAM abonelik cezasina karsi). Sadece uyeligi KESIN dusmus olanlari sayar."""
    assert tg_client is not None
    now = time.time()
    cands = [(k, v) for k, v in JOINS.items() if now - float(v.get("t", now)) > 7200]
    random.shuffle(cands)
    lost = []
    for k, v in cands[:20]:
        try:
            async with TG_LOCK:
                ent = await resolve_entity(int(k))
                if type(ent).__name__ != "Channel":
                    continue
                await tg_client(GetParticipantRequest(channel=ent, participant="me"))
        except Exception as e:
            name = type(e).__name__
            if any(x in name for x in ("NotParticipant", "ChannelPrivate", "Banned")):
                lost.append((k, v, name))
            continue  # baska hata / onbellek eksigi: alarm verme
        await asyncio.sleep(random.uniform(1, 3))
    if not lost:
        return
    lines = [f"🔎 {len(lost)} kanalda üyeliğin düşmüş (atılmış ya da kanal kapanmış olabilir). "
             f"PR GRAM abonelik şartı yüzünden ceza çıkarabilir:"]
    for k, v, name in lost[:10]:
        label = str(v.get("target", k))
        JOINS.pop(k, None)  # kayittan cikar (tekrar tekrar uyarmasin)
        note = ""
        if "Banned" not in name and "ChannelPrivate" not in name and v.get("target"):
            async with TG_LOCK:
                note = await do_join(str(v["target"]))
        lines.append(f"• {label}: {name}" + (f" → yeniden: {note}" if note else ""))
    await persist_joins()
    await send_admin("\n".join(lines))


async def leave_and_report(force: bool):
    left, failed = await leave_due()
    if not (left or failed):
        if force:
            await send_admin(f"Süresi dolan kanal yok (kayıtlı kanal: {len(JOINS)}).")
        return
    lines = [f"🚪 7 günü dolan kanallardan çıkış: {len(left)} çıkıldı, {len(failed)} hata"]
    lines += [f"• {x}" for x in left[:15]]
    lines += [f"⚠️ {x}" for x in failed[:10]]
    lines.append(f"Kalan kayıtlı kanal: {len(JOINS)}")
    await send_admin("\n".join(lines))


def autopilot_short() -> str:
    if AUTOPILOT.get("on"):
        return f"ACIK -> @{AUTOPILOT.get('bot')}"
    return "kapali"


def autopilot_status_text() -> str:
    now = time.time()
    lines = []
    if AUTOPILOT.get("on"):
        lines.append(f"🛫 Otopilot: AÇIK → @{AUTOPILOT.get('bot')} ({' > '.join(AUTOPILOT.get('steps') or [])})")
        lines.append(f"Her {AUTOPILOT_MIN_MINUTES}-{AUTOPILOT_MAX_MINUTES} dk'da bir görev listesini tarar.")
    else:
        lines.append("🛬 Otopilot: kapalı\nAçmak için: /otopilot gram_prbot")
    lines.append(f"Kayıtlı kanal: {len(JOINS)} (her biri {LEAVE_AFTER_HOURS // 24} gün {LEAVE_AFTER_HOURS % 24} saat sonra bırakılır)")
    if JOINS:
        first = min(float(v.get("t", now)) for v in JOINS.values()) + LEAVE_AFTER_HOURS * 3600 - now
        due = sum(1 for v in JOINS.values() if now - float(v.get("t", now)) >= LEAVE_AFTER_HOURS * 3600)
        when = "şimdi" if first <= 0 else f"{int(first // 3600)} saat sonra"
        lines.append(f"En yakın çıkış: {when} · süresi dolan: {due}")
    if AUTOPILOT.get("on") and AUTOPILOT.get("last"):
        lines.append(f"Son tur: {int((now - float(AUTOPILOT['last'])) // 60)} dk önce")
    if FLOOD_UNTIL > now:
        lines.append(f"⏸ Telegram bekletiyor: yaklaşık {int((FLOOD_UNTIL - now) // 60)} dk")
    return "\n".join(lines)


async def autopilot_loop():
    """Hic durmaz: (1) suresi dolan kanallardan cik, (2) otopilot aciksa gorev listesini tara."""
    await asyncio.sleep(75)
    while True:
        try:
            if time.time() >= FLOOD_UNTIL:
                await leave_and_report(False)
                await membership_watch()
                if AUTOPILOT.get("on") and AUTOPILOT.get("bot"):
                    await run_autotasks(AUTOPILOT["bot"], AUTOPILOT.get("steps") or ["kazanc", "kanallar"], 0, quiet=True)
                    AUTOPILOT["last"] = time.time()
                    await persist_autopilot()
        except Exception as e:
            print("[AUTOPILOT]", repr(e))
        base = random.uniform(AUTOPILOT_MIN_MINUTES, max(AUTOPILOT_MIN_MINUTES, AUTOPILOT_MAX_MINUTES)) * 60
        await asyncio.sleep(max(base, FLOOD_UNTIL - time.time() + 120))


# ===================== REFERANS LINKI + MINI UYGULAMA ARASTIRMA =====================
# Amac: botun/mini uygulamanin KISISEL referans linkini bulmak ve uygulamanin API yapisini cikarmak.
# Sadece OKUR: GET istekleri + yalnizca giris (auth/login) yollarina POST. Satin alma, yakma, cekim,
# talep etme gibi islem yollarina asla istek atmaz. Giris verisi / token sohbete yazilmaz.

REFS_KEY = os.getenv("REFS_KEY", "radar:refs:v1").strip()
REFS_FILE = os.getenv("REFS_FILE", "/tmp/radar_refs.json")
REFS: dict = {}  # bot -> {"link": ..., "src": ..., "t": ...}

REF_BTN_WORDS = tuple(fold(w) for w in (
    "davet", "invite", "referral", "referans", "arkadaş", "friends", "partner", "ortak", "affiliate",
    "реферал", "пригласи", "друзь", "партнер",
))
REF_KEY_RE = re.compile(
    r"(^|[_\-.])(ref|referral|referer|invite|inviter|startapp|share)([_\-.]|$)"
    r"|refcode|invitecode|referralcode|reflink|invitelink|referrallink|sharelink|refurl",
    re.I,
)
# GET ile bile cagirmayacagimiz, islem yapan yollar
ACTION_PATH_RE = re.compile(
    r"claim|collect|start|play|spin|buy|purchase|shop|burn|forge|withdraw|deposit|transfer|swap|stake|"
    r"pay|invest|upgrade|craft|ticket|task|check|verify|reward|bonus|daily|harvest|open|mint|sell|"
    r"exchange|boost|finish|complete|logout|signout|revoke",
    re.I,
)
AUTH_PATH_RE = re.compile(r"auth|login|signin|sign-in|session", re.I)
DEFAULT_GET_PATHS = [
    "/api/me", "/api/user", "/api/user/me", "/api/users/me", "/api/profile", "/api/account",
    "/api/v1/me", "/api/v1/user", "/api/v1/user/me", "/api/v1/profile",
    "/api/referral", "/api/referrals", "/api/v1/referral", "/api/v1/referrals",
    "/api/invite", "/api/friends", "/api/v1/friends", "/api/config", "/api/state", "/api/init",
    "/api/bootstrap", "/api/v1/init", "/api/v1/state", "/user", "/me", "/profile",
]
DEFAULT_AUTH_PATHS = [
    "/api/auth", "/api/auth/telegram", "/auth/telegram", "/api/login", "/api/telegram/auth",
    "/api/v1/auth", "/api/v1/auth/telegram", "/api/v1/login", "/auth", "/login", "/api/auth/login",
    "/api/v1/auth/login", "/api/session", "/api/v1/session", "/api/tg/auth", "/api/telegram",
    "/api/user/auth", "/api/users/auth", "/api/webapp/auth", "/api/auth/webapp",
]


async def persist_refs():
    await save_json(REFS_KEY, REFS_FILE, REFS)


async def load_refs():
    data = await load_json(REFS_KEY, REFS_FILE)
    if isinstance(data, dict):
        REFS.update(data)
    print("[REFERANS]", len(REFS))


def find_ref_links(msgs, bot: str) -> list:
    """Mesaj metni, gomulu linkler ve butonlardaki 't.me/<bot>...?start|startapp=...' linkleri."""
    rx = re.compile(
        r"(?:https?://)?t\.me/" + re.escape(bot) + r"(?:/[A-Za-z0-9_]+)?\?(?:start|startapp)=[A-Za-z0-9_\-%=.]+",
        re.I,
    )
    out = []
    for m in msgs:
        parts = [m.message or ""]
        for e in (m.entities or []):
            u = getattr(e, "url", None)
            if u:
                parts.append(str(u))
        for row in (m.buttons or []):
            for b in row:
                u = raw_url(b)
                if u:
                    parts.append(u)
        for t in parts:
            for mm in rx.finditer(t):
                link = mm.group(0)
                pm = re.search(r"[?&](?:start|startapp)=([^&#\s]+)", link)
                if pm and re.fullmatch(r"[a-z]+(?:_[a-z]+)+", pm.group(1)):
                    continue  # 'rotate_restart' gibi: botun kendi eylem parametresi, kisisel referans degil
                out.append(link if link.lower().startswith("http") else "https://" + link)
    return list(dict.fromkeys(out))


async def ref_from_chat(ent, bot: str) -> list:
    """Bot sohbetinden referans linki arar; yoksa 'davet/referans' menu butonlarina (guvenli) basip tekrar bakar."""
    msgs = await fetch_incoming(ent, 0, limit=12)
    links = find_ref_links(msgs, bot)
    depth = 0
    while not links and depth < 2:
        depth += 1
        target = None
        for m in reversed(msgs):
            for row in (m.buttons or []):
                for b in row:
                    t = (b.text or "").strip()
                    if (classify_button(b) == "click" and not DANGER_BTN_RE.search(t)
                            and any(w in fold(t) for w in REF_BTN_WORDS)):
                        target = (m, t)
                        break
                if target:
                    break
            if target:
                break
        if not target:
            break
        m, t = target
        await asyncio.sleep(random.uniform(1.5, 3))
        try:
            await m.click(filter=lambda bb, w=fold(t): fold(bb.text or "") == w)
        except Exception as e:
            print("[REF CHAT]", repr(e))
            break
        await asyncio.sleep(4)
        msgs = await fetch_incoming(ent, m.id, limit=12)
        links = find_ref_links(msgs, bot)
    return links


def parse_init_data(webview_url: str) -> str:
    """Mini uygulama adresindeki giris verisini (tgWebAppData) cikarir. ASLA sohbete yazilmaz."""
    frag = urlparse(webview_url).fragment
    return (parse_qs(frag).get("tgWebAppData") or [""])[0]


async def http_json(method: str, url: str, headers: dict, body=None):
    """(durum, json | None). Yonlendirme takip etmez, kisa zaman asimi."""
    assert http_session is not None
    try:
        async with http_session.request(
            method, url, headers=headers, json=body, allow_redirects=False,
            timeout=aiohttp.ClientTimeout(total=8),
        ) as r:
            if r.status >= 400:
                return r.status, None
            try:
                return r.status, await r.json(content_type=None)
            except Exception:
                return r.status, None
    except Exception:
        return 0, None


def find_token(data, depth: int = 0):
    """Giris cevabindaki oturum anahtarini (token/jwt) bulur."""
    if depth > 4:
        return None
    if isinstance(data, dict):
        for k, v in data.items():
            if isinstance(v, str) and len(v) > 20 and str(k).lower().replace("_", "") in (
                    "token", "accesstoken", "jwt", "authtoken", "bearer"):
                return v
            if isinstance(v, (dict, list)):
                r = find_token(v, depth + 1)
                if r:
                    return r
    elif isinstance(data, list):
        for v in data[:5]:
            r = find_token(v, depth + 1)
            if r:
                return r
    return None


def scan_json(obj, path, links, codes, keys, depth: int = 0):
    """JSON icinde referans linki / kodu arar; alan adlarini (deger degil) toplar."""
    if depth > 6:
        return
    if isinstance(obj, dict):
        for k, v in list(obj.items())[:60]:
            p = f"{path}.{k}" if path else str(k)
            if depth <= 2 and len(keys) < 25:
                keys.append(p)
            if isinstance(v, (str, int)) and not isinstance(v, bool) and REF_KEY_RE.search(str(k)):
                s = str(v)
                if 0 < len(s) <= 80 and not s.startswith("eyJ"):
                    codes.append((p, s))
            scan_json(v, p, links, codes, keys, depth + 1)
    elif isinstance(obj, list):
        for v in obj[:3]:
            scan_json(v, f"{path}[]", links, codes, keys, depth + 1)
    elif isinstance(obj, str):
        if "t.me/" in obj and ("start=" in obj or "startapp=" in obj) and len(obj) < 300:
            links.append(obj)


CHUNK_RE = re.compile(r"""["'`]((?:\.{0,2}/)?[A-Za-z0-9_\-./]{2,100}\.js)["'`]""")


async def collect_site(pages: list):
    """Sayfalari + JS dosyalarini (ve onlarin ek olarak istedigi parca/chunk dosyalarini) indirir.
    (blobs, sunucu_adresleri, yol_adaylari) doner."""
    origin = ""
    if pages:
        pu0 = urlparse(pages[0])
        origin = f"{pu0.scheme}://{pu0.netloc}"
    blobs, js_items, scripts, seen_urls = [], [], [], set()
    for pg in pages[:4]:
        t = await fetch_text(pg)
        if t:
            blobs.append(t)
            js_items.append((pg, t))
            seen_urls.add(pg.split("?")[0])
            scripts += [urljoin(pg, x) for x in SCRIPT_RE.findall(t)[:6]]
    for sj in list(dict.fromkeys(scripts))[:8]:
        seen_urls.add(sj.split("?")[0])
        t = await fetch_text(sj)
        if t:
            blobs.append(t)
            js_items.append((sj, t))

    # Tembel yuklenen parcalar: Mine / Wallet / Forge gibi ekranlar ayri dosyada olabilir
    cand = []
    for url, txt in js_items:
        for ref in CHUNK_RE.findall(txt):
            if ref.startswith(("http://", "https://", "//")):
                continue
            if ref.startswith(("assets/", "static/", "_next/", "/")):
                full = urljoin(origin + "/", ref)
            else:
                full = urljoin(url, ref)
            if origin and full.startswith(origin) and full.split("?")[0] not in seen_urls:
                cand.append(full)
    cand = list(dict.fromkeys(cand))[:30]
    sem = asyncio.Semaphore(6)

    async def get(u):
        async with sem:
            return await fetch_text(u)

    if cand:
        for t in await asyncio.gather(*[get(u) for u in cand]):
            # bazi siteler olmayan dosya icin ana sayfayi (HTML) dondurur: onu atla
            if t and not t.lstrip()[:15].lower().startswith(("<!doctype", "<html")):
                blobs.append(t)

    hosts, paths = [], []
    for t in blobs:
        for h in HOST_RE.findall(t):
            h = h.rstrip(".,;)")
            if any(n in h.lower() for n in NOISE_HOSTS):
                continue
            hosts.append(h[:90])
        paths += PATH_RE.findall(t)
    return blobs, list(dict.fromkeys(hosts))[:20], list(dict.fromkeys(paths))[:150]


def tma_headers(base_hdr: dict, init: str) -> dict:
    """Mini uygulama API'lerinin kullandigi yaygin giris basliklari (birlikte gonderilir)."""
    return {**base_hdr, "Authorization": f"tma {init}", "X-Telegram-Init-Data": init, "X-Init-Data": init,
            "X-Telegram-Web-App-Data": init, "Telegram-Init-Data": init, "Init-Data": init}


def app_base_headers(origin: str) -> dict:
    return {"Origin": origin, "Referer": origin + "/", "User-Agent": DESKTOP_UA, "Accept": "application/json"}


async def http_call(method: str, url: str, headers: dict, body=None):
    """(durum, json | None, metin_ozeti). Hata durumlarinda da cevap metnini dondurur."""
    assert http_session is not None
    try:
        async with http_session.request(
            method, url, headers=headers, json=body, allow_redirects=False,
            timeout=aiohttp.ClientTimeout(total=10),
        ) as r:
            txt = await r.text()
            try:
                data = json.loads(txt)
            except Exception:
                data = None
            return r.status, data, (txt or "")[:200]
    except Exception as e:
        return 0, None, type(e).__name__


async def app_context(webview_url: str) -> dict:
    """Mini uygulamaya girer: sayfa + JS'i okur, calisan giris yontemini (tma / token) bulur.
    Giris verisi yalniz bellekte kalir."""
    init = parse_init_data(webview_url)
    base_url = webview_url.split("#")[0]
    pu = urlparse(base_url)
    origin = f"{pu.scheme}://{pu.netloc}"
    ctx = {"ok": False, "init": init, "origin": origin, "mode": "", "hdr": {}, "bases": [origin],
           "blobs": [], "hosts": [], "paths": [], "got": [], "auth": None, "notes": []}

    blobs, hosts, paths = await collect_site([base_url, origin + "/"])
    ctx.update(blobs=blobs, hosts=hosts, paths=paths)
    if not blobs:
        ctx["notes"].append("Uygulama sayfası indirilemedi.")
        return ctx
    if not init:
        ctx["notes"].append("Giriş verisi alınamadı, API yoklaması yapılamadı.")
        return ctx

    api_bases = []
    for h in hosts:
        ph = urlparse(h)
        if ph.netloc and "api" in ph.netloc.lower():
            api_bases.append(f"{ph.scheme}://{ph.netloc}")
    bases = list(dict.fromkeys(api_bases + [origin]))[:3]
    ctx["bases"] = bases
    js_get = [p for p in paths if not ACTION_PATH_RE.search(p) and not AUTH_PATH_RE.search(p)]
    get_paths = list(dict.fromkeys(js_get + DEFAULT_GET_PATHS))[:24]
    urls = [b.rstrip("/") + p for p in get_paths for b in bases][:45]

    base_hdr = app_base_headers(origin)
    sem = asyncio.Semaphore(6)

    async def one(u, hdr):
        async with sem:
            st, data = await http_json("GET", u, hdr)
            return u, data

    async def run_gets(hdr):
        out = await asyncio.gather(*[one(u, hdr) for u in urls])
        return [(u, d) for u, d in out if d]

    tma_hdr = tma_headers(base_hdr, init)
    got = await run_gets(tma_hdr)
    if got:
        ctx.update(ok=True, mode="tma", hdr=tma_hdr, got=got)
        return ctx

    # Bazi uygulamalar once giris yapip oturum anahtari (token) dagitir
    auth_paths = [p for p in paths if AUTH_PATH_RE.search(p) and not ACTION_PATH_RE.search(p)] + DEFAULT_AUTH_PATHS
    auth_urls = [b.rstrip("/") + p for p in dict.fromkeys(auth_paths) for b in bases][:24]
    bodies = [{"initData": init}, {"init_data": init}, {"initDataRaw": init}, {"data": init},
              {"tgWebAppData": init}, {"init": init}, {"telegramInitData": init}]
    token, used, t0 = None, None, time.time()
    for au in auth_urls:
        for body in bodies:
            if time.time() - t0 > 60:
                break
            st, data = await http_json("POST", au, {**base_hdr, "Content-Type": "application/json"}, body)
            token = find_token(data)
            if token:
                used = {"url": au, "key": next(iter(body))}
                break
        if token or time.time() - t0 > 60:
            break
    if token:
        bearer = {**base_hdr, "Authorization": f"Bearer {token}"}
        ctx.update(ok=True, mode="token", hdr=bearer, auth=used, got=await run_gets(bearer))
    else:
        ctx["notes"].append("API giriş yöntemini çözemedim (tma başlığı ve basit giriş denemeleri sonuç vermedi).")
    return ctx


def analyze_ctx(ctx: dict) -> dict:
    """Mini uygulama baglamindan (kod + API cevaplari) referans link/kod/kalip ve API ozetini cikarir."""
    res = {"links": [], "codes": [], "templates": [], "api": [], "notes": list(ctx["notes"]),
           "hosts": ctx["hosts"][:10], "paths": ctx["paths"][:25]}

    for t in ctx["blobs"]:
        found_tpl = re.findall(r"""[A-Za-z0-9_./:?&%\-]{0,80}startapp=[^\s"'`]{0,60}""", t)[:3]
        if not found_tpl:
            found_tpl = re.findall(r".{0,70}startapp=.{0,90}", t)[:2]
        for s_ in found_tpl:
            tpl = re.sub(r"\s+", " ", s_).strip()[:150]
            if tpl and tpl not in res["templates"]:
                res["templates"].append(tpl)
    res["templates"] = res["templates"][:3]

    for u, data in ctx["got"]:
        links, codes, keys = [], [], []
        scan_json(data, "", links, codes, keys)
        res["links"] += links
        res["codes"] += codes
        if keys:
            res["api"].append(f"GET {urlparse(u).path} → {', '.join(keys[:8])}")
    res["links"] = list(dict.fromkeys(res["links"]))[:5]
    res["codes"] = list(dict.fromkeys(res["codes"]))[:6]
    res["api"] = list(dict.fromkeys(res["api"]))[:8]
    if ctx["got"]:
        res["notes"].append(f"API yoklaması başarılı ({ctx['mode']} yöntemi, {len(ctx['got'])} yanıt).")
    elif ctx["ok"]:
        res["notes"].append(f"Giriş çalışıyor ({ctx['mode']}) ama okuma yolları cevap vermedi.")
    return res


async def probe_miniapp(bot: str, webview_url: str, how: str) -> dict:
    """Mini uygulamanin JS'inden referans kalibi arar, giris verisiyle API'yi (yalniz GET) yoklar."""
    return analyze_ctx(await app_context(webview_url))


async def ref_finder(bot: str):
    """Referans linkini once bot sohbetinde, sonra mini uygulamanin API'sinde arar."""
    try:
        ent = await resolve_entity(bot)
        if not getattr(ent, "bot", False):
            await send_admin(f"ℹ️ @{bot} bir bot değil, referans araması yapmadım.")
            return
        await send_admin(f"🔎 @{bot}: referans linki aranıyor (bot sohbeti + mini uygulama). 1-2 dakika sürebilir...")
        chat_links = []
        if await try_lock(TG_LOCK, 8):
            try:
                chat_links = await ref_from_chat(ent, bot)
            finally:
                TG_LOCK.release()
        async with APP_LOCK:
            url, how, pub = await get_webview_url(ent, bot)

        found = [(l, "bot sohbeti") for l in chat_links]
        probe = None
        if url:
            probe = await probe_miniapp(bot, url, how)
            found += [(l, "mini uygulama API") for l in probe["links"]]

        lines = [f"🔗 REFERANS ARAMA: @{bot}"]
        if found:
            link, src = found[0]
            REFS[bot] = {"link": link, "src": src, "t": time.time()}
            await persist_refs()
            lines += ["", f"✅ Bulundu ve kaydedildi ({src}):", link]
            for l, s in found[1:4]:
                lines.append(f"Diğer aday: {l}")
        else:
            lines += ["", "❌ Tam referans linkini bulamadım."]
            if not url:
                lines.append("Mini uygulama açılamadı: " + how[:300])
        if probe:
            if probe["codes"]:
                lines += ["", "🔑 Referansa benzeyen alanlar:"] + [f"- {p} = {v}" for p, v in probe["codes"]]
            if probe["templates"]:
                lines += ["", "🧩 Kodda geçen link kalıbı:"] + [f"- {t}" for t in probe["templates"]]
            if probe["api"]:
                lines += ["", "🌐 API'den okuduğum alanlar (değerler yazılmadı):"] + [f"- {a}" for a in probe["api"]]
            else:
                if probe.get("hosts"):
                    lines += ["", "🖥 Uygulama kodunda bulduğum sunucu adresleri:"] + [f"- {h}" for h in probe["hosts"]]
                if probe.get("paths"):
                    lines += ["", "🧭 Kodda geçen yol adayları:"] + [f"- {p}" for p in probe["paths"][:20]]
            for n in probe["notes"]:
                lines.append(f"ℹ️ {n}")
        if not found:
            lines += ["", f"Uygulamada Davet sayfasındaki Kopyala ile linki alıp şunu yazarsan kaydederim:",
                      f"/ref {bot} <link>"]
        await send_admin("\n".join(lines))
    except Exception as e:
        print("[REF]", repr(e))
        try:
            await send_admin(f"⚠️ @{bot} referans araması başarısız: {type(e).__name__} {e}")
        except Exception:
            pass


# ===================== ODUL TOPLAMA (mini uygulama, kesif tabanli + onayli) =====================
# Uygulamanin KENDI JS kodunda gecen, guvenli 'topla / oturum baslat' yollarini bulur. Para harcayan,
# yakan, cekim yapan, satin alan yollara asla istek atmaz. Her yol ilk kez SENIN onayinla denenir;
# calisirsa istersen otomatik (periyodik) toplanir.

CLAIMS_KEY = os.getenv("CLAIMS_KEY", "radar:claims:v1").strip()
CLAIMS_FILE = os.getenv("CLAIMS_FILE", "/tmp/radar_claims.json")
CLAIMS: dict = {}  # "bot|yol" -> {bot, base, path, mode, auth, every, last, on, n_ok, n_err, cls, ...}
CLAIM_EVERY_MIN = int(os.getenv("CLAIM_EVERY_MIN", "60") or 60)

CLAIM_OK_RE = re.compile(
    r"claim|collect|harvest|check-?in|daily|session|farm|(?<![a-z])(?:mine|mining)(?![a-z])", re.I)
CLAIM_BAD_RE = re.compile(
    r"buy|purchase|shop|store|burn|forge|withdraw|deposit|transfer|swap|stake|pay|invest|upgrade|craft|ticket|"
    r"sell|exchange|mint|task|referral|invite|friend|crew|clash|arcade|raid|play|spin|wheel|bet|wager|stars|"
    r"premium|wallet|(?<![a-z])ton(?![a-z])|auth|login|logout|signout|revoke|delete|remove|unlink|connect|verify|boost",
    re.I,
)
CLAIM_SCAN_RE = re.compile(
    r"""["'`](/[A-Za-z0-9_\-/.]*(?:claim|collect|harvest|checkin|check-in|session|mine|mining|farm|daily)"""
    r"""[A-Za-z0-9_\-/.]{0,40})["'`]""",
    re.I,
)


async def persist_claims():
    await save_json(CLAIMS_KEY, CLAIMS_FILE, CLAIMS)


async def load_claims():
    data = await load_json(CLAIMS_KEY, CLAIMS_FILE)
    if isinstance(data, dict):
        CLAIMS.update(data)
    print("[TOPLAMA]", len(CLAIMS))


def claim_candidates(ctx: dict) -> list:
    """Uygulamanin kendi kodunda gecen guvenli 'topla/oturum' yollari."""
    found = []
    for t in ctx["blobs"]:
        found += CLAIM_SCAN_RE.findall(t)
    found += list(ctx["paths"])
    out = []
    for p in dict.fromkeys(found):
        if not CLAIM_OK_RE.search(p) or CLAIM_BAD_RE.search(p):
            continue
        if re.search(r"[{}$:\\]", p) or len(p) > 80:
            continue
        if p.lower().endswith((".js", ".css", ".png", ".svg", ".json", ".html", ".jpg", ".webp", ".woff2")):
            continue
        out.append(p)
    return out[:6]


AUTO_SAFE_RE = re.compile(r"claim|collect|harvest|check-?in|daily", re.I)
WAIT_HINT_RE = re.compile(r"already|wait|cooldown|too early|not ready|later|claimed|next|come back|bekle|hazır|zaten", re.I)  # onay istemeden denenebilen "dogrudan odul" yollari


async def claim_post(ctx: dict, path: str):
    """Yola POST {} atar (sirayla olasi sunucu adreslerinde). (base, durum, json, metin) doner."""
    hdr = {**ctx["hdr"], "Content-Type": "application/json"}
    last = (ctx["origin"], 0, None, "")
    for base in ctx["bases"]:
        st, data, txt = await http_call("POST", base.rstrip("/") + path, hdr, {})
        last = (base, st, data, txt)
        if st not in (0, 404):
            break
    return last


async def claim_auto_run(bot: str, ctx: dict, cands: list, include_start: bool = False):
    """Guvenli yollari onay istemeden dener; basarili / bekleme cevabi verenleri otomatik toplamaya alir.
    (satirlar, denenen_yollar) doner. include_start: oturum/madencilik baslatma yollari da denensin."""
    lines, done = [], set()
    for p in sorted(cands, key=lambda x: not AUTO_SAFE_RE.search(x)):
        is_claim = bool(AUTO_SAFE_RE.search(p))
        if (not is_claim and not include_start) or len(done) >= 4:
            continue
        done.add(p)
        base, st, data, txt = await claim_post(ctx, p)
        ok = 200 <= st < 300
        summ = summarize_resp(data, txt)
        # "zaten alindi / sonra gel" gibi bekleme cevabi: yol dogru, sadece zamani gelmemis
        cooldown = (not ok) and (st in (409, 425, 429) or (
            st == 400 and WAIT_HINT_RE.search(summ + " " + (txt or ""))))
        tag = "✅" if ok else ("⏳" if cooldown else "⚠️")
        lines.append(f"{tag} POST {p} → {st} {summ}"
                     + (" (şu an bekleme süresinde, yine de otomatiğe aldım)" if cooldown else ""))
        if ok or cooldown:
            CLAIMS[f"{bot}|{p}"] = {"bot": bot, "base": base, "path": p, "mode": ctx["mode"],
                                    "auth": ctx["auth"], "every": CLAIM_EVERY_MIN if is_claim else CLAIM_EVERY_MIN * 3,
                                    "last": time.time(), "on": True, "n_ok": 1 if ok else 0, "n_err": 0,
                                    "cls": "ok" if ok else "wait", "when": time.time()}
    if done:
        await persist_claims()
    return lines, done


def summarize_resp(data, txt: str) -> str:
    """Cevabin kisa ozeti (oturum anahtari / gizli alanlar yazilmaz)."""
    if isinstance(data, dict):
        parts = []
        for k, v in list(data.items())[:12]:
            if re.search(r"token|jwt|secret|key|hash|sign|auth", str(k), re.I):
                continue
            if isinstance(v, (str, int, float, bool)) and len(str(v)) <= 60 and not str(v).startswith("eyJ"):
                parts.append(f"{k}={v}")
        if parts:
            return ", ".join(parts[:6])
        return "alanlar: " + ", ".join(list(data.keys())[:10])
    return (txt or "")[:80]


async def quick_auth(webview_url: str, c: dict):
    """Kayitli giris yontemiyle (kesif yapmadan) yetki basliklarini uretir."""
    init = parse_init_data(webview_url)
    if not init:
        return None
    pu = urlparse(webview_url.split("#")[0])
    origin = f"{pu.scheme}://{pu.netloc}"
    base_hdr = app_base_headers(origin)
    if c.get("mode") == "tma":
        return tma_headers(base_hdr, init)
    a = c.get("auth") or {}
    if c.get("mode") == "token" and a.get("url") and a.get("key"):
        st, data, _ = await http_call("POST", a["url"], {**base_hdr, "Content-Type": "application/json"},
                                      {a["key"]: init})
        tok = find_token(data)
        if tok:
            return {**base_hdr, "Authorization": f"Bearer {tok}"}
    return None


async def claim_run(c: dict):
    """Kayitli bir toplama istegini taze giris verisiyle atar. (durum, ozet) doner."""
    bot = c["bot"]
    ent = await resolve_entity(bot)
    async with APP_LOCK:
        url, how, pub = await get_webview_url(ent, bot)
    if not url:
        return 0, "mini uygulama açılamadı"
    hdr = await quick_auth(url, c)
    if hdr is None:
        return 401, "giriş yapılamadı"
    st, data, txt = await http_call("POST", c["base"].rstrip("/") + c["path"],
                                    {**hdr, "Content-Type": "application/json"}, {})
    return st, summarize_resp(data, txt)


async def claim_discover(bot: str, auto: bool = False):
    """Uygulamaya girer, kodunda gecen guvenli toplama yollarini listeler (hicbirine istek atmaz)."""
    try:
        ent = await resolve_entity(bot)
        if not getattr(ent, "bot", False):
            await send_admin(f"ℹ️ @{bot} bir bot değil.")
            return
        await send_admin(f"🔎 @{bot}: uygulamanın kendi kodundaki 'topla / oturum' yolları aranıyor "
                         + ("(güvenli 'claim/collect/daily' yollarını otomatik deneyeceğim)..." if auto
                            else "(hiçbirine istek atmıyorum)..."))
        async with APP_LOCK:
            url, how, pub = await get_webview_url(ent, bot)
        if not url:
            await send_admin(f"⚠️ @{bot}: mini uygulama açılamadı. {how[:300]}")
            return
        ctx = await app_context(url)
        cands = claim_candidates(ctx)
        if not cands:
            extra = ""
            if ctx["hosts"]:
                extra += "\n\nSunucu adresleri:\n" + "\n".join("- " + h for h in ctx["hosts"][:8])
            if ctx["paths"]:
                extra += "\n\nKodda geçen yol adayları:\n" + "\n".join("- " + p for p in ctx["paths"][:25])
            api_lines = []
            for u, data in ctx["got"][:6]:
                lk, cd, ks = [], [], []
                scan_json(data, "", lk, cd, ks)
                if ks:
                    api_lines.append(f"GET {urlparse(u).path} → {', '.join(ks[:20])}")
            if api_lines:
                extra += "\n\nAPI'den okuduğum alanlar (değerler yazılmadı):\n" + "\n".join(
                    "- " + a for a in dict.fromkeys(api_lines))
            await send_admin(f"❌ @{bot}: uygulamanın kodunda güvenli bir 'topla / oturum' yolu bulamadım.\n"
                             + "\n".join(ctx["notes"]) + extra)
            return
        auto_lines, done = [], set()
        if auto and ctx["ok"]:
            auto_lines, done = await claim_auto_run(bot, ctx, cands, False)
        remaining = [p for p in cands if p not in done]
        lines = []
        if auto and not ctx["ok"]:
            lines.append(f"⚠️ @{bot}: otomatik mod — uygulamaya giriş yapamadım, hiçbir istek atmadım.")
        elif auto_lines:
            lines += [f"🪙 @{bot}: otomatik mod — güvenli 'topla' yollarını denedim:"] + auto_lines
            lines += ["", f"Başarılı olanlar otomatik toplamaya alındı (her {CLAIM_EVERY_MIN} dk, hata olursa haber "
                          f"veririm). Liste / kapatma: /topla"]
        elif auto:
            lines.append(f"🪙 @{bot}: otomatik mod — 'claim / collect / daily' gibi doğrudan ödül yolu bulamadım.")
        if remaining:
            if lines:
                lines.append("")
            lines.append(f"🪙 @{bot}: uygulamanın kodunda şu {'onayını isteyen ' if auto else ''}'topla / oturum' yolları geçiyor:")
            lines += [f"- {p}" for p in remaining]
            lines += ["", f"Giriş yöntemi: {ctx['mode'] or 'çözülemedi'}",
                      "Henüz bunlara istek atmadım. Bir yolu denemek için butona bas (POST {} atarım).",
                      "Para harcayan / yakan / çekim yapan yollar listeye alınmadı."]
        rows = []
        if ctx["ok"]:
            for p in remaining[:4]:
                aid = new_action({"t": "claimtry", "bot": bot, "path": p})
                rows.append([InlineKeyboardButton(f"▶️ POST {p[:40]} dene", callback_data=f"a:{aid}")])
        elif remaining and not auto:
            lines.append("⚠️ Uygulamaya giriş yapamadığım için deneme butonu koymadım.")
        await send_admin("\n".join(lines), InlineKeyboardMarkup(rows) if rows else None)
    except Exception as e:
        print("[CLAIM DISCOVER]", repr(e))
        try:
            await send_admin(f"⚠️ @{bot} toplama araması başarısız: {type(e).__name__} {e}")
        except Exception:
            pass


async def claim_try(act: dict):
    """Onaylanan yola ilk kez POST {} atar; calisirsa 'otomatik topla' butonu sunar."""
    bot, path = act["bot"], act["path"]
    try:
        ent = await resolve_entity(bot)
        async with APP_LOCK:
            url, how, pub = await get_webview_url(ent, bot)
        if not url:
            await send_admin(f"⚠️ @{bot}: mini uygulama açılamadı. {how[:200]}")
            return
        ctx = await app_context(url)
        if not ctx["ok"]:
            await send_admin(f"⚠️ @{bot}: uygulamaya giriş yapamadım. " + " ".join(ctx["notes"]))
            return
        hdr = {**ctx["hdr"], "Content-Type": "application/json"}
        last = None
        for base in ctx["bases"]:
            st, data, txt = await http_call("POST", base.rstrip("/") + path, hdr, {})
            last = (base, st, data, txt)
            if st not in (0, 404):
                break
        base, st, data, txt = last
        ok = 200 <= st < 300
        lines = [f"{'✅' if ok else '⚠️'} @{bot}: POST {path} → {st}", summarize_resp(data, txt)]
        kb = None
        if ok:
            aid = new_action({"t": "claimauto", "bot": bot, "base": base, "path": path,
                              "mode": ctx["mode"], "auth": ctx["auth"]})
            kb = InlineKeyboardMarkup([[InlineKeyboardButton(
                f"🔁 Otomatik topla (her {CLAIM_EVERY_MIN} dk)", callback_data=f"a:{aid}")]])
        else:
            lines.append("İstek kabul edilmedi: zamanı gelmemiş olabilir ya da gövde/parametre gerekiyor. "
                         "Birkaç dakika sonra tekrar deneyebilirsin.")
        await send_admin("\n".join(lines), kb)
    except Exception as e:
        print("[CLAIM TRY]", repr(e))
        try:
            await send_admin(f"⚠️ @{bot} toplama denemesi başarısız: {type(e).__name__} {e}")
        except Exception:
            pass


async def claims_tick():
    """Zamani gelen otomatik toplamalari bir kez calistirir."""
    now = time.time()
    for key, c in list(CLAIMS.items()):
        if not c.get("on", True) or now - c.get("last", 0) < c.get("every", CLAIM_EVERY_MIN) * 60:
            continue
        c["last"] = now
        try:
            st, summ = await claim_run(c)
        except Exception as e:
            st, summ = 0, type(e).__name__
        cls = "ok" if 200 <= st < 300 else ("wait" if st in (400, 409, 423, 425, 429) else "err")
        prev = c.get("cls")
        c.update(st=st, msg=summ, cls=cls, when=now)
        if cls == "ok":
            c["n_ok"] = c.get("n_ok", 0) + 1
        elif cls == "err":
            c["n_err"] = c.get("n_err", 0) + 1
        await persist_claims()
        notify = (cls == "err" and prev != "err") or (
            cls == "ok" and (prev in (None, "err") or now - c.get("last_notify", 0) > 12 * 3600))
        if notify:
            c["last_notify"] = now
            await persist_claims()
            await send_admin(f"{'🪙' if cls == 'ok' else '⚠️'} Otomatik toplama @{c['bot']} {c['path']}: {st} {summ}\n"
                             f"Toplam başarılı: {c.get('n_ok', 0)}, hata: {c.get('n_err', 0)}  (liste: /topla)")


async def claims_loop():
    await asyncio.sleep(150)
    while True:
        try:
            await claims_tick()
        except Exception as e:
            print("[CLAIMS LOOP]", repr(e))
        await asyncio.sleep(60)


# ===================== LINK AT, GERISINI BOT YAPSIN =====================
# Admin bota (komut yazmadan) bir t.me linki / @kullaniciadi atar; bot sormadan: mini uygulamaya girer,
# referans linkini bulup kaydeder, guvenli odul (claim/collect/daily) yollarini bulup otomatik toplamaya alir.

APP_LINK_RE = re.compile(
    r"(?:https?://)?(?:t\.me|telegram\.me)/([A-Za-z0-9_]{4,32})(?:/([A-Za-z0-9_]+))?(?:\?([^\s#]*))?", re.I)
SKIP_LINK_NAMES = {"joinchat", "addstickers", "addemoji", "addlist", "share", "proxy", "socks", "iv", "login",
                   "boost", "setlanguage", "confirmphone", "invoice", "bg", "addtheme"}
AUTO_LINK_BUSY: set = set()


def parse_link_targets(text: str) -> list:
    """Mesajdaki t.me linklerinden / @kullaniciadlarindan [(ad, kisa_ad, baslangic_parametresi)] cikarir."""
    out = []
    for m in APP_LINK_RE.finditer(text or ""):
        name = m.group(1).lower()
        if name in SKIP_LINK_NAMES:
            continue
        qs = parse_qs(m.group(3) or "")
        start = (qs.get("startapp") or qs.get("start") or [""])[0]
        out.append((name, m.group(2) or "", start))
    if not out:
        for tok in re.split(r"[\s,;]+", (text or "").strip()):
            if re.fullmatch(r"@[A-Za-z0-9_]{4,32}", tok) or re.fullmatch(r"[A-Za-z0-9_]{2,}[Bb][Oo][Tt]", tok):
                out.append((tok.lstrip("@").lower(), "", ""))
    seen_n, uniq = set(), []
    for t in out:
        if t[0] not in seen_n:
            seen_n.add(t[0])
            uniq.append(t)
    return uniq[:5]


async def auto_link(name: str, short: str = "", start: str = ""):
    """Gonderilen link/ad icin her seyi kendisi yapar: giris, referans bulma, otomatik odul toplama."""
    if name in AUTO_LINK_BUSY:
        return
    AUTO_LINK_BUSY.add(name)
    try:
        ent = await resolve_entity(name)
        if not getattr(ent, "bot", False):
            await send_admin(f"ℹ️ @{name} bir bot / mini uygulama değil (kanal, grup ya da kişi), atladım.")
            return
        await send_admin(f"🤖 @{name}: otomatik işlem başladı (giriş, referans, ödül toplama). Sormadan yapıyorum...")
        async with APP_LOCK:
            url, how, pub = await get_webview_url(ent, name, short, start)
        out = [f"🤖 @{name} — otomatik sonuç"]

        if not url:
            out.append("📱 Mini uygulama açılamadı: " + (how.split("\n")[0])[:260])
            links = []
            if await try_lock(TG_LOCK, 8):
                try:
                    links = await ref_from_chat(ent, name)
                finally:
                    TG_LOCK.release()
            if links:
                REFS[name] = {"link": links[0], "src": "bot sohbeti", "t": time.time()}
                await persist_refs()
                out.append(f"🔗 Referans linkin (sohbetten) kaydedildi: {links[0]}")
            out.append("💬 Sohbet botu gibi davranıp /start gönderiyorum; rapor ayrıca gelecek.")
            await send_admin("\n".join(out))
            spawn(inspect_bot(name, start))
            return

        out.append("📱 " + how)
        ctx = await app_context(url)
        res = analyze_ctx(ctx)
        if res["links"]:
            REFS[name] = {"link": res["links"][0], "src": "mini uygulama API", "t": time.time()}
            await persist_refs()
            out.append(f"🔗 Referans linkin kaydedildi: {res['links'][0]}")
        elif res["codes"]:
            out.append("🔑 Referansa benzeyen alanlar: " + ", ".join(f"{p}={v}" for p, v in res["codes"][:3]))
        else:
            out.append("🔗 Referans linkini bulamadım.")

        if ctx["ok"]:
            cands = claim_candidates(ctx)
            lines = []
            if cands:
                lines, done = await claim_auto_run(name, ctx, cands, True)
            if lines:
                out += lines
                out.append(f"↻ Başarılı / bekleme süresindeki yollar otomatik toplamaya alındı "
                           f"(her {CLAIM_EVERY_MIN} dk). Liste / kapatma: /topla")
            else:
                out.append("🪙 Kodda güvenli bir 'claim / collect / daily / oturum' yolu bulamadım.")
                if res["paths"]:
                    out.append("Kodda geçen yol adayları: " + ", ".join(res["paths"][:8]))
        else:
            out.append("⚠️ Uygulamanın API girişini çözemedim, istek atmadım. " + " ".join(ctx["notes"])[:200])
            if res["hosts"]:
                out.append("Sunucu adresleri: " + ", ".join(res["hosts"][:5]))
            if res["paths"]:
                out.append("Yol adayları: " + ", ".join(res["paths"][:8]))
        await send_admin("\n".join(out))
    except Exception as e:
        print("[AUTO LINK]", repr(e))
        try:
            await send_admin(f"⚠️ @{name} otomatik işlem hatası: {type(e).__name__} {str(e)[:150]}")
        except Exception:
            pass
    finally:
        AUTO_LINK_BUSY.discard(name)


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Komut olmayan mesaj: link / @ad ise otomatik isleme al. Admin disindakileri sessizce yok sayar."""
    user = update.effective_user
    msg = update.effective_message
    if not user or not msg or user.id not in ADMIN_IDS:
        return
    text = (msg.text or msg.caption or "")
    for e in (msg.entities or []) + (msg.caption_entities or []):
        if getattr(e, "url", None):
            text += " " + e.url
    for name, short, start in parse_link_targets(text):
        spawn(auto_link(name, short, start))


# ===================== GUNLUK RUTIN =====================

async def run_routine(r: dict) -> str:
    assert tg_client is not None
    async with TG_LOCK:
        ent = await resolve_entity(r["bot"])
        sent = await tg_client.send_message(ent, "/start")
        await asyncio.sleep(INSPECT_WAIT)
        msgs = await fetch_incoming(ent, sent.id + 1)
        target = None
        for m in reversed(msgs):  # en yeniden eskiye
            for row in (m.buttons or []):
                for b in row:
                    if norm_label(b.text or "") == norm_label(r["label"]) and classify_button(b) == "click":
                        target = m
                        break
                if target:
                    break
            if target:
                break
        if not target:
            return f"❓ @{r['bot']}: '{r['label']}' butonu bulunamadı (bot menüsü değişmiş olabilir)."
        await asyncio.sleep(random.uniform(1.5, 4))
        await target.click(filter=lambda b: norm_label(b.text or "") == norm_label(r["label"]))
        await asyncio.sleep(4)
        after = await fetch_incoming(ent, target.id)
    snippet = ""
    for m in reversed(after):
        if (m.message or "").strip():
            snippet = m.message.strip()[:300]
            break
    return f"✅ @{r['bot']}: '{r['label']}' basıldı.\n{snippet}"


async def routine_loop():
    if not ROUTINES_ON:
        return
    await asyncio.sleep(90)
    while True:
        try:
            now = time.time()
            for rid, r in list(ROUTINES.items()):
                if now - r.get("last", 0) < 86400 + r.get("jitter", 0):
                    continue
                try:
                    msg = await run_routine(r)
                except Exception as e:
                    msg = f"⚠️ Rutin hatası @{r['bot']}: {e}"
                r["last"] = time.time()
                r["jitter"] = random.randint(0, 1800)
                await persist_routines()
                await send_admin("🔁 GÜNLÜK RUTİN\n" + msg)
                await asyncio.sleep(random.uniform(20, 60))
        except Exception as e:
            print("[ROUTINE LOOP]", repr(e))
        await asyncio.sleep(1800)


# ===================== TELETHON =====================

async def on_group_message(event):
    try:
        if event.chat_id not in ACTIVE_SOURCES:
            return
        msg = event.message
        text = msg.message or ""

        if msg.reply_markup:
            try:
                await msg.get_buttons()
            except Exception:
                pass
        extra = []
        for ent in msg.entities or []:
            u = getattr(ent, "url", None)
            if u:
                extra.append(str(u))
        for row in msg.buttons or []:
            for b in row:
                u = getattr(b, "url", None)
                if u:
                    extra.append(str(u))
        full = text + "\n" + "\n".join(extra)

        bots = list(dict.fromkeys(m.lower() for m in BOT_LINK_RE.findall(full)))
        links = []

        if bots:
            yeni = [b for b in bots if f"bot:{b}" not in seen]
            if not yeni:
                return
            now = time.time()
            for b in yeni:
                seen[f"bot:{b}"] = now
            await persist_seen()
            bots = yeni
        else:
            if ONLY_BOTS:
                return
            links = extract_links(full)
            if not (links or KEYWORD_RE.search(text or "")):
                return
            fp = "fp:" + fingerprint(text, links)
            cleanup_seen()
            if fp in seen:
                return
            seen[fp] = time.time()

        chat = await event.get_chat()
        title = (
            getattr(chat, "title", None) or getattr(chat, "username", None) or str(event.chat_id)
        )
        guide = await ai_guide(text) if len(text.strip()) >= 30 else ""
        warn = [w for w in BAD_WORDS if w in text.lower()]
        await notify_admin(title, text, bots, links, guide, warn)

        # Otomatik inceleme: botlara /start yazip cevabi oku (grup mesajinda uyari varsa acma)
        if INSPECT and bots and not warn:
            for b in bots:
                spawn(inspect_bot(b))
    except Exception as e:
        print("[LISTENER]", repr(e))


# ===================== BOT KOMUTLARI =====================

@admin_only
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(
        "Airdrop / oyun bot radari\n\n"
        "👉 Komut yazmana gerek yok: bir t.me linki ya da @kullaniciadi gönder, giriş + referans + ödül toplamayı sormadan kendisi yapar.\n\n"
        "Komutlar:\n"
        "/add -1001234567890  (grup ekle)\n"
        "/del -1001234567890\n"
        "/list\n"
        "/incele botadi  (bota /start yaz, cevabı oku, rapor ver)\n"
        "/oyun botadi  (mini uygulamanın sunucu adreslerini çıkar)\n"
        "/ref botadi  (referans linkini bul ve kaydet; /ref ile liste)\n"
        "/topla botadi  (mini uygulamada ödül toplama / oturum başlatma yolunu bul, otomatikleştir)\n"
        "/gorev botadi  (görev listesindeki görevleri otomatik yap)\n"
        "/otopilot gram_prbot  (hiç durmadan çalış, 7 gün sonra kanallardan çık)\n"
        "/cik  (süresi dolan kanallardan şimdi çık)\n"
        "/yetkiler  (botu kullanabilen hesaplar)\n"
        "/dur  (otomatik görevi durdur)\n"
        "/rutin  (günlük otomatik rutinler)\n"
        "/bil botadi  (zaten bildiğin oyun, bildirim gelmesin)\n"
        "/status\n\n"
        "Telethon hesabin dinlenecek grupta UYE olmali."
    )


@admin_only
async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await cmd_start(update, context)


@admin_only
async def cmd_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.effective_message.reply_text("Kullanim:\n/add -1001234567890")
        return
    parts = parse_id_list(" ".join(context.args))
    replies = [await add_source(p) for p in parts]
    await update.effective_message.reply_text("\n\n".join(replies)[:4000])


@admin_only
async def cmd_del(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.effective_message.reply_text("Kullanim:\n/del -1001234567890")
        return
    parts = parse_id_list(" ".join(context.args))
    replies = [await del_source(p) for p in parts]
    await update.effective_message.reply_text("\n\n".join(replies)[:4000])


@admin_only
async def cmd_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await enrich_source_titles()
    await update.effective_message.reply_text(
        list_sources_text(), reply_markup=build_list_keyboard()
    )


@admin_only
async def cmd_bil(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.effective_message.reply_text(
            "Kullanim:\n/bil hamster_kombat_bot blumcryptobot\n(link de yazabilirsin)"
        )
        return
    eklenen = []
    for a in context.args:
        m = BOT_LINK_RE.search(a)
        name = (m.group(1) if m else a.strip().lstrip("@")).lower()
        if re.fullmatch(r"[a-z0-9_]{2,}bot", name):
            seen[f"bot:{name}"] = time.time()
            eklenen.append(name)
    if eklenen:
        await persist_seen()
        await update.effective_message.reply_text(
            "Bilinen olarak eklendi: " + ", ".join("@" + n for n in eklenen)
        )
    else:
        await update.effective_message.reply_text("Gecerli bot adi bulunamadi.")


@admin_only
async def cmd_incele(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.effective_message.reply_text("Kullanim:\n/incele hamster_kombat_bot")
        return
    a = context.args[0]
    name = parse_bot_arg(a)
    if not name:
        await update.effective_message.reply_text("Geçerli bir kullanıcı adı yaz (örnek: gram_prbot ya da MyAgeApp).")
        return
    await update.effective_message.reply_text(
        f"@{name} inceleniyor, 10-20 saniye (sırada başka varsa daha uzun)..."
    )
    spawn(inspect_bot(name))


@admin_only
async def cmd_oyun(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.effective_message.reply_text(
            "Kullanim:\n/oyun lootvaultdexbot\nveya bir site adresi:\n/oyun https://lootvault.lol")
        return
    a = context.args[0]
    if a.lower().startswith("http"):
        await update.effective_message.reply_text("Site inceleniyor, 20-40 saniye...")
        spawn(recon_game(a))
        return
    name = parse_bot_arg(a)
    if not name:
        await update.effective_message.reply_text("Geçerli bir kullanıcı adı yaz (örnek: gram_prbot ya da MyAgeApp) ya da http adresi.")
        return
    await update.effective_message.reply_text(f"@{name} inceleniyor, 20-40 saniye...")
    spawn(recon_game(name))


@admin_only
async def cmd_gorev(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.effective_message.reply_text(
            "Kullanim:\n/gorev gram_prbot\n(menüde Kazanç > Kanallar'a gider; görev kalmayana ya da /dur diyene kadar yapar)\n\n"
            "Sayıyla sınırlamak için:\n/gorev gram_prbot kazanc>kanallar 30\n\n"
            "Durdurmak için: /dur")
        return
    a = context.args[0]
    name = parse_bot_arg(a)
    if not name:
        await update.effective_message.reply_text("Geçerli bir kullanıcı adı yaz (örnek: gram_prbot ya da MyAgeApp).")
        return
    cap, steps = AUTO_DEFAULT_CAP, ["kazanc", "kanallar"]
    for x in context.args[1:]:
        if x.isdigit():
            cap = max(0, int(x))
        else:
            steps = [y.strip() for y in x.split(">") if y.strip()]
    if AUTO_RUNNING:
        await update.effective_message.reply_text("⏳ Zaten bir otomatik görev çalışıyor. Durdurmak için /dur")
        return
    await update.effective_message.reply_text(
        f"🤖 @{name}: {' > '.join(steps)} yolundan {cap if cap > 0 else 'sınırsız'} görev otomatik başlıyor. Bitince özet gelecek. Durdurmak için /dur")
    spawn(run_autotasks(name, steps, cap))


@admin_only
async def cmd_otopilot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if not args:
        await update.effective_message.reply_text(autopilot_status_text())
        return
    a = args[0].lower().lstrip("@")
    if a in ("kapat", "off", "durdur", "dur"):
        AUTOPILOT["on"] = False
        await persist_autopilot()
        await update.effective_message.reply_text(
            "🛬 Otopilot kapatıldı. Görev taraması durdu; 7 günü dolan kanallardan çıkış takibi sürüyor.")
        return
    m = BOT_LINK_RE.search(a)
    name = (m.group(1) if m else a).lower()
    if not re.fullmatch(r"[a-z0-9_]{2,}bot", name):
        await update.effective_message.reply_text("Kullanım:\n/otopilot gram_prbot\n/otopilot kapat\n/otopilot (durum)")
        return
    steps = ["kazanc", "kanallar"]
    if len(args) > 1:
        steps = [y.strip() for y in args[1].split(">") if y.strip()] or steps
    AUTOPILOT.update({"on": True, "bot": name, "steps": steps, "since": time.time()})
    await persist_autopilot()
    await update.effective_message.reply_text(
        f"🛫 Otopilot açıldı: @{name} ({' > '.join(steps)})\n"
        f"Şimdi ilk turu başlatıyorum. Sonra her {AUTOPILOT_MIN_MINUTES}-{AUTOPILOT_MAX_MINUTES} dk'da bir "
        f"yeni görevleri tarar, hiç durmaz. Katıldığım kanallardan "
        f"{LEAVE_AFTER_HOURS // 24} gün {LEAVE_AFTER_HOURS % 24} saat sonra çıkarım.\n"
        f"Kapatmak için: /otopilot kapat")
    spawn(run_autotasks(name, steps, 0))


@admin_only
async def cmd_cik(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text("Süresi dolan kanallar kontrol ediliyor...")
    spawn(leave_and_report(True))


@admin_only
async def cmd_dur(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global AUTO_STOP
    if AUTO_RUNNING:
        AUTO_STOP = True
        await update.effective_message.reply_text("Durdurma isteği alındı, o anki görev bitince duracak." + (" Otopilot hâlâ açık, sonraki turda yeniden başlar; tamamen kapatmak için /otopilot kapat." if AUTOPILOT.get("on") else ""))
    else:
        await update.effective_message.reply_text("Çalışan otomatik görev yok.")


@admin_only
async def cmd_yetkiler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_USER_ID:
        await update.effective_message.reply_text("Bu sadece asıl sahibe açık.")
        return
    lines = ["🔑 Botu kullanabilenler:"]
    rows = []
    for uid in sorted(ADMIN_IDS):
        info = EXTRA_ADMINS.get(str(uid), {})
        tag = "asıl sahip" if uid == ADMIN_USER_ID else (info.get("name") or "eklenen")
        lines.append(f"- {uid} ({tag})")
        if str(uid) in EXTRA_ADMINS:
            rows.append([InlineKeyboardButton(f"Yetkiyi kaldır: {uid}", callback_data=f"adm:del:{uid}")])
    lines.append("\nYeni hesap eklemek için: o hesaptan bota /start yaz, sana onay butonu gelir.")
    await update.effective_message.reply_text("\n".join(lines), reply_markup=InlineKeyboardMarkup(rows) if rows else None)


def routines_text_and_kb():
    if not ROUTINES:
        return "Rutin yok.\n\nBir botu /incele ile incele, bir butona bas, çıkan\n'🔁 Her gün otomatik' butonuna dokun.", None
    lines = [f"Günlük rutinler ({len(ROUTINES)}):"]
    rows = []
    for rid, r in ROUTINES.items():
        lines.append(f"- @{r['bot']} → '{r['label']}'")
        rows.append([InlineKeyboardButton(f"Sil: {r['bot'][:14]} / {r['label'][:14]}", callback_data=f"rd:{rid}")])
    return "\n".join(lines), InlineKeyboardMarkup(rows)


@admin_only
async def cmd_ref(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if not args:
        if not REFS:
            await update.effective_message.reply_text(
                "Kayıtlı referans linki yok.\n\n/ref botadi → otomatik ara\n"
                "/ref botadi https://t.me/... → elle kaydet\n/ref sil botadi")
            return
        lines = ["Kayıtlı referans linkleri:"] + [f"@{b}: {v['link']}" for b, v in REFS.items()]
        await update.effective_message.reply_text("\n".join(lines)[:4000], disable_web_page_preview=True)
        return
    if args[0].lower() in ("sil", "del") and len(args) > 1:
        name = args[1].lstrip("@").lower()
        if REFS.pop(name, None) is not None:
            await persist_refs()
            await update.effective_message.reply_text(f"@{name} referans linki silindi.")
        else:
            await update.effective_message.reply_text("Böyle bir kayıt yok.")
        return
    name = parse_bot_arg(args[0])
    if not name:
        await update.effective_message.reply_text("Geçerli bir kullanıcı adı yaz (örnek: gram_prbot ya da MyAgeApp).")
        return
    if len(args) >= 2 and args[1].lower().startswith(("http", "t.me")):
        link = args[1] if args[1].lower().startswith("http") else "https://" + args[1]
        if "t.me/" not in link.lower():
            await update.effective_message.reply_text("Bu bir t.me linki değil.")
            return
        REFS[name] = {"link": link, "src": "elle", "t": time.time()}
        await persist_refs()
        await update.effective_message.reply_text(f"@{name} için referans linki kaydedildi.")
        return
    spawn(ref_finder(name))


@admin_only
async def cmd_topla(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if not args:
        if not CLAIMS:
            await update.effective_message.reply_text(
                "Otomatik toplama yok.\n\n/topla botadi → uygulamanın kodundaki güvenli 'topla/oturum' "
                "yollarını bul, onayınla dene\n/topla botadi oto → onay istemeden güvenli claim/collect/daily yollarını dene, çalışanı otomatiğe al\n/topla kapat botadi → o botun otomatik toplamalarını sil")
            return
        now = time.time()
        lines = ["Otomatik toplamalar:"]
        for c in CLAIMS.values():
            ago = f"{int((now - c['when']) // 60)} dk önce" if c.get("when") else "henüz çalışmadı"
            lines.append(f"- @{c['bot']} POST {c['path']} (her {c.get('every', CLAIM_EVERY_MIN)} dk) · son: "
                         f"{c.get('st', '-')} {c.get('msg', '')[:40]} ({ago}) · ✓{c.get('n_ok', 0)} ✗{c.get('n_err', 0)}")
        await update.effective_message.reply_text("\n".join(lines)[:4000])
        return
    if args[0].lower() in ("kapat", "sil") and len(args) > 1:
        name = args[1].lstrip("@").lower()
        keys = [k for k, c in CLAIMS.items() if c["bot"] == name]
        for k in keys:
            CLAIMS.pop(k, None)
        await persist_claims()
        await update.effective_message.reply_text(f"@{name}: {len(keys)} otomatik toplama silindi.")
        return
    name = parse_bot_arg(args[0])
    if not name:
        await update.effective_message.reply_text("Geçerli bir kullanıcı adı yaz (örnek: gram_prbot ya da MyAgeApp).")
        return
    auto = any(x.lower() in ("oto", "otomatik", "auto") for x in args[1:])
    spawn(claim_discover(name, auto))


@admin_only
async def cmd_rutin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text, kb = routines_text_and_kb()
    await update.effective_message.reply_text(text, reply_markup=kb)


def kb_without(markup, data: str):
    if not markup:
        return None
    rows = [[b for b in row if b.callback_data != data] for row in markup.inline_keyboard]
    rows = [r for r in rows if r]
    return InlineKeyboardMarkup(rows) if rows else None


@admin_only
async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not q or not q.data:
        return
    data = q.data

    if data.startswith("del:"):
        await q.answer()
        try:
            cid = int(data[4:])
        except ValueError:
            await q.edit_message_text("Gecersiz ID")
            return
        msg = await del_source(cid)
        await enrich_source_titles()
        text = msg + "\n\n" + list_sources_text()
        kb = build_list_keyboard()
        try:
            await q.edit_message_text(text[:4000], reply_markup=kb)
        except Exception:
            await q.message.reply_text(text[:4000], reply_markup=kb)

    elif data.startswith("adm:"):
        await q.answer()
        if q.from_user.id != ADMIN_USER_ID:
            await q.message.reply_text("Yetki verme/kaldırma sadece asıl sahibe açık.")
            return
        parts = data.split(":")
        act = parts[1] if len(parts) > 1 else ""
        uid = int(parts[2]) if len(parts) > 2 and parts[2].lstrip("-").isdigit() else 0
        if act == "ok" and uid:
            ADMIN_IDS.add(uid)
            try:
                chat = await context.bot.get_chat(uid)
                nm = f"{chat.full_name} (@{chat.username})" if chat.username else str(chat.full_name)
            except Exception:
                nm = str(uid)
            EXTRA_ADMINS[str(uid)] = {"name": nm, "t": time.time()}
            await persist_admins()
            await q.message.reply_text(f"✅ Yetki verildi: {nm} (ID {uid})")
            try:
                await context.bot.send_message(uid, "✅ Erişim verildi. /start yaz, komutlar orada.")
            except Exception:
                pass
        elif act == "no" and uid:
            await q.message.reply_text(f"❌ Reddedildi: ID {uid}")
        elif act == "del" and uid and str(uid) in EXTRA_ADMINS:
            ADMIN_IDS.discard(uid)
            EXTRA_ADMINS.pop(str(uid), None)
            await persist_admins()
            await q.message.reply_text(f"Yetki kaldırıldı: ID {uid}")

    elif data.startswith("ins:"):
        await q.answer("İnceleniyor...")
        name = data[4:].strip().lower()
        if re.fullmatch(r"[a-z0-9_]{2,}bot", name):
            spawn(inspect_bot(name))
            await q.message.reply_text(f"@{name} inceleniyor...")

    elif data.startswith("a:"):
        act = ACTIONS.get(data[2:])
        if not act:
            await q.answer("Bu buton eskimiş.", show_alert=True)
            await q.message.reply_text("Bu işlemin süresi dolmuş (servis yeniden başlamış olabilir). "
                                       "/incele botadi ile yeniden bak.")
            return
        await q.answer("İşleniyor...")
        try:
            await q.edit_message_reply_markup(reply_markup=kb_without(q.message.reply_markup, data))
        except Exception:
            pass
        try:
            await handle_action(act)
        except Exception as e:
            print("[ACTION]", repr(e))
            await send_admin(f"⚠️ İşlem hatası: {e}")

    elif data.startswith("rd:"):
        await q.answer()
        ROUTINES.pop(data[3:], None)
        await persist_routines()
        text, kb = routines_text_and_kb()
        try:
            await q.edit_message_text(text, reply_markup=kb)
        except Exception:
            await q.message.reply_text(text, reply_markup=kb)
    else:
        await q.answer()


@admin_only
async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    n_bots = sum(1 for k in seen if k.startswith("bot:"))
    await update.effective_message.reply_text(
        f"Durum: aktif\n"
        f"Dinlenen: {len(ACTIVE_SOURCES)}\n"
        f"Gorulen/bilinen bot: {n_bots}\n"
        f"Mod: {'sadece bot linkleri' if ONLY_BOTS else 'genis filtre'}\n"
        f"Otomatik inceleme: {'acik' if INSPECT else 'kapali'}\n"
        f"Kanal katilim limiti: {JOIN_DAILY_MAX if JOIN_DAILY_MAX > 0 else 'yok'}\n"
        f"Otomatik gorev: {'calisiyor' if AUTO_RUNNING else 'bosta'}\n"
        f"Otopilot: {autopilot_short()} | kayitli kanal: {len(JOINS)}\n"
        f"Gunluk rutin: {len(ROUTINES)} ({'acik' if ROUTINES_ON else 'kapali'})\n"
        f"Groq: {'acik' if GROQ_API_KEY else 'kapali'} ({GROQ_MODEL})\n"
        f"Gemini (yedek): {'acik' if GEMINI_API_KEY else 'kapali'} ({GEMINI_MODEL})\n"
        f"Upstash: {'acik' if UPSTASH_REDIS_REST_URL else 'kapali'}\n"
        f"Keepalive: {'acik' if (KEEPALIVE and RENDER_URL) else 'kapali'}"
    )


# ===================== HTTP (Render port) =====================

async def handle_health(request):
    return web.Response(text=f"ok sources={len(ACTIVE_SOURCES)}", content_type="text/plain")


async def start_http():
    app = web.Application()
    app.router.add_get("/", handle_health)
    app.router.add_get("/health", handle_health)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    print(f"[HTTP] Port {PORT} acik (Render health)")


async def keepalive_loop():
    if not (KEEPALIVE and RENDER_URL):
        print("[KEEPALIVE] kapali")
        return
    print("[KEEPALIVE] acik:", RENDER_URL)
    while True:
        await asyncio.sleep(600)
        try:
            assert http_session is not None
            async with http_session.get(
                RENDER_URL + "/health", timeout=aiohttp.ClientTimeout(total=20)
            ) as r:
                await r.read()
        except Exception as e:
            print("[KEEPALIVE HATA]", repr(e))


# ===================== MAIN =====================

# ============================================================
# V20 - UNIVERSAL MINIAPP ENGINE + BROWSER AUTOMATION v7
# Her Telegram mini uygulama botu icin ortak otomasyon.
# "miniapp botadi" (slash'siz) ve "/miniapp botadi" ikisi de calisir.
# ============================================================

import io as _io

try:
    from playwright.async_api import async_playwright
    PLAYWRIGHT_OK = True
except Exception:
    PLAYWRIGHT_OK = False

MINIAPP_BUSY = set()
_BROWSER = None
_PW = None

BALANCE_HINTS = (
    "balance", "balances", "coin", "coins", "point", "points",
    "token", "tokens", "credit", "credits", "gem", "gems",
    "amount", "total", "wallet", "cash", "money"
)

PRIORITY_BALANCE_PATHS = (
    "api/user", "api/me", "api/profile", "api/account",
    "api/v1/user", "api/v1/me", "api/v1/profile", "user", "me", "profile"
)

DANGEROUS_PATH_RE = re.compile(
    r"deposit|withdraw|swap|stake|buy|sell|transfer|pay|purchase|"
    r"wallet|connect|auth|login|sign-?in|session|revoke|logout|signout",
    re.I
)

DANGER_CLICK_RE = re.compile(
    r"wallet|c\u00fczdan|deposit|withdraw|ekle|cekim|\u00e7ekim|yat\u0131r|"
    r"buy|sat\u0131n|sat|swap|stake|invest|premium|stars|usdt|"
    r"pay|\u00f6deme|confirm|onayla|approve|sign|connect|login|giri\u015f",
    re.I
)

SAFE_CLICK_RE = re.compile(
    r"claim|collect|daily|check[- ]?in|reward|bonus|harvest|"
    r"al|topla|\u00f6d\u00fcl|g\u00fcnl\u00fck|open|start|play|get|tap|earn|task",
    re.I
)

POPUP_SUCCESS_RE = re.compile(
    r"success|successful|claimed|collected|received|added|completed|"
    r"ba\u015far\u0131l\u0131|al\u0131nd\u0131|tamamland\u0131|kazand\u0131n",
    re.I
)

POPUP_WAIT_RE = re.compile(
    r"already|wait|cooldown|too early|not ready|later|come back|"
    r"zaten|bekle|haz\u0131r de\u011fil|sonra|tekrar dene",
    re.I
)

POPUP_ERROR_RE = re.compile(
    r"error|failed|invalid|expired|denied|forbidden|"
    r"hata|ba\u015far\u0131s\u0131z|ge\u00e7ersiz|s\u00fcre doldu",
    re.I
)

API_PATH_RE = re.compile(
    r"['\"`](/api/[A-Za-z0-9_\-/.]{2,100}|/v[0-9]+/[A-Za-z0-9_\-/.]{2,100}|"
    r"/[A-Za-z0-9_\-/]{2,60}(?:claim|collect|harvest|check-?in|daily|reward|bonus)[A-Za-z0-9_\-/]*)['\"`]",
    re.I
)

SCRIPT_URL_RE = re.compile(
    r'(?:src=["\']|href=["\']|["\'])([^"\']*?\.js(?:\?[^"\']*)?)["\']',
    re.I
)

DYNAMIC_IMPORT_RE = re.compile(
    r'import\(\s*["\']([^"\']+)["\']\s*\)|import\(\s*`([^`]+)`\s*\)',
    re.I
)


def classify_popup_text(text: str) -> str:
    t = (text or "").strip()
    if not t:
        return "unknown"
    if POPUP_SUCCESS_RE.search(t):
        return "success"
    if POPUP_WAIT_RE.search(t):
        return "wait"
    if POPUP_ERROR_RE.search(t):
        return "error"
    return "unknown"


def extract_numeric_balances(obj, out=None, prefix=""):
    if out is None:
        out = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            key = f"{prefix}.{k}" if prefix else str(k)
            lk = k.lower()
            if isinstance(v, (int, float)) and any(h in lk for h in BALANCE_HINTS):
                out[key] = v
            elif isinstance(v, (dict, list)):
                extract_numeric_balances(v, out, key)
    elif isinstance(obj, list):
        for i, v in enumerate(obj[:20]):
            extract_numeric_balances(v, out, f"{prefix}[{i}]")
    return out


async def universal_read_balance(ctx: dict):
    bases = ctx.get("bases") or []
    headers = ctx.get("hdr") or {}
    found = {}

    ordered = list(PRIORITY_BALANCE_PATHS) + [
        p for p in DEFAULT_GET_PATHS if p not in PRIORITY_BALANCE_PATHS
    ]

    for path in ordered:
        if DANGEROUS_PATH_RE.search(path):
            continue
        for base in bases:
            url = base.rstrip("/") + "/" + path.lstrip("/")
            st, data, txt = await http_call("GET", url, headers)
            if st != 200:
                continue
            vals = extract_numeric_balances(data)
            if vals:
                found[path] = vals
                break
        if found:
            break

    return found


def balance_diff(before: dict, after: dict):
    diffs = {}
    for k, after_val in after.items():
        before_val = before.get(k)
        if isinstance(before_val, (int, float)) and isinstance(after_val, (int, float)):
            d = after_val - before_val
            if d:
                diffs[k] = d
    return diffs


async def deep_scan_claims(ctx: dict, webview_url: str):
    extra = []
    all_paths = []
    base = webview_url.split("#")[0]
    seen_urls = set()
    queue = [(base, 0)]
    scanned = 0

    def add_path(p):
        if not p or len(p) > 120:
            return
        if p in all_paths:
            return
        all_paths.append(p)
        if DANGEROUS_PATH_RE.search(p):
            return
        if not re.search(r"claim|collect|harvest|check-?in|daily|reward|bonus", p, re.I):
            return
        if p not in extra:
            extra.append(p)

    while queue and scanned < 60 and len(extra) < 30:
        u, depth = queue.pop(0)
        if u in seen_urls:
            continue
        seen_urls.add(u)
        txt = await fetch_text(u, 3000000)
        if not txt:
            continue
        scanned += 1

        for m in API_PATH_RE.finditer(txt):
            add_path(m.group(1))

        if depth < 3:
            for m in DYNAMIC_IMPORT_RE.finditer(txt):
                su = m.group(1) or m.group(2)
                if not su or su.startswith("data:") or su.startswith("blob:"):
                    continue
                full = urljoin(u, su)
                if full not in seen_urls:
                    queue.append((full, depth + 1))

            for sm in SCRIPT_URL_RE.finditer(txt):
                su = sm.group(1)
                if su.startswith("data:") or su.startswith("blob:"):
                    continue
                full = urljoin(u, su)
                if full not in seen_urls:
                    queue.append((full, depth + 1))

    return extra[:30], scanned, all_paths[:40]


async def get_browser():
    global _PW, _BROWSER
    if not PLAYWRIGHT_OK:
        return None
    if _BROWSER is None:
        _PW = await async_playwright().start()
        _BROWSER = await _PW.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"]
        )
    return _BROWSER


def parse_balance_from_text(text: str):
    m = re.search(r"balance\s*[:=]?\s*([\d.,]+)", (text or "").lower())
    if not m:
        return None
    raw = m.group(1).replace(",", "").replace(".", "") if "," in m.group(1) else m.group(1)
    try:
        return float(raw)
    except Exception:
        return None


async def browser_auto(bot: str, url: str) -> list:
    """Mini uygulamayı gerçek tarayıcıda açar; JS ile güvenli butonları tıklar.

    Network isteklerini de yakalar; claim/daily API çağrılarını raporlar.
    """
    lines = []
    browser = await get_browser()
    if browser is None:
        return ["Playwright kurulu değil; tarayıcı otomasyonu atlandı."]

    context = await browser.new_context(
        user_agent=(
            "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0 Mobile Safari/537.36"
        ),
        viewport={"width": 412, "height": 915},
    )
    page = await context.new_page()

    api_calls = []

    def on_request(req):
        u = req.url
        if any(k in u.lower() for k in ("api", "claim", "daily", "reward", "check", "collect")):
            api_calls.append(u)

    page.on("request", on_request)

    async def shot(caption):
        try:
            s = await page.screenshot(type="png")
            if tg_client:
                await tg_client.send_file(
                    ADMIN_CHAT_ID,
                    _io.BytesIO(s),
                    caption=caption,
                    force_document=False
                )
        except Exception as e:
            lines.append(f"Ekran görüntüsü gönderilemedi: {type(e).__name__} {e}")

    async def js_click(pattern: str, max_wait: int = 4000):
        """Sayfadaki metne gore ilk guvenli elementi JS ile tiklar."""
        try:
            label = await page.evaluate(
                """(pattern) => {
                    const rx = new RegExp(pattern, 'i');
                    const bad = /wallet|cüzdan|deposit|withdraw|ekle|çekim|yatır|buy|satın|sat|swap|stake|invest|premium|stars|usdt|pay|ödeme|confirm|onayla|approve|sign|connect|login|giriş/i;
                    const els = Array.from(document.querySelectorAll('button, a, [role=button], div, span'));
                    for (const el of els) {
                        const t = (el.innerText || el.textContent || '').trim();
                        if (!t || t.length > 60) continue;
                        if (!rx.test(t)) continue;
                        if (bad.test(t)) continue;
                        el.click();
                        return t;
                    }
                    return null;
                }""",
                pattern,
            )
        except Exception as e:
            return None
        if label:
            await page.wait_for_timeout(max_wait)
        return label

    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(8000)

        title = await page.title()
        body_text = ""
        try:
            body_text = await page.inner_text("body")
        except Exception:
            pass

        lines.append(f"Sayfa başlığı: {title[:80]}")
        lines.append(
            f"DOM: canvas={await page.locator('canvas').count()}, "
            f"iframe={await page.locator('iframe').count()}, "
            f"buton={await page.locator('button, [role=button], a').count()}"
        )
        lines.append("Ekran metni: " + (re.sub(r"\s+", " ", body_text)[:200] or "(boş)"))

        await shot(f"{bot} - giriş ekranı")

        balance_before = parse_balance_from_text(body_text)
        if balance_before is not None:
            lines.append(f"Ekrandan okunan bakiye: {balance_before}")

        # 1) Uygulamaya gir
        entered = await js_click(r"^(open|start|play|launch|enter)$")
        if not entered:
            entered = await js_click(r"open|start|play|launch|enter")
        if entered:
            lines.append(f"Uygulamaya giriş butonu: {entered}")
            await page.wait_for_timeout(5000)

        # 2) Earn/Tasks/Daily sekmeleri
        for tab in ["earn", "tasks", "daily", "rewards", "check-in", "bonus"]:
            res = await js_click(re.escape(tab))
            if res:
                lines.append(f"Sekme butonu: {res}")
                break

        # 3) Claim/Collect/Reward
        claim_btn = await js_click(
            r"claim|collect|daily|check[- ]?in|reward|bonus|harvest|al|topla|\u00f6d\u00fcl|g\u00fcnl\u00fck"
        )
        if claim_btn:
            lines.append(f"Claim butonu: {claim_btn}")
        else:
            lines.append("Claim/Daily/Collect butonu bulunamadı.")

        await page.wait_for_timeout(3000)
        await shot(f"{bot} - işlem sonrası ekran")

        body_after = ""
        try:
            body_after = await page.inner_text("body")
        except Exception:
            pass
        balance_after = parse_balance_from_text(body_after)

        if balance_before is not None and balance_after is not None:
            if balance_after > balance_before:
                lines.append(f"Bakiye arttı: {balance_before} -> {balance_after}")
            elif balance_after == balance_before:
                lines.append("Bakiye değişmedi.")
            else:
                lines.append(f"Bakiye azaldı: {balance_before} -> {balance_after}")
        else:
            lines.append("Bakiye ekran üzerinden doğrulanamadı.")

        if api_calls:
            uniq = list(dict.fromkeys(api_calls))[:6]
            lines.append("Yakalanan API çağrıları: " + " | ".join(u[:80] for u in uniq))
        else:
            lines.append("Claim/daily API çağrısı yakalanmadı.")

        popup = classify_popup_text(body_after[:500])
        lines.append(f"Son ekran sınıfı: {popup}")

    except Exception as e:
        lines.append(f"Tarayıcı otomasyonu hatası: {type(e).__name__} {e}")
    finally:
        try:
            await context.close()
        except Exception:
            pass

    return lines


async def universal_miniapp(bot: str):
    if bot in MINIAPP_BUSY:
        await send_admin(f"{bot} icin mini uygulama otomasyonu zaten calisiyor.")
        return
    MINIAPP_BUSY.add(bot)
    try:
        ent = await resolve_entity(bot)
        if not getattr(ent, "bot", False):
            await send_admin(f"{bot} bir bot değil; mini uygulama otomasyonu başlatmadım.")
            return

        await send_admin(
            f"UNIVERSAL MINIAPP başladı: {bot}\n"
            "1) Mini uygulama açılıyor\n"
            "2) Claim/daily yolları taranıyor\n"
            "3) Tarayıcı ile Open -> Earn/Tasks -> Claim akisi deneniyor\n"
            "Cüzdan, ödeme, swap, stake ve tehlikeli işlemler otomatik yapılmayacak."
        )

        async with APP_LOCK:
            url, how, pub = await get_webview_url(ent, bot)

        if not url:
            await send_admin(
                f"{bot} mini uygulaması açılamadı.\n{how}\n"
                "Bot menüsünde 'Oyna / Play / Start' varsa önce onu elle aç; "
                "sonra tekrar miniapp yaz."
            )
            return

        ctx = await app_context(url)

        lines = [
            f"UNIVERSAL MINIAPP: {bot}",
            f"Mini uygulama: {how}",
        ]

        if not ctx.get("ok"):
            lines += [
                "Uygulamaya otomatik giriş yapılamadı.",
                "API taraması atlandı, tarayıcı deneniyor.",
            ]
        else:
            before = await universal_read_balance(ctx)
            if before:
                first_path = next(iter(before))
                lines.append(f"Claim öncesi bakiye alanı: {first_path}")
            else:
                lines.append("Claim öncesi bakiye alanı okunamadı.")

            cands = claim_candidates(ctx)
            if not cands:
                deep, scanned, all_paths = await deep_scan_claims(ctx, url)
                lines.append(f"Derin JS taraması: {scanned} dosya okundu, {len(deep)} claim adayı bulundu.")
                if deep:
                    cands = deep
                elif all_paths:
                    lines.append("Bulunan API yolları: " + ", ".join(all_paths[:10]))

            if cands:
                lines.append(f"Güvenli claim adayı: {len(cands)} yol bulundu.")
                claim_lines, done = await claim_auto_run(bot, ctx, cands, True)
                if claim_lines:
                    lines += claim_lines
            else:
                lines.append("Kodda doğrudan güvenli claim/collect/daily yolu bulunamadı.")

            after = await universal_read_balance(ctx)
            diffs = balance_diff(before, after)
            if diffs:
                pretty = ", ".join(f"{k}: +{v}" for k, v in list(diffs.items())[:5])
                lines.append(f"Claim sonrası bakiye değişimi doğrulandı: {pretty}")
            elif before or after:
                lines.append(
                    "Claim sonrası bakiye değişimi doğrulanamadı; "
                    "kasa sıfırlanmış olabilir ama toplam bakiye artışı kanıtlanamadı."
                )
            else:
                lines.append("Bakiye alanları hiç okunamadı; claim sonucu doğrulanamadı.")

        blines = await browser_auto(bot, url)
        lines += blines

        lines.append("Görev listesi taraması arka planda başladı; bitince özet gelecek.")
        await send_admin("\n".join(lines))

        spawn(run_autotasks(bot, [], 0, quiet=False))

    except Exception as e:
        await send_admin(f"{bot} universal miniapp hatası: {type(e).__name__} {e}")
    finally:
        MINIAPP_BUSY.discard(bot)


def spawn_universal_miniapp(bot: str):
    spawn(universal_miniapp(bot))


@admin_only
async def cmd_miniapp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if not args:
        await update.effective_message.reply_text(
            "Kullanım: miniapp botadi\n"
            "Örnek: miniapp atomicappbot\n"
            "Sistem mini uygulamayı açar, güvenli claim/daily yollarını dener, "
            "gerekirse tarayıcı ile buton tıklaması yapar."
        )
        return

    name = parse_bot_arg(args[0])
    if not name:
        await update.effective_message.reply_text(
            "Geçerli bot adı yaz. Örnek: miniapp atomicappbot"
        )
        return

    if name in MINIAPP_BUSY:
        await update.effective_message.reply_text(
            f"{name} için otomasyon zaten çalışıyor. Bitmesini bekle."
        )
        return

    await update.effective_message.reply_text(
        f"{name} için genel mini uygulama otomasyonu başlatıldı.\n"
        "Güvenli olmayan işlemler otomatik yapılmayacak."
    )
    spawn_universal_miniapp(name)


async def miniapp_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.effective_message.text or "").strip()
    parts = text.split()
    context.args = parts[1:]
    await cmd_miniapp(update, context)


async def main():
    global tg_client, http_session, bot_app, TG_LOCK, INSPECT_LOCK, APP_LOCK

    if not API_ID or not API_HASH or not STRING_SESSION:
        raise SystemExit("API_ID / API_HASH / STRING_SESSION zorunlu")
    if not BOT_TOKEN:
        raise SystemExit("BOT_TOKEN zorunlu (Airdrop radar bot)")
    if not ADMIN_USER_ID:
        raise SystemExit("ADMIN_USER_ID / ADMIN_CHAT_ID zorunlu")

    TG_LOCK = asyncio.Lock()
    APP_LOCK = asyncio.Lock()
    INSPECT_LOCK = asyncio.Lock()

    print("=" * 60)
    print("AIRDROP RADARI v3 + GROQ")
    print("=" * 60)
    print("[KONFIG] ADMIN =", ADMIN_USER_ID)
    print("[KONFIG] PORT =", PORT)
    print("[KONFIG] GROQ =", GROQ_MODEL if GROQ_API_KEY else "yok")
    print("[KONFIG] GEMINI =", GEMINI_MODEL if GEMINI_API_KEY else "yok")
    print("[KONFIG] MOD =", "sadece bot linkleri" if ONLY_BOTS else "genis filtre")
    print("[KONFIG] INSPECT =", INSPECT, "| RUTIN =", ROUTINES_ON)

    http_session = aiohttp.ClientSession()
    await start_http()

    tg_client = TelegramClient(StringSession(STRING_SESSION), API_ID, API_HASH)
    await tg_client.start()
    me = await tg_client.get_me()
    print("[TELETHON]", me.id, getattr(me, "username", None))
    await tg_client.get_dialogs()

    await load_seen()
    await load_routines()
    await load_joins()
    await load_autopilot()
    await load_admins()
    await load_refs()
    await load_claims()

    seed = []
    seed.extend(parse_id_list(SOURCE_CHATS_EXTRA))
    seed.extend(await load_persisted_sources())

    for item in seed:
        try:
            entity = await resolve_entity(item)
            cid = get_peer_id(entity)
            ACTIVE_SOURCES.add(cid)
            SOURCE_META[cid] = (
                getattr(entity, "title", None) or getattr(entity, "username", None) or str(cid)
            )
            print("[KAYNAK OK]", item, "->", cid, SOURCE_META[cid])
        except Exception as e:
            try:
                ACTIVE_SOURCES.add(int(item))
                print("[KAYNAK ID]", item)
            except Exception:
                print("[KAYNAK HATA]", item, repr(e))

    await persist_sources()
    tg_client.add_event_handler(on_group_message, events.NewMessage(incoming=True))

    bot_app = Application.builder().token(BOT_TOKEN).build()
    bot_app.add_handler(CommandHandler("start", cmd_start))
    bot_app.add_handler(CommandHandler("help", cmd_help))
    bot_app.add_handler(CommandHandler("yardim", cmd_help))
    bot_app.add_handler(CommandHandler("add", cmd_add))
    bot_app.add_handler(CommandHandler("del", cmd_del))
    bot_app.add_handler(CommandHandler("remove", cmd_del))
    bot_app.add_handler(CommandHandler("list", cmd_list))
    bot_app.add_handler(CommandHandler("bil", cmd_bil))
    bot_app.add_handler(CommandHandler("incele", cmd_incele))
    bot_app.add_handler(CommandHandler("oyun", cmd_oyun))
    bot_app.add_handler(CommandHandler("ref", cmd_ref))
    bot_app.add_handler(CommandHandler("topla", cmd_topla))
    bot_app.add_handler(CommandHandler("miniapp", cmd_miniapp))
    bot_app.add_handler(CommandHandler("gorev", cmd_gorev))
    bot_app.add_handler(CommandHandler("dur", cmd_dur))
    bot_app.add_handler(CommandHandler("otopilot", cmd_otopilot))
    bot_app.add_handler(CommandHandler("cik", cmd_cik))
    bot_app.add_handler(CommandHandler("yetkiler", cmd_yetkiler))
    bot_app.add_handler(CommandHandler("rutin", cmd_rutin))
    bot_app.add_handler(CommandHandler("status", cmd_status))
    bot_app.add_handler(CallbackQueryHandler(on_callback))
    bot_app.add_handler(MessageHandler(filters.TEXT & filters.Regex(r"^\s*miniapp\b"), miniapp_text))
    bot_app.add_handler(MessageHandler((filters.TEXT | filters.CAPTION) & ~filters.COMMAND, on_text))

    await bot_app.initialize()
    await bot_app.start()
    await bot_app.updater.start_polling(drop_pending_updates=True)

    spawn(keepalive_loop())
    spawn(routine_loop())
    spawn(autopilot_loop())
    spawn(claims_loop())

    try:
        await bot_app.bot.send_message(
            ADMIN_CHAT_ID,
            f"Radar aktif (v3 + Groq)\nDinlenen: {len(ACTIVE_SOURCES)}\n"
            f"Groq: {'acik' if GROQ_API_KEY else 'kapali'}\n"
            f"Otomatik inceleme: {'acik' if INSPECT else 'kapali'}\n"
            f"Rutin: {len(ROUTINES)}\n\n"
            f"/add -100... ile grup ekle, /incele botadi ile dene",
        )
    except Exception as e:
        print("[ADMIN MSG HATA]", repr(e))

    print("[HAZIR] Bot komutlari + Telethon + HTTP")
    await tg_client.run_until_disconnected()


try:
    _n_lines = sum(1 for _ in open(__file__, encoding="utf-8"))
except Exception:
    _n_lines = -1
print(f"[BOOT] dosya sonuna kadar okundu ({_n_lines} satir)", flush=True)


if __name__ == "__main__":
    print("[BOOT] main() baslatiliyor", flush=True)
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
    print("[BOOT] main() bitti (program kapaniyor)", flush=True)
