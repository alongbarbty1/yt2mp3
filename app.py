import os
import logging
import asyncio
import tempfile
import shutil
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv

# Bot dependencies
from telegram import Update, InputFile
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    ConversationHandler,
)
from telegram.constants import ParseMode

# YouTube download dependencies
import yt_dlp
import re

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Bot configuration
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
ALLOWED_USER_IDS = os.getenv("ALLOWED_USER_IDS", "").split(",")
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB Telegram limit
COOKIES_FILE = "cookies.txt" if os.path.exists("cookies.txt") else None

# Conversation states
CHOOSING, DOWNLOADING = range(2)

class YouTubeMusicDownloader:
    def __init__(self):
        self.ydl_opts = {
            'format': 'bestaudio/best',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
            'outtmpl': '%(title)s.%(ext)s',
            'quiet': True,
            'no_warnings': True,
            'extract_flat': False,
            'noplaylist': True,
            'nocheckcertificate': True,
            'ignoreerrors': False,
            'logtostderr': False,
            'source_address': '0.0.0.0',
        }
        
        # Add cookies if available
        if COOKIES_FILE:
            self.ydl_opts['cookiefile'] = COOKIES_FILE
            
        # For video info extraction
        self.info_opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': True,
        }
        if COOKIES_FILE:
            self.info_opts['cookiefile'] = COOKIES_FILE
    
    def extract_video_info(self, url):
        """Extract video information without downloading"""
        try:
            with yt_dlp.YoutubeDL(self.info_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                return {
                    'title': info.get('title', 'Unknown Title'),
                    'duration': info.get('duration', 0),
                    'uploader': info.get('uploader', 'Unknown Artist'),
                    'thumbnail': info.get('thumbnail', ''),
                    'webpage_url': info.get('webpage_url', url),
                    'duration_string': info.get('duration_string', '0:00'),
                }
        except Exception as e:
            logger.error(f"Error extracting video info: {e}")
            return None
    
    async def download_audio(self, url, chat_id):
        """Download audio from YouTube URL"""
        temp_dir = tempfile.mkdtemp()
        output_path = None
        
        try:
            # Update output template for temp directory
            opts = self.ydl_opts.copy()
            opts['outtmpl'] = os.path.join(temp_dir, '%(title)s.%(ext)s')
            
            # Download the audio
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)
                
                # Find the downloaded file
                downloaded_files = list(Path(temp_dir).glob("*.mp3"))
                if downloaded_files:
                    output_path = downloaded_files[0]
                    
                    # Check file size
                    file_size = output_path.stat().st_size
                    if file_size > MAX_FILE_SIZE:
                        # Try to compress to lower quality
                        return await self.download_lower_quality(url, temp_dir, chat_id)
                    
                    return output_path
                
        except Exception as e:
            logger.error(f"Error downloading audio: {e}")
            if "Sign in to confirm your age" in str(e):
                return "age_restricted"
            return None
        finally:
            # Cleanup other files in temp directory
            if output_path:
                # Keep only the output file, delete others
                for file in Path(temp_dir).glob("*"):
                    if file != output_path:
                        try:
                            if file.is_file():
                                file.unlink()
                        except:
                            pass
            # Temp directory will be cleaned up by caller
        return None
    
    async def download_lower_quality(self, url, temp_dir, chat_id):
        """Download with lower quality to reduce file size"""
        try:
            opts = self.ydl_opts.copy()
            opts['postprocessors'][0]['preferredquality'] = '128'
            opts['outtmpl'] = os.path.join(temp_dir, 'compressed_%(title)s.%(ext)s')
            
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)
                
                downloaded_files = list(Path(temp_dir).glob("*.mp3"))
                if downloaded_files:
                    output_path = downloaded_files[0]
                    file_size = output_path.stat().st_size
                    
                    if file_size > MAX_FILE_SIZE:
                        return "file_too_large"
                    return output_path
        except Exception as e:
            logger.error(f"Error in lower quality download: {e}")
            return None

class TelegramBot:
    def __init__(self):
        self.downloader = YouTubeMusicDownloader()
        self.active_downloads = {}
        
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Send welcome message when /start is issued"""
        user_id = str(update.effective_user.id)
        
        if ALLOWED_USER_IDS and user_id not in ALLOWED_USER_IDS:
            await update.message.reply_text(
                "⚠️ You are not authorized to use this bot."
            )
            return
        
        welcome_text = """
🎵 *YouTube Music Downloader Bot* 🎵

Send me a YouTube Music link and I'll download it for you!

*Supported URLs:*
• YouTube Music tracks
• YouTube videos
• Playlists (single tracks only)

*Features:*
✅ High quality MP3 audio
✅ Metadata preservation
✅ Fast downloads
✅ Direct Telegram upload

*Commands:*
/start - Show this message
/help - Get help
/cancel - Cancel current operation

