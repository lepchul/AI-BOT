"""Safe stage diagnostics: never log provider bodies, prompts, keys or URLs."""
import logging
import re
import time

LOG=logging.getLogger('chat_ai')
NOTICE='сейчас не получается получить ответ от сервиса. попробуй чуть позже'

class APIFailure(RuntimeError):
    def __init__(self,stage,code):
        self.stage=stage
        self.code=code
        super().__init__(f'{stage}: {code}')

def safe_code(exc):
    if type(exc) is RuntimeError:
        match=re.fullmatch(r'AI HTTP ([1-5][0-9]{2})',str(exc))
        if match:return 'HTTP '+match[1]
    kind=type(exc).__name__
    if 'Timeout' in kind:return 'TIMEOUT'
    if kind in ('ConnectError','ReadError','WriteError','RemoteProtocolError','NetworkError'):return 'NETWORK'
    if kind in ('JSONDecodeError','KeyError','IndexError','TypeError','ValueError','RuntimeError'):return 'INVALID_RESPONSE'
    return 'REQUEST_FAILED'

async def api_call(stage,operation,chat_id):
    started=time.monotonic()
    try:
        result=await operation()
    except Exception as exc:
        code=safe_code(exc)
        LOG.warning('API сбой: этап=%s чат=%s ошибка=%s время=%.1fс',stage,chat_id,code,time.monotonic()-started)
        raise APIFailure(stage,code) from None
    LOG.info('API выполнен: этап=%s чат=%s время=%.1fс',stage,chat_id,time.monotonic()-started)
    return result

class Notices:
    def __init__(self,interval=60):
        self.interval=interval
        self.last={}
    async def send(self,event,direct,permitted):
        if not direct or not permitted:return False
        now=time.monotonic()
        last=self.last.get(event.chat_id)
        if last is not None and now-last<self.interval:return False
        # Reserve before await, including failed sends, to prevent concurrent spam.
        self.last[event.chat_id]=now
        await event.reply(NOTICE,parse_mode=None,link_preview=False)
        return True
