"""
Oyun / Airdrop / Bot tanitim radari
- Grup ID'lerini admin komutlariyla ekle/sil (kod degistirmeden)
- t.me bot + airdrop linkleri yakalar
- Gemini ile Turkce ceviri + ozet
- Sadece ADMIN_CHAT_ID'ye bildirir
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
from telethon import TelegramClient, events
from telethon.sessions import StringSession

# ===================== ENV =====================

API_ID = int(os.getenv("API_ID", "0") or 0)
API_HASH = os.getenv("API_HASH", "").strip()
STRING_SESSION = os.getenv("STRING_SESSION", "").strip()
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID", "0") or 0)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash").strip()

DEDUP_TTL = int(os.getenv("DEDUP_TTL", "86400") or 86400)

# Opsiyonel: baslangicta env ile de eklenebilir
# SOURCE_CHATS_EXTRA=-100111,-100222
SOURCE_CHATS_EXTRA = os.getenv("SOURCE_CHATS_EXTRA", "").strip()

# Upstash (kalici liste - Render restart sonrasi da kalir)
UPSTASH_REDIS_REST_URL = os.getenv("UPSTASH_REDIS_REST_URL", "").strip().rstrip("/")
UPSTASH_REDIS_REST_TOKEN = os.getenv("UPSTASH_REDIS_REST_TOKEN", "").strip()
SOURCES_KEY = os.getenv("SOURCES_KEY", "radar:source_chats:v1").strip()

# Yerel yedek dosya (Upstash yoksa)
SOURCES_FILE = os.getenv("SOURCES_FILE", "/tmp/radar_sources.json")

# main.py icine sabit yazmak istersen (opsiyonel, bos birakilabilir)
SOURCE_CHATS_STATIC = [
    # -1001111111111,
]

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
    r"razdacha|аирдроп|раздача|квест|"
    r"ücretsiz|odul|gorev|görev|ödül"
    r")\b",
    re.I,
)

BOT_USERNAME_RE = re.compile(
    r"(?:t\.me|telegram\.me)/([A-Za-z0-9_]{4,})(?:\?|$|/)",
    re.I,
)

CMD_RE = re.compile(
    r"^/(add|del|remove|list|help|start|status)\b(?:\s+(.+))?",
    re.I,
)

# ===================== STATE =====================

seen: dict[str, float] = {}
ACTIVE_SOURCES: Set[int] = set()  # chat id'ler (telethon form)
http_session: Optional[aiohttp.ClientSession] = None
client: Optional[TelegramClient] = None


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


# ===================== KALICI DEPO =====================

async def upstash_get(key: str) -> Optional[str]:
    if not UPSTASH_REDIS_REST_URL or not UPSTASH_REDIS_REST_TOKEN:
        return None
    assert http_session is not None
    url = f"{UPSTASH_REDIS_REST_URL}/get/{key}"
    headers = {"Authorization": f"Bearer {UPSTASH_REDIS_REST_TOKEN}"}
    try:
        async with http_session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as r:
            data = await r.json()
            return data.get("result")
    except Exception as e:
        print("[UPSTASH GET HATA]", repr(e))
        return None


async def upstash_set(key: str, value: str) -> bool:
    if not UPSTASH_REDIS_REST_URL or not UPSTASH_REDIS_REST_TOKEN:
        return False
    assert http_session is not None
    url = f"{UPSTASH_REDIS_REST_URL}/set/{key}/{aiohttp.client.URL(value, encoded=False)}"
    # Upstash REST: POST /set/key/value — value path'te sorun cikarabilir; body kullan
    headers = {
        "Authorization": f"Bearer {UPSTASH_REDIS_REST_TOKEN}",
        "Content-Type": "application/json",
    }
    try:
        async with http_session.post(
            f"{UPSTASH_REDIS_REST_URL}/set/{key}",
            headers=headers,
            json={"value": value} if False else None,
            timeout=aiohttp.ClientTimeout(total=10),
        ) as r:
            # Upstash pipeline style: /set/key/value with encoded value
            pass
    except Exception:
        pass
    # dogru yontem: GET-style path encode
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
        print("[UPSTASH SET HATA]", repr(e))
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
        print("[FILE SAVE HATA]", repr(e))


async def persist_sources():
    """ACTIVE_SOURCES'u kaydet (orijinal girilen degerler icin meta tutulur)."""
    # id listesi
    items = sorted(ACTIVE_SOURCES)
    save_sources_file(items)
    await upstash_set(SOURCES_KEY, json.dumps(items))


