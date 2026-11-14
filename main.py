"""
Airdrop / oyun bot radari (v3 + V8.33 evrensel mini app motoru + V9 GROQ SİHİRBAZI)

V9 Sihirbaz (yeni):
  - Groq akıllandı: model zinciri (kapalı/limitli model atlanır), JSON modu, 429 bekleme, Gemini yedek.
  - Mini app ekran yazılarını okur, cümleleri anlar; kural motoru bitince yapay zeka kalan güvenli
    görevleri yapar (tıkla / gizli kodu yaz / kaydır / geri). Cüzdan-ödeme-davet adımları kodla engelli.
  - Referans linkini ağ cevaplarından, sayfadan, Kopyala butonundan (pano yakalanır), Davet ekranından
    ve bot sohbetinden bulur, kaydeder.
  - Her mini app için Türkçe ÖZET + altında REFERANS LİNKİ gönderir; yapamadıklarını nedeniyle yazar.
  - Komutlar: sihirbaz · özet botadi · özetler · referanslar · ref botadi link · sor <soru>

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

    # 4) menu tusu — DÜZELTME: menü butonunun kendi adresi Telegram'dan okunup veriliyor
    menu_url = ""
    try:
        from telethon.tl.functions.users import GetFullUserRequest
        full = await tg_client(GetFullUserRequest(ent))
        mb = getattr(getattr(full.full_user, "bot_info", None), "menu_button", None)
        menu_url = getattr(mb, "url", "") or ""
    except Exception as e:
        notes.append(f"bot bilgisi: {friendly_err(e)}")
    try:
        kw = {"url": menu_url} if menu_url else {}
        res = await tg_client(M.RequestWebViewRequest(peer=ent, bot=ent, platform="android", from_bot_menu=True, **kw))
        return res.url, "menü tuşundan açıldı", pub_urls
    except Exception as e:
        notes.append(f"menü tuşu: {friendly_err(e)}")
    has_main = bool(getattr(ent, "bot_has_main_app", False))
    if not menu_url and not has_main and not wv_urls and not shorts:
        notes.insert(0, "BU BOT MİNİ UYGULAMA DEĞİL (menü butonu yok, ana uygulama yok, mesajda mini uygulama butonu yok — sadece sohbet botu)")

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
            lines += ["", "Uygulamada Davet sayfasındaki Kopyala ile linki alıp şunu yazarsan kaydederim:",
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
                if b.lower().lstrip("@") not in (V8_AP.get("blocked") or []):
                    spawn(inspect_bot(b))
        # Oto-ekle açıksa: yeni bulunan botu evrensel motorla dene, açılırsa otopilot listesine ekle
        if bots and not warn and V8_AP.get("auto_add"):
            for b in bots:
                if not UNI_BOT_NAME_RISK.search(b) and b.lower().lstrip("@") not in (V8_AP.get("blocked") or []):
                    spawn(auto_link(b))
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


# ===== V8: MyAgeApp — güvenli claim + kontrollü otopilot =====
V8_TASKS={}
V8_LOCK=None
V8_AP_KEY = os.getenv("V8_AP_KEY", "radar:v8_ap:v1").strip()
V8_AP_FILE = os.getenv("V8_AP_FILE", "/tmp/radar_v8_ap.json")
# on: otopilot açık mı | min_m/max_m: tur aralığı (dk) | istatistikler
V8_AP = {
    "on": False,
    # Tüm botlar tek otopilot listesinde; turda sırayla gezilir
    "bots": ["myageapp", "pickaxeempirebot"],
    "bot": "myageapp",  # geriye uyum: son çalışılan
    "min_m": 45,
    "max_m": 75,
    "last": 0.0,
    "n_ok": 0,
    "n_skip": 0,
    "n_err": 0,
    "last_vault": None,
    "last_bal": None,
    "last_note": "",
    "cursor": 0,  # listedeki sıradaki bot
    # V8.33: yeniden başlatmada kaybolmasın
    "auto_add": False,
    "per": {},
    "pxe_fb_t": 0,
    "blocked": [],     # 'otopilot sil' ile çıkarılan / sohbeti silinen botlar — bir daha açılmaz
    "report": "kisa",  # kisa | detay
}


def v8_canonical(text):
    return re.sub(r"[^a-z0-9]","",(text or "").lower())


def v8_known_announcement(text):
    # User-transcribed notice only. No generic OK/continue acceptance.
    text=v8_canonical(text)
    return bool(re.fullmatch(r"agetokenislive(?:agetokenislive)?listing23novembercheckofficialchannelcompletenewtaskok",text))


async def v8_public(url):
    import socket,ipaddress
    p=urlparse(url)
    if p.scheme!="https" or not p.hostname or p.username or p.password:
        return False
    try:
        if p.port not in (None,443):
            return False
        rows=await asyncio.wait_for(asyncio.get_running_loop().getaddrinfo(p.hostname,443,type=socket.SOCK_STREAM),5)
        return bool(rows) and all(ipaddress.ip_address(row[4][0]).is_global for row in rows)
    except Exception:
        return False


async def persist_v8_ap():
    await save_json(V8_AP_KEY, V8_AP_FILE, V8_AP)


async def load_v8_ap():
    data = await load_json(V8_AP_KEY, V8_AP_FILE)
    if isinstance(data, dict):
        V8_AP.update({k: data[k] for k in V8_AP if k in data})
    print("[V8 OTOPILOT]", "acik" if V8_AP.get("on") else "kapali",
          f"aralik={V8_AP.get('min_m')}-{V8_AP.get('max_m')}dk",
          f"ok={V8_AP.get('n_ok')} skip={V8_AP.get('n_skip')} err={V8_AP.get('n_err')}")


def v8_ap_bots() -> list:
    bots = V8_AP.get("bots")
    blocked = set(V8_AP.get("blocked") or [])
    if isinstance(bots, list):
        return [str(b).lower().lstrip("@") for b in bots if str(b).strip() and str(b).lower().lstrip("@") not in blocked]
    b = (V8_AP.get("bot") or "myageapp").lower().lstrip("@")
    return [b] if b and b not in blocked else []


def v8_ap_status_text() -> str:
    on = "AÇIK" if V8_AP.get("on") else "KAPALI"
    last = V8_AP.get("last") or 0
    ago = ""
    if last:
        m = int((time.time() - last) / 60)
        ago = f" | son tur: {m} dk önce"
    bl = v8_ap_bots()
    bots_s = ", ".join("@" + x for x in bl) if bl else "(liste boş)"
    return (
        f"V8 Otopilot: {on}\n"
        f"Botlar: {bots_s}\n"
        f"Son bot: @{V8_AP.get('bot', '-')}\n"
        f"Aralık: {V8_AP.get('min_m')}-{V8_AP.get('max_m')} dk (rastgele)\n"
        f"Başarılı: {V8_AP.get('n_ok', 0)} | Atlanan: {V8_AP.get('n_skip', 0)} | Hata: {V8_AP.get('n_err', 0)}"
        f"{ago}\n"
        f"Son kasa: {V8_AP.get('last_vault')} | Son bakiye: {V8_AP.get('last_bal')}\n"
        f"Son not: {V8_AP.get('last_note', '')[:120]}\n\n"
        f"otopilot aç / kapat\n"
        f"otopilot ekle botadi  |  otopilot sil botadi\n"
        f"Tek sefer: @botadi"
    )


async def v8_report(name,text):
    await bot_app.bot.send_message(ADMIN_USER_ID,f"@{name} — V8 SONUC\n{text}",disable_web_page_preview=True)


async def v810_screen(page):
    try:
        return await page.locator('body').inner_text(timeout=3000)
    except Exception:
        return ''

def _v821_clean_lines(text):
    if not text:
        return []
    return [ln.strip() for ln in text.splitlines() if ln.strip()]


def _v821_first_pure_number(lines, start, window=5):
    """Etiketten sonraki window satırda yalnızca saf sayı olan ilk satırı döndür."""
    for j in range(start, min(start + window, len(lines))):
        s = lines[j].replace(",", "").replace(" ", "")
        if re.fullmatch(r"\d+(?:\.\d+)?", s):
            try:
                return float(s)
            except ValueError:
                pass
    return None


def v821_find_balance(text):
    """
    Balance değerini güvenli oku.
    - 'Balance' tam satır eşleşmesi aranır.
    - Altındaki ilk saf sayı alınır.
    - Aynı etiketten birden fazla aday veya sayı yoksa None döner (başarı ilan edilmez).
    """
    lines = _v821_clean_lines(text)
    candidates = []
    for i, line in enumerate(lines):
        if line.lower() == "balance":
            val = _v821_first_pure_number(lines, i + 1, window=4)
            if val is not None:
                candidates.append(val)
    if len(candidates) == 1:
        return candidates[0]
    return None


def v821_find_vault(text):
    """
    Vault (kasa) miktarını güvenli oku.
    - 'Vault' tam satır eşleşmesi aranır.
    - '21 AGE an hour...' gibi metinli satırlar atlanır, ilk saf sayı alınır.
    - Birden fazla aday veya sayı yoksa None.
    """
    lines = _v821_clean_lines(text)
    candidates = []
    for i, line in enumerate(lines):
        if line.lower() == "vault":
            val = _v821_first_pure_number(lines, i + 1, window=5)
            if val is not None:
                candidates.append(val)
    if len(candidates) == 1:
        return candidates[0]
    return None


def v821_diagnose(text, label=""):
    """Sadece teşhis. Tıklama yapmaz. Belirsiz durumda değeri reddeder."""
    notes = []
    if label:
        notes.append(f"[{label}]")
    lines = _v821_clean_lines(text)
    bal = v821_find_balance(text)
    vault = v821_find_vault(text)

    bal_hits = [i for i, ln in enumerate(lines) if ln.lower() == "balance"]
    if not bal_hits:
        notes.append("Balance etiketi hiç bulunamadı.")
    elif len(bal_hits) > 1:
        notes.append(f"Balance etiketi {len(bal_hits)} kez göründü → belirsiz, değer alınmadı.")
        for idx in bal_hits[:3]:
            notes.append("  çevresi: " + " | ".join(lines[idx:idx+4]))
    elif bal is None:
        notes.append("Balance bulundu ama altında saf sayı yok.")
        idx = bal_hits[0]
        notes.append("  çevresi: " + " | ".join(lines[idx:idx+5]))
    else:
        notes.append(f"Balance net okundu: {bal:g}")

    vault_hits = [i for i, ln in enumerate(lines) if ln.lower() == "vault"]
    if not vault_hits:
        notes.append("Vault etiketi hiç bulunamadı.")
    elif len(vault_hits) > 1:
        notes.append(f"Vault etiketi {len(vault_hits)} kez göründü → belirsiz, değer alınmadı.")
        for idx in vault_hits[:3]:
            notes.append("  çevresi: " + " | ".join(lines[idx:idx+5]))
    elif vault is None:
        notes.append("Vault bulundu ama altında saf sayı yok.")
        idx = vault_hits[0]
        notes.append("  çevresi: " + " | ".join(lines[idx:idx+6]))
    else:
        notes.append(f"Vault (kasa) net okundu: {vault:g}")

    return notes


def v821_verify(before, after):
    """
    Claim öncesi/sonrası karşılaştırma (sadece okuma).
    Başarı yalnızca her iki değer de net okunursa ve
    kasa sıfırlanıp bakiye artarsa ilan edilir.
    """
    notes = ["V8.21-safe: Balance/Vault güvenli okuma (çoklu aday veya belirsizse reddedilir)."]
    notes.extend(v821_diagnose(before, "ÖNCE"))
    notes.extend(v821_diagnose(after, "SONRA"))

    b = v821_find_balance(before)
    a = v821_find_balance(after)
    vb = v821_find_vault(before)
    va = v821_find_vault(after)

    if None in (b, a, vb, va):
        notes.append("Değerlerden en az biri belirsiz → toplandı kabul edilmedi.")
        return notes

    notes.append(f"Bakiye: {b:g} → {a:g}")
    notes.append(f"Kasa:   {vb:g} → {va:g}")

    if va == 0 and a > b:
        notes.append("Kasa sıfırlandı ve bakiye arttı → toplama doğrulandı.")
    else:
        notes.append("Beklenen kasa=0 + bakiye artışı birlikte görülmedi → toplandı kabul edilmedi.")

    return notes

async def v816_find_claim(page):
    # Claim, Vault kutusunun sagindaki ayri ogge. Metin bazli arar; rastgele secmez.
    labels=["claim","claim now","collect","get","start","open"]
    candidates=[]
    for label in labels:
        loc=page.get_by_text(label,exact=True)
        try:
            n=await loc.count()
        except Exception:
            continue
        for i in range(n):
            el=loc.nth(i)
            try:
                if await el.is_visible() and await el.is_enabled():
                    candidates.append((label,el))
            except Exception:
                pass
    # Tek aday varsa onu dondurur; yoksa None.
    if len(candidates)==1:
        return candidates[0]
    return None


async def v8_find_safe_claim(page):
    """Tek, görünür, tehlikesiz Claim/Collect benzeri buton ara. Birden fazlaysa None."""
    labels = [
        r"^\s*claim\s*$",
        r"^\s*claim now\s*$",
        r"^\s*collect\s*$",
        r"^\s*harvest\s*$",
        r"^\s*get reward\s*$",
        r"^\s*claim reward\s*$",
        r"^\s*topla\s*$",
        r"^\s*ödül al\s*$",
        r"^\s*odul al\s*$",
    ]
    risk = re.compile(
        r"wallet|connect|deposit|withdraw|buy|purchase|payment|fee|cost|price|stake|swap|"
        r"premium|stars|usdt|\bton\b|cuzdan|cüzdan|odeme|ödeme|satın|satin|ucret|ücret|[$€₺]",
        re.I,
    )
    candidates = []
    for pat in labels:
        loc = page.get_by_role("button", name=re.compile(pat, re.I))
        try:
            n = await loc.count()
        except Exception:
            continue
        for i in range(n):
            el = loc.nth(i)
            try:
                if not await el.is_visible() or not await el.is_enabled():
                    continue
                nearby = await el.evaluate(
                    "e => (e.parentElement?.innerText || e.innerText).slice(0,1000)",
                    timeout=3000,
                )
                if risk.search(nearby or ""):
                    continue
                candidates.append(el)
            except Exception:
                pass
    if len(candidates) == 1:
        return candidates[0]
    return None



def v8_pxe_parse_holding(text: str):
    """Üst bardaki HOLDING / coin miktarı (örn. 189)."""
    if not text:
        return None
    # "HOLDING 189" veya satırda tek başına büyük sayı + yakında PXE
    m = re.search(r"HOLDING\s*(\d+(?:[.,]\d+)?)", text, re.I)
    if m:
        try:
            return float(m.group(1).replace(",", ""))
        except ValueError:
            pass
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    for i, ln in enumerate(lines):
        if re.fullmatch(r"\d{2,6}", ln.replace(",", "")):
            # üst bar: avatar adı sonrası coin
            window = " ".join(lines[max(0, i - 2): i + 3]).lower()
            if "holding" in window or "pxe" in window or "jimin" in window:
                try:
                    return float(ln.replace(",", ""))
                except ValueError:
                    pass
    return None


def v8_pxe_parse_mined(text: str):
    """Mine edilen miktar (0.0141 gibi). CLAIM'E HAZIR yakını."""
    if not text:
        return None
    m = re.search(r"(?:MINE ED[Iİ]LD[Iİ]|CLAIM['’]?E HAZIR)[^\d]{0,40}(\d+(?:[.,]\d+)?)", text, re.I)
    if m:
        try:
            return float(m.group(1).replace(",", "."))
        except ValueError:
            pass
    m = re.search(r"\b0\.\d{3,6}\b", text)
    if m:
        try:
            return float(m.group(0))
        except ValueError:
            pass
    return None


def v8_pxe_risk_label(s: str) -> bool:
    return bool(re.search(
        r"wallet|connect|deposit|withdraw|buy\b|purchase|payment|subscribe\s*\$|on-chain|"
        r"keepeye|cuzdan|cüzdan|odeme|ödeme|sat[iı]n|ucret|ücret|\$pxe\s*on",
        s or "", re.I,
    ))


async def v8_pxe_click_nav(page, label: str) -> bool:
    """Alt menü: Upgrade / Earn / Arkadaşlar / Profile / kazma."""
    for role in ("button", "tab", "link"):
        loc = page.get_by_role(role, name=re.compile(rf"^\s*{re.escape(label)}\s*$", re.I))
        try:
            if await loc.count() >= 1 and await loc.first.is_visible():
                await loc.first.click(timeout=8000, no_wait_after=True)
                await page.wait_for_timeout(2000)
                return True
        except Exception:
            pass
    # metin ile dene
    loc = page.get_by_text(re.compile(rf"^\s*{re.escape(label)}\s*$", re.I))
    try:
        if await loc.count() >= 1 and await loc.first.is_visible():
            await loc.first.click(timeout=8000, no_wait_after=True)
            await page.wait_for_timeout(2000)
            return True
    except Exception:
        pass
    return False


async def v8_pxe_click_claim_mine(page, notes, state) -> bool:
    """Ana maden ekranındaki büyük Claim butonu."""
    state["stage"] = "pxe_mine_claim"
    claim = page.get_by_role("button", name=re.compile(r"^\s*Claim\s*$", re.I))
    try:
        n = await claim.count()
    except Exception:
        n = 0
    if n != 1:
        # bazen sadece text
        claim = page.get_by_text(re.compile(r"^\s*Claim\s*$", re.I))
        try:
            n = await claim.count()
        except Exception:
            n = 0
        if n != 1:
            notes.append("Maden Claim butonu tek net aday olarak bulunamadı.")
            return False
    el = claim.first if hasattr(claim, "first") else claim
    try:
        if not await el.is_visible() or not await el.is_enabled():
            notes.append("Maden Claim görünür/etkin değil.")
            return False
        nearby = await el.evaluate(
            "e => (e.parentElement?.innerText || e.innerText).slice(0,800)", timeout=3000)
        if v8_pxe_risk_label(nearby):
            notes.append("Claim çevresinde riskli ifade; basılmadı.")
            return False
        before = await v810_screen(page)
        mined = v8_pxe_parse_mined(before)
        hold_b = v8_pxe_parse_holding(before)
        if mined is not None and mined <= 0:
            notes.append(f"Mine edilen miktar {mined:g}; claim atlandı.")
            return False
        await el.scroll_into_view_if_needed(timeout=5000)
        await el.click(trial=True, timeout=10000)
        await el.click(timeout=10000, no_wait_after=True)
        await page.wait_for_timeout(3000)
        after = await v810_screen(page)
        hold_a = v8_pxe_parse_holding(after)
        notes.append("Maden Claim bir kez tıklandı.")
        if hold_b is not None and hold_a is not None:
            notes.append(f"HOLDING: {hold_b:g} → {hold_a:g}")
            if hold_a > hold_b:
                notes.append("HOLDING arttı → maden toplama doğrulandı.")
            else:
                notes.append("HOLDING artışı görülmedi; yine de tıklama yapıldı.")
        elif mined is not None:
            notes.append(f"Claim öncesi mine: {mined:g}")
        return True
    except Exception as e:
        notes.append(f"Maden Claim tıklanamadı: {type(e).__name__}")
        return False


async def v8_pxe_click_daily_topla(page, notes, state) -> bool:
    """Earn > Günlük Ödül > Topla +N"""
    state["stage"] = "pxe_daily_topla"
    # Önce Earn sekmesine geç
    if not await v8_pxe_click_nav(page, "Earn"):
        notes.append("Earn sekmesine geçilemedi; günlük ödül atlandı.")
        return False
    await page.wait_for_timeout(1500)
    # Topla +11 / Topla +N
    loc = page.get_by_role("button", name=re.compile(r"^\s*Topla\s*\+?\s*\d*\s*$", re.I))
    try:
        n = await loc.count()
    except Exception:
        n = 0
    if n == 0:
        loc = page.get_by_text(re.compile(r"^\s*Topla\s*\+\s*\d+\s*$", re.I))
        try:
            n = await loc.count()
        except Exception:
            n = 0
    if n != 1:
        notes.append("Günlük 'Topla +N' tek aday olarak yok (zaten alınmış veya kapalı).")
        return False
    el = loc.first
    try:
        if not await el.is_visible() or not await el.is_enabled():
            notes.append("Topla butonu görünür/etkin değil.")
            return False
        # Buton metni Topla ise güvenli say; üst kart metnine bakma (yanlış pozitif oluyordu)
        try:
            btn_txt = (await el.inner_text(timeout=2000) or "").strip()
        except Exception:
            btn_txt = ""
        if not re.search(r"topla", btn_txt, re.I):
            notes.append(f"Topla beklenirken farklı metin: {btn_txt[:40]!r}; basılmadı.")
            return False
        before = await v810_screen(page)
        hold_b = v8_pxe_parse_holding(before)
        await el.click(trial=True, timeout=10000)
        await el.click(timeout=10000, no_wait_after=True)
        await page.wait_for_timeout(3000)
        after = await v810_screen(page)
        hold_a = v8_pxe_parse_holding(after)
        notes.append("Günlük ödül Topla bir kez tıklandı.")
        if hold_b is not None and hold_a is not None:
            notes.append(f"HOLDING (günlük): {hold_b:g} → {hold_a:g}")
            if hold_a > hold_b:
                notes.append("Günlük ödül doğrulandı (HOLDING arttı).")
        return True
    except Exception as e:
        notes.append(f"Topla tıklanamadı: {type(e).__name__}")
        return False


async def v8_pxe_scan_tasks(page, notes, state):
    """Earn ekranındaki görevleri oku; tehlikelilere basma, güvenli olanları listele."""
    state["stage"] = "pxe_task_scan"
    text = await v810_screen(page)
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    safe, risky, share = [], [], []
    for ln in lines:
        low = ln.lower()
        if v8_pxe_risk_label(ln):
            risky.append(ln)
        elif any(k in low for k in ("paylaş", "story", "share", "verify")):
            share.append(ln)
        elif any(k in low for k in ("katıl", "katil", "duyuru", "sohbet", "kanal", "vote", "react", "reklam", "izle")):
            safe.append(ln)
    if safe:
        notes.append("Güvenli/topluluk görev adayları: " + " · ".join(safe[:10])[:400])
    if share:
        notes.append("Paylaşım/Verify (manuel, basılmaz): " + " · ".join(share[:6])[:300])
    if risky:
        uniq = list(dict.fromkeys(risky))[:6]
        notes.append("Atlandı (cüzdan/ödeme/satın): " + " · ".join(uniq)[:300])


async def v8_pxe_extract_join_targets(text: str) -> list:
    """Ekran/metinden t.me kanal-grup hedeflerini çıkar (bot hariç)."""
    found = []
    for m in CH_RE.finditer(text or ""):
        tgt = m.group(1)
        low = tgt.lower()
        if low.endswith("bot") or low in ("share", "proxy", "socks", "addstickers"):
            continue
        found.append(tgt)
    # düz @kanal
    for m in re.finditer(r"@([A-Za-z][A-Za-z0-9_]{3,})", text or ""):
        n = m.group(1)
        if not n.lower().endswith("bot"):
            found.append(n)
    # tekilleştir, sırayı koru
    out = []
    seen = set()
    for x in found:
        k = x.lower()
        if k not in seen:
            seen.add(k)
            out.append(x)
    return out[:8]


async def v8_pxe_do_joins(targets: list, notes) -> int:
    """Telethon ile güvenli kanallara katıl. Birden fazla hedef destekler."""
    if not targets:
        return 0
    if not tg_client:
        notes.append("Telethon yok; kanallara katılınamadı.")
        return 0
    ok_n = 0
    # tarayıcı kilidi dışında; kısa TG kilidi al
    got = await try_lock(TG_LOCK, 25)
    if not got:
        notes.append("Telegram sırası dolu; katılım sonraya bırakıldı.")
        return 0
    try:
        for tgt in targets:
            if v8_pxe_risk_label(tgt):
                notes.append(f"Atlandı (riskli hedef): {tgt}")
                continue
            try:
                msg = await do_join(tgt)
                notes.append(f"Katılım @{tgt if not tgt.startswith('+') else tgt}: {msg}")
                if "Katıldım" in msg or "zaten" in msg.lower():
                    ok_n += 1
            except Exception as e:
                notes.append(f"Katılım hata {tgt}: {type(e).__name__}")
            await asyncio.sleep(random.uniform(2, 5))
    finally:
        TG_LOCK.release()
    return ok_n


async def v8_pxe_run_community_tasks(page, notes, state, max_tasks: int = 8):
    """
    Earn'deki mavi/topluluk görevleri:
      - Duyuru kanalı / miner sohbeti gibi KATIL satırlarına bas
      - Çıkan t.me hedeflerine Telethon ile katıl
      - Story/Verify/Buy/Payment/cüzdan'a basma
      - Birden fazla görev sırayla (max_tasks)
    """
    state["stage"] = "pxe_community"
    # Earn'de olduğumuzdan emin ol
    await v8_pxe_click_nav(page, "Earn")
    await page.wait_for_timeout(1200)

    # Güvenli görev metin kalıpları (birden fazla dil/varyasyon)
    SAFE_PATTERNS = [
        r"DUYURU\s*KANAL",
        r"M[İI]NER\s*SOHBET",
        r"KANALINA\s*KATIL",
        r"SOHBET[İI]NE\s*KATIL",
        r"JOIN\s*(ANNOUNCE|CHANNEL|CHAT|GROUP)",
        r"ANNOUNCEMENT",
        r"COMMUNITY\s*CHAT",
    ]
    # Asla basılmayacak
    BLOCK_PATTERNS = [
        r"STORY", r"PAYLA[ŞS]", r"VERIFY", r"BUY\s*\$", r"PAYMENT",
        r"ON[- ]?CHAIN", r"KEEPEYE", r"SUBSCRIBE\s*\$", r"WALLET",
        r"REKLAM", r"İZLE", r"IZLE", r"VOTE", r"REACT",
    ]

    clicked_labels = []
    all_targets = []

    # Sayfadaki tüm tıklanabilir metin adaylarını tara
    candidates = []
    for pat in SAFE_PATTERNS:
        loc = page.get_by_text(re.compile(pat, re.I))
        try:
            n = await loc.count()
        except Exception:
            continue
        for i in range(min(n, 6)):
            el = loc.nth(i)
            try:
                if not await el.is_visible():
                    continue
                label = (await el.inner_text(timeout=2000) or "").strip()
                if not label:
                    continue
                low = label.lower()
                if any(re.search(b, label, re.I) for b in BLOCK_PATTERNS):
                    continue
                if v8_pxe_risk_label(label):
                    continue
                candidates.append((label[:80], el))
            except Exception:
                pass

    # Aynı etiketi tekilleştir
    uniq = []
    seen_l = set()
    for label, el in candidates:
        k = re.sub(r"\s+", " ", label.lower())
        if k in seen_l:
            continue
        seen_l.add(k)
        uniq.append((label, el))

    notes.append(f"Topluluk katılım adayı: {len(uniq)} (en fazla {max_tasks} denenecek).")

    for label, el in uniq[:max_tasks]:
        state["stage"] = "pxe_community_click"
        try:
            # satırın kendisi veya parent tıklanabilir olabilir
            await el.scroll_into_view_if_needed(timeout=4000)
            await el.click(timeout=8000, no_wait_after=True)
            clicked_labels.append(label)
            notes.append(f"Görev satırına tıklandı: {label[:60]}")
            await page.wait_for_timeout(2500)
            # Açılan metinden / sayfadan link topla
            txt = await v810_screen(page)
            try:
                _d = await page.evaluate("() => window.__uni ? window.__uni.drain() : {links: []}") or {}
                for _l in _d.get("links") or []:
                    txt += "\n" + str(_l.get("url", ""))
            except Exception:
                pass
            targets = await v8_pxe_extract_join_targets(txt)
            # link butonları
            for a in await page.locator("a[href*='t.me']").all():
                try:
                    href = await a.get_attribute("href")
                    if href:
                        targets.extend(await v8_pxe_extract_join_targets(href))
                except Exception:
                    pass
            # tekilleştir
            t2 = []
            s2 = set()
            for t in targets:
                if t.lower() not in s2:
                    s2.add(t.lower())
                    t2.append(t)
            if t2:
                notes.append("Bulunan katılım hedefleri: " + ", ".join(t2)[:200])
                all_targets.extend(t2)
            else:
                notes.append("Bu satırdan t.me hedefi çıkmadı (mini app içi yönlendirme olabilir).")
            # geri dönmeyi dene
            for back in ("Geri", "Back", "Kapat", "Close", "Earn"):
                if await v8_pxe_click_nav(page, back):
                    break
            await page.wait_for_timeout(800)
            await v8_pxe_click_nav(page, "Earn")
        except Exception as e:
            notes.append(f"Görev tık hatası ({label[:30]}): {type(e).__name__}")

    # Toplanan kanallara katıl
    all_targets = list(dict.fromkeys(all_targets))
    if all_targets:
        n = await v8_pxe_do_joins(all_targets, notes)
        notes.append(f"Katılım özeti: {n}/{len(all_targets)} başarılı/zaten üye.")
    elif clicked_labels:
        notes.append(
            "Satırlara tıklandı ama açık t.me linki yok; bilinen Pickaxe kanallarına yedek katılım deneniyor."
        )
        # Mini app çoğu zaman Telegram'a yönlendirir; yaygın duyuru/sohbet adları
        fallbacks = ["PickaxeEmpire", "PickaxeEmpireChat"]
        if time.time() - float(V8_AP.get("pxe_fb_t") or 0) < 7 * 86400:
            notes.append("Yedek kanallara bu hafta zaten katılındı; tekrar denenmedi.")
        else:
            n = await v8_pxe_do_joins(fallbacks, notes)
            V8_AP["pxe_fb_t"] = time.time()
            notes.append(f"Yedek katılım: {n}/{len(fallbacks)}.")
    else:
        notes.append("Tıklanacak güvenli katılım satırı bulunamadı (hepsi tamamlanmış veya farklı metin).")

    if clicked_labels:
        notes.append("Tıklanan görevler: " + " · ".join(clicked_labels)[:300])


async def v8_pickaxe_flow(page, name, notes, state):
    """
    Pickaxe Empire profili:
      1) Maden Claim (CLAIM'E HAZIR)
      2) Earn > Günlük Topla +N
      3) Topluluk katılım görevleri (birden fazla; duyuru/sohbet)
      4) Görev taraması / rapor (BUY/PAYMENT/ON-CHAIN/Story basılmaz)
    """
    notes.append("Pickaxe Empire profili devrede.")
    state["stage"] = "pxe_dialog"
    dialogs = page.locator('[role="dialog"], [aria-modal="true"], dialog[open]')
    for i in range(min(await dialogs.count(), 8)):
        if await dialogs.nth(i).is_visible():
            notes.append("Açık diyalog var; Pickaxe profili bilinmeyene basmaz. Claim denenmedi.")
            return notes

    await v8_pxe_click_claim_mine(page, notes, state)
    await v8_pxe_click_daily_topla(page, notes, state)

    try:
        await v8_pxe_run_community_tasks(page, notes, state, max_tasks=8)
    except Exception as e:
        notes.append(f"Topluluk görevleri: {type(e).__name__}")

    try:
        await v8_pxe_scan_tasks(page, notes, state)
    except Exception as e:
        notes.append(f"Görev taraması: {type(e).__name__}")

    notes.append("Pickaxe: cüzdan, BUY $PXE, payment channel, on-chain, story/Verify, reklam izle basılmaz.")
    notes.append("Birden fazla güvenli katılım görevi sırayla denendi. İkinci claim tıklaması yok.")
    return notes



async def v8_myage_nav(page, label: str) -> bool:
    for role in ("button", "tab", "link"):
        loc = page.get_by_role(role, name=re.compile(rf"^\s*{re.escape(label)}\s*$", re.I))
        try:
            if await loc.count() >= 1 and await loc.first.is_visible():
                await loc.first.click(timeout=8000, no_wait_after=True)
                await page.wait_for_timeout(1500)
                return True
        except Exception:
            pass
    loc = page.get_by_text(re.compile(rf"^\s*{re.escape(label)}\s*$", re.I))
    try:
        if await loc.count() >= 1 and await loc.first.is_visible():
            await loc.first.click(timeout=8000, no_wait_after=True)
            await page.wait_for_timeout(1500)
            return True
    except Exception:
        pass
    return False


async def v8_myage_click_spin(page, notes, state) -> bool:
    """Home'daki mavi Spin (2h30m). Watch/Locked'a basmaz."""
    state["stage"] = "myage_spin"
    # Home'a dön
    await v8_myage_nav(page, "Home")
    await page.wait_for_timeout(800)
    spin = page.get_by_role("button", name=re.compile(r"^\s*Spin\s*$", re.I))
    try:
        n = await spin.count()
    except Exception:
        n = 0
    if n == 0:
        spin = page.get_by_text(re.compile(r"^\s*Spin\s*$", re.I))
        try:
            n = await spin.count()
        except Exception:
            n = 0
    if n != 1:
        notes.append("Spin: tek net buton yok (cooldown veya farklı ekran).")
        return False
    el = spin.first
    try:
        if not await el.is_visible() or not await el.is_enabled():
            notes.append("Spin görünür/etkin değil.")
            return False
        nearby = await el.evaluate(
            "e => (e.parentElement?.innerText || e.innerText).slice(0,600)", timeout=3000)
        if re.search(r"watch|locked|wallet|deposit|premium", nearby or "", re.I):
            notes.append("Spin çevresi riskli/kilitli; basılmadı.")
            return False
        before = await v810_screen(page)
        bal_b = v821_find_balance(before)
        await el.click(trial=True, timeout=8000)
        await el.click(timeout=8000, no_wait_after=True)
        await page.wait_for_timeout(3500)
        after = await v810_screen(page)
        bal_a = v821_find_balance(after)
        notes.append("Spin bir kez tıklandı.")
        if bal_b is not None and bal_a is not None:
            notes.append(f"Spin sonrası bakiye: {bal_b:g} → {bal_a:g}")
        return True
    except Exception as e:
        notes.append(f"Spin tıklanamadı: {type(e).__name__}")
        return False


async def v8_myage_claim_achievements(page, notes, state, max_n: int = 5) -> int:
    """
    Achievements ekranındaki mavi Claim butonları (Hoarder vb.).
    Watch / Register gambling / Locked basılmaz.
    """
    state["stage"] = "myage_achievements"
    # Achievements satırına veya TOP üzerinden dene
    opened = False
    for label in ("Achievements", "Achievement"):
        loc = page.get_by_text(re.compile(rf"^\s*{label}\s*$", re.I))
        try:
            if await loc.count() >= 1 and await loc.first.is_visible():
                await loc.first.click(timeout=8000, no_wait_after=True)
                await page.wait_for_timeout(2000)
                opened = True
                break
        except Exception:
            pass
    if not opened:
        # COMPETE bölümünde olabilir; kaydır + tekrar
        try:
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await page.wait_for_timeout(800)
            loc = page.get_by_text(re.compile(r"Achievements", re.I))
            if await loc.count() >= 1:
                await loc.first.click(timeout=8000, no_wait_after=True)
                await page.wait_for_timeout(2000)
                opened = True
        except Exception:
            pass
    if not opened:
        notes.append("Achievements ekranı açılamadı; başarı claim atlandı.")
        return 0

    done = 0
    # Sayfadaki Claim butonları (vault claim değil, başarı claim)
    claim_btns = page.get_by_role("button", name=re.compile(r"^\s*Claim\s*$", re.I))
    try:
        n = await claim_btns.count()
    except Exception:
        n = 0
    notes.append(f"Achievements Claim adayı: {n}")
    for i in range(min(n, max_n)):
        el = claim_btns.nth(i)
        try:
            if not await el.is_visible() or not await el.is_enabled():
                continue
            nearby = await el.evaluate(
                "e => (e.parentElement?.parentElement?.innerText || e.parentElement?.innerText || e.innerText).slice(0,900)",
                timeout=3000,
            )
            low = (nearby or "").lower()
            if re.search(r"wallet|deposit|withdraw|premium|watch|register\s+jetton|register\s+tonplay|locked", low):
                notes.append("Başarı Claim atlandı (riskli/partner bağlamı).")
                continue
            # Hoarder / Keeper / vault times gibi metinler güvenli
            await el.scroll_into_view_if_needed(timeout=4000)
            await el.click(trial=True, timeout=8000)
            await el.click(timeout=8000, no_wait_after=True)
            await page.wait_for_timeout(2500)
            done += 1
            notes.append(f"Başarı Claim tıklandı ({done}): {(nearby or '')[:60].replace(chr(10), ' ')}")
        except Exception as e:
            notes.append(f"Başarı Claim hata: {type(e).__name__}")
    if done == 0:
        notes.append("Tıklanabilir başarı Claim yok (hepsi alınmış veya kilitli).")
    return done


