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

# Import mainLogic components
from mainLogic.big4.Ravenclaw_decrypt.key import LicenseKeyFetcher
from mainLogic.startup.Login.sudat import Login
from mainLogic.main import Main
from mainLogic.startup.checkup import CheckState
from mainLogic.utils import glv_var
from mainLogic.error import TokenInvalid
from mainLogic.utils.gen_utils import generate_safe_folder_name
from mainLogic.utils.glv_var import debugger

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
        
        # Store user sessions and download progress
        self.user_sessions: Dict[int, Dict] = {}
        self.active_downloads: Dict[int, Dict] = {}
        
        # Store pending OTP verifications
        self.pending_otp: Dict[int, Login] = {}
        
        # Initialize checkup for dependencies
        self.check_state = CheckState()
        
        self.setup_handlers()

    def validate_token_with_mainlogic(self, token: str, random_id: str) -> bool:
        """Validate token using mainLogic's CheckState"""
        try:
            logger.info(f"Validating token with mainLogic CheckState")
            
            # Set up the token structure exactly like your CLI does
            token_config = {
                "access_token": token,
                "token": token,
                "random_id": random_id,
                "randomId": random_id
            }
            
            # Set up glv_var.vars['prefs'] with the token - this is crucial!
            if 'prefs' not in glv_var.vars:
                glv_var.vars['prefs'] = {}
            
            # Set the token in the format mainLogic expects
            glv_var.vars['prefs']['token'] = token_config
            
            try:
                # Use CheckState to validate token like your CLI does
                state = self.check_state.checkup(
                    glv_var.EXECUTABLES,
                    directory="./",
                    verbose=False,
                    do_raise=True
                )
                
                # If we get here, token is valid
                logger.info("Token validation successful with mainLogic CheckState")
                return True
                
            except TokenInvalid:
                logger.warning("Token validation failed - TokenInvalid exception")
                return False
            except Exception as e:
                logger.error(f"Token validation failed with exception: {str(e)}")
                return False
                
        except Exception as e:
            logger.error(f"Error in mainLogic token validation: {str(e)}")
            return False

    def validate_token_with_endpoint(self, token: str, random_id: str) -> bool:
        """Validate token using the specific PW endpoint as fallback"""
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

This bot downloads videos from PhysicsWallah using your token, exactly like the CLI tool.

**Commands:**
/login - Login with phone number (OTP-based)
/token - Set your PW token directly
/download - Download a video using IDs
/link - Download from direct MPD link
/status - Check your login status
/help - Show this help message

**Quick Start:**
1. Use `/login phone_number` for OTP-based login
2. Or use `/token your_token_here` to set token directly
3. Then use `/download` or `/link` to download videos

**Example:**
`/download 6854310c752ef68ab0116a71 "aniknew" 678b4cf5a3a368218a2b16e7`
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
• `/download video_id "video_name" batch_id`
• `/link Video Name:mpd_url`

**Examples:**
`/download 6854310c752ef68ab0116a71 "aniknew" 678b4cf5a3a368218a2b16e7`
`/link Kinetic Theory:https://d1d34p8vz63oiq.cloudfront.net/video_id/master.mpd?parentId=batch&childId=video`

