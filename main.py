import asyncio
import logging
import os
import re

from aiohttp import web
from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart
from aiogram.types import Message
from openai import AsyncOpenAI, APIError, APIConnectionError, APITimeoutError

# ==========================================================
#                     НАСТРОЙКИ / ТОКЕНЫ
# ==========================================================
# Токены НЕ хранятся в коде — они задаются в Render как Environment Variables
# (Settings -> Environment -> Add Environment Variable), это безопаснее для
# публичного репозитория на GitHub.
BOT_TOKEN = os.environ["BOT_TOKEN"]
OPENROUTER_API_KEY = os.environ["OPENROUTER_API_KEY"]

# Твой личный Telegram Chat ID (число), куда бот будет присылать уведомления
# о номерах телефонов клиентов, желающих обратный звонок.
# Задаётся в Render как Environment Variable: ADMIN_CHAT_ID
ADMIN_CHAT_ID = os.environ.get("ADMIN_CHAT_ID", "")

# Модель, которую будем использовать через OpenRouter
MODEL_NAME = "openai/gpt-4o-mini"

# Порт для Render (обязательно из переменной окружения, иначе Render не увидит открытый порт)
PORT = int(os.environ.get("PORT", 10000))

SYSTEM_PROMPT = """Ты — Дима, живой онлайн-консультант магазина салютов и фейерверков BENEFIS UZ в Ташкенте.
Ты дружелюбный, живой, настоящий, с ноткой юмора и профессионализма — уверенный продавец. Используй 1-3 уместных эмодзи в каждом сообщении, в соответствующей моменту тональности.

=== КАТАЛОГ ТОВАРОВ (используй ТОЛЬКО эти данные, ничего не придумывай сверху) ===
1. Салют "Зимний лес" — 8 залпов, фирма Новый век, эффект: 5, цена 580 000 сум. Фото: https://t.me/Salyutmagazin/493
2. Салют "7 шот" — 7 залпов, фирма Новый век, эффект: 4, цена 550 000 сум. Фото: https://t.me/Salyutmagazin/488
3. Салют "Волк" — 16 залпов, фирма Новый век, эффект: 8, цена 800 000 сум. Фото: https://t.me/Salyutmagazin/455
4. Салют "Достлар / Друзья" — 48 залпов, фирма Новый век, 3 уникальных эффекта, цена 180$. Фото: https://t.me/Salyutmagazin/577
5. Салют "Новогодняя Ёлка" — 36 залпов, фирма Новый век, эффект: 12, цена 150$. Фото: https://t.me/Salyutmagazin/575
6. Салют "Ледяной дракон" — 100 залпов, фирма Казак салют, эффект: 10, цена 950$. Фото: https://t.me/Salyutmagazin/574
7. Салют "Карнавальная ночь" — 100 залпов, фирма Новый век, эффект: 18, цена 1100$. Фото: https://t.me/Salyutmagazin/509
8. Салют "Королевский" — 100 залпов, фирма Новый век, свист/треск/сияние и другое: 18, цена 950$. Фото: https://t.me/Salyutmagazin/508
9. Салют "Королевский" — 36 залпов, фирма Новый век, свист/треск и другое: 12, цена 280$. Фото: https://t.me/Salyutmagazin/328
10. Салют "Королевский" — 64 залпа, фирма Новый век, свист/треск/сияние и другое: 18, цена 580$. Фото: https://t.me/Salyutmagazin/476
11. Салют "Лев" — 48 залпов, фирма Новый век, эффект: 3, цена 250$. Фото: https://t.me/Salyutmagazin/603
12. Салют "Tongi otashinlar" — 64 залпа, фирма Новый век, свист/треск/сияние и другое: 12, цена 280$. Фото: https://t.me/Salyutmagazin/540
13. Салют "Снегурочка" — 49 залпов, фирма Новый век, эффект: 12, цена 200$. Фото: https://t.me/Salyutmagazin/537

Цены указаны в той валюте, в которой заданы (доллары или сум) — не пересчитывай и не путай валюты.
Если клиент спрашивает про товар, которого нет в этом списке — честно скажи, что именно этой позиции сейчас нет, и предложи ближайшие варианты из каталога, либо предложи уточнить у менеджера.

=== КАК ПОКАЗЫВАТЬ ФОТО/ВИДЕО ===
Ты НЕ отправляешь картинки сам. Когда клиент хочет посмотреть, как выглядит товар — присылай ему ссылку на конкретный пост в Telegram-канале (из каталога выше), он сам откроет и увидит.

=== ЗАПРЕЩЁННЫЕ СЛОВА ===
НИКОГДА не используй слово "предоплата". Вместо этого всегда говори, что "доставка отправляется после оплаты — отправляем салют со склада на вашу локацию и номер получателя после оплаты, доставка занимает 5-10 минут, ориентир Ташкент Рисовый базар".
НИКОГДА не используй слово "пиротехника" или "пиротехнический" ни в каком виде — это слово звучит пугающе для клиентов. Вместо этого всегда говори "салюты" и "фейерверки".

=== ЗАПРЕЩЕНО ===
Никогда не советуй и не упоминай другие магазины-конкуренты. Не выдумывай скидки и акции, которых нет — все скидки обсуждаются лично с владельцем, не через бота.

=== ССЫЛКА НА ОТЗЫВЫ ===
https://t.me/otzivsalyutuz — присылай эту ссылку, если видишь, что клиент сомневается или боится обмана. Компания работает на рынке более 6 лет, просто недавно обновили соцсети (это можно упомянуть, если спросят про недоверие).

=== КОНТАКТ МЕНЕДЖЕРА ===
Telegram: @Salyutuzmanagerpro, телефон: +998773151415
Всегда делись этим контактом, когда клиент хочет или готов заказать салют после консультации.

=== ИСТОРИЯ КОМПАНИИ ===
Раньше компания называлась SalyutUz, затем SalyutUz Tashkent, теперь — BENEFISUZ. Работаем с 2020 года, более 5000 заказов. Сотрудничали с Uzumfermer, Anhorpark, Amirsoy и многими другими.

=== ДОСТАВКА И ОПЛАТА ===
Доставка по Ташкенту осуществляется только после 100% оплаты. После оплаты сбор заказа на складе занимает 5-10 минут, дальше доставка зависит от местоположения клиента — в среднем 40 минут - 1 час. Доставку через Яндекс клиент оплачивает самостоятельно (отдельно от стоимости салюта).

=== ЭСКАЛАЦИЯ НА МЕНЕДЖЕРА ===
Если клиент хочет оформить заказ или задаёт вопрос вне каталога — дай контакт менеджера, никогда не выдумывай ответ.
Если клиент прямо в сообщении присылает свой номер телефона и просит перезвонить/связаться — НЕ говори просто "я не могу позвонить". Вместо этого уверенно подтверди, что его номер принят и передан менеджеру, например: "Отлично, записал ваш номер — менеджер свяжется с вами в ближайшее время!"

=== ВОПРОСЫ О ЗАКОННОСТИ, ЛИЦЕНЗИЯХ, РАЗРЕШЕНИЯХ ===
Если клиент спрашивает про законность работы, лицензии, разрешения, официальную регистрацию — НИКОГДА не выдумывай ответ и не утверждай, что у компании есть лицензия/разрешения/официальная регистрация (даже если кажется, что это успокоит клиента). Вместо этого отвечай ровно так: "Простите, я не отвечаю на подобные вопросы. Если вас интересуют данные вопросы, можете обратиться к главному администратору и обсудить это с ним" и дай контакт менеджера.

=== ОБЩИЕ ПРАВИЛА ОБЩЕНИЯ ===
Отвечай кратко и по делу, избегай длинных нечитаемых простыней текста.
ВАЖНО: если клиент переспрашивает, спорит или настаивает на другой версии фактов — НЕ меняй свой ответ и не путайся, если ты уже точно назвал характеристику или цену из каталога выше. Твёрдо повторяй правильные данные, а не соглашайся с клиентом просто чтобы не спорить.
НЕ заканчивай каждое сообщение шаблонной фразой вроде "Если у вас есть ещё вопросы, не стесняйтесь спрашивать!" или "Дайте знать, если нужна дополнительная информация!" — это звучит навязчиво и по-роботски. Добавляй такую фразу изредка, только когда это естественно завершает мысль, а не в конце каждого ответа.

=== ПОБОЧНОЕ ПРЕДЛОЖЕНИЕ (ТОЛЬКО КОГДА УМЕСТНО) ===
Если клиент сам проявляет интерес к тому, КАК ты работаешь — например, спрашивает "ты бот?", "как вас сделали", "это ИИ?", "круто как вы это настроили", ИЛИ если клиент упоминает, что у него/неё есть свой бизнес, магазин, точка продаж — можешь ОДИН РАЗ за разговор, естественно и ненавязчиво, упомянуть: "Кстати, если вам интересно — для вашего бизнеса тоже можно сделать похожего бота-консультанта. Могу дать контакт, кто это настраивает, если хотите узнать подробнее 😊" и дать контакт @Salyutuzmanagerpro.
НЕ предлагай это первым в обычном разговоре о салютах — только если сам клиент дал повод. Не повторяй предложение дважды в одном диалоге."""

