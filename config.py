import os
from pathlib import Path
from zoneinfo import ZoneInfo
from dotenv import load_dotenv
ROOT=Path(__file__).resolve().parent
load_dotenv(ROOT/'.env')
DATA=Path(os.getenv('DATA_DIR') or ROOT/'data');DATA.mkdir(parents=True,exist_ok=True)
SESSION=str(DATA/'account')
def telegram_credentials():
    try: api_id=int(os.getenv('TELEGRAM_API_ID',''))
    except ValueError: raise ValueError('Заполни TELEGRAM_API_ID в .env') from None
    api_hash=os.getenv('TELEGRAM_API_HASH','').strip()
    if api_id<=0 or len(api_hash)!=32:raise ValueError('Проверь TELEGRAM_API_ID и TELEGRAM_API_HASH')
    return api_id,api_hash
class Config:
    def __init__(self):
        self.api_id,self.api_hash=telegram_credentials()
        self.key=os.getenv('AI_API_KEY','').strip()
        if not self.key:raise ValueError('Заполни AI_API_KEY')
        self.model=os.getenv('AI_MODEL','deepseek-v4-pro').strip()
        self.base_url=os.getenv('AI_BASE_URL','https://darkapi.shop/v1').strip().rstrip('/')
        from urllib.parse import urlsplit
        url=urlsplit(self.base_url)
        if url.scheme!='https' or not url.hostname or url.username or url.password or url.query or url.fragment:
            raise ValueError('AI_BASE_URL должен быть HTTPS URL без ключей и параметров')
        if not self.model:raise ValueError('Заполни AI_MODEL')
        self.chats={int(x.strip()) for x in os.getenv('ALLOWED_CHAT_IDS','').split(',') if x.strip()}
        if not self.chats or any(x>=0 for x in self.chats):raise ValueError('Укажи отрицательные ID групп в ALLOWED_CHAT_IDS')
        self.owner=int(os.getenv('OWNER_ID') or 0)
        self.name=os.getenv('BOT_NAME','Бао')[:60]
        self.triggers=[x.strip().casefold() for x in os.getenv('TRIGGER_WORDS','бао').split(',') if x.strip()]
        self.chance=float(os.getenv('RANDOM_REPLY_CHANCE','0.03'))
        self.interval=int(os.getenv('MIN_REPLY_SECONDS','90'))
        self.limit=int(os.getenv('DAILY_API_LIMIT','100'))
        self.context=int(os.getenv('CONTEXT_MESSAGES','35'))
        self.days=int(os.getenv('RETENTION_DAYS','7'))
        self.tz=ZoneInfo(os.getenv('TIMEZONE','Europe/Moscow'))
        self.quiet_start=int(os.getenv('QUIET_START','1'));self.quiet_end=int(os.getenv('QUIET_END','9'))
        if not (0<=self.chance<=1 and 5<=self.interval<=86400 and 1<=self.limit<=10000 and 5<=self.context<=100 and 1<=self.days<=365 and 0<=self.quiet_start<24 and 0<=self.quiet_end<24):
            raise ValueError('Настройки частоты/лимитов вне допустимого диапазона. См. README.')
