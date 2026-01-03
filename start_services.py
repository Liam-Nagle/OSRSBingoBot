import os
import subprocess
import sys
import time
from threading import Thread


def run_api():
    """Run Flask API"""
    print("🚀 Starting Flask API...")
    subprocess.run([sys.executable, "bingo_api.py"])


if __name__ == "__main__":
    print("=" * 60)
    print("🎮 OSRS Bingo - Starting Services")
    print("=" * 60)
    print("⚠️  Discord bot DISABLED temporarily to avoid rate limits")
    print("=" * 60)

    # Only start the API - no Discord bot
    run_api()