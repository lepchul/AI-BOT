import asyncio
import os
import logging
import random
import time
from datetime import datetime
from telethon import TelegramClient,events,errors
from telethon.sessions import StringSession
from config import Config,DATA,SESSION,ROOT
from storage import Store
from instance import single_instance
from brain import Brain,prompt,mentioned,quiet

LOG=logging.getLogger('chat_ai')
HELP='''Управление в Избранном этого аккаунта или в ЛС от OWNER_ID:
!ai status
!ai pause CHAT_ID
!ai resume CHAT_ID
!ai remember CHAT_ID текст шутки и её смысл
!ai memories CHAT_ID
!ai forget CHAT_ID ID_ЗАПИСИ
!ai nick CHAT_ID USER_ID прозвище
!ai clear CHAT_ID CONFIRM
!ai announce CHAT_ID
!ai help
В группе участник может написать /ai_forgetme или /ai_allowme.
Частота и модель задаются в .env, характер - personality.txt. После изменения перезапусти программу.'''
NOTICE='Я ИИ-участник чата. Использую последние сообщения для ответов через внешний API-провайдер (по умолчанию Dark API); локальный контекст хранится до установленного срока. Владелец может сохранять шутки и прозвища в память. /ai_forgetme удаляет твой локальный контекст и исключает новые сообщения из обработки, /ai_allowme включает обратно.'

