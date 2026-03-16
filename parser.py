import requests
from bs4 import BeautifulSoup
import sqlite3
import time
import logging
from datetime import datetime
import schedule
import random
from zoneinfo import ZoneInfo  # для корректного UTC

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

DB_PATH = "lots.db"

# ── Настройки ──────────────────────────────────────────────
MIN_PRICE = 1
MIN_SELLER_RATING = 4.5
REQUIRE_DESCRIPTION = True
ONLINE_ONLY = False

ACCOUNT_CATEGORIES = {
    "1400": "Honkai: Star Rail Accounts",
}

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0",
]

HEADERS_BASE = {
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
}

# ── База данных ───────────────────────────────────────────
def init_db():
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS lots (
            id              TEXT PRIMARY KEY,
            category_id     TEXT,
            title           TEXT,
            description     TEXT,
            price           REAL,
            price_str       TEXT,
            seller          TEXT,
            seller_rating   REAL,
            seller_online   INTEGER,
            game            TEXT,
            url             TEXT,
            image_url       TEXT,
            sold            INTEGER DEFAULT 0,
            first_seen      TEXT,
            last_seen       TEXT
        )
    """)
    con.commit()
    con.close()

# ── Случайный заголовок ───────────────────────────────────
def get_headers():
    return {
        **HEADERS_BASE,
        "User-Agent": random.choice(USER_AGENTS)
    }

# ── Парсер страницы ───────────────────────────────────────
def parse_category(category_id: str, game_name: str) -> list[dict]:
    url = f"https://funpay.com/en/lots/{category_id}/"
    headers = get_headers()

    try:
        r = requests.get(url, headers=headers, timeout=20)
        r.raise_for_status()
    except Exception as e:
        log.error(f"Не удалось загрузить {url}: {e}")
        return []

    soup = BeautifulSoup(r.text, "html.parser")
    items = soup.select(".tc-item")
    log.info(f"[{game_name}] Найдено карточек: {len(items)}")

    lots = []
    for item in items:
        try:
            href = item.get("href", "")
            lot_id = href.split("id=")[-1] if "id=" in href else ""
            if not lot_id:
                continue

            # Цена
            price_el = item.select_one(".tc-price")
            if not price_el:
                continue
            price_raw = price_el.get("data-s", "0")
            try:
                price_num = float(price_raw)
            except ValueError:
                continue

            if price_num < MIN_PRICE:
                continue

            unit_el = price_el.select_one(".unit")
            unit = unit_el.text.strip() if unit_el else "€"
            price_str = f"{price_num:.2f} {unit}"

            # ── ФИЛЬТР ПО EUROPE ───────────────────────────────────────
            server_el = item.select_one(".tc-server")
            region = server_el.text.strip() if server_el else ""
            if region != "Europe":
                continue

            # ── Описание ───────────────────────────────────────────────
            desc_el = item.select_one(".tc-desc-text")
            desc_text = desc_el.get_text(separator=" ", strip=True) if desc_el else ""

            if REQUIRE_DESCRIPTION and not desc_text.strip():
                continue

            # Продавец
            seller_el = item.select_one(".media-user-name")
            seller = seller_el.text.strip() if seller_el else "unknown"

            # Рейтинг
            seller_rating = 0.0
            rating_el = item.select_one("[class*='rating-']")
            if rating_el:
                for cls in rating_el.get("class", []):
                    if cls.startswith("rating-") and cls not in ["rating-stars", "rating-mini-count"]:
                        try:
                            seller_rating = float(cls.split("-")[-1])
                            break
                        except ValueError:
                            pass

            if seller_rating > 0 and seller_rating < MIN_SELLER_RATING:
                continue

            # Онлайн
            media_el = item.select_one(".media")
            seller_online = 1 if media_el and "online" in (media_el.get("class") or []) else 0
            if ONLINE_ONLY and not seller_online:
                continue

            # Ссылки
            lot_url = f"https://funpay.com{href}" if href.startswith("/") else href
            img_el = item.select_one("img")
            image_url = img_el.get("src", "") if img_el else ""

            # Заголовок — берём из описания
            title = desc_text.strip()[:140]
            if len(desc_text) > 140:
                title += "..."
            # Пропускаем лоты с кириллицей в названии — английская версия уже есть
            import re as _re
            if _re.search(r'[а-яА-ЯёЁ]', title):
                continue
            has_cyrillic = 0

            lots.append({
                "id": lot_id,
                "category_id": category_id,
                "title": title,
                "has_cyrillic": has_cyrillic,
                "description": desc_text,
                "price": price_num,
                "price_str": price_str,
                "seller": seller,
                "seller_rating": seller_rating,
                "seller_online": seller_online,
                "game": game_name,
                "url": lot_url,
                "image_url": image_url,
            })

            # ── Отладка (раскомментируй при необходимости) ─────────────
            # log.debug(f"Lot {lot_id} | europe: {europe_count} | {full_text[:180]}")

        except Exception as e:
            log.warning(f"Ошибка лота {lot_id}: {e}")
            continue

    log.info(f"[{game_name}] После фильтра Europe: {len(lots)} лотов")
    return lots

# ── Обновление базы ───────────────────────────────────────
def update_db(fresh_lots: list[dict], category_id: str):
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    now = datetime.now(ZoneInfo("UTC")).isoformat()

    for lot in fresh_lots:
        cur.execute("""
            INSERT INTO lots 
                (id, category_id, title, description, price, price_str,
                 seller, seller_rating, seller_online, game, url, image_url,
                 sold, first_seen, last_seen)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,0,?,?)
            ON CONFLICT(id) DO UPDATE SET
                price        = excluded.price,
                price_str    = excluded.price_str,
                seller_online= excluded.seller_online,
                sold         = 0,
                last_seen    = excluded.last_seen
        """, (
            lot["id"], lot["category_id"], lot["title"], lot["description"],
            lot["price"], lot["price_str"], lot["seller"], lot["seller_rating"],
            lot["seller_online"], lot["game"], lot["url"], lot["image_url"],
            now, now
        ))

    # Помечаем проданные
    cur.execute(
        "UPDATE lots SET sold=1 WHERE category_id=? AND sold=0 AND last_seen < ?",
        (category_id, now)
    )

    con.commit()
    con.close()
    log.info(f"[{category_id}] База обновлена. Активных Europe: {len(fresh_lots)}")

# ── Запуск ────────────────────────────────────────────────
def run_parser():
    log.info("=== Запуск парсера (только Europe) ===")
    for cat_id, game_name in ACCOUNT_CATEGORIES.items():
        lots = parse_category(cat_id, game_name)
        update_db(lots, cat_id)
        time.sleep(random.uniform(10, 18))  # более безопасная пауза
    log.info("=== Завершено ===")

if __name__ == "__main__":
    init_db()
    run_parser()  # первый запуск сразу

    schedule.every(6).minutes.do(run_parser)
    log.info("Планировщик: каждые 6 минут")

    while True:
        schedule.run_pending()
        time.sleep(30)