import os
import subprocess
import sys
import time
from threading import Thread


def run_api():
    """Run Flask API"""
    print("🚀 Starting Flask API...")
    subprocess.run([sys.executable, "bingo_api.py"])


def run_bot():
    """Run Discord Bot with retry logic"""
    while True:
        try:
            time.sleep(5)  # Wait 5 seconds before starting bot
            print("🤖 Starting Discord Bot...")
            subprocess.run([sys.executable, "DinkParser.py"])
        except Exception as e:
            print(f"⚠️ Discord bot crashed: {e}")

        # If bot exits/crashes, wait before retrying
        print("⏳ Discord bot exited. Waiting 60 seconds before retry...")
        time.sleep(60)  # Wait 1 minute before retrying


if __name__ == "__main__":
    print("=" * 60)
    print("🎮 OSRS Bingo - Starting All Services")
    print("=" * 60)

    # Start Flask API in background thread
    api_thread = Thread(target=run_api, daemon=True)
    api_thread.start()

    # Start Discord bot in background thread (with retry)
    bot_thread = Thread(target=run_bot, daemon=True)
    bot_thread.start()

    # Keep main thread alive
    print("✅ Both services started. API will stay running even if bot fails.")
    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        print("\n👋 Shutting down...")