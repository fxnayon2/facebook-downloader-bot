import os
import json
import time
import logging
import subprocess
from datetime import datetime, timezone
from telegram import Update, BotCommand
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
from keep_alive import keep_alive
from downloader import download_facebook_video, split_video

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

BOT_NAME = "YourBotUsername"
MAX_SIZE_BYTES = 50 * 1024 * 1024
FACEBOOK_DOMAINS = ("facebook.com", "fb.watch", "fb.com", "m.facebook.com", "www.facebook.com")
STATS_FILE = "/tmp/bot_stats.json"
START_TIME = time.time()


def load_stats() -> dict:
    try:
        with open(STATS_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {
            "total_downloads": 0,
            "failed_downloads": 0,
            "total_size_bytes": 0,
            "recent_downloads": [],
            "start_time": START_TIME,
        }


def save_stats(stats: dict):
    try:
        with open(STATS_FILE, "w") as f:
            json.dump(stats, f)
    except Exception as e:
        logger.error(f"Failed to save stats: {e}")


def record_download(success: bool, size_bytes: int = 0, url: str = "", caption: str = ""):
    stats = load_stats()
    if success:
        stats["total_downloads"] = stats.get("total_downloads", 0) + 1
        stats["total_size_bytes"] = stats.get("total_size_bytes", 0) + size_bytes
        entry = {
            "url": url[:100],
            "caption": (caption[:80] + "...") if len(caption) > 80 else caption,
            "size_bytes": size_bytes,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "status": "success",
        }
    else:
        stats["failed_downloads"] = stats.get("failed_downloads", 0) + 1
        entry = {
            "url": url[:100],
            "caption": "",
            "size_bytes": 0,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "status": "failed",
        }
    recent = stats.get("recent_downloads", [])
    recent.insert(0, entry)
    stats["recent_downloads"] = recent[:20]
    if "start_time" not in stats:
        stats["start_time"] = START_TIME
    save_stats(stats)


def is_facebook_url(text: str) -> bool:
    return any(domain in text for domain in FACEBOOK_DOMAINS)


def build_caption(original: str) -> str:
    caption = original.strip() if original else ""
    if len(caption) > 4096:
        caption = caption[:4096]
    return caption


def format_uptime(seconds: float) -> str:
    seconds = int(seconds)
    d, rem = divmod(seconds, 86400)
    h, rem = divmod(rem, 3600)
    m, s = divmod(rem, 60)
    parts = []
    if d: parts.append(f"{d}d")
    if h: parts.append(f"{h}h")
    if m: parts.append(f"{m}m")
    parts.append(f"{s}s")
    return " ".join(parts)


def format_size(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 ** 2:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 ** 3:
        return f"{size_bytes / (1024 ** 2):.1f} MB"
    return f"{size_bytes / (1024 ** 3):.2f} GB"


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Facebook Video Downloader Bot\n\n"
        "Just send me any Facebook video link and I will download it for you.\n\n"
        "Commands:\n"
        "/start - Show this message\n"
        "/help - How to use the bot\n"
        "/status - Bot status and stats\n"
        "/about - About this bot\n\n"
        "Supported links:\n"
        "- facebook.com/...\n"
        "- fb.watch/...\n"
        "- m.facebook.com/...\n\n"
        "Max video size: 50 MB"
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "How to use:\n\n"
        "1. Copy any Facebook video link\n"
        "2. Paste it here and send\n"
        "3. Wait - the bot will download and send the video\n"
        "4. The original caption comes as a separate message\n\n"
        "Limits:\n"
        "- Max file size: 50 MB\n"
        "- Private/restricted videos may not work"
    )


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    stats = load_stats()
    uptime = time.time() - stats.get("start_time", START_TIME)
    total = stats.get("total_downloads", 0)
    failed = stats.get("failed_downloads", 0)
    size = stats.get("total_size_bytes", 0)
    success_rate = round((total / (total + failed)) * 100) if (total + failed) > 0 else 100
    await update.message.reply_text(
        f"Bot Status\n\nStatus: Online\nUptime: {format_uptime(uptime)}\n\n"
        f"Downloads\nTotal: {total}\nFailed: {failed}\n"
        f"Success Rate: {success_rate}%\nData Sent: {format_size(size)}"
    )


async def cmd_about(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"About This Bot\n\nName: @{BOT_NAME}\n"
        "Purpose: Download Facebook videos directly in Telegram\n\n"
        "Built with:\n- python-telegram-bot\n- yt-dlp\n- ffmpeg"
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text or ""
    if not is_facebook_url(text):
        await update.message.reply_text("Please send a valid Facebook video link.\nUse /help to see supported formats.")
        return

    status_msg = await update.message.reply_text("Downloading video, please wait...")
    filepath = None
    try:
        filepath, original_caption = download_facebook_video(text)
        if not filepath or not os.path.exists(filepath):
            await status_msg.edit_text("Failed to download the video. Please check the link and try again.")
            record_download(success=False, url=text)
            return

        file_size = os.path.getsize(filepath)
        caption = build_caption(original_caption or "")

        if file_size > MAX_SIZE_BYTES:
            await status_msg.edit_text(f"Video is {format_size(file_size)} - splitting into parts, please wait...")
            parts = split_video(filepath)
            if len(parts) > 1 or (parts and parts[0] != filepath):
                if os.path.exists(filepath):
                    os.remove(filepath)
                    filepath = None
            total_parts = len(parts)
            total_sent_bytes = 0
            for i, part_path in enumerate(parts):
                part_num = i + 1
                part_size = os.path.getsize(part_path) if os.path.exists(part_path) else 0
                if part_size > MAX_SIZE_BYTES:
                    await update.message.reply_text(f"Part {part_num}/{total_parts} is too large. Skipping.")
                    os.remove(part_path)
                    continue
                await status_msg.edit_text(f"Sending part {part_num}/{total_parts}...")
                try:
                    with open(part_path, "rb") as vf:
                        await update.message.reply_video(video=vf, caption=f"Part {part_num} / {total_parts}", supports_streaming=True, read_timeout=180, write_timeout=180)
                    total_sent_bytes += part_size
                finally:
                    if os.path.exists(part_path):
                        os.remove(part_path)
            await status_msg.delete()
            if caption:
                await update.message.reply_text(caption)
            record_download(success=True, size_bytes=total_sent_bytes, url=text, caption=original_caption or "")
        else:
            await status_msg.edit_text("Sending video...")
            with open(filepath, "rb") as video_file:
                await update.message.reply_video(video=video_file, supports_streaming=True, read_timeout=120, write_timeout=120)
            await status_msg.delete()
            if caption:
                await update.message.reply_text(caption)
            record_download(success=True, size_bytes=file_size, url=text, caption=original_caption or "")
    except RuntimeError as e:
        await status_msg.edit_text(f"Error: {e}")
        record_download(success=False, url=text)
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        await status_msg.edit_text("An unexpected error occurred. Please try again.")
        record_download(success=False, url=text)
    finally:
        if filepath and os.path.exists(filepath):
            os.remove(filepath)


async def post_init(application):
    await application.bot.set_my_commands([
        BotCommand("start", "Show welcome message"),
        BotCommand("help", "How to use the bot"),
        BotCommand("status", "Bot status and download stats"),
        BotCommand("about", "About this bot"),
    ])


def update_ytdlp():
    try:
        subprocess.run(["pip", "install", "-q", "--upgrade", "yt-dlp"], capture_output=True, text=True, timeout=60)
        logger.info("yt-dlp updated successfully")
    except Exception as e:
        logger.warning(f"yt-dlp update skipped: {e}")


def main():
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN environment variable is not set.")
    update_ytdlp()
    stats = load_stats()
    stats["start_time"] = START_TIME
    save_stats(stats)
    keep_alive()
    app = ApplicationBuilder().token(token).post_init(post_init).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("about", cmd_about))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    logger.info("Bot is starting...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
