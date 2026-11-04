"""
Airdrop / oyun bot radari (v3)

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

import asyncio
import hashlib
import json
import os
import random
import re
import time
from typing import Optional, Set

import aiohttp
from aiohttp import web
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.tl.functions.channels import JoinChannelRequest
from telethon.tl.functions.messages import ImportChatInviteRequest
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
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-flash-latest").strip()
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
JOIN_DAILY_MAX = int(os.getenv("JOIN_DAILY_MAX", "10") or 10)      # 24 saatte en fazla kanal katilimi
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

# ===================== FILTRE =====================

BOT_LINK_RE = re.compile(r"(?:t\.me|telegram\.me)/([A-Za-z0-9_]{2,}bot)\b", re.I)

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
    r"\bpay\b|ödeme|odeme|stake|invest|premium|stars|usdt|swap|\bton\b",
    re.I,
)

# ===================== STATE =====================

seen: dict[str, float] = {}
ACTIVE_SOURCES: Set[int] = set()
SOURCE_META: dict[int, str] = {}
ACTIONS: dict[str, dict] = {}       # onay bekleyen islemler (bellekte; yeniden baslayinca silinir)
ACTION_N = 0
ROUTINES: dict[str, dict] = {}      # gunluk rutinler (kalici)
INSPECT_TIMES: list = []
JOIN_TIMES: list = []
LAST_INSPECT = 0.0
http_session: Optional[aiohttp.ClientSession] = None
tg_client: Optional[TelegramClient] = None
bot_app: Optional[Application] = None
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


def admin_only(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        if not user or user.id != ADMIN_USER_ID:
            if update.effective_message:
                await update.effective_message.reply_text("Yetkin yok.")
            return
        return await func(update, context)
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


async def gemini_guide(text: str, prompt: str = GUIDE_PROMPT) -> str:
    text = (text or "").strip()
    if not GEMINI_API_KEY:
        return "(Ozet yok - GEMINI_API_KEY yok)"
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
    )
    payload = {
        "contents": [{"parts": [{"text": prompt + text[:6000]}]}],
        "generationConfig": {"temperature": 0.2, "maxOutputTokens": 1024},
    }
    assert http_session is not None
    try:
        async with http_session.post(
            url, json=payload, timeout=aiohttp.ClientTimeout(total=40)
        ) as resp:
            data = await resp.json()
            if resp.status >= 400:
                print("[GEMINI]", resp.status, str(data)[:200])
                return f"(Gemini hatasi {resp.status}, ozet cikarilamadi)"
            parts = (data.get("candidates") or [{}])[0].get("content", {}).get("parts", [])
            raw = "\n".join(p.get("text", "") for p in parts).strip()
            return raw or "(Ozet bos geldi)"
    except Exception as e:
        print("[GEMINI EX]", repr(e))
        return f"(Gemini hata: {e})"


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
    await send_admin("\n".join(lines))
    print("[BILDIRIM]", source_title, bots or links[:2])


# ===================== BOT INCELEME =====================

def classify_button(b) -> str:
    """Buton turunu sinif adindan anlar (Telethon surumunden bagimsiz)."""
    name = type(b.button).__name__
    if name in ("KeyboardButtonWebView", "KeyboardButtonSimpleWebView"):
        return "webapp"
    if name in ("KeyboardButtonUrl", "KeyboardButtonUrlAuth"):
        return "url"
    if name in ("KeyboardButtonRequestPhone", "KeyboardButtonRequestGeoLocation"):
        return "private"
    if name in ("KeyboardButtonCallback", "KeyboardButton"):
        return "click"
    return "other"  # odeme (Buy), oyun vb.: basilmaz


def summarize_msgs(msgs, bot: str) -> dict:
    """msgs: eskiden yeniye. Mesajlardaki metin, buton ve kanal linklerini ayiklar."""
    texts, webs, blocked, privs, chans = [], [], [], [], []
    clicks: dict[str, int] = {}  # etiket -> mesaj id (ayni etiket varsa en yenisi)
    for m in msgs:
        t = (m.message or "").strip()
        if t:
            texts.append(t[:700])
        urls = [str(e.url) for e in (m.entities or []) if getattr(e, "url", None)]
        urls.append(t)
        for row in (m.buttons or []):
            for b in row:
                label = (b.text or "").strip()
                kind = classify_button(b)
                if kind == "url" and getattr(b, "url", None):
                    urls.append(b.url)
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
    guide = await gemini_guide(combo, INSPECT_PROMPT) if len(raw_text) >= 20 else ""

    lines = [f"{header}: @{bot}", ""]
    lines.append(guide or (raw_text[:600] if raw_text else "(Bot metin göndermedi, sadece butonlar var.)"))
    if info["clicks"]:
        lines += ["", "▶️ Basılabilir: " + ", ".join(l for l, _ in info["clicks"])]
    if info["webs"]:
        lines.append("📱 Mini uygulama (sen açarsın): " + ", ".join(info["webs"]))
    if info["blocked"]:
        lines.append("⛔ Ödeme/cüzdan butonları atlandı: " + ", ".join(info["blocked"]))
    if info["privs"]:
        lines.append("🚫 Telefon/konum isteyen buton var: " + ", ".join(info["privs"]))
    if warn:
        lines += ["", "⚠️ Dikkat, şu ifadeler geçiyor: " + ", ".join(warn),
                  "Güvenlik için otomatik işlem butonu koymadım."]

    rows = []
    if not warn:
        if routine_label:
            aid = new_action({"t": "routine", "bot": bot, "label": routine_label})
            rows.append([InlineKeyboardButton(f"🔁 Her gün otomatik: {routine_label[:22]}", callback_data=f"a:{aid}")])
        for label, mid in info["clicks"][:8]:
            aid = new_action({"t": "click", "bot": bot, "msg_id": mid, "label": label})
            rows.append([InlineKeyboardButton(f"▶️ Bas: {label[:28]}", callback_data=f"a:{aid}")])
        for tgt in info["chans"]:
            aid = new_action({"t": "join", "target": tgt})
            rows.append([InlineKeyboardButton(f"📢 Katıl: {tgt[:22]}", callback_data=f"a:{aid}")])
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


async def inspect_bot(username: str):
    """Bota /start yazar, cevabini okur, rapor gonderir."""
    global LAST_INSPECT
    assert tg_client is not None
    try:
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
                sent = await tg_client.send_message(ent, "/start")
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
    labels = [(b.text or "").strip() for row in (msg.buttons or []) for b in row]
    if label not in labels:
        return None, "Buton artık yok (bot mesajı değiştirmiş). /incele ile yeniden bak."
    await asyncio.sleep(random.uniform(1.5, 4))
    try:
        await msg.click(filter=lambda b: (b.text or "").strip() == label)
    except Exception as e:
        return None, f"Basılamadı: {e}"
    await asyncio.sleep(4)
    return await fetch_incoming(ent, msg_id), "ok"


async def do_join(target: str) -> str:
    assert tg_client is not None
    now = time.time()
    JOIN_TIMES[:] = [t for t in JOIN_TIMES if now - t < 86400]
    if len(JOIN_TIMES) >= JOIN_DAILY_MAX:
        return f"Günlük katılım limiti doldu ({JOIN_DAILY_MAX}). Hesabı korumak için yarın dene."
    try:
        await asyncio.sleep(random.uniform(2, 6))
        if target.startswith("+") or target.lower().startswith("joinchat/"):
            code = target.lstrip("+")
            if code.lower().startswith("joinchat/"):
                code = code[9:]
            await tg_client(ImportChatInviteRequest(code))
        else:
            ent = await tg_client.get_entity(target)
            await tg_client(JoinChannelRequest(ent))
        JOIN_TIMES.append(time.time())
        return "Katıldım ✅"
    except Exception as e:
        return f"Katılamadım: {e}"


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
    elif t == "join":
        async with TG_LOCK:
            note = await do_join(act["target"])
        await send_admin(f"📢 {act['target']}: {note}")
    elif t == "routine":
        for r in ROUTINES.values():
            if r["bot"] == act["bot"] and r["label"] == act["label"]:
                await send_admin("🔁 Bu rutin zaten var. /rutin ile bak.")
                return
        rid = str(int(time.time() * 1000))
        ROUTINES[rid] = {"bot": act["bot"], "label": act["label"],
                         "last": time.time(), "jitter": random.randint(0, 1800)}
        await persist_routines()
        await send_admin(f"🔁 Rutin eklendi: @{act['bot']} → '{act['label']}' her gün otomatik basılacak.\n"
                         f"Silmek için /rutin")


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
                    if (b.text or "").strip() == r["label"] and classify_button(b) == "click":
                        target = m
                        break
                if target:
                    break
            if target:
                break
        if not target:
            return f"❓ @{r['bot']}: '{r['label']}' butonu bulunamadı (bot menüsü değişmiş olabilir)."
        await asyncio.sleep(random.uniform(1.5, 4))
        await target.click(filter=lambda b: (b.text or "").strip() == r["label"])
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
        guide = await gemini_guide(text) if len(text.strip()) >= 30 else ""
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
        "Komutlar:\n"
        "/add -1001234567890  (grup ekle)\n"
        "/del -1001234567890\n"
        "/list\n"
        "/incele botadi  (bota /start yaz, cevabı oku, rapor ver)\n"
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
    m = BOT_LINK_RE.search(a)
    name = (m.group(1) if m else a.strip().lstrip("@")).lower()
    if not re.fullmatch(r"[a-z0-9_]{2,}bot", name):
        await update.effective_message.reply_text("Geçerli bir bot adı yaz (…bot ile biten).")
        return
    await update.effective_message.reply_text(
        f"@{name} inceleniyor, 10-20 saniye (sırada başka varsa daha uzun)..."
    )
    spawn(inspect_bot(name))


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
        f"Gunluk rutin: {len(ROUTINES)} ({'acik' if ROUTINES_ON else 'kapali'})\n"
        f"Gemini: {'acik' if GEMINI_API_KEY else 'kapali'} ({GEMINI_MODEL})\n"
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

async def main():
    global tg_client, http_session, bot_app, TG_LOCK, INSPECT_LOCK

    if not API_ID or not API_HASH or not STRING_SESSION:
        raise SystemExit("API_ID / API_HASH / STRING_SESSION zorunlu")
    if not BOT_TOKEN:
        raise SystemExit("BOT_TOKEN zorunlu (Airdrop radar bot)")
    if not ADMIN_USER_ID:
        raise SystemExit("ADMIN_USER_ID / ADMIN_CHAT_ID zorunlu")

    TG_LOCK = asyncio.Lock()
    INSPECT_LOCK = asyncio.Lock()

    print("=" * 60)
    print("AIRDROP RADARI v3")
    print("=" * 60)
    print("[KONFIG] ADMIN =", ADMIN_USER_ID)
    print("[KONFIG] PORT =", PORT)
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
    bot_app.add_handler(CommandHandler("rutin", cmd_rutin))
    bot_app.add_handler(CommandHandler("status", cmd_status))
    bot_app.add_handler(CallbackQueryHandler(on_callback))

    await bot_app.initialize()
    await bot_app.start()
    await bot_app.updater.start_polling(drop_pending_updates=True)

    spawn(keepalive_loop())
    spawn(routine_loop())

    try:
        await bot_app.bot.send_message(
            ADMIN_CHAT_ID,
            f"Radar aktif (v3)\nDinlenen: {len(ACTIVE_SOURCES)}\n"
            f"Otomatik inceleme: {'acik' if INSPECT else 'kapali'}\n"
            f"Rutin: {len(ROUTINES)}\n\n"
            f"/add -100... ile grup ekle, /incele botadi ile dene",
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