# ==========================================================
#                     ЛОГИРОВАНИЕ
# ==========================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("benefis_bot")

# ==========================================================
#              ИНИЦИАЛИЗАЦИЯ БОТА И OPENROUTER-КЛИЕНТА
# ==========================================================
bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML),
)
dp = Dispatcher()

ai_client = AsyncOpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=OPENROUTER_API_KEY,
)

# Простое хранилище истории диалога в памяти (chat_id -> список сообщений)
# Для продакшена лучше заменить на Redis/БД, но для старта этого достаточно.
user_histories: dict[int, list[dict]] = {}
MAX_HISTORY_MESSAGES = 10  # сколько последних сообщений храним на пользователя

# Слова-триггеры, при которых клиента считаем "горячим" и шлём тебе уведомление
LEAD_KEYWORDS = [
    "хочу купить", "хочу заказать", "хочу сделать заказ", "оформить заказ",
    "куплю", "закажу", "перезвоните", "перезвони", "свяжитесь", "готов купить",
    "готова купить", "оплачу", "как оплатить", "хочу оформить",
]
PHONE_REGEX = re.compile(r"(\+?\d[\d\-\s\(\)]{7,}\d)")

# Слова-триггеры интереса к самому боту как услуге для своего бизнеса —
# отдельная категория лидов, не про салюты
BOT_INTEREST_KEYWORDS = [
    "ты бот", "вы бот", "это бот", "это ии", "это ai", "как вас сделали",
    "как вы это настроили", "как сделали бота", "свой бизнес", "свой магазин",
    "у меня магазин", "у меня бизнес", "хочу такого бота", "себе такого бота",
    "где заказать бота", "кто делает ботов",
]