async def load_persisted_sources() -> list:
    raw = await upstash_get(SOURCES_KEY)
    if raw:
        try:
            data = json.loads(raw)
            if isinstance(data, list):
                print("[KAYNAK] Upstash'ten yuklendi:", len(data))
                return data
        except Exception:
            pass
    data = load_sources_file()
    if data:
        print("[KAYNAK] Dosyadan yuklendi:", len(data))
    return data


async def resolve_to_id(item) -> Optional[int]:
    """username veya id -> telethon chat id."""
    assert client is not None
    try:
        entity = await client.get_entity(item)
        # Telethon chat_id: kanallarda -100... formuna cevrilir event.chat_id ile uyumlu
        eid = entity.id
        # channel/supergroup
        if hasattr(entity, "megagroup") or getattr(entity, "broadcast", False) or type(entity).__name__ in ("Channel", "Chat"):
            # event.chat_id genelde -100xxxxxxxxxx
            if eid > 0:
                # PeerChannel
                chat_id = int(f"-100{eid}")
            else:
                chat_id = eid
        else:
            chat_id = eid
        # dogrulama: get_entity sonrasi
        return chat_id
    except Exception as e:
        print("[RESOLVE HATA]", item, repr(e))
        return None


async def add_source(item) -> str:
    assert client is not None
    try:
        entity = await client.get_entity(item)
    except Exception as e:
        return f"Bulunamadi / uye degilsin: {item}\nHata: {e}"

    # event.chat_id ile eslesmesi icin
    full = await client.get_input_entity(entity)
    # gercek chat id'yi bir mesajdan almak zor; Telethon utils
    from telethon.utils import get_peer_id
    chat_id = get_peer_id(entity)

    if chat_id in ACTIVE_SOURCES:
        title = getattr(entity, "title", None) or getattr(entity, "username", None) or chat_id
        return f"Zaten listede: {title} ({chat_id})"

    ACTIVE_SOURCES.add(chat_id)
    await persist_sources()
    title = getattr(entity, "title", None) or getattr(entity, "username", None) or chat_id
    return f"Eklendi: {title}\nID: {chat_id}\nToplam: {len(ACTIVE_SOURCES)}"


async def del_source(item) -> str:
    from telethon.utils import get_peer_id

    assert client is not None
    try:
        if isinstance(item, int) or (isinstance(item, str) and re.fullmatch(r"-?\d+", str(item))):
            chat_id = int(item)
        else:
            entity = await client.get_entity(item)
            chat_id = get_peer_id(entity)
    except Exception as e:
        # dogrudan id dene
        try:
            chat_id = int(str(item).strip())
        except Exception:
            return f"Silinemedi: {item} ({e})"

    if chat_id not in ACTIVE_SOURCES:
        return f"Listede yok: {chat_id}"

    ACTIVE_SOURCES.discard(chat_id)
    await persist_sources()
    return f"Silindi: {chat_id}\nToplam: {len(ACTIVE_SOURCES)}"


def list_sources_text() -> str:
    if not ACTIVE_SOURCES:
        return "Liste bos.\nEklemek icin: /add -1001234567890"
    lines = [f"Dinlenen gruplar ({len(ACTIVE_SOURCES)}):"]
    for i, cid in enumerate(sorted(ACTIVE_SOURCES), 1):
        lines.append(f"{i}. {cid}")
    lines.append("")
    lines.append("Ekle: /add -100...")
    lines.append("Sil: /del -100...")
    return "\n".join(lines)


