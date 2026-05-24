import aiohttp
import asyncio
import logging
import re
import json

logger = logging.getLogger(__name__)

# Заголовки имитируют реальный браузер
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": "https://domclick.ru/",
    "DNT": "1",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}

# Актуальный API эндпоинт (перехвачен из браузера, 2025)
SEARCH_URL = "https://estate.domclick.ru/api/offer-service/v2/get/offers"


class DomclickParser:

    def _build_params(self, cfg: dict) -> dict:
        """Строим параметры запроса под актуальный API Домклик"""
        params = {
            "deal_type": "sale",
            "offer_type": "house",       # дом
            "with_neighbors": "true",    # включая ближайшие районы
            "offset": 0,
            "limit": 20,
            "sort": "creation_date",
            "order": "desc",
        }

        region = cfg.get("region", "Московская область")
        params["location_name"] = region

        if cfg.get("price_min"):
            params["price_from"] = int(cfg["price_min"])
        if cfg.get("price_max"):
            params["price_to"] = int(cfg["price_max"])
        if cfg.get("area_min"):
            params["house_area_from"] = int(cfg["area_min"])
        if cfg.get("area_max"):
            params["house_area_to"] = int(cfg["area_max"])
        if cfg.get("land_min"):
            params["land_area_from"] = int(cfg["land_min"])
        if cfg.get("land_max"):
            params["land_area_to"] = int(cfg["land_max"])

        return params

    def _parse_item(self, raw: dict) -> dict | None:
        try:
            offer_id = str(raw.get("id") or raw.get("offer_id") or "")
            if not offer_id:
                return None

            # Цена
            price_val = None
            price_block = raw.get("price") or {}
            if isinstance(price_block, dict):
                price_val = price_block.get("value") or price_block.get("amount")
            elif isinstance(price_block, (int, float)):
                price_val = int(price_block)
            if price_val:
                try:
                    price_val = int(float(price_val))
                except Exception:
                    price_val = None

            # Площади
            total_area = (
                raw.get("house_area")
                or raw.get("total_area")
                or (raw.get("house") or {}).get("total_area")
            )
            land_area = (
                raw.get("land_area")
                or (raw.get("land") or {}).get("area")
            )

            # Адрес
            addr_parts = []
            addr = raw.get("address") or raw.get("location") or {}
            if isinstance(addr, dict):
                for key in ("region", "region_name", "area", "area_name",
                            "settlement", "settlement_name", "street", "street_name", "house"):
                    v = addr.get(key)
                    if v:
                        addr_parts.append(str(v))
            address_str = ", ".join(addr_parts) or raw.get("full_address", "адрес не указан")

            # Фото
            photo_url = None
            photos = raw.get("photos") or raw.get("images") or []
            if photos and isinstance(photos, list):
                first = photos[0]
                if isinstance(first, dict):
                    photo_url = (first.get("large_url") or first.get("medium_url")
                                 or first.get("url") or first.get("large") or first.get("medium"))
                elif isinstance(first, str):
                    photo_url = first

            # Тип объекта для заголовка
            obj_type = raw.get("offer_type_name") or raw.get("category") or "Дом с участком"

            return {
                "id": offer_id,
                "title": obj_type,
                "address": address_str,
                "price": price_val,
                "area": total_area,
                "land": land_area,
                "photo": photo_url,
                "url": f"https://domclick.ru/card/sale__house__{offer_id}",
            }
        except Exception as e:
            logger.warning(f"Ошибка парсинга объекта: {e}")
            return None

    async def fetch(self, cfg: dict) -> list:
        params = self._build_params(cfg)
        timeout = aiohttp.ClientTimeout(total=25)
        connector = aiohttp.TCPConnector(ssl=False)

        async with aiohttp.ClientSession(headers=HEADERS, connector=connector) as session:
            # Сначала «прогреваем» сессию — заходим на главную страницу
            try:
                async with session.get("https://domclick.ru/", timeout=aiohttp.ClientTimeout(total=10)):
                    pass
            except Exception:
                pass

            # Пробуем основной эндпоинт
            result = await self._try_endpoint(session, SEARCH_URL, params, timeout)
            if result is not None:
                return result

            # Запасной эндпоинт (старый v1)
            fallback_url = "https://estate.domclick.ru/api/offer-service/v1/get/offers"
            result = await self._try_endpoint(session, fallback_url, params, timeout)
            if result is not None:
                return result

            # Ещё один запасной — через основной сайт
            result = await self._try_main_api(session, cfg, timeout)
            if result is not None:
                return result

        logger.error("Все эндпоинты не вернули данных")
        return []

    async def _try_endpoint(self, session, url: str, params: dict, timeout) -> list | None:
        try:
            async with session.get(url, params=params, timeout=timeout) as resp:
                logger.info(f"GET {url} → {resp.status}")
                if resp.status not in (200, 201):
                    body = await resp.text()
                    logger.warning(f"Статус {resp.status}, тело: {body[:300]}")
                    return None
                data = await resp.json(content_type=None)
                offers = (
                    data.get("result", {}).get("offers")
                    or data.get("data", {}).get("offers")
                    or data.get("offers")
                    or []
                )
                logger.info(f"Найдено объявлений: {len(offers)}")
                items = [self._parse_item(o) for o in offers]
                return [i for i in items if i]
        except asyncio.TimeoutError:
            logger.warning(f"Таймаут запроса к {url}")
            return None
        except Exception as e:
            logger.warning(f"Ошибка запроса к {url}: {e}")
            return None

    async def _try_main_api(self, session, cfg: dict, timeout) -> list | None:
        """Запрос через основной API домклика с другими параметрами"""
        url = "https://domclick.ru/api/search-front/v1/serp/offers"
        region = cfg.get("region", "Московская область")
        params = {
            "deal_type": "sale",
            "category": "house",
            "sort": "creation_date_desc",
            "page": 0,
            "size": 20,
            "q": region,
        }
        if cfg.get("price_min"):
            params["price_min"] = cfg["price_min"]
        if cfg.get("price_max"):
            params["price_max"] = cfg["price_max"]
        return await self._try_endpoint(session, url, params, timeout)
