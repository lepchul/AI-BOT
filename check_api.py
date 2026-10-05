"""One paid API request. No Telegram connection, no chat history sent."""
import asyncio
import os
from dotenv import load_dotenv
from pathlib import Path
from brain import Brain
load_dotenv(Path(__file__).resolve().parent/'.env')
async def main():
    key=os.getenv('AI_API_KEY','').strip()
    if not key:raise ValueError('Заполни AI_API_KEY в .env')
    brain=Brain(key,os.getenv('AI_MODEL','deepseek-v4-pro'),os.getenv('AI_BASE_URL','https://darkapi.shop/v1'))
    try:
        result=await brain.reply([{'role':'user','content':'Ответь одним словом: работает'}])
        print('API ответил:',result or '(пустой ответ)')
    finally:await brain.close()
if __name__=='__main__':
    try:asyncio.run(main())
    except Exception as exc:
        safe=str(exc) if isinstance(exc,ValueError) or (type(exc) is RuntimeError and str(exc).startswith('AI HTTP ')) else type(exc).__name__
        print('Проверка не прошла:',safe)
        raise SystemExit(1)
