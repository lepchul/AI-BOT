"""Run interactively once. Never run concurrently with main.py."""
import asyncio
import os
from telethon import TelegramClient, connection
from telethon.sessions import StringSession
from pathlib import Path
from config import telegram_credentials,SESSION,DATA
from instance import single_instance
async def main():
    api_id,api_hash=telegram_credentials()
    secret = input("Вставь секрет прокси: ").strip()
    client = TelegramClient(
        SESSION,
        api_id,
        api_hash,
        connection=connection.ConnectionTcpMTProxyRandomizedIntermediate,
        proxy=("127.0.0.1", 1080, secret),
    )
    try:
        await client.start()
        me=await client.get_me()
        print('Вход выполнен. ID аккаунта:',me.id)
        session_path=Path(__file__).resolve().parent/'session_string.txt'
        fd=os.open(session_path,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
        with os.fdopen(fd,'w',encoding='utf-8') as out:out.write(StringSession.save(client.session))
        print('Строка сессии сохранена в session_string.txt. Не загружай этот файл на GitHub.')
        print('Группы, в которые аккаунт уже добавлен:')
        async for d in client.iter_dialogs():
            if d.is_group:print(d.id,d.name)
    finally:await client.disconnect()
    try:os.chmod(SESSION+'.session',0o600)
    except OSError:pass
    print('Сессия сохранена в data/account.session. Впиши ID групп в .env и запускай main.py.')
if __name__=='__main__':
    with single_instance(DATA/'runtime.lockdb'):asyncio.run(main())