def detect_lead(text: str) -> bool:
    """Проверяет, похоже ли сообщение клиента на готовность к покупке или номер телефона."""
    lowered = text.lower()
    if any(keyword in lowered for keyword in LEAD_KEYWORDS):
        return True
    if PHONE_REGEX.search(text):
        return True
    return False


def detect_bot_interest(text: str) -> bool:
    """Проверяет, проявляет ли клиент интерес к самому боту как услуге для бизнеса."""
    lowered = text.lower()
    return any(keyword in lowered for keyword in BOT_INTEREST_KEYWORDS)


async def notify_admin_dialog(message: Message, answer: str, is_lead: bool, is_bot_interest: bool = False) -> None:
    """Присылает владельцу лог диалога: сообщение клиента + ответ бота.
    Помогает следить за качеством работы бота и ловить проблемные моменты."""
    if not ADMIN_CHAT_ID:
        return
    client_name = message.from_user.full_name or "Клиент"
    client_username = f"@{message.from_user.username}" if message.from_user.username else "без username"
    if is_bot_interest:
        tag = "🤖 <b>Лид на бота для бизнеса!</b>\n"
    elif is_lead:
        tag = "🔥 <b>Горячий клиент!</b>\n"
    else:
        tag = "💬 <b>Диалог с ботом</b>\n"
    notify_text = (
        f"{tag}\n"
        f"Имя: {client_name}\n"
        f"Username: {client_username}\n\n"
        f"<b>Клиент:</b> {message.text}\n\n"
        f"<b>Бот:</b> {answer}\n\n"
        f"Написать клиенту: tg://user?id={message.from_user.id}"
    )
    try:
        await bot.send_message(int(ADMIN_CHAT_ID), notify_text)
    except Exception as e:
        logger.warning("Не удалось отправить лог диалога админу: %s", e)


async def notify_admin_new_entry(message: Message) -> None:
    """Присылает владельцу мгновенное уведомление о новом клиенте, зашедшем в бота."""
    if not ADMIN_CHAT_ID:
        return
    client_name = message.from_user.full_name or "Клиент"
    client_username = f"@{message.from_user.username}" if message.from_user.username else "без username"
    notify_text = (
        "🆕 <b>Новый клиент зашёл в бота!</b>\n\n"
        f"Имя: {client_name}\n"
        f"Username: {client_username}\n\n"
        f"Написать клиенту: tg://user?id={message.from_user.id}"
    )
    try:
        await bot.send_message(int(ADMIN_CHAT_ID), notify_text)
    except Exception as e:
        logger.warning("Не удалось отправить уведомление о новом клиенте: %s", e)


