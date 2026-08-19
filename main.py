import os
import logging
import asyncio
import requests
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart
from aiogram.utils.keyboard import InlineKeyboardBuilder
from youtubesearchpython import VideosSearch
import uvicorn

logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
WEBHOOK_PATH = f"/webhook/{BOT_TOKEN}"
WEBHOOK_URL = f"https://tunefetch-bot-1.onrender.com{WEBHOOK_PATH}"

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

user_langs = {}
user_search_results = {}

TEXTS = {
    "uz": {
        "welcome": "Salom! Musiqa nomini yoki YouTube havolasini yuboring.",
        "searching": "🔍 <b>{query}</b> qidirilmoqda...",
        "select": "Yuklab olish uchun ro'yxatdan birini tanlang:",
        "downloading": "🎵 Yuklanmoqda...",
        "not_found": "Afsuski, hech narsa topilmadi.",
        "error": "Xatolik yuz berdi. Qayta urinib ko'ring.",
        "lang_set": "O'zbek tili tanlandi!"
    },
    "ru": {
        "welcome": "Привет! Отправьте название песни или ссылку на YouTube.",
        "searching": "🔍 Ищем <b>{query}</b>...",
        "select": "Выберите трек для скачивания:",
        "downloading": "🎵 Скачиваем музыку, подождите...",
        "not_found": "К сожалению, ничего не найдено.",
        "error": "Произошла ошибка. Попробуйте еще раз.",
        "lang_set": "Язык успешно изменен!"
    },
    "en": {
        "welcome": "Hello! Send song name or YouTube link.",
        "searching": "🔍 Searching <b>{query}</b>...",
        "select": "Choose a track to download:",
        "downloading": "🎵 Downloading music, please wait...",
        "not_found": "Unfortunately, nothing found.",
        "error": "An error occurred. Try again.",
        "lang_set": "Language successfully changed!"
    }
}

def get_user_lang(user_id):
    return user_langs.get(user_id, "uz")

@dp.message(CommandStart())
async def start_cmd(message: types.Message):
    kb = InlineKeyboardBuilder()
    kb.button(text="🇺🇿 O'zbekcha", callback_data="lang_uz")
    kb.button(text="🇷🇺 Русский", callback_data="lang_ru")
    kb.button(text="🇬🇧 English", callback_data="lang_en")
    kb.adjust(3)
    
    await message.answer("🌐 Tilni tanlang / Select language / Выберите язык:", reply_markup=kb.as_markup())

@dp.callback_query(F.data.startswith("lang_"))
async def set_lang(callback: types.CallbackQuery):
    lang = callback.data.split("_")[1]
    user_id = callback.from_user.id
    user_langs[user_id] = lang
    
    await callback.answer(TEXTS[lang]["lang_set"], show_alert=True)
    await callback.message.answer(TEXTS[lang]["welcome"])

@dp.message(F.text)
async def handle_search(message: types.Message):
    user_id = message.from_user.id
    lang = get_user_lang(user_id)
    query = message.text.strip()
    
    msg = await message.answer(TEXTS[lang]["searching"].format(query=query), parse_mode="HTML")
    
    try:
        loop = asyncio.get_event_loop()
        search = await loop.run_in_executor(None, lambda: VideosSearch(query, limit=5).result())
        results = search.get('result', [])
        
        if not results:
            await msg.edit_text(TEXTS[lang]["not_found"])
            return
            
        user_search_results[user_id] = results
        kb = InlineKeyboardBuilder()
        
        for idx, item in enumerate(results):
            title = item.get('title', f"Track {idx+1}")[:30]
            kb.button(text=f"🎵 {title}", callback_data=f"dl_{idx}")
            
        kb.adjust(1)
        await msg.edit_text(TEXTS[lang]["select"], reply_markup=kb.as_markup())
        
    except Exception as e:
        logging.error(f"Search error: {e}")
        await msg.edit_text(TEXTS[lang]["error"])

@dp.callback_query(F.data.startswith("dl_"))
async def download_music(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    lang = get_user_lang(user_id)
    idx = int(callback.data.split("_")[1])
    
    results = user_search_results.get(user_id, [])
    if not results or idx >= len(results):
        await callback.answer(TEXTS[lang]["error"], show_alert=True)
        return
        
    item = results[idx]
    video_id = item.get('id')
    title = item.get('title', 'Music')
    
    await callback.message.edit_text(TEXTS[lang]["downloading"])
    os.makedirs("downloads", exist_ok=True)
    file_path = f"downloads/{user_id}_{idx}.mp3"

    try:
        audio_url = f"https://invidious.nerdvpn.de/latest_version?id={video_id}&italic=0&quality=local"
        
        loop = asyncio.get_event_loop()
        def download_file():
            r = requests.get(audio_url, stream=True, timeout=30)
            if r.status_code == 200:
                with open(file_path, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=1024*1024):
                        f.write(chunk)
                return True
            return False

        success = await loop.run_in_executor(None, download_file)

        if success and os.path.exists(file_path) and os.path.getsize(file_path) > 1000:
            audio = types.FSInputFile(file_path)
            await callback.message.answer_audio(audio, caption=f"🎵 <b>{title}</b>", parse_mode="HTML")
            await callback.message.delete()
            os.remove(file_path)
        else:
            await callback.message.edit_text(TEXTS[lang]["error"])

    except Exception as e:
        logging.error(f"Download error: {e}")
        await callback.message.edit_text(TEXTS[lang]["error"])

@asynccontextmanager
async def lifespan(app: FastAPI):
    await bot.set_webhook(url=WEBHOOK_URL, drop_pending_updates=True)
    yield
    await bot.delete_webhook()

app = FastAPI(lifespan=lifespan)

@app.post(WEBHOOK_PATH)
async def bot_webhook(request: Request):
    update = types.Update.model_validate(await request.json(), context={"bot": bot})
    await dp.feed_update(bot, update)
    return {"status": "ok"}

@app.get("/")
async def root():
    return {"status": "bot is running"}

if __name__ == "__main__":
    port = int(os.getenv("PORT", 10000))
    uvicorn.run(app, host="0.0.0.0", port=port)