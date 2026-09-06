"""Generate a fresh TELEGRAM_SESSION_STRING for Railway.

Run locally:  python3 generate_session.py

Telegram sends a login code to the phone you enter; type it at the prompt.
Copy the printed string into Railway → svetliyparser → Variables →
TELEGRAM_SESSION_STRING. Saving that variable triggers exactly one redeploy —
do not touch anything else afterwards.

The account whose session this is must not be signed in anywhere else: every
extra login (phone, desktop) revokes the key this script just made.
"""
from telethon.sync import TelegramClient
from telethon.sessions import StringSession

API_ID = int(input("TELEGRAM_API_ID (число, из Railway → Variables): ").strip())
API_HASH = input("TELEGRAM_API_HASH (из Railway → Variables): ").strip()
PHONE = input("Телефон юзербота (например +79930910730): ").strip()

# Deliberately not the `with` form: its __enter__ calls start() with no
# arguments and prompts for the phone number all over again.
client = TelegramClient(StringSession(), API_ID, API_HASH)
client.start(phone=PHONE)
try:
    print("\n" + "=" * 70)
    print("TELEGRAM_SESSION_STRING — скопируй строку целиком:\n")
    print(client.session.save())
    print("=" * 70)
finally:
    # Disconnect, never log_out(): logging out would revoke the key we just made.
    client.disconnect()
