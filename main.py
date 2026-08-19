import os
import asyncio
import logging
import requests
from fastapi import FastAPI
import uvicorn
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
import yt_dlp

logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.getenv("BOT_TOKEN")
PORT = int(os.getenv("PORT", 8080))

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
app = FastAPI()

user_languages = {}

TEXTS = {
    'uz': {
        'start': "Salom! Musiqa nomini yoki YouTube havolasini yuboring.",
        'searching': "🔍 Qidirilmoqda...",
        'not_found': "❌ Hech narsa topilmadi.",
        'select_song': "Musiqani tanlang:",
        'downloading': "⏳ Yuklanmoqda...",
        'error': "Xatolik yuz berdi. Qayta urinib ko'ring."
    },
    'ru': {
        'start': "Привет! Отправьте название музыки или ссылку на YouTube.",
        'searching': "🔍 Поиск...",
        'not_found': "❌ Ничего не найдено.",
        'select_song': "Выберите музыку:",
        'downloading': "⏳ Скачивается...",
        'error': "Произошла ошибка. Попробуйте еще раз."
    },
    'en': {
        'start': "Hello! Send the music name or YouTube link.",
        'searching': "🔍 Searching...",
        'not_found': "❌ Nothing found.",
        'select_song': "Select music:",
        'downloading': "⏳ Downloading...",
        'error': "An error occurred. Try again."
    }
}

@app.get("/")
async def root():
    return {"status": "ok"}

@app.get("/health")
async def health():
    return {"status": "healthy"}

YDL_OPTIONS = {
    'format': 'bestaudio/best',
    'noplaylist': True,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'scsearch5',
    'source_address': '0.0.0.0'
}

def search_music(query):
    results = []
    # SoundCloud qidiruvi
    try:
        with yt_dlp.YoutubeDL(YDL_OPTIONS) as ydl:
            info = ydl.extract_info(f"scsearch5:{query}", download=False)
            if 'entries' in info and info['entries']:
                for entry in info['entries']:
                    if entry:
                        results.append({
                            'id': entry.get('url') or entry.get('webpage_url'),
                            'title': entry.get('title'),
                            'duration': entry.get('duration')
                        })
    except Exception as e:
        logging.error(f"SoundCloud error: {e}")

    # Fallback (Piped API)
    if not results:
        try:
            resp = requests.get(f"https://pipedapi.kavin.rocks/search?q={query}&filter=music_songs", timeout=5)
            if resp.status_code == 200:
                data = resp.json().get('items', [])
                for item in data[:5]:
                    results.append({
                        'id': f"https://www.youtube.com/watch?v={item.get('url').split('=')[-1]}",
                        'title': item.get('title'),
                        'duration': item.get('duration')
                    })
        except Exception as e:
            logging.error(f"Fallback error: {e}")

    return results

def download_audio_file(url, title, output_path):
    # 1. yt-dlp orqali yuklashga urinish
    try:
        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': output_path,
            'quiet': True,
            'no_warnings': True,
            'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36',
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
        if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
            return True
    except Exception as e:
        logging.warning(f"yt-dlp download failed (DRM or block), trying fallback stream: {e}")

    # 2. DRM xatosi bo'lsa, ochiq Stream API orqali ko'chirish
    try:
        clean_title = title.replace(" ", "+")
        stream_url = f"https://api.vagalume.com.br/search.php" # zaxira ochiq oqim uchun
        resp = requests.get(f"https://yt-stream-api.vercel.app/api/dl?query={clean_title}", timeout=10)
        if resp.status_code == 200 and resp.json().get("url"):
            audio_url = resp.json().get("url")
            r = requests.get(audio_url, stream=True, timeout=15)
            with open(output_path, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)
            return True
    except Exception as fallback_err:
        logging.error(f"Fallback stream error: {fallback_err}")

    return False

@dp.message(Command("start"))
async def start_cmd(message: types.Message):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🇺🇿 O'zbekcha", callback_data="lang_uz"),
            InlineKeyboardButton(text="🇷🇺 Русский", callback_data="lang_ru"),
            InlineKeyboardButton(text="🇬🇧 English", callback_data="lang_en")
        ]
    ])
    await message.answer("🌐 Tilni tanlang / Select language / Выберите язык:", reply_markup=keyboard)

@dp.callback_query(F.data.startswith("lang_"))
async def set_language(callback: types.CallbackQuery):
    lang = callback.data.split("_")[1]
    user_languages[callback.from_user.id] = lang
    await callback.message.delete()
    await callback.message.answer(TEXTS[lang]['start'])

@dp.message(F.text & ~F.text.startswith("/"))
async def handle_text(message: types.Message):
    lang = user_languages.get(message.from_user.id, 'uz')
    query = message.text
    status_msg = await message.answer(TEXTS[lang]['searching'])

    results = search_music(query)

    if not results:
        await status_msg.edit_text(TEXTS[lang]['not_found'])
        return

    keyboard = []
    for idx, item in enumerate(results):
        title = item['title'][:35] if item.get('title') else "Music"
        keyboard.append([InlineKeyboardButton(text=f"🎵 {title}", callback_data=f"dl_{idx}")])

    dp['search_cache_' + str(message.from_user.id)] = results

    markup = InlineKeyboardMarkup(inline_keyboard=keyboard)
    await status_msg.edit_text(TEXTS[lang]['select_song'], reply_markup=markup)

@dp.callback_query(F.data.startswith("dl_"))
async def handle_download(callback: types.CallbackQuery):
    lang = user_languages.get(callback.from_user.id, 'uz')
    idx = int(callback.data.split("_")[1])
    cache_key = 'search_cache_' + str(callback.from_user.id)
    results = dp.get(cache_key, [])

    if not results or idx >= len(results):
        await callback.message.edit_text(TEXTS[lang]['error'])
        return

    item = results[idx]
    url = item['id']
    title = item.get('title', 'music')
    file_path = f"music_{callback.from_user.id}.mp3"

    await callback.message.edit_text(TEXTS[lang]['downloading'])

    success = download_audio_file(url, title, file_path)

    if success and os.path.exists(file_path):
        try:
            audio_file = types.FSInputFile(file_path)
            await callback.message.answer_audio(audio=audio_file, title=title)
            await callback.message.delete()
        except Exception as e:
            logging.error(f"Send audio error: {e}")
            await callback.message.edit_text(TEXTS[lang]['error'])
    else:
        await callback.message.edit_text(TEXTS[lang]['error'])

    if os.path.exists(file_path):
        os.remove(file_path)

async def start_bot():
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

async def main():
    config = uvicorn.Config(app=app, host="0.0.0.0", port=PORT, log_level="info")
    server = uvicorn.Server(config)

    await asyncio.gather(
        server.serve(),
        start_bot()
    )

if __name__ == "__main__":
    asyncio.run(main())