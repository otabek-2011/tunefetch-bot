import os
import asyncio
import logging
import requests
from fastapi import FastAPI
import uvicorn
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

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

INVIDIOUS_INSTANCES = [
    "https://invidious.nerdvpn.de",
    "https://inv.us.projectsegfau.lt",
    "https://invidious.flokinet.to",
    "https://invidious.privacydev.net"
]

@app.get("/")
async def root():
    return {"status": "ok"}

@app.get("/health")
async def health():
    return {"status": "healthy"}

def search_music(query):
    results = []
    for instance in INVIDIOUS_INSTANCES:
        try:
            url = f"{instance}/api/v1/search?q={requests.utils.quote(query)}&type=video"
            resp = requests.get(url, timeout=4)
            if resp.status_code == 200:
                data = resp.json()
                for item in data[:5]:
                    results.append({
                        'id': item.get('videoId'),
                        'title': item.get('title'),
                        'duration': item.get('lengthSeconds')
                    })
                if results:
                    break
        except Exception as e:
            logging.warning(f"Failed instance {instance}: {e}")
            continue
    return results

def download_audio_file(video_id, output_path):
    for instance in INVIDIOUS_INSTANCES:
        try:
            url = f"{instance}/api/v1/videos/{video_id}"
            resp = requests.get(url, timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                adaptive_formats = data.get('adaptiveFormats', [])
                audio_streams = [f for f in adaptive_formats if f.get('type', '').startswith('audio/')]
                
                if audio_streams:
                    # Eng sifatli audio havola
                    audio_url = audio_streams[0].get('url')
                    r = requests.get(audio_url, stream=True, timeout=20)
                    if r.status_code == 200:
                        with open(output_path, 'wb') as f:
                            for chunk in r.iter_content(chunk_size=1024 * 64):
                                f.write(chunk)
                        return True
        except Exception as e:
            logging.warning(f"Download fail on {instance}: {e}")
            continue
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
    video_id = item['id']
    title = item.get('title', 'music')
    file_path = f"music_{callback.from_user.id}.mp3"

    await callback.message.edit_text(TEXTS[lang]['downloading'])

    success = download_audio_file(video_id, file_path)

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