async def v8_myage_click_checks(page, notes, state, max_n: int = 3) -> int:
    """Home'daki Check butonları (tag / link in bio). Bas, sonucu not et."""
    state["stage"] = "myage_check"
    await v8_myage_nav(page, "Home")
    await page.wait_for_timeout(600)
    checks = page.get_by_role("button", name=re.compile(r"^\s*Check\s*$", re.I))
    try:
        n = await checks.count()
    except Exception:
        n = 0
    done = 0
    for i in range(min(n, max_n)):
        el = checks.nth(i)
        try:
            if not await el.is_visible() or not await el.is_enabled():
                continue
            nearby = await el.evaluate(
                "e => (e.parentElement?.innerText || e.innerText).slice(0,500)", timeout=3000)
            if re.search(r"wallet|deposit|watch|premium", nearby or "", re.I):
                continue
            await el.click(timeout=8000, no_wait_after=True)
            await page.wait_for_timeout(2000)
            done += 1
            notes.append(f"Check tıklandı: {(nearby or '')[:50].replace(chr(10), ' ')}")
        except Exception:
            pass
    if done == 0 and n == 0:
        notes.append("Check butonu yok.")
    return done


async def v8_myage_extra_tasks(page, notes, state):
    """
    MyAgeApp ek görevler (vault claim sonrası):
      - Spin (varsa, 1 kez)
      - Check butonları
      - Achievements Claim (Hoarder vb., birden fazla)
    Watch / Locked / gambling Register basılmaz.
    """
    notes.append("MyAgeApp ek görevler başlıyor (Spin / Check / Achievements Claim).")
    try:
        await v8_myage_click_spin(page, notes, state)
    except Exception as e:
        notes.append(f"Spin aşaması: {type(e).__name__}")
    try:
        await v8_myage_click_checks(page, notes, state)
    except Exception as e:
        notes.append(f"Check aşaması: {type(e).__name__}")
    try:
        await v8_myage_claim_achievements(page, notes, state, max_n=6)
    except Exception as e:
        notes.append(f"Achievements aşaması: {type(e).__name__}")
    notes.append(
        "Atlandı: Epic Watch (reklam), Locked Mystery, Register Jetton/Tonplay, "
        "Like&share manuel, cüzdan/ödeme."
    )
    return notes


async def v8_generic_miniap_flow(page, name, notes, state):
    """MyAgeApp dışı mini uygulamalar: bilinmeyen duyuruya basma, tek güvenli claim dene, raporla."""
    state["stage"] = "genel_dialog_kontrol"
    dialogs = page.locator('[role="dialog"], [aria-modal="true"], dialog[open]')
    for i in range(min(await dialogs.count(), 10)):
        if await dialogs.nth(i).is_visible():
            notes.append("Bilinmeyen pencere açık; genel modda otomatik kapatılmadı, claim denenmedi.")
            return notes

    state["stage"] = "genel_claim_bulma"
    claim = await v8_find_safe_claim(page)
    if claim is None:
        notes.append("Tek bir güvenli Claim/Collect butonu bulunamadı; rastgele seçim yapılmadı.")
        # teşhis için kısa ekran özeti
        try:
            t = await v810_screen(page)
            snippet = " | ".join([ln.strip() for ln in t.splitlines() if ln.strip()][:12])
            if snippet:
                notes.append("Ekran özeti: " + snippet[:500])
        except Exception:
            pass
        return notes

    state["stage"] = "genel_claim_hazirlik"
    try:
        await claim.scroll_into_view_if_needed(timeout=5000)
        await claim.click(trial=True, timeout=12000)
    except Exception:
        notes.append("Claim adayı tıklanabilir değil; zorlanmadı.")
        return notes

    before_text = await v810_screen(page)
    # MyAgeApp etiketleri varsa bonus olarak oku (zorunlu değil)
    pre_bal = v821_find_balance(before_text)
    pre_vault = v821_find_vault(before_text)
    if pre_vault is not None and pre_vault <= 0:
        notes.append(f"Kasa/Vault zaten {pre_vault:g}; claim atlandı.")
        return notes

    state["stage"] = "genel_claim_tiklama"
    try:
        await claim.click(timeout=10000, no_wait_after=True)
    except Exception:
        notes.append("Claim tıklaması tamamlanamadı; tekrar denenmedi.")
        return notes
    await page.wait_for_timeout(3000)
    notes.append("Genel mod: güvenli Claim/Collect bir kez tıklandı; ikinci tıklama yok.")
    after_text = await v810_screen(page)

    # Bilinen etiketler varsa doğrula; yoksa sadece metin farkı raporla
    if v821_find_balance(before_text) is not None or v821_find_vault(before_text) is not None:
        notes.extend(v821_verify(before_text, after_text))
    else:
        notes.append("Bu uygulamada Balance/Vault etiketi yok; otomatik başarı ilan edilmedi.")
        b_lines = [ln.strip() for ln in before_text.splitlines() if ln.strip()][:8]
        a_lines = [ln.strip() for ln in after_text.splitlines() if ln.strip()][:8]
        notes.append("ÖNCE: " + " | ".join(b_lines)[:400])
        notes.append("SONRA: " + " | ".join(a_lines)[:400])
    notes.append("Cüzdan/ödeme pencerelerine basılmaz. Genel mini app modu.")
    return notes


async def v8_myage_page_flow(page, name, notes, state):
    """MyAgeApp: bilinen duyuru OK + Claim + Balance/Vault dogrulama + ek gorevler."""
    from playwright.async_api import TimeoutError as PWTimeout
    state["stage"]="duyuru_tanima"
    dialogs=page.locator('[role="dialog"], [aria-modal="true"], dialog[open]')
    closed=False
    for i in range(min(await dialogs.count(),10)):
        dialog=dialogs.nth(i)
        if not await dialog.is_visible():
            continue
        text=await dialog.inner_text(timeout=5000)
        if not v8_known_announcement(text):
            continue
        ok=dialog.get_by_role("button",name=re.compile(r"^\s*OK\s*$",re.I))
        if await ok.count()!=1:
            return notes+["Taninmis duyuruda tek bir erisilebilir OK dugmesi bulunamadi; basilmadi."]
        state["stage"]="duyuru_ok"
        await ok.click(trial=True,timeout=10000)
        # Recheck exact notice immediately before dismissal.
        if not v8_known_announcement(await dialog.inner_text(timeout=3000)):
            return notes+["Duyuru metni degisti; OK basilmadi."]
        await ok.click(timeout=10000,no_wait_after=True)
        try:
            await dialog.wait_for(state="hidden",timeout=10000)
        except PWTimeout:
            return notes+["OK tiklamasi tamamlandi ancak pencerenin kapandigi dogrulanamadi; claim denenmedi."]
        closed=True
        notes.append("Yazdigin $AGE duyurusu tanindi. Kendi OK dugmesi tiklandi ve pencere kapandi.")
        break
    if not closed:
        visible=False
        for i in range(min(await dialogs.count(),10)):
            if await dialogs.nth(i).is_visible():
                visible=True
                break
        if visible:
            return notes+["Farkli veya metni birebir eslesmeyen pencere var; onaylanmadi, claim denenmedi."]
        notes.append("Gorunur duyuru penceresi yok; claim kontrolune geciliyor.")
    # Never act while another modal remains visible.
    for i in range(min(await dialogs.count(),10)):
        if await dialogs.nth(i).is_visible():
            return notes+["Baska bir pencere hala acik; claim denenmedi."]
    state["stage"]="claim_bulma"
    claim=page.get_by_role("button",name=re.compile(r"^\s*claim\s*$",re.I))
    if await claim.count()!=1:
        notes.append("Tek bir claim dugmesi bulunamadi; rastgele secim yapilmadi.")
        return await v8_myage_extra_tasks(page, notes, state)
    if not await claim.is_visible() or not await claim.is_enabled():
        notes.append("Claim gorunur/etkin degil; tiklanmadi.")
        return await v8_myage_extra_tasks(page, notes, state)
    nearby=await claim.evaluate("e => (e.parentElement?.innerText || e.innerText).slice(0,1000)",timeout=3000)
    risk=re.compile(r"wallet|connect|deposit|withdraw|buy|purchase|payment|fee|cost|price|stake|swap|premium|stars|usdt|\bton\b|cuzdan|cüzdan|odeme|ödeme|satın|satin|ucret|ücret|[$€₺]",re.I)
    if risk.search(nearby):
        return notes+["Claim cevresinde ucret/cuzdan benzeri ifade var; tiklanmadi."]
    state["stage"]="claim_hazirlik"
    try:
        await claim.scroll_into_view_if_needed(timeout=5000)
        await claim.click(trial=True,timeout=12000)
    except PWTimeout:
        return notes+["Claim hala tiklanabilir degil; zorlanmadi."]
    if risk.search(await claim.evaluate("e => (e.parentElement?.innerText || e.innerText).slice(0,1000)",timeout=3000)):
        return notes+["Claim baglami degisti; tiklanmadi."]
    before_text=await v810_screen(page)
    pre_vault = v821_find_vault(before_text)
    pre_bal = v821_find_balance(before_text)
    if pre_vault is not None and pre_vault <= 0:
        notes.append(f"Kasa zaten {pre_vault:g}; claim atlandı (gereksiz tıklama yok).")
        if pre_bal is not None:
            notes.append(f"Bakiye: {pre_bal:g}")
        notes.append("Sonradan açılan onay/ödeme pencerelerine basılmaz.")
        return await v8_myage_extra_tasks(page, notes, state)
    state["stage"]="claim_tiklama"
    try:
        await claim.click(timeout=10000,no_wait_after=True)
    except PWTimeout:
        return notes+["Claim tiklamasi tamamlanamadi; tekrar denenmedi."]
    await page.wait_for_timeout(3000)
    notes.append("Claim tiklamasi tamamlandi; ikinci tiklama yapilmadi.")
    after_text=await v810_screen(page)
    notes.extend(v821_verify(before_text, after_text))
    notes.append("V8.21-safe: Balance/Vault çoklu aday veya belirsizse reddedilir; başarı yalnız net kasa=0 + bakiye artışı ile ilan edilir.")
    notes.append("Sonradan açılan onay/ödeme pencerelerine basılmaz.")
    return await v8_myage_extra_tasks(page, notes, state)


async def v8_run(name,short="",start=""):
    global V8_LOCK
    if V8_LOCK is None:
        V8_LOCK=asyncio.Lock()
    state={"stage":"sirada"}
    async def work():
        state["stage"]="telegram_hedefi"
        ent=await asyncio.wait_for(resolve_entity(name),30)
        if not getattr(ent,"bot",False):
            return ["Hedef bot degil."]
        state["stage"]="telegram_kilidi"
        if not await try_lock(TG_LOCK,30):
            return ["Telegram sirasi bosalmadi."]
        try:
            state["stage"]="start_gonderme"
            await asyncio.wait_for(tg_client.send_message(ent,f"/start {start}".strip()),30)
            await asyncio.sleep(INSPECT_WAIT)
        finally:
            TG_LOCK.release()
        state["stage"]="mini_uygulama_kilidi"
        if not await try_lock(APP_LOCK,30):
            return ["Mini uygulama sirasi bosalmadi."]
        try:
            state["stage"]="yetkili_adres_alma"
            url,how,public=await asyncio.wait_for(get_webview_url(ent,name,short,start),90)
        finally:
            APP_LOCK.release()
        if not url:
            return ["Yetkili acilis adresi alinamadi."]
        return await v8_browser(name,url,state)
    async with V8_LOCK:
        try:
            notes=await asyncio.wait_for(work(),V8_JOB_TIMEOUT)
            await v8_report(name,"\n".join(notes))
        except asyncio.CancelledError:
            raise
        except Exception as e:
            import traceback
            stack=" > ".join(f"{os.path.basename(f.filename)}:{f.lineno}:{f.name}" for f in traceback.extract_tb(e.__traceback__)[-6:])
            print(f"[V8] stage={state['stage']} type={type(e).__name__} stack={stack}",flush=True)
            await v8_report(name,f"Asama: {state['stage']}\nHata: {type(e).__name__}\nGizli bilgiler yazilmadi; odul basarisi dogrulanmadi.")


async def auto_link(name: str,short: str="",start: str=""):
    if name in V8_TASKS and not V8_TASKS[name].done():
        await v8_report(name,"Zaten sirada veya calisiyor.")
        return
    await v8_report(name,"V8 iş sıraya alındı. MyAgeApp: duyuru+claim+doğrulama. Evrensel mini app motoru. dur ile iptal.")
    V8_TASKS[name]=spawn(v8_run(name,short,start))


def _v8_notes_outcome(notes: list) -> str:
    text = "\n".join(notes)
    if "toplama doğrulandı" in text or "toplama dogrulandi" in text:
        return "ok"
    if "claim atlandı" in text or "claim atlandi" in text or "Kasa zaten" in text:
        return "skip"
    if "toplandı kabul edilmedi" in text or "toplandi kabul edilmedi" in text:
        return "skip"
    return "err"


async def v8_run_and_track(name="myageapp", short="", start=""):
    """Tek tur çalıştır, V8_AP istatistiğini güncelle."""
    global V8_LOCK
    if V8_LOCK is None:
        V8_LOCK = asyncio.Lock()
    state = {"stage": "sirada"}

    async def work():
        state["stage"] = "telegram_hedefi"
        ent = await asyncio.wait_for(resolve_entity(name), 30)
        if not getattr(ent, "bot", False):
            return ["Hedef bot değil."]
        state["stage"] = "telegram_kilidi"
        if not await try_lock(TG_LOCK, 30):
            return ["Telegram sırası boşalmadı."]
        try:
            state["stage"] = "start_gonderme"
            await asyncio.wait_for(tg_client.send_message(ent, f"/start {start}".strip()), 30)
            await asyncio.sleep(INSPECT_WAIT)
        finally:
            TG_LOCK.release()
        state["stage"] = "mini_uygulama_kilidi"
        if not await try_lock(APP_LOCK, 30):
            return ["Mini uygulama sırası boşalmadı."]
        try:
            state["stage"] = "yetkili_adres_alma"
            url, how, public = await asyncio.wait_for(get_webview_url(ent, name, short, start), 90)
        finally:
            APP_LOCK.release()
        if not url:
            return ["Yetkili açılış adresi alınamadı.", str(how or "")[:900]]
        return await v8_browser(name, url, state)

    try:
        async with V8_LOCK:
            notes = await asyncio.wait_for(work(), V8_JOB_TIMEOUT)
    except asyncio.CancelledError:
        raise
    except Exception as e:
        import traceback
        stack = " > ".join(
            f"{os.path.basename(f.filename)}:{f.lineno}:{f.name}"
            for f in traceback.extract_tb(e.__traceback__)[-6:]
        )
        print(f"[V8] stage={state['stage']} type={type(e).__name__} stack={stack}", flush=True)
        notes = [f"Aşama: {state['stage']}", f"Hata: {type(e).__name__}",
                 "Gizli bilgiler yazılmadı; ödül başarısı doğrulanmadı."]

    outcome = _v8_notes_outcome(notes)
    # son bakiye/kasa notlardan kabaca çekmeye çalış
    joined = "\n".join(notes)
    import re as _re
    m_bal = _re.search(r"Bakiye(?: net okundu)?:\s*([0-9.]+)\s*→\s*([0-9.]+)", joined)
    m_vault = _re.search(r"Kasa:\s*([0-9.]+)\s*→\s*([0-9.]+)", joined)
    if m_bal:
        V8_AP["last_bal"] = float(m_bal.group(2))
    else:
        m2 = _re.search(r"Balance net okundu:\s*([0-9.]+)", joined)
        if m2:
            V8_AP["last_bal"] = float(m2.group(1))
    if m_vault:
        V8_AP["last_vault"] = float(m_vault.group(2))
    else:
        m2 = _re.search(r"Vault \(kasa\) net okundu:\s*([0-9.]+)", joined)
        if m2:
            V8_AP["last_vault"] = float(m2.group(1))
        m3 = _re.search(r"Kasa zaten ([0-9.]+)", joined)
        if m3:
            V8_AP["last_vault"] = float(m3.group(1))

    V8_AP["last"] = time.time()
    V8_AP["last_note"] = notes[-1] if notes else ""
    if outcome == "ok":
        V8_AP["n_ok"] = int(V8_AP.get("n_ok") or 0) + 1
    elif outcome == "skip":
        V8_AP["n_skip"] = int(V8_AP.get("n_skip") or 0) + 1
    else:
        V8_AP["n_err"] = int(V8_AP.get("n_err") or 0) + 1
    await persist_v8_ap()
    V8_LAST[name] = {"t": time.time(), "outcome": outcome, "notes": list(notes)}
    if V8_AP.get("report") == "detay":
        await v8_report(name, "\n".join(notes))
    return outcome, notes


async def v8_autopilot_loop():
    """MyAgeApp kasa claim otopilotu. Sadece V8_AP['on'] iken tur atar."""
    print("[V8 OTOPILOT] döngü hazır (kapalı başlar; 'otopilot aç' ile devreye girer)", flush=True)
    while True:
        try:
            if not V8_AP.get("on"):
                await asyncio.sleep(20)
                continue
            # aralık kontrolü
            min_m = int(V8_AP.get("min_m") or 45)
            max_m = int(V8_AP.get("max_m") or 75)
            if max_m < min_m:
                max_m = min_m
            wait_s = random.randint(min_m * 60, max_m * 60)
            last = float(V8_AP.get("last") or 0)
            elapsed = time.time() - last
            if last > 0 and elapsed < wait_s:
                await asyncio.sleep(min(60, wait_s - elapsed))
                continue
            # çakışan tek seferlik iş varsa bekle
            busy = any(not t.done() for t in V8_TASKS.values())
            if busy:
                await asyncio.sleep(30)
                continue
            bots = v8_ap_bots()
            if not bots:
                # liste boşsa silinmiş botları geri ekleme; sadece bekle
                await asyncio.sleep(300)
                continue
            # Listedeki tüm botları bu turda sırayla çalıştır
            await bot_app.bot.send_message(
                ADMIN_USER_ID,
                f"🔁 Otopilot turu başladı: {len(bots)} bot. Bitince tek mesajla özet atacağım.\n(Durdurmak için: dur)",
                disable_web_page_preview=True,
            )
            round_lines = []
            dialog_names = await uni_dialog_usernames()
            for bot in bots:
                if not V8_AP.get("on"):
                    break
                if uni_paused(bot):
                    round_lines.append(f"⏸ @{bot} — üst üste hata verdiği için bekletiliyor")
                    continue
                # sohbeti Telegram'dan sildiysen: listeden çıkar, bir daha açma
                if dialog_names is not None and float(uni_per(bot).get("last") or 0) > 0 and bot not in dialog_names:
                    await uni_block_bot(bot)
                    round_lines.append(f"🗑 @{bot} — sohbeti silmişsin; listeden çıkarıldı, bir daha açılmayacak")
                    continue
                busy = any(not t.done() for t in V8_TASKS.values())
                if busy:
                    await asyncio.sleep(20)
                V8_AP["bot"] = bot
                key = f"ap:{bot}"
                task = asyncio.create_task(v8_run_and_track(bot))
                V8_TASKS[key] = task
                try:
                    outcome, notes = await task
                except asyncio.CancelledError:
                    notes = ["Tur iptal edildi."]
                    outcome = "err"
                    raise
                finally:
                    V8_TASKS.pop(key, None)
                uni_track(bot, outcome)
                await persist_v8_ap()
                round_lines.append(uni_short_line(bot, outcome, notes))
                await asyncio.sleep(random.uniform(8, 20))
            wait_s = random.randint(min_m * 60, max_m * 60)
            await uni_send_round_summary(round_lines, wait_s)
            # bekleme sırasında kapatılırsa çıksın
            end = time.time() + wait_s
            while time.time() < end:
                if not V8_AP.get("on"):
                    break
                await asyncio.sleep(15)
        except asyncio.CancelledError:
            print("[V8 OTOPILOT] iptal", flush=True)
            raise
        except Exception as e:
            print("[V8 OTOPILOT HATA]", repr(e), flush=True)
            V8_AP["n_err"] = int(V8_AP.get("n_err") or 0) + 1
            V8_AP["last_note"] = f"döngü hata: {type(e).__name__}"
            try:
                await persist_v8_ap()
            except Exception:
                pass
            await asyncio.sleep(120)


async def v8_stop():
    global AUTO_STOP
    AUTO_STOP = True
    was_on = bool(V8_AP.get("on"))
    V8_AP["on"] = False
    await persist_v8_ap()
    tasks = [t for t in V8_TASKS.values() if t is not None and not t.done()]
    for t in tasks:
        try:
            t.cancel()
        except Exception:
            pass
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
    msg = "V8 işleri durduruldu."
    if was_on:
        msg += " Otopilot kapatıldı."
    msg += " Gönderilmiş işlemler geri alınamaz."
    await bot_app.bot.send_message(ADMIN_USER_ID, msg)


async def v8_ap_set(on: bool):
    global AUTO_STOP
    if on:
        AUTO_STOP = False
    V8_AP["on"] = bool(on)
    if on and not V8_AP.get("last"):
        V8_AP["last"] = 0.0  # hemen ilk turu tetikleyebilsin
    await persist_v8_ap()
    await bot_app.bot.send_message(ADMIN_USER_ID, v8_ap_status_text(), disable_web_page_preview=True)


async def on_text(update: Update,context: ContextTypes.DEFAULT_TYPE):
    user,msg=update.effective_user,update.effective_message
    if not user or not msg:
        return
    if user.id!=ADMIN_USER_ID or update.effective_chat.type!="private":
        await msg.reply_text("V8 yalnızca bot sahibinin özel sohbetinde kullanılır.")
        return
    text=(msg.text or msg.caption or "").strip()
    low=text.lower()
    if low in {"dur","durdur","kapat"}:
        await v8_stop()
        return
    if low in {"otopilot", "otopilot durum", "otopilot status"}:
        await msg.reply_text(v8_ap_status_text())
        return
    if low in {"otopilot aç", "otopilot ac", "otopilot on", "otopilot baslat", "otopilot başlat"}:
        # Varsayılan listeyi garantile
        if not v8_ap_bots():
            await msg.reply_text("Otopilot listesi boş. Önce 'otopilot tara' yaz ya da 'otopilot ekle botadi' ile bot ekle.")
        await v8_ap_set(True)
        return
    if low in {"otopilot kapat", "otopilot off", "otopilot durdur"}:
        await v8_ap_set(False)
        return
    if low in {"otopilot tara", "otopilot hepsi", "otopilot tümü", "otopilot tumu", "otopilot all"}:
        await msg.reply_text("Hesabındaki botlar taranıyor (mini uygulaması olanlar listeye eklenecek)…")
        try:
            found = await uni_discover_bots()
        except Exception as e:
            await msg.reply_text(f"Tarama hatası: {type(e).__name__}")
            return
        bots = v8_ap_bots()
        blocked = set(V8_AP.get("blocked") or [])
        new = [b for b in found if b not in bots and b not in blocked]
        V8_AP["bots"] = bots + new
        await persist_v8_ap()
        await msg.reply_text(
            f"Bulunan mini app botu: {len(found)} | yeni eklenen: {len(new)}\n"
            + (", ".join("@" + b for b in new)[:3500] if new else "(yeni yok)")
        )
        if low != "otopilot tara":
            await v8_ap_set(True)
        return
    if low in {"otopilot otoekle aç", "otopilot otoekle ac", "otopilot otoekle on"}:
        V8_AP["auto_add"] = True
        await persist_v8_ap()
        await msg.reply_text("Oto-ekle AÇIK: radarın bulduğu ve açılabilen her yeni mini app otomatik çalıştırılıp listeye eklenecek.")
        return
    if low in {"otopilot otoekle kapat", "otopilot otoekle off"}:
        V8_AP["auto_add"] = False
        await persist_v8_ap()
        await msg.reply_text("Oto-ekle KAPALI.")
        return
    if low in {"otopilot temizle", "otopilot sifirla", "otopilot sıfırla"}:
        V8_AP["bots"] = []
        V8_AP["per"] = {}
        await persist_v8_ap()
        await msg.reply_text(v8_ap_status_text())
        return
    if low.startswith("otopilot ekle") or low.startswith("otopilot add"):
        parts = text.split()
        name = parts[-1].lstrip("@").lower() if len(parts) >= 3 else ""
        name = parse_bot_arg(name) or (name if re.fullmatch(r"[a-z0-9_]{4,32}", name) else "")
        if not name:
            await msg.reply_text("Kullanım: otopilot ekle botadi")
            return
        bots = v8_ap_bots()
        V8_AP["blocked"] = [b for b in (V8_AP.get("blocked") or []) if b != name]
        if name not in bots:
            bots.append(name)
            V8_AP["bots"] = bots
        await persist_v8_ap()
        await msg.reply_text(f"✅ @{name} otopilota eklendi. Listede {len(v8_ap_bots())} bot var.")
        return
    if low.startswith("otopilot sil") or low.startswith("otopilot del"):
        parts = text.split()
        name = parts[-1].lstrip("@").lower() if len(parts) >= 3 else ""
        if not name:
            await msg.reply_text("Kullanım: otopilot sil botadi")
            return
        await uni_block_bot(name)
        await msg.reply_text(f"🗑 @{name} listeden çıkarıldı ve engellendi. 'otopilot tara' bile onu tekrar eklemez.\nGeri eklemek için: otopilot ekle {name}")
        return
    if low in {"rapor kısa", "rapor kisa", "rapor ozet", "rapor özet"}:
        V8_AP["report"] = "kisa"
        await persist_v8_ap()
        await msg.reply_text("Rapor: KISA. Her tur sonunda tek bir özet mesajı gelecek.")
        return
    if low in {"rapor detay", "rapor uzun"}:
        V8_AP["report"] = "detay"
        await persist_v8_ap()
        await msg.reply_text("Rapor: DETAY. Her bot için teknik log da gelecek.")
        return
    if low.startswith("detay ") or low.startswith("son "):
        nm = low.split(None, 1)[1].strip().lstrip("@")
        rec = V8_LAST.get(nm)
        if not rec:
            await msg.reply_text(f"@{nm} için bu oturumda kayıt yok.")
        else:
            await msg.reply_text(f"@{nm} — son çalışmanın tam logu:\n" + "\n".join(rec["notes"])[:3900], disable_web_page_preview=True)
        return
    if low in {"komutlar", "yardım", "yardim", "help"}:
        await msg.reply_text(UNI_HELP_TEXT)
        return
    if low in {"engelliler", "otopilot engelli"}:
        bl = V8_AP.get("blocked") or []
        await msg.reply_text("Engellenen botlar: " + (", ".join("@" + b for b in bl) if bl else "yok"))
        return
    for e in list(msg.entities or [])+list(msg.caption_entities or []):
        if getattr(e,"url",None):
            text+=" "+e.url
    for name,short,start in parse_link_targets(text):
        await auto_link(name,short,start)


