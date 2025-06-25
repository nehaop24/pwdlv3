import os
import asyncio
import json
import uuid
import logging
from pathlib import Path
from typing import Dict, Optional

from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton

from config import config
from downloader import PWDownloader
from pw_api import PWAPIError, LicenseKeyFetcher, MPDParser, PWLogin

# Set up logging for API calls only (not Telegram messages)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

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
        
        # Store pending OTP verifications
        self.pending_otp: Dict[int, PWLogin] = {}
        
        self.setup_handlers()

    def validate_token_with_endpoint(self, token: str, random_id: str) -> bool:
        """Validate token using the specific PW endpoint"""
        try:
            logger.info(f"Validating token with specific endpoint")
            
            tokencheckheaders = {
                "client-id": "5eb393ee95fab7468a79d189",
                "client-type": "WEB",
                "Authorization": f"Bearer {token}",
                "client-version": "3.3.0",
                "randomId": random_id,
                "Accept": "application/json, text/plain, */*"
            }
            
            test_url = "https://api.penpencil.co/v3/batches/my-batches?mode=1&amount=paid&page=1"
            logger.info(f"Testing token with URL: {test_url}")
            logger.debug(f"Headers: {json.dumps(tokencheckheaders, indent=2)}")
            
            import requests
            response = requests.get(test_url, headers=tokencheckheaders)
            
            logger.info(f"Token validation response status: {response.status_code}")
            logger.debug(f"Token validation response: {response.text}")
            
            if response.status_code == 200:
                try:
                    data = response.json()
                    # Check if response has expected structure
                    if 'success' in data and data.get('success'):
                        logger.info("Token validation successful - valid response structure")
                        return True
                    elif 'data' in data:
                        logger.info("Token validation successful - has data field")
                        return True
                    else:
                        logger.warning(f"Token validation: unexpected response structure: {data}")
                        return False
                except json.JSONDecodeError:
                    logger.warning("Token validation: response is not valid JSON")
                    return False
            else:
                logger.warning(f"Token validation failed with status {response.status_code}")
                return False
                
        except Exception as e:
            logger.error(f"Error validating token: {str(e)}")
            return False

    def setup_handlers(self):
        """Setup message handlers"""
        
        @self.app.on_message(filters.command("start"))
        async def start_command(client, message: Message):
            welcome_text = """
🎓 **PW Video Downloader Bot**

This bot helps you download videos from PhysicsWallah using your token.

**Commands:**
/login - Login with phone number (OTP-based)
/token - Set your PW token directly
/download - Download a video using IDs
/link - Download from direct MPD link
/quality - Check available video qualities
/status - Check your login status
/help - Show this help message

**Quick Start:**
1. Use /login with your phone number for OTP-based login
2. Or use /token to set your token directly
3. Then use /download or /link to download videos

**Example:**
`/login 9876543210`
`/download 6854310c752ef68ab0116a71 "My Video" 678b4cf5a3a368218a2b16e7 720`
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

**Method 1: Phone Login (Recommended)**
1. Use `/login 9876543210` (your phone number)
2. Enter the OTP you receive
3. Start downloading!

**Method 2: Token Login**
1. Login to pw.live in your browser
2. Open Developer Tools (F12) → Network tab
3. Find any request to api.penpencil.co
4. Copy the `Authorization` header value
5. Use `/token your_token_here`

**Download Commands:**
• `/download video_id "video_name" batch_id [quality]`
• `/link Video Name:mpd_url [quality]`
• `/quality video_id batch_id` - Check available qualities

**Quality Options:** 240, 360, 480, 720, 1080
If not specified, highest quality is selected automatically.

**Examples:**
`/download 6854310c752ef68ab0116a71 "Physics Lecture" 678b4cf5a3a368218a2b16e7 720`
`/link Kinetic Theory:https://d1d34p8vz63oiq.cloudfront.net/video_id/master.mpd?parentId=batch&childId=video`
            """
            await message.reply_text(help_text)

        @self.app.on_message(filters.command("login"))
        async def login_command(client, message: Message):
            user_id = message.from_user.id
            
            # Parse login command
            parts = message.text.split(maxsplit=1)
            if len(parts) < 2:
                await message.reply_text(
                    "❌ **Invalid format!**\n\n"
                    "Use: `/login phone_number`\n\n"
                    "Example:\n"
                    "`/login 9876543210`"
                )
                return
            
            phone_number = parts[1].strip()
            
            # Validate phone number (basic check)
            if not phone_number.isdigit() or len(phone_number) != 10:
                await message.reply_text(
                    "❌ **Invalid phone number!**\n\n"
                    "Please provide a valid 10-digit phone number."
                )
                return
            
            # Initialize login process
            pw_login = PWLogin(phone_number)
            
            # Send OTP
            if pw_login.send_otp():
                self.pending_otp[user_id] = pw_login
                await message.reply_text(
                    f"📱 **OTP sent to {phone_number}**\n\n"
                    "Please reply with the OTP you received.\n"
                    "Example: `123456`"
                )
            else:
                await message.reply_text(
                    "❌ **Failed to send OTP!**\n\n"
                    "Please check your phone number and try again."
                )

        @self.app.on_message(filters.command("token"))
        async def token_command(client, message: Message):
            user_id = message.from_user.id
            
            # Parse token command
            parts = message.text.split(maxsplit=1)
            if len(parts) < 2:
                await message.reply_text(
                    "❌ **Invalid format!**\n\n"
                    "Use: `/token your_token_here`\n\n"
                    "Get your token from pw.live browser developer tools."
                )
                return
            
            token = parts[1].strip()
            
            # Validate token format (basic check)
            if not token.startswith("eyJ"):
                await message.reply_text(
                    "❌ **Invalid token format!**\n\n"
                    "Token should start with 'eyJ'. Please check your token."
                )
                return
            
            # Generate random ID automatically
            random_id = str(uuid.uuid4())
            
            # Validate token with specific endpoint
            if self.validate_token_with_endpoint(token, random_id):
                # Store user session
                self.user_sessions[user_id] = {
                    "token": token,
                    "random_id": random_id,
                    "username": message.from_user.username or message.from_user.first_name,
                    "login_method": "token"
                }
                
                await message.reply_text(
                    "✅ **Token validation successful!**\n\n"
                    f"🎲 **Random ID:** `{random_id}`\n"
                    "You can now download videos using `/download` or `/link` commands."
                )
            else:
                await message.reply_text(
                    "❌ **Invalid or expired token!**\n\n"
                    "Please get a fresh token from pw.live"
                )

        @self.app.on_message(filters.text & ~filters.command(["start", "help", "login", "token", "download", "link", "quality", "status"]))
        async def handle_otp(client, message: Message):
            user_id = message.from_user.id
            
            # Check if user has pending OTP
            if user_id not in self.pending_otp:
                return
            
            otp = message.text.strip()
            
            # Validate OTP format
            if not otp.isdigit() or len(otp) != 6:
                await message.reply_text(
                    "❌ **Invalid OTP format!**\n\n"
                    "Please enter a 6-digit OTP."
                )
                return
            
            pw_login = self.pending_otp[user_id]
            
            # Verify OTP
            if pw_login.verify_otp(otp):
                # Get access token
                access_token = pw_login.get_access_token()
                random_id = pw_login.random_id
                
                if access_token:
                    # Validate token with specific endpoint
                    if self.validate_token_with_endpoint(access_token, random_id):
                        # Store user session
                        self.user_sessions[user_id] = {
                            "token": access_token,
                            "random_id": random_id,
                            "username": message.from_user.username or message.from_user.first_name,
                            "login_method": "phone",
                            "phone_number": pw_login.phone_number
                        }
                        
                        # Clean up pending OTP
                        del self.pending_otp[user_id]
                        
                        await message.reply_text(
                            "✅ **Login successful!**\n\n"
                            f"📱 **Phone:** {pw_login.phone_number}\n"
                            f"🎲 **Random ID:** `{random_id}`\n"
                            "You can now download videos using `/download` or `/link` commands."
                        )
                    else:
                        await message.reply_text(
                            "❌ **Token validation failed!**\n\n"
                            "The login was successful but token validation failed. Please try again."
                        )
                else:
                    await message.reply_text(
                        "❌ **Failed to extract token!**\n\n"
                        "Login was successful but couldn't extract access token."
                    )
            else:
                await message.reply_text(
                    "❌ **Invalid OTP!**\n\n"
                    "Please check the OTP and try again."
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
                    "Use `/login phone_number` or `/token your_token`",
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
            
            # Parse quality if provided
            if len(parts) > 3:
                try:
                    quality = int(parts[3])
                    if quality not in [240, 360, 480, 720, 1080]:
                        await message.reply_text(
                            "❌ **Invalid quality!**\n\n"
                            "Supported qualities: 240, 360, 480, 720, 1080"
                        )
                        return
                except ValueError:
                    await message.reply_text(
                        "❌ **Invalid quality format!**\n\n"
                        "Quality should be a number (240, 360, 480, 720, 1080)"
                    )
                    return
            
            # Start download
            await self.start_download(message, user_id, video_id, video_name, batch_id, quality)

        @self.app.on_message(filters.command("link"))
        async def link_command(client, message: Message):
            user_id = message.from_user.id
            
            # Check if user is logged in
            if user_id not in self.user_sessions:
                await message.reply_text(
                    "❌ **You need to login first!**\n\n"
                    "Use `/login phone_number` or `/token your_token`"
                )
                return
            
            # Check if user has active download
            if user_id in self.active_downloads:
                await message.reply_text(
                    "⏳ **You already have an active download!**\n\n"
                    "Please wait for it to complete."
                )
                return
            
            # Parse link command
            text = message.text[6:]  # Remove "/link "
            parts = text.split(maxsplit=1)
            
            if len(parts) < 1:
                await message.reply_text(
                    "❌ **Invalid format!**\n\n"
                    "Use: `/link Video Name:mpd_url [quality]`\n\n"
                    "Example:\n"
                    "`/link Kinetic Theory:https://d1d34p8vz63oiq.cloudfront.net/video_id/master.mpd?parentId=batch&childId=video 720`"
                )
                return
            
            link = parts[0]
            quality = None
            
            # Parse quality if provided
            if len(parts) > 1:
                try:
                    quality = int(parts[1])
                    if quality not in [240, 360, 480, 720, 1080]:
                        await message.reply_text(
                            "❌ **Invalid quality!**\n\n"
                            "Supported qualities: 240, 360, 480, 720, 1080"
                        )
                        return
                except ValueError:
                    await message.reply_text(
                        "❌ **Invalid quality format!**\n\n"
                        "Quality should be a number (240, 360, 480, 720, 1080)"
                    )
                    return
            
            # Start download from direct link
            await self.start_download_from_link(message, user_id, link, quality)

        @self.app.on_message(filters.command("quality"))
        async def quality_command(client, message: Message):
            user_id = message.from_user.id
            
            # Check if user is logged in
            if user_id not in self.user_sessions:
                await message.reply_text(
                    "❌ **You need to login first!**\n\n"
                    "Use `/login phone_number` or `/token your_token`"
                )
                return
            
            # Parse quality command
            text = message.text[9:]  # Remove "/quality "
            parts = text.split()
            
            if len(parts) < 1:
                await message.reply_text(
                    "❌ **Invalid format!**\n\n"
                    "Use: `/quality video_id batch_id` or `/quality direct_link`\n\n"
                    "Examples:\n"
                    "`/quality 6854310c752ef68ab0116a71 678b4cf5a3a368218a2b16e7`\n"
                    "`/quality https://d1d34p8vz63oiq.cloudfront.net/video_id/master.mpd`"
                )
                return
            
            await self.check_quality(message, user_id, parts)

        @self.app.on_message(filters.command("status"))
        async def status_command(client, message: Message):
            user_id = message.from_user.id
            
            if user_id not in self.user_sessions:
                await message.reply_text("❌ **You are not logged in!**")
                return
            
            session = self.user_sessions[user_id]
            
            if user_id not in self.active_downloads:
                status_text = f"""
✅ **Logged in successfully**

👤 **User:** {session['username']}
🔑 **Method:** {session['login_method']}
"""
                if session['login_method'] == 'phone':
                    status_text += f"📱 **Phone:** {session.get('phone_number', 'N/A')}\n"
                
                status_text += f"🎲 **Random ID:** `{session['random_id']}`\n\n💡 **No active downloads**"
                
                await message.reply_text(status_text)
                return
            
            download_info = self.active_downloads[user_id]
            status_text = f"""
📊 **Download Status**

📹 **Video:** {download_info['name']}
🆔 **ID:** {download_info['video_id']}
📦 **Batch:** {download_info.get('batch_id', 'Direct Link')}

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
                    "**Method 1:** `/login phone_number`\n"
                    "**Method 2:** `/token your_token_here`\n\n"
                    "Choose the method that works best for you!"
                )

    async def check_quality(self, message: Message, user_id: int, parts: list):
        """Check available qualities for a video"""
        try:
            user_session = self.user_sessions[user_id]
            fetcher = LicenseKeyFetcher(user_session["token"], user_session["random_id"])
            
            if len(parts) == 1 and parts[0].startswith("http"):
                # Direct link
                link = parts[0]
                await message.reply_text("🔍 **Checking qualities for direct link...**")
                
                # Get MPD URL and parse it
                mpd_url, _, _ = fetcher.get_video_url_and_key_from_direct_link(link)
                parser = MPDParser(mpd_url)
                
            elif len(parts) >= 2:
                # Video ID and batch ID
                video_id = parts[0]
                batch_id = parts[1]
                await message.reply_text("🔍 **Checking qualities...**")
                
                # Get video URL and parse MPD
                mpd_url, _, _ = fetcher.get_video_url_and_key(video_id, batch_id)
                parser = MPDParser(mpd_url)
                
            else:
                await message.reply_text(
                    "❌ **Invalid format!**\n\n"
                    "Use: `/quality video_id batch_id` or `/quality direct_link`"
                )
                return
            
            # Get available qualities
            qualities = parser.get_available_qualities()
            
            if qualities:
                quality_text = "🎬 **Available Qualities:**\n\n"
                for q in qualities:
                    quality_text += f"• **{q['height']}p** ({q['label']})\n"
                
                quality_text += "\n💡 Use these values with `/download` or `/link` commands."
                await message.reply_text(quality_text)
            else:
                await message.reply_text("❌ **No video qualities found!**")
                
        except Exception as e:
            await message.reply_text(f"❌ **Error checking qualities:** {str(e)}")

    async def start_download(self, message: Message, user_id: int, video_id: str, video_name: str, batch_id: str, quality: Optional[int]):
        """Start video download process"""
        
        # Store download info
        self.active_downloads[user_id] = {
            "video_id": video_id,
            "name": video_name,
            "batch_id": batch_id,
            "quality": quality,
            "status": "Starting..."
        }
        
        # Send initial status
        quality_text = f" ({quality}p)" if quality else " (auto quality)"
        status_msg = await message.reply_text(
            f"🚀 **Starting download...**\n\n"
            f"📹 **Video:** {video_name}\n"
            f"🆔 **ID:** {video_id}\n"
            f"📦 **Batch:** {batch_id}\n"
            f"🎬 **Quality:** {quality_text}\n\n"
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
                f"🎬 **Quality:** {quality_text}\n\n"
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
                            f"📦 **Batch:** {batch_id}\n"
                            f"🎬 **Quality:** {quality_text}\n\n"
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
                user_session["random_id"],
                quality
            )
            
            # Download completed successfully
            file_size = os.path.getsize(output_file) / (1024 * 1024)  # MB
            
            await status_msg.edit_text(
                f"✅ **Download completed!**\n\n"
                f"📹 **Video:** {video_name}\n"
                f"📁 **File:** {os.path.basename(output_file)}\n"
                f"📊 **Size:** {file_size:.1f} MB\n"
                f"🎬 **Quality:** {quality_text}\n\n"
                f"🎉 **Your video is ready!**"
            )
            
            # Send the video file if it's not too large
            if file_size < 50:  # Telegram limit is 50MB for bots
                try:
                    await message.reply_video(
                        video=output_file,
                        caption=f"🎬 **{video_name}**\n\n📊 Size: {file_size:.1f} MB{quality_text}"
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

    async def start_download_from_link(self, message: Message, user_id: int, link: str, quality: Optional[int]):
        """Start download from direct MPD link"""
        
        try:
            # Parse the link to get name
            if ':' in link:
                name = link.split(':', 1)[0].strip()
            else:
                name = "Video"
            
            # Store download info
            self.active_downloads[user_id] = {
                "video_id": "direct_link",
                "name": name,
                "batch_id": None,
                "quality": quality,
                "status": "Starting..."
            }
            
            # Send initial status
            quality_text = f" ({quality}p)" if quality else " (auto quality)"
            status_msg = await message.reply_text(
                f"🚀 **Starting download from direct link...**\n\n"
                f"📹 **Video:** {name}\n"
                f"🔗 **Source:** Direct MPD Link\n"
                f"🎬 **Quality:** {quality_text}\n\n"
                f"⏳ **Status:** Initializing..."
            )
            
            user_session = self.user_sessions[user_id]
            
            # Update status
            await status_msg.edit_text(
                f"🚀 **Download in progress...**\n\n"
                f"📹 **Video:** {name}\n"
                f"🔗 **Source:** Direct MPD Link\n"
                f"🎬 **Quality:** {quality_text}\n\n"
                f"⏳ **Status:** Parsing link and getting key..."
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
                            f"📹 **Video:** {name}\n"
                            f"🔗 **Source:** Direct MPD Link\n"
                            f"🎬 **Quality:** {quality_text}\n\n"
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
                self.downloader.download_from_direct_link,
                link,
                user_session["token"],
                user_session["random_id"],
                quality
            )
            
            # Download completed successfully
            file_size = os.path.getsize(output_file) / (1024 * 1024)  # MB
            
            await status_msg.edit_text(
                f"✅ **Download completed!**\n\n"
                f"📹 **Video:** {name}\n"
                f"📁 **File:** {os.path.basename(output_file)}\n"
                f"📊 **Size:** {file_size:.1f} MB\n"
                f"🎬 **Quality:** {quality_text}\n\n"
                f"🎉 **Your video is ready!**"
            )
            
            # Send the video file if it's not too large
            if file_size < 50:  # Telegram limit is 50MB for bots
                try:
                    await message.reply_video(
                        video=output_file,
                        caption=f"🎬 **{name}**\n\n📊 Size: {file_size:.1f} MB{quality_text}"
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
                f"📹 **Video:** {name}\n"
                f"🔗 **Source:** Direct MPD Link\n\n"
                f"💥 **Error:** {str(e)}"
            )
        except Exception as e:
            await status_msg.edit_text(
                f"❌ **Unexpected error!**\n\n"
                f"📹 **Video:** {name}\n"
                f"🔗 **Source:** Direct MPD Link\n\n"
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
        print("📱 Phone-based login system enabled")
        print("🔧 Using mainLogic components for downloading")
        
        # Create download directory
        Path(config.DOWNLOAD_DIR).mkdir(parents=True, exist_ok=True)
        
        self.app.run()

if __name__ == "__main__":
    bot = PWDownloadBot()
    bot.run()