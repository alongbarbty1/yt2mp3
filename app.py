import os
import logging
import asyncio
import tempfile
import shutil
import threading
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

# Flask web server
from flask import Flask, render_template_string, jsonify, request
import json

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
PORT = int(os.getenv("PORT", 8443))

# Bot status
bot_status = {
    "status": "initializing",
    "start_time": datetime.now(),
    "downloads_processed": 0,
    "active_downloads": 0,
    "last_activity": None,
    "bot_username": None,
    "webhook_set": False
}

# HTML template for web interface
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>YouTube Music Downloader Bot</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { 
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            display: flex;
            justify-content: center;
            align-items: center;
            padding: 20px;
        }
        .container {
            background: white;
            border-radius: 20px;
            box-shadow: 0 20px 60px rgba(0, 0, 0, 0.3);
            padding: 40px;
            max-width: 800px;
            width: 100%;
            text-align: center;
        }
        .logo {
            width: 100px;
            height: 100px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            border-radius: 50%;
            margin: 0 auto 20px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 40px;
            color: white;
        }
        h1 { color: #333; margin-bottom: 10px; font-size: 2.5em; }
        .status-card {
            background: #f8f9fa;
            border-radius: 15px;
            padding: 25px;
            margin: 20px 0;
            text-align: left;
        }
        .status-dot {
            display: inline-block;
            width: 12px;
            height: 12px;
            border-radius: 50%;
            margin-right: 10px;
            background-color: {{ 'green' if bot_status.status == 'running' else 'orange' if bot_status.status == 'initializing' else 'red' }};
            animation: {{ 'pulse 2s infinite' if bot_status.status == 'running' else 'none' }};
        }
        @keyframes pulse {
            0% { opacity: 1; } 50% { opacity: 0.5; } 100% { opacity: 1; }
        }
        .info-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px;
            margin-top: 20px;
        }
        .info-item {
            background: white;
            padding: 15px;
            border-radius: 10px;
            border-left: 4px solid #667eea;
        }
        .footer { margin-top: 30px; color: #777; font-size: 0.9em; }
        .error { color: #dc3545; background: #f8d7da; padding: 10px; border-radius: 5px; margin: 10px 0; }
        .success { color: #28a745; background: #d4edda; padding: 10px; border-radius: 5px; margin: 10px 0; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <div class="logo">🎵</div>
            <h1>YouTube Music Downloader Bot</h1>
            <p class="subtitle">Powered by Python & Docker • Running on Render</p>
        </div>
        
        <div class="status-card">
            <h2><span class="status-dot"></span> Bot Status: {{ bot_status.status|upper }}</h2>
            <div class="info-grid">
                <div class="info-item">
                    <strong>Uptime:</strong><br>{{ bot_status.uptime }}
                </div>
                <div class="info-item">
                    <strong>Downloads:</strong><br>{{ bot_status.downloads_processed }}
                </div>
                <div class="info-item">
                    <strong>Active:</strong><br>{{ bot_status.active_downloads }}
                </div>
                <div class="info-item">
                    <strong>Mode:</strong><br>{{ 'Webhook' if bot_status.webhook_set else 'Polling' }}
                </div>
            </div>
        </div>
        
        <div class="status-card">
            <h3>🐳 Docker Container</h3>
            <div class="info-grid">
                <div class="info-item">
                    <strong>Port:</strong><br>{{ bot_status.port }}
                </div>
                <div class="info-item">
                    <strong>Memory:</strong><br>512 MB (Render Free)
                </div>
                <div class="info-item">
                    <strong>Cookies:</strong><br>{{ '✅ Enabled' if bot_status.cookies_enabled else '❌ Disabled' }}
                </div>
                <div class="info-item">
                    <strong>Python:</strong><br>{{ bot_status.python_version }}
                </div>
            </div>
        </div>
        
        {% if bot_status.error %}
        <div class="error">
            <strong>Error:</strong> {{ bot_status.error }}
        </div>
        {% endif %}
        
        {% if bot_status.success %}
        <div class="success">
            {{ bot_status.success }}
        </div>
        {% endif %}
        
        <div class="footer">
            <p>Bot Username: @{{ bot_status.bot_username or 'Not set' }}</p>
            <p>Current Time: {{ bot_status.current_time }}</p>
        </div>
    </div>
    
    <script>
        setTimeout(() => window.location.reload(), 30000);
    </script>
</body>
</html>
"""

# Initialize Flask app
flask_app = Flask(__name__)

# Global application variable
application = None

@flask_app.route('/')
def index():
    """Render main status page"""
    import platform
    
    # Calculate uptime
    uptime = datetime.now() - bot_status["start_time"]
    hours, remainder = divmod(int(uptime.total_seconds()), 3600)
    minutes, seconds = divmod(remainder, 60)
    uptime_str = f"{hours}h {minutes}m {seconds}s"
    
    return render_template_string(HTML_TEMPLATE, bot_status={
        **bot_status,
        "uptime": uptime_str,
        "port": PORT,
        "cookies_enabled": bool(COOKIES_FILE),
        "python_version": platform.python_version(),
        "current_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC"),
    })

@flask_app.route('/health')
def health():
    """Health check endpoint for Render"""
    return jsonify({
        "status": "healthy" if bot_status["status"] == "running" else "starting",
        "bot": bot_status["status"],
        "timestamp": datetime.now().isoformat(),
        "service": "youtube-music-bot",
        "port": PORT
    })

@flask_app.route(f'/{TELEGRAM_TOKEN}', methods=['POST'])
async def webhook():
    """Handle Telegram webhook updates"""
    if application is None:
        return "Bot not initialized", 503
    
    update = Update.de_json(await request.get_json(), application.bot)
    await application.process_update(update)
    return "OK"

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
            # Add headers to avoid bot detection
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.5',
                'Accept-Encoding': 'gzip, deflate',
                'DNT': '1',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1',
            }
        }
        
        if COOKIES_FILE:
            self.ydl_opts['cookiefile'] = COOKIES_FILE
            logger.info(f"Using cookies file: {COOKIES_FILE}")
            
        self.info_opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': True,
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.5',
            }
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
            if "Sign in to confirm" in str(e) or "age-restricted" in str(e).lower():
                return {"error": "age_restricted", "message": "Age-restricted content. Cookies.txt required."}
            return {"error": str(e)}
    
    async def download_audio(self, url, chat_id):
        """Download audio from YouTube URL"""
        temp_dir = tempfile.mkdtemp()
        output_path = None
        
        try:
            opts = self.ydl_opts.copy()
            opts['outtmpl'] = os.path.join(temp_dir, '%(title)s.%(ext)s')
            
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)
                
                downloaded_files = list(Path(temp_dir).glob("*.mp3"))
                if downloaded_files:
                    output_path = downloaded_files[0]
                    
                    file_size = output_path.stat().st_size
                    if file_size > MAX_FILE_SIZE:
                        return await self.download_lower_quality(url, temp_dir, chat_id)
                    
                    return output_path
                
        except Exception as e:
            logger.error(f"Error downloading audio: {e}")
            if "Sign in to confirm" in str(e) or "age-restricted" in str(e).lower():
                return "age_restricted"
            return None
        finally:
            if output_path:
                for file in Path(temp_dir).glob("*"):
                    if file != output_path:
                        try:
                            if file.is_file():
                                file.unlink()
                        except:
                            pass
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
            await update.message.reply_text("⚠️ You are not authorized to use this bot.")
            return
        
        welcome_text = """
🎵 *YouTube Music Downloader Bot* 🎵

Send me a YouTube Music link and I'll download it for you!

*Commands:*
/start - Show this message
/help - Get help
/status - Check bot status

Simply send a YouTube link to get started!
"""
        
        await update.message.reply_text(
            welcome_text,
            parse_mode=ParseMode.MARKDOWN,
            disable_web_page_preview=True
        )
        
        bot_status["last_activity"] = datetime.now().strftime("%H:%M:%S")
    
    async def status_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Send bot status to user"""
        uptime = datetime.now() - bot_status["start_time"]
        hours, remainder = divmod(int(uptime.total_seconds()), 3600)
        minutes, seconds = divmod(remainder, 60)
        
        status_text = f"""
🤖 *Bot Status Report*

*Status:* {'🟢 Running' if bot_status['status'] == 'running' else '🟡 Initializing'}
*Uptime:* {hours}h {minutes}m {seconds}s
*Downloads:* {bot_status['downloads_processed']}
*Active:* {bot_status['active_downloads']}
*Mode:* {'Webhook ✅' if bot_status['webhook_set'] else 'Polling ⚠️'}
*Cookies:* {'✅ Enabled' if COOKIES_FILE else '❌ Disabled'}

*Web Interface:* Available
"""
        
        await update.message.reply_text(
            status_text,
            parse_mode=ParseMode.MARKDOWN
        )
    
    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Send help message"""
        help_text = """
*How to use:*

1. Send a YouTube Music or YouTube URL
2. Wait for download to complete
3. Receive MP3 file in Telegram

*Tips:*
• Max file size: 50MB
• Max duration: 30 minutes
• Age-restricted videos require cookies.txt
"""
        
        await update.message.reply_text(
            help_text,
            parse_mode=ParseMode.MARKDOWN
        )
    
    async def handle_url(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle incoming YouTube URLs"""
        user_id = str(update.effective_user.id)
        
        if ALLOWED_USER_IDS and user_id not in ALLOWED_USER_IDS:
            await update.message.reply_text("⚠️ You are not authorized to use this bot.")
            return
        
        url = update.message.text.strip()
        
        if not self._is_valid_youtube_url(url):
            await update.message.reply_text("❌ Please send a valid YouTube or YouTube Music URL.")
            return
        
        if user_id in self.active_downloads:
            await update.message.reply_text("⏳ You already have a download in progress. Please wait...")
            return
        
        self.active_downloads[user_id] = True
        bot_status["active_downloads"] = len(self.active_downloads)
        
        try:
            status_msg = await update.message.reply_text("🔍 *Processing...*", parse_mode=ParseMode.MARKDOWN)
            
            await status_msg.edit_text("📥 *Fetching video information...*")
            video_info = self.downloader.extract_video_info(url)
            
            if isinstance(video_info, dict) and "error" in video_info:
                if video_info["error"] == "age_restricted":
                    await status_msg.edit_text("🔞 *Age-restricted content*\n\nThis video requires cookies.txt setup.")
                else:
                    await status_msg.edit_text(f"❌ Error: {video_info.get('message', 'Unknown error')}")
                del self.active_downloads[user_id]
                bot_status["active_downloads"] = len(self.active_downloads)
                return
            
            if not video_info:
                await status_msg.edit_text("❌ Could not fetch video information.")
                del self.active_downloads[user_id]
                bot_status["active_downloads"] = len(self.active_downloads)
                return
            
            if video_info['duration'] > 1800:
                await status_msg.edit_text("❌ Video is too long (max 30 minutes).")
                del self.active_downloads[user_id]
                bot_status["active_downloads"] = len(self.active_downloads)
                return
            
            info_text = f"""
🎵 *Track Info:*
• *Title:* {video_info['title'][:100]}
• *Artist:* {video_info['uploader']}
• *Duration:* {video_info['duration_string']}

⬇️ *Downloading audio...*
            """
            
            await status_msg.edit_text(info_text, parse_mode=ParseMode.MARKDOWN)
            
            temp_dir = tempfile.mkdtemp()
            try:
                audio_file = await self.downloader.download_audio(url, user_id)
                
                if audio_file == "age_restricted":
                    await status_msg.edit_text("🔞 Age-restricted. Need cookies.txt")
                elif audio_file == "file_too_large":
                    await status_msg.edit_text("📁 File too large (>50MB). Try shorter video.")
                elif audio_file and os.path.exists(audio_file):
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
                    
                    bot_status["downloads_processed"] += 1
                    await status_msg.delete()
                else:
                    await status_msg.edit_text("❌ Download failed. Try again.")
                    
            finally:
                try:
                    shutil.rmtree(temp_dir, ignore_errors=True)
                except:
                    pass
                
        except Exception as e:
            logger.error(f"Error in handle_url: {e}")
            await update.message.reply_text(f"❌ Error: {str(e)}")
        finally:
            if user_id in self.active_downloads:
                del self.active_downloads[user_id]
                bot_status["active_downloads"] = len(self.active_downloads)
            bot_status["last_activity"] = datetime.now().strftime("%H:%M:%S")
    
    def _is_valid_youtube_url(self, url: str) -> bool:
        """Validate YouTube URL"""
        youtube_regex = r'(https?://)?(www\.)?(youtube|youtu)\.(com|be)/(watch\?v=|embed/|v/|.+\?v=)?([^&=%\?]{11})'
        youtube_music_regex = r'https?://music\.youtube\.com/watch\?v=([^&]{11})'
        
        return bool(re.match(youtube_regex, url)) or bool(re.match(youtube_music_regex, url))
    
    async def error_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Log errors"""
        logger.error(f"Update {update} caused error {context.error}")
        
        if update and update.effective_message:
            await update.effective_message.reply_text("❌ An error occurred. Please try again.")

async def run_bot():
    """Run the Telegram bot"""
    global application
    
    if not TELEGRAM_TOKEN:
        raise ValueError("TELEGRAM_TOKEN environment variable is required")
    
    # Create bot application
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    
    # Initialize bot
    bot = TelegramBot()
    
    # Get bot info
    try:
        bot_info = await application.bot.get_me()
        bot_status["bot_username"] = bot_info.username
        logger.info(f"Bot started: @{bot_info.username}")
    except Exception as e:
        logger.error(f"Failed to get bot info: {e}")
    
    # Add handlers
    application.add_handler(CommandHandler("start", bot.start))
    application.add_handler(CommandHandler("help", bot.help_command))
    application.add_handler(CommandHandler("status", bot.status_command))
    
    # Add message handler for URLs
    application.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND,
        bot.handle_url
    ))
    
    # Add error handler
    application.add_error_handler(bot.error_handler)
    
    # Update bot status
    bot_status["status"] = "running"
    
    # Check if we should use webhook (Render provides a URL)
    webhook_url = os.getenv("RENDER_EXTERNAL_URL")
    
    if webhook_url:
        # Set webhook for production
        webhook_url = f"{webhook_url}/{TELEGRAM_TOKEN}"
        await application.bot.set_webhook(webhook_url)
        bot_status["webhook_set"] = True
        logger.info(f"Webhook set: {webhook_url[:50]}...")
        
        # Start webhook
        await application.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            url_path=TELEGRAM_TOKEN,
            webhook_url=webhook_url,
            secret_token=None
        )
    else:
        # Development with polling
        bot_status["webhook_set"] = False
        logger.info("Starting in polling mode...")
        await application.run_polling(allowed_updates=Update.ALL_TYPES)

def start_services():
    """Start both Flask and Telegram bot"""
    import threading
    
    # Start Flask in a separate thread
    def run_flask():
        flask_app.run(host='0.0.0.0', port=PORT, debug=False, threaded=True, use_reloader=False)
    
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    
    # Start Telegram bot in main thread
    asyncio.run(run_bot())

if __name__ == "__main__":
    print(f"🤖 Starting YouTube Music Downloader Bot...")
    print(f"🌐 Web interface on port: {PORT}")
    print(f"🔧 Python: {os.sys.version}")
    print(f"🍪 Cookies: {'Enabled' if COOKIES_FILE else 'Disabled'}")
    print(f"🐳 Docker: Running")
    print(f"⚡ Render Free Tier: Active")
    
    start_services()