async def cmd_incele(update: Update,context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id==ADMIN_USER_ID and update.effective_chat.type=="private":
        for name,short,start in parse_link_targets(" ".join(context.args)):
            await auto_link(name,short,start)


async def cmd_dur(update: Update,context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id==ADMIN_USER_ID:
        await v8_stop()


@admin_only
async def cmd_start(update: Update,context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(
        "V8 Mini App\n\n"
        "• Tek sefer: @MyAgeApp veya başka bot adı / t.me linki gönder\n"
        "• MyAgeApp: duyuru OK + Claim + bakiye/kasa doğrulama\n"
        "• Diğer TÜM mini app'ler: evrensel motor (claim/daily/farm/spin, görev sekmeleri, kanal katılımı + Check, tapper)\n"
        "• otopilot tara → hesabındaki tüm mini app botlarını bul / otopilot hepsi → bul + başlat\n"
        "• otopilot otoekle aç → radarın bulduğu yeni mini app'leri otomatik ekle\n"
        "• Otopilot (tüm liste): otopilot aç / kapat / otopilot\n"
        "• Liste: otopilot ekle botadi  |  otopilot sil botadi\n"
        "• Durdur: dur\n\n"
        "Cüzdan, ödeme, deposit butonlarına basılmaz. "
        "Bilinmeyen pop-up otomatik onaylanmaz."
    )




# =====================================================================
# V8.28 — EVRENSEL MINI APP MOTORU (tüm Telegram mini uygulamaları)
# ---------------------------------------------------------------------
#  - Telegram WebApp köprüsü taklidi (TelegramWebviewProxy): mini app'in
#    gönderdiği olayları yakalar; t.me linkleri, popup, CloudStorage,
#    DeviceStorage, tema/viewport isteklerine Telegram gibi cevap verir.
#    Ödeme (invoice), telefon, emoji, hikaye paylaşımı → her zaman iptal.
#  - Ekrandaki tüm tıklanabilir öğeleri tarar, sınıflandırır:
#       ödül  : Claim / Collect / Daily / Check-in / Farm / Spin / Topla ...
#       görev : Start / Go / Join / Subscribe / Katıl ...
#       kontrol: Check / Verify / Kontrol et ...
#       kapat : Close / Skip / Got it / Tamam / × (sadece açık pencerede)
#    Risk (cüzdan/ödeme/satın alma/stars/TON...) içerenlere asla basmaz.
#  - Alt menüde Earn / Tasks / Görevler / Bonus gibi sekmeleri gezer.
#  - Görevlerin açtığı t.me kanal/gruplarına Telethon ile katılır,
#    ardından Check/Verify'a basar.
#  - Tapper oyunlarında ana coin'e sınırlı sayıda dokunur (UNI_TAPS).
#  - Her bot için tarayıcı depolaması saklanır (onboarding tekrar etmez).
#  - "otopilot tara": hesabındaki mini uygulamalı tüm botları bulup listeye ekler.
# =====================================================================

UNI_MAX_ACTIONS = int(os.getenv("UNI_MAX_ACTIONS", "80") or 80)      # bir turda en fazla tıklama
UNI_BUDGET_S = int(os.getenv("UNI_BUDGET_S", "300") or 300)          # bir bot için tarayıcı süresi (sn)
UNI_TABS = int(os.getenv("UNI_TABS", "8") or 8)                      # gezilecek en fazla sekme
UNI_TAPS = int(os.getenv("UNI_TAPS", "30") or 30)                    # tapper oyunlarında dokunma (0 = kapalı)
UNI_JOIN = os.getenv("UNI_JOIN", "1").strip() != "0"                 # görev kanallarına katıl
UNI_JOIN_MAX = int(os.getenv("UNI_JOIN_MAX", "12") or 12)              # bir turda en fazla katılım
UNI_ADS = os.getenv("UNI_ADS", "0").strip() == "1"                   # "reklam izle" görevleri
UNI_BOT_START = os.getenv("UNI_BOT_START", "0").strip() == "1"       # görevdeki başka botlara /start
UNI_FAIL_PAUSE = int(os.getenv("UNI_FAIL_PAUSE", "5") or 5)          # üst üste bu kadar hata → bot beklemeye
UNI_STATE_DIR = os.getenv("UNI_STATE_DIR", "/tmp/uni_state")
UNI_AFTER_PROFILE = os.getenv("UNI_AFTER_PROFILE", "1").strip() != "0"  # MyAge/Pickaxe sonrası evrensel görevler
V8_AP.setdefault("pxe_fb_t", 0)
V8_JOB_TIMEOUT = int(os.getenv("V8_JOB_TIMEOUT", "600") or 600)

V8_AP.setdefault("auto_add", False)   # radar yeni mini app bulunca listeye eklesin mi
V8_AP.setdefault("per", {})           # bot başına istatistik {bot: {ok,skip,err,fail,last}}

UNI_RISK_RE = re.compile(
    r"wallet|connect|deposit|withdraw|\bbuy\b|purchase|payment|\bpay\b|\bfee\b|price|\bstake|swap|"
    r"premium|\bstars?\b|⭐|usdt|\bton\b|tonconnect|transaction|invoice|sign transaction|mint nft|"
    r"\bbid\b|auction|subscribe for \$|"
    r"cuzdan|cüzdan|odeme|ödeme|sat[ıi]n al|ucret|ücret|yat[ıi]r|çek(im)?\b|"
    r"кошел|оплат|купить|вывод|депозит|[$€₺]",
    re.I,
)
UNI_SKIP_RE = re.compile(
    r"invite|refer|friend|story|stories|share|repost|retweet|boost (?:the |our |a )?channel|channel boost|boost us|t\.me/boost|emoji|nickname|"
    r"to (your )?name|rename|username|premium|davet|arkada[şs]|payla[şs]|hikaye|"
    r"пригласи|друз|сторис|поделит",
    re.I,
)
UNI_ADS_RE = re.compile(r"\bads?\b|advert|watch (an )?ad|reklam|реклам", re.I)
UNI_REWARD_RE = re.compile(
    r"^(?:claim(?: now| reward| all| daily| bonus| free)?|collect(?: all| reward)?|harvest|"
    r"get(?: reward| bonus| it| free)?|receive|take|redeem reward|"
    r"daily(?: reward| bonus| check[- ]?in| claim)?|check[- ]?in|sign[- ]?in today|"
    r"start farming|farm(?:ing)?|start mining|mine|open(?: box| chest| case)?|free spin|spin|roll|"
    r"topla|al|[öo]d[üu]l[üu]? al|g[üu]nl[üu]k [öo]d[üu]l|madencili[ğg]e ba[şs]la|"
    r"получить|забрать|собрать|клейм|фарм)"
    r"(?:\s*[+x×]?\s*[\d.,]+\s*[kKmMbB]?\b.*)?$",
    re.I,
)
UNI_GO_RE = re.compile(
    r"^(?:start|go|open|join|subscribe|follow|visit|do it|do|perform|complete|launch|play|read|"
    r"check out|ba[şs]la|git|a[çc]|kat[ıi]l|abone ol|takip et|ziyaret et|yap|tamamla|"
    r"перейти|подписаться|вступить|выполнить|начать|открыть)\s*[→>›»]?$",
    re.I,
)
UNI_CHECK_RE = re.compile(
    r"^(?:check|verify|validate|confirm|kontrol(?: et)?|do[ğg]rula|onayla|проверить|подтвердить)$",
    re.I,
)
UNI_DISMISS_RE = re.compile(
    r"^(?:close|skip|later|not now|maybe later|got it|ok|okay|continue|next|start|let'?s go|"
    r"understood|cool|nice|great|thanks|done|×|✕|✖|x|kapat|tamam|devam|ileri|ge[çc]|atla|anlad[ıi]m|"
    r"понятно|закрыть|далее|пропустить|ок)$",
    re.I,
)
UNI_SAFE_DISMISS_RE = re.compile(r"^(?:close|skip|later|not now|maybe later|×|✕|✖|x|kapat|ge[çc]|atla|закрыть|пропустить)$", re.I)
UNI_NAV_RE = re.compile(
    r"^(?:earn|earnings?|tasks?|quests?|missions?|bonus(?:es)?|rewards?|daily|daily tasks|airdrop|challenges?|"
    r"free|events?|activit(?:y|ies)|social|partners?|special|offers?|achievements?|"
    r"g[öo]rev(?:ler)?|kazan|[öo]d[üu]l(?:ler)?|bonus|задания|заработ\w*|награды|квесты)$",
    re.I,
)
UNI_TASK_VERB_RE = re.compile(
    r"\b(?:join|subscribe|follow|visit|watch|play|open|start|launch|check out|explore|try|read|"
    r"telegram|channel|chat|group|community|twitter|on x\b|x\.com|youtube|tiktok|instagram|discord|website|partner|"
    r"kat[ıi]l|abone|takip|ziyaret|izle|oyna|kanal|sohbet|grup|"
    r"подпиш|вступ|перейд|канал|чат|смотр)\w*",
    re.I,
)
UNI_SOCIAL_RE = re.compile(
    r"\b(?:join|subscribe|follow|telegram|channel|chat|group|community|twitter|youtube|tiktok|instagram|discord|"
    r"kat[ıi]l|abone|takip|kanal|sohbet|grup|подпиш|вступ|канал|чат)\w*",
    re.I,
)
UNI_MAIN_GO_RE = re.compile(r"^(?:start|ba[şs]la|начать)\b", re.I)
UNI_TIMER_RE = re.compile(r"\d+\s*[dhms]\b|\d+\s*/\s*\d+|\d+:\d+|[⏳⌛🏆⚔💪]")
UNI_AMOUNT_RE = re.compile(r"^\+?\s*[\d.,]+\s*[kKmMbB]?\s*[A-Za-z$]{0,8}\s*[→>›»]?$")
UNI_DONE_RE = re.compile(r"\b(?:done|completed?|claimed|finished|received|tamamland[ıi]|al[ıi]nd[ıi]|выполнено|получено)\b|✓|✔|✅", re.I)
UNI_JOIN_SKIP = {"share", "proxy", "socks", "addstickers", "addemoji", "addlist", "boost", "iv", "login",
                 "setlanguage", "addtheme", "confirmphone", "c", "s", "joinchat"}
UNI_BOT_NAME_RISK = re.compile(
    r"wallet|^pay|pay$|send$|^cryptobot$|exchange|bank|tonkeeper|tonhub|tonspace|fragment|"
    r"bybit|binance|okx|bitget|mexc|kucoin|gateio|htx|premium|stars|botfather|stickers|gif$|"
    r"^vote$|^like$|^bing$|^wiki$|^imdb$|^bold$|^vid$|^pic$|^youtube$|^music$",
    re.I,
)

UNI_SHIM_JS = r"""
(() => {
  if (window.__uni) return;
  const U = window.__uni = { events: [], links: [], blocked: [], seq: 0 };
  const RISK = /wallet|connect|deposit|withdraw|\bbuy\b|purchase|payment|\bpay\b|premium|stars?|usdt|\bton\b|transaction|cüzdan|ödeme|satın|оплат|купить|кошел/i;
  const store = (k) => 'uni_cs_' + k;
  function respond(t, d) {
    setTimeout(() => {
      try {
        const W = window.Telegram && window.Telegram.WebView;
        if (W && typeof W.receiveEvent === 'function') { W.receiveEvent(t, d); return; }
        if (window.TelegramGameProxy && typeof window.TelegramGameProxy.receiveEvent === 'function') { window.TelegramGameProxy.receiveEvent(t, d); return; }
        if (typeof window.TelegramGameProxy_receiveEvent === 'function') window.TelegramGameProxy_receiveEvent(t, d);
      } catch (e) {}
    }, 60);
  }
  function link(u, how) { try { U.links.push({ url: String(u), how: how, t: Date.now() }); } catch (e) {} }
  function handle(type, data) {
    let d = data;
    try { if (typeof d === 'string') d = JSON.parse(d || '{}'); } catch (e) { d = {}; }
    d = d || {};
    U.events.push({ type: type, t: Date.now() });
    switch (type) {
      case 'web_app_open_tg_link': link('https://t.me' + (d.path_full || ''), 'tg_link'); break;
      case 'web_app_open_link': link(d.url || '', 'open_link'); break;
      case 'web_app_open_invoice': U.blocked.push('invoice'); respond('invoice_closed', { slug: d.slug, status: 'cancelled' }); break;
      case 'web_app_request_phone': U.blocked.push('phone'); respond('phone_requested', { status: 'cancelled' }); break;
      case 'web_app_request_write_access': respond('write_access_requested', { status: 'allowed' }); break;
      case 'web_app_share_to_story': U.blocked.push('story'); break;
      case 'web_app_switch_inline_query': U.blocked.push('inline_share'); break;
      case 'web_app_send_prepared_message': U.blocked.push('prepared_msg'); respond('prepared_message_failed', { error: 'USER_DECLINED' }); break;
      case 'web_app_request_emoji_status_access': respond('emoji_status_access_requested', { status: 'cancelled' }); break;
      case 'web_app_set_emoji_status': U.blocked.push('emoji'); respond('emoji_status_failed', { error: 'USER_DECLINED' }); break;
      case 'web_app_open_scan_qr_popup': respond('scan_qr_popup_closed', {}); break;
      case 'web_app_read_text_from_clipboard': respond('clipboard_text_received', { req_id: d.req_id }); break;
      case 'web_app_request_viewport': respond('viewport_changed', { height: window.innerHeight, width: window.innerWidth, is_expanded: true, is_state_stable: true }); break;
      case 'web_app_request_theme': respond('theme_changed', { theme_params: { bg_color: '#ffffff', text_color: '#000000', hint_color: '#999999', link_color: '#2481cc', button_color: '#2481cc', button_text_color: '#ffffff', secondary_bg_color: '#f0f0f0' } }); break;
      case 'web_app_request_safe_area': respond('safe_area_changed', { top: 0, bottom: 0, left: 0, right: 0 }); break;
      case 'web_app_request_content_safe_area': respond('content_safe_area_changed', { top: 0, bottom: 0, left: 0, right: 0 }); break;
      case 'web_app_biometry_get_info': respond('biometry_info_received', { available: false }); break;
      case 'web_app_check_home_screen': respond('home_screen_checked', { status: 'unsupported' }); break;
      case 'web_app_check_location': respond('location_checked', { available: false }); break;
      case 'web_app_request_location': respond('location_requested', { available: false }); break;
      case 'web_app_request_fullscreen': respond('fullscreen_changed', { is_fullscreen: true }); break;
      case 'web_app_open_popup': {
        const btns = (d.buttons && d.buttons.length) ? d.buttons : [{ id: '', type: 'close' }];
        const msg = (d.title || '') + ' ' + (d.message || '');
        let pick = null;
        if (!RISK.test(msg)) pick = btns.find(b => (b.type === 'ok' || b.type === 'default') && !RISK.test(b.text || ''));
        if (!pick) pick = btns.find(b => b.type === 'cancel' || b.type === 'close');
        U.events.push({ type: 'popup:' + msg.slice(0, 120) + ' -> ' + (pick ? (pick.text || pick.type) : 'none'), t: Date.now() });
        respond('popup_closed', pick ? { button_id: pick.id } : {});
        break;
      }
      case 'web_app_invoke_custom_method': {
        const p = d.params || {}; let res = true;
        try {
          if (d.method === 'saveStorageValue') localStorage.setItem(store(p.key), p.value);
          else if (d.method === 'getStorageValues') { res = {}; (p.keys || []).forEach(k => { const v = localStorage.getItem(store(k)); res[k] = v === null ? '' : v; }); }
          else if (d.method === 'deleteStorageValues') (p.keys || []).forEach(k => localStorage.removeItem(store(k)));
          else if (d.method === 'getStorageKeys') { res = []; for (let i = 0; i < localStorage.length; i++) { const k = localStorage.key(i); if (k.startsWith('uni_cs_')) res.push(k.slice(7)); } }
          respond('custom_method_invoked', { req_id: d.req_id, result: res });
        } catch (e) { respond('custom_method_invoked', { req_id: d.req_id, error: String(e) }); }
        break;
      }
      case 'web_app_device_storage_save_key':
        try { if (d.value === null || d.value === undefined) localStorage.removeItem('uni_ds_' + d.key); else localStorage.setItem('uni_ds_' + d.key, d.value); } catch (e) {}
        respond('device_storage_key_saved', { req_id: d.req_id }); break;
      case 'web_app_device_storage_get_key': {
        let v = null; try { v = localStorage.getItem('uni_ds_' + d.key); } catch (e) {}
        respond('device_storage_key_received', { req_id: d.req_id, value: v }); break;
      }
      case 'web_app_device_storage_clear': respond('device_storage_cleared', { req_id: d.req_id }); break;
      case 'web_app_secure_storage_save_key':
      case 'web_app_secure_storage_get_key':
      case 'web_app_secure_storage_restore_key':
      case 'web_app_secure_storage_clear':
        respond('secure_storage_failed', { req_id: d.req_id, error: 'UNSUPPORTED' }); break;
      default: break;
    }
  }
  try {
    Object.defineProperty(window, 'TelegramWebviewProxy', {
      value: { postEvent: (t, d) => { try { handle(t, d); } catch (e) {} } },
      writable: false, configurable: false,
    });
  } catch (e) {}
  // yeni sekme / dış link açılmasını yakala, sayfadan çıkma
  const fakeWin = { closed: false, close() {}, focus() {}, blur() {}, postMessage() {}, location: { href: '' }, document: { write() {}, close() {} } };
  window.open = function (u) { link(u || '', 'window_open'); return fakeWin; };
  document.addEventListener('click', (ev) => {
    const a = ev.target && ev.target.closest && ev.target.closest('a[href]');
    if (!a) return;
    const href = a.href || '';
    let ext = false;
    try { ext = new URL(href, location.href).origin !== location.origin; } catch (e) {}
    if (ext || a.target === '_blank') { link(href, 'anchor'); ev.preventDefault(); }
  }, true);
  U.drain = () => { const out = { events: U.events.splice(0), links: U.links.splice(0), blocked: U.blocked.splice(0) }; return out; };

  // Ekrandaki tıklanabilir öğeleri bul
  U.scan = () => {
    const vw = window.innerWidth, vh = window.innerHeight;
    const sel = 'button, a[href], [role=button], [role=tab], [role=menuitem], [onclick], input[type=button], input[type=submit], label, li, div, span, img, svg';
    const all = Array.from(document.querySelectorAll(sel));
    const out = [];
    const seen = new Set();
    const isOverlay = (el) => {
      let n = el;
      for (let i = 0; n && i < 12; i++, n = n.parentElement) {
        if (n.matches && n.matches('[role=dialog],[aria-modal=true],dialog[open],[class*=modal i],[class*=popup i],[class*=sheet i],[class*=drawer i],[class*=overlay i]')) return true;
        const st = getComputedStyle(n);
        if (st.position === 'fixed') {
          const r = n.getBoundingClientRect();
          if (r.width * r.height > vw * vh * 0.35 && parseInt(st.zIndex || '0', 10) > 0) return true;
        }
      }
      return false;
    };
    for (const el of all) {
      if (out.length > 400) break;
      const tag = el.tagName.toLowerCase();
      const st = getComputedStyle(el);
      const natural = /^(button|a|input)$/.test(tag) || /button|tab|menuitem/.test(el.getAttribute('role') || '') || el.hasAttribute('onclick');
      if (!natural) {
        if (st.cursor !== 'pointer') continue;
        const p = el.parentElement;
        if (p && getComputedStyle(p).cursor === 'pointer' && (p.innerText || '').trim() === (el.innerText || '').trim()) continue;
      }
      if (st.visibility === 'hidden' || st.display === 'none' || parseFloat(st.opacity || '1') < 0.1) continue;
      if (el.disabled || el.getAttribute('aria-disabled') === 'true' || st.pointerEvents === 'none') continue;
      const r = el.getBoundingClientRect();
      if (r.width < 6 || r.height < 6) continue;
      if (r.bottom < -2000 || r.top > vh + 6000) continue;
      let text = (el.innerText || el.value || '').replace(/\s+/g, ' ').trim();
      const aria = (el.getAttribute('aria-label') || el.getAttribute('title') || el.getAttribute('alt') || '').trim();
      if (!text) text = aria;
      if (!text) {
        const cls = String(el.className && el.className.baseVal !== undefined ? el.className.baseVal : el.className || '');
        if (/close|dismiss/i.test(cls)) text = 'close';
        else if (r.width <= 90 && r.height <= 90) text = '[ikon]';   // ok / chevron / play simgesi
      }
      if (!text || text.length > 140) continue;
      // üstte başka öğe mi var?
      const inView = r.top >= 0 && r.bottom <= vh && r.left >= 0 && r.right <= vw;
      let covered = false;
      if (inView) {
        const cx = r.left + r.width / 2, cy = r.top + r.height / 2;
        const top = document.elementFromPoint(cx, cy);
        if (top && top !== el && !el.contains(top) && !top.contains(el)) covered = true;
      }
      if (covered) continue;
      // bağlam: üst öğenin metni, içindeki DİĞER butonların metni çıkarılarak (komşu "Connect Wallet" Claim'i riskli yapmasın)
      let ctx = '', n = el.parentElement;
      for (let i = 0; n && i < 5; i++, n = n.parentElement) {
        let t = (n.innerText || '');
        for (const o of n.querySelectorAll('button,a[href],[role=button],[onclick],input[type=button],input[type=submit]')) {
          if (o === el || o.contains(el) || el.contains(o)) continue;
          const ot = (o.innerText || o.value || '').trim();
          if (ot) t = t.split(ot).join(' ');
        }
        t = t.replace(/\s+/g, ' ').trim();
        if (t.length > text.length + 2) { ctx = t.slice(0, 300); if (t.length >= 10) break; }
      }
      // anahtar: sayılar normalize (sürekli artan sayaç aynı butonu 'yeni' göstermesin)
      const norm = (v) => v.replace(/\d+(?:[.,:]\d+)+|\d{3,}/g, '#');
      const key = norm(text) + '|' + norm(ctx).slice(0, 120);
      let rowEl = el, q = el.parentElement;
      for (let i = 0; q && i < 4; i++, q = q.parentElement) { if (getComputedStyle(q).cursor === 'pointer' && (q.innerText || '').length < 200) rowEl = q; else break; }
      const row = norm((rowEl.innerText || '').replace(/\s+/g, ' ').trim()).slice(0, 90);
      if (seen.has(key + Math.round(r.top))) continue;
      seen.add(key + Math.round(r.top));
      const id = 'u' + (++U.seq);
      el.setAttribute('data-uni', id);
      out.push({ id, text, ctx, key, row, tag, x: r.left, y: r.top, w: r.width, h: r.height,
        bottom: r.top > vh * 0.78, overlay: isOverlay(el), tab: (el.getAttribute('role') || '') === 'tab' || /\btab\b|chip|segment/i.test(String(el.className || '')) });
    }
    return out;
  };

  // Tapper coin adayı
  U.tapTarget = () => {
    const vw = window.innerWidth, vh = window.innerHeight;
    let best = null, bestA = 0;
    for (const el of document.querySelectorAll('img, div, button, canvas, svg')) {
      const sig = (String(el.className && el.className.baseVal !== undefined ? el.className.baseVal : el.className || '') + ' ' + (el.id || '') + ' ' + (el.getAttribute('alt') || '')).toLowerCase();
      if (!/coin|tap|clicker|click-?area|hamster|egg|planet|main-?button|tapper/.test(sig)) continue;
      const r = el.getBoundingClientRect();
      const a = r.width * r.height;
      if (a < 9000 || r.top < 0 || r.bottom > vh || r.width > vw * 1.05) continue;
      if (a > bestA) { bestA = a; best = r; }
    }
    return best ? { x: best.left + best.width / 2, y: best.top + best.height / 2, w: best.width, h: best.height } : null;
  };
  U.hasCanvas = () => { const vw = Math.min(window.innerWidth, screen.width || window.innerWidth), vh = Math.min(window.innerHeight, screen.height || window.innerHeight); return Array.from(document.querySelectorAll('canvas')).some(c => { const r = c.getBoundingClientRect(); return r.width * r.height > vw * vh * 0.4; }); };
})();
"""


def uni_state_path(name: str) -> str:
    safe = re.sub(r"[^a-z0-9_]", "", (name or "").lower()) or "x"
    return os.path.join(UNI_STATE_DIR, f"{safe}.json")


async def uni_new_context(browser, name: str):
    kw = dict(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True,
              user_agent=DESKTOP_UA, accept_downloads=False, locale="en-US")
    p = uni_state_path(name)
    if os.path.exists(p):
        try:
            return await browser.new_context(storage_state=p, **kw)
        except Exception:
            pass
    return await browser.new_context(**kw)


async def uni_save_state(context, name: str):
    try:
        os.makedirs(UNI_STATE_DIR, exist_ok=True)
        await asyncio.wait_for(context.storage_state(path=uni_state_path(name)), 10)
    except Exception:
        pass


def uni_tme_from_nav(url: str) -> bool:
    try:
        return (urlparse(url).hostname or "").lower() in ("t.me", "telegram.me", "www.t.me")
    except Exception:
        return False


def uni_join_targets(urls: list) -> tuple:
    """t.me linklerinden (kanal/grup hedefleri, bot adları) çıkarır."""
    chans, bots = [], []
    for u in urls:
        m = re.search(r"(?:t\.me|telegram\.me)/(\+[A-Za-z0-9_-]{6,}|joinchat/[A-Za-z0-9_-]{6,}|[A-Za-z][A-Za-z0-9_]{3,31})", u or "", re.I)
        if not m:
            continue
        tgt = m.group(1)
        low = tgt.lower()
        if low in UNI_JOIN_SKIP:
            continue
        if low.endswith("bot") or re.search(r"[?&]start(app)?=", u or "", re.I) and "/" in (urlparse(u).path.strip("/")):
            bots.append(tgt)
        else:
            chans.append(tgt)
    return list(dict.fromkeys(chans)), list(dict.fromkeys(bots))


def uni_numbers(text: str) -> list:
    """Ekrandaki sayıları etiketleriyle çıkarır: 'Balance\n100' → ('Balance#0', 100)."""
    num_re = re.compile(r"(?<![\w.])(\d{1,3}(?:[ ,]\d{3})+|\d+(?:\.\d+)?)\s*([kKmMbB])?(?![\w])")
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()][:80]
    out, prev, cnt = [], "", {}
    for ln in lines:
        rest = num_re.sub("#", ln)
        base = rest if re.search(r"[A-Za-zÀ-ɏЀ-ӿ]", rest) else (prev or "?")
        for m in num_re.finditer(ln):
            s = m.group(1).replace(",", "").replace(" ", "")
            try:
                v = float(s)
            except ValueError:
                continue
            v *= {"k": 1e3, "m": 1e6, "b": 1e9}.get((m.group(2) or "").lower(), 1)
            lab = base[:40]
            k = f"{lab}#{cnt.get(lab, 0)}"
            cnt[lab] = cnt.get(lab, 0) + 1
            out.append((k, v))
        if re.search(r"[A-Za-zÀ-ɏЀ-ӿ]", rest):
            prev = ln[:40]
    return out


def uni_diff(before: str, after: str) -> list:
    b, a = uni_numbers(before), uni_numbers(after)
    notes = []
    bl = {}
    for lab, v in b:
        bl.setdefault(lab, v)
    ups = []
    for lab, v in a:
        if lab in bl and v != bl[lab]:
            ups.append((lab, bl[lab], v))
    seen = set()
    for lab, x, y in ups:
        if lab in seen:
            continue
        seen.add(lab)
        notes.append(f"{(lab.split('#')[0].strip(' :') or 'Bakiye')}: {x:g} → {y:g}")
        if len(notes) >= 5:
            break
    return notes


async def uni_screen(page) -> str:
    try:
        return await page.locator("body").inner_text(timeout=4000)
    except Exception:
        return ""


async def uni_scan(page) -> list:
    try:
        cands = await page.evaluate("() => window.__uni ? window.__uni.scan() : []") or []
    except Exception:
        return []
    # alt menü çubuğu: ekranın altında aynı hizada 3+ öğe → sadece sekme olarak kullanılır
    rows = {}
    for c in cands:
        if c.get("bottom") and not c.get("overlay"):
            rows.setdefault(round(c["y"] / 12), []).append(c)
    for grp in rows.values():
        if len(grp) >= 3 and all(c["h"] < 110 for c in grp):
            for c in grp:
                c["navbar"] = True
    return cands


async def uni_drain(page) -> dict:
    try:
        return await page.evaluate("() => window.__uni ? window.__uni.drain() : {events:[],links:[],blocked:[]}") or {}
    except Exception:
        return {}


def uni_classify(c: dict) -> str:
    text = (c.get("text") or "").strip()
    ctx = c.get("ctx") or ""
    both = text + " " + ctx
    if UNI_RISK_RE.search(text):
        return "risk"
    navtext = re.sub(r"[\d+]+", "", text).strip()
    if c.get("navbar"):
        if UNI_SKIP_RE.search(text):
            return "skip"
        return "nav" if UNI_NAV_RE.match(navtext) else "tabx"
    if (c.get("bottom") or c.get("tab")) and UNI_NAV_RE.match(navtext):
        return "nav"
    if UNI_RISK_RE.search(ctx) and len(ctx) < 200:
        return "risk"
    if UNI_SKIP_RE.search(text) or UNI_SKIP_RE.search(ctx[:160]):
        return "skip"
    if not UNI_ADS and (UNI_ADS_RE.search(text) or UNI_ADS_RE.search(ctx[:120])):
        return "skip"
    if c.get("overlay") and UNI_DISMISS_RE.match(text):
        # pencerede riskli içerik varsa sadece "kapat/geç" türü butonlar
        if UNI_RISK_RE.search(ctx) and not UNI_SAFE_DISMISS_RE.match(text):
            return "risk"
        return "dismiss"
    if UNI_REWARD_RE.match(text):
        return "reward"
    if UNI_CHECK_RE.match(text):
        return "check"
    if UNI_GO_RE.match(text):
        return "go"
    if UNI_NAV_RE.match(navtext) and len(navtext) <= 14:
        return "nav"
    if c.get("tab"):
        return "tabx"   # bilinmeyen sekme: ana menüde görev sekmesi bulunamazsa gezilir
    # görev satırı: satırın kendisi, '+500' gibi ödül butonu ya da ok simgesi
    rowtxt = text if text != "[ikon]" else ""
    if UNI_DONE_RE.search(text) or (UNI_DONE_RE.search(ctx[:80]) and len(ctx) < 120):
        return ""
    if text == "[ikon]" and UNI_TASK_VERB_RE.search(ctx[:160]):
        return "task"
    if UNI_AMOUNT_RE.match(text) and UNI_TASK_VERB_RE.search(ctx[:160]) and len(ctx) < 160:
        return "task"
    if 8 <= len(rowtxt) <= 140 and UNI_TASK_VERB_RE.search(rowtxt):
        return "task"
    return ""


async def uni_click(page, c: dict) -> bool:
    loc = page.locator(f'[data-uni="{c["id"]}"]')
    try:
        await loc.scroll_into_view_if_needed(timeout=4000)
    except Exception:
        pass
    try:
        await loc.click(timeout=6000, no_wait_after=True)
        return True
    except Exception:
        pass
    try:
        await loc.dispatch_event("click", timeout=3000)
        return True
    except Exception:
        return False


async def uni_handle_links(page, name: str, run: dict, notes: list):
    d = await uni_drain(page)
    for b in d.get("blocked") or []:
        run["blocked"].add(b)
    for ev in d.get("events") or []:
        t = ev.get("type", "")
        if t.startswith("popup:"):
            notes.append("Popup: " + t[6:160])
    urls = [x.get("url", "") for x in (d.get("links") or [])]
    urls += list(run["navq"])
    run["navq"].clear()
    if not urls:
        return 0
    tg = [u for u in urls if uni_tme_from_nav(u) or u.startswith("tg:")]
    other = [u for u in urls if u not in tg]
    for u in other[:5]:
        host = urlparse(u).hostname or u[:40]
        run["visited"].append(host)
    chans, bots = uni_join_targets(tg)
    me = (name or "").lower()
    bots = [b for b in bots if b.lower() != me]
    if chans and UNI_JOIN:
        todo = [c for c in chans if c.lower() not in run["joined"]][: max(0, UNI_JOIN_MAX - len(run["joined"]))]
        if todo:
            n = await v8_pxe_do_joins(todo, notes)
            for c in todo:
                run["joined"].add(c.lower())
            run["join_ok"] += n
    for b in bots:
        if b.lower() in run["bot_seen"]:
            continue
        run["bot_seen"].add(b.lower())
        if UNI_BOT_START and not UNI_BOT_NAME_RISK.search(b):
            try:
                if await try_lock(TG_LOCK, 20):
                    try:
                        await tg_client.send_message(b, "/start")
                        notes.append(f"Görev botu @{b} başlatıldı.")
                    finally:
                        TG_LOCK.release()
            except Exception as e:
                notes.append(f"@{b} başlatılamadı: {type(e).__name__}")
        else:
            notes.append(f"Görev başka bot istiyor: @{b} (UNI_BOT_START=1 ile otomatik başlatılır).")
    return len(urls)


async def uni_tap(page, notes: list):
    if UNI_TAPS <= 0:
        return 0
    try:
        tgt = await page.evaluate("() => window.__uni ? window.__uni.tapTarget() : null")
    except Exception:
        tgt = None
    if not tgt:
        return 0
    n = 0
    for _ in range(UNI_TAPS):
        x = tgt["x"] + random.uniform(-tgt["w"] * 0.18, tgt["w"] * 0.18)
        y = tgt["y"] + random.uniform(-tgt["h"] * 0.18, tgt["h"] * 0.18)
        try:
            await page.touchscreen.tap(x, y)
        except Exception:
            try:
                await page.mouse.click(x, y)
            except Exception:
                break
        n += 1
        await page.wait_for_timeout(random.randint(90, 260))
    notes.append(f"Tapper: ana coin'e {n} dokunuş yapıldı.")
    return n


UNI_TEXT_CAP = {"reward": 2, "check": 25, "go": 25, "task": 2, "dismiss": 30}
UNI_SCREEN_MAX = int(os.getenv("UNI_SCREEN_MAX", "12") or 12)   # ana ekranda en fazla işlem
UNI_TAB_MAX = int(os.getenv("UNI_TAB_MAX", "40") or 40)         # görev sekmesinde en fazla işlem


def uni_norm(t: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"\d+(?:[.,:]\d+)+|\d{3,}", "#", (t or "").strip().lower()))


def uni_gain(before: str, after: str) -> bool:
    """Aynı etiketli bir sayı arttı mı?"""
    b = dict(uni_numbers(before))
    for k, v in uni_numbers(after):
        if k in b and v > b[k]:
            return True
    return False


async def uni_work_screen(page, name: str, run: dict, notes: list, deadline: float, label: str):
    """Mevcut ekranda: pencere kapat → ödül → görev → kontrol, ta ki yapılacak kalmayana dek.
    Döngü koruması: aynı yazılı butona sınırlı basılır; kazanç getirmeyen ödül butonu bu turda bir daha denenmez;
    tekrar eden Claim→Close gibi desen görülürse ekran bırakılır."""
    idle = 0
    pending_check = False
    screen_actions = 0
    tcount = run.setdefault("tcount", {})
    recent = []
    while time.time() < deadline and run["actions"] < UNI_MAX_ACTIONS and screen_actions < (UNI_SCREEN_MAX if label == "ana" else UNI_TAB_MAX):
        if AUTO_STOP:
            notes.append("Durdurma isteği alındı.")
            return
        cands = await uni_scan(page)
        groups = {"reward": [], "check": [], "go": [], "task": [], "dismiss": [], "nav": [], "tabx": [], "risk": [], "skip": []}
        for c in cands:
            k = uni_classify(c)
            if k:
                groups[k].append(c)
        for c in groups["risk"]:
            if UNI_RISK_RE.search(c["text"]):
                run["risky"].add(c["text"][:30])
        for c in groups["nav"]:
            run["navs"].setdefault(c["text"].lower(), c["text"])

        def fresh(lst, kind, limit=1):
            out = []
            for c in lst:
                k = kind + ":" + c["key"]
                tk = f"{label}:{kind}:{uni_norm(c['text'])}"
                if run["clicked"].get(k, 0) < limit and tcount.get(tk, 0) < UNI_TEXT_CAP.get(kind, 3):
                    out.append((k, c))
            return out

        tsig = run.setdefault("task_sig", {})

        def sig_ok(c):
            sg = c.get("row") or uni_norm(c["text"])
            st = tsig.get(sg)
            return st is None or (st["n"] < 2 and not st["eff"])

        ov = lambda lst: [c for c in lst if c.get("overlay")]
        pg = lambda lst: [c for c in lst if not c.get("overlay")]
        order = []
        # 1) açık pencere/alt sayfa: ödül > görev(Join/Go) > kontrol > kapat
        order += [("reward", x) for x in fresh(ov(groups["reward"]), "reward")]
        order += [("go", x) for x in fresh(ov(groups["go"]), "go")]
        order += [("check", x) for x in fresh(ov(groups["check"]), "check", limit=2)]
        ov_dismiss = [("dismiss", x) for x in fresh(ov(groups["dismiss"]), "dismiss", limit=2)]
        if order or ov_dismiss:
            order += ov_dismiss
        else:
            # 2) sayfa: ödül > (bekleyen) kontrol > görev butonu > görev satırı > kontrol
            order += [("reward", x) for x in fresh(pg(groups["reward"]), "reward")]
            if pending_check or run["join_ok"]:
                order += [("check", x) for x in fresh(pg(groups["check"]), "check", limit=2)]
            gos = pg(groups["go"])
            tasks = groups["task"]
            # tüm görev satırları sadece görev sekmelerinde (Earn/Tasks/Görevler…); Mine/Profile/Upgrade'de sadece sosyal görevler
            task_tab = label != "ana" and bool(UNI_NAV_RE.match(re.sub(r"[\d+#>].*$", "", uni_norm(label)).strip() or "x"))
            if not task_tab:
                tasks = [c for c in tasks if UNI_SOCIAL_RE.search(c["text"] + " " + c["ctx"][:120]) and not UNI_AMOUNT_RE.match(c["text"])]
            if label == "ana":
                gos = [c for c in gos if UNI_MAIN_GO_RE.match(c["text"]) or UNI_SOCIAL_RE.search(c["text"] + " " + c["ctx"][:120])]
                tasks = [c for c in tasks if UNI_SOCIAL_RE.search(c["text"] + " " + c["ctx"][:120])]
            order += [("go", x) for x in fresh(gos, "go")]
            order += [("task", x) for x in fresh(tasks, "task") if sig_ok(x[1])]
            order += [("check", x) for x in fresh(pg(groups["check"]), "check", limit=1)]
            order += [("dismiss", x) for x in fresh(groups["dismiss"], "dismiss", limit=2)]

        if not order:
            idle += 1
            if idle >= (4 if pending_check else 2):
                return
            # bazı görevler 10-30 sn sonra Check/Claim açar
            await page.wait_for_timeout(7000 if pending_check else 1500)
            if pending_check:
                run["clicked"] = {k: v for k, v in run["clicked"].items() if not k.startswith("check:")}
            continue
        idle = 0
        kind, (key, c) = order[0]
        run["clicked"][key] = run["clicked"].get(key, 0) + 1
        tk = f"{label}:{kind}:{uni_norm(c['text'])}"
        tcount[tk] = tcount.get(tk, 0) + 1
        before = await uni_screen(page)
        ok = await uni_click(page, c)
        if not ok:
            continue
        run["actions"] += 1
        screen_actions += 1
        run["log"].append(f"{label}/{kind}: {c['text'][:30]}")
        recent.append(tk)
        if kind in ("go", "task"):
            pending_check = True
        await page.wait_for_timeout(2200 if kind != "check" else 3500)
        nlinks = await uni_handle_links(page, name, run, notes)
        after = await uni_screen(page)
        if kind == "task":
            sg = c.get("row") or uni_norm(c["text"])
            st = tsig.setdefault(sg, {"n": 0, "eff": False})
            st["n"] += 1
            try:
                ov_open = await page.evaluate("() => !!document.querySelector('[role=dialog],[aria-modal=true],dialog[open],[class*=sheet i],[class*=modal i]')")
            except Exception:
                ov_open = False
            st["eff"] = st["eff"] or bool(nlinks) or ov_open
        diff = uni_diff(before, after)
        gained = uni_gain(before, after)
        if diff and gained and kind in ("reward", "check"):
            run["gains"].extend(diff[:2])
        if kind == "reward" and not gained:
            # kazanç yok (zaten toplanmış / süre dolmamış) → bu buton bu turda bitti
            tcount[tk] = UNI_TEXT_CAP["reward"]
        # Claim→Close→Claim→Close gibi tekrar eden desen → bu ekranı bırak
        if len(recent) >= 4 and recent[-1] == recent[-3] and recent[-2] == recent[-4]:
            notes.append(f"{label}: tekrar eden döngü ({c['text'][:20]}) algılandı, ekran bırakıldı.")
            return
        if kind in ("go", "task") and run["join_ok"]:
            await page.wait_for_timeout(2500)


async def uni_flow(page, name, notes, state):
    """Evrensel mini app akışı — her mini uygulamada aynı mantık."""
    deadline = time.time() + UNI_BUDGET_S
    run = {"clicked": {}, "actions": 0, "log": [], "gains": [], "joined": set(), "join_ok": 0,
           "bot_seen": set(), "visited": [], "risky": set(), "blocked": set(), "navs": {}, "navq": state.get("nav_links") if isinstance(state.get("nav_links"), list) else []}
    state["uni_run"] = run
    notes.append(f"Evrensel mod: @{name}")
    await page.wait_for_timeout(2500)
    start_text = await uni_screen(page)

    state["stage"] = "uni_ana_ekran"
    await uni_handle_links(page, name, run, notes)
    await uni_work_screen(page, name, run, notes, deadline, "ana")

    state["stage"] = "uni_tapper"
    await uni_tap(page, notes)

    # sekmeleri gez
    state["stage"] = "uni_sekmeler"
    visited_tabs = set()

    async def scroll_and_work(lab: str):
        """Uzun görev listelerinde sona kadar kaydırıp her bölümü işle."""
        try:
            await page.mouse.move(195, 430)
        except Exception:
            pass
        last = await uni_screen(page)
        for _s in range(8):
            if time.time() >= deadline or run["actions"] >= UNI_MAX_ACTIONS or AUTO_STOP:
                return
            try:
                await page.mouse.wheel(0, 700)
                await page.evaluate("() => { const el = [...document.querySelectorAll('*')].filter(e => e.scrollHeight > e.clientHeight + 40 && /auto|scroll/.test(getComputedStyle(e).overflowY)).sort((a, b) => b.clientHeight - a.clientHeight)[0]; if (el) el.scrollBy(0, 700); else window.scrollBy(0, 700); }")
            except Exception:
                pass
            await page.wait_for_timeout(1200)
            await uni_work_screen(page, name, run, notes, deadline, lab)
            cur = await uni_screen(page)
            if cur == last:
                return
            last = cur

    async def work_tab(c, lab: str):
        if not await uni_click(page, c):
            return False
        await page.wait_for_timeout(2500)
        await uni_handle_links(page, name, run, notes)
        await uni_work_screen(page, name, run, notes, deadline, lab)
        await scroll_and_work(lab)
        return True

    for _ in range(UNI_TABS):
        if time.time() >= deadline or run["actions"] >= UNI_MAX_ACTIONS or AUTO_STOP:
            break
        cands = await uni_scan(page)
        kinds = [(uni_classify(c), c) for c in cands]
        navs = [c for k, c in kinds if k == "nav" and uni_norm(c["text"]) not in visited_tabs]
        if not navs:
            # görev sekmesi adı tanınmadı → alt menüdeki diğer (riskli/davet olmayan) sekmeleri dene
            navs = [c for k, c in kinds if k == "tabx" and c.get("navbar") and uni_norm(c["text"]) not in visited_tabs]
        if not navs:
            break
        navs.sort(key=lambda c: (not c.get("bottom"), c["x"], c["y"]))
        tab = navs[0]
        lab = tab["text"][:14]
        visited_tabs.add(uni_norm(tab["text"]))
        if not await work_tab(tab, lab):
            continue
        # sekme içindeki alt sekmeler (Daily / Social / Partners / In-game ...)
        for _sub in range(6):
            if time.time() >= deadline or run["actions"] >= UNI_MAX_ACTIONS or AUTO_STOP:
                break
            subs = []
            scan = await uni_scan(page)
            for c in scan:
                k = uni_classify(c)
                if c.get("navbar") or c.get("overlay") or k in ("risk", "skip"):
                    continue
                t = c["text"]
                if t == "[ikon]" or len(t) > 18 or UNI_TIMER_RE.search(t) or uni_norm(t) in visited_tabs:
                    continue
                if not (c.get("tab") or k == "nav"):
                    continue
                # gerçek sekme şeridi: aynı hizada en az 2 kısa sekme benzeri öğe
                peers = [o for o in scan if o is not c and abs(o["y"] - c["y"]) < 10 and abs(o["h"] - c["h"]) < 12
                         and len(o["text"]) <= 18 and not o.get("navbar")]
                if not peers:
                    continue
                subs.append(c)
            if not subs:
                break
            subs.sort(key=lambda c: (c["y"], c["x"]))
            st = subs[0]
            visited_tabs.add(uni_norm(st["text"]))
            await work_tab(st, f"{lab}>{st['text'][:10]}")

    await uni_handle_links(page, name, run, notes)
    end_text = await uni_screen(page)

    # rapor
    if visited_tabs:
        notes.append("Gezilen sekmeler: " + ", ".join(sorted(visited_tabs))[:200])
    if run["log"]:
        notes.append(f"Yapılan {run['actions']} işlem: " + " · ".join(run["log"][:45])[:2500])
    if run["joined"]:
        notes.append(f"Görev kanalları: {run['join_ok']}/{len(run['joined'])} katılım.")
    if run["visited"]:
        notes.append("Açılan dış linkler (ziyaret sayıldı): " + ", ".join(list(dict.fromkeys(run["visited"]))[:8]))
    if run["risky"]:
        notes.append("Basılmadı (cüzdan/ödeme/satın alma): " + " · ".join(list(run["risky"])[:8])[:300])
    if run["blocked"]:
        notes.append("Engellenen istekler: " + ", ".join(sorted(run["blocked"])))
    total = uni_diff(start_text, end_text)
    if total:
        notes.append("Ekrandaki değişim: " + " | ".join(total))
    if run["actions"] == 0:
        try:
            canvas = await page.evaluate("() => window.__uni ? window.__uni.hasCanvas() : false")
        except Exception:
            canvas = False
        if canvas:
            notes.append("Bu oyun canvas tabanlı (Unity/Phaser); DOM butonu yok, otomatik tıklanamadı.")
        snippet = " | ".join([ln.strip() for ln in end_text.splitlines() if ln.strip()][:12])
        if snippet:
            notes.append("Ekran özeti: " + snippet[:400])
        notes.append("Evrensel sonuç: ATLANDI (yapılacak güvenli işlem yok ya da hepsi zaten alınmış).")
    elif run["gains"] or uni_gain(start_text, end_text) or run["join_ok"]:
        notes.append("Evrensel sonuç: OK")
    else:
        notes.append("Evrensel sonuç: BELIRSIZ (tıklandı ama ekranda değişim okunamadı).")
    notes.append("Cüzdan, ödeme, Stars, TON, satın alma, hikaye/paylaşım ve davet adımlarına basılmaz.")
    return notes


# eski genel modu evrensel motora yönlendir
async def v8_generic_miniap_flow(page, name, notes, state):
    return await uni_flow(page, name, notes, state)


async def v8_browser(name, url, state):
    from playwright.async_api import async_playwright, TimeoutError as PWTimeout
    if not await v8_public(url):
        return ["Adres guvenlik kontrolunden gecmedi."]
    notes = []
    async with async_playwright() as p:
        state["stage"] = "chromium_baslatma"
        browser = await p.chromium.launch(headless=True, timeout=60000, args=WIZ_CHROME_ARGS)
        context = None
        try:
            context = await uni_new_context(browser, name)
            await context.add_init_script(UNI_SHIM_JS)
            cache = {}
            nav_links = []

            async def guard(route):
                req = route.request
                u = req.url
                host = urlparse(u).netloc
                try:
                    # ana sayfadan t.me'ye yönlendirme → yakala, sayfayı terk etme
                    if req.is_navigation_request() and uni_tme_from_nav(u):
                        nav_links.append(u)
                        await route.abort()
                        return
                    if host not in cache:
                        cache[host] = await v8_public(u)
                    if cache[host] and urlparse(u).scheme == "https":
                        await route.continue_()
                    else:
                        await route.abort()
                except Exception:
                    try:
                        await route.abort()
                    except Exception:
                        pass

            await context.route("**/*", guard)
            page = await context.new_page()
            page.set_default_timeout(10000)
            state["stage"] = "sayfa_acilisi"
            try:
                response = await page.goto(url, wait_until="domcontentloaded", timeout=60000)
                if response and response.status >= 400:
                    return [f"HTTP {response.status}; islem yapilmadi."]
            except PWTimeout:
                notes.append("Acilis suresi asildi; yuklenen ekran kontrol ediliyor.")
            await page.locator("body").wait_for(state="attached", timeout=15000)
            try:
                await page.wait_for_load_state("networkidle", timeout=12000)
            except Exception:
                pass
            await page.wait_for_timeout(3000)
            notes.append("Sayfa açıldı (Telegram köprüsü taklidi aktif).")
            low = name.lower()
            if low in ("pickaxeempirebot", "pickaxe_empire_bot"):
                notes.append("Pickaxe Empire özel profili seçildi.")
                notes = await v8_pickaxe_flow(page, name, notes, state)
                if UNI_AFTER_PROFILE:
                    state["nav_links"] = nav_links
                    notes.append("— Kalan görevler için evrensel motor —")
                    notes = await uni_flow(page, name, notes, state)
            elif low == "myageapp":
                notes = await v8_myage_page_flow(page, name, notes, state)
                if UNI_AFTER_PROFILE:
                    state["nav_links"] = nav_links
                    notes.append("— Kalan görevler için evrensel motor (Spin / Achievements / Tasks) —")
                    notes = await uni_flow(page, name, notes, state)
            else:
                state["nav_links"] = nav_links
                notes = await uni_flow(page, name, notes, state)
            return notes
        finally:
            if context is not None:
                await uni_save_state(context, name)
            try:
                await asyncio.wait_for(browser.close(), 15)
            except Exception:
                pass


def _v8_notes_outcome(notes: list) -> str:
    text = "\n".join(notes)
    if "toplama doğrulandı" in text or "toplama dogrulandi" in text or "HOLDING arttı" in text:
        return "ok"
    if "Evrensel sonuç: OK" in text:
        return "ok"
    if "Evrensel sonuç: ATLANDI" in text or "Evrensel sonuç: BELIRSIZ" in text:
        return "skip"
    if "toplama doğrulandı" in text or "toplama dogrulandi" in text or "doğrulandı" in text:
        return "ok"
    if "claim atlandı" in text or "claim atlandi" in text or "Kasa zaten" in text:
        return "skip"
    if "toplandı kabul edilmedi" in text or "toplandi kabul edilmedi" in text:
        return "skip"
    return "err"


# ---------- bot başına istatistik / otomatik bekletme ----------

def uni_per(bot: str) -> dict:
    per = V8_AP.setdefault("per", {})
    return per.setdefault(bot, {"ok": 0, "skip": 0, "err": 0, "fail": 0, "last": 0})


def uni_track(bot: str, outcome: str):
    st = uni_per(bot)
    st[outcome] = int(st.get(outcome, 0)) + 1
    st["last"] = time.time()
    st["fail"] = int(st.get("fail", 0)) + 1 if outcome == "err" else 0


def uni_paused(bot: str) -> bool:
    st = uni_per(bot)
    if int(st.get("fail", 0)) < UNI_FAIL_PAUSE:
        return False
    # 12 saatte bir yine de dene
    return time.time() - float(st.get("last") or 0) < 12 * 3600


# ---------- hesaptaki tüm mini app botlarını bul ----------

async def uni_discover_bots(limit: int = 400) -> list:
    from telethon.tl.functions.users import GetFullUserRequest
    found = []
    own = ""
    try:
        own = (bot_app.bot.username or "").lower()
    except Exception:
        pass
    async for d in tg_client.iter_dialogs(limit=limit):
        e = d.entity
        if not getattr(e, "bot", False):
            continue
        un = (getattr(e, "username", None) or "").lower()
        if not un or un == own or UNI_BOT_NAME_RISK.search(un):
            continue
        has = bool(getattr(e, "bot_has_main_app", False))
        if not has:
            try:
                full = await tg_client(GetFullUserRequest(e))
                mb = getattr(getattr(full.full_user, "bot_info", None), "menu_button", None)
                has = type(mb).__name__ == "BotMenuButton"
            except Exception as ex:
                if "FloodWait" in type(ex).__name__:
                    break
            await asyncio.sleep(0.6)
        if has:
            found.append(un)
    return found


async def uni_auto_add(name: str, notes: list):
    if not V8_AP.get("auto_add") or name in (V8_AP.get("blocked") or []):
        return
    txt = "\n".join(notes or [])
    if "açılış adresi alınamadı" in txt.lower() or "acilis adresi alinamadi" in txt.lower() or "Hedef bot" in txt:
        return
    if UNI_BOT_NAME_RISK.search(name):
        return
    bots = v8_ap_bots()
    if name not in bots:
        bots.append(name)
        V8_AP["bots"] = bots
        await persist_v8_ap()
        await bot_app.bot.send_message(ADMIN_USER_ID, f"➕ @{name} otopilot listesine otomatik eklendi ({len(bots)} bot).")


# ---------- V8.33: anlaşılır raporlar + engelli botlar ----------

V8_LAST: dict = {}

UNI_HELP_TEXT = (
    "📖 KOMUTLAR\n"
    "• otopilot aç / otopilot kapat — otomatik turları başlat/durdur\n"
    "• otopilot hepsi — hesabındaki mini app botlarını bul + başlat\n"
    "• otopilot tara — sadece bul ve listeye ekle\n"
    "• otopilot ekle botadi — listeye ekle\n"
    "• otopilot sil botadi — listeden çıkar ve ENGELLE (tekrar eklenmez)\n"
    "• engelliler — engellenen botları göster\n"
    "• otopilot — durum\n"
    "• rapor kısa — tur sonunda tek özet (varsayılan)\n"
    "• rapor detay — her bot için teknik log da gelsin\n"
    "• detay botadi — o botun son tam logunu göster\n"
    "• @botadi veya t.me linki — tek sefer çalıştır\n"
    "• dur — çalışan işi durdur\n"
    "Not: Telegram'da bir botun sohbetini silersen otopilot onu kendiliğinden listeden çıkarır."
)

UNI_STAGE_TR = {
    "telegram_hedefi": "bot Telegram'da bulunamadı",
    "telegram_kilidi": "Telegram meşguldü",
    "start_gonderme": "/start gönderilemedi",
    "mini_uygulama_kilidi": "başka bir iş sürüyordu",
    "yetkili_adres_alma": "mini uygulama açılamadı (Telegram adres vermedi)",
    "sayfa_acilisi": "sayfa yüklenemedi",
    "chromium_baslatma": "tarayıcı başlatılamadı",
}


def uni_problem_tr(notes: list) -> str:
    text = "\n".join(notes or [])
    low = text.lower()
    stage = ""
    m = re.search(r"Aşama:\s*(\S+)", text)
    if m:
        stage = m.group(1)
    err = ""
    m = re.search(r"Hata:\s*(\S+)", text)
    if m:
        err = m.group(1)
    if "BELLEK SINIRI" in text:
        return "mini app sunucu belleğini doldurdu (512 MB yetmedi), bot çökmesin diye tarayıcı kapatıldı"
    if "mini uygulama değil" in low or "MİNİ UYGULAMA DEĞİL" in text:
        return "bu bot mini uygulama değil (sadece sohbet botu), atlanabilir"
    if "açılış adresi alınamadı" in low or "acilis adresi alinamadi" in low:
        return "mini uygulama açılamadı (Telegram adres vermedi)"
    if "hedef bot" in low and "bulunamad" in low:
        return "bot Telegram'da bulunamadı"
    if stage in UNI_STAGE_TR:
        return UNI_STAGE_TR[stage]
    if stage.startswith("uni_") or "Timeout" in err:
        return "uygulama içinde zaman aşımı (çok yavaş açıldı)"
    if "FloodWait" in err:
        return "Telegram çok sık istek dedi, sonra tekrar denenecek"
    if err:
        return f"beklenmeyen hata ({err})"
    if "canvas tabanlı" in low:
        return "oyun canvas tabanlı, butonlara tıklanamıyor"
    return ""


def uni_short_line(bot: str, outcome: str, notes: list) -> str:
    text = "\n".join(notes or [])
    icon = {"ok": "✅", "skip": "➖", "err": "❌"}.get(outcome, "•")
    parts = []
    if "toplama doğrulandı" in text or "HOLDING arttı" in text:
        parts.append("ödül toplandı")
    m = re.search(r"Yapılan (\d+) işlem", text)
    if m:
        parts.append(f"{m.group(1)} tıklama")
    m = re.search(r"Görev kanalları: (\d+)/(\d+)", text)
    if m:
        parts.append(f"{m.group(1)} kanala katıldı")
    m = re.search(r"Ekrandaki değişim: ([^\n]+)", text)
    if m:
        # DÜZELTME: sadece ARTAN değer gösterilir (7.16 → 1.42 gibi azalanlar kazanç değildir)
        for part in m.group(1).split(" | "):
            mm = re.search(r"([0-9.,]+)\s*→\s*([0-9.,]+)\s*$", part)
            try:
                if mm and float(mm.group(2).replace(",", "")) > float(mm.group(1).replace(",", "")):
                    parts.append(part[:50])
                    break
            except ValueError:
                pass
    if outcome == "skip":
        if "BELIRSIZ" in text:
            parts.append("tıkladı ama sonuç görülmedi")
        elif not parts:
            parts.append("yapılacak bir şey yok (hepsi alınmış ya da süre dolmamış)")
    prob = uni_problem_tr(notes) if outcome != "ok" else ""
    if outcome == "err" and not prob:
        prob = "hata"
    line = f"{icon} @{bot} — " + (", ".join(parts) if parts else ("tamam" if outcome == "ok" else ""))
    if prob:
        line = line.rstrip(" —,") + f" — sorun: {prob}"
    return line.rstrip(" —")


async def uni_send_round_summary(lines: list, wait_s: int):
    ok = sum(1 for l in lines if l.startswith("✅"))
    sk = sum(1 for l in lines if l.startswith("➖"))
    er = sum(1 for l in lines if l.startswith("❌"))
    head = f"📋 Tur bitti — ✅ {ok} başarılı · ➖ {sk} boş · ❌ {er} hata\n"
    tail = (f"\n\n💤 Sonraki tur ~{wait_s // 60} dk sonra."
            f"\nBir botun ayrıntısı için: detay botadi  ·  Komutlar: komutlar")
    body = "\n".join(lines) if lines else "(çalıştırılan bot yok)"
    msg = head + "\n" + body
    for i in range(0, len(msg), 3500):
        chunk = msg[i:i + 3500]
        if i + 3500 >= len(msg):
            chunk += tail
        await bot_app.bot.send_message(ADMIN_USER_ID, chunk, disable_web_page_preview=True)


async def uni_dialog_usernames():
    """Hesaptaki sohbetlerin kullanıcı adları; hata olursa None (silme kontrolü atlanır)."""
    try:
        names = set()
        async for d in tg_client.iter_dialogs(limit=800):
            un = (getattr(d.entity, "username", None) or "").lower()
            if un:
                names.add(un)
        return names if names else None
    except Exception as e:
        print(f"[V8] dialog listesi alınamadı: {type(e).__name__}", flush=True)
        return None


async def uni_block_bot(name: str):
    name = (name or "").lstrip("@").lower()
    if not name:
        return
    V8_AP["bots"] = [b for b in v8_ap_bots() if b != name]
    bl = V8_AP.setdefault("blocked", [])
    if name not in bl:
        bl.append(name)
    await persist_v8_ap()


async def auto_link(name: str, short: str = "", start: str = ""):
    if name in V8_TASKS and not V8_TASKS[name].done():
        await v8_report(name, "Zaten sirada veya calisiyor.")
        return
    ahead = sum(1 for t in V8_TASKS.values() if not t.done())
    if ahead:
        await bot_app.bot.send_message(
            ADMIN_USER_ID, f"⏳ @{name} sıraya alındı — önünde {ahead} bot var (botlar tek tek çalışır, "
            f"tahmini {ahead * 2}–{ahead * 6} dk). Sırası gelince ▶️ mesajı gelecek. Durumu görmek için: sıra")
    else:
        await bot_app.bot.send_message(ADMIN_USER_ID, f"⏳ @{name} çalıştırılıyor… (1–5 dk sürer, bitince kısa sonuç gelecek). Durum: sıra")

    global AUTO_STOP
    AUTO_STOP = False

    async def job():
        try:
            await _job()
        except asyncio.CancelledError:
            try:
                if not AUTO_STOP:  # 'dur' ile toplu durdurmada her bot için ayrı mesaj atılmaz
                    await bot_app.bot.send_message(ADMIN_USER_ID, f"⏹ @{name} durduruldu.")
            except Exception:
                pass
            raise
        except Exception as e:
            # DÜZELTME: iş hata verirse artık sessiz kalmaz, sebebi yazılır
            print(f"[V8 JOB] {name} {e!r}", flush=True)
            try:
                await bot_app.bot.send_message(ADMIN_USER_ID, f"❌ @{name} — beklenmeyen hata: {type(e).__name__} {str(e)[:150]}")
            except Exception:
                pass

    async def _job():
        outcome, notes = await v8_run_and_track(name, short, start)
        uni_track(name, outcome)
        await persist_v8_ap()
        await bot_app.bot.send_message(ADMIN_USER_ID, uni_short_line(name, outcome, notes) + f"\n(Tam log: detay {name})", disable_web_page_preview=True)
        if outcome == "ok" and name not in v8_ap_bots() and name not in (V8_AP.get("blocked") or []) and not UNI_BOT_NAME_RISK.search(name):
            # elle çalıştırılıp başarılı olan bot otopilota eklenir
            V8_AP["bots"] = v8_ap_bots() + [name]
            await persist_v8_ap()
            await bot_app.bot.send_message(ADMIN_USER_ID, f"➕ @{name} başarılı çalıştı, otopilot listesine eklendi ({len(V8_AP['bots'])} bot). Çıkarmak için: otopilot sil {name}")
        else:
            await uni_auto_add(name, notes)

    V8_TASKS[name] = spawn(job())


def v8_ap_status_text() -> str:
    on = "AÇIK" if V8_AP.get("on") else "KAPALI"
    last = V8_AP.get("last") or 0
    ago = f" | son tur: {int((time.time() - last) / 60)} dk önce" if last else ""
    bl = v8_ap_bots()
    paused = [b for b in bl if uni_paused(b)]
    if len(bl) <= 15:
        bots_s = ", ".join("@" + x for x in bl) if bl else "(liste boş)"
    else:
        bots_s = ", ".join("@" + x for x in bl[:15]) + f" … (+{len(bl) - 15})"
    return (
        f"V8 Otopilot: {on}\n"
        f"Botlar ({len(bl)}): {bots_s}\n"
        f"Beklemede (üst üste hata): {', '.join('@' + b for b in paused) or '-'}\n"
        f"Oto-ekle (radar yeni mini app bulunca): {'AÇIK' if V8_AP.get('auto_add') else 'KAPALI'}\n"
        f"Son bot: @{V8_AP.get('bot', '-')}\n"
        f"Aralık: {V8_AP.get('min_m')}-{V8_AP.get('max_m')} dk (rastgele)\n"
        f"Başarılı: {V8_AP.get('n_ok', 0)} | Atlanan: {V8_AP.get('n_skip', 0)} | Hata: {V8_AP.get('n_err', 0)}{ago}\n"
        f"Engelli: {len(V8_AP.get('blocked') or [])} bot  ·  Rapor: {'DETAY' if V8_AP.get('report') == 'detay' else 'KISA'}\n\n"
        f"Tüm komutlar için: komutlar"
    )



# =====================================================================
# V9 — GROQ SİHİRBAZI (akıllı mini app asistanı)
# ---------------------------------------------------------------------
#  1) Akıllı Groq: model zinciri (biri kapalıysa / limiti dolduysa sıradakine
#     geçer), JSON modu, 429'da bekleme süresini okur, Gemini yedek.
#  2) Ekran okuma: mini app'te gezilen her ekranın yazısı kaydedilir; Groq
#     yazıları/cümleleri okuyup anlar (hangi dilde olursa olsun).
#  3) Yapay zeka ile görev: kural motoru bitince Groq ekrana bakıp "sıradaki
#     güvenli adım" kararını verir (tıkla / kod yaz / kaydır / geri / bitir).
#     Cüzdan, ödeme, Stars, TON, satın alma, davet/paylaşım ASLA yapılmaz —
#     yapay zeka istese bile kod engeller.
#  4) Referans avcısı: ağ cevapları (API JSON), sayfa HTML'i, kutucuklar,
#     "Kopyala" butonu (pano yakalanır), Davet/Friends sekmesi, paylaş linki
#     ve en son bot sohbetinden kişisel referans linkini bulur, kaydeder.
#  5) Her mini app için Türkçe ÖZET + altında REFERANS LİNKİ gönderir.
#     Yapamadığı şeyleri nedeniyle birlikte "❗ Yapamadıklarım" bölümüne yazar.
#  6) Hata düzeltmeleri: 'dur' sonrası otopilot döngüsünün ölmesi, 4096
#     karakteri aşan raporların çökmesi, 800+ sohbetli hesapta botların
#     yanlışlıkla engellenmesi, FloodWait sırasında katılım denemesi,
#     tıklanamayan butonlar (5 farklı tıklama yöntemi), açılmayan sayfa
#     (temiz oturumla 1 kez daha dener).
# Komutlar (özel sohbet): sihirbaz · özet botadi · özetler · referanslar ·
#   ref botadi link · sor <soru> · sihirbaz aç/kapat · sihirbaz ai aç/kapat ·
#   özet mod her|yeni|kapalı
# =====================================================================

from urllib.parse import unquote as _wiz_unquote

if not os.getenv("V8_JOB_TIMEOUT"):
    V8_JOB_TIMEOUT = 720  # sihirbaz adımları (AI + referans) için ek süre; tek bot en fazla ~12 dk

WIZ_AI_STEPS = int(os.getenv("WIZ_AI_STEPS", "10") or 10)          # bir botta en fazla AI kararı
WIZ_AI_BUDGET_S = int(os.getenv("WIZ_AI_BUDGET_S", "170") or 170)  # AI keşif süresi (sn)
WIZ_REF_BUDGET_S = int(os.getenv("WIZ_REF_BUDGET_S", "70") or 70)  # referans avı süresi (sn)
WIZ_AI_GAP = float(os.getenv("WIZ_AI_GAP", "2.5") or 2.5)          # iki Groq isteği arası en az sn
WIZ_SUM_KEY = os.getenv("WIZ_SUM_KEY", "radar:wiz_sum:v1").strip()
WIZ_SUM_FILE = os.getenv("WIZ_SUM_FILE", "/tmp/radar_wiz_sum.json")
WIZ_RESEND_H = int(os.getenv("WIZ_RESEND_H", "24") or 24)          # 'yeni' modda aynı bot özeti en az kaç saatte bir

_wiz_chain_env = os.getenv("GROQ_MODELS", "").strip()
GROQ_CHAIN = [m.strip() for m in (
    ([GROQ_MODEL] if GROQ_MODEL else [])
    + (_wiz_chain_env.split(",") if _wiz_chain_env else
       ["openai/gpt-oss-120b", "llama-3.3-70b-versatile", "openai/gpt-oss-20b",
        "qwen/qwen3.8-27b", "llama-3.1-8b-instant"])
) if m.strip()]
GROQ_CHAIN = list(dict.fromkeys(GROQ_CHAIN))

V8_AP.setdefault("wiz_on", True)       # sihirbaz (özet + referans) açık mı
V8_AP.setdefault("wiz_ai", True)       # yapay zeka ile görev adımları açık mı
V8_AP.setdefault("wiz_ap_mode", "yeni")  # otopilotta özet: her | yeni | kapali

WIZ_SUM: dict = {}          # bot -> {"t","outcome","summary","ref","ref_src","problems"}
WIZ_CUR: dict = {}          # o an çalışan botun canlı verisi
WIZ_ME = {"id": None}
GROQ_STATE = {"dead": {}, "cool": {}, "last": 0.0, "lock": None, "used": {}}

WIZ_SYSTEM = (
    "Sen Telegram mini uygulamaları (tap-to-earn, farm, airdrop, görev oyunları) konusunda uzman, "
    "dikkatli bir asistansın. Metinler HANGİ DİLDE olursa olsun (İngilizce, Rusça, Çince...) okuyup "
    "anlarsın ve HER ZAMAN TÜRKÇE cevap verirsin. Kurallar: 1) Sadece sana verilen bilgiyi kullan, "
    "ASLA uydurma; bilmiyorsan 'belirsiz' de. 2) Cüzdan bağlama, ödeme, Stars, TON, USDT, satın alma, "
    "yatırım, çekim, depozito, telefon numarası, arkadaş daveti, hikaye/paylaşım adımlarını ASLA önerme "
    "ve seçme. 3) Kısa, net, maddeli yaz."
)

WIZ_RISK_INPUT_RE = re.compile(
    r"wallet|address|adres|e-?mail|phone|telefon|card|kart|password|şifre|sifre|seed|mnemonic|private|"
    r"amount|miktar|tutar|iban|\b0x|\bUQ|\bEQ|кошел|адрес|телефон|пароль", re.I)
WIZ_REF_RE = re.compile(
    r"(?:https?://)?(?:t\.me|telegram\.me)/([A-Za-z0-9_]{4,32})(?:/([A-Za-z0-9_]{1,64}))?/?\?(start|startapp)="
    r"([A-Za-z0-9_\-%=.]{2,160})", re.I)
WIZ_CODE_RE = re.compile(
    r'"(ref(?:erral)?_?code|invite_?code|refCode|inviteCode|referralCode|ref_?link|referral_?link|invite_?link|'
    r'inviteLink|referralLink|refLink|ref_?url|invite_?url|share_?link|shareLink|startParam|start_param)"\s*:\s*"([^"]{2,200})"',
    re.I)
WIZ_REF_NAV_RE = re.compile(
    r"friend|frens|fren\b|invite|refer|referral|affiliate|squad|team\b|партн|друз|приглас|реферал|davet|arkada[şs]|ekip|tak[ıi]m|ortakl",
    re.I)
WIZ_COPY_RE = re.compile(r"copy|kopyala|копир|скопир|^\[ikon\]$|📋|⧉", re.I)
WIZ_SHARE_RE = re.compile(r"invite|share|send|davet|payla[şs]|gönder|gonder|приглас|поделит|отправ", re.I)

WIZ_SHIM_JS = r"""
(() => {
  const U = window.__uni;
  if (!U || U.__wiz) return;
  U.__wiz = 1;
  U.clips = []; U.allLinks = [];
  const origPush = Array.prototype.push;
  U.links.push = function (...a) { try { origPush.apply(U.allLinks, a); } catch (e) {} return origPush.apply(this, a); };
  // pano (Kopyala butonu) yakala — gerçek panoya yazmaz
  try {
    const fake = { writeText: (t) => { U.clips.push(String(t || '')); return Promise.resolve(); },
                   readText: () => Promise.resolve(''),
                   write: () => Promise.resolve(), read: () => Promise.resolve([]) };
    Object.defineProperty(navigator, 'clipboard', { value: fake, configurable: true });
  } catch (e) {}
  try {
    const oe = document.execCommand ? document.execCommand.bind(document) : null;
    document.execCommand = function (cmd, ...rest) {
      try {
        if (String(cmd).toLowerCase() === 'copy') {
          const a = document.activeElement;
          let t = (window.getSelection && String(window.getSelection())) || '';
          if (!t && a && 'value' in a) t = a.value;
          U.clips.push(String(t || ''));
          return true;
        }
      } catch (e) {}
      return oe ? oe(cmd, ...rest) : false;
    };
  } catch (e) {}
  U.fire = (t, d) => {
    try {
      const W = window.Telegram && window.Telegram.WebView;
      if (W && typeof W.receiveEvent === 'function') { W.receiveEvent(t, d || {}); return true; }
    } catch (e) {}
    return false;
  };
  // yazı kutuları (kod girme görevleri için)
  U.inputs = () => {
    const out = [];
    let n = 0;
    for (const el of document.querySelectorAll('input:not([type=hidden]):not([type=button]):not([type=submit]):not([type=checkbox]):not([type=radio]), textarea')) {
      const r = el.getBoundingClientRect();
      if (r.width < 20 || r.height < 10) continue;
      const st = getComputedStyle(el);
      if (st.display === 'none' || st.visibility === 'hidden') continue;
      const id = 'w' + (++n);
      el.setAttribute('data-wiz', id);
      let ctx = '', p = el.parentElement;
      for (let i = 0; p && i < 4; i++, p = p.parentElement) { const t = (p.innerText || '').replace(/\s+/g, ' ').trim(); if (t.length > 6) { ctx = t.slice(0, 160); break; } }
      out.push({ id, ph: (el.placeholder || el.getAttribute('aria-label') || el.name || '').slice(0, 60),
                 val: (el.value || '').slice(0, 200), ro: !!el.readOnly, type: el.type || 'text', ctx });
      if (out.length >= 12) break;
    }
    return out;
  };
  // sayfadaki her yerden referans adayı
  U.refBlob = () => {
    const parts = [];
    try { parts.push(document.documentElement.innerHTML.slice(0, 600000)); } catch (e) {}
    try { for (const el of document.querySelectorAll('input, textarea')) parts.push(el.value || ''); } catch (e) {}
    try { parts.push(U.clips.join('\n')); } catch (e) {}
    try { parts.push(U.allLinks.map(x => x.url).join('\n')); } catch (e) {}
    try { for (let i = 0; i < localStorage.length; i++) { const k = localStorage.key(i); parts.push(k + '=' + String(localStorage.getItem(k)).slice(0, 2000)); } } catch (e) {}
    return parts.join('\n');
  };
})();
"""


# ---------------------------------------------------------------- Groq ----

def _wiz_is_qwen(model: str) -> bool:
    return "qwen" in (model or "").lower()


def _wiz_is_gptoss(model: str) -> bool:
    return model.lower().startswith("openai/gpt-oss")


def _wiz_retry_after(resp, data) -> float:
    try:
        ra = resp.headers.get("retry-after")
        if ra:
            return float(ra)
    except Exception:
        pass
    msg = json.dumps(data)[:600] if data else ""
    m = re.search(r"try again in (?:(\d+)m)?([\d.]+)s", msg)
    if m:
        return int(m.group(1) or 0) * 60 + float(m.group(2))
    m = re.search(r"try again in (\d+)m", msg)
    if m:
        return int(m.group(1)) * 60
    return 20.0


async def groq_chat(messages: list, json_mode: bool = False, max_tokens: int = 900,
                    temperature: float = 0.2, timeout: int = 60, gemini: bool = True, models: list = None):
    """Akıllı Groq çağrısı: model zinciri + 429 bekleme + JSON modu. (metin | None, not) döner."""
    if not GROQ_API_KEY and not (gemini and GEMINI_API_KEY):
        return None, "GROQ_API_KEY yok"
    assert http_session is not None
    if GROQ_STATE["lock"] is None:
        GROQ_STATE["lock"] = asyncio.Lock()
    last_note = "Groq hata"
    for model in ((models or GROQ_CHAIN) if GROQ_API_KEY else []):
        now = time.time()
        if GROQ_STATE["dead"].get(model, 0) > now or GROQ_STATE["cool"].get(model, 0) > now:
            continue
        use_json = json_mode
        use_reason = _wiz_is_gptoss(model)
        use_hide = _wiz_is_qwen(model)  # qwen düşünme metnini gizle (cevap kısa ve temiz gelsin)
        for attempt in range(4):
            async with GROQ_STATE["lock"]:
                gap = WIZ_AI_GAP - (time.time() - GROQ_STATE["last"])
                if gap > 0:
                    await asyncio.sleep(gap)
                GROQ_STATE["last"] = time.time()
            body = {"model": model, "messages": messages, "temperature": temperature,
                    "max_tokens": max_tokens + (1200 if _wiz_is_gptoss(model) else 0)}
            if use_reason:
                body["reasoning_effort"] = "low"
            if use_hide:
                body["reasoning_format"] = "hidden"
                body["max_tokens"] = max_tokens + 1500
            if use_json:
                body["response_format"] = {"type": "json_object"}
            try:
                async with http_session.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
                    json=body, timeout=aiohttp.ClientTimeout(total=timeout),
                ) as resp:
                    try:
                        data = await resp.json(content_type=None)
                    except Exception:
                        data = {}
                    st = resp.status
                    err = json.dumps(data.get("error") or {})[:400] if isinstance(data, dict) else ""
                    if st == 429:
                        wait = _wiz_retry_after(resp, data)
                        last_note = f"Groq {model} limit"
                        if wait <= 12 and attempt < 3:
                            await asyncio.sleep(wait + 0.5)
                            continue
                        GROQ_STATE["cool"][model] = time.time() + min(wait, 6 * 3600)
                        print(f"[GROQ] {model} limit doldu, {int(wait)} sn sıradaki modele geçiliyor", flush=True)
                        break
                    if st in (500, 502, 503, 504):
                        last_note = f"Groq {model} {st}"
                        await asyncio.sleep(2 + attempt * 3)
                        continue
                    if st == 400 and use_json and ("response_format" in err or "json" in err.lower()):
                        use_json = False  # model JSON modunu desteklemiyor / bozuk JSON üretti → düz metin
                        continue
                    if st == 401:
                        return None, "Groq anahtarı geçersiz (401)"
                    el = err.lower()
                    if st in (403, 404) or (st == 400 and any(w in el for w in (
                            "decommission", "does not exist", "not found", "not have access", "model_not", "terms"))):
                        GROQ_STATE["dead"][model] = time.time() + 6 * 3600
                        last_note = f"Groq {model} kullanılamıyor ({st})"
                        print(f"[GROQ] {model} kullanılamıyor: {st} {err[:160]}", flush=True)
                        break
                    if st == 400 and "reasoning" in el and (use_reason or use_hide):
                        use_reason = use_hide = False
                        continue
                    if st >= 400:
                        last_note = f"Groq {model} {st}"
                        print(f"[GROQ] {model} {st} {err[:200]}", flush=True)
                        break
                    msg = ((data.get("choices") or [{}])[0].get("message") or {})
                    raw = (msg.get("content") or "").strip()
                    raw = re.sub(r"(?s)<think>.*?</think>", "", raw).strip()
                    if raw.startswith("<think>"):  # düşünme yarıda kesildi → cevap yok
                        raw = ""
                    if raw:
                        GROQ_STATE["used"][model] = GROQ_STATE["used"].get(model, 0) + 1
                        return raw, model
                    last_note = f"Groq {model} boş cevap"
                    break
            except Exception as e:
                last_note = f"Groq {model} {type(e).__name__}"
                print("[GROQ EX]", model, repr(e), flush=True)
                await asyncio.sleep(2)
    # Groq'un tümü düşerse Gemini yedeği
    if gemini and GEMINI_API_KEY:
        flat = "\n\n".join(f"[{m['role']}]\n{m['content']}" for m in messages)
        if json_mode:
            flat += "\n\nSADECE geçerli JSON döndür."
        raw, note = await _gemini(flat)
        if raw:
            return raw, "gemini"
        last_note += f" / {note}"
    return None, last_note


