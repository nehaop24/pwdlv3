# PW Video Downloader Telegram Bot

A Telegram bot that downloads videos from PhysicsWallah (pw.live) using user tokens.

## Features

- 🎓 Download PW videos directly through Telegram
- 🔐 Secure token-based authentication
- 📊 Real-time download progress
- 🎬 Automatic video delivery (for files under 50MB)
- 🛡️ User session management
- ⚡ Concurrent downloads with progress tracking

## Setup

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Install Required Tools

You need `mp4decrypt` and `ffmpeg` installed:

**For Ubuntu/Debian:**
```bash
sudo apt update
sudo apt install ffmpeg
# For mp4decrypt, download from Bento4 releases
wget https://github.com/axiomatic-systems/Bento4/releases/download/v1.6.0-639/Bento4-SDK-1-6-0-639.x86_64-unknown-linux.zip
unzip Bento4-SDK-1-6-0-639.x86_64-unknown-linux.zip
sudo cp Bento4-SDK-1-6-0-639.x86_64-unknown-linux/bin/mp4decrypt /usr/local/bin/
```

**For Windows:**
- Download ffmpeg from https://ffmpeg.org/download.html
- Download mp4decrypt from Bento4 releases
- Add both to your PATH

### 3. Configure Environment

1. Copy `.env.example` to `.env`
2. Fill in your Telegram bot credentials:
   - Get `BOT_TOKEN` from @BotFather
   - Get `API_ID` and `API_HASH` from https://my.telegram.org

```env
BOT_TOKEN=your_bot_token_here
API_ID=your_api_id_here
API_HASH=your_api_hash_here
DOWNLOAD_DIR=./downloads
MAX_WORKERS=8
```

### 4. Run the Bot

```bash
python bot.py
```

## Usage

### 1. Get PW Credentials

1. Login to pw.live in your browser
2. Open Developer Tools (F12)
3. Go to Network tab
4. Make any request to api.penpencil.co
5. Copy the `Authorization` header (your token)
6. Copy the `randomid` header

### 2. Bot Commands

- `/start` - Start the bot
- `/login token random_id` - Set your PW credentials
- `/download video_id "video_name" batch_id` - Download a video
- `/status` - Check download status
- `/help` - Show help

### 3. Example Usage

```
/login eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9... a3e290fa-ea36-4012-9124-8908794c33aa

/download 6854310c752ef68ab0116a71 "Physics Lecture" 678b4cf5a3a368218a2b16e7
```

## How It Works

1. **Authentication**: Users provide their PW token and random ID
2. **Video URL Extraction**: Bot fetches video URLs and decryption keys from PW API
3. **MPD Parsing**: Parses the DASH manifest to get segment URLs
4. **Segment Download**: Downloads audio and video segments concurrently
5. **Decryption**: Decrypts segments using mp4decrypt
6. **Merging**: Combines audio and video using ffmpeg
7. **Delivery**: Sends the final video file via Telegram

## File Structure

```
├── bot.py              # Main bot application
├── pw_api.py           # PW API client and MPD parser
├── downloader.py       # Download and processing logic
├── config.py           # Configuration management
├── requirements.txt    # Python dependencies
├── .env.example        # Environment variables template
└── README.md          # This file
```

## Security Notes

- User tokens are stored in memory only (not persisted)
- Each user can only have one active download at a time
- Bot validates token format before storing
- All downloads are isolated per user

## Limitations

- Telegram file size limit: 50MB for bots
- Requires mp4decrypt and ffmpeg to be installed
- Users need to provide their own PW tokens
- One download per user at a time

## Troubleshooting

### Common Issues

1. **"mp4decrypt not found"**
   - Install mp4decrypt and add to PATH
   - Or place binary in `./bin/` directory

2. **"ffmpeg not found"**
   - Install ffmpeg and add to PATH
   - Or place binary in `./bin/` directory

3. **"Invalid token format"**
   - Ensure token starts with "eyJ"
   - Ensure random_id is 36 characters long

4. **Download fails**
   - Check if token is still valid
   - Verify video_id and batch_id are correct
   - Check network connectivity

## Contributing

Feel free to submit issues and enhancement requests!

## License

This project is for educational purposes only. Please respect PhysicsWallah's terms of service.