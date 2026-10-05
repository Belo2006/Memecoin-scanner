"""
Memecoin-Scanner (Einmal-Lauf fuer GitHub Actions).
Prueft neue Solana-Token, schickt Treffer per Telegram und merkt sich
gemeldete Token in seen.json, damit nichts doppelt kommt.

WICHTIG: Das ist ein Filter, keine Vorhersage. Die meisten neuen
Memecoins fallen auf null.
"""
import json
import os
import time
import requests

CHAIN = "solana"

# ---- Filter (nach Geschmack anpassen) ----
MIN_LIQUIDITY_USD = 15_000
MIN_VOLUME_1H_USD = 20_000
MIN_MARKET_CAP_USD = 50_000
MAX_MARKET_CAP_USD = 2_000_000
MIN_AGE_MIN = 10
MAX_AGE_MIN = 6 * 60
MIN_BUY_RATIO = 0.55
MIN_TXNS_1H = 150

API = "https://api.dexscreener.com"
STATE_FILE = "seen.json"


def get(url):
    try:
        r = requests.get(url, timeout=15)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print("Fehler:", url, e)
        return None


def load_seen():
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except Exception:
        return []


def save_seen(seen):
    with open(STATE_FILE, "w") as f:
        json.dump(seen[-2000:], f)


def latest_token_addresses():
    data = get(f"{API}/token-profiles/latest/v1") or []
    return [t["tokenAddress"] for t in data if t.get("chainId") == CHAIN]


def pairs_for(addresses):
    out = []
    for i in range(0, len(addresses), 30):
        chunk = ",".join(addresses[i:i + 30])
        data = get(f"{API}/tokens/v1/{CHAIN}/{chunk}")
        if data:
            out.extend(data)
    return out


def rug_flags(mint):
    data = get(f"https://api.rugcheck.xyz/v1/tokens/{mint}/report/summary")
    if not data:
        return ["RugCheck nicht erreichbar"]
    risks = data.get("risks") or []
    return [r.get("name", "?") for r in risks if r.get("level") in ("danger", "warn")]


def passes(p):
    now_ms = time.time() * 1000
    age_min = (now_ms - p.get("pairCreatedAt", now_ms)) / 60000
    liq = (p.get("liquidity") or {}).get("usd", 0)
    vol = (p.get("volume") or {}).get("h1", 0)
    mc = p.get("marketCap") or p.get("fdv") or 0
    tx = (p.get("txns") or {}).get("h1", {})
    buys, sells = tx.get("buys", 0), tx.get("sells", 0)
    total = buys + sells
    ratio = buys / total if total else 0
    return (
        MIN_AGE_MIN <= age_min <= MAX_AGE_MIN
        and liq >= MIN_LIQUIDITY_USD
        and vol >= MIN_VOLUME_1H_USD
        and MIN_MARKET_CAP_USD <= mc <= MAX_MARKET_CAP_USD
        and total >= MIN_TXNS_1H
        and ratio >= MIN_BUY_RATIO
    )


def send(msg):
    token = os.environ.get("TELEGRAM_TOKEN")
    chat = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat:
        print(msg)
        return
    r = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={"chat_id": chat, "text": msg, "disable_web_page_preview": True},
        timeout=15,
    )
    print("Telegram:", r.status_code)


def main():
    seen = load_seen()
    addrs = latest_token_addresses()
    for p in pairs_for(addrs):
        mint = p["baseToken"]["address"]
        if mint in seen or not passes(p):
            continue
        flags = rug_flags(mint)
        mc = p.get("marketCap") or p.get("fdv") or 0
        msg = (
            f"Kandidat: {p['baseToken']['symbol']} ({p['baseToken']['name']})\n"
            f"Market Cap: ${mc:,.0f} | Liquiditaet: ${p['liquidity']['usd']:,.0f}\n"
            f"Vol 1h: ${p['volume']['h1']:,.0f}\n"
            f"Warnungen: {', '.join(flags) if flags else 'keine gefunden'}\n"
            f"Chart: {p['url']}\n"
            f"Mint: {mint}\n"
            f"Kein Anlagetipp - selbst pruefen."
        )
        send(msg)
        seen.append(mint)
    save_seen(seen)
    print("Fertig, geprueft:", len(addrs))


if __name__ == "__main__":
    main()