def wiz_json(text: str):
    if not text:
        return None
    t = text.strip()
    t = re.sub(r"^```(?:json)?|```$", "", t, flags=re.M).strip()
    try:
        return json.loads(t)
    except Exception:
        pass
    m = re.search(r"\{.*\}", t, re.S)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            return None
    return None


# Eski Groq fonksiyonunu akıllı zincire bağla (radar rehberi / inceleme raporu da akıllanır)
async def _groq(prompt_full: str):
    raw, note = await groq_chat([{"role": "system", "content": WIZ_SYSTEM},
                                 {"role": "user", "content": prompt_full}], max_tokens=1024, gemini=False)
    return (raw, "") if raw else (None, note)


# --------------------------------------------------- rapor / güvenli gönderim ----

def _wiz_chunks(text: str, n: int = 3800) -> list:
    out, cur = [], ""
    for line in text.split("\n"):
        while len(line) > n:
            if cur:
                out.append(cur)
                cur = ""
            out.append(line[:n])
            line = line[n:]
        if len(cur) + len(line) + 1 > n:
            out.append(cur)
            cur = ""
        cur += line + "\n"
    if cur.strip():
        out.append(cur)
    return [c for c in out if c.strip()] or ["(boş)"]


async def wiz_send(text: str, kb=None):
    """4096 sınırına takılmadan parça parça gönderir."""
    chunks = _wiz_chunks(text or "(boş)")
    for i, ch in enumerate(chunks):
        try:
            await bot_app.bot.send_message(ADMIN_USER_ID, ch.rstrip(), disable_web_page_preview=True,
                                           reply_markup=kb if i == len(chunks) - 1 else None)
        except Exception as e:
            print("[WIZ SEND]", repr(e), flush=True)
            try:
                await bot_app.bot.send_message(ADMIN_USER_ID, ch.rstrip()[:3900], disable_web_page_preview=True)
            except Exception:
                pass


async def v8_report(name, text):  # DÜZELTME: uzun log artık çökmeden parça parça gider
    await wiz_send(f"@{name} — V8 SONUC\n{text}")


# ------------------------------------------------------- kalıcı özetler ----

async def wiz_persist():
    if len(WIZ_SUM) > 300:
        for k, _ in sorted(WIZ_SUM.items(), key=lambda kv: kv[1].get("t", 0))[: len(WIZ_SUM) - 300]:
            WIZ_SUM.pop(k, None)
    await save_json(WIZ_SUM_KEY, WIZ_SUM_FILE, WIZ_SUM)


async def wiz_load():
    data = await load_json(WIZ_SUM_KEY, WIZ_SUM_FILE)
    if isinstance(data, dict):
        WIZ_SUM.update(data)
    print("[SIHIRBAZ] kayıtlı özet:", len(WIZ_SUM), "| Groq zinciri:", ", ".join(GROQ_CHAIN), flush=True)


_wiz_load_v8_ap_base = load_v8_ap


async def load_v8_ap():
    await _wiz_load_v8_ap_base()
    await wiz_load()


async def wiz_me_id():
    if WIZ_ME["id"] is None and tg_client:
        try:
            WIZ_ME["id"] = (await asyncio.wait_for(tg_client.get_me(), 20)).id
        except Exception:
            WIZ_ME["id"] = 0
    return WIZ_ME["id"] or 0


# ------------------------------------------------- ekran kaydı + tıklama ----

def wiz_new_cur(name: str, start: str = "") -> dict:
    cur = {"bot": name, "start": start or "", "screens": [], "sig": set(), "fails": [], "ai_log": [],
           "ai_issues": [], "refs": {}, "codes": [], "net_n": 0, "ai_gain": [], "ai_steps": 0}
    WIZ_CUR.clear()
    WIZ_CUR.update(cur)
    return WIZ_CUR


async def uni_screen(page) -> str:
    """Ekran yazısını okur ve sihirbaz için kaydeder (aynı ekranı iki kez saklamaz)."""
    try:
        txt = await page.locator("body").inner_text(timeout=4000)
    except Exception:
        return ""
    if WIZ_CUR and txt:
        sig = hashlib.sha1(uni_norm(txt)[:900].encode("utf-8", "ignore")).hexdigest()[:12]
        if sig not in WIZ_CUR["sig"] and len(WIZ_CUR["screens"]) < 30:
            WIZ_CUR["sig"].add(sig)
            lines = [ln.strip() for ln in txt.splitlines() if ln.strip()]
            WIZ_CUR["screens"].append(" | ".join(dict.fromkeys(lines))[:1500])
    return txt


async def uni_click(page, c: dict) -> bool:
    """DÜZELTME: 5 farklı yöntemle tıklar; hiçbiri olmazsa 'yapamadım' listesine yazar."""
    loc = page.locator(f'[data-uni="{c["id"]}"]')
    try:
        cnt = await loc.count()
    except Exception:
        cnt = 0
    if cnt:
        try:
            await loc.first.scroll_into_view_if_needed(timeout=3000)
        except Exception:
            pass
        try:
            await loc.first.click(timeout=5000, no_wait_after=True)
            return True
        except Exception:
            pass
        try:
            await loc.first.click(timeout=3000, no_wait_after=True, force=True)
            return True
        except Exception:
            pass
        try:
            box = await loc.first.bounding_box()
            if box and box["width"] > 0:
                x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
                try:
                    await page.touchscreen.tap(x, y)
                except Exception:
                    await page.mouse.click(x, y)
                return True
        except Exception:
            pass
        try:
            await loc.first.dispatch_event("click", timeout=2500)
            return True
        except Exception:
            pass
    try:
        ok = await page.evaluate(
            "(id) => { const el = document.querySelector('[data-uni=\"' + id + '\"]'); if (!el) return false; el.click(); return true; }",
            c["id"])
        if ok:
            return True
    except Exception:
        pass
    if WIZ_CUR is not None and WIZ_CUR:
        t = (c.get("text") or "?")[:40]
        msg = f"'{t}' butonuna basılamadı (öğe kayboldu ya da üstü kapalı)"
        if msg not in WIZ_CUR["fails"] and len(WIZ_CUR["fails"]) < 20:
            WIZ_CUR["fails"].append(msg)
    return False


