"""
Airdrop / oyun bot radari
- Telethon: grup dinleme
- BOT_TOKEN: /add /del /list (Airdrop radar botu uzerinden)
- Gemini ceviri
- Sadece admin'e bildirim
- Render icin PORT uzerinde HTTP (health)
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

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash").strip()
DEDUP_TTL = int(os.getenv("DEDUP_TTL", "86400") or 86400)
PORT = int(os.getenv("PORT", "10000") or 10000)

SOURCE_CHATS_EXTRA = os.getenv("SOURCE_CHATS_EXTRA", "").strip()
UPSTASH_REDIS_REST_URL = os.getenv("UPSTASH_REDIS_REST_URL", "").strip().rstrip("/")
UPSTASH_REDIS_REST_TOKEN = os.getenv("UPSTASH_REDIS_REST_TOKEN", "").strip()
SOURCES_KEY = os.getenv("SOURCES_KEY", "radar:source_chats:v1").strip()
SOURCES_FILE = os.getenv("SOURCES_FILE", "/tmp/radar_sources.json")

SOURCE_CHATS_STATIC: list = []

# ===================== FILTRE =====================

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

BOT_USERNAME_RE = re.compile(
    r"(?:t\.me|telegram\.me)/([A-Za-z0-9_]{4,})(?:\?|$|/)",
    re.I,
)

# ===================== STATE =====================

seen: dict[str, float] = {}
ACTIVE_SOURCES: Set[int] = set()
SOURCE_META: dict[int, str] = {}  # chat_id -> title
http_session: Optional[aiohttp.ClientSession] = None
tg_client: Optional[TelegramClient] = None
bot_app: Optional[Application] = None
INSPECT_COOLDOWN: dict[str, float] = {}  # bot username -> last inspect ts
INSPECT_MIN_INTERVAL = int(os.getenv("INSPECT_MIN_INTERVAL", "120") or 120)


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


# ===================== DEPO =====================

async def upstash_get(key: str) -> Optional[str]:
    if not UPSTASH_REDIS_REST_URL or not UPSTASH_REDIS_REST_TOKEN:
        return None
    assert http_session is not None
    try:
        async with http_session.get(
            f"{UPSTASH_REDIS_REST_URL}/get/{key}",
            headers={"Authorization": f"Bearer {UPSTASH_REDIS_REST_TOKEN}"},
            timeout=aiohttp.ClientTimeout(total=10),
        ) as r:
            data = await r.json()
            return data.get("result")
    except Exception as e:
        print("[UPSTASH GET]", repr(e))
        return None


async def upstash_set(key: str, value: str) -> bool:
    if not UPSTASH_REDIS_REST_URL or not UPSTASH_REDIS_REST_TOKEN:
        return False
    assert http_session is not None
    try:
        from urllib.parse import quote
        path_val = quote(value, safe="")
        async with http_session.post(
            f"{UPSTASH_REDIS_REST_URL}/set/{key}/{path_val}",
            headers={"Authorization": f"Bearer {UPSTASH_REDIS_REST_TOKEN}"},
            timeout=aiohttp.ClientTimeout(total=10),
        ) as r:
            return r.status < 300
    except Exception as e:
        print("[UPSTASH SET]", repr(e))
        return False


def load_sources_file() -> list:
    try:
        with open(SOURCES_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                return data
    except Exception:
        pass
    return []


def save_sources_file(items: list):
    try:
        with open(SOURCES_FILE, "w", encoding="utf-8") as f:
            json.dump(items, f)
    except Exception as e:
        print("[FILE SAVE]", repr(e))


async def persist_sources():
    items = sorted(ACTIVE_SOURCES)
    save_sources_file(items)
    await upstash_set(SOURCES_KEY, json.dumps(items))


async def load_persisted_sources() -> list:
    raw = await upstash_get(SOURCES_KEY)
    if raw:
        try:
            data = json.loads(raw)
            if isinstance(data, list):
                print("[KAYNAK] Upstash:", len(data))
                return data
        except Exception:
            pass
    data = load_sources_file()
    if data:
        print("[KAYNAK] Dosya:", len(data))
    return data


async def add_source(item) -> str:
    assert tg_client is not None
    try:
        entity = await tg_client.get_entity(
            int(item) if str(item).lstrip("-").isdigit() else item
        )
        chat_id = get_peer_id(entity)
    except Exception as e:
        return f"Bulunamadi / hesap uye degil: {item}\n{e}"

    if chat_id in ACTIVE_SOURCES:
        title = getattr(entity, "title", None) or chat_id
        return f"Zaten listede: {title} ({chat_id})"

    ACTIVE_SOURCES.add(chat_id)
    title = getattr(entity, "title", None) or getattr(entity, "username", None) or str(chat_id)
    SOURCE_META[chat_id] = str(title)
    await persist_sources()
    return f"Eklendi: {title}\nID: `{chat_id}`\nToplam: {len(ACTIVE_SOURCES)}"


async def del_source(item) -> str:
    assert tg_client is not None
    try:
        if str(item).lstrip("-").isdigit():
            chat_id = int(item)
        else:
            entity = await tg_client.get_entity(item)
            chat_id = get_peer_id(entity)
    except Exception as e:
        try:
            chat_id = int(str(item).strip())
        except Exception:
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
    """Eksik isimleri Telethon ile doldur."""
    if not tg_client:
        return
    for cid in list(ACTIVE_SOURCES):
        if cid in SOURCE_META and SOURCE_META[cid]:
            continue
        try:
            ent = await tg_client.get_entity(cid)
            SOURCE_META[cid] = (
                getattr(ent, "title", None)
                or getattr(ent, "username", None)
                or str(cid)
            )
        except Exception:
            SOURCE_META[cid] = str(cid)


def build_list_keyboard():
    rows = []
    for cid in sorted(ACTIVE_SOURCES):
        name = SOURCE_META.get(cid) or str(cid)
        # buton yazisi kisa tut
        label = name if len(name) <= 28 else name[:25] + "..."
        rows.append([
            InlineKeyboardButton(
                f"Sil: {label}",
                callback_data=f"del:{cid}",
            )
        ])
    return InlineKeyboardMarkup(rows) if rows else None


# ===================== GEMINI =====================

async def gemini_translate_and_summary(text: str) -> tuple[str, str]:
    text = (text or "").strip()
    if not text:
        return "", ""
    if not GEMINI_API_KEY:
        return text, "(Ceviri yok - GEMINI_API_KEY yok)"

    prompt = (
        "Asagidaki Telegram tanitim / airdrop / bot mesajini isle.\n"
        "1) CEVIRI: Metni anlami bozmadan Turkce'ye cevir. Link ve @adlari aynen birak.\n"
        "2) OZET: En fazla 3 kisa cumle.\n"
        "Format:\nCEVIRI:\n...\nOZET:\n...\n\n"
        f"MESAJ:\n{text[:6000]}"
    )
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
    )
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.2, "maxOutputTokens": 2048},
    }
    assert http_session is not None
    try:
        async with http_session.post(
            url, json=payload, timeout=aiohttp.ClientTimeout(total=40)
        ) as resp:
            data = await resp.json()
            if resp.status >= 400:
                print("[GEMINI]", resp.status, str(data)[:200])
                return text, f"(Gemini {resp.status})"
            parts = (data.get("candidates") or [{}])[0].get("content", {}).get("parts", [])
            raw = "\n".join(p.get("text", "") for p in parts).strip()
            m = re.search(
                r"(?:CEVIRI|ÇEVİRİ)\s*:\s*(.*?)\s*(?:OZET|ÖZET)\s*:\s*(.*)",
                raw,
                re.I | re.S,
            )
            if m:
                return m.group(1).strip(), m.group(2).strip()
            return raw or text, ""
    except Exception as e:
        print("[GEMINI EX]", repr(e))
        return text, f"(Gemini hata: {e})"


# ===================== BILDIRIM =====================

def fingerprint(text: str, links: list[str]) -> str:
    base = "|".join(sorted(links)) if links else text[:400]
    return hashlib.sha1(base.encode("utf-8", "ignore")).hexdigest()


def cleanup_seen():
    now = time.time()
    for k in [k for k, ts in seen.items() if now - ts > DEDUP_TTL]:
        seen.pop(k, None)


def extract_links(text: str) -> list[str]:
    return list(
        dict.fromkeys(
            m.group(0).rstrip(").,]>\"'")
            for m in LINK_RE.finditer(text or "")
        )
    )


def is_interesting(text: str, links: list[str]) -> bool:
    return bool(links) or bool(KEYWORD_RE.search(text or ""))


def extract_bot_usernames(links: list[str]) -> list[str]:
    out = []
    for url in links:
        m = BOT_USERNAME_RE.search(url)
        if not m:
            continue
        name = m.group(1)
        if name.lower() in {"joinchat", "addstickers", "share", "proxy", "socks"}:
            continue
        if name.startswith("+"):
            continue
        out.append(name)
    return list(dict.fromkeys(out))


def extract_start_param(links: list[str], bot: str) -> str:
    bot_l = bot.lower()
    for u in links:
        m = re.search(
            rf"(?:t\.me|telegram\.me)/{re.escape(bot)}\?start=([A-Za-z0-9_\-]+)",
            u,
            re.I,
        )
        if m:
            return m.group(1)
    return ""


async def inspect_telegram_bot(bot_username: str, start_param: str = "") -> str:
    """
    Bota /start atar, gelen mesajlari okur, ref/gorev ozetler.
    Kanala katilmaz, gorev yapmaz.
    """
    assert tg_client is not None
    bot_username = bot_username.lstrip("@")
    now = time.time()
    last = INSPECT_COOLDOWN.get(bot_username.lower(), 0)
    if now - last < INSPECT_MIN_INTERVAL:
        wait = int(INSPECT_MIN_INTERVAL - (now - last))
        return f"@{bot_username} icin bekle: {wait} sn (limit)"

    INSPECT_COOLDOWN[bot_username.lower()] = now

    try:
        entity = await tg_client.get_entity(bot_username)
    except Exception as e:
        return f"@{bot_username} bulunamadi: {e}"

    # onceki son mesaj id
    last_id = 0
    try:
        async for m in tg_client.iter_messages(entity, limit=1):
            last_id = m.id
            break
    except Exception:
        pass

    payload = f"/start {start_param}".strip() if start_param else "/start"
    try:
        await tg_client.send_message(entity, payload)
    except Exception as e:
        return f"@{bot_username} /start gonderilemedi: {e}"

    # cevapları bekle
    await asyncio.sleep(4)
    collected_texts = []
    collected_buttons = []
    collected_links = []

    try:
        async for m in tg_client.iter_messages(entity, limit=8):
            if last_id and m.id <= last_id:
                break
            t = m.message or ""
            if t:
                collected_texts.append(t)
                collected_links.extend(extract_links(t))
            # inline buttons
            markup = getattr(m, "reply_markup", None)
            if markup and getattr(markup, "rows", None):
                for row in markup.rows:
                    for btn in row.buttons:
                        label = getattr(btn, "text", None) or ""
                        url = getattr(btn, "url", None) or ""
                        if label:
                            collected_buttons.append(label)
                        if url:
                            collected_links.append(url)
                            collected_buttons.append(f"{label} -> {url}" if label else url)
    except Exception as e:
        print("[INSPECT READ]", repr(e))

    if not collected_texts and not collected_buttons:
        return (
            f"BOT INCELEME: @{bot_username}\n"
            f"/start gonderildi ama cevap yok (bot yavas veya engel)."
        )

    raw_blob = "\n\n".join(collected_texts)[:5000]
    btn_blob = "\n".join(collected_buttons[:40])
    link_blob = "\n".join(list(dict.fromkeys(collected_links))[:20])

    # ref adaylari
    ref_links = []
    for u in collected_links:
        if re.search(r"[?&]start=", u, re.I) or "ref" in u.lower():
            ref_links.append(u)

    summary = ""
    if GEMINI_API_KEY:
        prompt = (
            "Asagida bir Telegram botuna /start sonrasi gelen mesajlar var.\n"
            "Gorev YAPMA. Sadece analiz et.\n"
            "Yaz:\n"
            "1) Bot ne vaat ediyor (1-2 cumle)\n"
            "2) Gorev listesi (madde madde, varsa)\n"
            "3) Kanal/grup linkleri\n"
            "4) YouTube veya dis linkler\n"
            "5) Referans/start linki varsa belirt\n"
            "6) Risk notu (seed/cüzdan istiyor mu)\n"
            "Turkce yaz.\n\n"
            f"BOT: @{bot_username}\n"
            f"MESAJLAR:\n{raw_blob}\n\n"
            f"BUTONLAR:\n{btn_blob}\n\n"
            f"LINKLER:\n{link_blob}\n"
        )
        try:
            summary, _ = await gemini_translate_and_summary(prompt)
            # gemini_translate expects CEVIRI format; use raw call better
        except Exception:
            summary = ""

    # Gemini ozet icin dogrudan istek
    if GEMINI_API_KEY:
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
        )
        prompt = (
            "Telegram bot /start sonrasi icerik analizi. Gorev yapma, sadece rapor.\n"
            "Turkce, kisa:\n"
            "- Ne vaat ediyor\n- Gorevler (madde)\n- Kanal linkleri\n"
            "- YouTube/dis linkler\n- Ref/start linki\n- Risk\n\n"
            f"@{bot_username}\nMESAJ:\n{raw_blob}\nBUTON:\n{btn_blob}\nLINK:\n{link_blob}"
        )
        payload_g = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.2, "maxOutputTokens": 1500},
        }
        try:
            assert http_session is not None
            async with http_session.post(
                url, json=payload_g, timeout=aiohttp.ClientTimeout(total=40)
            ) as resp:
                data = await resp.json()
                parts = (data.get("candidates") or [{}])[0].get("content", {}).get("parts", [])
                summary = "\n".join(p.get("text", "") for p in parts).strip()
        except Exception as e:
            summary = f"(AI ozet yok: {e})"

    lines = [
        f"BOT INCELEME: @{bot_username}",
        f"Komut: {payload}",
        "",
    ]
    if summary:
        lines.append("AI RAPOR:")
        lines.append(summary)
        lines.append("")
    if ref_links:
        lines.append("Ref / start linkleri:")
        for u in ref_links[:5]:
            lines.append(f"- {u}")
        lines.append("")
    if collected_buttons:
        lines.append("Butonlar:")
        for b in collected_buttons[:15]:
            lines.append(f"- {b}")
        lines.append("")
    lines.append("Ham mesaj (kisaltma):")
    lines.append(raw_blob[:1500] or "(bos)")
    lines.append("")
    lines.append("Not: Kanala otomatik katilim YOK. Link varsa sen katil.")

    return "\n".join(lines)[:4000]


async def notify_admin(source_title, source_id, text, links, ceviri, ozet):
    bots = extract_bot_usernames(links)
    lines = [
        "YENI TANITIM / AIRDROP",
        f"Kaynak: {source_title} ({source_id})",
    ]
    if bots:
        lines.append("Botlar: " + ", ".join(f"@{b}" for b in bots))
    if links:
        lines.append("Linkler:")
        for u in links[:8]:
            lines.append(f"- {u}")
    if ozet:
        lines.append("")
        lines.append("Ozet:")
        lines.append(ozet)
    lines.append("")
    lines.append("Turkce ceviri:")
    lines.append(ceviri[:2500] if ceviri else "(bos)")
    lines.append("")
    lines.append("Orijinal:")
    lines.append((text or "")[:800])
    if bots:
        lines.append("")
        lines.append("Bot incelemek icin asagidaki butona bas (gorev yapmaz, sadece okur).")

    msg = "\n".join(lines)
    if len(msg) > 4000:
        msg = msg[:3900] + "\n..."

    # Inline İncele butonlari
    rows = []
    for b in bots[:5]:
        sp = extract_start_param(links, b)
        cb = f"ins:{b}:{sp}" if sp else f"ins:{b}"
        # callback_data max 64 byte
        if len(cb) > 64:
            cb = f"ins:{b}"[:64]
        rows.append([InlineKeyboardButton(f"Incele @{b}", callback_data=cb)])
        rows.append([InlineKeyboardButton(f"Ac @{b}", url=f"https://t.me/{b}")])

    kb = InlineKeyboardMarkup(rows) if rows else None

    if bot_app and bot_app.bot:
        await bot_app.bot.send_message(
            ADMIN_CHAT_ID,
            msg,
            disable_web_page_preview=True,
            reply_markup=kb,
        )
    elif tg_client:
        await tg_client.send_message(ADMIN_CHAT_ID, msg, link_preview=False)
    print("[BILDIRIM]", source_title, links[:2], "bots=", bots)


# ===================== TELETHON =====================

async def on_group_message(event):
    try:
        if event.chat_id not in ACTIVE_SOURCES:
            return
        text = event.message.message or ""
        for ent in event.message.entities or []:
            u = getattr(ent, "url", None)
            if u:
                text = text + "\n" + str(u)

        links = extract_links(text)
        if not is_interesting(text, links):
            return

        fp = fingerprint(text, links)
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
        ceviri, ozet = await gemini_translate_and_summary(text)
        await notify_admin(title, event.chat_id, text, links, ceviri, ozet)
    except Exception as e:
        print("[LISTENER]", repr(e))


# ===================== BOT KOMUTLARI =====================

@admin_only
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(
        "Airdrop / oyun bot radari\n\n"
        "Komutlar:\n"
        "/add -1001234567890\n"
        "/add -100111 -100222\n"
        "/del -1001234567890\n"
        "/list\n"
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
    kb = build_list_keyboard()
    await update.effective_message.reply_text(
        list_sources_text(),
        reply_markup=kb,
    )


@admin_only
async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not q or not q.data:
        return
    data = q.data

    if data.startswith("del:"):
        await q.answer()
        raw = data[4:]
        try:
            cid = int(raw)
        except ValueError:
            await q.edit_message_text("Gecersiz ID")
            return
        msg = await del_source(cid)
        await enrich_source_titles()
        kb = build_list_keyboard()
        text = msg + "\n\n" + list_sources_text()
        try:
            await q.edit_message_text(text[:4000], reply_markup=kb)
        except Exception:
            await q.message.reply_text(text[:4000], reply_markup=kb)
        return

    if data.startswith("ins:"):
        await q.answer("Inceleniyor...")
        parts = data.split(":")
        bot = parts[1] if len(parts) > 1 else ""
        start_param = parts[2] if len(parts) > 2 else ""
        if not bot:
            await q.message.reply_text("Bot adi yok")
            return
        report = await inspect_telegram_bot(bot, start_param)
        await q.message.reply_text(report[:4000])
        return


@admin_only
async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(
        f"Durum: aktif\n"
        f"Dinlenen: {len(ACTIVE_SOURCES)}\n"
        f"Gemini: {'acik' if GEMINI_API_KEY else 'kapali'}\n"
        f"Upstash: {'acik' if UPSTASH_REDIS_REST_URL else 'kapali'}"
    )


# ===================== HTTP (Render port) =====================

async def handle_health(request):
    return web.Response(
        text=f"ok sources={len(ACTIVE_SOURCES)}",
        content_type="text/plain",
    )


async def start_http():
    app = web.Application()
    app.router.add_get("/", handle_health)
    app.router.add_get("/health", handle_health)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    print(f"[HTTP] Port {PORT} acik (Render health)")


# ===================== MAIN =====================

async def main():
    global tg_client, http_session, bot_app

    if not API_ID or not API_HASH or not STRING_SESSION:
        raise SystemExit("API_ID / API_HASH / STRING_SESSION zorunlu")
    if not BOT_TOKEN:
        raise SystemExit("BOT_TOKEN zorunlu (Airdrop radar bot)")
    if not ADMIN_USER_ID:
        raise SystemExit("ADMIN_USER_ID / ADMIN_CHAT_ID zorunlu")

    print("=" * 60)
    print("AIRDROP RADARI + BOT KOMUTLARI")
    print("=" * 60)
    print("[KONFIG] ADMIN =", ADMIN_USER_ID)
    print("[KONFIG] PORT =", PORT)
    print("[KONFIG] GEMINI =", "aktif" if GEMINI_API_KEY else "yok")

    http_session = aiohttp.ClientSession()

    # HTTP once - Render port gorsun
    await start_http()

    # Telethon
    tg_client = TelegramClient(StringSession(STRING_SESSION), API_ID, API_HASH)
    await tg_client.start()
    me = await tg_client.get_me()
    print("[TELETHON]", me.id, getattr(me, "username", None))

    seed = []
    seed.extend(SOURCE_CHATS_STATIC)
    seed.extend(parse_id_list(SOURCE_CHATS_EXTRA))
    seed.extend(await load_persisted_sources())

    for item in seed:
        try:
            entity = await tg_client.get_entity(
                int(item) if str(item).lstrip("-").isdigit() else item
            )
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

    # Bot komutlari
    bot_app = Application.builder().token(BOT_TOKEN).build()
    bot_app.add_handler(CommandHandler("start", cmd_start))
    bot_app.add_handler(CommandHandler("help", cmd_help))
    bot_app.add_handler(CommandHandler("yardim", cmd_help))
    bot_app.add_handler(CommandHandler("add", cmd_add))
    bot_app.add_handler(CommandHandler("del", cmd_del))
    bot_app.add_handler(CommandHandler("remove", cmd_del))
    bot_app.add_handler(CommandHandler("list", cmd_list))
    bot_app.add_handler(CommandHandler("status", cmd_status))
    bot_app.add_handler(CallbackQueryHandler(on_callback))

    await bot_app.initialize()
    await bot_app.start()
    await bot_app.updater.start_polling(drop_pending_updates=True)

    try:
        await bot_app.bot.send_message(
            ADMIN_CHAT_ID,
            f"Radar aktif\nDinlenen: {len(ACTIVE_SOURCES)}\n"
            f"Gemini: {'acik' if GEMINI_API_KEY else 'kapali'}\n\n"
            f"/add -100... ile grup ekle",
        )
    except Exception as e:
        print("[ADMIN MSG HATA]", repr(e))

    print("[HAZIR] Bot komutlari + Telethon + HTTP")
    await tg_client.run_until_disconnected()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
