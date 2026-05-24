import os
import asyncio
import logging
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from parser import DomclickParser
from config import load_config, save_config, get_user_config, update_user_config

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN")
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())
scheduler = AsyncIOScheduler()
parser = DomclickParser()


class FilterStates(StatesGroup):
    region = State()
    price_min = State()
    price_max = State()
    area_min = State()
    area_max = State()
    land_min = State()
    land_max = State()


def main_menu():
    kb = ReplyKeyboardMarkup(resize_keyboard=True, keyboard=[
        [KeyboardButton(text="🔍 Искать сейчас"), KeyboardButton(text="⚙️ Фильтры")],
        [KeyboardButton(text="🔔 Автопоиск: вкл/выкл"), KeyboardButton(text="📋 Мои настройки")],
    ])
    return kb


def back_menu():
    kb = ReplyKeyboardMarkup(resize_keyboard=True, keyboard=[
        [KeyboardButton(text="❌ Отмена")]
    ])
    return kb


@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    user_id = message.from_user.id
    cfg = get_user_config(user_id)
    if not cfg:
        update_user_config(user_id, {
            "region": "Московская область",
            "price_min": None,
            "price_max": None,
            "area_min": None,
            "area_max": None,
            "land_min": None,
            "land_max": None,
            "auto_search": False,
            "seen_ids": []
        })
    await message.answer(
        "🏡 <b>Домклик Парсер</b>\n\n"
        "Ищу дома с участком в Московской области.\n"
        "Настрой фильтры и нажми «Искать сейчас» или включи автопоиск — "
        "буду присылать новые объявления каждые 30 минут.",
        parse_mode="HTML",
        reply_markup=main_menu()
    )


@dp.message(lambda m: m.text == "📋 Мои настройки")
async def show_settings(message: types.Message):
    cfg = get_user_config(message.from_user.id) or {}
    price_min = f"{cfg.get('price_min'):,}".replace(",", " ") if cfg.get("price_min") else "не задано"
    price_max = f"{cfg.get('price_max'):,}".replace(",", " ") if cfg.get("price_max") else "не задано"
    area_min = cfg.get("area_min") or "не задано"
    area_max = cfg.get("area_max") or "не задано"
    land_min = cfg.get("land_min") or "не задано"
    land_max = cfg.get("land_max") or "не задано"
    auto = "✅ включён" if cfg.get("auto_search") else "❌ выключен"

    text = (
        f"📋 <b>Текущие фильтры</b>\n\n"
        f"📍 Регион: <b>{cfg.get('region', 'Московская область')}</b>\n"
        f"💰 Цена: <b>{price_min} — {price_max} ₽</b>\n"
        f"🏠 Площадь дома: <b>{area_min} — {area_max} м²</b>\n"
        f"🌿 Площадь участка: <b>{land_min} — {land_max} сот.</b>\n"
        f"🔔 Автопоиск: <b>{auto}</b>"
    )
    await message.answer(text, parse_mode="HTML", reply_markup=main_menu())


@dp.message(lambda m: m.text == "⚙️ Фильтры")
async def filters_menu(message: types.Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📍 Регион", callback_data="filter_region")],
        [InlineKeyboardButton(text="💰 Цена (мин)", callback_data="filter_price_min"),
         InlineKeyboardButton(text="💰 Цена (макс)", callback_data="filter_price_max")],
        [InlineKeyboardButton(text="🏠 Площадь дома (мин)", callback_data="filter_area_min"),
         InlineKeyboardButton(text="🏠 Площадь дома (макс)", callback_data="filter_area_max")],
        [InlineKeyboardButton(text="🌿 Участок (мин, сот)", callback_data="filter_land_min"),
         InlineKeyboardButton(text="🌿 Участок (макс, сот)", callback_data="filter_land_max")],
        [InlineKeyboardButton(text="🔄 Сбросить все фильтры", callback_data="filter_reset")],
    ])
    await message.answer("⚙️ <b>Выбери фильтр для настройки:</b>", parse_mode="HTML", reply_markup=kb)


@dp.callback_query(lambda c: c.data == "filter_reset")
async def filter_reset(callback: types.CallbackQuery):
    update_user_config(callback.from_user.id, {
        "region": "Московская область",
        "price_min": None, "price_max": None,
        "area_min": None, "area_max": None,
        "land_min": None, "land_max": None,
    })
    await callback.answer("Фильтры сброшены ✅")
    await callback.message.edit_text("✅ Все фильтры сброшены. Регион: Московская область.")


@dp.callback_query(lambda c: c.data.startswith("filter_"))
async def filter_callback(callback: types.CallbackQuery, state: FSMContext):
    field = callback.data.replace("filter_", "")
    prompts = {
        "region": ("📍 Введи название региона или города:\nПример: <code>Московская область</code> или <code>Сергиев Посад</code>", FilterStates.region),
        "price_min": ("💰 Введи минимальную цену в рублях:\nПример: <code>3000000</code>", FilterStates.price_min),
        "price_max": ("💰 Введи максимальную цену в рублях:\nПример: <code>10000000</code>", FilterStates.price_max),
        "area_min": ("🏠 Введи минимальную площадь дома (м²):\nПример: <code>80</code>", FilterStates.area_min),
        "area_max": ("🏠 Введи максимальную площадь дома (м²):\nПример: <code>200</code>", FilterStates.area_max),
        "land_min": ("🌿 Введи минимальную площадь участка (сотки):\nПример: <code>6</code>", FilterStates.land_min),
        "land_max": ("🌿 Введи максимальную площадь участка (сотки):\nПример: <code>30</code>", FilterStates.land_max),
    }
    prompt, state_obj = prompts[field]
    await state.set_state(state_obj)
    await state.update_data(field=field)
    await callback.message.answer(f"{prompt}\n\nОтправь <code>0</code> чтобы сбросить этот фильтр.", parse_mode="HTML", reply_markup=back_menu())
    await callback.answer()