# ------------------------------------------------- referans toplama ----

def wiz_add_refs(blob: str, src: str):
    if not WIZ_CUR or not blob:
        return 0
    blob = blob.replace("\\/", "/").replace("\\u0026", "&").replace("&amp;", "&")
    n = 0
    # paylaş linkleri: t.me/share/url?url=<kodlu ref>
    for m in re.finditer(r"(?:t\.me|telegram\.me)/share/url\?([^\s\"'<>]+)", blob, re.I):
        qs = parse_qs(m.group(1))
        for v in (qs.get("url") or []) + (qs.get("text") or []):
            n += wiz_add_refs(_wiz_unquote(v), src + "/paylaş")
    for m in WIZ_REF_RE.finditer(blob):
        bot_n, short, kind, param = m.group(1), m.group(2) or "", m.group(3), m.group(4)
        low = bot_n.lower()
        if low in SKIP_LINK_NAMES or low in ("share", "addlist"):
            continue
        param = _wiz_unquote(param).rstrip(".")
        if WIZ_CUR.get("start") and param == WIZ_CUR["start"]:
            continue  # bizi davet edenin linki, bizim değil
        if re.fullmatch(r"[a-z]+(?:_[a-z]+)+", param):
            continue  # botun kendi eylem parametresi
        link = f"https://t.me/{bot_n}" + (f"/{short}" if short else "") + f"?{kind}={param}"
        score = 1
        if low == (WIZ_CUR.get("bot") or "").lower():
            score += 3
        me = WIZ_ME.get("id") or 0
        if me and str(me) in param:
            score += 4
        if "pano" in src or "kopya" in src:
            score += 2
        if "davet" in src:
            score += 1
        old = WIZ_CUR["refs"].get(link)
        if not old or old[0] < score:
            WIZ_CUR["refs"][link] = (score, src)
            n += 1
    for m in WIZ_CODE_RE.finditer(blob):
        k, v = m.group(1), m.group(2)
        if "t.me/" in v:
            n += wiz_add_refs(v, src + "/api")
        elif 2 <= len(v) <= 64 and not v.startswith("eyJ") and (k, v) not in WIZ_CUR["codes"] and len(WIZ_CUR["codes"]) < 8:
            if not (WIZ_CUR.get("start") and v == WIZ_CUR["start"]):
                WIZ_CUR["codes"].append((k, v))
    return n


WIZ_REF_MIN_SCORE = 3  # başka botların (partner görev) linkleri yanlışlıkla 'senin referansın' sayılmasın


def wiz_best_ref():
    if not WIZ_CUR or not WIZ_CUR.get("refs"):
        return None, ""
    link, (score, src) = max(WIZ_CUR["refs"].items(), key=lambda kv: kv[1][0])
    if score < WIZ_REF_MIN_SCORE:
        return None, ""
    return link, src


async def wiz_collect_dom(page, src: str):
    try:
        blob = await page.evaluate("() => window.__uni && window.__uni.refBlob ? window.__uni.refBlob() : ''")
    except Exception:
        blob = ""
    return wiz_add_refs(blob or "", src)


def wiz_attach_network(page):
    """API cevaplarındaki referans linki / kodunu dinler (sadece okur)."""
    async def cap(resp):
        try:
            if not WIZ_CUR or WIZ_CUR.get("net_n", 0) > 250:
                return
            ct = (resp.headers or {}).get("content-type", "")
            u = resp.url
            if not ("json" in ct or "/api" in u or "graphql" in u or "text/plain" in ct):
                return
            WIZ_CUR["net_n"] = WIZ_CUR.get("net_n", 0) + 1
            body = await asyncio.wait_for(resp.body(), 6)
            if body and len(body) < 600_000:
                wiz_add_refs(body.decode("utf-8", "ignore"), "ağ/API")
        except Exception:
            pass

    page.on("response", lambda r: asyncio.ensure_future(cap(r)))


async def wiz_ref_hunt(page, name: str, notes: list, state: dict):
    """Davet/Friends ekranını açıp referans linkini arar. Hiçbir şey paylaşılmaz/gönderilmez."""
    state["stage"] = "sihirbaz_referans"
    deadline = time.time() + WIZ_REF_BUDGET_S
    await wiz_collect_dom(page, "sayfa")
    link, _ = wiz_best_ref()
    if link and WIZ_CUR["refs"][link][0] >= 4:
        return
    tried = set()
    for _round in range(3):
        if time.time() > deadline or AUTO_STOP:
            break
        cands = await uni_scan(page)
        navs = [c for c in cands if WIZ_REF_NAV_RE.search(c.get("text") or "")
                and not UNI_RISK_RE.search(c.get("text") or "") and len(c.get("text") or "") <= 30
                and uni_norm(c["text"]) not in tried]
        navs.sort(key=lambda c: (not c.get("navbar"), not c.get("bottom"), c["y"]))
        if not navs:
            break
        tab = navs[0]
        tried.add(uni_norm(tab["text"]))
        if not await uni_click(page, tab):
            continue
        await page.wait_for_timeout(2800)
        await uni_screen(page)
        await wiz_collect_dom(page, "davet ekranı")
        # Kopyala butonları (pano yakalanır, gerçek panoya gitmez)
        cands = await uni_scan(page)
        copies = [c for c in cands if WIZ_COPY_RE.search(c.get("text") or "")
                  and (c.get("text") != "[ikon]" or re.search(r"link|t\.me|invite|refer|davet|code|kod|ссылк", c.get("ctx") or "", re.I))
                  and not UNI_RISK_RE.search(c.get("text") or "")]
        for c in copies[:3]:
            if time.time() > deadline:
                break
            if await uni_click(page, c):
                await page.wait_for_timeout(1200)
                await wiz_collect_dom(page, "pano (kopyala)")
        link, _ = wiz_best_ref()
        if link:
            break
        # Davet et / Paylaş: köprü taklidi linki yakalar, Telegram'da HİÇBİR ŞEY paylaşılmaz
        shares = [c for c in await uni_scan(page) if WIZ_SHARE_RE.search(c.get("text") or "")
                  and not UNI_RISK_RE.search(c.get("text") or "") and len(c.get("text") or "") <= 40]
        for c in shares[:2]:
            if time.time() > deadline:
                break
            if await uni_click(page, c):
                await page.wait_for_timeout(1500)
                await wiz_collect_dom(page, "davet butonu (paylaşılmadı)")
        link, _ = wiz_best_ref()
        if link:
            break
    if link:
        notes.append(f"Referans linki bulundu ({WIZ_CUR['refs'][link][1]}).")
    elif WIZ_CUR["codes"]:
        notes.append("Referans kodu benzeri alan bulundu: " + ", ".join(f"{k}={v}" for k, v in WIZ_CUR["codes"][:3]))


# ------------------------------------------------- yapay zeka ile görev ----

WIZ_STEP_PROMPT = (
    "Bir Telegram mini uygulamasının içindesin ve kullanıcının hesabında güvenli görevleri tamamlıyorsun.\n"
    "Aşağıda ekranın yazısı, tıklanabilir öğeler (id [tür] yazı — bağlam) ve yazı kutuları var.\n"
    "Görevin: ekrandaki cümleleri OKU, ANLA ve ödül kazandıran SIRADAKİ TEK güvenli adımı seç.\n"
    "Öncelik: açık pencereyi kapat/onayla > ödül topla (Claim/Collect/Daily/Check-in/Farm) > "
    "görev başlat (Join/Subscribe/Visit/Watch/Play) > görev doğrula (Check/Verify) > görev sekmesine git.\n"
    "Bir görev 'gizli kod / secret code / keyword' istiyorsa ve kod ekranda/metinde açıkça yazıyorsa "
    "'yaz' eylemiyle o kutuya yaz. Kodu TAHMİN ETME.\n"
    "YASAK: cüzdan, ödeme, Stars, TON, satın alma, yükseltme için para, davet/arkadaş, paylaş/hikaye, "
    "telefon, e-posta. 'Denendi' listesindeki işe yaramamış öğeleri tekrar seçme.\n"
    "Yapacak güvenli bir şey kalmadıysa eylem='bitir' de; bir görevi yapamıyorsan 'sorun' alanına "
    "nedenini Türkçe yaz (ör: 'X görevi Twitter hesabı istiyor').\n"
    "SADECE şu JSON'u döndür:\n"
    '{"ekran":"ekranın 1 cümle Türkçe özeti","eylem":"tikla|yaz|kaydir|geri|bitir",'
    '"id":"u12 veya w1","metin":"yaz eylemi için","neden":"kısa","sorun":""}\n\n'
)


async def wiz_ai_explore(page, name: str, notes: list, state: dict):
    """Kural motorundan sonra Groq ile ekranı okuyup kalan görevleri yapmayı dener."""
    if not (V8_AP.get("wiz_ai") and GROQ_API_KEY and WIZ_AI_STEPS > 0):
        return
    state["stage"] = "sihirbaz_ai"
    run = state.get("uni_run") or {"clicked": {}, "actions": 0, "log": [], "gains": [], "joined": set(),
                                   "join_ok": 0, "bot_seen": set(), "visited": [], "risky": set(),
                                   "blocked": set(), "navs": {}, "navq": []}
    deadline = time.time() + WIZ_AI_BUDGET_S
    history, tried_bad, idle = [], {}, 0
    written = set()
    start_text = await uni_screen(page)
    for step in range(1, WIZ_AI_STEPS + 1):
        if time.time() > deadline or AUTO_STOP:
            break
        cands = await uni_scan(page)
        try:
            inputs = await page.evaluate("() => window.__uni && window.__uni.inputs ? window.__uni.inputs() : []") or []
        except Exception:
            inputs = []
        allowed, lines = {}, []
        cands.sort(key=lambda c: (not c.get("overlay"), c["y"]))
        for c in cands:
            k = uni_classify(c) or "diğer"
            if k in ("risk", "skip"):
                continue
            t = (c.get("text") or "").strip()
            if UNI_RISK_RE.search(t) or WIZ_REF_NAV_RE.search(t) and k not in ("reward", "check"):
                continue
            if tried_bad.get(uni_norm(t), 0) >= 2:
                continue
            allowed[c["id"]] = c
            ctx = (c.get("ctx") or "")[:70].replace("\n", " ")
            flag = " (pencere)" if c.get("overlay") else (" (alt menü)" if c.get("navbar") else "")
            lines.append(f'{c["id"]} [{k}]{flag} "{t[:50]}" — {ctx}')
            if len(lines) >= 45:
                break
        in_lines, in_ok = [], {}
        for i in inputs:
            if i.get("ro") or WIZ_RISK_INPUT_RE.search((i.get("ph") or "") + " " + (i.get("ctx") or "")):
                continue
            in_ok[i["id"]] = i
            in_lines.append(f'{i["id"]} [yazı kutusu] ipucu="{i.get("ph", "")}" — {i.get("ctx", "")[:90]}')
        if not allowed and not in_ok:
            break
        screen = await uni_screen(page)
        scr = " | ".join([ln.strip() for ln in screen.splitlines() if ln.strip()])[:2000]
        hist = "\n".join(history[-8:]) or "(yok)"
        bad = ", ".join(list(tried_bad)[:12]) or "(yok)"
        prompt = (WIZ_STEP_PROMPT + f"UYGULAMA: @{name}\nADIM: {step}/{WIZ_AI_STEPS}\n\nEKRAN YAZISI:\n{scr}\n\n"
                  f"TIKLANABİLİR ÖĞELER:\n" + "\n".join(lines) +
                  (("\n\nYAZI KUTULARI:\n" + "\n".join(in_lines)) if in_lines else "") +
                  f"\n\nÖNCEKİ ADIMLAR:\n{hist}\n\nDENENDİ, İŞE YARAMADI: {bad}")
        raw, model = await groq_chat([{"role": "system", "content": WIZ_SYSTEM},
                                      {"role": "user", "content": prompt}], json_mode=True, max_tokens=300)
        dec = wiz_json(raw)
        if not dec:
            WIZ_CUR["ai_issues"].append(f"Yapay zeka cevap vermedi ({model})")
            break
        WIZ_CUR["ai_steps"] += 1
        act = str(dec.get("eylem") or "").lower().strip()
        sorun = str(dec.get("sorun") or "").strip()
        if sorun and sorun not in WIZ_CUR["ai_issues"] and len(WIZ_CUR["ai_issues"]) < 10:
            WIZ_CUR["ai_issues"].append(sorun[:200])
        if act in ("bitir", "done", "finish", ""):
            history.append(f"{step}. bitir: {str(dec.get('neden') or '')[:80]}")
            break
        before = screen
        did, label = False, ""
        if act in ("tikla", "tıkla", "click"):
            c = allowed.get(str(dec.get("id") or "").strip())
            if not c:
                history.append(f"{step}. geçersiz id seçildi ({dec.get('id')}) — listeden seç")
                idle += 1
                if idle >= 3:
                    break
                continue
            label = c["text"][:40]
            did = await uni_click(page, c)
        elif act == "yaz":
            i = in_ok.get(str(dec.get("id") or "").strip())
            val = str(dec.get("metin") or "").strip()
            if not i or not val or len(val) > 40 or WIZ_RISK_INPUT_RE.search(val) or UNI_RISK_RE.search(val):
                history.append(f"{step}. yazma reddedildi (güvenli değil / geçersiz)")
                idle += 1
                continue
            wkey = (uni_norm(i.get("ph") or "") + "|" + uni_norm(i.get("ctx") or "")[:60], val)
            if wkey in written:
                history.append(f"{step}. '{val}' bu kutuya ZATEN yazıldı — şimdi yanındaki gönder/onayla/check butonuna bas")
                idle += 1
                if idle >= 3:
                    break
                continue
            written.add(wkey)
            try:
                await page.locator(f'[data-wiz="{i["id"]}"]').fill(val, timeout=4000)
                did, label = True, f"{val} yazıldı"
            except Exception:
                WIZ_CUR["fails"].append(f"'{i.get('ph') or 'kutu'}' kutusuna yazılamadı")
        elif act in ("kaydir", "kaydır", "scroll"):
            try:
                await page.mouse.wheel(0, 650)
                await page.evaluate("() => { const el = [...document.querySelectorAll('*')].filter(e => e.scrollHeight > e.clientHeight + 40 && /auto|scroll/.test(getComputedStyle(e).overflowY)).sort((a, b) => b.clientHeight - a.clientHeight)[0]; if (el) el.scrollBy(0, 650); else window.scrollBy(0, 650); }")
                did, label = True, "aşağı kaydırıldı"
            except Exception:
                pass
        elif act in ("geri", "back"):
            try:
                fired = await page.evaluate("() => window.__uni && window.__uni.fire ? window.__uni.fire('back_button_pressed', {}) : false")
                if not fired:
                    await page.go_back(timeout=5000)
                did, label = True, "geri"
            except Exception:
                pass
        if not did:
            tried_bad[uni_norm(label or str(dec.get("id")))] = tried_bad.get(uni_norm(label or str(dec.get("id"))), 0) + 1
            history.append(f"{step}. {act} {label} → yapılamadı")
            idle += 1
            if idle >= 3:
                break
            continue
        run["actions"] = run.get("actions", 0) + 1
        run["log"].append(f"AI/{act}: {label[:30]}")
        await page.wait_for_timeout(2600)
        try:
            await uni_handle_links(page, name, run, notes)
        except Exception:
            pass
        after = await uni_screen(page)
        gained = uni_gain(before, after)
        diff = uni_diff(before, after)
        changed = uni_norm(before)[:1500] != uni_norm(after)[:1500]
        if gained and diff:
            WIZ_CUR["ai_gain"].extend(diff[:2])
        res = ("kazanç: " + ", ".join(diff[:2])) if gained and diff else ("ekran değişti" if changed else "değişmedi")
        history.append(f"{step}. {act} '{label}' → {res} ({str(dec.get('neden') or '')[:60]})")
        WIZ_CUR["ai_log"].append(f"{act} '{label}' → {res}")
        if act == "yaz":
            idle = 0  # yazmak tek başına ekranı değiştirmez; sıradaki adım gönder/onayla olur
        elif not changed:
            tried_bad[uni_norm(label)] = tried_bad.get(uni_norm(label), 0) + 1
            idle += 1
            if idle >= 3:
                break
        else:
            idle = 0
    if WIZ_CUR["ai_log"]:
        notes.append(f"Sihirbaz (yapay zeka) {len(WIZ_CUR['ai_log'])} adım: " + " · ".join(WIZ_CUR["ai_log"][:12])[:1200])
    end_text = await uni_screen(page)
    if WIZ_CUR["ai_gain"] or uni_gain(start_text, end_text):
        notes.append("Evrensel sonuç: OK")


# --------------------------------------------------------- tarayıcı ----

# ------------------------------------------- canvas oyunları (görüntü) ----
# Unity/Phaser gibi oyunlarda butonlar HTML değil, resim içinde. Bu modda ekran görüntüsü
# Groq'un görüntü okuyabilen modeline gönderilir; model nereye dokunulacağını söyler.

WIZ_CHROME_ARGS = ["--disable-dev-shm-usage", "--disable-gpu", "--disable-extensions", "--mute-audio",
                   "--no-first-run", "--renderer-process-limit=1", "--disable-background-networking",
                   "--disable-site-isolation-trials", "--disable-features=site-per-process,IsolateOrigins,Translate",
                   "--disable-software-rasterizer", "--disable-breakpad", "--no-zygote",
                   "--js-flags=--max-old-space-size=" + (os.getenv("WIZ_JS_HEAP_MB", "256") or "256")]
if os.getenv("WIZ_CHROME_SINGLE", "").strip() in ("1", "true", "evet"):
    WIZ_CHROME_ARGS.append("--single-process")   # ~30 MB daha az bellek, biraz daha kararsız

WIZ_VISION_MODELS = [m.strip() for m in (os.getenv("WIZ_VISION_MODEL", "qwen/qwen3.8-27b") or "").split(",") if m.strip()]
WIZ_CANVAS_STEPS = int(os.getenv("WIZ_CANVAS_STEPS", "8") or 8)
WIZ_CANVAS_BUDGET_S = int(os.getenv("WIZ_CANVAS_BUDGET_S", "180") or 180)

WIZ_CANVAS_PROMPT = (
    "Bu bir Telegram mini oyununun ekran görüntüsü ({w}x{h} piksel). Butonlar resmin içinde.\n"
    "Görevin: ekrandaki yazıları OKU, oyunu ANLA ve ödül kazandıran SIRADAKİ TEK güvenli dokunuşu seç.\n"
    "Öncelik: açık pencereyi kapat/onayla (OK, Close, X, Continue, Got it) > ödül topla (Claim, Collect, Daily, "
    "Free, Check-in) > görev/oyna (Play, Start, Tap, Tasks) > bitir.\n"
    "YASAK: cüzdan, Connect Wallet, ödeme, Stars, TON, satın alma (Buy, Shop, fiyatlı butonlar), davet/arkadaş, paylaş.\n"
    "Daha önce işe yaramayan noktalar: {bad}\nÖnceki adımlar: {hist}\n"
    "SADECE şu JSON'u döndür:\n"
    '{{"ekran":"ekranın 1-2 cümle Türkçe açıklaması","yazilar":"ekranda okuduğun önemli yazılar/sayılar",'
    '"bakiye":"ana bakiye sayısı ya da boş","eylem":"dokun|bitir","x":0,"y":0,"buton":"dokunulacak butonun yazısı",'
    '"neden":"kısa","sorun":""}}'
)


def _wiz_num(v):
    try:
        return float(re.sub(r"[^0-9.]", "", str(v).replace(",", "")) or "x")
    except ValueError:
        return None


async def wiz_canvas_explore(page, name: str, notes: list, state: dict):
    if not (V8_AP.get("wiz_ai") and GROQ_API_KEY and WIZ_CANVAS_STEPS > 0 and WIZ_VISION_MODELS):
        return False
    state["stage"] = "sihirbaz_canvas"
    import base64
    vp = page.viewport_size or {"width": 390, "height": 844}
    w, h = int(vp["width"]), int(vp["height"])
    deadline = time.time() + WIZ_CANVAS_BUDGET_S
    hist, bad, log = [], [], []
    first_bal, last_bal, idle = None, None, 0
    prev_shot = b""
    for step in range(1, WIZ_CANVAS_STEPS + 1):
        if time.time() > deadline or AUTO_STOP:
            break
        try:
            shot = await page.screenshot(type="jpeg", quality=55, timeout=10000)
        except Exception as e:
            WIZ_CUR["ai_issues"].append(f"Oyun ekranının görüntüsü alınamadı ({type(e).__name__})")
            break
        prompt = WIZ_CANVAS_PROMPT.format(w=w, h=h, bad=", ".join(bad[-6:]) or "(yok)",
                                          hist=" | ".join(hist[-5:]) or "(yok)")
        msg = [{"role": "system", "content": WIZ_SYSTEM},
               {"role": "user", "content": [
                   {"type": "text", "text": prompt},
                   {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(shot).decode()}}]}]
        raw, model = await groq_chat(msg, json_mode=True, max_tokens=400, gemini=False, models=WIZ_VISION_MODELS)
        dec = wiz_json(raw)
        if not dec:
            WIZ_CUR["ai_issues"].append(f"Görüntü okuyan yapay zeka cevap vermedi ({model})")
            break
        WIZ_CUR["ai_steps"] += 1
        desc = (str(dec.get("ekran") or "") + " " + str(dec.get("yazilar") or "")).strip()
        if desc and len(WIZ_CUR["screens"]) < 30:
            WIZ_CUR["screens"].append("[oyun ekranı, görüntüden okundu] " + desc[:500])
        bal = _wiz_num(dec.get("bakiye"))
        if bal is not None:
            first_bal = bal if first_bal is None else first_bal
            last_bal = bal
        sorun = str(dec.get("sorun") or "").strip()
        if sorun and sorun not in WIZ_CUR["ai_issues"] and len(WIZ_CUR["ai_issues"]) < 10:
            WIZ_CUR["ai_issues"].append(sorun[:200])
        act = str(dec.get("eylem") or "").lower()
        btn = str(dec.get("buton") or "")[:40]
        if act not in ("dokun", "tikla", "tıkla", "click", "tap"):
            break
        if UNI_RISK_RE.search(btn) or WIZ_REF_NAV_RE.search(btn):
            hist.append(f"{step}. '{btn}' güvenlik nedeniyle reddedildi")
            bad.append(btn)
            WIZ_CUR["fails"].append(f"Güvenlik için basılmadı (oyun içi): {btn}")
            idle += 1
            if idle >= 3:
                break
            continue
        x, y = _wiz_num(dec.get("x")), _wiz_num(dec.get("y"))
        if x is None or y is None or not (0 < x < w and 0 < y < h):
            hist.append(f"{step}. geçersiz koordinat ({dec.get('x')},{dec.get('y')})")
            idle += 1
            if idle >= 3:
                break
            continue
        try:
            await page.mouse.click(x, y)
        except Exception:
            try:
                await page.touchscreen.tap(x, y)
            except Exception:
                pass
        await page.wait_for_timeout(2500)
        try:
            after = await page.screenshot(type="jpeg", quality=55, timeout=10000)
        except Exception:
            after = b""
        changed = after != shot and after != prev_shot
        prev_shot = shot
        res = "ekran değişti" if changed else "değişmedi"
        hist.append(f"{step}. dokun '{btn}' ({int(x)},{int(y)}) → {res}")
        log.append(f"'{btn or f'{int(x)},{int(y)}'}' → {res}")
        if changed:
            idle = 0
        else:
            bad.append(f"{btn} ({int(x)},{int(y)})")
            idle += 1
            if idle >= 3:
                break
    if log:
        notes.append(f"Sihirbaz (görüntü ile canvas oyunu) {len(log)} dokunuş: " + " · ".join(log[:10])[:900])
        WIZ_CUR.setdefault("cv_log", []).extend(log)
    if first_bal is not None and last_bal is not None and last_bal > first_bal:
        notes.append(f"Ekrandaki değişim: Bakiye (görüntüden): {first_bal:g} → {last_bal:g}")
        WIZ_CUR.setdefault("cv_gain", []).append(f"Bakiye {first_bal:g} → {last_bal:g}")
        notes.append("Evrensel sonuç: OK")
        return True
    return bool(log)


class _WizRetry(Exception):
    pass


async def v8_browser(name, url, state, _retry: bool = False):
    """DÜZELTME: sayfa hata verirse / boş gelirse bozuk kayıtlı oturumu silip temiz oturumla 1 kez daha dener."""
    if WIZ_LIVE.get("bot") == name:
        WIZ_LIVE["state"] = state
    try:
        return await _wiz_browser_once(name, url, state, _retry)
    except _WizRetry as r:
        try:
            os.remove(uni_state_path(name))
        except Exception:
            pass
        if _retry:
            return [f"{r}; temiz oturumla da açılamadı, işlem yapılmadı."]
        if WIZ_CUR:
            WIZ_CUR["fails"].append(f"İlk açılışta sorun ({r}); kayıtlı oturum silinip yeniden denendi")
        return await v8_browser(name, url, state, _retry=True)


async def _wiz_browser_once(name, url, state, _retry: bool = False):
    from playwright.async_api import async_playwright, TimeoutError as PWTimeout
    if not await v8_public(url):
        return ["Adres guvenlik kontrolunden gecmedi."]
    notes = []
    retry_needed = False
    async with async_playwright() as p:
        state["stage"] = "chromium_baslatma"
        browser = await p.chromium.launch(headless=True, timeout=60000, args=WIZ_CHROME_ARGS)
        context = None
        try:
            context = await uni_new_context(browser, name)
            await context.add_init_script(UNI_SHIM_JS)
            await context.add_init_script(WIZ_SHIM_JS)
            cache = {}
            nav_links = []

            async def guard(route):
                req = route.request
                u = req.url
                host = urlparse(u).netloc
                try:
                    if req.is_navigation_request() and uni_tme_from_nav(u):
                        nav_links.append(u)
                        if WIZ_CUR:
                            wiz_add_refs(u, "yönlendirme")
                        await route.abort()
                        return
                    if WIZ_LITE.get("on") and (req.resource_type in ("image", "media", "font") or WIZ_HEAVY_RE.search(u)):
                        await route.abort()   # hafif mod: belleği dolduran dosyalar yüklenmez
                        return
                    if host not in cache:
                        cache[host] = await v8_public(u)
                    if cache[host] and urlparse(u).scheme == "https":
                        await route.continue_()
                    else:
                        await route.abort()
                except Exception:
                    try:
                        await route.abort()
                    except Exception:
                        pass

            await context.route("**/*", guard)
            page = await context.new_page()
            page.set_default_timeout(10000)
            if WIZ_CUR:
                wiz_attach_network(page)
            state["stage"] = "sayfa_acilisi"
            try:
                response = await page.goto(url, wait_until="domcontentloaded", timeout=60000)
                if response and response.status >= 400:
                    retry_needed = True
                    raise _WizRetry(f"HTTP {response.status}")
            except PWTimeout:
                notes.append("Acilis suresi asildi; yuklenen ekran kontrol ediliyor.")
            await page.locator("body").wait_for(state="attached", timeout=15000)
            try:
                await page.wait_for_load_state("networkidle", timeout=12000)
            except Exception:
                pass
            await page.wait_for_timeout(3000)
            first = await uni_screen(page)
            if not first.strip() and not _retry:
                # boş ekran: bozuk kayıtlı oturum olabilir → temiz oturumla bir kez daha
                await page.wait_for_timeout(5000)
                first = await uni_screen(page)
                try:
                    has_cv = await page.evaluate("() => !!document.querySelector('canvas')")
                except Exception:
                    has_cv = False
                if not first.strip() and has_cv:
                    # DÜZELTME: canvas oyunlarında yazı olmaz; boş sanılıp oturum silinmez, yüklenmesi beklenir
                    await page.wait_for_timeout(8000)
                elif not first.strip():
                    retry_needed = True
                    raise _WizRetry("ekran boş geldi")
            notes.append("Sayfa açıldı (Telegram köprüsü taklidi aktif)." + (" [temiz oturum]" if _retry else ""))
            low = name.lower()
            if low in ("pickaxeempirebot", "pickaxe_empire_bot"):
                notes.append("Pickaxe Empire özel profili seçildi.")
                notes = await v8_pickaxe_flow(page, name, notes, state)
                if UNI_AFTER_PROFILE:
                    state["nav_links"] = nav_links
                    notes.append("— Kalan görevler için evrensel motor —")
                    notes = await uni_flow(page, name, notes, state)
            elif low == "myageapp":
                notes = await v8_myage_page_flow(page, name, notes, state)
                if UNI_AFTER_PROFILE:
                    state["nav_links"] = nav_links
                    notes.append("— Kalan görevler için evrensel motor (Spin / Achievements / Tasks) —")
                    notes = await uni_flow(page, name, notes, state)
            else:
                state["nav_links"] = nav_links
                notes = await uni_flow(page, name, notes, state)
            # ---- sihirbaz: yapay zeka + referans ----
            if V8_AP.get("wiz_on") and WIZ_CUR:
                try:
                    is_canvas = await page.evaluate("() => window.__uni && window.__uni.hasCanvas ? window.__uni.hasCanvas() : false")
                except Exception:
                    is_canvas = False
                if is_canvas:
                    try:
                        did_cv = await asyncio.wait_for(wiz_canvas_explore(page, name, notes, state), WIZ_CANVAS_BUDGET_S + 60)
                        if not did_cv:
                            WIZ_CUR["fails"].append("Canvas oyununda görüntüden güvenli bir dokunuş bulunamadı")
                    except asyncio.TimeoutError:
                        WIZ_CUR["ai_issues"].append("Canvas oyunu adımları süre sınırına takıldı")
                    except Exception as e:
                        WIZ_CUR["ai_issues"].append(f"Canvas oyunu adımı hata verdi: {type(e).__name__}")
                try:
                    await asyncio.wait_for(wiz_ai_explore(page, name, notes, state), WIZ_AI_BUDGET_S + 60)
                except asyncio.TimeoutError:
                    WIZ_CUR["ai_issues"].append("Yapay zeka adımları süre sınırına takıldı")
                except Exception as e:
                    WIZ_CUR["ai_issues"].append(f"Yapay zeka adımı hata verdi: {type(e).__name__}")
                state["stage"] = "sihirbaz_ref"
                try:
                    await asyncio.wait_for(wiz_ref_hunt(page, name, notes, state), WIZ_REF_BUDGET_S + 30)
                except Exception as e:
                    print("[WIZ REF]", repr(e), flush=True)
                run = state.get("uni_run") or {}
                for sg, st in (run.get("task_sig") or {}).items():
                    if not st.get("eff") and len(WIZ_CUR["fails"]) < 20:
                        WIZ_CUR["fails"].append(f"Görev satırına basıldı ama bir şey açılmadı: {sg[:60]}")
                for r_ in list(run.get("risky") or [])[:6]:
                    WIZ_CUR["fails"].append(f"Güvenlik için basılmadı: {r_}")
            return notes
        finally:
            if context is not None and not retry_needed:
                await uni_save_state(context, name)
            try:
                await asyncio.wait_for(browser.close(), 15)
            except Exception:
                pass
    return notes


# ------------------------------------------------- özet + referans çıktısı ----

WIZ_SUM_PROMPT = (
    "Aşağıda bir Telegram mini uygulamasında botun gezdiği ekranların yazıları, yaptığı işlemlerin logu "
    "ve yapamadığı şeyler var. Bunları OKU ve kullanıcı için TÜRKÇE bir özet yaz. SADECE verilen "
    "bilgiyi kullan, uydurma. Tam olarak şu formatta yaz (başlıkları koru):\n"
    "🎮 Uygulama: <ad> — <1 cümle ne olduğu>\n"
    "📌 Nasıl çalışıyor: <2-3 cümle: tap/farm/görev/puan/token mantığı>\n"
    "✅ Bu turda yaptıklarım:\n- ... (SADECE İŞLEM LOGU'nda geçen eylemler; ekranda 'Completed/Done/✓' yazan "
    "görevleri buraya YAZMA)\n"
    "📋 Zaten yapılmış görünenler:\n- ... (ekranda tamamlandı yazanlar; yoksa '- yok')\n"
    "❗ Yapamadıklarım ve nedeni:\n- ... (yoksa '- yok')\n"
    "👉 Senin elle yapman gerekenler:\n- ... (yoksa '- yok')\n"
    "💰 Token / airdrop: <ekranda geçen bilgi, yoksa 'belirsiz'>\n"
    "⭐ Değerlendirme: <1 cümle: devam etmeye değer mi, dikkat edilecek risk>\n"
    "Sayı azaldıysa (ör. 7.16 → 1.42) bunu kazanç diye yazma. Liste satırları tek '- ' ile başlasın.\n"
    "En fazla 1500 karakter.\n\n"
)


def wiz_fallback_summary(name: str, outcome: str, notes: list) -> str:
    fails = WIZ_CUR.get("fails", []) + WIZ_CUR.get("ai_issues", [])
    scr = (WIZ_CUR.get("screens") or [""])[0][:300]
    out = [f"🎮 Uygulama: @{name}", "📌 Ekran: " + (scr or "okunamadı"),
           "✅ Sonuç: " + uni_short_line(name, outcome, notes).split(" — ", 1)[-1]]
    out.append("❗ Yapamadıklarım:\n" + ("\n".join("- " + f for f in fails[:8]) if fails else "- yok"))
    prob = uni_problem_tr(notes)
    if prob:
        out.append("⚠️ Sorun: " + prob)
    out.append("(Yapay zeka özeti alınamadı; kural tabanlı özet.)")
    return "\n".join(out)


async def wiz_make_summary(name: str, outcome: str, notes: list) -> str:
    if not GROQ_API_KEY and not GEMINI_API_KEY:
        return wiz_fallback_summary(name, outcome, notes)
    screens = "\n---\n".join(WIZ_CUR.get("screens", [])[:14])[:6000]
    log = "\n".join(notes)[-3000:]
    fails = "\n".join("- " + f for f in (WIZ_CUR.get("fails", []) + WIZ_CUR.get("ai_issues", []))[:15]) or "- yok"
    prob = uni_problem_tr(notes) or "yok"
    prompt = (WIZ_SUM_PROMPT + f"UYGULAMA: @{name}\nSONUÇ KODU: {outcome}\nGENEL SORUN: {prob}\n\n"
              f"EKRAN YAZILARI:\n{screens or '(okunamadı)'}\n\nİŞLEM LOGU:\n{log}\n\nYAPAMADIKLARI:\n{fails}")
    raw, model = await groq_chat([{"role": "system", "content": WIZ_SYSTEM},
                                  {"role": "user", "content": prompt}], max_tokens=900)
    if not raw:
        return wiz_fallback_summary(name, outcome, notes)
    raw = re.sub(r"(?m)^(\s*)[-•*]\s*[-•*]\s+", r"\1- ", raw.strip())  # "- - yok" → "- yok"
    return raw[:2200]


async def wiz_ref_from_chat(name: str):
    """Mini app'te bulunamazsa bot sohbetindeki davet menüsüne bakar."""
    try:
        ent = await asyncio.wait_for(resolve_entity(name), 20)
        if not await try_lock(TG_LOCK, 20):
            return None
        try:
            links = await asyncio.wait_for(ref_from_chat(ent, name), 45)
        finally:
            TG_LOCK.release()
        for l in links or []:
            wiz_add_refs(l, "bot sohbeti")
    except Exception as e:
        print("[WIZ REF CHAT]", repr(e), flush=True)
    return wiz_best_ref()[0]