**Note:** This bot uses the same mainLogic components as the CLI tool!
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
            
            # Initialize login process using mainLogic Login class
            pw_login = Login(phone_number)
            
            # Send OTP
            if pw_login.gen_otp():
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
            
            # Validate token with mainLogic first, then fallback to endpoint
            token_valid = self.validate_token_with_mainlogic(token, random_id)
            if not token_valid:
                logger.info("MainLogic validation failed, trying endpoint validation")
                token_valid = self.validate_token_with_endpoint(token, random_id)
            
            if token_valid:
                # Store user session with the exact token structure mainLogic needs
                token_config = {
                    "access_token": token,
                    "token": token,
                    "random_id": random_id,
                    "randomId": random_id
                }
                
                self.user_sessions[user_id] = {
                    "token_config": token_config,  # Store the full config
                    "token": token,  # Also store raw token for compatibility
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

        @self.app.on_message(filters.text & ~filters.command(["start", "help", "login", "token", "download", "link", "status"]))
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
            
            # Verify OTP using mainLogic Login class
            if pw_login.login(otp):
                # Get token data
                token_data = pw_login.token
                
                if token_data:
                    # Extract access token and random ID
                    access_token = token_data.get('access_token') or token_data.get('token')
                    random_id = str(uuid.uuid4())  # Generate new random ID
                    
                    if access_token:
                        # Create the token config structure that mainLogic expects
                        token_config = {
                            "access_token": access_token,
                            "token": access_token,
                            "random_id": random_id,
                            "randomId": random_id
                        }
                        
                        # Validate token with mainLogic first, then fallback to endpoint
                        token_valid = self.validate_token_with_mainlogic(access_token, random_id)
                        if not token_valid:
                            logger.info("MainLogic validation failed, trying endpoint validation")
                            token_valid = self.validate_token_with_endpoint(access_token, random_id)
                        
                        if token_valid:
                            # Store user session with the exact token structure mainLogic needs
                            self.user_sessions[user_id] = {
                                "token_config": token_config,  # Store the full config
                                "token": access_token,  # Also store raw token for compatibility
                                "random_id": random_id,
                                "username": message.from_user.username or message.from_user.first_name,
                                "login_method": "phone",
                                "phone_number": pw_login.username
                            }
                            
                            # Clean up pending OTP
                            del self.pending_otp[user_id]
                            
                            await message.reply_text(
                                "✅ **Login successful!**\n\n"
                                f"📱 **Phone:** {pw_login.username}\n"
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
                        "❌ **No token data received!**\n\n"
                        "Login was successful but no token data was returned."
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
                    "Use: `/download video_id \"video_name\" batch_id`\n\n"
                    "Example:\n"
                    "`/download 6854310c752ef68ab0116a71 \"aniknew\" 678b4cf5a3a368218a2b16e7`"
                )
                return
            
            video_id = parts[0]
            video_name = parts[1]
            batch_id = parts[2]
            
            # Start download
            await self.start_download(message, user_id, video_id, video_name, batch_id)

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
            
            if not text.strip():
                await message.reply_text(
                    "❌ **Invalid format!**\n\n"
                    "Use: `/link Video Name:mpd_url`\n\n"
                    "Example:\n"
                    "`/link aniknew:https://d1d34p8vz63oiq.cloudfront.net/c3905743-cd7e-49d7-b472-4a8f11444beb/master.mpd?parentId=63fc53f28aac0a001871320d&childId=6583cf6da25635465b7e6430`"
                )
                return
            
            link = text.strip()
            
            # Start download from direct link
            await self.start_download_from_link(message, user_id, link)

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

    async def start_download(self, message: Message, user_id: int, video_id: str, video_name: str, batch_id: str):
        """Start video download process using mainLogic Main class"""
        
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
            f"⏳ **Status:** Initializing mainLogic components..."
        )
        
        try:
            user_session = self.user_sessions[user_id]
            
            # Update status
            await status_msg.edit_text(
                f"🚀 **Download in progress...**\n\n"
                f"📹 **Video:** {video_name}\n"
                f"🆔 **ID:** {video_id}\n"
                f"📦 **Batch:** {batch_id}\n\n"
                f"⏳ **Status:** Setting up dependencies..."
            )
            
            # Create safe folder name
            safe_name = generate_safe_folder_name(video_name)
            
            # Create download directory for this user
            user_download_dir = os.path.join(config.DOWNLOAD_DIR, str(user_id))
            os.makedirs(user_download_dir, exist_ok=True)
            
            # Create progress callback
            async def progress_callback(progress_info):
                try:
                    progress_str = progress_info.get('str', 'Processing...')
                    progress_val = progress_info.get('progress', 0)
                    
                    status_text = f"⬬ **Progress:** {progress_val:.1f}% - {progress_str}"
                    self.active_downloads[user_id]['status'] = status_text
                    
                    # Update message periodically to avoid rate limits
                    if progress_val % 20 == 0 or progress_val >= 99:
                        await status_msg.edit_text(
                            f"🚀 **Download in progress...**\n\n"
                            f"📹 **Video:** {video_name}\n"
                            f"🆔 **ID:** {video_id}\n"
                            f"📦 **Batch:** {batch_id}\n\n"
                            f"⏳ **Status:** {status_text}"
                        )
                except Exception:
                    pass  # Ignore update errors
            
            # Start download using mainLogic Main class
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                self._run_main_download,
                video_id,
                safe_name,
                batch_id,
                user_download_dir,
                user_session["token_config"],  # Pass the full token config
                progress_callback
            )
            
            # Find the downloaded file
            output_file = os.path.join(user_download_dir, f"{safe_name}.mp4")
            
            if os.path.exists(output_file):
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
            else:
                await status_msg.edit_text(
                    f"❌ **Download failed!**\n\n"
                    f"📹 **Video:** {video_name}\n"
                    f"🆔 **ID:** {video_id}\n\n"
                    f"💥 **Error:** Output file not found"
                )
            
        except TokenInvalid:
            await status_msg.edit_text(
                f"❌ **Download failed!**\n\n"
                f"📹 **Video:** {video_name}\n"
                f"🆔 **ID:** {video_id}\n\n"
                f"💥 **Error:** Invalid token. Please login again."
            )
        except Exception as e:
            logger.error(f"Download failed: {str(e)}")
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

    def _run_main_download(self, video_id, name, batch_id, directory, token_config, progress_callback):
        """Run the main download using mainLogic Main class - exactly like CLI"""
        try:
            logger.info(f"Starting mainLogic download for video_id: {video_id}, batch_id: {batch_id}")
            
            # Set up glv_var.vars['prefs'] exactly like your CLI does
            glv_var.vars['prefs'] = {
                'token': token_config,  # Use the full token config
                'dir': directory,
                'tmpDir': './tmp/'
            }
            
            # Setup dependencies using CheckState like your CLI
            state = self.check_state.checkup(
                glv_var.EXECUTABLES,
                directory=directory,
                verbose=True,  # Enable verbose like your CLI --verbose flag
                do_raise=True
            )
            
            logger.info("Dependencies checked successfully")
            
            # Create Main instance exactly like your CLI does
            main_instance = Main(
                id=video_id,
                name=name,
                batch_name=batch_id,
                topic_name=None,  # Not used in your CLI command
                lecture_url=None,  # Not used in your CLI command
                directory=directory,
                tmpDir=state.get('tmpDir', './tmp/'),
                ffmpeg=state['ffmpeg'],
                mp4d=state['mp4decrypt'],
                token=state['prefs']['token'],  # Use the token from state
                random_id=state['prefs']['random_id'],  # Use the random_id from state
                verbose=True,  # Enable verbose like your CLI --verbose flag
                progress_callback=progress_callback
            )
            
            logger.info("Main instance created, starting process...")
            
            # Process the download exactly like your CLI
            main_instance.process()
            logger.info("MainLogic download completed successfully")
            
        except Exception as e:
            logger.error(f"Main download failed: {str(e)}")
            debugger.error(f"Main download failed: {str(e)}")
            raise

    async def start_download_from_link(self, message: Message, user_id: int, link: str):
        """Start download from direct MPD link using mainLogic"""
        
        try:
            # Parse the link to get name and extract video/batch IDs
            if ':' in link:
                name, mpd_url = link.split(':', 1)
                name = name.strip()
                mpd_url = mpd_url.strip()
            else:
                mpd_url = link.strip()
                name = "Video"
            
            # Parse MPD URL to extract parentId and childId
            from urllib.parse import urlparse, parse_qs
            parsed_url = urlparse(mpd_url)
            query_params = parse_qs(parsed_url.query)
            
            parent_id = query_params.get('parentId', [None])[0]
            child_id = query_params.get('childId', [None])[0]
            
            if not parent_id or not child_id:
                await message.reply_text(
                    "❌ **Invalid MPD link!**\n\n"
                    "Could not extract parentId or childId from the URL."
                )
                return
            
            logger.info(f"Parsed - Name: {name}, Parent ID: {parent_id}, Child ID: {child_id}")
            
            # Use the regular download method with extracted IDs
            await self.start_download(message, user_id, child_id, name, parent_id)
            
        except Exception as e:
            logger.error(f"Link parsing failed: {str(e)}")
            await message.reply_text(
                f"❌ **Failed to parse link!**\n\n"
                f"💥 **Error:** {str(e)}"
            )

    def run(self):
        """Start the bot"""
        print("🤖 Starting PW Downloader Bot...")
        print(f"📁 Download directory: {config.DOWNLOAD_DIR}")
        print("📱 Phone-based login system enabled")
        print("🔧 Using mainLogic components for downloading")
        print("⚡ Same processing pipeline as CLI tool")
        
        # Create download directory
        Path(config.DOWNLOAD_DIR).mkdir(parents=True, exist_ok=True)
        
        self.app.run()

if __name__ == "__main__":
    bot = PWDownloadBot()
    bot.run()