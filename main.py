
import asyncio
import logging
import os
 
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
 
# Модель, которую будем использовать через OpenRouter
MODEL_NAME = "openai/gpt-3.5-turbo"
 
# Порт для Render (обязательно из переменной окружения, иначе Render не увидит открытый порт)
PORT = int(os.environ.get("PORT", 10000))
 
SYSTEM_PROMPT = (
    "Ты — вежливый и квалифицированный онлайн-консультант магазина салютов "
    "и пиротехники BENEFIS UZ в Ташкенте."
)
 
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
 
 
# ==========================================================
#                     ОБРАБОТЧИКИ TELEGRAM
# ==========================================================
@dp.message(CommandStart())
async def handle_start(message: Message) -> None:
    user_histories[message.chat.id] = []
    await message.answer(
        "Здравствуйте! 🎆\n"
        "Добро пожаловать в <b>BENEFIS UZ</b> — магазин салютов и пиротехники в Ташкенте.\n\n"
        "Я онлайн-консультант и с радостью отвечу на ваши вопросы: "
        "об ассортименте, ценах, доставке и правилах безопасного использования пиротехники. "
        "Просто напишите свой вопрос!"
    )
 
 
@dp.message(F.text)
async def handle_text(message: Message) -> None:
    chat_id = message.chat.id
    user_text = message.text
 
    history = user_histories.setdefault(chat_id, [])
    history.append({"role": "user", "content": user_text})
    # Обрезаем историю, чтобы не раздувать контекст
    history = history[-MAX_HISTORY_MESSAGES:]
    user_histories[chat_id] = history
 
    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + history
 
    await bot.send_chat_action(chat_id, action="typing")
 
    try:
        response = await ai_client.chat.completions.create(
            model=MODEL_NAME,
            messages=messages,
            temperature=0.7,
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
