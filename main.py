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
        "downloading": "📥 Yuklanmoqda...",
        "not_found": "Afsuski, hech narsa topilmadi.",
        "error": "Xatolik yuz berdi. Qayta urinib ko'ring.",
        "lang_set": "Uzbek tili tanlandi!"
    },
    "ru": {
        "welcome": "Привет! Отправьте название песни или ссылку на YouTube.",
        "searching": "🔍 Ищем <b>{query}</b>...",
        "select": "Выберите трек для скачивания:",
        "downloading": "📥 Скачиваем музыку, подождите...",
        "not_found": "К сожалению, ничего не найдено.",
        "error": "Произошла ошибка. Попробуйте еще раз.",
        "lang_set": "Язык успешно изменен!"
    },
    "en": {
        "welcome": "Hello! Send song name or YouTube link.",
        "searching": "🔍 Searching <b>{query}</b>...",
        "select": "Choose a track to download:",
        "downloading": "📥 Downloading music, please wait...",
        "not_found": "Unfortunately, nothing found.",
        "error": "An error occurred. Try again.",
        "lang_set": "Language successfully changed!"
    }
}

def get_user_lang(user_id):
    return user_langs.get(user_id, "uz")

@dp.message(CommandStart())
async def start(message: types.Message):
    user_id = message.from_user.id
    builder = InlineKeyboardBuilder()
    builder.button(text="🇺🇿 O'zbekcha", callback_data="setlang_uz")
    builder.button(text="🇷🇺 Русский", callback_data="setlang_ru")
    builder.button(text="🇬🇧 English", callback_data="setlang_en")
    
    await message.answer("Tilni tanlang / Choose language / Выберите язык:", reply_markup=builder.as_markup())

@dp.callback_query(F.data.startswith("setlang_"))
async def set_language_callback(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    lang = callback.data.split("_")[1]
    user_langs[user_id] = lang
    await callback.message.answer(TEXTS[lang]["lang_set"])
    await callback.message.answer(TEXTS[lang]["welcome"])
    await callback.answer()

@dp.message(F.text)
async def search_music(message: types.Message):
    user_id = message.from_user.id
    lang = get_user_lang(user_id)
    query = message.text.strip()

    status_msg = await message.answer(TEXTS[lang]["searching"].format(query=query), parse_mode="HTML")

    search_query = query if query.startswith("http") else f"ytsearch5:{query}"

    ydl_opts = {
        'format': 'bestaudio/best',
        'noplaylist': True,
        'quiet': True,
        'no_warnings': True,
        'nocheckcertificate': True,
        'cookiefile': 'cookies.txt' if os.path.exists('cookies.txt') else None,
        'source_address': '0.0.0.0',
        'extractor_args': {
            'youtube': {
                'player_client': ['android', 'web']
            }
        }
    }

    loop = asyncio.get_event_loop()

    def search():
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            return ydl.extract_info(search_query, download=False)

    try:
        info = await loop.run_in_executor(None, search)

        if not info or 'entries' not in info or not info['entries']:
            await status_msg.edit_text(TEXTS[lang]["not_found"])
            return

        valid_entries = [e for e in info['entries'] if e]
        user_search_results[user_id] = valid_entries

        builder = InlineKeyboardBuilder()

        for idx, entry in enumerate(valid_entries):
            title = entry.get('title', 'Music')[:30]
            duration = entry.get('duration', 0)
            dur_str = f"{duration // 60}:{duration % 60:02d}" if duration else ""
            btn_text = f"{idx + 1}. {title} [{dur_str}]"
            builder.button(text=btn_text, callback_data=f"dl_{idx}")

        builder.adjust(1)
        await status_msg.edit_text(TEXTS[lang]["select"], reply_markup=builder.as_markup())

    except Exception as e:
        print(f"Search error: {e}")
        await status_msg.edit_text(TEXTS[lang]["error"])

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

    loop = asyncio.get_event_loop()

    def download():
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([video_url])

    try:
        await loop.run_in_executor(None, download)

        if os.path.exists(file_path):
            audio_file = types.FSInputFile(file_path, filename=f"{title}.mp3")
            await callback.message.answer_audio(audio=audio_file, caption=f"🎧 <b>{title}</b> | @TuneFetchBot", parse_mode="HTML")
            await callback.message.delete()
        else:
            await callback.message.edit_text(TEXTS[lang]["error"])

    except Exception as e:
        print(f"Download error: {e}")
        await callback.message.edit_text(TEXTS[lang]["error"])

    finally:
        if os.path.exists(file_path):
            os.remove(file_path)

@app.post(WEBHOOK_PATH)
async def bot_webhook(request: Request):
    update_data = await request.json()
    update = types.Update(**update_data)
    await dp.feed_update(bot, update)
    return {"status": "ok"}

@app.get("/")
async def health_check():
    return {"status": "bot is running"}

@app.on_event("startup")
async def on_startup():
    if WEBHOOK_URL:
        await bot.set_webhook(WEBHOOK_URL)
        print(f"Webhook o'rnatildi: {WEBHOOK_URL}")

@app.on_event("shutdown")
async def on_shutdown():
    await bot.delete_webhook()

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 10000))
    uvicorn.run(app, host="0.0.0.0", port=port)