# ===================== GEMINI =====================

async def gemini_translate_and_summary(text: str) -> tuple[str, str]:
    text = (text or "").strip()
    if not text:
        return "", ""

    if not GEMINI_API_KEY:
        return text, "(Ceviri yok - GEMINI_API_KEY tanimli degil)"

    prompt = (
        "Asagidaki Telegram tanitim / airdrop / bot mesajini isle.\n"
        "1) CEVIRI: Metni anlami bozmadan, oldugu gibi Turkce'ye cevir. "
        "Linkleri ve @kullanici / bot adlarini aynen birak.\n"
        "2) OZET: En fazla 3 kisa cumle - ne vaat ediyor, ne yapilmali, risk var mi.\n"
        "Cikti formati tam olarak soyle olsun:\n"
        "CEVIRI:\n"
        "...\n"
        "OZET:\n"
        "...\n\n"
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

    global http_session
    assert http_session is not None

    try:
        async with http_session.post(
            url, json=payload, timeout=aiohttp.ClientTimeout(total=40)
        ) as resp:
            data = await resp.json()
            if resp.status >= 400:
                print("[GEMINI HATA]", resp.status, str(data)[:300])
                return text, f"(Gemini hata {resp.status})"

            parts = (data.get("candidates") or [{}])[0].get("content", {}).get("parts", [])
            raw = "\n".join(p.get("text", "") for p in parts).strip()
            if not raw:
                return text, "(Gemini bos cevap)"

            m = re.search(
                r"(?:CEVIRI|CEVIRİ|ÇEVİRİ)\s*:\s*(.*?)\s*(?:OZET|ÖZET)\s*:\s*(.*)",
                raw,
                re.I | re.S,
            )
            if m:
                return m.group(1).strip(), m.group(2).strip()
            return raw, ""
    except Exception as e:
        print("[GEMINI EXCEPTION]", repr(e))
        return text, f"(Gemini exception: {e})"


# ===================== YARDIMCI =====================

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
    if links:
        return True
    if KEYWORD_RE.search(text or ""):
        return True
    return False


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
    lines.append("Turkce ceviri (oldugu gibi):")
    lines.append(ceviri[:3500] if ceviri else "(bos)")
    lines.append("")
    lines.append("Orijinal (kisaltilmis):")
    lines.append((text or "")[:1500])

    msg = "\n".join(lines)
    if len(msg) > 4000:
        msg = msg[:3900] + "\n..."

    assert client is not None
    await client.send_message(ADMIN_CHAT_ID, msg, link_preview=False)
    print("[BILDIRIM]", source_title, links[:2])


# ===================== HANDLERS =====================

async def on_admin_command(event):
    """Sadece admin'den gelen /add /del /list komutlari."""
    if not event.message or not event.message.message:
        return
    if event.sender_id != ADMIN_CHAT_ID and event.chat_id != ADMIN_CHAT_ID:
        return

    text = (event.message.message or "").strip()
    m = CMD_RE.match(text)
    if not m:
        return

    cmd = m.group(1).lower()
    arg = (m.group(2) or "").strip()

    if cmd in ("help", "start"):
        await event.respond(
            "Komutlar:\n"
            "/add -100123... veya /add @grup\n"
            "/del -100123...\n"
            "/list\n"
            "/status\n\n"
            "Not: Hesabin o grupta UYE olmali.\n"
            "Birden fazla: /add -1001 -1002 @grup"
        )
        return

    if cmd == "list":
        await event.respond(list_sources_text())
        return

    if cmd == "status":
        await event.respond(
            f"Durum: aktif\n"
            f"Dinlenen: {len(ACTIVE_SOURCES)}\n"
            f"Gemini: {'acik' if GEMINI_API_KEY else 'kapali'}\n"
            f"Upstash: {'acik' if UPSTASH_REDIS_REST_URL else 'kapali'}"
        )
        return

    if cmd == "add":
        if not arg:
            await event.respond("Kullanim: /add -1001234567890")
            return
        parts = parse_id_list(arg)
        replies = []
        for p in parts:
            replies.append(await add_source(p))
        await event.respond("\n\n".join(replies)[:4000])
        return

    if cmd in ("del", "remove"):
        if not arg:
            await event.respond("Kullanim: /del -1001234567890")
            return
        parts = parse_id_list(arg)
        replies = []
        for p in parts:
            replies.append(await del_source(p))
        await event.respond("\n\n".join(replies)[:4000])
        return


async def on_group_message(event):
    """Dinlenen gruplardaki tanitim mesajlari."""
    try:
        if event.chat_id not in ACTIVE_SOURCES:
            return
        # admin komutlarini gruba yazarsa cift isleme
        if event.sender_id == ADMIN_CHAT_ID and (event.message.message or "").startswith("/"):
            return

        text = event.message.message or ""
        extra_urls = []
        for ent in event.message.entities or []:
            u = getattr(ent, "url", None)
            if u:
                extra_urls.append(str(u))
        if extra_urls:
            text = text + "\n" + "\n".join(extra_urls)

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
        print("[LISTENER HATA]", repr(e))


# ===================== MAIN =====================

async def main():
    global client, http_session

    if not API_ID or not API_HASH or not STRING_SESSION:
        raise SystemExit("API_ID / API_HASH / STRING_SESSION zorunlu")
    if not ADMIN_CHAT_ID:
        raise SystemExit("ADMIN_CHAT_ID zorunlu")

    print("=" * 60)
    print("OYUN / AIRDROP RADARI")
    print("=" * 60)
    print("[KONFIG] ADMIN_CHAT_ID =", ADMIN_CHAT_ID)
    print("[KONFIG] GEMINI =", "aktif" if GEMINI_API_KEY else "yok")
    print("[KONFIG] UPSTASH =", "aktif" if UPSTASH_REDIS_REST_URL else "yok")

    http_session = aiohttp.ClientSession()
    client = TelegramClient(StringSession(STRING_SESSION), API_ID, API_HASH)
    await client.start()
    me = await client.get_me()
    print("[TELEGRAM] Baglandi:", me.id, getattr(me, "username", None))

    # kayitli + static + env kaynaklari yukle
    from telethon.utils import get_peer_id

    seed_items = []
    seed_items.extend(SOURCE_CHATS_STATIC)
    seed_items.extend(parse_id_list(SOURCE_CHATS_EXTRA))
    seed_items.extend(await load_persisted_sources())

    for item in seed_items:
        try:
            entity = await client.get_entity(int(item) if str(item).lstrip("-").isdigit() else item)
            cid = get_peer_id(entity)
            ACTIVE_SOURCES.add(cid)
            print("[KAYNAK OK]", item, "->", cid, getattr(entity, "title", None))
        except Exception as e:
            # ham id olarak dene
            try:
                cid = int(item)
                ACTIVE_SOURCES.add(cid)
                print("[KAYNAK ID]", cid)
            except Exception:
                print("[KAYNAK HATA]", item, repr(e))

    await persist_sources()

    # admin komutlari (ozel chat)
    client.add_event_handler(
        on_admin_command,
        events.NewMessage(from_users=ADMIN_CHAT_ID),
    )
    # tum gelen mesajlar - ACTIVE_SOURCES icindeyse isle
    client.add_event_handler(on_group_message, events.NewMessage(incoming=True))

    await client.send_message(
        ADMIN_CHAT_ID,
        "Radar aktif.\n"
        f"Dinlenen: {len(ACTIVE_SOURCES)} grup\n"
        f"Gemini: {'acik' if GEMINI_API_KEY else 'kapali'}\n\n"
        "Grup ekle: /add -1001234567890\n"
        "Liste: /list\n"
        "Yardim: /help",
    )

    print("[HAZIR] Dinleniyor... Komut: /add /del /list")
    await client.run_until_disconnected()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
