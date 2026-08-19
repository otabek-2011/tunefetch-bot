import os
import logging
from fastapi import FastAPI, Request
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart
from aiogram.utils.keyboard import InlineKeyboardBuilder
import asyncio
import yt_dlp

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
WEBHOOK_PATH = f"/webhook/{BOT_TOKEN}"
RENDER_HOSTNAME = os.getenv("RENDER_EXTERNAL_HOSTNAME", "")
WEBHOOK_URL = f"https://tunefetch-bot-1.onrender.com{WEBHOOK_PATH}"

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
app = FastAPI()

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
    
    lang = get_user_lang(message.from_user.id)
    await message.answer(TEXTS[lang]["welcome"], reply_markup=kb.as_markup())

@dp.callback_query(F.data.startswith("lang_"))
async def set_lang(callback: types.CallbackQuery):
    lang = callback.data.split("_")[1]
    user_langs[callback.from_user.id] = lang
    await callback.answer(TEXTS[lang]["lang_set"], show_alert=True)

@dp.message(F.text)
async def handle_search(message: types.Message):
    user_id = message.from_user.id
    lang = get_user_lang(user_id)
    query = message.text.strip()
    
    msg = await message.answer(TEXTS[lang]["searching"].format(query=query), parse_mode="HTML")
    
    ydl_opts = {
        'format': 'bestaudio/best',
        'quiet': True,
        'no_warnings': True,
        'extract_flat': True,
        'cookiefile': 'cookies.txt' if os.path.exists('cookies.txt') else None
    }
    
    try:
        loop = asyncio.get_event_loop()
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            if "youtube.com" in query or "youtu.be" in query:
                info = await loop.run_in_executor(None, lambda: ydl.extract_info(query, download=False))
                entries = [info] if 'entries' not in info else info['entries']
            else:
                info = await loop.run_in_executor(None, lambda: ydl.extract_info(f"ytsearch5:{query}", download=False))
                entries = info.get('entries', [])
                
        if not entries:
            await msg.edit_text(TEXTS[lang]["not_found"])
            return
            
        user_search_results[user_id] = entries
        kb = InlineKeyboardBuilder()
        
        for idx, item in enumerate(entries[:5]):
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
    video_url = item.get('webpage_url') or f"https://www.youtube.com/watch?v={item.get('id')}"
    title = item.get('title', 'Music')
    
    await callback.message.edit_text(TEXTS[lang]["downloading"])
    
    file_path = f"downloads/{user_id}_{idx}.mp3"
    os.makedirs("downloads", exist_ok=True)
    
    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': f"downloads/{user_id}_{idx}.%(ext)s",
        'quiet': True,
        'no_warnings': True,
        'nocheckcertificate': True,
        'cookiefile': 'cookies.txt' if os.path.exists('cookies.txt') else None,
        'source_address': '0.0.0.0',
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }],
        'extractor_args': {
            'youtube': {
                'player_client': ['android', 'web']
            }
        }
    }
    
    try:
        loop = asyncio.get_event_loop()
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            await loop.run_in_executor(None, lambda: ydl.download([video_url]))
            
        audio = types.FSInputFile(file_path)
        await callback.message.answer_audio(audio, caption=f"🎵 <b>{title}</b>", parse_mode="HTML")
        await callback.message.delete()
        
        if os.path.exists(file_path):
            os.remove(file_path)
    except Exception as e:
        logging.error(f"Download error: {e}")
        await callback.message.edit_text(TEXTS[lang]["error"])

@app.on_event("startup")
async def on_startup():
    await bot.set_webhook(url=WEBHOOK_URL, drop_pending_updates=True)

@app.on_event("shutdown")
async def on_shutdown():
    await bot.delete_webhook()

@app.post(WEBHOOK_PATH)
async def bot_webhook(request: Request):
    update = types.Update.model_validate(await request.json(), context={"bot": bot})
    await dp.feed_update(bot, update)
    return {"status": "ok"}

@app.get("/")
async def root():
    return {"status": "bot is running"}