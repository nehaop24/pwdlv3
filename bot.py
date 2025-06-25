import os
import asyncio
import json
from pathlib import Path
from typing import Dict, Optional

from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton

from config import config
from downloader import PWDownloader, PWAPIError

class PWDownloadBot:
    def __init__(self):
        self.app = Client(
            "pw_downloader_bot",
            api_id=config.API_ID,
            api_hash=config.API_HASH,
            bot_token=config.BOT_TOKEN
        )
        
        self.downloader = PWDownloader(
            tmp_dir=os.path.join(config.DOWNLOAD_DIR, "tmp"),
            out_dir=config.DOWNLOAD_DIR,
            max_workers=config.MAX_WORKERS
        )
        
        # Store user sessions and download progress
        self.user_sessions: Dict[int, Dict] = {}
        self.active_downloads: Dict[int, Dict] = {}
        
        self.setup_handlers()

    def setup_handlers(self):
        """Setup message handlers"""
        
        @self.app.on_message(filters.command("start"))
        async def start_command(client, message: Message):
            welcome_text = """
🎓 **PW Video Downloader Bot**

This bot helps you download videos from PhysicsWallah using your token.

**Commands:**
/login - Set your PW token and random ID
/download - Download a video
/status - Check your login status
/help - Show this help message

**Usage:**
1. First, use /login to set your credentials
2. Then use /download with video details

**Example:**
`/download 6854310c752ef68ab0116a71 "My Video" 678b4cf5a3a368218a2b16e7`
            """
            
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("📚 Help", callback_data="help")],
                [InlineKeyboardButton("🔑 Login", callback_data="login")]
            ])
            
            await message.reply_text(welcome_text, reply_markup=keyboard)

        @self.app.on_message(filters.command("help"))
        async def help_command(client, message: Message):
            help_text = """
📖 **How to use this bot:**

**1. Get your PW credentials:**
   - Login to pw.live in your browser
   - Open Developer Tools (F12)
   - Go to Network tab
   - Make any request to api.penpencil.co
   - Copy the `Authorization` header (your token)
   - Copy the `randomid` header

**2. Login to the bot:**
   `/login your_token your_random_id`

**3. Download videos:**
   `/download video_id "video_name" batch_id`

**Example:**
`/download 6854310c752ef68ab0116a71 "Physics Lecture" 678b4cf5a3a368218a2b16e7`

**Notes:**
- Video name should be in quotes if it contains spaces
- All downloads are saved to your personal folder
- You can check download progress with /status
            """
            await message.reply_text(help_text)

        @self.app.on_message(filters.command("login"))
        async def login_command(client, message: Message):
            user_id = message.from_user.id
            
            # Parse login command
            parts = message.text.split(maxsplit=2)
            if len(parts) < 3:
                await message.reply_text(
                    "❌ **Invalid format!**\n\n"
                    "Use: `/login your_token your_random_id`\n\n"
                    "Example:\n"
                    "`/login eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9... a3e290fa-ea36-4012-9124-8908794c33aa`"
                )
                return
            
            token = parts[1]
            random_id = parts[2]
            
            # Validate token format (basic check)
            if not token.startswith("eyJ") or len(random_id) != 36:
                await message.reply_text(
                    "❌ **Invalid credentials format!**\n\n"
                    "Please check your token and random ID format."
                )
                return
            
            # Store user session
            self.user_sessions[user_id] = {
                "token": token,
                "random_id": random_id,
                "username": message.from_user.username or message.from_user.first_name
            }
            
            await message.reply_text(
                "✅ **Login successful!**\n\n"
                "You can now download videos using `/download` command."
            )

        @self.app.on_message(filters.command("download"))
        async def download_command(client, message: Message):
            user_id = message.from_user.id
            
            # Check if user is logged in
            if user_id not in self.user_sessions:
                keyboard = InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔑 Login Now", callback_data="login")]
                ])
                await message.reply_text(
                    "❌ **You need to login first!**\n\n"
                    "Use `/login your_token your_random_id`",
                    reply_markup=keyboard
                )
                return
            
            # Check if user has active download
            if user_id in self.active_downloads:
                await message.reply_text(
                    "⏳ **You already have an active download!**\n\n"
                    "Please wait for it to complete or use /status to check progress."
                )
                return
            
            # Parse download command
            text = message.text[10:]  # Remove "/download "
            parts = []
            current_part = ""
            in_quotes = False
            
            for char in text:
                if char == '"' and not in_quotes:
                    in_quotes = True
                elif char == '"' and in_quotes:
                    in_quotes = False
                    parts.append(current_part)
                    current_part = ""
                elif char == ' ' and not in_quotes:
                    if current_part:
                        parts.append(current_part)
                        current_part = ""
                else:
                    current_part += char
            
            if current_part:
                parts.append(current_part)
            
            if len(parts) < 3:
                await message.reply_text(
                    "❌ **Invalid format!**\n\n"
                    "Use: `/download video_id \"video_name\" batch_id`\n\n"
                    "Example:\n"
                    "`/download 6854310c752ef68ab0116a71 \"Physics Lecture\" 678b4cf5a3a368218a2b16e7`"
                )
                return
            
            video_id = parts[0]
            video_name = parts[1]
            batch_id = parts[2]
            
            # Start download
            await self.start_download(message, user_id, video_id, video_name, batch_id)

        @self.app.on_message(filters.command("status"))
        async def status_command(client, message: Message):
            user_id = message.from_user.id
            
            if user_id not in self.user_sessions:
                await message.reply_text("❌ **You are not logged in!**")
                return
            
            if user_id not in self.active_downloads:
                await message.reply_text("✅ **No active downloads**")
                return
            
            download_info = self.active_downloads[user_id]
            status_text = f"""
📊 **Download Status**

📹 **Video:** {download_info['name']}
🆔 **ID:** {download_info['video_id']}
📦 **Batch:** {download_info['batch_id']}

⏳ **Status:** {download_info.get('status', 'Starting...')}
            """
            
            await message.reply_text(status_text)

        @self.app.on_callback_query()
        async def callback_handler(client, callback_query):
            data = callback_query.data
            
            if data == "help":
                await callback_query.message.edit_text(
                    "📖 **Bot Help**\n\n"
                    "Use /help command for detailed instructions."
                )
            elif data == "login":
                await callback_query.message.edit_text(
                    "🔑 **Login Instructions**\n\n"
                    "Use: `/login your_token your_random_id`\n\n"
                    "Get your credentials from pw.live browser developer tools."
                )

    async def start_download(self, message: Message, user_id: int, video_id: str, video_name: str, batch_id: str):
        """Start video download process"""
        
        # Store download info
        self.active_downloads[user_id] = {
            "video_id": video_id,
            "name": video_name,
            "batch_id": batch_id,
            "status": "Starting..."
        }
        
        # Send initial status
        status_msg = await message.reply_text(
            f"🚀 **Starting download...**\n\n"
            f"📹 **Video:** {video_name}\n"
            f"🆔 **ID:** {video_id}\n"
            f"📦 **Batch:** {batch_id}\n\n"
            f"⏳ **Status:** Initializing..."
        )
        
        try:
            user_session = self.user_sessions[user_id]
            
            # Update status
            await status_msg.edit_text(
                f"🚀 **Download in progress...**\n\n"
                f"📹 **Video:** {video_name}\n"
                f"🆔 **ID:** {video_id}\n"
                f"📦 **Batch:** {batch_id}\n\n"
                f"⏳ **Status:** Getting video URL and key..."
            )
            
            # Create progress callback
            async def progress_callback(progress_info):
                try:
                    media_type = progress_info['type']
                    percentage = progress_info['percentage']
                    current = progress_info['current']
                    total = progress_info['total']
                    
                    status_text = f"⬬ **Downloading {media_type}:** {current}/{total} ({percentage:.1f}%)"
                    self.active_downloads[user_id]['status'] = status_text
                    
                    # Update message every 10 segments to avoid rate limits
                    if current % 10 == 0 or current == total:
                        await status_msg.edit_text(
                            f"🚀 **Download in progress...**\n\n"
                            f"📹 **Video:** {video_name}\n"
                            f"🆔 **ID:** {video_id}\n"
                            f"📦 **Batch:** {batch_id}\n\n"
                            f"⏳ **Status:** {status_text}"
                        )
                except Exception:
                    pass  # Ignore update errors
            
            # Set progress callback
            self.downloader.progress_callback = progress_callback
            
            # Start download in background
            loop = asyncio.get_event_loop()
            output_file = await loop.run_in_executor(
                None,
                self.downloader.download_video,
                video_id,
                batch_id,
                video_name,
                user_session["token"],
                user_session["random_id"]
            )
            
            # Download completed successfully
            file_size = os.path.getsize(output_file) / (1024 * 1024)  # MB
            
            await status_msg.edit_text(
                f"✅ **Download completed!**\n\n"
                f"📹 **Video:** {video_name}\n"
                f"📁 **File:** {os.path.basename(output_file)}\n"
                f"📊 **Size:** {file_size:.1f} MB\n\n"
                f"🎉 **Your video is ready!**"
            )
            
            # Send the video file if it's not too large
            if file_size < 50:  # Telegram limit is 50MB for bots
                try:
                    await message.reply_video(
                        video=output_file,
                        caption=f"🎬 **{video_name}**\n\n📊 Size: {file_size:.1f} MB"
                    )
                except Exception as e:
                    await message.reply_text(
                        f"✅ **Download completed but file is too large to send via Telegram.**\n\n"
                        f"📁 **File location:** `{output_file}`\n"
                        f"📊 **Size:** {file_size:.1f} MB"
                    )
            else:
                await message.reply_text(
                    f"✅ **Download completed but file is too large for Telegram.**\n\n"
                    f"📁 **File location:** `{output_file}`\n"
                    f"📊 **Size:** {file_size:.1f} MB"
                )
            
        except PWAPIError as e:
            await status_msg.edit_text(
                f"❌ **Download failed!**\n\n"
                f"📹 **Video:** {video_name}\n"
                f"🆔 **ID:** {video_id}\n\n"
                f"💥 **Error:** {str(e)}"
            )
        except Exception as e:
            await status_msg.edit_text(
                f"❌ **Unexpected error!**\n\n"
                f"📹 **Video:** {video_name}\n"
                f"🆔 **ID:** {video_id}\n\n"
                f"💥 **Error:** {str(e)}"
            )
        finally:
            # Remove from active downloads
            if user_id in self.active_downloads:
                del self.active_downloads[user_id]

    def run(self):
        """Start the bot"""
        print("🤖 Starting PW Downloader Bot...")
        print(f"📁 Download directory: {config.DOWNLOAD_DIR}")
        
        # Create download directory
        Path(config.DOWNLOAD_DIR).mkdir(parents=True, exist_ok=True)
        
        self.app.run()

if __name__ == "__main__":
    bot = PWDownloadBot()
    bot.run()