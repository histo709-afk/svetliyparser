"""Run this script once locally to generate TELEGRAM_SESSION_STRING for Railway."""
from telethon.sync import TelegramClient
from telethon.sessions import StringSession

API_ID = int(input("Enter TELEGRAM_API_ID: "))
API_HASH = input("Enter TELEGRAM_API_HASH: ")
PHONE = input("Enter phone number (e.g. +79001234567): ")

with TelegramClient(StringSession(), API_ID, API_HASH) as client:
    client.start(phone=PHONE)
    print("\n✅ Session string (copy this to Railway env vars as TELEGRAM_SESSION_STRING):")
    print(client.session.save())
