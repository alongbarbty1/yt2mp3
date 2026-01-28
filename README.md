# YouTube Music Downloader Telegram Bot

A powerful Telegram bot that downloads music from YouTube and YouTube Music, built for Render's free tier.

## Features

- 🎵 Download YouTube Music tracks as MP3
- 🚀 Fast and efficient downloads
- 🔐 Cookie support for age-restricted content
- 📱 Direct upload to Telegram
- 🎨 Preserves metadata (title, artist, album art)
- ⚡ Optimized for Render free tier

## Setup

### 1. Create a Telegram Bot
1. Message @BotFather on Telegram
2. Create a new bot with `/newbot`
3. Copy the API token

### 2. Deploy to Render

#### Method A: One-Click Deploy
[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy)

#### Method B: Manual Deployment
1. Fork this repository
2. Create a new Web Service on Render
3. Connect your GitHub repository
4. Set environment variables:
   - `TELEGRAM_TOKEN`: Your bot token
   - `ALLOWED_USER_IDS`: Comma-separated user IDs (optional)
5. Deploy!

### 3. Environment Variables
```bash
TELEGRAM_TOKEN=your_bot_token_here
ALLOWED_USER_IDS=123456789,987654321  # Optional
