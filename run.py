#!/usr/bin/env python3
"""
Simple runner script for the PW Downloader Bot
"""

import os
import sys
from pathlib import Path

# Add current directory to Python path
sys.path.insert(0, str(Path(__file__).parent))

def check_dependencies():
    """Check if required dependencies are available"""
    try:
        import pyrogram
        import requests
        import tqdm
        print("✅ Python dependencies are installed")
    except ImportError as e:
        print(f"❌ Missing Python dependency: {e}")
        print("Run: pip install -r requirements.txt")
        return False
    
    # Check for external tools
    tools_found = True
    
    # Check for mp4decrypt
    mp4decrypt_paths = [
        "mp4decrypt",
        "./bin/mp4decrypt",
        "/usr/local/bin/mp4decrypt"
    ]
    
    mp4decrypt_found = False
    for path in mp4decrypt_paths:
        if os.system(f"{path} --version > /dev/null 2>&1") == 0:
            mp4decrypt_found = True
            print(f"✅ mp4decrypt found at: {path}")
            break
    
    if not mp4decrypt_found:
        print("❌ mp4decrypt not found")
        print("Please install mp4decrypt from Bento4 releases")
        tools_found = False
    
    # Check for ffmpeg
    if os.system("ffmpeg -version > /dev/null 2>&1") == 0:
        print("✅ ffmpeg found")
    else:
        print("❌ ffmpeg not found")
        print("Please install ffmpeg")
        tools_found = False
    
    return tools_found

def check_config():
    """Check if configuration is properly set"""
    if not os.path.exists(".env"):
        print("❌ .env file not found")
        print("Copy .env.example to .env and fill in your credentials")
        return False
    
    # Load environment variables
    from dotenv import load_dotenv
    load_dotenv()
    
    required_vars = ["BOT_TOKEN", "API_ID", "API_HASH"]
    missing_vars = []
    
    for var in required_vars:
        if not os.getenv(var):
            missing_vars.append(var)
    
    if missing_vars:
        print(f"❌ Missing environment variables: {', '.join(missing_vars)}")
        print("Please fill in your .env file")
        return False
    
    print("✅ Configuration is valid")
    return True

def main():
    """Main runner function"""
    print("🤖 PW Downloader Bot - Starting...")
    print("=" * 50)
    
    # Check dependencies
    if not check_dependencies():
        print("\n❌ Dependency check failed")
        sys.exit(1)
    
    # Check configuration
    try:
        if not check_config():
            print("\n❌ Configuration check failed")
            sys.exit(1)
    except ImportError:
        print("❌ python-dotenv not installed")
        print("Run: pip install python-dotenv")
        sys.exit(1)
    
    print("\n✅ All checks passed!")
    print("🚀 Starting bot...")
    print("=" * 50)
    
    # Start the bot
    try:
        from bot import PWDownloadBot
        bot = PWDownloadBot()
        bot.run()
    except KeyboardInterrupt:
        print("\n👋 Bot stopped by user")
    except Exception as e:
        print(f"\n❌ Bot crashed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()