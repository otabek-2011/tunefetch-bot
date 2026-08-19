import os
import logging
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart
from aiogram.utils.keyboard import InlineKeyboardBuilder
import asyncio
import yt_dlp

logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.getenv("BOT_TOKEN", "")

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
    
    os.makedirs("downloads", exist_ok=True)
    
    ydl_opts = {
        'format': 'm4a/bestaudio/best',
        'outtmpl': f"downloads/{user_id}_{idx}.%(ext)s",
        'quiet': True,
        'no_warnings': True,
        'nocheckcertificate': True,
        'source_address': '0.0.0.0',
    }
    
    try:
        loop = asyncio.get_event_loop()
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            await loop.run_in_executor(None, lambda: ydl.download([video_url]))
            
        downloaded_file = None
        for file in os.listdir("downloads"):
            if file.startswith(f"{user_id}_{idx}"):
                downloaded_file = os.path.join("downloads", file)
                break

        if downloaded_file:
            audio = types.FSInputFile(downloaded_file)
            await callback.message.answer_audio(audio, caption=f"🎵 <b>{title}</b>", parse_mode="HTML")
            await callback.message.delete()
            if os.path.exists(downloaded_file):
                os.remove(downloaded_file)
        else:
            await callback.message.edit_text(TEXTS[lang]["error"])

    except Exception as e:
        logging.error(f"Download error: {e}")
        await callback.message.edit_text(TEXTS[lang]["error"])

async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())