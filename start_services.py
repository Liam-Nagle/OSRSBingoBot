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
    """Run Discord Bot"""
    # Wait a bit for API to start
    time.sleep(5)
    print("🤖 Starting Discord Bot...")
    subprocess.run([sys.executable, "DinkParser.py"])


if __name__ == "__main__":
    print("=" * 60)
    print("🎮 OSRS Bingo - Starting All Services")
    print("=" * 60)

    # Start Flask API in background thread
    api_thread = Thread(target=run_api, daemon=True)
    api_thread.start()

    # Run Discord bot in main thread (keeps process alive)
    run_bot()