Simply send a YouTube link to get started!
        """
        
        await update.message.reply_text(
            welcome_text,
            parse_mode=ParseMode.MARKDOWN,
            disable_web_page_preview=True
        )
    
    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Send help message"""
        help_text = """
*How to use this bot:*

1. Copy a YouTube Music or YouTube URL
2. Paste it here
3. Wait for the download to complete
4. Receive the audio file directly in Telegram

*Tips:*
• Maximum file size: 50MB (Telegram limit)
• For longer videos, lower quality audio is automatically used
• Age-restricted videos require cookies.txt setup

*Need help?*
Contact the bot administrator.
        """
        
        await update.message.reply_text(
            help_text,
            parse_mode=ParseMode.MARKDOWN
        )
    
    async def cancel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Cancel the current operation"""
        await update.message.reply_text(
            "Operation cancelled."
        )
        return ConversationHandler.END
    
    async def handle_url(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle incoming YouTube URLs"""
        user_id = str(update.effective_user.id)
        
        # Check authorization
        if ALLOWED_USER_IDS and user_id not in ALLOWED_USER_IDS:
            await update.message.reply_text(
                "⚠️ You are not authorized to use this bot."
            )
            return
        
        url = update.message.text.strip()
        
        # Validate YouTube URL
        if not self._is_valid_youtube_url(url):
            await update.message.reply_text(
                "❌ Please send a valid YouTube or YouTube Music URL."
            )
            return
        
        # Check if user already has an active download
        if user_id in self.active_downloads:
            await update.message.reply_text(
                "⏳ You already have a download in progress. Please wait..."
            )
            return
        
        # Mark user as downloading
        self.active_downloads[user_id] = True
        
        try:
            # Send initial processing message
            status_msg = await update.message.reply_text(
                "🔍 *Processing your request...*",
                parse_mode=ParseMode.MARKDOWN
            )
            
            # Extract video information
            await status_msg.edit_text("📥 *Fetching video information...*")
            video_info = self.downloader.extract_video_info(url)
            
            if not video_info:
                await status_msg.edit_text("❌ Could not fetch video information.")
                del self.active_downloads[user_id]
                return
            
            # Check duration (limit to 30 minutes for free tier)
            if video_info['duration'] > 1800:  # 30 minutes
                await status_msg.edit_text(
                    "❌ Video is too long (max 30 minutes for free tier)."
                )
                del self.active_downloads[user_id]
                return
            
            # Show video info
            info_text = f"""
🎵 *Track Info:*
• *Title:* {video_info['title'][:100]}
• *Artist:* {video_info['uploader']}
• *Duration:* {video_info['duration_string']}

⬇️ *Downloading audio...* This may take a moment.
            """
            
            await status_msg.edit_text(
                info_text,
                parse_mode=ParseMode.MARKDOWN
            )
            
            # Download the audio
            temp_dir = tempfile.mkdtemp()
            try:
                audio_file = await self.downloader.download_audio(url, user_id)
                
                if audio_file == "age_restricted":
                    await status_msg.edit_text(
                        "🔞 This video is age-restricted. Cookies.txt is required."
                    )
                elif audio_file == "file_too_large":
                    await status_msg.edit_text(
                        "📁 File is too large (>50MB). Try a shorter video."
                    )
                elif audio_file and os.path.exists(audio_file):
                    # Send the audio file
                    await status_msg.edit_text("📤 *Uploading to Telegram...*")
                    
                    with open(audio_file, 'rb') as audio:
                        await update.message.reply_audio(
                            audio=InputFile(audio),
                            title=video_info['title'][:64],
                            performer=video_info['uploader'][:32],
                            duration=video_info['duration'],
                            thumb=video_info['thumbnail'] if video_info['thumbnail'] else None,
                            caption=f"🎵 {video_info['title']}\n👤 {video_info['uploader']}"
                        )
                    
                    await status_msg.delete()
                else:
                    await status_msg.edit_text("❌ Download failed. Please try again.")
                    
            finally:
                # Cleanup temporary files
                try:
                    shutil.rmtree(temp_dir, ignore_errors=True)
                except:
                    pass
                
        except Exception as e:
            logger.error(f"Error in handle_url: {e}")
            await update.message.reply_text(
                f"❌ An error occurred: {str(e)}"
            )
        finally:
            # Remove user from active downloads
            if user_id in self.active_downloads:
                del self.active_downloads[user_id]
    
    def _is_valid_youtube_url(self, url: str) -> bool:
        """Validate YouTube URL"""
        youtube_regex = r'(https?://)?(www\.)?(youtube|youtu)\.(com|be)/(watch\?v=|embed/|v/|.+\?v=)?([^&=%\?]{11})'
        youtube_music_regex = r'https?://music\.youtube\.com/watch\?v=([^&]{11})'
        
        return bool(re.match(youtube_regex, url)) or bool(re.match(youtube_music_regex, url))
    
    async def error_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Log errors"""
        logger.error(f"Update {update} caused error {context.error}")
        
        if update and update.effective_message:
            await update.effective_message.reply_text(
                "❌ An unexpected error occurred. Please try again later."
            )

def main():
    """Start the bot"""
    if not TELEGRAM_TOKEN:
        raise ValueError("TELEGRAM_TOKEN environment variable is required")
    
    # Create bot application
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    
    # Initialize bot
    bot = TelegramBot()
    
    # Add handlers
    application.add_handler(CommandHandler("start", bot.start))
    application.add_handler(CommandHandler("help", bot.help_command))
    application.add_handler(CommandHandler("cancel", bot.cancel))
    
    # Add message handler for URLs
    application.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND,
        bot.handle_url
    ))
    
    # Add error handler
    application.add_error_handler(bot.error_handler)
    
    # Start the bot
    print("🤖 YouTube Music Downloader Bot is starting...")
    print("📁 Cookies file:", "Available" if COOKIES_FILE else "Not found")
    
    # For Render deployment
    port = int(os.getenv("PORT", 8443))
    
    # Start webhook for production
    webhook_url = os.getenv("WEBHOOK_URL")
    
    if webhook_url:
        # Production with webhook
        application.run_webhook(
            listen="0.0.0.0",
            port=port,
            url_path=TELEGRAM_TOKEN,
            webhook_url=f"{webhook_url}/{TELEGRAM_TOKEN}"
        )
    else:
        # Development with polling
        print("🔄 Starting in polling mode...")
        application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