async def run():
    cfg=Config();db=Store(DATA/'memory.sqlite3');db.cleanup(cfg.days)
    brain=Brain(cfg.key,cfg.model,cfg.base_url)
    session_value=os.getenv("SESSION_STRING", "").strip()
    session=StringSession(session_value) if session_value else SESSION
    client=TelegramClient(session,cfg.api_id,cfg.api_hash,flood_sleep_threshold=0,catch_up=False)
    await client.connect()
    if not await client.is_user_authorized():
        await client.disconnect();await brain.close()
        raise ValueError('Сначала выполни python login.py в интерактивном терминале.')
    me=await client.get_me();owner=cfg.owner or me.id
    locks={cid:asyncio.Lock() for cid in cfg.chats}
    api_lock=asyncio.Lock();started=time.time();flood_until=0.0
    # Populate access hashes before resolving numeric group IDs.
    await client.get_dialogs()
    for cid in cfg.chats:
        await client.get_input_entity(cid)
    LOG.info('Запущен. Разрешённых групп: %d. Команды: !ai help в Избранном.',len(cfg.chats))

    @client.on(events.NewMessage())
    async def command(event):
        nonlocal flood_until
        if not event.is_private or not (event.raw_text or '').startswith('!ai '):return
        is_saved=event.out and event.chat_id==me.id
        is_owner=not event.out and event.sender_id==owner
        if not (is_saved or is_owner):return
        if time.time()<flood_until:return
        try:
            bits=event.raw_text.split(maxsplit=3);action=bits[1]
            if action=='help':result=HELP
            elif action=='status':
                result='Группы:\n'+'\n'.join(f'{cid}: '+('пауза' if db.paused(cid) else 'работает') for cid in cfg.chats)+f'\nМодель: {cfg.model}\nЛимит API: {cfg.limit}/сутки'
            else:
                cid=int(bits[2])
                if cid not in cfg.chats:raise ValueError('Чат не входит в ALLOWED_CHAT_IDS')
                rest=bits[3] if len(bits)>3 else ''
                if action in ('pause','resume'):db.pause(cid,action=='pause');result='Готово.'
                elif action=='remember':result='Сохранено, ID '+str(db.remember(cid,rest))
                elif action=='memories':result='\n'.join(f"{x['id']}: {x['text']}" for x in db.snapshot(cid,1)['memories']) or 'Пусто.'
                elif action=='forget':db.delete_memory(cid,int(rest));result='Удалено.'
                elif action=='nick':
                    uid,name=rest.split(maxsplit=1);db.nickname(cid,int(uid),name);result='Прозвище сохранено только в памяти ИИ.'
                elif action=='clear' and rest=='CONFIRM':db.clear(cid);result='Контекст, шутки и прозвища этого чата удалены.'
                elif action=='announce':
                    await client.send_message(cid,NOTICE,parse_mode=None);result='Объявление отправлено.'
                else:raise ValueError('Неизвестная команда. !ai help')
            # Split long memory lists without exposing them to the public chat.
            for start in range(0,len(result),3000):await event.reply(result[start:start+3000],parse_mode=None)
        except errors.FloodWaitError as exc:
            flood_until=time.time()+exc.seconds+1;LOG.warning('Telegram FloodWait: %s секунд',exc.seconds)
        except (ValueError,IndexError):await event.reply('Проверь аргументы команды. !ai help',parse_mode=None)
        except Exception as exc:LOG.warning('Команда не выполнена: %s',type(exc).__name__)

    @client.on(events.NewMessage(incoming=True))
    async def incoming(event):
        nonlocal flood_until
        cid=event.chat_id
        if cid not in cfg.chats or not event.is_group:return
        if event.date.timestamp()<started-5:return
        text=(event.raw_text or '').strip()
        if not text or not event.sender_id:return
        try:
            sender=await event.get_sender()
            if not sender or getattr(sender,'bot',False) or not getattr(sender,'first_name',None):return
            uid=event.sender_id
            if text in ('/ai_forgetme','/ai_allowme'):
                if text=='/ai_forgetme':db.forget_user(cid,uid)
                else:db.resume_user(cid,uid)
                # Silent to avoid turning this command into a spam echo.
                return
            if text.startswith('/') or db.paused(cid) or db.opted_out(cid,uid):return
            db.cleanup(cfg.days)
            db.add(cid,event.id,uid,sender.first_name,text)
            if time.time()<flood_until or locks[cid].locked():return
            direct=mentioned(text,cfg.triggers,me.username or '')
            if event.is_reply:
                replied=await event.get_reply_message()
                direct=direct or bool(replied and replied.sender_id==me.id)
            now=datetime.now(cfg.tz)
            if not direct and (quiet(now.hour,cfg.quiet_start,cfg.quiet_end) or random.random()>=cfg.chance):return
            async with locks[cid]:
                if not db.reserve(cid,now.date().isoformat(),cfg.interval,cfg.limit):return
                # Global serialisation avoids bursts against the API across groups.
                async with api_lock:
                    if db.paused(cid) or db.opted_out(cid,uid):return
                    context=db.snapshot(cid,cfg.context)
                    revision=[x['id'] for x in context['memories']]
                    style=(ROOT/'personality.txt').read_text(encoding='utf-8')[:2500]
                    answer=await brain.reply(prompt(cfg.name,style,context,direct))
                if not answer or db.paused(cid) or db.opted_out(cid,uid) or time.time()<flood_until:return
                # Discard a response if history was cleared while the API was running.
                current=db.snapshot(cid,cfg.context)
                if not any(x['mid']==event.id for x in current['messages']):return
                if revision!=[x['id'] for x in current['memories']]:return
                sent=await event.reply(answer,parse_mode=None,link_preview=False)
                db.add(cid,sent.id,me.id,cfg.name,answer)
        except errors.FloodWaitError as exc:
            flood_until=time.time()+exc.seconds+1;LOG.warning('Telegram FloodWait: %s секунд',exc.seconds)
        except Exception as exc:
            # Avoid logging keys, request bodies or other people's messages.
            LOG.warning('Ответ пропущен: %s%s',type(exc).__name__,(' '+str(exc)) if type(exc) is RuntimeError and str(exc).startswith('AI HTTP ') else '')

    async def cleanup_loop():
        while True:
            await asyncio.sleep(3600);db.cleanup(cfg.days)
    task=asyncio.create_task(cleanup_loop())
    try:await client.run_until_disconnected()
    finally:
        task.cancel()
        await asyncio.gather(task,return_exceptions=True)
        await brain.close();await client.disconnect()
if __name__=='__main__':
    logging.basicConfig(level=logging.INFO,format='%(asctime)s %(name)s %(levelname)s %(message)s')
    logging.getLogger('telethon').setLevel(logging.WARNING)
    logging.getLogger('httpx').setLevel(logging.WARNING)
    try:
        with single_instance(DATA/'runtime.lockdb'):asyncio.run(run())
    except KeyboardInterrupt:pass
    except ValueError as exc:print('Ошибка настройки:',exc)
