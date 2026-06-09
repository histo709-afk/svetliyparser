# Светлый Парсер — Telegram Channel Sync Bot

Бот для автоматической пересылки сообщений из исходных Telegram-каналов в целевые каналы.

## Требования

- Docker и Docker Compose
- Аккаунт Telegram
- Бот, созданный через @BotFather

## Установка и запуск

### Шаг 1: Получить токен бота

1. Напишите @BotFather в Telegram
2. Отправьте `/newbot` и следуйте инструкциям
3. Скопируйте токен вида `123456:ABC-DEF...`

### Шаг 2: Получить API_ID и API_HASH

1. Перейдите на https://my.telegram.org
2. Войдите в аккаунт с номером телефона
3. Нажмите «API development tools»
4. Создайте новое приложение (название и платформа — любые)
5. Скопируйте `App api_id` и `App api_hash`

### Шаг 3: Клонировать репозиторий

```bash
git clone <url-репозитория>
cd svetliyparser
```

### Шаг 4: Настроить конфигурацию

```bash
cp .env.example .env
```

Откройте файл `.env` и заполните все значения:

```
BOT_TOKEN=токен_от_BotFather
ADMIN_IDS=ваш_telegram_id  # Узнайте у @userinfobot
TELEGRAM_API_ID=ваш_api_id
TELEGRAM_API_HASH=ваш_api_hash
TELEGRAM_PHONE=+79001234567  # Ваш номер телефона
DATABASE_URL=postgresql+asyncpg://postgres:postgres@postgres:5432/svetliyparser
REDIS_URL=redis://redis:6379/0
SESSION_NAME=userbot
LOG_LEVEL=INFO
```

### Шаг 5: Запустить

```bash
docker compose up -d
```

### Шаг 6: Авторизация Telethon (первый запуск)

При первом запуске боту нужно авторизоваться в Telegram через ваш аккаунт:

```bash
docker compose logs -f app
```

В логах появится запрос кода подтверждения. Введите его:

```bash
docker compose exec app python -c "
import asyncio
from telethon import TelegramClient
from app.config import settings

async def auth():
    client = TelegramClient('sessions/' + settings.SESSION_NAME, settings.TELEGRAM_API_ID, settings.TELEGRAM_API_HASH)
    await client.start(phone=settings.TELEGRAM_PHONE)
    print('Авторизация успешна!')
    await client.disconnect()

asyncio.run(auth())
"
```

После успешной авторизации файл сессии сохранится в папке `sessions/` и перезапуски не потребуют повторной авторизации.

Перезапустите приложение:
```bash
docker compose restart app
```

## Использование бота

1. Откройте бота в Telegram и отправьте `/start`
2. Добавьте исходный канал командой `/addsource` или просто отправьте ссылку на канал
3. Добавьте целевой канал командой `/adddest`
4. Свяжите исходный канал с целевым — бот предложит выбор
5. Просмотрите активные маршруты командой `/routes`
6. Статистика доступна по команде `/status`

## Команды

| Команда | Описание |
|---------|----------|
| `/start` | Главное меню |
| `/addsource` | Добавить исходный канал |
| `/adddest` | Добавить целевой канал |
| `/routes` | Показать все маршруты пересылки |
| `/status` | Статистика синхронизации |
| `/logs` | Последние ошибки |
| `/cancel` | Отменить текущее действие |

## Форматы ссылок на каналы

Бот принимает ссылки в любом формате:
- `https://t.me/channel_name`
- `t.me/channel_name`
- `@channel_name`
- `channel_name`

## Важные замечания

- Бот должен быть **администратором** в целевых каналах с правом публикации
- Userbot-аккаунт должен быть **подписчиком** исходных каналов
- Сессия Telethon хранится в папке `sessions/` — не удаляйте её
