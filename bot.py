import os
import asyncio
import json
import logging
from pathlib import Path
from typing import Dict, Optional

from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton

from config import config

# Import from your existing mainLogic
from mainLogic.startup.Login.sudat import Login
from mainLogic.big4.Ravenclaw_decrypt.key import LicenseKeyFetcher
from mainLogic.utils.MPDParser import MPDParser
from mainLogic.main import Main
from mainLogic.startup.checkup import CheckState
from mainLogic.utils import glv_var
from mainLogic.utils.glv_var import debugger
from mainLogic.error import PWAPIError

# Set up logging for bot messages only (not API calls)
logging.basicConfig(
    level=logging.WARNING,  # Only show warnings and errors for Telegram
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class PWDownloadBot:
    def __init__(self):
        self.app = Client(
            "pw_downloader_bot",
            api_id=config.API_ID,
            api_hash=config.API_HASH,
            bot_token=config.BOT_TOKEN
        )
        
        # Store user sessions and download progress
        self.user_sessions: Dict[int, Dict] = {}
        self.active_downloads: Dict[int, Dict] = {}
        self.pending_logins: Dict[int, Dict] = {}  # For OTP verification
        
        # Initialize checkup for dependencies
        self.ch = CheckState()
        
        self.setup_handlers()

    def setup_handlers(self):
        """Setup message handlers"""
        
        @self.app.on_message(filters.command("start"))
        async def start_command(client, message: Message):
            welcome_text = """
🎓 **PW Video Downloader Bot**

This bot helps you download videos from PhysicsWallah using phone number login.

**Commands:**
/login - Login with your phone number
/download - Download a video using video ID and batch ID
/link - Download from direct MPD link
/quality - Check available qualities for a video
/status - Check your login status
/help - Show this help message

**Usage:**
1. First, use /login to authenticate with your phone number
2. Then use /download or /link to download videos

**Examples:**
`/login 9876543210`
`/download 6854310c752ef68ab0116a71 "My Video" 678b4cf5a3a368218a2b16e7`
`/link Kinetic Theory:https://d1d34p8vz63oiq.cloudfront.net/c3905743.../master.mpd?parentId=...&childId=...`
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

**1. Login with your phone number:**
   `/login 9876543210`
   
   The bot will send you an OTP via SMS. Reply with the OTP to complete login.

**2. Download videos:**
   **Method 1 - Using video ID and batch ID:**
   `/download video_id "video_name" batch_id [quality]`
   
   **Method 2 - Using direct MPD link:**
   `/link Video Name:https://d1d34p8vz63oiq.cloudfront.net/.../master.mpd?parentId=...&childId=...`

**3. Check available qualities:**
   `/quality video_id batch_id` or `/quality direct_link`

**Quality Options:**
- 240, 360, 480, 720, 1080 (specify the height in pixels)
- If not specified, highest available quality is used

**Examples:**
`/login 9876543210`
`123456` (OTP reply)
`/download 6854310c752ef68ab0116a71 "Physics Lecture" 678b4cf5a3a368218a2b16e7 720`
`/link Kinetic Theory:https://d1d34p8vz63oiq.cloudfront.net/c3905743.../master.mpd?parentId=...&childId=...`

**Notes:**
- Video name should be in quotes if it contains spaces
- All downloads are saved to your personal folder
- You can check download progress with /status
            """
            await message.reply_text(help_text)

        @self.app.on_message(filters.command("login"))
        async def login_command(client, message: Message):
            user_id = message.from_user.id
            
            # Parse login command - phone number
            parts = message.text.split(maxsplit=1)
            if len(parts) < 2:
                await message.reply_text(
                    "❌ **Invalid format!**\n\n"
                    "Use: `/login phone_number`\n\n"
                    "Example:\n"
                    "`/login 9876543210`\n\n"
                    "**Note:** Use your 10-digit phone number without +91"
                )
                return
            
            phone_number = parts[1].strip()
            
            # Validate phone number format
            if not phone_number.isdigit() or len(phone_number) != 10:
                await message.reply_text(
                    "❌ **Invalid phone number format!**\n\n"
                    "Please enter a valid 10-digit phone number.\n\n"
                    "Example: `9876543210`"
                )
                return
            
            try:
                # Initialize login process using your existing Login class
                login_instance = Login(phone_number)
                
                # Send OTP
                status_msg = await message.reply_text("📱 **Sending OTP...**")
                
                if login_instance.gen_otp():
                    # Store login session for OTP verification
                    self.pending_logins[user_id] = {
                        "login_instance": login_instance,
                        "phone_number": phone_number,
                        "username": message.from_user.username or message.from_user.first_name
                    }
                    
                    await status_msg.edit_text(
                        f"✅ **OTP sent to {phone_number}**\n\n"
                        "📝 **Please reply with the 6-digit OTP you received**\n\n"
                        "Example: `123456`"
                    )
                else:
                    await status_msg.edit_text(
                        "❌ **Failed to send OTP**\n\n"
                        "Please check your phone number and try again.\n"
                        "Make sure you have a valid PhysicsWallah account."
                    )
                    
            except Exception as e:
                debugger.error(f"Error sending OTP: {str(e)}")
                await message.reply_text(
                    f"❌ **Error sending OTP**\n\n"
                    f"Error: {str(e)}\n\n"
                    "Please try again later."
                )

        @self.app.on_message(filters.text & ~filters.command(["start", "help", "login", "download", "link", "quality", "status"]))
        async def handle_otp(client, message: Message):
            """Handle OTP verification"""
            user_id = message.from_user.id
            
            # Check if user has pending login
            if user_id not in self.pending_logins:
                return  # Not an OTP, ignore
            
            otp = message.text.strip()
            
            # Validate OTP format
            if not otp.isdigit() or len(otp) != 6:
                await message.reply_text(
                    "❌ **Invalid OTP format**\n\n"
                    "Please enter the 6-digit OTP you received.\n\n"
                    "Example: `123456`"
                )
                return
            
            try:
                pending_login = self.pending_logins[user_id]
                login_instance = pending_login["login_instance"]
                
                status_msg = await message.reply_text("🔄 **Verifying OTP...**")
                
                if login_instance.login(otp):
                    # Get token data from login instance
                    token_data = login_instance.token
                    
                    if token_data:
                        # Extract access token and random ID
                        access_token = token_data.get('token') or token_data.get('access_token')
                        random_id = token_data.get('randomId', "a3e290fa-ea36-4012-9124-8908794c33aa")
                        
                        # Store user session
                        self.user_sessions[user_id] = {
                            "token": access_token,
                            "random_id": random_id,
                            "phone_number": pending_login["phone_number"],
                            "username": pending_login["username"]
                        }
                        
                        # Remove pending login
                        del self.pending_logins[user_id]
                        
                        await status_msg.edit_text(
                            "✅ **Login successful!**\n\n"
                            f"📱 **Phone:** {pending_login['phone_number']}\n"
                            f"🎲 **Random ID:** `{random_id}`\n\n"
                            "You can now download videos using `/download` or `/link` commands."
                        )
                    else:
                        await status_msg.edit_text(
                            "❌ **Login failed - Could not get access token**\n\n"
                            "Please try logging in again with `/login`"
                        )
                else:
                    await status_msg.edit_text(
                        "❌ **Invalid OTP**\n\n"
                        "Please check the OTP and try again.\n"
                        "Or use `/login` to request a new OTP."
                    )
                    
            except Exception as e:
                debugger.error(f"Error verifying OTP: {str(e)}")
                await message.reply_text(
                    f"❌ **Error verifying OTP**\n\n"
                    f"Error: {str(e)}\n\n"
                    "Please try logging in again with `/login`"
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
                    "Use `/login phone_number`",
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
                    "Use: `/download video_id \"video_name\" batch_id [quality]`\n\n"
                    "Example:\n"
                    "`/download 6854310c752ef68ab0116a71 \"Physics Lecture\" 678b4cf5a3a368218a2b16e7 720`"
                )
                return
            
            video_id = parts[0]
            video_name = parts[1]
            batch_id = parts[2]
            quality = None
            
            if len(parts) > 3:
                try:
                    quality = int(parts[3])
                except ValueError:
                    await message.reply_text("❌ **Invalid quality format!** Quality should be a number (e.g., 720)")
                    return
            
            # Start download
            await self.start_batch_download(message, user_id, video_id, video_name, batch_id, quality)

        @self.app.on_message(filters.command("link"))
        async def link_command(client, message: Message):
            user_id = message.from_user.id
            
            # Check if user is logged in
            if user_id not in self.user_sessions:
                keyboard = InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔑 Login Now", callback_data="login")]
                ])
                await message.reply_text(
                    "❌ **You need to login first!**\n\n"
                    "Use `/login phone_number`",
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
            
            # Parse link command
            text = message.text[6:]  # Remove "/link "
            if not text.strip():
                await message.reply_text(
                    "❌ **Invalid format!**\n\n"
                    "Use: `/link Video Name:https://d1d34p8vz63oiq.cloudfront.net/.../master.mpd?parentId=...&childId=...`\n\n"
                    "Or: `/link https://d1d34p8vz63oiq.cloudfront.net/.../master.mpd?parentId=...&childId=... [quality]`"
                )
                return
            
            # Parse quality if provided
            parts = text.strip().split()
            link = parts[0]
            quality = None
            
            if len(parts) > 1:
                try:
                    quality = int(parts[1])
                except ValueError:
                    await message.reply_text("❌ **Invalid quality format!** Quality should be a number (e.g., 720)")
                    return
            
            # Start download
            await self.start_link_download(message, user_id, link, quality)

        @self.app.on_message(filters.command("quality"))
        async def quality_command(client, message: Message):
            user_id = message.from_user.id
            
            # Check if user is logged in
            if user_id not in self.user_sessions:
                await message.reply_text("❌ **You need to login first!**")
                return
            
            # Parse quality command
            text = message.text[9:]  # Remove "/quality "
            parts = text.strip().split()
            
            if len(parts) < 1:
                await message.reply_text(
                    "❌ **Invalid format!**\n\n"
                    "Use: `/quality video_id batch_id` or `/quality direct_link`"
                )
                return
            
            try:
                user_session = self.user_sessions[user_id]
                fetcher = LicenseKeyFetcher(user_session["token"], user_session["random_id"])
                
                if len(parts) == 2:
                    # video_id and batch_id provided
                    video_id, batch_id = parts[0], parts[1]
                    kid, key = fetcher.get_key(video_id, batch_id, verbose=False)
                    mpd_url = fetcher.url
                elif len(parts) == 1:
                    # Direct link provided
                    link = parts[0]
                    if ':' in link:
                        mpd_url = link.split(':', 1)[1].strip()
                    else:
                        mpd_url = link.strip()
                else:
                    await message.reply_text("❌ **Invalid format!**")
                    return
                
                # Parse MPD and get qualities using your existing MPDParser
                parser = MPDParser(mpd_url)
                parser.pre_process().parse()
                
                # Get available resolutions from video adaptation set
                video_set = parser.get_video_set()
                resolutions = parser.get_resolutions_in_adaptation_set(video_set)
                
                if resolutions:
                    quality_text = "📺 **Available Qualities:**\n\n"
                    for res in sorted(resolutions, reverse=True):
                        quality_text += f"• **{res}p**\n"
                    
                    quality_text += "\n💡 **Usage:** Add quality number to your download command\n"
                    quality_text += "Example: `/download video_id \"name\" batch_id 720`"
                else:
                    quality_text = "❌ **No quality information found**"
                
                await message.reply_text(quality_text)
                
            except Exception as e:
                debugger.error(f"Error getting quality info: {str(e)}")
                await message.reply_text(f"❌ **Error getting quality info:** {str(e)}")

        @self.app.on_message(filters.command("status"))
        async def status_command(client, message: Message):
            user_id = message.from_user.id
            
            if user_id not in self.user_sessions:
                if user_id in self.pending_logins:
                    pending = self.pending_logins[user_id]
                    await message.reply_text(
                        f"⏳ **Login in progress**\n\n"
                        f"📱 **Phone:** {pending['phone_number']}\n"
                        f"📝 **Waiting for OTP verification**\n\n"
                        "Please reply with the 6-digit OTP you received."
                    )
                else:
                    await message.reply_text("❌ **You are not logged in!**")
                return
            
            if user_id not in self.active_downloads:
                user_session = self.user_sessions[user_id]
                await message.reply_text(
                    f"✅ **No active downloads**\n\n"
                    f"📱 **Phone:** {user_session['phone_number']}\n"
                    f"👤 **User:** {user_session['username']}\n"
                    f"🎲 **Random ID:** `{user_session['random_id']}`"
                )
                return
            
            download_info = self.active_downloads[user_id]
            status_text = f"""
📊 **Download Status**

📹 **Video:** {download_info['name']}
🆔 **ID:** {download_info.get('video_id', 'N/A')}
📦 **Batch:** {download_info.get('batch_id', 'N/A')}

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
                    "Use: `/login phone_number`\n\n"
                    "Example: `/login 9876543210`\n\n"
                    "You'll receive an OTP via SMS to complete the login."
                )

    def parse_direct_link(self, link: str):
        """Parse direct MPD link to extract video_id, batch_id, and name"""
        try:
            from urllib.parse import urlparse, parse_qs
            
            # Split by the colon to separate name and URL
            if ':' in link:
                name, url = link.split(':', 1)
                name = name.strip()
            else:
                url = link.strip()
                name = "Video"
            
            # Parse URL to extract parentId and childId
            parsed_url = urlparse(url)
            query_params = parse_qs(parsed_url.query)
            
            parent_id = query_params.get('parentId', [None])[0]
            child_id = query_params.get('childId', [None])[0]
            
            debugger.info(f"Parsed - Name: {name}, Parent ID: {parent_id}, Child ID: {child_id}")
            
            if not parent_id or not child_id:
                raise Exception("Could not extract parentId or childId from URL")
            
            return child_id, parent_id, name
            
        except Exception as e:
            debugger.error(f"Error parsing direct link: {str(e)}")
            raise Exception(f"Error parsing direct link: {str(e)}")

    async def start_batch_download(self, message: Message, user_id: int, video_id: str, video_name: str, batch_id: str, quality: Optional[int]):
        """Start batch video download process using mainLogic.main.Main"""
        
        # Store download info
        self.active_downloads[user_id] = {
            "video_id": video_id,
            "name": video_name,
            "batch_id": batch_id,
            "quality": quality,
            "status": "Starting..."
        }
        
        # Send initial status
        quality_text = f" ({quality}p)" if quality else ""
        status_msg = await message.reply_text(
            f"🚀 **Starting download...**\n\n"
            f"📹 **Video:** {video_name}\n"
            f"🆔 **ID:** {video_id}\n"
            f"📦 **Batch:** {batch_id}\n"
            f"🎬 **Quality:** {quality or 'Best Available'}{quality_text}\n\n"
            f"⏳ **Status:** Initializing..."
        )
        
        try:
            user_session = self.user_sessions[user_id]
            
            # Update status
            await status_msg.edit_text(
                f"🚀 **Download in progress...**\n\n"
                f"📹 **Video:** {video_name}\n"
                f"🆔 **ID:** {video_id}\n"
                f"📦 **Batch:** {batch_id}\n"
                f"🎬 **Quality:** {quality or 'Best Available'}{quality_text}\n\n"
                f"⏳ **Status:** Getting video URL and key..."
            )
            
            # Create user-specific download directory
            user_download_dir = os.path.join(config.DOWNLOAD_DIR, f"user_{user_id}")
            os.makedirs(user_download_dir, exist_ok=True)
            
            # Create progress callback
            async def progress_callback(progress_info):
                try:
                    progress_str = progress_info.get('str', '')
                    progress_percent = progress_info.get('progress', 0)
                    
                    status_text = f"⬬ **Progress:** {progress_percent:.1f}% - {progress_str}"
                    self.active_downloads[user_id]['status'] = status_text
                    
                    # Update message periodically to avoid rate limits
                    if progress_percent % 10 < 1:  # Update every 10%
                        await status_msg.edit_text(
                            f"🚀 **Download in progress...**\n\n"
                            f"📹 **Video:** {video_name}\n"
                            f"🆔 **ID:** {video_id}\n"
                            f"📦 **Batch:** {batch_id}\n"
                            f"🎬 **Quality:** {quality or 'Best Available'}{quality_text}\n\n"
                            f"⏳ **Status:** {status_text}"
                        )
                except Exception:
                    pass  # Ignore update errors
            
            # Get dependencies using your existing checkup
            state = self.ch.checkup(glv_var.EXECUTABLES, directory=user_download_dir, verbose=False, do_raise=True)
            prefs = state['prefs']
            
            # Start download using your existing Main class
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                self._run_main_download,
                video_id,
                video_name,
                batch_id,
                user_session["token"],
                user_session["random_id"],
                user_download_dir,
                state,
                progress_callback
            )
            
            # Find the downloaded file
            output_file = None
            for file in os.listdir(user_download_dir):
                if file.endswith('.mp4') and video_name.replace(' ', '_') in file:
                    output_file = os.path.join(user_download_dir, file)
                    break
            
            if not output_file:
                # Fallback: find any .mp4 file
                for file in os.listdir(user_download_dir):
                    if file.endswith('.mp4'):
                        output_file = os.path.join(user_download_dir, file)
                        break
            
            if output_file and os.path.exists(output_file):
                # Download completed successfully
                file_size = os.path.getsize(output_file) / (1024 * 1024)  # MB
                
                await status_msg.edit_text(
                    f"✅ **Download completed!**\n\n"
                    f"📹 **Video:** {video_name}\n"
                    f"📁 **File:** {os.path.basename(output_file)}\n"
                    f"📊 **Size:** {file_size:.1f} MB\n"
                    f"🎬 **Quality:** {quality or 'Best Available'}{quality_text}\n\n"
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
            else:
                await status_msg.edit_text(
                    f"❌ **Download failed - Output file not found**\n\n"
                    f"📹 **Video:** {video_name}\n"
                    f"🆔 **ID:** {video_id}"
                )
            
        except Exception as e:
            debugger.error(f"Download failed: {str(e)}")
            await status_msg.edit_text(
                f"❌ **Download failed!**\n\n"
                f"📹 **Video:** {video_name}\n"
                f"🆔 **ID:** {video_id}\n\n"
                f"💥 **Error:** {str(e)}"
            )
        finally:
            # Remove from active downloads
            if user_id in self.active_downloads:
                del self.active_downloads[user_id]

    async def start_link_download(self, message: Message, user_id: int, link: str, quality: Optional[int]):
        """Start direct link download process"""
        
        try:
            # Parse the link to get video_id, batch_id, and name
            video_id, batch_id, name = self.parse_direct_link(link)
            
            # Use the batch download method with parsed data
            await self.start_batch_download(message, user_id, video_id, name, batch_id, quality)
            
        except Exception as e:
            debugger.error(f"Link download failed: {str(e)}")
            await message.reply_text(
                f"❌ **Failed to parse link!**\n\n"
                f"💥 **Error:** {str(e)}\n\n"
                "Please check the link format."
            )

    def _run_main_download(self, video_id: str, video_name: str, batch_id: str, token: str, random_id: str, 
                          download_dir: str, state: dict, progress_callback):
        """Run the main download using your existing Main class"""
        try:
            # Use your existing Main class for downloading
            main_instance = Main(
                id=video_id,
                name=video_name,
                batch_name=batch_id,
                directory=download_dir,
                ffmpeg=state['ffmpeg'],
                token=token,
                random_id=random_id,
                mp4d=state['mp4decrypt'],
                tmpDir=state.get('tmpDir', './tmp/'),
                verbose=False,
                progress_callback=progress_callback
            )
            
            # Process the download
            main_instance.process()
            
        except Exception as e:
            debugger.error(f"Main download process failed: {str(e)}")
            raise e

    def run(self):
        """Start the bot"""
        print("🤖 Starting PW Downloader Bot...")
        print(f"📁 Download directory: {config.DOWNLOAD_DIR}")
        print("📱 Phone-based login system enabled")
        print("🔧 Using mainLogic components for downloading")
        
        # Create download directory
        Path(config.DOWNLOAD_DIR).mkdir(parents=True, exist_ok=True)
        
        self.app.run()

if __name__ == "__main__":
    bot = PWDownloadBot()
    bot.run()