async def wiz_finish(name: str, outcome: str, notes: list, source: str):
    """Özet + referans linkini hazırlar, kaydeder, gerektiğinde gönderir."""
    if not V8_AP.get("wiz_on"):
        return
    text_all = "\n".join(notes)
    opened = "Sayfa açıldı" in text_all or bool(WIZ_CUR.get("screens"))
    link, src = wiz_best_ref()
    if not link and opened:
        link = await wiz_ref_from_chat(name)
        src = WIZ_CUR["refs"][link][1] if link and link in WIZ_CUR.get("refs", {}) else src
    saved = REFS.get(name) or {}
    if link and saved.get("src") != "elle":
        if saved.get("link") != link:
            REFS[name] = {"link": link, "src": f"sihirbaz/{src}", "t": time.time()}
            await persist_refs()
    final_ref = (REFS.get(name) or {}).get("link") or link
    final_src = (REFS.get(name) or {}).get("src") or src

    prev = WIZ_SUM.get(name) or {}
    mode = V8_AP.get("wiz_ap_mode", "yeni") if source == "ap" else "her"
    problems = sorted(set(WIZ_CUR.get("fails", []) + WIZ_CUR.get("ai_issues", [])))
    send = mode == "her" or (mode == "yeni" and (
        not prev or time.time() - float(prev.get("t") or 0) > WIZ_RESEND_H * 3600
        or (final_ref and final_ref != prev.get("ref")) or set(problems) - set(prev.get("problems") or [])))
    if mode == "kapali":
        send = False
    summary = prev.get("summary", "")
    if not opened:
        # açılamadıysa Groq kotası harcanmaz, nedeni kısaca yazılır
        why = uni_problem_tr(notes) or "mini uygulama açılamadı"
        detail = next((n for n in notes if n.startswith("Açılamadı:")), "")[:500]
        summary = f"🎮 Uygulama: @{name}\n❗ Açılamadı: {why}"
        if "mini uygulama değil" in why:
            summary += "\n👉 Bu bir sohbet botu; otomatik yapılacak bir şey yok, istersen listeden çıkarabilirsin."
        elif detail:
            summary += "\n🔎 Ayrıntı: " + detail
    elif send or not prev:
        summary = await wiz_make_summary(name, outcome, notes)
    WIZ_SUM[name] = {"t": time.time(), "outcome": outcome, "summary": summary[:2200],
                     "ref": final_ref or "", "ref_src": final_src or "", "problems": problems[:15]}
    await wiz_persist()
    if not send:
        return
    if final_ref:
        ref_txt = f"🔗 Referans linkin ({final_src}):\n{final_ref}"
    else:
        codes = WIZ_CUR.get("codes") or []
        ref_txt = "🔗 Referans linki: bulunamadı."
        if codes:
            ref_txt += "\nBulunan kod benzeri alanlar: " + ", ".join(f"{k}={v}" for k, v in codes[:3])
        if not opened:
            ref_txt += "\n(Mini uygulama açılamadığı için aranamadı.)"
        ref_txt += f"\nUygulamada Davet ekranındaki linki kopyalayıp şunu yazarsan kaydederim:\nref {name} https://t.me/..."
    kb_rows = [[InlineKeyboardButton(f"🤖 @{name} aç"[:60], url=f"https://t.me/{name}")]]
    if final_ref and final_ref.startswith("https://t.me/"):
        kb_rows.append([InlineKeyboardButton("🔗 Referans linki", url=final_ref)])
    await wiz_send(f"🧙 SİHİRBAZ ÖZETİ — @{name}\n\n{summary}\n\n{ref_txt}", InlineKeyboardMarkup(kb_rows))


_wiz_run_and_track_base = v8_run_and_track
WIZ_RUN_LOCK = None
WIZ_QUEUE: list = []   # sırada bekleyen botlar
WIZ_LIVE: dict = {}    # şu an çalışan bot

WIZ_STAGE_NAMES = {
    "sirada": "sırada", "telegram_hedefi": "bot Telegram'da aranıyor", "telegram_kilidi": "Telegram sırası bekleniyor",
    "start_gonderme": "/start gönderiliyor", "mini_uygulama_kilidi": "mini uygulama sırası bekleniyor",
    "yetkili_adres_alma": "mini uygulama adresi alınıyor", "chromium_baslatma": "tarayıcı açılıyor",
    "sayfa_acilisi": "sayfa yükleniyor", "sihirbaz_ai": "yapay zeka görevleri yapıyor",
    "sihirbaz_canvas": "yapay zeka oyun ekranına bakıyor", "sihirbaz_ref": "referans linki aranıyor",
}


def wiz_queue_text() -> str:
    now = time.time()
    out = []
    if WIZ_LIVE.get("bot"):
        st = (WIZ_LIVE.get("state") or {}).get("stage", "") if isinstance(WIZ_LIVE.get("state"), dict) else ""
        if WIZ_CUR.get("bot") == WIZ_LIVE["bot"] and not st:
            st = "hazırlanıyor"
        st_tr = WIZ_STAGE_NAMES.get(st, st or "başlıyor")
        if st.startswith("uni_"):
            st_tr = "uygulama içinde görevler yapılıyor"
        el = int(now - WIZ_LIVE.get("t0", now))
        out.append(f"▶️ Şu an çalışan: @{WIZ_LIVE['bot']} — {el // 60} dk {el % 60} sn — aşama: {st_tr}"
                   f"\n   (bir bot en fazla ~{(V8_JOB_TIMEOUT + 150) // 60} dk sürebilir, sonra kendiliğinden kesilir)")
    else:
        out.append("▶️ Şu an çalışan bot yok.")
    if WIZ_QUEUE:
        out.append(f"⏳ Sırada {len(WIZ_QUEUE)} bot (tahmini {len(WIZ_QUEUE) * 2}–{len(WIZ_QUEUE) * 6} dk):")
        for i, it in enumerate(WIZ_QUEUE[:30], 1):
            src = " (otopilot)" if it.get("source") == "ap" else ""
            out.append(f"  {i}. @{it['bot']}{src} — {int((now - it['t']) // 60)} dk bekliyor")
        if len(WIZ_QUEUE) > 30:
            out.append(f"  … +{len(WIZ_QUEUE) - 30}")
    else:
        out.append("⏳ Sıra boş.")
    out.append("\nSıradan çıkarmak / durdurmak için: iptal botadi  ·  hepsini durdur: dur")
    return "\n".join(out)


async def v8_run_and_track(name="myageapp", short="", start="", source="manual"):
    """Eski tur + sihirbaz (ekran okuma, AI görev, referans, özet). Botlar sırayla, veriler karışmaz."""
    global WIZ_RUN_LOCK
    if WIZ_RUN_LOCK is None:
        WIZ_RUN_LOCK = asyncio.Lock()
    item = {"bot": name, "t": time.time(), "source": source}
    WIZ_QUEUE.append(item)
    try:
        await WIZ_RUN_LOCK.acquire()
    finally:
        if item in WIZ_QUEUE:
            WIZ_QUEUE.remove(item)
    try:
        waited = time.time() - item["t"]
        WIZ_LIVE.clear()
        WIZ_LIVE.update({"bot": name, "t0": time.time(), "source": source, "state": None})
        if waited > 20 and source != "ap":
            try:
                await bot_app.bot.send_message(
                    ADMIN_USER_ID, f"▶️ @{name} sırası geldi, şimdi çalışıyor ({int(waited // 60)} dk sırada bekledi).")
            except Exception:
                pass
        wiz_new_cur(name, start)
        try:
            await wiz_me_id()
            outcome, notes = await _wiz_run_and_track_base(name, short, start)
            try:
                await asyncio.wait_for(wiz_finish(name, outcome, notes, source), 150)
            except Exception as e:
                print("[WIZ FINISH]", repr(e), flush=True)
            return outcome, notes
        finally:
            WIZ_CUR.clear()
    finally:
        WIZ_LIVE.clear()
        WIZ_RUN_LOCK.release()


# ---------------------------------------------- düzeltilmiş yardımcılar ----

_wiz_do_join_base = do_join


async def do_join(target: str) -> str:
    """DÜZELTME: Telegram bekletirken (FloodWait) tekrar tekrar katılmayı denemez."""
    if FLOOD_UNTIL > time.time():
        return f"Telegram bekletiyor ({int((FLOOD_UNTIL - time.time()) / 60) + 1} dk), katılım sonraya bırakıldı."
    return await _wiz_do_join_base(target)


async def uni_dialog_usernames():
    """DÜZELTME: TÜM sohbetler okunur; okunamazsa None (silme kontrolü atlanır, bot yanlışlıkla engellenmez)."""
    try:
        names = set()

        async def collect():
            async for d in tg_client.iter_dialogs(limit=None):
                un = (getattr(d.entity, "username", None) or "").lower()
                if un:
                    names.add(un)
        await asyncio.wait_for(collect(), 90)
        return names if names else None
    except Exception as e:
        print(f"[V8] dialog listesi alınamadı: {type(e).__name__}", flush=True)
        return None


_wiz_short_line_base = uni_short_line


def uni_short_line(bot: str, outcome: str, notes: list) -> str:
    line = _wiz_short_line_base(bot, outcome, notes)
    ref = (REFS.get(bot) or {}).get("link")
    if ref:
        line += f"\n   🔗 {ref}"
    return line


async def v8_autopilot_loop():
    """DÜZELTME: 'dur' ile iş iptal edilince döngü artık ölmüyor; sonra 'otopilot aç' çalışır."""
    print("[V8 OTOPILOT] döngü hazır (kapalı başlar; 'otopilot aç' ile devreye girer)", flush=True)
    while True:
        try:
            if not V8_AP.get("on"):
                await asyncio.sleep(20)
                continue
            min_m = int(V8_AP.get("min_m") or 45)
            max_m = max(int(V8_AP.get("max_m") or 75), min_m)
            wait_s = random.randint(min_m * 60, max_m * 60)
            last = float(V8_AP.get("last") or 0)
            elapsed = time.time() - last
            if last > 0 and elapsed < wait_s:
                await asyncio.sleep(min(60, wait_s - elapsed))
                continue
            if any(not t.done() for t in V8_TASKS.values()):
                await asyncio.sleep(30)
                continue
            bots = v8_ap_bots()
            if not bots:
                await asyncio.sleep(300)
                continue
            await bot_app.bot.send_message(
                ADMIN_USER_ID,
                f"🔁 Otopilot turu başladı: {len(bots)} bot. Bitince tek mesajla özet atacağım.\n(Durdurmak için: dur)",
                disable_web_page_preview=True,
            )
            round_lines = []
            dialog_names = await uni_dialog_usernames()
            for bot in bots:
                if not V8_AP.get("on"):
                    break
                if uni_paused(bot):
                    round_lines.append(f"⏸ @{bot} — üst üste hata verdiği için bekletiliyor")
                    continue
                if dialog_names is not None and float(uni_per(bot).get("last") or 0) > 0 and bot not in dialog_names:
                    await uni_block_bot(bot)
                    round_lines.append(f"🗑 @{bot} — sohbeti silmişsin; listeden çıkarıldı, bir daha açılmayacak")
                    continue
                if any(not t.done() for t in V8_TASKS.values()):
                    await asyncio.sleep(20)
                V8_AP["bot"] = bot
                key = f"ap:{bot}"
                task = asyncio.create_task(v8_run_and_track(bot, source="ap"))
                V8_TASKS[key] = task
                try:
                    await asyncio.wait({task})  # iş iptal edilse bile döngü ayakta kalır
                finally:
                    V8_TASKS.pop(key, None)
                if task.cancelled():
                    round_lines.append(f"⏹ @{bot} — durduruldu")
                    break
                exc = task.exception()
                if exc:
                    outcome, notes = "err", [f"Hata: {type(exc).__name__}"]
                else:
                    outcome, notes = task.result()
                uni_track(bot, outcome)
                await persist_v8_ap()
                round_lines.append(uni_short_line(bot, outcome, notes))
                await asyncio.sleep(random.uniform(8, 20))
            wait_s = random.randint(min_m * 60, max_m * 60)
            await uni_send_round_summary(round_lines, wait_s)
            end = time.time() + wait_s
            while time.time() < end:
                if not V8_AP.get("on"):
                    break
                await asyncio.sleep(15)
        except asyncio.CancelledError:
            print("[V8 OTOPILOT] iptal", flush=True)
            raise
        except Exception as e:
            print("[V8 OTOPILOT HATA]", repr(e), flush=True)
            V8_AP["n_err"] = int(V8_AP.get("n_err") or 0) + 1
            V8_AP["last_note"] = f"döngü hata: {type(e).__name__}"
            try:
                await persist_v8_ap()
            except Exception:
                pass
            await asyncio.sleep(120)


# ------------------------------------------------------------ komutlar ----

WIZ_HELP = (
    "🧙 SİHİRBAZ KOMUTLARI\n"
    "• @botadi veya t.me linki — çalıştır + özet + referans linki\n"
    "• özet botadi — o mini app'in son özeti ve referans linki\n"
    "• özetler — tüm mini app'ler (tek satır + ref linki)\n"
    "• referanslar — kayıtlı tüm referans linklerin\n"
    "• ref botadi https://t.me/... — referans linkini elle kaydet\n"
    "• sor <soru> — yapay zekaya özetlere bakarak soru sor\n"
    "• sıra — şu an hangi bot çalışıyor, hangi aşamada, sırada kimler var\n"
    "• iptal botadi — o botu sıradan çıkar / durdur\n"
    "• devam — bot yeniden başladıysa sırada kalanları sürdür\n"
    "• bellek — sunucu bellek kullanımı ve ağır (hafif modda açılan) botlar\n"
    "• zorla botadi — sunucuyu çökerttiği için atlanan botu yine de dene\n"
    "• sihirbaz — durum  ·  sihirbaz aç / kapat\n"
    "• sihirbaz ai aç / kapat — yapay zekanın görev adımları\n"
    "• özet mod her | yeni | kapalı — otopilotta özet gönderimi\n"
)


def wiz_status_text() -> str:
    now = time.time()
    models = []
    for m in GROQ_CHAIN:
        if GROQ_STATE["dead"].get(m, 0) > now:
            s = "kullanılamıyor"
        elif GROQ_STATE["cool"].get(m, 0) > now:
            s = f"limit, {int((GROQ_STATE['cool'][m] - now) / 60) + 1} dk"
        else:
            s = "hazır"
        models.append(f"  - {m}: {s} ({GROQ_STATE['used'].get(m, 0)} istek)")
    return (
        f"🧙 Sihirbaz: {'AÇIK' if V8_AP.get('wiz_on') else 'KAPALI'}\n"
        f"Yapay zeka görev adımları: {'AÇIK' if V8_AP.get('wiz_ai') else 'KAPALI'} (en fazla {WIZ_AI_STEPS} adım)\n"
        f"Otopilotta özet: {V8_AP.get('wiz_ap_mode', 'yeni')}\n"
        f"Groq: {'anahtar var' if GROQ_API_KEY else 'ANAHTAR YOK'} · Gemini yedek: {'var' if GEMINI_API_KEY else 'yok'}\n"
        f"Model zinciri:\n" + "\n".join(models) + "\n"
        f"Kayıtlı özet: {len(WIZ_SUM)} · Referans linki: {len(REFS)}\n\n" + WIZ_HELP
    )


_wiz_on_text_base = on_text


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user, msg = update.effective_user, update.effective_message
    if not user or not msg or user.id != ADMIN_USER_ID or update.effective_chat.type != "private":
        return await _wiz_on_text_base(update, context)
    text = (msg.text or msg.caption or "").strip()
    low = text.lower().replace("ı", "i").replace("ö", "o").replace("ü", "u").replace("ş", "s").replace("ç", "c").replace("ğ", "g")
    try:
        age = time.time() - msg.date.timestamp()
    except Exception:
        age = 0
    if age > WIZ_MSG_MAX_AGE:
        print(f"[MSG] {int(age // 60)} dk eski mesaj yok sayıldı: {text[:40]}", flush=True)
        return
    if low in {"dur", "durdur"}:
        await v8_stop()
        return
    if await wiz_day_cmd(msg, text, low):
        return
    if await wiz_post_cmd(msg, text, low):
        return
    if low in {"bellek", "ram", "hafiza"}:
        hv = {**(WIZ_JOURNAL.get("crash") or {}), **(WIZ_JOURNAL.get("heavy") or {}), **(WIZ_JOURNAL.get("lite") or {})}
        await msg.reply_text(
            f"🧠 Bellek: {wiz_mem_used_mb()} MB / {wiz_mem_limit_mb()} MB "
            f"(tarayıcı {int(wiz_mem_limit_mb() * WIZ_MEM_KILL_PCT)} MB'ta kapatılır)\n"
            f"Son mini app tepe kullanımı: {WIZ_MEM['peak']} MB\n"
            "Ağır (hafif modda açılan) botlar: " + (", ".join(f"@{b}" for b in hv) or "yok"))
        return
    if low in {"devam", "surdur"}:
        await wiz_resume()
        return
    if low.startswith("zorla "):
        bn = text.split(None, 1)[1].strip().lstrip("@").lower()
        bn = re.sub(r"^https?://t\.me/", "", bn).split("/")[0].split("?")[0]
        await wiz_force(bn)
        return
    if low in {"sihirbaz", "sihirbaz durum", "wizard"}:
        await wiz_send(wiz_status_text())
        return
    if low in {"sira", "durum", "kuyruk", "ne yapiyor", "neredesin"}:
        await wiz_send(wiz_queue_text())
        return
    if low.startswith("iptal "):
        bn = text.split(None, 1)[1].strip().lstrip("@").lower()
        bn = re.sub(r"^https?://t\.me/", "", bn).split("/")[0].split("?")[0]
        t = V8_TASKS.get(bn)
        if t and not t.done():
            t.cancel()
            await msg.reply_text(f"@{bn} sıradan çıkarıldı / durduruldu.")
        else:
            await msg.reply_text(f"@{bn} sırada ya da çalışırken bulunamadı. Sırayı görmek için: sıra")
        return
    if low in {"sihirbaz ac", "sihirbaz on"}:
        V8_AP["wiz_on"] = True
        await persist_v8_ap()
        await msg.reply_text("🧙 Sihirbaz AÇIK: her mini app için özet + referans linki gelecek.")
        return
    if low in {"sihirbaz kapat", "sihirbaz off"}:
        V8_AP["wiz_on"] = False
        await persist_v8_ap()
        await msg.reply_text("Sihirbaz KAPALI (eski V8 davranışı).")
        return
    if low in {"sihirbaz ai ac", "sihirbaz ai on", "ai ac"}:
        V8_AP["wiz_ai"] = True
        await persist_v8_ap()
        await msg.reply_text("Yapay zeka görev adımları AÇIK.")
        return
    if low in {"sihirbaz ai kapat", "sihirbaz ai off", "ai kapat"}:
        V8_AP["wiz_ai"] = False
        await persist_v8_ap()
        await msg.reply_text("Yapay zeka görev adımları KAPALI (sadece kural motoru + özet + referans).")
        return
    if low.startswith("ozet mod"):
        m = low.split()[-1]
        m = {"her": "her", "hepsi": "her", "yeni": "yeni", "kapali": "kapali", "kapat": "kapali"}.get(m)
        if not m:
            await msg.reply_text("Kullanım: özet mod her | yeni | kapalı")
            return
        V8_AP["wiz_ap_mode"] = m
        await persist_v8_ap()
        await msg.reply_text({"her": "Otopilotta her bot için her turda özet gelecek.",
                              "yeni": f"Otopilotta özet: ilk kez, yeni referans/sorun çıkınca ya da {WIZ_RESEND_H} saatte bir.",
                              "kapali": "Otopilotta özet gönderilmeyecek (özet: botadi ile bakabilirsin)."}[m])
        return
    if low in {"ozetler", "ozet liste", "ozet hepsi"}:
        if not WIZ_SUM:
            await msg.reply_text("Henüz özet yok. Bir bot adı / t.me linki gönder ya da 'otopilot aç' yaz.")
            return
        icon = {"ok": "✅", "skip": "➖", "err": "❌"}
        lines = [f"🧙 Mini app özetleri ({len(WIZ_SUM)}):"]
        for b, v in sorted(WIZ_SUM.items(), key=lambda kv: -float(kv[1].get("t") or 0)):
            first = next((ln for ln in (v.get("summary") or "").splitlines() if ln.strip()), "")[:110]
            lines.append(f"\n{icon.get(v.get('outcome'), '•')} @{b} — {first}")
            lines.append(f"   🔗 {v.get('ref') or (REFS.get(b) or {}).get('link') or 'referans yok'}")
        await wiz_send("\n".join(lines) + "\n\nAyrıntı: özet botadi")
        return
    if low.startswith("ozet "):
        nm = parse_bot_arg(text.split(None, 1)[1]) or text.split(None, 1)[1].strip().lstrip("@").lower()
        v = WIZ_SUM.get(nm)
        if not v:
            await msg.reply_text(f"@{nm} için özet yok. Önce @{nm} gönderip çalıştır.")
            return
        ago = int((time.time() - float(v.get("t") or 0)) / 60)
        ref = v.get("ref") or (REFS.get(nm) or {}).get("link")
        await wiz_send(f"🧙 @{nm} — {ago} dk önceki özet\n\n{v.get('summary')}\n\n"
                       f"🔗 Referans linki: {ref or 'bulunamadı'}")
        return
    if low in {"referanslar", "reflerim", "ref liste", "refler"}:
        if not REFS:
            await msg.reply_text("Kayıtlı referans linki yok.")
            return
        await wiz_send("🔗 Referans linklerin:\n\n" + "\n\n".join(
            f"@{b} ({v.get('src', '?')}):\n{v.get('link')}" for b, v in REFS.items()))
        return
    if low.startswith("ref ") and len(text.split()) >= 3:
        parts = text.split()
        nm, link = parse_bot_arg(parts[1]), parts[2]
        if not link.lower().startswith("http"):
            link = "https://" + link
        if not nm or "t.me/" not in link.lower():
            await msg.reply_text("Kullanım: ref botadi https://t.me/botadi?startapp=...")
            return
        REFS[nm] = {"link": link, "src": "elle", "t": time.time()}
        await persist_refs()
        if nm in WIZ_SUM:
            WIZ_SUM[nm]["ref"] = link
            await wiz_persist()
        await msg.reply_text(f"✅ @{nm} referans linki kaydedildi.")
        return
    if low.startswith("sor "):
        q = text.split(None, 1)[1]
        ctx = "\n\n".join(f"@{b}:\n{(v.get('summary') or '')[:700]}\nRef: {v.get('ref') or '-'}"
                          for b, v in list(WIZ_SUM.items())[:12])[:7000]
        await msg.reply_text("🧙 Düşünüyorum…")
        raw, model = await groq_chat([
            {"role": "system", "content": WIZ_SYSTEM},
            {"role": "user", "content": f"Kullanıcının mini app özetleri:\n{ctx or '(özet yok)'}\n\nSORU: {q}\n\n"
                                        f"Türkçe, kısa ve net cevap ver; özetlerde yoksa bilmediğini söyle."}], max_tokens=700)
        await wiz_send(raw or f"Cevap alınamadı ({model}).")
        return
    if low in {"komutlar", "yardim", "help"}:
        await wiz_send(UNI_HELP_TEXT + "\n\n" + WIZ_HELP + "\n" + WIZ_POST_HELP + "\n\n" + WD_HELP)
        return
    return await _wiz_on_text_base(update, context)


@admin_only
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(
        "🧙 V9 Groq Sihirbazı + V8 Mini App\n\n"
        "• Bot adı / t.me linki gönder → mini app açılır, ekran yazıları okunur, kural motoru + yapay zeka "
        "güvenli görevleri yapar, referans linkin bulunur, sonunda Türkçe ÖZET + altında REFERANS LİNKİ gelir.\n"
        "• Yapamadığı şeyleri nedeniyle '❗ Yapamadıklarım' bölümünde yazar.\n"
        "• otopilot tara / otopilot hepsi / otopilot aç / dur\n"
        "• özetler · özet botadi · referanslar · sor <soru> · sihirbaz\n\n"
        "Cüzdan, ödeme, Stars, TON, satın alma, davet ve paylaşım adımlarına asla basılmaz."
    )



# ------------------------------------------- çökme koruması (V9.3) ----
# Bot kapanırsa (bellek yetmedi / tarayıcı çöktü / sunucu yeniden başlattı) hangi botta
# kapandığı ve sırada kimlerin kaldığı kaydedilir; açılışta sana yazılır, 'devam' ile sürer.

WIZ_LIVE_KEY = "radar:wiz_live:v1"
WIZ_LIVE_FILE = "/tmp/radar_wiz_live.json"
WIZ_CRASH_SKIP = int(os.getenv("WIZ_CRASH_SKIP", "2") or 2)   # bu kadar çökertme → otomatik atla
WIZ_MSG_MAX_AGE = int(os.getenv("WIZ_MSG_MAX_AGE", "1800") or 1800)  # bundan eski bekleyen mesajlar yok sayılır
WIZ_JOURNAL = {"bot": "", "t0": 0, "queue": [], "crash": {}, "pending": []}


async def wiz_journal_save():
    try:
        WIZ_JOURNAL["queue"] = [it["bot"] for it in WIZ_QUEUE][:60]
        WIZ_JOURNAL["bot"] = WIZ_LIVE.get("bot", "") or ""
        WIZ_JOURNAL["t0"] = WIZ_LIVE.get("t0", 0) or 0
        await asyncio.wait_for(save_json(WIZ_LIVE_KEY, WIZ_LIVE_FILE, WIZ_JOURNAL), 10)
    except Exception as e:
        print("[CRASH-GUARD] kayıt hatası", repr(e), flush=True)


async def wiz_journal_boot():
    """Açılışta: önceki çalışma yarıda kaldıysa kaydı oku ve kullanıcıya bildir."""
    try:
        data = await load_json(WIZ_LIVE_KEY, WIZ_LIVE_FILE)
    except Exception:
        data = None
    if not isinstance(data, dict):
        return
    WIZ_JOURNAL["crash"] = dict(data.get("crash") or {})
    WIZ_JOURNAL["heavy"] = dict(data.get("heavy") or {})
    WIZ_JOURNAL["lite"] = dict(data.get("lite") or {})
    dead = data.get("bot") or ""
    queue = [b for b in (data.get("queue") or []) if b and b != dead]
    WIZ_JOURNAL["pending"] = list(dict.fromkeys(queue))
    if dead:
        WIZ_JOURNAL["crash"][dead] = int(WIZ_JOURNAL["crash"].get(dead, 0)) + 1
    WIZ_JOURNAL["bot"], WIZ_JOURNAL["queue"] = "", []
    await asyncio.wait_for(save_json(WIZ_LIVE_KEY, WIZ_LIVE_FILE, WIZ_JOURNAL), 10)
    if not dead and not queue:
        return
    lines = ["⚠️ Bot yeniden başladı (sunucu kapattı ya da çöktü)."]
    if dead:
        el = int(time.time() - float(data.get("t0") or time.time()))
        n = WIZ_JOURNAL["crash"][dead]
        lines.append(f"Kapanma @{dead} çalışırken oldu ({el // 60} dk sonra). En olası neden: bu mini app "
                     f"sunucunun belleğini doldurdu (ağır oyun / tarayıcı çöktü). Bu bot {n} kez çökertti.")
        if n >= WIZ_CRASH_SKIP + 1:
            lines.append(f"@{dead} artık otomatik ATLANACAK. Yine de denemek için: zorla {dead}")
        else:
            lines.append(f"Bir dahaki sefere @{dead} HAFİF MODDA açılacak (resim/oyun dosyası yüklenmez) ve "
                         f"bellek bekçisi sınıra yaklaşınca sadece tarayıcıyı kapatacak.")
    if WIZ_JOURNAL["pending"]:
        lines.append(f"Sırada kalan {len(WIZ_JOURNAL['pending'])} bot: " +
                     ", ".join("@" + b for b in WIZ_JOURNAL["pending"][:20]))
        lines.append("Kaldığı yerden sürdürmek için: devam")
    lines.append("Kapalıyken yazdığın mesajlar artık kaybolmuyor; 30 dk'dan eski olanlar yok sayılır.")
    try:
        await bot_app.bot.send_message(ADMIN_USER_ID, "\n".join(lines))
    except Exception as e:
        print("[CRASH-GUARD] bildirim gönderilemedi", repr(e), flush=True)


def wiz_crashy(name: str) -> bool:
    return int((WIZ_JOURNAL.get("crash") or {}).get(name, 0)) >= WIZ_CRASH_SKIP


_wiz_load_v8_ap_base2 = load_v8_ap


async def load_v8_ap():
    await _wiz_load_v8_ap_base2()
    try:
        await wiz_journal_boot()
    except Exception as e:
        print("[CRASH-GUARD] açılış kontrolü hatası", repr(e), flush=True)


_wiz_track_base2 = v8_run_and_track


async def v8_run_and_track(name="myageapp", short="", start="", source="manual", force=False):
    if wiz_crashy(name) and not force:
        n = WIZ_JOURNAL["crash"].get(name, 0)
        return "skip", [f"Atlandı: bu mini app sunucuyu {n} kez çökertti (bellek). Denemek için: zorla {name}"]
    task = asyncio.create_task(_wiz_track_base2(name, short, start, source))
    # sıraya girdiği / başladığı / bittiği an kaydedilir
    await asyncio.sleep(0)
    await wiz_journal_save()
    try:
        res = await task
        if (WIZ_JOURNAL.get("crash") or {}).get(name):
            WIZ_JOURNAL["crash"].pop(name, None)   # sorunsuz bitti → çökme sayısı sıfırlanır
            WIZ_JOURNAL.setdefault("lite", {})[name] = 1   # ama hep hafif modda açılmaya devam eder
        return res
    finally:
        if not task.done():
            task.cancel()
        await wiz_journal_save()


_wiz_browser_base3 = v8_browser


async def v8_browser(name, url, state, _retry: bool = False):
    await wiz_journal_save()   # çalışan bot kaydı (çökerse açılışta bilinsin)
    return await _wiz_browser_base3(name, url, state, _retry)


async def v8_stop():
    """DÜZELTME: 'dur' artık en fazla 20 sn bekler; takılan iş diğer mesajları kilitlemez."""
    global AUTO_STOP
    AUTO_STOP = True
    was_on = bool(V8_AP.get("on"))
    V8_AP["on"] = False
    try:
        await persist_v8_ap()
    except Exception:
        pass
    tasks = [t for t in V8_TASKS.values() if t is not None and not t.done()]
    n_q = len(WIZ_QUEUE)
    try:
        await bot_app.bot.send_message(ADMIN_USER_ID, f"⏹ Durduruluyor… ({len(tasks)} iş, sırada {n_q} bot)")
    except Exception:
        pass
    for t in tasks:
        try:
            t.cancel()
        except Exception:
            pass
    stuck = 0
    if tasks:
        _, pend = await asyncio.wait(tasks, timeout=20)
        stuck = len(pend)
    WIZ_QUEUE.clear()
    WIZ_JOURNAL["pending"] = []
    await wiz_journal_save()
    msg = "V8 işleri durduruldu, sıra boşaltıldı."
    if was_on:
        msg += " Otopilot kapatıldı."
    if stuck:
        msg += f" ({stuck} iş kapanırken takıldı; arka planda kendiliğinden kapanacak.)"
    msg += " Gönderilmiş işlemler geri alınamaz."
    await bot_app.bot.send_message(ADMIN_USER_ID, msg)


async def wiz_resume():
    names = [b for b in (WIZ_JOURNAL.get("pending") or []) if not wiz_crashy(b)]
    WIZ_JOURNAL["pending"] = []
    await wiz_journal_save()
    if not names:
        await bot_app.bot.send_message(ADMIN_USER_ID, "Sürdürülecek bot yok.")
        return
    await bot_app.bot.send_message(ADMIN_USER_ID, f"▶️ {len(names)} bot yeniden sıraya alınıyor: " +
                                   ", ".join("@" + b for b in names[:20]))
    for b in names:
        await auto_link(b)
        await asyncio.sleep(0.3)


async def wiz_force(name: str):
    WIZ_JOURNAL.setdefault("crash", {}).pop(name, None)
    WIZ_JOURNAL.setdefault("heavy", {}).pop(name, None)
    WIZ_JOURNAL.setdefault("lite", {}).pop(name, None)
    await wiz_journal_save()
    await bot_app.bot.send_message(ADMIN_USER_ID, f"@{name} çökme kaydı silindi, yeniden deneniyor "
                                                  f"(yine çökertirse tekrar atlanır).")
    await auto_link(name)



# ------------------------------------------- bellek bekçisi (V9.4) ----
# Render ücretsiz plan 512 MB. Ağır mini app (Unity oyunu vb.) belleği doldurursa Render tüm botu
# öldürüyordu. Artık bellek sınıra yaklaşınca SADECE tarayıcı kapatılır, bot çalışmaya devam eder.
# O mini app "ağır" diye işaretlenir; sonraki turlarda HAFİF MODDA açılır (resim/ses/oyun dosyası yüklenmez).

import signal as _wiz_signal

WIZ_HEAVY_RE = re.compile(r"\.(?:wasm|data|unityweb|bundle|mem|br|mp4|webm|m4a|mp3|ogg|wav|glb|gltf|ktx2?|basis|atlas)(?:\.gz|\.br)?(?:[?#]|$)", re.I)
WIZ_LITE = {"on": False}
WIZ_MEM = {"killed": False, "peak": 0, "watching": False}


def _wiz_read(path: str) -> str:
    try:
        with open(path) as f:
            return f.read().strip()
    except Exception:
        return ""


def wiz_mem_limit_mb() -> int:
    env = os.getenv("WIZ_MEM_LIMIT_MB", "").strip()
    if env.isdigit():
        return int(env)
    for p in ("/sys/fs/cgroup/memory.max", "/sys/fs/cgroup/memory/memory.limit_in_bytes"):
        v = _wiz_read(p)
        if v.isdigit() and int(v) < (1 << 40):
            return int(v) // (1024 * 1024)
    return 512   # Render ücretsiz plan


