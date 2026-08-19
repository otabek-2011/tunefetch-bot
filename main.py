import os
import logging
import asyncio
import requests
import uvicorn
from fastapi import FastAPI
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart
from aiogram.utils.keyboard import InlineKeyboardBuilder
import yt_dlp

logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.getenv("BOT_TOKEN", "")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Render port talab qilgani uchun FastAPI
app = FastAPI()

@app.get("/")
async def root():
    return {"status": "ok"}

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

def search_youtube_ytdlp(query, limit=5):
    ydl_opts = {
        'extract_flat': True,
        'skip_download': True,
        'quiet': True,
        'no_warnings': True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        try:
            info = ydl.extract_info(f"ytsearch{limit}:{query}", download=False)
            results = []
            if info and 'entries' in info:
                for entry in info['entries']:
                    results.append({
                        'id': entry.get('id'),
                        'title': entry.get('title', 'Music Track')
                    })
            return results
        except Exception as e:
            logging.error(f"yt-dlp search error: {e}")
            return []

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
    user_langs[callback.from_user.id] = lang
    await callback.answer(TEXTS[lang]["lang_set"], show_alert=True)
    await callback.message.answer(TEXTS[lang]["welcome"])

@dp.message(F.text)
async def handle_search(message: types.Message):
    user_id = message.from_user.id
    lang = get_user_lang(user_id)
    query = message.text.strip()
    
    msg = await message.answer(TEXTS[lang]["searching"].format(query=query), parse_mode="HTML")
    
    loop = asyncio.get_event_loop()
    results = await loop.run_in_executor(None, search_youtube_ytdlp, query, 5)
    
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
    video_url = f"https://www.youtube.com/watch?v={video_id}"
    title = item.get('title', 'Music')
    
    await callback.message.edit_text(TEXTS[lang]["downloading"])
    os.makedirs("downloads", exist_ok=True)
    file_path = f"downloads/{user_id}_{idx}.mp3"

    loop = asyncio.get_event_loop()

    def download_via_cobalt():
        try:
            payload = {"url": video_url, "downloadMode": "audio", "audioFormat": "mp3"}
            headers = {"Accept": "application/json", "Content-Type": "application/json"}
            res = requests.post("https://api.cobalt.tools/", json=payload, headers=headers, timeout=15)
            if res.status_code == 200 and "url" in res.json():
                audio_res = requests.get(res.json()["url"], stream=True, timeout=30)
                if audio_res.status_code == 200:
                    with open(file_path, 'wb') as f:
                        for chunk in audio_res.iter_content(chunk_size=1024*1024):
                            f.write(chunk)
                    return True
        except Exception as e:
            logging.error(f"Cobalt download failed: {e}")
        return False

    def download_via_ytdlp():
        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': f"downloads/{user_id}_{idx}.%(ext)s",
            'quiet': True,
            'no_warnings': True,
            'nocheckcertificate': True,
            'extractor_args': {'youtube': {'player_client': ['android', 'ios']}}
        }
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([video_url])
            for file in os.listdir("downloads"):
                if file.startswith(f"{user_id}_{idx}"):
                    return os.path.join("downloads", file)
        except Exception as e:
            logging.error(f"YTDLP download failed: {e}")
        return None

    success = await loop.run_in_executor(None, download_via_cobalt)
    downloaded_file = file_path if success else await loop.run_in_executor(None, download_via_ytdlp)

    if downloaded_file and os.path.exists(downloaded_file) and os.path.getsize(downloaded_file) > 1000:
        try:
            audio = types.FSInputFile(downloaded_file)
            await callback.message.answer_audio(audio, caption=f"🎵 <b>{title}</b>", parse_mode="HTML")
            await callback.message.delete()
            os.remove(downloaded_file)
        except Exception as e:
            logging.error(f"Send audio error: {e}")
            await callback.message.edit_text(TEXTS[lang]["error"])
    else:
        await callback.message.edit_text(TEXTS[lang]["error"])

async def start_bot():
    await bot.delete_webhook(drop_pending_updates=True)
    print("\n🚀 BOT ISHGA TUSHDI VA TAYYOR!\n")
    await dp.start_polling(bot)

async def main():
    port = int(os.getenv("PORT", 10000))
    config = uvicorn.Config(app, host="0.0.0.0", port=port, log_level="warning")
    server = uvicorn.Server(config)
    
    await asyncio.gather(
        server.serve(),
        start_bot()
    )

if __name__ == "__main__":
    asyncio.run(main())