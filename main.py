"""
Oyun / Airdrop / Bot tanitim radari
- Birden fazla Telegram grubunu dinler
- t.me bot linkleri + airdrop / promo mesajlarini yakalar
- Gemini (ucretsiz) ile oldugu gibi Turkce'ye cevirir + kisa ozet
- Sadece ADMIN_CHAT_ID'ye ozel bildirir
- Soguk DM yok, gruba yazmaz
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import re
import time
from typing import Optional

import aiohttp
from telethon import TelegramClient, events
from telethon.sessions import StringSession

# ===================== ENV =====================

API_ID = int(os.getenv("API_ID", "0") or 0)
API_HASH = os.getenv("API_HASH", "").strip()
STRING_SESSION = os.getenv("STRING_SESSION", "").strip()
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID", "0") or 0)

# Virgulle ayrilmis grup ID'leri: -100111,-100222,@grupadi
SOURCE_CHATS_RAW = os.getenv("SOURCE_CHATS", "").strip()

# Google AI Studio -> ucretsiz Gemini key
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash").strip()

# Ayni tanitimi tekrar atmamak icin (saniye)
DEDUP_TTL = int(os.getenv("DEDUP_TTL", "86400") or 86400)

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
    r"razdacha|airdrop|belyi|квест|раздача|аирдроп|"
    r"ücretsiz|odul|gorev|görev|ödül"
    r")\b",
    re.I,
)

BOT_USERNAME_RE = re.compile(
    r"(?:t\.me|telegram\.me)/([A-Za-z0-9_]{4,})(?:\?|$|/)",
    re.I,
)

# ===================== STATE =====================

seen: dict[str, float] = {}
http_session: Optional[aiohttp.ClientSession] = None
client: Optional[TelegramClient] = None


def parse_source_chats(raw: str):
    items = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        if re.fullmatch(r"-?\d+", part):
            items.append(int(part))
        else:
            items.append(part.lstrip("@"))
    return items


SOURCE_CHATS = parse_source_chats(SOURCE_CHATS_RAW)


def fingerprint(text: str, links: list[str]) -> str:
    base = "|".join(sorted(links)) if links else text[:400]
    return hashlib.sha1(base.encode("utf-8", "ignore")).hexdigest()


def cleanup_seen():
    now = time.time()
    dead = [k for k, ts in seen.items() if now - ts > DEDUP_TTL]
    for k in dead:
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
        "generationConfig": {
            "temperature": 0.2,
            "maxOutputTokens": 2048,
        },
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

            ceviri, ozet = raw, ""
            m = re.search(
                r"(?:CEVIRI|CEVIRİ|ÇEVİRİ)\s*:\s*(.*?)\s*(?:OZET|ÖZET)\s*:\s*(.*)",
                raw,
                re.I | re.S,
            )
            if m:
                ceviri = m.group(1).strip()
                ozet = m.group(2).strip()
            else:
                ceviri = raw
            return ceviri, ozet
    except Exception as e:
        print("[GEMINI EXCEPTION]", repr(e))
        return text, f"(Gemini exception: {e})"


# ===================== BILDIRIM =====================

async def notify_admin(
    source_title: str,
    source_id,
    text: str,
    links: list[str],
    ceviri: str,
    ozet: str,
):
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


# ===================== LISTENER =====================

async def on_new_message(event):
    try:
        if not event.message or not event.message.message:
            # bazen sadece media/caption
            text = getattr(event.message, "message", None) or ""
            if not text and event.message:
                text = ""
        else:
            text = event.message.message or ""

        extra_urls = []
        for ent in event.message.entities or []:
            u = getattr(ent, "url", None)
            if u:
                extra_urls.append(str(u))
        if extra_urls:
            text = (text or "") + "\n" + "\n".join(extra_urls)

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
        raise SystemExit("ADMIN_CHAT_ID zorunlu (senin Telegram user id)")
    if not SOURCE_CHATS:
        raise SystemExit("SOURCE_CHATS zorunlu - ornek: -100111,-100222")

    print("=" * 60)
    print("OYUN / AIRDROP RADARI BASLIYOR")
    print("=" * 60)
    print("[KONFIG] ADMIN_CHAT_ID =", ADMIN_CHAT_ID)
    print("[KONFIG] SOURCE_CHATS =", SOURCE_CHATS)
    print("[KONFIG] GEMINI =", "aktif" if GEMINI_API_KEY else "YOK (ceviri olmadan calisir)")

    http_session = aiohttp.ClientSession()
    client = TelegramClient(StringSession(STRING_SESSION), API_ID, API_HASH)

    await client.start()
    me = await client.get_me()
    print("[TELEGRAM] Baglandi:", me.id, getattr(me, "username", None))

    resolved = []
    for item in SOURCE_CHATS:
        try:
            entity = await client.get_entity(item)
            resolved.append(entity)
            print(
                "[KAYNAK OK]",
                item,
                "->",
                getattr(entity, "id", None),
                getattr(entity, "title", None),
            )
        except Exception as e:
            print("[KAYNAK HATA]", item, repr(e))

    if not resolved:
        raise SystemExit("Hicbir kaynak grup cozulemedi - uyelik / ID kontrol et")

    client.add_event_handler(on_new_message, events.NewMessage(chats=resolved))

    await client.send_message(
        ADMIN_CHAT_ID,
        f"Radar aktif\nKaynak: {len(resolved)} grup\nGemini: {'acik' if GEMINI_API_KEY else 'kapali'}",
    )

    print("[HAZIR] Dinleniyor...")
    await client.run_until_disconnected()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