def wiz_mem_used_mb() -> int:
    """Konteynerin gerçek bellek kullanımı (önbellek hariç)."""
    cur = _wiz_read("/sys/fs/cgroup/memory.current")
    stat_p = "/sys/fs/cgroup/memory.stat"
    if not cur.isdigit():
        cur = _wiz_read("/sys/fs/cgroup/memory/memory.usage_in_bytes")
        stat_p = "/sys/fs/cgroup/memory/memory.stat"
    if cur.isdigit():
        used = int(cur)
        for ln in _wiz_read(stat_p).splitlines():
            k, _, v = ln.partition(" ")
            if k in ("inactive_file", "total_inactive_file") and v.isdigit():
                used -= int(v)
        return max(0, used // (1024 * 1024))
    total = 0   # cgroup okunamazsa: tüm süreçlerin PSS/RSS toplamı
    for pid in os.listdir("/proc"):
        if not pid.isdigit():
            continue
        txt = _wiz_read(f"/proc/{pid}/smaps_rollup") or _wiz_read(f"/proc/{pid}/status")
        m = re.search(r"^(?:Pss|VmRSS):\s+(\d+)", txt, re.M)
        if m:
            total += int(m.group(1))
    return total // 1024


def wiz_kill_browsers() -> int:
    n = 0
    for pid in os.listdir("/proc"):
        if not pid.isdigit() or int(pid) == os.getpid():
            continue
        cmd = _wiz_read(f"/proc/{pid}/cmdline").split("\0")[0].lower()
        if "chrom" in cmd or "headless_shell" in cmd:
            try:
                os.kill(int(pid), _wiz_signal.SIGKILL)
                n += 1
            except Exception:
                pass
    return n


WIZ_MEM_KILL_PCT = float(os.getenv("WIZ_MEM_KILL_PCT", "0.92") or 0.92)   # 512 MB → 471 MB'ta tarayıcı kapanır


async def wiz_mem_watch(name: str):
    limit = wiz_mem_limit_mb()
    kill_at = int(limit * WIZ_MEM_KILL_PCT)
    while True:
        await asyncio.sleep(0.8)
        try:
            used = wiz_mem_used_mb()
        except Exception:
            continue
        WIZ_MEM["peak"] = max(WIZ_MEM["peak"], used)
        if used >= kill_at and not WIZ_MEM["killed"]:
            WIZ_MEM["killed"] = True
            k = wiz_kill_browsers()
            print(f"[BELLEK] @{name} {used} MB / {limit} MB → tarayıcı kapatıldı ({k} süreç), bot çökmedi", flush=True)


def wiz_heavy_level(name: str) -> int:
    j = WIZ_JOURNAL
    return (int((j.get("crash") or {}).get(name, 0)) + int((j.setdefault("heavy", {})).get(name, 0))
            + int((j.setdefault("lite", {})).get(name, 0)))


def wiz_crashy(name: str) -> bool:   # V9.3'ün yerine: ağır modda da sığmayan bot atlanır
    return int((WIZ_JOURNAL.get("crash") or {}).get(name, 0)) >= WIZ_CRASH_SKIP + 1 or \
        int((WIZ_JOURNAL.setdefault("heavy", {})).get(name, 0)) >= 3


async def v8_browser(name, url, state, _retry: bool = False):
    await wiz_journal_save()
    if WIZ_MEM["watching"]:   # temiz oturumla tekrar denemede bekçi zaten çalışıyor
        return await _wiz_browser_base3(name, url, state, _retry)
    lite = wiz_heavy_level(name) > 0
    WIZ_LITE["on"] = lite
    WIZ_MEM.update({"killed": False, "peak": 0, "watching": True})
    mon = asyncio.create_task(wiz_mem_watch(name))
    pre = []
    if lite:
        pre.append("Hafif mod: bu mini app daha önce belleği doldurdu; resim/ses/oyun dosyaları yüklenmeden açıldı.")
        if WIZ_CUR:
            WIZ_CUR["fails"].append("Hafif modda açıldı (sunucu belleği 512 MB): oyunun grafik kısmı yüklenmedi")
    try:
        try:
            notes = await _wiz_browser_base3(name, url, state, _retry)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            if not WIZ_MEM["killed"]:
                raise
            notes = [f"Tarayıcı kapandı ({type(e).__name__})."]
    finally:
        mon.cancel()
        WIZ_MEM["watching"] = False
        WIZ_LITE["on"] = False
    print(f"[BELLEK] @{name} tepe kullanım: {WIZ_MEM['peak']} MB / {wiz_mem_limit_mb()} MB"
          + (" (hafif mod)" if lite else ""), flush=True)
    if WIZ_MEM["killed"]:
        hv = WIZ_JOURNAL.setdefault("heavy", {})
        hv[name] = int(hv.get(name, 0)) + 1
        await wiz_journal_save()
        msg = (f"BELLEK SINIRI: mini app sunucu belleğini doldurdu ({WIZ_MEM['peak']} MB / {wiz_mem_limit_mb()} MB); "
               f"bot çökmesin diye tarayıcı kapatıldı.")
        msg += (" Hafif modda da sığmadı." if lite else " Bir dahaki sefere hafif modda açılacak.")
        if WIZ_CUR:
            WIZ_CUR["fails"].append(msg)
        notes = pre + list(notes or []) + [msg]
    else:
        notes = pre + list(notes or [])
    return notes



# ------------------------------------------- kanal / grup paylaşımı (V9.5) ----
# Her mini app için HALKA AÇIK bir tanıtım yazısı hazırlanır (kişisel bakiye/hata bilgisi olmadan):
# "ne bu, nasıl kazanılır (adım adım), token bilgisi, dikkat" + altında SENİN referans linkin.
# Her hedefin kendi stili/dili var: kanal → detaylı rehber, grup → kısa duyuru, istersen İngilizce.
# Varsayılan mod ONAY: önce sana önizleme gelir, "Gönder"e basınca paylaşılır.

WIZ_POST_KEY = "radar:wiz_post:v1"
WIZ_POST_FILE = "/tmp/radar_wiz_post.json"
WIZ_POST = {"targets": [], "mode": "onay", "posted": {}, "daily_max": 8, "day": "", "day_n": 0,
            "repost_days": 7, "drafts": {}, "seq": 0, "sign": ""}
WIZ_POST_STYLES = ("detay", "kisa", "liste")
WIZ_POST_STYLE_TR = {"detay": "detaylı rehber", "kisa": "kısa duyuru", "liste": "madde madde"}

WIZ_POST_PROMPT = {
    "detay": ("Bir Telegram airdrop/kripto KANALI için TANITIM GÖNDERİSİ yaz. Okuyucu bu mini uygulamayı ilk kez "
              "görüyor. Şu formatta:\n"
              "1. satır: emoji + uygulama adı + kısa çarpıcı başlık\n"
              "Boş satır, sonra 1-2 cümle: uygulama ne, nasıl kazandırıyor\n"
              "'📝 Yapılması gerekenler:' başlığı altında 3-6 numaralı kısa adım (botu başlat, günlük ödül, görevler, "
              "farm vb. — SADECE bilgide geçenler)\n"
              "'💰 Ödül / Token:' 1 satır (bilgi yoksa 'henüz açıklanmadı')\n"
              "'⚠️ Not:' 1 satır dikkat (cüzdan/ödeme isterse dikkat, yatırım tavsiyesi değildir)\n"
              "En fazla 900 karakter."),
    "kisa": ("Bir Telegram SOHBET GRUBU için KISA duyuru yaz: en fazla 4 satır, samimi dil. 1. satır emoji + uygulama "
             "adı + ne olduğu, 2-3. satır en önemli 2-3 adım tek satırda, son satır kısa çağrı (ör. 'Hemen başla 👇'). "
             "En fazla 350 karakter."),
    "liste": ("Bir Telegram kanalı için MADDE MADDE gönderi yaz: başlık satırı (emoji + uygulama adı), sonra 4-6 "
              "madde ('▫️' ile): ne olduğu, yapılacaklar, ödül. En fazla 600 karakter."),
}
WIZ_POST_RULES = (
    "\nKURALLAR: SADECE verilen bilgiyi kullan, UYDURMA (tarih, miktar, borsa listesi uydurma). Kişisel bakiye, "
    "hesap numarası, hata mesajı, 'botum yaptı', 'yapamadım' gibi İÇ bilgileri YAZMA — okuyucuya hitap et. "
    "Linki YAZMA (link en alta otomatik eklenecek). Abartılı 'kesin kazanç' vaadi verme. Markdown/HTML kullanma, "
    "düz metin + emoji. {lang}\n\nUYGULAMA: @{bot}\n\nBİLGİ (özet + ekran yazıları):\n{info}"
)


def _wiz_today() -> str:
    return time.strftime("%Y-%m-%d", time.gmtime(time.time() + 3 * 3600))


async def wiz_post_persist():
    data = {k: v for k, v in WIZ_POST.items() if k != "drafts"}
    data["drafts"] = dict(list(WIZ_POST["drafts"].items())[-20:])
    try:
        await asyncio.wait_for(save_json(WIZ_POST_KEY, WIZ_POST_FILE, data), 10)
    except Exception as e:
        print("[PAYLAŞIM] kayıt hatası", repr(e), flush=True)


async def wiz_post_load():
    try:
        data = await load_json(WIZ_POST_KEY, WIZ_POST_FILE)
    except Exception:
        data = None
    if isinstance(data, dict):
        for k in WIZ_POST:
            if k in data:
                WIZ_POST[k] = data[k]
    print(f"[PAYLAŞIM] {len(WIZ_POST['targets'])} hedef · mod={WIZ_POST['mode']}", flush=True)


_wiz_load_v8_ap_base3 = load_v8_ap


async def load_v8_ap():
    await _wiz_load_v8_ap_base3()
    await wiz_post_load()


def _wiz_post_info(bot: str) -> str:
    s = WIZ_SUM.get(bot) or {}
    info = (s.get("summary") or "")[:2200]
    scr = "\n".join((WIZ_CUR.get("screens") or [])[:6])[:1800] if WIZ_CUR.get("bot") == bot else ""
    return (info + ("\n\nEKRAN YAZILARI:\n" + scr if scr else "")).strip() or "(bilgi yok)"


def _wiz_post_fallback(bot: str, style: str) -> str:
    s = (WIZ_SUM.get(bot) or {}).get("summary") or ""
    m = re.search(r"🎮 Uygulama:\s*([^\n]+)", s)
    what = (m.group(1).split("—", 1)[-1].strip() if m else "Telegram mini uygulaması")[:160]
    m = re.search(r"📌 Nasıl çalışıyor:\s*([^\n]+)", s)
    how = (m.group(1).strip() if m else "")[:300]
    if style == "kisa":
        return f"🚀 @{bot} — {what}\nBotu başlat, günlük ödülünü al, görevleri yap.\nHemen başla 👇"
    return (f"🚀 @{bot}\n\n{what}\n{how}\n\n📝 Yapılması gerekenler:\n1. Aşağıdaki linkten botu başlat\n"
            f"2. Günlük ödülü ve görevleri yap\n3. Her gün girip toplamayı unutma\n\n"
            f"⚠️ Not: Cüzdan/ödeme isteyen adımlara dikkat; yatırım tavsiyesi değildir.")


async def wiz_post_text(bot: str, style: str, lang: str) -> str:
    style = style if style in WIZ_POST_PROMPT else "detay"
    lang_txt = "Dil: İNGİLİZCE yaz (English)." if lang == "en" else "Dil: TÜRKÇE yaz."
    prompt = WIZ_POST_PROMPT[style] + WIZ_POST_RULES.format(lang=lang_txt, bot=bot, info=_wiz_post_info(bot))
    raw, _ = await groq_chat([{"role": "system", "content": "Sen deneyimli bir Telegram kripto/airdrop kanal yöneticisisin. "
                                                            "Dürüst, net ve okunaklı gönderiler yazarsın."},
                              {"role": "user", "content": prompt}], max_tokens=700, temperature=0.6)
    txt = (raw or "").strip() or _wiz_post_fallback(bot, style)
    txt = re.sub(r"https?://\S+", "", txt)            # yapay zeka link eklediyse sil (link en altta tek)
    txt = re.sub(r"[*_`#]{2,}", "", txt).strip()
    return txt[:1200]


def _wiz_post_full(text: str, ref: str, lang: str) -> str:
    cta = "👉 Start here (my referral link):" if lang == "en" else "👉 Buradan başla (referans linkim):"
    out = f"{text}\n{ref}" if text.rstrip().endswith("👇") else f"{text}\n\n{cta}\n{ref}"
    if WIZ_POST.get("sign"):
        out += f"\n\n{WIZ_POST['sign']}"
    return out


def _wiz_post_kb(bot: str, ref: str, lang: str):
    lab = "🚀 Start" if lang == "en" else "🚀 Hemen Başla"
    if ref.startswith("https://t.me/"):
        return InlineKeyboardMarkup([[InlineKeyboardButton(lab, url=ref)]])
    return None


def _wiz_post_due(bot: str, chat: str) -> bool:
    t = float(((WIZ_POST["posted"].get(bot) or {}).get(str(chat))) or 0)
    return time.time() - t > float(WIZ_POST.get("repost_days", 7)) * 86400


async def wiz_post_draft(bot: str, force: bool = False):
    """Taslak hazırlar (her stil/dil için bir metin). (taslak_id | None, not)"""
    ref = (REFS.get(bot) or {}).get("link") or (WIZ_SUM.get(bot) or {}).get("ref") or ""
    if not WIZ_POST["targets"]:
        return None, "Paylaşım hedefi yok. Önce: kanal ekle @kanaladi"
    if not ref:
        return None, f"@{bot} için referans linki yok. Önce: ref {bot} https://t.me/..."
    if not WIZ_SUM.get(bot):
        return None, f"@{bot} için özet yok. Önce botu çalıştır: @{bot}"
    targets = [t for t in WIZ_POST["targets"] if force or _wiz_post_due(bot, t["chat"])]
    if not targets:
        return None, f"@{bot} tüm hedeflerde son {WIZ_POST.get('repost_days', 7)} gün içinde zaten paylaşıldı."
    texts = {}
    for t in targets:
        k = f"{t.get('style', 'detay')}|{t.get('lang', 'tr')}"
        if k not in texts:
            texts[k] = await wiz_post_text(bot, t.get("style", "detay"), t.get("lang", "tr"))
    WIZ_POST["seq"] = int(WIZ_POST.get("seq", 0)) + 1
    did = str(WIZ_POST["seq"])
    WIZ_POST["drafts"][did] = {"bot": bot, "ref": ref, "texts": texts, "chats": [str(t["chat"]) for t in targets],
                               "t": time.time()}
    await wiz_post_persist()
    return did, ""


async def wiz_post_preview(did: str):
    d = WIZ_POST["drafts"].get(did)
    if not d:
        return
    tmap = {str(t["chat"]): t for t in WIZ_POST["targets"]}
    head = f"📣 PAYLAŞIM ÖNİZLEME — @{d['bot']} → {len(d['chats'])} hedef:\n" + "\n".join(
        f"  • {tmap.get(c, {}).get('title', c)} ({WIZ_POST_STYLE_TR.get(tmap.get(c, {}).get('style', 'detay'), '')}, "
        f"{tmap.get(c, {}).get('lang', 'tr')})" for c in d["chats"])
    await bot_app.bot.send_message(ADMIN_USER_ID, head)
    for k, txt in d["texts"].items():
        st, lg = k.split("|")
        await bot_app.bot.send_message(ADMIN_USER_ID, f"— {WIZ_POST_STYLE_TR.get(st, st)} / {lg} —\n\n" +
                                       _wiz_post_full(txt, d["ref"], lg), disable_web_page_preview=True,
                                       reply_markup=_wiz_post_kb(d["bot"], d["ref"], lg))
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("✅ Gönder", callback_data=f"wp:ok:{did}"),
                                InlineKeyboardButton("🔁 Yeniden yaz", callback_data=f"wp:re:{did}"),
                                InlineKeyboardButton("❌ Vazgeç", callback_data=f"wp:no:{did}")]])
    await bot_app.bot.send_message(ADMIN_USER_ID, "Paylaşayım mı?", reply_markup=kb)


async def wiz_post_send(did: str) -> str:
    d = WIZ_POST["drafts"].get(did)
    if not d:
        return "Taslak bulunamadı (eski olabilir)."
    today = _wiz_today()
    if WIZ_POST.get("day") != today:
        WIZ_POST["day"], WIZ_POST["day_n"] = today, 0
    tmap = {str(t["chat"]): t for t in WIZ_POST["targets"]}
    ok, bad = [], []
    for c in d["chats"]:
        if WIZ_POST["day_n"] >= int(WIZ_POST.get("daily_max", 8)):
            bad.append(f"{tmap.get(c, {}).get('title', c)}: günlük limit doldu ({WIZ_POST['daily_max']})")
            continue
        t = tmap.get(c)
        if not t:
            continue
        txt = d["texts"].get(f"{t.get('style', 'detay')}|{t.get('lang', 'tr')}") or next(iter(d["texts"].values()))
        try:
            chat_id = int(c) if re.fullmatch(r"-?\d+", c) else c
            await bot_app.bot.send_message(chat_id, _wiz_post_full(txt, d["ref"], t.get("lang", "tr")),
                                           disable_web_page_preview=True,
                                           reply_markup=_wiz_post_kb(d["bot"], d["ref"], t.get("lang", "tr")))
            WIZ_POST["posted"].setdefault(d["bot"], {})[c] = time.time()
            WIZ_POST["day_n"] += 1
            ok.append(t.get("title", c))
        except Exception as e:
            bad.append(f"{t.get('title', c)}: {type(e).__name__} {str(e)[:80]} (bot orada yönetici mi?)")
        await asyncio.sleep(3)   # hedefler arası bekleme (spam sayılmasın)
    WIZ_POST["drafts"].pop(did, None)
    await wiz_post_persist()
    out = f"📣 @{d['bot']}: " + (f"✅ {len(ok)} hedefe paylaşıldı ({', '.join(ok)})" if ok else "hiçbir hedefe gönderilemedi")
    if bad:
        out += "\n❗ " + "\n❗ ".join(bad)
    return out


async def wiz_post_after_run(bot: str, outcome: str):
    """Tur bittikten sonra: mod 'onay' → önizleme, 'oto' → direkt paylaş. Sadece ilk kez / süresi dolunca."""
    mode = WIZ_POST.get("mode", "onay")
    if mode == "kapali" or not WIZ_POST["targets"] or outcome == "err":
        return
    if not ((REFS.get(bot) or {}).get("link") or (WIZ_SUM.get(bot) or {}).get("ref")):
        return
    if not any(_wiz_post_due(bot, t["chat"]) for t in WIZ_POST["targets"]):
        return
    # aynı bot için bekleyen taslak varsa yenisini yapma
    if any(d.get("bot") == bot for d in WIZ_POST["drafts"].values()):
        return
    did, err = await wiz_post_draft(bot)
    if not did:
        return
    if mode == "oto":
        await bot_app.bot.send_message(ADMIN_USER_ID, await wiz_post_send(did))
    else:
        await wiz_post_preview(did)


_wiz_finish_base_post = wiz_finish


async def wiz_finish(name: str, outcome: str, notes: list, source: str):
    await _wiz_finish_base_post(name, outcome, notes, source)
    try:
        await asyncio.wait_for(wiz_post_after_run(name, outcome), 120)
    except Exception as e:
        print("[PAYLAŞIM]", repr(e), flush=True)


async def wiz_post_add_target(arg: str) -> str:
    parts = arg.split()
    if not parts:
        return "Kullanım: kanal ekle @kanaladi [detay|kisa|liste] [tr|en]"
    raw = parts[0].strip()
    raw = re.sub(r"^https?://t\.me/", "@", raw).rstrip("/")
    style = next((p for p in parts[1:] if p in WIZ_POST_STYLES), "detay")
    lang = next((p for p in parts[1:] if p in ("tr", "en")), "tr")
    chat_ref = int(raw) if re.fullmatch(r"-?\d+", raw) else ("@" + raw.lstrip("@"))
    try:
        chat = await bot_app.bot.get_chat(chat_ref)
        me = await bot_app.bot.get_me()
        mem = await bot_app.bot.get_chat_member(chat.id, me.id)
        st = getattr(mem, "status", "")
        can = st in ("administrator", "creator") or (chat.type in ("group", "supergroup") and st == "member")
        if chat.type == "channel" and st == "administrator" and getattr(mem, "can_post_messages", True) is False:
            can = False
    except Exception as e:
        return (f"{raw} bulunamadı ya da bot orada değil ({type(e).__name__}).\n"
                f"Önce botu (@{(await bot_app.bot.get_me()).username}) kanala YÖNETİCİ olarak ekle "
                f"(gönderi paylaşma izni), gruba üye olarak ekle; sonra tekrar dene.")
    if not can:
        return f"Bot '{chat.title}' içinde mesaj atamıyor (durum: {st}). Kanala yönetici yap, 'Mesaj gönder' iznini ver."
    cid = str(chat.id)
    WIZ_POST["targets"] = [t for t in WIZ_POST["targets"] if str(t["chat"]) != cid]
    WIZ_POST["targets"].append({"chat": cid, "title": chat.title or raw, "style": style, "lang": lang,
                                "type": chat.type})
    await wiz_post_persist()
    return (f"✅ Hedef eklendi: {chat.title} ({'kanal' if chat.type == 'channel' else 'grup'}) — stil: "
            f"{WIZ_POST_STYLE_TR[style]}, dil: {lang}\nPaylaşım modu: {WIZ_POST['mode']}  ·  Hedefler: kanallar")


def wiz_post_targets_text() -> str:
    if not WIZ_POST["targets"]:
        tl = "(hedef yok)"
    else:
        tl = "\n".join(f"{i}. {t['title']} [{t['chat']}] — {WIZ_POST_STYLE_TR.get(t.get('style'), '')}, {t.get('lang', 'tr')}"
                       for i, t in enumerate(WIZ_POST["targets"], 1))
    today_n = WIZ_POST["day_n"] if WIZ_POST.get("day") == _wiz_today() else 0
    return (f"📣 PAYLAŞIM HEDEFLERİ\n{tl}\n\nMod: {WIZ_POST['mode']} (onay = önce bana sor · oto = direkt paylaş · "
            f"kapali)\nGünlük limit: {today_n}/{WIZ_POST['daily_max']} · Aynı bot tekrar: {WIZ_POST['repost_days']} gün sonra\n"
            f"İmza: {WIZ_POST.get('sign') or '(yok)'}\nPaylaşılan bot sayısı: {len(WIZ_POST['posted'])}")


WIZ_POST_HELP = (
    "📣 KANAL / GRUP PAYLAŞIMI\n"
    "• kanal ekle @kanal [detay|kisa|liste] [tr|en] — hedef ekle (bot orada yönetici olmalı)\n"
    "• kanal sil @kanal  ·  kanallar — hedefler ve ayarlar\n"
    "• paylaş botadi — o mini app için gönderi hazırla (önizleme gelir)\n"
    "• paylaşım mod onay | oto | kapalı\n"
    "• paylaşım limit 8  ·  paylaşım tekrar 7 (gün)  ·  imza @kanalim (her gönderinin altına)\n"
    "• duyuru <metin> — tüm hedeflere serbest duyuru (önizlemeli)\n"
)


async def wiz_post_cmd(msg, text: str, low: str) -> bool:
    """Paylaşım komutları. İşlendiyse True."""
    if low.startswith("kanal ekle ") or low.startswith("grup ekle "):
        await msg.reply_text(await wiz_post_add_target(text.split(None, 2)[2]))
        return True
    if low.startswith("kanal sil ") or low.startswith("grup sil "):
        raw = re.sub(r"^https?://t\.me/", "", text.split(None, 2)[2].strip()).lstrip("@").lower()
        before = len(WIZ_POST["targets"])
        WIZ_POST["targets"] = [t for t in WIZ_POST["targets"] if raw not in (str(t["chat"]).lower(), (t.get("title") or "").lower())
                               and str(t["chat"]).lstrip("@").lower() != raw]
        if len(WIZ_POST["targets"]) == before:
            try:
                chat = await bot_app.bot.get_chat("@" + raw if not re.fullmatch(r"-?\d+", raw) else int(raw))
                WIZ_POST["targets"] = [t for t in WIZ_POST["targets"] if str(t["chat"]) != str(chat.id)]
            except Exception:
                pass
        await wiz_post_persist()
        await msg.reply_text("Silindi." if len(WIZ_POST["targets"]) < before else "Bu hedef listede yok. Bak: kanallar")
        return True
    if low in {"kanallar", "gruplar", "hedefler", "paylasim"}:
        await msg.reply_text(wiz_post_targets_text() + "\n\n" + WIZ_POST_HELP)
        return True
    if low.startswith("paylasim mod"):
        m = {"onay": "onay", "oto": "oto", "otomatik": "oto", "kapali": "kapali", "kapat": "kapali"}.get(low.split()[-1])
        if not m:
            await msg.reply_text("Kullanım: paylaşım mod onay | oto | kapalı")
            return True
        WIZ_POST["mode"] = m
        await wiz_post_persist()
        await msg.reply_text(f"Paylaşım modu: {m}" + (" — her yeni mini app (ref linki varsa) DİREKT paylaşılacak, "
                                                       "günlük limit: " + str(WIZ_POST['daily_max']) if m == "oto" else ""))
        return True
    if low.startswith("paylasim limit "):
        n = re.findall(r"\d+", low)
        if n:
            WIZ_POST["daily_max"] = max(1, min(50, int(n[0])))
            await wiz_post_persist()
        await msg.reply_text(f"Günlük paylaşım limiti: {WIZ_POST['daily_max']}")
        return True
    if low.startswith("paylasim tekrar "):
        n = re.findall(r"\d+", low)
        if n:
            WIZ_POST["repost_days"] = max(1, min(90, int(n[0])))
            await wiz_post_persist()
        await msg.reply_text(f"Aynı mini app {WIZ_POST['repost_days']} gün sonra tekrar paylaşılabilir.")
        return True
    if low.startswith("imza"):
        WIZ_POST["sign"] = text.split(None, 1)[1].strip()[:120] if len(text.split()) > 1 else ""
        await wiz_post_persist()
        await msg.reply_text(f"İmza: {WIZ_POST['sign'] or '(kaldırıldı)'}")
        return True
    if low.startswith("paylas ") and not low.startswith("paylasim"):
        bn = re.sub(r"^https?://t\.me/", "", text.split(None, 1)[1].strip()).lstrip("@").split("/")[0].split("?")[0].lower()
        await msg.reply_text(f"📝 @{bn} için gönderi yazılıyor…")
        did, err = await wiz_post_draft(bn, force=True)
        if not did:
            await msg.reply_text(err)
        else:
            await wiz_post_preview(did)
        return True
    if low.startswith("duyuru "):
        body = text.split(None, 1)[1].strip()[:3000]
        if not WIZ_POST["targets"]:
            await msg.reply_text("Paylaşım hedefi yok. Önce: kanal ekle @kanaladi")
            return True
        WIZ_POST["seq"] = int(WIZ_POST.get("seq", 0)) + 1
        did = str(WIZ_POST["seq"])
        WIZ_POST["drafts"][did] = {"bot": "duyuru", "ref": "", "texts": {"serbest|tr": body},
                                   "chats": [str(t["chat"]) for t in WIZ_POST["targets"]], "t": time.time(), "raw": True}
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("✅ Gönder", callback_data=f"wp:ok:{did}"),
                                    InlineKeyboardButton("❌ Vazgeç", callback_data=f"wp:no:{did}")]])
        await msg.reply_text(f"📣 DUYURU ÖNİZLEME → {len(WIZ_POST['targets'])} hedef:\n\n{body}", reply_markup=kb)
        return True
    return False


_wiz_post_full_base = _wiz_post_full


def _wiz_post_full(text: str, ref: str, lang: str) -> str:
    if not ref:   # serbest duyuru: link/CTA eklenmez
        return text + (f"\n\n{WIZ_POST['sign']}" if WIZ_POST.get("sign") else "")
    return _wiz_post_full_base(text, ref, lang)


_wiz_on_callback_base = on_callback


async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if q and q.data and q.data.startswith("wp:"):
        if not update.effective_user or update.effective_user.id != ADMIN_USER_ID:
            await q.answer("Yetkin yok.")
            return
        _, act, did = (q.data.split(":") + ["", ""])[:3]
        await q.answer()
        try:
            await q.edit_message_reply_markup(None)
        except Exception:
            pass
        if act == "ok":
            await bot_app.bot.send_message(ADMIN_USER_ID, "⏳ Paylaşılıyor…")
            await bot_app.bot.send_message(ADMIN_USER_ID, await wiz_post_send(did))
        elif act == "re":
            d = WIZ_POST["drafts"].pop(did, None)
            if d:
                await bot_app.bot.send_message(ADMIN_USER_ID, f"🔁 @{d['bot']} yeniden yazılıyor…")
                nd, err = await wiz_post_draft(d["bot"], force=True)
                if nd:
                    await wiz_post_preview(nd)
                else:
                    await bot_app.bot.send_message(ADMIN_USER_ID, err)
        elif act == "no":
            d = WIZ_POST["drafts"].pop(did, None)
            if d and d.get("bot") != "duyuru":
                # vazgeçilen bot bu süre boyunca tekrar sorulmaz
                for c in d["chats"]:
                    WIZ_POST["posted"].setdefault(d["bot"], {})[c] = time.time()
            await wiz_post_persist()
            await bot_app.bot.send_message(ADMIN_USER_ID, "Vazgeçildi." + (
                f" @{d['bot']} {WIZ_POST['repost_days']} gün tekrar sorulmayacak (istersen: paylaş {d['bot']})."
                if d and d.get("bot") != "duyuru" else ""))
        return
    return await _wiz_on_callback_base(update, context)




# ------------------------------------------------ günlük rutin planlayıcı (V9.6) ----
# Her mini app için ayrı ayar: günlük ödül / check-in, claim (farm/mining) aralığı, görev yapma.
# Bot, ekrandaki sayacı ("Claim in 03:12:45", "3h 12m", "2 saat sonra") okur ve bir sonraki
# toplamayı tam o saate kurar. Gün dönünce günlük ödül turu atar. Akşam tek mesajla gün raporu gelir.

WD_KEY = os.getenv("WIZ_DAY_KEY", "radar:wiz_daily:v1").strip()
WD_FILE = os.getenv("WIZ_DAY_FILE", "/tmp/radar_wiz_daily.json")
WD_TZ_H = int(os.getenv("WIZ_TZ_OFFSET_H", "3") or 3)              # İstanbul = UTC+3
WD_DEFAULT_H = float(os.getenv("WIZ_DAY_DEFAULT_H", "6") or 6)       # sayaç okunamazsa kaç saatte bir
WD_MIN_GAP_MIN = int(os.getenv("WIZ_DAY_MIN_GAP_MIN", "20") or 20)   # aynı bota en az bu kadar dk arayla
WD_AI_STEPS = int(os.getenv("WIZ_DAY_AI_STEPS", "14") or 14)
WD_CLAIM_STEPS = ["oto", 2, 4, 6, 8, 12, 24]
WD_TASK_STEPS = [3, 5, 10, 20]
WIZ_DAY = {"on": True, "bots": {}, "report": "ozet", "night": [], "saat": 3, "digest_h": 21,
           "digest_day": "", "auto_add": True}
WD_RUN: dict = {}
WD_STARTED = {"on": False}

WD_DAILY_RE = re.compile(
    r"daily|check[- ]?in|sign[- ]?in|login (?:reward|bonus)|streak|\bday\s*\d|g[üu]nl[üu]k|g[üu]n\s*\d|seri|"
    r"ежедн|ежеднев|bonus|бонус|calendar|takvim", re.I)
WD_CLAIM_RE = re.compile(
    r"claim|collect|harvest|farm|mining|\bmine\b|topla|[öo]d[üu]l[üu]? al|\bal\b|получить|забрать|собрать|фарм|"
    r"start farming|start mining|madencil", re.I)
WD_DONE_RE = re.compile(
    r"already|claimed|come back|tomorrow|next (?:reward|claim|day)|zaten|yar[ıi]n|al[ıi]nd[ıi]|завтра|уже", re.I)
WD_KEYLINE_RE = re.compile(
    r"claim|farm|mine|mining|next|available|ready|until|left|remain|refresh|reset|daily|collect|harvest|storage|"
    r"full|in\s+\d|kalan|sonra|haz[ıi]r|dolu|g[üu]nl[üu]k|через|осталось|⏳|⌛|🕒|⏱", re.I)


def wd_now_local():
    return time.gmtime(time.time() + WD_TZ_H * 3600)


def wd_day_key(ts: float = None) -> str:
    """Günlük ödül günü: yerel saatten 'saat' kadar geri kaydırılmış tarih (varsayılan 03:00 = 00:00 UTC)."""
    ts = time.time() if ts is None else ts
    return time.strftime("%Y-%m-%d", time.gmtime(ts + WD_TZ_H * 3600 - int(WIZ_DAY.get("saat") or 0) * 3600))


def wd_fmt_dur(sec: float) -> str:
    sec = max(0, int(sec))
    h, m = sec // 3600, (sec % 3600) // 60
    if h and m:
        return f"{h} sa {m} dk"
    return f"{h} sa" if h else f"{max(1, m)} dk"


def wd_fmt_clock(ts: float) -> str:
    return time.strftime("%H:%M", time.gmtime(ts + WD_TZ_H * 3600))


def wd_parse_wait(text: str):
    """Ekrandaki geri sayımı saniyeye çevirir. Bulamazsa None. (5 dk – 26 saat arası kabul edilir)"""
    if not text:
        return None
    lines = [ln.strip() for ln in str(text).splitlines() if ln.strip()]
    if len(lines) <= 1:
        lines = [p.strip() for p in re.split(r"\s*\|\s*", str(text)) if p.strip()]
    vals = []
    for i, ln in enumerate(lines):
        near = ln + " " + (lines[i - 1] if i else "")
        for m in re.finditer(r"(?<![\d:.])(\d{1,2}):([0-5]\d):([0-5]\d)(?![\d:])", ln):
            vals.append(int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3)))
        if not WD_KEYLINE_RE.search(near):
            continue
        rest = ln
        for m in re.finditer(r"(\d{1,2})\s*(?:hours?|hrs|hr|h|saat|sa|час\w*|ч)(?![a-zçğıöşü])\.?\s*"
                             r"(?:(\d{1,2})\s*(?:minutes?|mins|min|m|dakika|dk|мин\w*))?", ln, re.I):
            vals.append(int(m.group(1)) * 3600 + int(m.group(2) or 0) * 60)
            rest = rest.replace(m.group(0), " ")
        for m in re.finditer(r"(?<![\d:])(\d{1,3})\s*(?:minutes?|mins|min|m|dakika|dk|мин\w*)(?![a-zа-я])", rest, re.I):
            vals.append(int(m.group(1)) * 60)
        for m in re.finditer(r"(?<![\d:])(\d{1,2}):([0-5]\d)(?![\d:])", rest):
            # '03:12' bir sayaç satırında → saat:dakika say (saat değil, kalan süre)
            if re.search(r"in\s|left|kalan|sonra|через|осталось|until|⏳|⌛", near, re.I):
                vals.append(int(m.group(1)) * 3600 + int(m.group(2)) * 60)
    vals = [v for v in vals if 300 <= v <= 26 * 3600]
    return min(vals) if vals else None


def wd_cfg(bot: str, create: bool = False) -> dict:
    bot = bot.lower().lstrip("@")
    c = WIZ_DAY["bots"].get(bot)
    if c is None and create:
        c = {"on": True, "claim": "oto", "daily": True, "tasks": True, "task_max": 5, "next": 0, "last": 0,
             "daily_day": "", "streak": 0, "fails": 0, "added": time.time(), "today": {}, "hist": [],
             "offset": random.randint(10, 90)}
        WIZ_DAY["bots"][bot] = c
    return c


async def wd_persist():
    await save_json(WD_KEY, WD_FILE, WIZ_DAY)


async def wd_load():
    try:
        data = await load_json(WD_KEY, WD_FILE)
    except Exception:
        data = None
    if isinstance(data, dict):
        for k, v in data.items():
            WIZ_DAY[k] = v
    WIZ_DAY.setdefault("bots", {})
    print(f"[GÜNLÜK] {len(WIZ_DAY['bots'])} bot, {'açık' if WIZ_DAY.get('on') else 'kapalı'}", flush=True)


def wd_in_night() -> bool:
    n = WIZ_DAY.get("night") or []
    if len(n) != 2:
        return False
    h = wd_now_local().tm_hour
    a, b = int(n[0]), int(n[1])
    return a <= h < b if a < b else (h >= a or h < b)


def wd_due(bot: str, c: dict, now: float):
    """(neden, öncelik) ya da None."""
    if not c.get("on", True):
        return None
    if now - float(c.get("last") or 0) < WD_MIN_GAP_MIN * 60:
        return None
    if c.get("now"):
        return ("elle", -1)
    if uni_paused(bot):
        return None
    if int(c.get("fails") or 0) and now < float(c.get("next") or 0):
        return None   # son tur açılamadı → bekleme süresi dolmadan tekrar denenmez
    day = wd_day_key(now)
    lt = time.gmtime(now + WD_TZ_H * 3600)
    minute_of_day = ((lt.tm_hour - int(WIZ_DAY.get("saat") or 0)) % 24) * 60 + lt.tm_min
    if c.get("daily", True) and c.get("daily_day") != day and minute_of_day >= int(c.get("offset") or 30):
        return ("günlük", 0)
    if c.get("claim") != 0 and now >= float(c.get("next") or 0):
        return ("claim", 1)
    return None


def wd_due_list(now: float = None) -> list:
    now = time.time() if now is None else now
    out = []
    for bot, c in WIZ_DAY.get("bots", {}).items():
        d = wd_due(bot, c, now)
        if d:
            out.append((d[1], float(c.get("next") or 0), bot, d[0]))
    out.sort()
    return [(b, why) for _, _, b, why in out]


# ---- tur içi ayarlar: sadece günlük turda geçerli, tur bitince eski haline döner ----

WD_PROMPT_HEAD = (
    "Bir Telegram mini uygulamasının içindesin. Bu bir GÜNLÜK RUTİN turu: amaç bugünün ödüllerini kaçırmamak.\n"
    "Aşağıda ekranın yazısı, tıklanabilir öğeler (id [tür] yazı — bağlam) ve yazı kutuları var.\n"
    "Ekrandaki cümleleri OKU ve SIRADAKİ TEK güvenli adımı seç. Sıra şöyle:\n"
    "1) açık pencereyi kapat/onayla (OK, Close, Continue, Got it)\n"
    "2) GÜNLÜK ÖDÜL: Daily reward / Daily bonus / Check-in / Streak / Day N / Login bonus / Günlük ödül — al. "
    "Takvim (Day 1..7) varsa bugünkü günü seç ve Claim'e bas. Gerekirse ilgili sekmeye (Daily, Rewards, Bonus, Earn) git.\n"
    "3) FARM/MINING: Claim / Collect / Harvest'e bas, sonra yeniden 'Start farming / Start mining / Başlat' ile başlat.\n"
    "4) ücretsiz günlük çark / kutu / hediye (Free spin, Free box, Gift) — sadece ÜCRETSİZ olanlar.\n"
)
WD_PROMPT_TASKS_ON = (
    "5) GÖREVLER: önce günlük görevler (Daily tasks), sonra diğerleri: başlat (Join/Visit/Watch/Play) → "
    "doğrula (Check/Verify/Claim). Bu turda en fazla {n} görev. Gizli kod istiyorsa ve kod ekranda açıkça "
    "yazıyorsa 'yaz' ile yaz, TAHMİN ETME.\n"
)
WD_PROMPT_TASKS_OFF = (
    "5) GÖREV YAPMA: Join / Subscribe / Visit / Follow / Check görevlerine BASMA. Sadece ödül topla.\n"
)
WD_PROMPT_TAIL = (
    "Ödül butonu yerine bir geri sayım görüyorsan (ör. 'Claim in 03:12:45', '3h 12m', '2 saat sonra') "
    "o ödül hazır değildir: üstüne basma, 'sayac' alanına yaz, sıradakine geç.\n"
    "YASAK: cüzdan, ödeme, Stars, TON, satın alma, ücretli yükseltme, davet/arkadaş, paylaş/hikaye, telefon, e-posta. "
    "'Denendi' listesindeki işe yaramamış öğeleri tekrar seçme.\n"
    "Yapacak güvenli bir şey kalmadıysa eylem='bitir'. Yapamadığın bir şey varsa 'sorun' alanına Türkçe nedenini yaz.\n"
    "SADECE şu JSON'u döndür:\n"
    '{"ekran":"ekranın 1 cümle Türkçe özeti","eylem":"tikla|yaz|kaydir|geri|bitir",'
    '"id":"u12 veya w1","metin":"yaz eylemi için","neden":"kısa","sorun":"",'
    '"sayac":"bir sonraki ödüle/claim\'e kalan süre ekranda yazıyorsa (ör. 03:12:45 veya 3h 12m), yoksa boş",'
    '"gunluk":"alindi|zaten|yok|bilinmiyor (günlük ödül durumu)"}\n\n'
)
WD_CANVAS_HEAD = (
    "GÜNLÜK RUTİN TURU: önce günlük ödül / check-in / daily bonus, sonra farm-mining Claim ve yeniden Start, "
    "sonra ücretsiz günlük çark/kutu. Geri sayım varsa o ödül hazır değildir, basma.\n"
)


def wd_prompt(c: dict) -> str:
    tasks = WD_PROMPT_TASKS_ON.format(n=int(c.get("task_max") or 5)) if c.get("tasks", True) else WD_PROMPT_TASKS_OFF
    return WD_PROMPT_HEAD + tasks + WD_PROMPT_TAIL


def wd_active() -> bool:
    return bool(WD_RUN.get("bot")) and WIZ_LIVE.get("source") == "gunluk"


_wd_browser_base = v8_browser


