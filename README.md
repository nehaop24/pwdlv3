# PW Video Downloader Telegram Bot

A Telegram bot that downloads videos from PhysicsWallah (pw.live) using user tokens. Supports both batch downloads and direct MPD links with quality selection and automatic random ID generation.

## Features

- 🎓 Download PW videos directly through Telegram
- 🔗 Support for direct MPD links
- 🎬 Quality selection (240p, 360p, 480p, 720p, 1080p)
- 🔐 Secure token-based authentication
- 🎲 **Automatic random ID generation** (no need to manually extract)
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

### 1. Get PW Token (Simplified!)

1. Login to pw.live in your browser
2. Open Developer Tools (F12)
3. Go to Network tab
4. Make any request to api.penpencil.co
5. Copy the `Authorization` header (your token)
6. **That's it!** Random ID is automatically generated

### 2. Bot Commands

- `/start` - Start the bot
- `/login token` - Set your PW token (random ID auto-generated)
- `/download video_id "video_name" batch_id [quality]` - Download using IDs
- `/link Video Name:mpd_url [quality]` - Download from direct link
- `/quality video_id batch_id` or `/quality direct_link` - Check available qualities
- `/status` - Check download status
- `/help` - Show help

### 3. Example Usage

**Login (Simplified!):**
```
/login eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9...
```

**Download using video ID and batch ID:**
```
/download 6854310c752ef68ab0116a71 "Physics Lecture" 678b4cf5a3a368218a2b16e7 720
```

**Download from direct link:**
```
/link Kinetic Theory of Gases:https://d1d34p8vz63oiq.cloudfront.net/c3905743-cd7e-49d7-b472-4a8f11444beb/master.mpd?parentId=63fc53f28aac0a001871320d&childId=6583cf6da25635465b7e6430
```

**Check available qualities:**
```
/quality 6854310c752ef68ab0116a71 678b4cf5a3a368218a2b16e7
```

## Quality Options

The bot supports the following quality options:
- **240p** - Low quality, smaller file size
- **360p** - Standard quality
- **480p** - Good quality
- **720p** - HD quality (recommended)
- **1080p** - Full HD quality (if available)

If no quality is specified, the bot will automatically select the highest available quality.

## Direct Link Format

For direct MPD links, use this format:
```
Video Name:https://d1d34p8vz63oiq.cloudfront.net/video_id/master.mpd?parentId=batch_id&childId=video_id
```

Where:
- `parentId` = batch ID
- `childId` = video ID

## Key Improvements

### 🎲 Automatic Random ID Generation
- **No more manual extraction** of random ID from browser
- **Automatic UUID generation** similar to your Endpoints class
- **Token validation** to ensure credentials work
- **Simplified login process** - just provide the token!

### 🔧 Enhanced Error Handling
- **Token validity testing** before storing credentials
- **Better error messages** for invalid tokens
- **Automatic retry logic** for network issues

### 📱 Improved User Experience
- **Cleaner login flow** with fewer steps
- **Real-time status updates** during downloads
- **Quality preview** before downloading
- **Progress tracking** with detailed feedback

## How It Works

1. **Authentication**: Users provide their PW token, random ID is auto-generated
2. **Token Validation**: Bot tests token validity before storing
3. **Video URL Extraction**: Bot fetches video URLs and decryption keys from PW API
4. **Quality Selection**: Bot analyzes available qualities and selects based on user preference
5. **MPD Parsing**: Parses the DASH manifest to get segment URLs
6. **Segment Download**: Downloads audio and video segments concurrently
7. **Decryption**: Decrypts segments using mp4decrypt
8. **Merging**: Combines audio and video using ffmpeg
9. **Delivery**: Sends the final video file via Telegram

## File Structure

```
├── bot.py              # Main bot application with auto random ID
├── pw_api.py           # Enhanced PW API client with auto UUID generation
├── downloader.py       # Download and processing logic
├── config.py           # Configuration management
├── requirements.txt    # Python dependencies
├── .env.example        # Environment variables template
└── README.md          # This file
```

## Security Notes

- User tokens are stored in memory only (not persisted)
- Random IDs are automatically generated using UUID4
- Each user can only have one active download at a time
- Bot validates token format and functionality before storing
- All downloads are isolated per user

## Limitations

- Telegram file size limit: 50MB for bots
- Requires mp4decrypt and ffmpeg to be installed
- Users need to provide their own PW tokens
- One download per user at a time

## Troubleshooting

### Common Issues

1. **"Invalid or expired token"**
   - Get a fresh token from pw.live
   - Ensure you're copying the full Authorization header

2. **"mp4decrypt not found"**
   - Install mp4decrypt and add to PATH
   - Or place binary in `./bin/` directory

3. **"ffmpeg not found"**
   - Install ffmpeg and add to PATH
   - Or place binary in `./bin/` directory

4. **Download fails**
   - Check if token is still valid
   - Verify video_id and batch_id are correct
   - Check network connectivity

5. **Quality not available**
   - Use `/quality` command to check available qualities
   - Bot will automatically select closest available quality

## Contributing

Feel free to submit issues and enhancement requests!

## License

This project is for educational purposes only. Please respect PhysicsWallah's terms of service.