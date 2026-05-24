import aiohttp
import logging
import urllib.parse

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "ru-RU,ru;q=0.9",
    "Referer": "https://domclick.ru/",
    "Origin": "https://domclick.ru",
}

BASE_URL = "https://api.domclick.ru/realty-search/api/v3/offers/search"


class DomclickParser:
    def __init__(self):
        self.session = None

    async def _get_session(self):
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(headers=HEADERS)
        return self.session

    def _build_params(self, cfg: dict) -> dict:
        params = {
            "deal_type": "sale",
            "category": "house",          # дома
            "with_neighbors": "false",
            "page": 0,
            "page_size": 20,
            "sort": "creation_date_desc",  # сначала новые
        }

        region = cfg.get("region", "Московская область")
        params["search_text"] = region

        if cfg.get("price_min"):
            params["price_from"] = cfg["price_min"]
        if cfg.get("price_max"):
            params["price_to"] = cfg["price_max"]
        if cfg.get("area_min"):
            params["total_area_from"] = cfg["area_min"]
        if cfg.get("area_max"):
            params["total_area_to"] = cfg["area_max"]
        if cfg.get("land_min"):
            params["land_area_from"] = cfg["land_min"]
        if cfg.get("land_max"):
            params["land_area_to"] = cfg["land_max"]

        return params

    def _parse_item(self, raw: dict) -> dict:
        offer_id = str(raw.get("id", ""))
        price = raw.get("price", {})
        price_val = price.get("amount") if isinstance(price, dict) else None
        if price_val:
            try:
                price_val = int(float(price_val))
            except Exception:
                price_val = None

        house = raw.get("house", {}) or {}
        total_area = house.get("total_area") or raw.get("total_area")
        land_area = raw.get("land_area") or house.get("land_area")

        address_parts = []
        addr = raw.get("address", {}) or {}
        for key in ("region_name", "area_name", "settlement_name", "street_name", "house_number"):
            val = addr.get(key)
            if val:
                address_parts.append(val)
        address_str = ", ".join(address_parts) if address_parts else raw.get("full_address", "")

        photos = raw.get("photos", []) or raw.get("images", [])
        photo_url = None
        if photos:
            first = photos[0]
            if isinstance(first, dict):
                photo_url = first.get("large") or first.get("medium") or first.get("url")
            elif isinstance(first, str):
                photo_url = first

        url = f"https://domclick.ru/card/sale__house__{offer_id}"

        title_parts = []
        if house.get("rooms_count"):
            title_parts.append(f"{house['rooms_count']}-комн. дом")
        else:
            title_parts.append("Дом с участком")

        return {
            "id": offer_id,
            "title": title_parts[0],
            "address": address_str,
            "price": price_val,
            "area": total_area,
            "land": land_area,
            "photo": photo_url,
            "url": url,
        }

    async def fetch(self, cfg: dict) -> list:
        session = await self._get_session()
        params = self._build_params(cfg)
        try:
            async with session.get(BASE_URL, params=params, timeout=aiohttp.ClientTimeout(total=20)) as resp:
                if resp.status != 200:
                    logger.warning(f"Домклик вернул статус {resp.status}")
                    return await self._fallback_fetch(cfg)
                data = await resp.json()
                items = data.get("result", {}).get("offers", [])
                if not items:
                    items = data.get("offers", [])
                if not items:
                    logger.info("Пустой ответ от API, пробуем запасной метод")
                    return await self._fallback_fetch(cfg)
                return [self._parse_item(i) for i in items if i.get("id")]
        except Exception as e:
            logger.error(f"Ошибка запроса к Домклик: {e}")
            return await self._fallback_fetch(cfg)

    async def _fallback_fetch(self, cfg: dict) -> list:
        """Запасной метод через альтернативный эндпоинт"""
        session = await self._get_session()
        region = cfg.get("region", "Московская область")
        fallback_url = "https://api.domclick.ru/realty-search/api/v2/offers"
        params = {
            "deal_type": "sale",
            "offer_type": "flat,house",
            "search_text": region,
            "sort": "creation_date_desc",
            "page": 0,
            "limit": 20,
        }
        if cfg.get("price_min"):
            params["price_from"] = cfg["price_min"]
        if cfg.get("price_max"):
            params["price_to"] = cfg["price_max"]
        try:
            async with session.get(fallback_url, params=params, timeout=aiohttp.ClientTimeout(total=20)) as resp:
                if resp.status != 200:
                    return []
                data = await resp.json()
                items = data.get("result", {}).get("offers", data.get("offers", []))
                return [self._parse_item(i) for i in items if i.get("id")]
        except Exception as e:
            logger.error(f"Fallback тоже не сработал: {e}")
            return []