async def handle_filter_input(message: types.Message, state: FSMContext, field: str, is_str=False):
    text = message.text.strip()
    if text == "❌ Отмена":
        await state.clear()
        await message.answer("Отменено.", reply_markup=main_menu())
        return
    if is_str:
        update_user_config(message.from_user.id, {field: text})
        await state.clear()
        await message.answer(f"✅ Сохранено: <b>{text}</b>", parse_mode="HTML", reply_markup=main_menu())
    else:
        try:
            val = int(text.replace(" ", ""))
            update_user_config(message.from_user.id, {field: None if val == 0 else val})
            display = "сброшен" if val == 0 else f"{val:,}".replace(",", " ")
            await state.clear()
            await message.answer(f"✅ Сохранено: <b>{display}</b>", parse_mode="HTML", reply_markup=main_menu())
        except ValueError:
            await message.answer("⚠️ Введи число, например: <code>5000000</code>", parse_mode="HTML")


@dp.message(FilterStates.region)
async def set_region(message: types.Message, state: FSMContext):
    await handle_filter_input(message, state, "region", is_str=True)

@dp.message(FilterStates.price_min)
async def set_price_min(message: types.Message, state: FSMContext):
    await handle_filter_input(message, state, "price_min")

@dp.message(FilterStates.price_max)
async def set_price_max(message: types.Message, state: FSMContext):
    await handle_filter_input(message, state, "price_max")

@dp.message(FilterStates.area_min)
async def set_area_min(message: types.Message, state: FSMContext):
    await handle_filter_input(message, state, "area_min")

@dp.message(FilterStates.area_max)
async def set_area_max(message: types.Message, state: FSMContext):
    await handle_filter_input(message, state, "area_max")

@dp.message(FilterStates.land_min)
async def set_land_min(message: types.Message, state: FSMContext):
    await handle_filter_input(message, state, "land_min")

@dp.message(FilterStates.land_max)
async def set_land_max(message: types.Message, state: FSMContext):
    await handle_filter_input(message, state, "land_max")


@dp.message(lambda m: m.text == "🔔 Автопоиск: вкл/выкл")
async def toggle_auto(message: types.Message):
    cfg = get_user_config(message.from_user.id) or {}
    new_val = not cfg.get("auto_search", False)
    update_user_config(message.from_user.id, {"auto_search": new_val})
    status = "✅ включён" if new_val else "❌ выключен"
    await message.answer(
        f"🔔 Автопоиск {status}.\n"
        + ("Буду присылать новые объявления каждые 30 минут." if new_val else "Уведомления остановлены."),
        reply_markup=main_menu()
    )


@dp.message(lambda m: m.text == "🔍 Искать сейчас")
async def search_now(message: types.Message):
    await message.answer("🔍 Ищу объявления, подожди немного...")
    cfg = get_user_config(message.from_user.id) or {}
    results = await parser.fetch(cfg)
    if not results:
        await message.answer("😔 По твоим фильтрам ничего не нашлось. Попробуй расширить параметры.", reply_markup=main_menu())
        return
    await message.answer(f"✅ Найдено: <b>{len(results)}</b> объявлений. Показываю первые 5.", parse_mode="HTML")
    for item in results[:5]:
        await send_listing(message.chat.id, item)


async def send_listing(chat_id: int, item: dict):
    price = f"{item['price']:,}".replace(",", " ") + " ₽" if item.get("price") else "Цена не указана"
    area = f"{item['area']} м²" if item.get("area") else ""
    land = f"{item['land']} сот." if item.get("land") else ""
    parts = [p for p in [area, land] if p]
    details = " · ".join(parts)

    text = (
        f"🏡 <b>{item.get('title', 'Дом с участком')}</b>\n"
        f"📍 {item.get('address', '')}\n"
        f"💰 <b>{price}</b>\n"
        + (f"📐 {details}\n" if details else "")
        + f"\n<a href='{item['url']}'>Открыть на Домклик →</a>"
    )
    try:
        if item.get("photo"):
            await bot.send_photo(chat_id, item["photo"], caption=text, parse_mode="HTML")
        else:
            await bot.send_message(chat_id, text, parse_mode="HTML", disable_web_page_preview=False)
    except Exception as e:
        logger.warning(f"Ошибка отправки: {e}")
        await bot.send_message(chat_id, text, parse_mode="HTML")


async def auto_search_job():
    cfg_all = load_config()
    for user_id_str, cfg in cfg_all.items():
        if not cfg.get("auto_search"):
            continue
        user_id = int(user_id_str)
        try:
            results = await parser.fetch(cfg)
            seen = set(cfg.get("seen_ids", []))
            new_items = [r for r in results if r["id"] not in seen]
            if new_items:
                await bot.send_message(user_id, f"🔔 <b>Новые объявления: {len(new_items)}</b>", parse_mode="HTML")
                for item in new_items[:10]:
                    await send_listing(user_id, item)
                    seen.add(item["id"])
                update_user_config(user_id, {"seen_ids": list(seen)[-500:]})
        except Exception as e:
            logger.error(f"Ошибка автопоиска для {user_id}: {e}")


async def main():
    scheduler.add_job(auto_search_job, "interval", minutes=30)
    scheduler.start()
    logger.info("Бот запущен")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
