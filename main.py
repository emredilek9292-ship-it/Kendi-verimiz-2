"""
Airdrop / oyun bot radari (v3 + Groq)

- Grup dinleme (Telethon)
- Bot/airdrop yakalama + Turkce ozet (Groq oncelik, Gemini yedek)
- /incele : bota /start, cevabi oku, rapor
- Komutlar: /add /del /list /incele /bil /status
- Otomatik kanal katilimi YOK
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import time
from typing import Optional, Set

import aiohttp
from aiohttp import web
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.utils import get_peer_id
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

# ===================== ENV =====================

API_ID = int(os.getenv("API_ID", "0") or 0)
API_HASH = os.getenv("API_HASH", "").strip()
STRING_SESSION = os.getenv("STRING_SESSION", "").strip()

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_USER_ID = int(os.getenv("ADMIN_USER_ID", "0") or os.getenv("ADMIN_CHAT_ID", "0") or 0)
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID", "0") or ADMIN_USER_ID or 0)

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile").strip()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip()

DEDUP_TTL = int(os.getenv("DEDUP_TTL", "86400") or 86400)
PORT = int(os.getenv("PORT", "10000") or 10000)

ONLY_BOTS = os.getenv("ONLY_BOTS", "0").strip() != "0"
INSPECT = os.getenv("INSPECT", "1").strip() != "0"
INSPECT_MIN_INTERVAL = int(os.getenv("INSPECT_MIN_INTERVAL", "120") or 120)
INSPECT_WAIT = int(os.getenv("INSPECT_WAIT", "7") or 7)
KEEPALIVE = os.getenv("KEEPALIVE", "1").strip() != "0"
RENDER_URL = os.getenv("RENDER_EXTERNAL_URL", "").strip().rstrip("/")

SOURCE_CHATS_EXTRA = os.getenv("SOURCE_CHATS_EXTRA", "").strip()
UPSTASH_REDIS_REST_URL = os.getenv("UPSTASH_REDIS_REST_URL", "").strip().rstrip("/")
UPSTASH_REDIS_REST_TOKEN = os.getenv("UPSTASH_REDIS_REST_TOKEN", "").strip()
SOURCES_KEY = os.getenv("SOURCES_KEY", "radar:source_chats:v1").strip()
SOURCES_FILE = os.getenv("SOURCES_FILE", "/tmp/radar_sources.json")
SEEN_KEY = os.getenv("SEEN_KEY", "radar:seen_bots:v1").strip()
SEEN_FILE = os.getenv("SEEN_FILE", "/tmp/radar_seen.json")
SEEN_MAX = int(os.getenv("SEEN_MAX", "3000") or 3000)

# ===================== FILTRE =====================

# VictorEmpireBot/app?startapp=... dahil
BOT_LINK_RE = re.compile(
    r"(?:t\.me|telegram\.me)/([A-Za-z0-9_]{3,})(?:/app|/start)?(?:\?|/|$|\b)",
    re.I,
)

LINK_RE = re.compile(
    r"(https?://(?:t\.me|telegram\.me)/[A-Za-z0-9_+/.?=&%-]+|"
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

SKIP_USERNAMES = {
    "joinchat", "share", "proxy", "socks", "addstickers", "s", "c", "iv", "login",
}

BAD_WORDS = [
    "seed phrase", "secret phrase", "recovery phrase", "mnemonic",
    "private key", "wallet connect", "connect wallet", "connect your wallet",
    "deposit", "cüzdan bağla", "yatırım yap",
]

# ===================== STATE =====================

seen: dict[str, float] = {}
ACTIVE_SOURCES: Set[int] = set()
SOURCE_META: dict[int, str] = {}
INSPECT_COOLDOWN: dict[str, float] = {}
http_session: Optional[aiohttp.ClientSession] = None
tg_client: Optional[TelegramClient] = None
bot_app: Optional[Application] = None
TG_LOCK: Optional[asyncio.Lock] = None
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


def admin_only(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        if not user or user.id != ADMIN_USER_ID:
            if update.effective_message:
                await update.effective_message.reply_text("Yetkin yok.")
            return
        return await func(update, context)
    return wrapper


def extract_bot_names(text: str) -> list[str]:
    names = []
    for m in BOT_LINK_RE.findall(text or ""):
        name = m.lower().strip()
        if not name or name in SKIP_USERNAMES or name.startswith("+"):
            continue
        names.append(name)
    # sadece bot benzeri: ...bot ile biter veya startapp/app linkinden geldi
    out = []
    for n in names:
        if n.endswith("bot") or "bot" in n:
            out.append(n)
    return list(dict.fromkeys(out))


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
    lines.append("\nEkle: /add -100...\nSil: /del -100... veya buton")
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


# ===================== AI (Groq + Gemini) =====================

GUIDE_PROMPT = (
    "Asagidaki Telegram mesaji bir oyun / airdrop botunu tanitiyor. "
    "Cevabi TURKCE yaz. SADECE mesajdaki bilgiyi kullan, uydurma. Format:\n"
    "Oyun: <ad>\n"
    "Ne yapilir: <1-2 cumle>\n"
    "Baslangic:\n1. ...\n2. ...\n"
    "Token/airdrop: <varsa / belirsiz>\n"
    "En fazla 900 karakter.\n\nMESAJ:\n"
)

INSPECT_PROMPT = (
    "Asagida bir Telegram botunun /start cevabi ve butonlari var. "
    "TURKCE yaz, uydurma. Format:\n"
    "Bu ne: <1 cumle>\n"
    "Yapilacaklar:\n1. ...\n"
    "Dikkat: <cuzdan/odeme istiyorsa yaz, yoksa yok>\n"
    "En fazla 700 karakter.\n\nBILGI:\n"
)


async def ai_guide(text: str, prompt: str = GUIDE_PROMPT) -> str:
    text = (text or "").strip()
    if not text:
        return "(bos)"
    full_prompt = prompt + text[:6000]
    assert http_session is not None

    # Groq oncelik
    if GROQ_API_KEY:
        try:
            async with http_session.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {GROQ_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": GROQ_MODEL,
                    "messages": [
                        {
                            "role": "system",
                            "content": "Kisa net Turkce yaz. Uydurma.",
                        },
                        {"role": "user", "content": full_prompt},
                    ],
                    "temperature": 0.2,
                    "max_tokens": 1024,
                },
                timeout=aiohttp.ClientTimeout(total=45),
            ) as resp:
                data = await resp.json()
                if resp.status < 400:
                    raw = (
                        (data.get("choices") or [{}])[0]
                        .get("message", {})
                        .get("content", "")
                        .strip()
                    )
                    if raw:
                        return raw
                print("[GROQ]", resp.status, str(data)[:300])
        except Exception as e:
            print("[GROQ EX]", repr(e))

    # Gemini yedek
    if not GEMINI_API_KEY:
        return "(Ozet yok - GROQ/GEMINI key yok veya hata)"

    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
    )
    payload = {
        "contents": [{"parts": [{"text": full_prompt}]}],
        "generationConfig": {"temperature": 0.2, "maxOutputTokens": 1024},
    }
    try:
        async with http_session.post(
            url, json=payload, timeout=aiohttp.ClientTimeout(total=45)
        ) as resp:
            data = await resp.json()
            if resp.status >= 400:
                print("[GEMINI]", resp.status, str(data)[:250])
                return f"(Gemini hatasi {resp.status})"
            parts = (data.get("candidates") or [{}])[0].get("content", {}).get("parts", [])
            raw = "\n".join(p.get("text", "") for p in parts).strip()
            return raw or "(Ozet bos)"
    except Exception as e:
        print("[GEMINI EX]", repr(e))
        return f"(Gemini hata: {type(e).__name__})"


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
    elif tg_client:
        await tg_client.send_message(ADMIN_CHAT_ID, text, link_preview=False)


async def notify_admin(source_title, text, bots, links, guide, warn):
    lines = ["YENI OYUN / AIRDROP", f"Grup: {source_title}", ""]
    lines.append(guide or "(Mesajda aciklama yok veya AI ozet yok.)")
    if warn:
        lines += ["", "Dikkat: " + ", ".join(warn)]
    lines.append("")
    if bots:
        lines += [f"https://t.me/{b}" for b in bots]
    else:
        lines += [f"{u}" for u in links[:6]]
    lines += ["", "Orijinal:", (text or "")[:500]]

    rows = []
    for b in bots[:4]:
        rows.append([InlineKeyboardButton(f"Incele @{b}", callback_data=f"ins:{b}"[:64])])
        rows.append([InlineKeyboardButton(f"Ac @{b}", url=f"https://t.me/{b}")])
    kb = InlineKeyboardMarkup(rows) if rows else None
    await send_admin("\n".join(lines), kb)
    print("[BILDIRIM]", source_title, bots or links[:2])


# ===================== INCELEME =====================

async def fetch_incoming(entity, min_id: int):
    assert tg_client is not None
    out = []
    async for m in tg_client.iter_messages(entity, limit=10):
        if m.id < min_id:
            break
        out.append(m)
    out.reverse()
    return out


async def inspect_bot(bot: str):
    bot = bot.lstrip("@").lower()
    now = time.time()
    last = INSPECT_COOLDOWN.get(bot, 0)
    if now - last < INSPECT_MIN_INTERVAL:
        wait = int(INSPECT_MIN_INTERVAL - (now - last))
        await send_admin(f"@{bot} inceleme limiti: {wait} sn bekle")
        return
    INSPECT_COOLDOWN[bot] = now

    assert tg_client is not None and TG_LOCK is not None
    try:
        async with TG_LOCK:
            ent = await resolve_entity(bot)
            sent = await tg_client.send_message(ent, "/start")
            await asyncio.sleep(INSPECT_WAIT)
            msgs = await fetch_incoming(ent, sent.id + 1)

        texts = []
        buttons = []
        for m in msgs:
            t = (m.message or "").strip()
            if t:
                texts.append(t[:800])
            for row in m.buttons or []:
                for b in row:
                    label = (b.text or "").strip()
                    url = getattr(b, "url", None) or ""
                    if label and url:
                        buttons.append(f"{label} -> {url}")
                    elif label:
                        buttons.append(label)

        raw = "\n\n".join(texts) if texts else "(Bot cevap vermedi)"
        btn_txt = "\n".join(buttons[:20]) if buttons else "(buton yok)"
        guide = await ai_guide(
            f"BOT: @{bot}\nMESAJLAR:\n{raw}\n\nBUTONLAR:\n{btn_txt}",
            INSPECT_PROMPT,
        )

        lines = [
            f"INCELEME: @{bot}",
            "",
            guide,
            "",
            "Botun mesaji:",
            raw[:1500],
            "",
            "Butonlar:",
            btn_txt[:800],
            "",
            "Not: Otomatik katilim/gorev YOK.",
        ]
        kb = InlineKeyboardMarkup(
            [[InlineKeyboardButton(f"Botu ac", url=f"https://t.me/{bot}")]]
        )
        await send_admin("\n".join(lines), kb)
    except Exception as e:
        print("[INSPECT]", repr(e))
        await send_admin(f"@{bot} inceleme hatasi: {type(e).__name__} {e}")


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

        bots = extract_bot_names(full)
        links: list = []

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
            getattr(chat, "title", None)
            or getattr(chat, "username", None)
            or str(event.chat_id)
        )
        guide = await ai_guide(text) if len(text.strip()) >= 20 else ""
        warn = [w for w in BAD_WORDS if w in text.lower()]
        await notify_admin(title, text, bots, links, guide, warn)

        if INSPECT and bots and not warn:
            for b in bots:
                spawn(inspect_bot(b))
    except Exception as e:
        print("[LISTENER]", repr(e))


# ===================== KOMUTLAR =====================

@admin_only
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(
        "Airdrop / oyun bot radari\n\n"
        "/add -100...\n"
        "/del -100...\n"
        "/list\n"
        "/incele botadi\n"
        "/bil botadi\n"
        "/status\n\n"
        "Telethon hesabin grupta UYE olmali."
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
        await update.effective_message.reply_text("Kullanim:\n/bil victorempirebot")
        return
    eklenen = []
    for a in context.args:
        m = BOT_LINK_RE.search(a)
        name = (m.group(1) if m else a.strip().lstrip("@")).lower()
        if len(name) >= 3 and name not in SKIP_USERNAMES:
            seen[f"bot:{name}"] = time.time()
            eklenen.append(name)
    if eklenen:
        await persist_seen()
        await update.effective_message.reply_text(
            "Bilinen: " + ", ".join("@" + n for n in eklenen)
        )
    else:
        await update.effective_message.reply_text("Gecerli bot adi yok.")


@admin_only
async def cmd_incele(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.effective_message.reply_text("Kullanim:\n/incele victorempirebot")
        return
    a = context.args[0]
    m = BOT_LINK_RE.search(a)
    name = (m.group(1) if m else a.strip().lstrip("@")).lower()
    await update.effective_message.reply_text(f"@{name} inceleniyor...")
    spawn(inspect_bot(name))


@admin_only
async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    n_bots = sum(1 for k in seen if k.startswith("bot:"))
    await update.effective_message.reply_text(
        f"Durum: aktif\n"
        f"Dinlenen: {len(ACTIVE_SOURCES)}\n"
        f"Gorulen bot: {n_bots}\n"
        f"Mod: {'sadece bot' if ONLY_BOTS else 'genis filtre'}\n"
        f"Inceleme: {'acik' if INSPECT else 'kapali'}\n"
        f"Groq: {'acik' if GROQ_API_KEY else 'kapali'} ({GROQ_MODEL})\n"
        f"Gemini: {'acik' if GEMINI_API_KEY else 'kapali'} ({GEMINI_MODEL})\n"
        f"Upstash: {'acik' if UPSTASH_REDIS_REST_URL else 'kapali'}"
    )


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
        return

    if data.startswith("ins:"):
        await q.answer("Inceleniyor...")
        bot = data[4:].strip().lower()
        if bot:
            spawn(inspect_bot(bot))
            await q.message.reply_text(f"@{bot} inceleme basladi...")
        return

    await q.answer()


# ===================== HTTP =====================

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
    print(f"[HTTP] Port {PORT}")


async def keepalive_loop():
    if not (KEEPALIVE and RENDER_URL):
        print("[KEEPALIVE] kapali")
        return
    print("[KEEPALIVE]", RENDER_URL)
    while True:
        await asyncio.sleep(600)
        try:
            assert http_session is not None
            async with http_session.get(
                RENDER_URL + "/health", timeout=aiohttp.ClientTimeout(total=20)
            ) as r:
                await r.read()
        except Exception as e:
            print("[KEEPALIVE]", repr(e))


# ===================== MAIN =====================

async def main():
    global tg_client, http_session, bot_app, TG_LOCK

    if not API_ID or not API_HASH or not STRING_SESSION:
        raise SystemExit("API_ID / API_HASH / STRING_SESSION zorunlu")
    if not BOT_TOKEN:
        raise SystemExit("BOT_TOKEN zorunlu")
    if not ADMIN_USER_ID:
        raise SystemExit("ADMIN_USER_ID zorunlu")

    TG_LOCK = asyncio.Lock()

    print("=" * 60)
    print("AIRDROP RADARI v3 + GROQ")
    print("=" * 60)
    print("[KONFIG] ADMIN =", ADMIN_USER_ID)
    print("[KONFIG] GROQ =", "aktif" if GROQ_API_KEY else "yok", GROQ_MODEL)
    print("[KONFIG] GEMINI =", "aktif" if GEMINI_API_KEY else "yok", GEMINI_MODEL)
    print("[KONFIG] MOD =", "sadece bot" if ONLY_BOTS else "genis filtre")
    print("[KONFIG] INSPECT =", INSPECT)

    http_session = aiohttp.ClientSession()
    await start_http()

    tg_client = TelegramClient(StringSession(STRING_SESSION), API_ID, API_HASH)
    await tg_client.start()
    me = await tg_client.get_me()
    print("[TELETHON]", me.id, getattr(me, "username", None))
    await tg_client.get_dialogs()
    await load_seen()

    seed = []
    seed.extend(parse_id_list(SOURCE_CHATS_EXTRA))
    seed.extend(await load_persisted_sources())
    for item in seed:
        try:
            entity = await resolve_entity(item)
            cid = get_peer_id(entity)
            ACTIVE_SOURCES.add(cid)
            SOURCE_META[cid] = (
                getattr(entity, "title", None)
                or getattr(entity, "username", None)
                or str(cid)
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
    bot_app.add_handler(CommandHandler("status", cmd_status))
    bot_app.add_handler(CallbackQueryHandler(on_callback))

    await bot_app.initialize()
    await bot_app.start()
    await bot_app.updater.start_polling(drop_pending_updates=True)

    spawn(keepalive_loop())

    try:
        await bot_app.bot.send_message(
            ADMIN_CHAT_ID,
            f"Radar aktif (Groq)\nDinlenen: {len(ACTIVE_SOURCES)}\n"
            f"Groq: {'acik' if GROQ_API_KEY else 'kapali'}\n"
            f"/incele botadi ile dene",
        )
    except Exception as e:
        print("[ADMIN MSG]", repr(e))

    print("[HAZIR]")
    await tg_client.run_until_disconnected()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
