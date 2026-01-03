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
    """Run Discord Bot with rate limit protection"""
    attempt = 0

    while True:
        attempt += 1

        # First attempt: immediate start
        # Subsequent attempts: wait 5 minutes
        if attempt > 1:
            wait_time = 300  # 5 minutes
            print(f"⏳ Waiting {wait_time} seconds before retry attempt {attempt}...")
            time.sleep(wait_time)
        else:
            time.sleep(5)  # Initial 5 second delay

        try:
            print(f"🤖 Starting Discord Bot (attempt {attempt})...")
            result = subprocess.run([sys.executable, "DinkParser.py"])

            # If bot exits cleanly (no error), don't restart
            if result.returncode == 0:
                print("✅ Discord bot exited cleanly")
                break

        except KeyboardInterrupt:
            print("\n👋 Bot shutdown requested")
            break
        except Exception as e:
            print(f"⚠️ Discord bot error: {e}")


if __name__ == "__main__":
    print("=" * 60)
    print("🎮 OSRS Bingo - Starting All Services")
    print("=" * 60)

    # Start Flask API in background thread
    api_thread = Thread(target=run_api, daemon=True)
    api_thread.start()

    # Start Discord bot in background thread
    bot_thread = Thread(target=run_bot, daemon=True)
    bot_thread.start()

    # Keep main thread alive
    print("✅ Services started")
    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        print("\n👋 Shutting down...")