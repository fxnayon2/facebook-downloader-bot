# Facebook Video Downloader Telegram Bot

A Telegram bot that downloads Facebook videos and sends them directly in chat.

## Features

- Send any Facebook video link - bot downloads and sends the video
- Original post caption sent separately
- Large videos (>50MB) automatically split into parts
- Download stats with /status command

## Setup

1. Get a Telegram Bot Token from @BotFather
2. Set TELEGRAM_BOT_TOKEN as an environment variable
3. Run: `pip install -r requirements.txt && python main.py`

## Commands

- /start - Welcome message
- /help - How to use the bot
- /status - Bot stats
- /about - About the bot

## Deployment

This project includes a render.yaml for easy Render.com deployment.
Set TELEGRAM_BOT_TOKEN in your Render environment variables.