async def v8_browser(name, url, state, _retry: bool = False):
    if not (wd_active() and WD_RUN.get("bot") == name):
        return await _wd_browser_base(name, url, state, _retry)
    c = WD_RUN.get("cfg") or {}
    g = globals()
    keys = ["WIZ_STEP_PROMPT", "WIZ_AI_STEPS", "WIZ_CANVAS_PROMPT", "UNI_JOIN", "UNI_JOIN_MAX", "UNI_TAB_MAX", "UNI_BUDGET_S"]
    saved = {k: g.get(k) for k in keys}
    try:
        g["WIZ_STEP_PROMPT"] = wd_prompt(c)
        g["WIZ_AI_STEPS"] = WD_AI_STEPS
        if not str(saved["WIZ_CANVAS_PROMPT"]).startswith("GÜNLÜK"):
            g["WIZ_CANVAS_PROMPT"] = WD_CANVAS_HEAD + saved["WIZ_CANVAS_PROMPT"]
        if c.get("tasks", True):
            g["UNI_JOIN_MAX"] = min(int(saved["UNI_JOIN_MAX"] or 12), int(c.get("task_max") or 5))
        else:
            g["UNI_JOIN"] = False
            g["UNI_TAB_MAX"] = min(int(saved["UNI_TAB_MAX"] or 40), 8)
        g["UNI_BUDGET_S"] = min(int(saved["UNI_BUDGET_S"] or 300), 240)
        return await _wd_browser_base(name, url, state, _retry)
    finally:
        for k, v in saved.items():
            g[k] = v


_wd_click_base = uni_click


async def uni_click(page, c: dict) -> bool:
    ok = await _wd_click_base(page, c)
    if ok and wd_active():
        WD_RUN.setdefault("clicks", []).append(((c.get("text") or "")[:40], (c.get("ctx") or "")[:140]))
    return ok


_wd_classify_base = uni_classify


def uni_classify(c: dict) -> str:
    k = _wd_classify_base(c)
    if k in ("go", "task") and wd_active() and not (WD_RUN.get("cfg") or {}).get("tasks", True):
        t = (c.get("text") or "") + " " + (c.get("ctx") or "")[:80]
        if not WD_DAILY_RE.search(t):
            return "skip"   # görevler kapalı: sadece ödül / günlük / claim
    return k


_wd_json_base = wiz_json


def wiz_json(text: str):
    d = _wd_json_base(text)
    if isinstance(d, dict) and wd_active():
        s = str(d.get("sayac") or "").strip()
        if s:
            WD_RUN.setdefault("sayac", []).append(s[:40])
        g = str(d.get("gunluk") or "").strip().lower()
        if g in ("alindi", "alındı", "zaten", "yok"):
            WD_RUN["gunluk_ai"] = g.replace("ı", "i")
        y = str(d.get("yazilar") or "")
        if y:
            WD_RUN.setdefault("yazilar", []).append(y[:300])
    return d


_wd_ai_base = wiz_ai_explore


async def wiz_ai_explore(page, name: str, notes: list, state: dict):
    try:
        return await _wd_ai_base(page, name, notes, state)
    finally:
        if wd_active():
            try:
                WD_RUN["end"] = await uni_screen(page)
            except Exception:
                pass


_wd_ref_base = wiz_ref_hunt


async def wiz_ref_hunt(page, name: str, notes: list, state: dict):
    if wd_active():
        try:
            WD_RUN["end"] = await uni_screen(page)
        except Exception:
            pass
        if (REFS.get(name) or {}).get("link"):
            return   # günlük turda referans zaten biliniyorsa vakit harcanmaz
    return await _wd_ref_base(page, name, notes, state)


def wd_analyze(name: str, outcome: str, notes: list) -> dict:
    st = (WIZ_LIVE.get("state") or {}) if isinstance(WIZ_LIVE.get("state"), dict) else {}
    run = st.get("uni_run") or {}
    acts = list(run.get("log") or []) + list((WIZ_CUR or {}).get("ai_log") or [])
    gains = list(run.get("gains") or []) + list((WIZ_CUR or {}).get("ai_gain") or [])
    text_all = "\n".join(notes)
    opened = "Sayfa açıldı" in text_all or bool((WIZ_CUR or {}).get("screens"))
    good = "Evrensel sonuç: OK" in text_all or bool(gains)
    end = WD_RUN.get("end") or next((n for n in notes if n.startswith("Ekran özeti:")), "")
    clicks = WD_RUN.get("clicks") or []
    daily_acts = [t for t, cx in clicks if WD_DAILY_RE.search(t) or (WD_CLAIM_RE.search(t) and WD_DAILY_RE.search(cx))]
    claim_acts = [t for t, cx in clicks if WD_CLAIM_RE.search(t) and t not in daily_acts]
    if not clicks:   # tıklama kaydı yoksa (eski yol) günlük metinden tahmin
        daily_acts = [a for a in acts if WD_DAILY_RE.search(a.split(":", 1)[-1])]
        claim_acts = [a for a in acts if WD_CLAIM_RE.search(a.split(":", 1)[-1]) and a not in daily_acts]
    task_acts = [a for a in acts if re.search(r"/(?:go|task|check):", a)]
    ai_daily = WD_RUN.get("gunluk_ai") or ""
    if ai_daily == "alindi" or (daily_acts and good):
        daily = "alındı"
    elif daily_acts and WD_DONE_RE.search(end or ""):
        daily = "alındı"   # bastı ve ekran 'claimed / come back tomorrow' diyor
    elif ai_daily == "zaten" or (WD_DONE_RE.search(end or "") and not daily_acts):
        daily = "zaten"
    elif daily_acts:
        daily = "basıldı"
    else:
        daily = "yok"
    wait = None
    for s in (WD_RUN.get("sayac") or [])[::-1]:
        wait = wd_parse_wait("next claim in " + s)
        if wait:
            break
    if not wait:
        wait = wd_parse_wait(end) or wd_parse_wait("\n".join(WD_RUN.get("yazilar") or []))
    problems = sorted(set(((WIZ_CUR or {}).get("fails") or []) + ((WIZ_CUR or {}).get("ai_issues") or [])))
    return {"opened": opened, "good": good, "daily": daily, "claims": len(claim_acts), "tasks": len(task_acts),
            "joins": int(run.get("join_ok") or 0), "gains": gains[:6], "wait": wait, "problems": problems[:6],
            "why": "" if opened else (uni_problem_tr(notes) or "mini uygulama açılamadı"), "outcome": outcome}


def wd_schedule(c: dict, r: dict) -> tuple:
    now = time.time()
    if not r["opened"] or r["outcome"] == "err":
        c["fails"] = int(c.get("fails") or 0) + 1
        sec = min(6, c["fails"]) * 3600
        return now + sec, f"hata — {wd_fmt_dur(sec)} sonra tekrar"
    c["fails"] = 0
    if c.get("claim") == "oto" and r.get("wait"):
        sec = int(r["wait"]) + random.randint(120, 600)
        return now + sec, "ekrandaki sayaca göre"
    if isinstance(c.get("claim"), (int, float)) and c["claim"] > 0:
        sec = float(c["claim"]) * 3600 * random.uniform(0.97, 1.05)
        return now + sec, f"her {c['claim']} saatte bir"
    sec = WD_DEFAULT_H * 3600 * random.uniform(0.95, 1.1)
    return now + sec, "sayaç okunamadı, varsayılan aralık"


def wd_report_text(name: str, r: dict, c: dict, how: str) -> str:
    if not r["opened"]:
        return (f"🌅 GÜNLÜK — @{name}\n❌ Açılamadı: {r['why']}\n"
                f"⏰ Tekrar: {wd_fmt_clock(c['next'])} ({how})")
    d = {"alındı": f"✅ alındı (seri {c.get('streak', 1)} gün)", "zaten": "☑️ bugün zaten alınmış",
         "basıldı": "🟡 butona basıldı, ekranda değişim okunamadı", "yok": "— bu uygulamada bulunamadı"}[r["daily"]]
    lines = [f"🌅 GÜNLÜK — @{name}", f"📅 Günlük ödül / check-in: {d}"]
    lines.append(f"🌾 Claim / farm: {r['claims']} kez toplandı" if r["claims"] else
                 ("🌾 Claim / farm: henüz hazır değil (sayaç çalışıyor)" if r.get("wait") else "🌾 Claim / farm: hazır değildi ya da yok"))
    if r["gains"]:
        lines.append("💰 Kazanç: " + ", ".join(r["gains"][:3]))
    if c.get("tasks", True):
        lines.append(f"📋 Görev: {r['tasks']} işlem" + (f", {r['joins']} kanal katılımı" if r["joins"] else ""))
    else:
        lines.append("📋 Görev: kapalı (sadece ödül toplandı)")
    if r["problems"]:
        lines.append("⚠️ Yapamadıkları: " + " · ".join(p[:80] for p in r["problems"][:3]))
    lines.append(f"⏰ Sonraki tur: {wd_fmt_clock(c['next'])} ({wd_fmt_dur(c['next'] - time.time())} sonra, {how})")
    return "\n".join(lines)


async def wd_apply_result(name: str, r: dict):
    c = wd_cfg(name, create=True)
    now = time.time()
    day = wd_day_key(now)
    if r["daily"] in ("alındı", "zaten"):
        if c.get("daily_day") != day:
            yday = wd_day_key(now - 86400)
            if r["daily"] == "alındı":
                c["streak"] = int(c.get("streak") or 0) + 1 if c.get("daily_day") == yday else 1
            c["daily_day"] = day
    elif r["opened"] and WD_RUN.get("why") == "günlük":
        # günlük ödül bulunamadı: bugün bir kez denendi say, claim turlarında yine aranır
        c["daily_day"] = day
    c["next"], how = wd_schedule(c, r)
    c["last"] = now
    t = c.get("today") or {}
    if t.get("day") != day:
        t = {"day": day, "runs": 0, "claims": 0, "tasks": 0, "gains": [], "daily": "", "err": 0}
    t["runs"] += 1
    t["claims"] += r["claims"]
    t["tasks"] += r["tasks"]
    t["gains"] = (t.get("gains", []) + r["gains"])[-6:]
    if r["daily"] in ("alındı", "zaten"):
        t["daily"] = r["daily"]
    if not r["opened"]:
        t["err"] = int(t.get("err") or 0) + 1
    c["today"] = t
    c["hist"] = (c.get("hist", []) + [{"t": now, "d": r["daily"], "c": r["claims"], "k": r["tasks"],
                                        "ok": r["opened"], "w": int(r["wait"] or 0)}])[-12:]
    paused = False
    if int(c.get("fails") or 0) >= 5:
        c["on"] = False
        paused = True
    await wd_persist()
    mode = WIZ_DAY.get("report", "ozet")
    text = wd_report_text(name, r, c, how)
    if paused:
        text += "\n⏸ Üst üste 5 kez açılamadı, bu bot günlük listede durduruldu. Açmak için: günlük " + name + " devam"
    important = r["daily"] == "alındı" or r["claims"] or r["gains"] or not r["opened"] or paused
    if mode == "detay" or (mode == "ozet" and important) or (WD_RUN.get("manual")):
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("⚙️ Ayarlar", callback_data=f"gd:s:{name}"[:64]),
                                    InlineKeyboardButton("▶️ Şimdi tekrar", callback_data=f"gd:r:{name}"[:64])]])
        try:
            await bot_app.bot.send_message(ADMIN_USER_ID, text, reply_markup=kb, disable_web_page_preview=True)
        except Exception as e:
            print("[GÜNLÜK RAPOR]", repr(e), flush=True)


_wd_finish_base = wiz_finish


async def wiz_finish(name: str, outcome: str, notes: list, source: str):
    if source == "gunluk":
        r = wd_analyze(name, outcome, notes)
        WD_RUN["done"] = True
        link, _src = wiz_best_ref() if WIZ_CUR else ("", "")
        if link and not (REFS.get(name) or {}).get("link"):
            REFS[name] = {"link": link, "src": "sihirbaz/günlük", "t": time.time()}
            await persist_refs()
        await wd_apply_result(name, r)
        return
    await _wd_finish_base(name, outcome, notes, source)
    # sihirbazın açabildiği her yeni mini app günlük listeye eklenir (istersen: günlük oto kapalı)
    try:
        text_all = "\n".join(notes)
        opened = "Sayfa açıldı" in text_all
        if WIZ_DAY.get("auto_add", True) and opened and outcome != "err" and not wd_cfg(name):
            c = wd_cfg(name, create=True)
            r = wd_analyze(name, outcome, notes)
            c["next"] = time.time() + (r["wait"] + random.randint(120, 600) if r.get("wait") else WD_DEFAULT_H * 3600)
            c["last"] = time.time()
            await wd_persist()
            await bot_app.bot.send_message(
                ADMIN_USER_ID, f"🌅 @{name} günlük rutine eklendi: günlük ödül + claim takibi. "
                               f"İlk claim turu {wd_fmt_clock(c['next'])}. Ayar: günlük {name}")
    except Exception as e:
        print("[GÜNLÜK OTO EKLE]", repr(e), flush=True)


async def wd_run(bot: str, why: str = "claim", manual: bool = False):
    c = wd_cfg(bot, create=True)
    WD_RUN.clear()
    c.pop("now", None)
    WD_RUN.update({"bot": bot, "t0": time.time(), "cfg": dict(c), "why": why, "manual": manual or why == "elle"})
    try:
        res = await asyncio.wait_for(v8_run_and_track(bot, source="gunluk"), V8_JOB_TIMEOUT + 300)
        outcome, notes = res if isinstance(res, tuple) else ("err", ["sonuç yok"])
    except asyncio.CancelledError:
        WD_RUN.clear()
        raise
    except Exception as e:
        outcome, notes = "err", [f"Hata: {type(e).__name__}"]
    try:
        if not WD_RUN.get("done"):
            # tarayıcıya hiç girilmedi (atlandı / hata) → yine de sonraki tur kurulur
            await wd_apply_result(bot, {"opened": False, "good": False, "daily": "yok", "claims": 0, "tasks": 0,
                                        "joins": 0, "gains": [], "wait": None, "problems": [],
                                        "why": (uni_problem_tr(notes) or (notes[0] if notes else "hata"))[:160],
                                        "outcome": "err"})
    finally:
        WD_RUN.clear()
    return outcome, notes


def wd_digest_text() -> str:
    day = wd_day_key()
    bots = WIZ_DAY.get("bots", {})
    if not bots:
        return "🌅 Günlük listede bot yok. Eklemek için: günlük ekle botadi  (ya da: günlük ekle hepsi)"
    lines = [f"📅 GÜNLÜK RAPOR — {day}", ""]
    n_daily = n_claim = n_err = 0
    for b, c in sorted(bots.items()):
        t = c.get("today") or {}
        if t.get("day") != day:
            t = {}
        dly = t.get("daily") or ""
        n_daily += dly in ("alındı", "zaten")
        n_claim += int(t.get("claims") or 0)
        n_err += 1 if t.get("err") else 0
        icon = "⏸" if not c.get("on", True) else ("✅" if dly else ("❌" if t.get("err") else "⏳"))
        part = [f"günlük: {dly or ('kapalı' if not c.get('daily', True) else 'henüz yok')}"]
        if t.get("claims"):
            part.append(f"claim {t['claims']}")
        if t.get("tasks"):
            part.append(f"görev {t['tasks']}")
        if c.get("streak"):
            part.append(f"seri {c['streak']}")
        if t.get("gains"):
            part.append(", ".join(t["gains"][-2:]))
        if c.get("on", True) and c.get("next"):
            part.append(f"sonraki {wd_fmt_clock(c['next'])}")
        lines.append(f"{icon} @{b} — " + " · ".join(part))
    lines += ["", f"Toplam: {n_daily}/{len(bots)} günlük ödül · {n_claim} claim · {n_err} açılamayan"]
    return "\n".join(lines)[:3900]


def wd_card(bot: str):
    c = wd_cfg(bot)
    if not c:
        return f"@{bot} günlük listede yok. Eklemek için: günlük ekle {bot}", None
    claim = "oto (ekrandaki sayaca göre)" if c.get("claim") == "oto" else f"her {c.get('claim')} saatte bir"
    last = c.get("hist", [])[-1:] or [{}]
    h = last[0]
    lines = [f"⚙️ @{bot} — günlük rutin ayarları",
             f"Durum: {'açık' if c.get('on', True) else 'DURDURULDU'}",
             f"⏱ Claim / farm: {claim}",
             f"📅 Günlük ödül / check-in: {'açık' if c.get('daily', True) else 'kapalı'}"
             + (f" · bugün: {c['today'].get('daily')}" if (c.get('today') or {}).get('day') == wd_day_key()
                and c['today'].get('daily') else ""),
             f"📋 Görev yapma: {'açık, turda en fazla ' + str(c.get('task_max', 5)) if c.get('tasks', True) else 'kapalı'}",
             f"🔥 Seri: {c.get('streak', 0)} gün"]
    if h:
        lines.append(f"Son tur: {wd_fmt_dur(time.time() - h['t'])} önce — "
                     + ("açılamadı" if not h.get("ok") else f"günlük {h.get('d')}, claim {h.get('c')}, görev {h.get('k')}"))
    if c.get("on", True) and c.get("next"):
        lines.append(f"Sonraki: {wd_fmt_clock(c['next'])} ({wd_fmt_dur(c['next'] - time.time())} sonra)")
    b = bot[:40]
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"⏱ Claim: {c.get('claim')}" + ("" if c.get("claim") == "oto" else " sa"), callback_data=f"gd:c:{b}"),
         InlineKeyboardButton(f"📅 Günlük: {'açık' if c.get('daily', True) else 'kapalı'}", callback_data=f"gd:d:{b}")],
        [InlineKeyboardButton(f"📋 Görev: {'açık' if c.get('tasks', True) else 'kapalı'}", callback_data=f"gd:t:{b}"),
         InlineKeyboardButton(f"🔢 Görev limiti: {c.get('task_max', 5)}", callback_data=f"gd:n:{b}")],
        [InlineKeyboardButton("▶️ Şimdi çalıştır", callback_data=f"gd:r:{b}"),
         InlineKeyboardButton("⏸ Durdur" if c.get("on", True) else "▶️ Devam", callback_data=f"gd:p:{b}"),
         InlineKeyboardButton("🗑 Çıkar", callback_data=f"gd:x:{b}")],
    ])
    return "\n".join(lines), kb


def wd_list():
    bots = WIZ_DAY.get("bots", {})
    head = (f"🌅 GÜNLÜK RUTİN: {'AÇIK' if WIZ_DAY.get('on') else 'KAPALI'} · rapor: {WIZ_DAY.get('report')}"
            + (f" · gece {WIZ_DAY['night'][0]}-{WIZ_DAY['night'][1]} arası çalışmaz" if len(WIZ_DAY.get('night') or []) == 2 else "")
            + f" · yeni mini app'ler otomatik eklenir: {'evet' if WIZ_DAY.get('auto_add', True) else 'hayır'}")
    if WD_RUN.get("bot"):
        head += f"\n▶️ Şu an çalışıyor: @{WD_RUN['bot']} ({WD_RUN.get('why')})"
    if not bots:
        return head + "\n\nListe boş. Eklemek için: günlük ekle botadi  ya da  günlük ekle hepsi\n\n" + WD_HELP, None
    lines = [head, ""]
    rows = []
    items = sorted(bots.items(), key=lambda kv: float(kv[1].get("next") or 0))
    for b, c in items:
        t = c.get("today") or {}
        dly = t.get("daily") if t.get("day") == wd_day_key() else ""
        st = "⏸" if not c.get("on", True) else ("✅" if dly else "⏳")
        nx = f"{wd_fmt_clock(c['next'])}" if c.get("next") and c.get("on", True) else "-"
        lines.append(f"{st} @{b} · claim {c.get('claim')}{'' if c.get('claim') == 'oto' else ' sa'} · "
                     f"görev {'açık' if c.get('tasks', True) else 'kapalı'} · sonraki {nx}")
        if len(rows) < 24:
            rows.append(InlineKeyboardButton(f"⚙️ {b}"[:30], callback_data=f"gd:s:{b[:40]}"))
    kb = InlineKeyboardMarkup([rows[i:i + 2] for i in range(0, len(rows), 2)]) if rows else None
    return "\n".join(lines)[:3800] + "\n\nAyarlamak için bir bota dokun ya da yaz: günlük botadi", kb


WD_HELP = (
    "🌅 GÜNLÜK RUTİN (günlük ödül · check-in · claim · görev)\n"
    "• günlük — liste + ayar butonları  ·  günlük rapor — bugünün raporu\n"
    "• günlük ekle bot1 bot2  ·  günlük ekle hepsi  ·  günlük sil botadi\n"
    "• günlük botadi — o botun ayar kartı (butonlarla değiştir)\n"
    "• günlük botadi claim oto | 4  (oto = ekrandaki sayaca göre, sayı = saat)\n"
    "• günlük botadi görev açık | kapalı | 10  ·  günlük botadi ödül açık | kapalı\n"
    "• günlük botadi durdur | devam  ·  günlük şimdi botadi\n"
    "• günlük aç | kapat  ·  günlük rapor sessiz | özet | detay\n"
    "• günlük gece 2-7 (bu saatlerde çalışmaz) | günlük gece kapalı  ·  günlük saat 3 (gün dönümü)\n"
    "• günlük oto açık | kapalı — sihirbazın açtığı yeni mini app'ler otomatik eklensin mi"
)


def wd_bot_names(raw_tokens: list) -> list:
    out = []
    for t in raw_tokens:
        t = re.sub(r"^https?://t\.me/", "", t.strip().strip(",")).split("/")[0].split("?")[0].lstrip("@").lower()
        if re.fullmatch(r"[a-z0-9_]{3,40}", t):
            out.append(t)
    return out


async def wd_set(bot: str, key: str, val: str) -> str:
    c = wd_cfg(bot)
    if not c:
        return f"@{bot} günlük listede yok. Önce: günlük ekle {bot}"
    on = val in ("ac", "acik", "on", "evet", "1")
    off = val in ("kapat", "kapali", "off", "hayir", "0")
    if key in ("claim", "farm", "topla"):
        if val in ("oto", "otomatik", "auto"):
            c["claim"] = "oto"
        else:
            try:
                h = float(val.replace(",", "."))
            except ValueError:
                return "Kullanım: günlük botadi claim oto | 4"
            if h < 0.5 or h > 48:
                return "Claim aralığı 0.5 ile 48 saat arasında olmalı."
            c["claim"] = int(h) if h == int(h) else h
            c["next"] = min(float(c.get("next") or 0) or time.time() + h * 3600, time.time() + h * 3600)
    elif key in ("gorev", "gorevler", "task", "tasks"):
        if on:
            c["tasks"] = True
        elif off:
            c["tasks"] = False
        elif val.isdigit():
            c["tasks"], c["task_max"] = True, max(1, min(30, int(val)))
        else:
            return "Kullanım: günlük botadi görev açık | kapalı | 10"
    elif key in ("odul", "daily", "gunluk", "checkin"):
        if not (on or off):
            return "Kullanım: günlük botadi ödül açık | kapalı"
        c["daily"] = on
    elif key in ("durdur", "dur", "kapat"):
        c["on"] = False
    elif key in ("devam", "baslat", "ac"):
        c["on"], c["fails"], c["next"] = True, 0, time.time()
    else:
        return "Bilinmeyen ayar. " + WD_HELP
    await wd_persist()
    return wd_card(bot)[0]


async def wd_start_now(bot: str) -> str:
    c = wd_cfg(bot, create=True)
    if WD_RUN.get("bot") or WIZ_QUEUE or (globals().get("WIZ_RUN_LOCK") is not None and WIZ_RUN_LOCK.locked()):
        c["on"], c["now"] = True, True
        await wd_persist()
        return f"⏳ Şu an başka bir iş çalışıyor. @{bot} günlük sırasında en öne alındı, o bitince başlar."
    c["on"] = True
    c["next"] = 0
    c["last"] = 0
    await wd_persist()
    spawn(wd_run(bot, "elle", manual=True))
    return f"▶️ @{bot} günlük turu başladı (günlük ödül → claim → {'görevler' if c.get('tasks', True) else 'görev yok'}). Bitince rapor gelir."


async def wiz_day_cmd(msg, text: str, low: str) -> bool:
    toks = low.split()
    if not toks or toks[0] not in ("gunluk", "gunlukler", "daily", "rutinler"):
        return False
    raw = text.split()
    args = toks[1:]
    if not args or args[0] in ("liste", "list"):
        t, kb = wd_list()
        await msg.reply_text(t, reply_markup=kb)
        return True
    a0 = args[0]
    if a0 in ("ac", "acik", "on", "kapat", "kapali", "off") and len(args) == 1:
        WIZ_DAY["on"] = a0 in ("ac", "acik", "on")
        await wd_persist()
        await msg.reply_text(f"🌅 Günlük rutin {'AÇIK' if WIZ_DAY['on'] else 'KAPALI'}."
                             + (f" {len(WIZ_DAY['bots'])} bot takipte." if WIZ_DAY["on"] else ""))
        return True
    if a0 in ("yardim", "komutlar", "help"):
        await msg.reply_text(WD_HELP)
        return True
    if a0 == "rapor":
        if len(args) > 1 and args[1] in ("sessiz", "ozet", "detay"):
            WIZ_DAY["report"] = args[1]
            await wd_persist()
            await msg.reply_text({"sessiz": "Rapor: sessiz — tur başına mesaj yok, sadece akşam gün raporu.",
                                  "ozet": "Rapor: özet — sadece ödül alınınca / hata olunca mesaj.",
                                  "detay": "Rapor: detay — her turdan sonra mesaj."}[args[1]])
        else:
            await msg.reply_text(wd_digest_text())
        return True
    if a0 in ("sessiz", "ozet", "detay"):
        WIZ_DAY["report"] = a0
        await wd_persist()
        await msg.reply_text(f"Rapor modu: {a0}")
        return True
    if a0 == "gece":
        if len(args) > 1 and args[1] in ("kapali", "kapat", "yok"):
            WIZ_DAY["night"] = []
        else:
            m = re.match(r"(\d{1,2})\s*-\s*(\d{1,2})", " ".join(args[1:]))
            if not m:
                await msg.reply_text("Kullanım: günlük gece 2-7  (02:00–07:00 arası çalışmaz)  ·  günlük gece kapalı")
                return True
            WIZ_DAY["night"] = [int(m.group(1)) % 24, int(m.group(2)) % 24]
        await wd_persist()
        await msg.reply_text("Gece arası: " + (f"{WIZ_DAY['night'][0]}:00–{WIZ_DAY['night'][1]}:00 çalışmaz"
                                               if WIZ_DAY["night"] else "kapalı (her saat çalışır)"))
        return True
    if a0 == "saat" and len(args) > 1 and args[1].isdigit():
        WIZ_DAY["saat"] = int(args[1]) % 24
        await wd_persist()
        await msg.reply_text(f"Gün dönümü saati {WIZ_DAY['saat']:02d}:00 (bu saatten sonra yeni günün günlük ödülü alınır).")
        return True
    if a0 == "oto" and len(args) > 1:
        WIZ_DAY["auto_add"] = args[1] in ("ac", "acik", "on", "evet")
        await wd_persist()
        await msg.reply_text("Yeni mini app'ler günlük listeye " + ("otomatik eklenecek." if WIZ_DAY["auto_add"] else "eklenmeyecek."))
        return True
    if a0 == "ekle":
        names = wd_bot_names(raw[2:])
        if args[1:2] == ["hepsi"]:
            names = list(dict.fromkeys(
                [b for b in v8_ap_bots()] +
                [b for b, s in WIZ_SUM.items() if "Açılamadı" not in str(s.get("summary", ""))
                 and "mini uygulama değil" not in str(s.get("summary", ""))]))
        if not names:
            await msg.reply_text("Kullanım: günlük ekle bot1 bot2  ·  günlük ekle hepsi")
            return True
        added = []
        for i, b in enumerate(names):
            if not wd_cfg(b):
                c = wd_cfg(b, create=True)
                c["next"] = time.time() + 60 + i * 300   # hepsi aynı anda açılmasın (5 dk arayla)
                added.append(b)
        await wd_persist()
        await msg.reply_text((f"🌅 {len(added)} bot günlük rutine eklendi: " + ", ".join("@" + b for b in added[:30])
                              if added else "Bunlar zaten listede.")
                             + "\nİlk turlar sırayla, 5 dk arayla başlar. Ayar: günlük")
        return True
    if a0 in ("sil", "cikar"):
        names = wd_bot_names(raw[2:])
        n = sum(1 for b in names if WIZ_DAY["bots"].pop(b, None) is not None)
        await wd_persist()
        await msg.reply_text(f"{n} bot günlük listeden çıkarıldı." if n else "Bu bot listede yok. Bak: günlük")
        return True
    if a0 in ("simdi", "calistir", "baslat") and len(args) > 1:
        await msg.reply_text(await wd_start_now(wd_bot_names(raw[2:3])[0] if wd_bot_names(raw[2:3]) else args[1]))
        return True
    names = wd_bot_names(raw[1:2])
    if names:
        b = names[0]
        if len(args) == 1:
            t, kb = wd_card(b)
            await msg.reply_text(t, reply_markup=kb)
            return True
        if args[1] in ("simdi", "calistir"):
            await msg.reply_text(await wd_start_now(b))
            return True
        await msg.reply_text(await wd_set(b, args[1], args[2] if len(args) > 2 else ""))
        return True
    await msg.reply_text(WD_HELP)
    return True


_wd_cb_base = on_callback


async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not (q and q.data and q.data.startswith("gd:")):
        return await _wd_cb_base(update, context)
    if not update.effective_user or update.effective_user.id != ADMIN_USER_ID:
        await q.answer("Yetkin yok.")
        return
    _, op, bot = (q.data.split(":", 2) + ["", ""])[:3]
    c = wd_cfg(bot)
    note = ""
    if op == "r":
        note = await wd_start_now(bot)
        await q.answer("Başladı")
        await bot_app.bot.send_message(ADMIN_USER_ID, note)
        return
    if op != "s" and not c:
        await q.answer("Bu bot listede yok.")
        return
    if op == "c":
        cur = c.get("claim")
        i = WD_CLAIM_STEPS.index(cur) if cur in WD_CLAIM_STEPS else 0
        c["claim"] = WD_CLAIM_STEPS[(i + 1) % len(WD_CLAIM_STEPS)]
        if c["claim"] != "oto":
            c["next"] = min(float(c.get("next") or 0) or 9e12, time.time() + c["claim"] * 3600)
    elif op == "d":
        c["daily"] = not c.get("daily", True)
    elif op == "t":
        c["tasks"] = not c.get("tasks", True)
    elif op == "n":
        cur = int(c.get("task_max") or 5)
        nx = [v for v in WD_TASK_STEPS if v > cur]
        c["task_max"] = nx[0] if nx else WD_TASK_STEPS[0]
        c["tasks"] = True
    elif op == "p":
        c["on"] = not c.get("on", True)
        if c["on"]:
            c["fails"], c["next"] = 0, time.time() + 60
    elif op == "x":
        WIZ_DAY["bots"].pop(bot, None)
        await wd_persist()
        await q.answer("Çıkarıldı")
        try:
            await q.edit_message_text(f"🗑 @{bot} günlük listeden çıkarıldı.")
        except Exception:
            pass
        return
    if op != "s":
        await wd_persist()
    await q.answer()
    t, kb = wd_card(bot)
    try:
        if op == "s":
            await bot_app.bot.send_message(ADMIN_USER_ID, t, reply_markup=kb)
        else:
            await q.edit_message_text(t, reply_markup=kb)
    except Exception:
        pass


async def wd_tick():
    now = time.time()
    # akşam gün raporu (sessiz/özet modda tek mesaj)
    lt = wd_now_local()
    today = time.strftime("%Y-%m-%d", lt)
    if WIZ_DAY.get("bots") and lt.tm_hour >= int(WIZ_DAY.get("digest_h", 21)) and WIZ_DAY.get("digest_day") != today:
        WIZ_DAY["digest_day"] = today
        await wd_persist()
        try:
            await bot_app.bot.send_message(ADMIN_USER_ID, wd_digest_text())
        except Exception as e:
            print("[GÜNLÜK RAPOR]", repr(e), flush=True)
    if not WIZ_DAY.get("on") or WD_RUN.get("bot") or wd_in_night():
        return
    lock = globals().get("WIZ_RUN_LOCK")
    if (lock is not None and lock.locked()) or WIZ_QUEUE:
        return   # elle başlatılan / otopilot işi varsa beklenir, sıraya yığılmaz
    try:
        if wiz_mem_used_mb() > wiz_mem_limit_mb() * 0.8:
            return
    except Exception:
        pass
    due = wd_due_list(now)
    if not due:
        return
    bot, why = due[0]
    spawn(wd_run(bot, why))


async def wd_loop():
    await asyncio.sleep(120)
    print("[GÜNLÜK] planlayıcı çalışıyor", flush=True)
    while True:
        try:
            await wd_tick()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            print("[GÜNLÜK LOOP]", repr(e), flush=True)
        await asyncio.sleep(45)


_wd_load_base = load_v8_ap


async def load_v8_ap():
    await _wd_load_base()
    await wd_load()
    if not WD_STARTED["on"]:
        WD_STARTED["on"] = True
        spawn(wd_loop())
        # V8'de kapalı kalan eski döngüler: API ile otomatik toplama (/topla) ve buton rutinleri (/rutin)
        if os.getenv("WIZ_API_CLAIMS", "1").strip() != "0":
            spawn(claims_loop())
        if ROUTINES_ON:
            spawn(routine_loop())
        print(f"[GÜNLÜK] başlatıldı · API toplama: {len(CLAIMS)} · buton rutini: {len(ROUTINES)}", flush=True)


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
    print("AIRDROP RADARI v3 + V8.33 EVRENSEL MINI APP + V9 GROQ SIHIRBAZI")
    print("=" * 60)
    print("[KONFIG] ADMIN =", ADMIN_USER_ID)
    print("[KONFIG] PORT =", PORT)
    print("[KONFIG] GROQ =", (" > ".join(GROQ_CHAIN)) if GROQ_API_KEY else "yok")
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

    bot_app = Application.builder().token(BOT_TOKEN).concurrent_updates(8).build()  # bir komut takılsa da diğerleri cevaplanır
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
    bot_app.add_handler(CommandHandler("gorev", cmd_gorev))
    bot_app.add_handler(CommandHandler("dur", cmd_dur))
    bot_app.add_handler(CommandHandler("otopilot", cmd_otopilot))
    bot_app.add_handler(CommandHandler("cik", cmd_cik))
    bot_app.add_handler(CommandHandler("yetkiler", cmd_yetkiler))
    bot_app.add_handler(CommandHandler("rutin", cmd_rutin))
    bot_app.add_handler(CommandHandler("status", cmd_status))
    bot_app.add_handler(CallbackQueryHandler(on_callback))
    bot_app.add_handler(MessageHandler((filters.TEXT | filters.CAPTION) & ~filters.COMMAND, on_text))

    await bot_app.initialize()
    await bot_app.start()
    await bot_app.updater.start_polling(drop_pending_updates=False)  # DÜZELTME: kapalıyken yazılanlar kaybolmaz

    spawn(keepalive_loop())
    await load_v8_ap()
    spawn(v8_autopilot_loop())
    print("[V8] otopilot döngüsü hazır (kapalı; 'otopilot aç' ile çalışır)", flush=True)
    print("[V9.6] günlük rutin + API toplama + buton rutinleri load_v8_ap içinde başlatılıyor", flush=True)

    try:
        await bot_app.bot.send_message(
            ADMIN_CHAT_ID,
            f"Radar aktif (v3 + V8 otopilot + 🧙 V9 Groq Sihirbazı)\nDinlenen: {len(ACTIVE_SOURCES)}\n"
            f"Groq: {'acik' if GROQ_API_KEY else 'kapali'} · Sihirbaz: {'AÇIK' if V8_AP.get('wiz_on') else 'kapalı'}"
            f" · AI görev: {'AÇIK' if V8_AP.get('wiz_ai') else 'kapalı'}\n"
            f"V8 otopilot: {'AÇIK' if V8_AP.get('on') else 'kapalı'} "
            f"({V8_AP.get('min_m')}-{V8_AP.get('max_m')} dk)\n\n"
            f"Özel sohbet: @botadi  |  otopilot hepsi  |  otopilot aç  |  özetler  |  sihirbaz  |  dur",
        )
    except Exception as e:
        print("[ADMIN MSG HATA]", repr(e))

    print(f"[BELLEK] açılış: {wiz_mem_used_mb()} MB / {wiz_mem_limit_mb()} MB", flush=True)
    print("[HAZIR] Bot komutlari + Telethon + HTTP")
    # DÜZELTME: Telethon bağlantısı koparsa program kapanmaz, yeniden bağlanır
    fails = 0
    while True:
        try:
            await tg_client.run_until_disconnected()
        except Exception as e:
            print("[TELETHON] bağlantı hatası:", repr(e), flush=True)
            if "AuthKey" in type(e).__name__ or "Unauthorized" in type(e).__name__:
                try:
                    await bot_app.bot.send_message(ADMIN_USER_ID, "❌ Telegram hesabı oturumu geçersiz oldu (başka yerde açılmış olabilir). "
                                                                  "TG_SESSION yenilenmeli.")
                except Exception:
                    pass
                raise
        fails += 1
        print(f"[TELETHON] bağlantı koptu, yeniden bağlanılıyor ({fails})", flush=True)
        await asyncio.sleep(min(60, 5 * fails))
        try:
            await tg_client.connect()
            if await tg_client.is_user_authorized():
                fails = 0
        except Exception as e:
            print("[TELETHON] yeniden bağlanma hatası:", repr(e), flush=True)


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