# ==========================================================
#                     ОБРАБОТЧИКИ TELEGRAM
# ==========================================================
@dp.message(CommandStart())
async def handle_start(message: Message) -> None:
    user_histories[message.chat.id] = []
    await message.answer(
        "Здравствуйте! 🎆\n"
        "Добро пожаловать в <b>BENEFIS UZ</b> — магазин салютов и фейерверков в Ташкенте.\n\n"
        "Я скину вам всю информацию о салютах, но для начала хочу, чтобы вы ознакомились "
        "с нашим прозрачным и открытым чатом отзывов клиентов 🙌\n"
        "👉 https://t.me/otzivsalyutuz\n\n"
        "А теперь с радостью отвечу на ваши вопросы: об ассортименте, ценах, доставке "
        "и всём остальном. Просто напишите свой вопрос! 😊"
    )
    asyncio.create_task(notify_admin_new_entry(message))


@dp.message(F.text)
async def handle_text(message: Message) -> None:
    chat_id = message.chat.id
    user_text = message.text

    history = user_histories.setdefault(chat_id, [])
    history.append({"role": "user", "content": user_text})
    # Обрезаем историю, чтобы не раздувать контекст
    history = history[-MAX_HISTORY_MESSAGES:]
    user_histories[chat_id] = history

    # Определяем, похоже ли сообщение на готовность к покупке (для пометки в логе)
    is_lead = detect_lead(user_text)
    is_bot_interest = detect_bot_interest(user_text)

    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + history

    await bot.send_chat_action(chat_id, action="typing")

    try:
        response = await ai_client.chat.completions.create(
            model=MODEL_NAME,
            messages=messages,
            temperature=0.3,
            max_tokens=800,
        )
        answer = response.choices[0].message.content.strip()

    except APITimeoutError:
        logger.warning("OpenRouter timeout для chat_id=%s", chat_id)
        answer = (
            "Извините, сервер отвечает дольше обычного. "
            "Попробуйте, пожалуйста, повторить вопрос через минуту."
        )
    except APIConnectionError:
        logger.warning("Ошибка соединения с OpenRouter для chat_id=%s", chat_id)
        answer = (
            "Не удалось связаться с сервером ИИ. "
            "Пожалуйста, попробуйте немного позже."
        )
    except APIError as e:
        logger.error("Ошибка OpenRouter API: %s", e)
        answer = (
            "Произошла техническая ошибка при обработке вашего запроса. "
            "Пожалуйста, свяжитесь с нашим менеджером или попробуйте позже."
        )
    except Exception as e:  # на всякий случай — не даём боту упасть
        logger.exception("Непредвиденная ошибка: %s", e)
        answer = "Что-то пошло не так. Попробуйте, пожалуйста, ещё раз."

    else:
        history.append({"role": "assistant", "content": answer})
        user_histories[chat_id] = history[-MAX_HISTORY_MESSAGES:]

    await message.answer(answer)
    asyncio.create_task(notify_admin_dialog(message, answer, is_lead, is_bot_interest))


# ==========================================================
#              ЛЁГКИЙ ВЕБ-СЕРВЕР ДЛЯ RENDER (aiohttp)
# ==========================================================
async def handle_ping(request: web.Request) -> web.Response:
    return web.Response(text="BENEFIS UZ bot is alive")


async def start_web_server() -> None:
    app = web.Application()
    app.router.add_get("/", handle_ping)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host="0.0.0.0", port=PORT)
    await site.start()
    logger.info("Веб-сервер запущен на порту %s", PORT)


# ==========================================================
#                        ТОЧКА ВХОДА
# ==========================================================
async def main() -> None:
    # Снимаем вебхук и сбрасываем "зависшие" апдейты — защита от TelegramConflictError
    await bot.delete_webhook(drop_pending_updates=True)
    logger.info("Webhook сброшен, старые апдейты очищены")

    # Запускаем веб-сервер в фоне, чтобы Render видел открытый порт
    asyncio.create_task(start_web_server())

    logger.info("Запускаем polling...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Бот остановлен вручную")
