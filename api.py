from fastapi import FastAPI, Query
from fastapi.responses import FileResponse
import os
from fastapi.middleware.cors import CORSMiddleware
import sqlite3, requests
from bs4 import BeautifulSoup
from typing import Optional

app = FastAPI(title="Funpay Mirror API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

DB_PATH = "lots.db"

def get_con():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con

@app.get("/api/lots")
def get_lots(
    game: Optional[str] = Query(None, description="Фильтр по игре"),
    min_price: float = Query(0, description="Минимальная цена"),
    max_price: Optional[float] = Query(None, description="Максимальная цена"),
    online_only: bool = Query(False, description="Только онлайн продавцы"),
    min_rating: float = Query(0, description="Минимальный рейтинг продавца"),
    search: Optional[str] = Query(None, description="Поиск по названию"),
    sort: str = Query("price_asc", description="Сортировка: price_asc, price_desc, newest"),
    limit: int = Query(50, le=200),
    offset: int = Query(0),
):
    con = get_con()
    cur = con.cursor()

    conditions = ["sold = 0", "price >= :min_price"]
    params: dict = {"min_price": min_price}

    if max_price:
        conditions.append("price <= :max_price")
        params["max_price"] = max_price

    if game:
        conditions.append("game LIKE :game")
        params["game"] = f"%{game}%"

    if online_only:
        conditions.append("seller_online = 1")

    if min_rating > 0:
        conditions.append("seller_rating >= :min_rating")
        params["min_rating"] = min_rating

    if search:
        conditions.append("(title LIKE :search OR description LIKE :search)")
        params["search"] = f"%{search}%"

    order = {
        "price_asc":  "price ASC",
        "price_desc": "price DESC",
        "newest":     "first_seen DESC",
    }.get(sort, "price ASC")

    where = " AND ".join(conditions)
    query = f"""
        SELECT * FROM lots
        WHERE {where}
        ORDER BY {order}
        LIMIT :limit OFFSET :offset
    """
    params["limit"] = limit
    params["offset"] = offset

    rows = cur.execute(query, params).fetchall()

    # Подсчёт общего количества
    count_row = cur.execute(
        f"SELECT COUNT(*) FROM lots WHERE {where}",
        {k: v for k, v in params.items() if k not in ("limit", "offset")}
    ).fetchone()
    total = count_row[0]

    con.close()
    return {
        "total": total,
        "offset": offset,
        "limit": limit,
        "items": [dict(r) for r in rows],
    }

@app.get("/api/games")
def get_games():
    """Список уникальных игр/категорий в базе"""
    con = get_con()
    rows = con.execute(
        "SELECT DISTINCT game, COUNT(*) as cnt FROM lots WHERE sold=0 GROUP BY game ORDER BY cnt DESC"
    ).fetchall()
    con.close()
    return [dict(r) for r in rows]

@app.get("/api/stats")
def get_stats():
    con = get_con()
    cur = con.cursor()
    total = cur.execute("SELECT COUNT(*) FROM lots WHERE sold=0").fetchone()[0]
    sold  = cur.execute("SELECT COUNT(*) FROM lots WHERE sold=1").fetchone()[0]
    avg_p = cur.execute("SELECT AVG(price) FROM lots WHERE sold=0").fetchone()[0]
    con.close()
    return {"active": total, "sold": sold, "avg_price": round(avg_p or 0, 2)}

@app.get("/api/lot/{lot_id}")
def get_lot_detail(lot_id: str):
    url = f"https://funpay.com/en/lots/offer?id={lot_id}"
    try:
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        r.raise_for_status()
    except Exception as e:
        return {"error": str(e)}

    soup = BeautifulSoup(r.text, "html.parser")

    # Full description — in param-item starting with "Detailed description"
    description = ""
    for el in soup.select(".param-item"):
        text = el.get_text(separator="\n", strip=True)
        if text.startswith("Detailed description"):
            description = text.replace("Detailed description", "", 1).strip()
            break

    # Seller info
    seller_el = soup.select_one(".media-user-name")
    seller = seller_el.text.strip() if seller_el else ""

    # Rating
    rating_el = soup.select_one(".rating-stars")
    rating = ""
    if rating_el:
        for cls in rating_el.get("class", []):
            if cls.startswith("rating-") and cls != "rating-stars":
                rating = cls.split("-")[-1]
                break

    # Reviews count
    reviews_el = soup.select_one(".rating-mini-count")
    reviews = reviews_el.text.strip() if reviews_el else "0"

    # Price
    price_el = soup.select_one(".tc-price")
    price = price_el.get("data-s", "") if price_el else ""
    unit_el = price_el.select_one(".unit") if price_el else None
    unit = unit_el.text.strip() if unit_el else ""

    # All images
    images = []
    for img in soup.select(".offer-images img, .tc-image img"):
        src = img.get("src", "")
        if src:
            images.append(src)

    # Seller online status
    media_el = soup.select_one(".media")
    online = bool(media_el and "online" in (media_el.get("class") or []))

    return {
        "id": lot_id,
        "url": url,
        "description": description,
        "seller": seller,
        "seller_rating": rating,
        "seller_reviews": reviews,
        "seller_online": online,
        "price": price,
        "unit": unit,
        "images": images,
    }

@app.get("/")
def serve_index():
    return FileResponse("index.html")
