import ast
import types
import unittest
from pathlib import Path

class FakeClient:
    def __init__(self,**kwargs):self.options=kwargs;self.calls=[];self.status=200;self.content='готово';self.closed=False
    async def post(self,url,**kwargs):
        self.calls.append((url,kwargs))
        return types.SimpleNamespace(status_code=self.status,json=lambda:{'choices':[{'message':{'content':self.content}}]})
    async def aclose(self):self.closed=True

class APITests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        tree=ast.parse(Path('brain.py').read_text())
        ns={'httpx':types.SimpleNamespace(AsyncClient=FakeClient)}
        exec(compile(ast.Module(body=[n for n in tree.body if isinstance(n,ast.ClassDef)],type_ignores=[]),'brain.py','exec'),ns)
        self.brain=ns['Brain']('test-placeholder','deepseek-v4-pro','https://darkapi.shop/v1/')
    async def test_endpoint_model_auth(self):
        self.assertEqual(await self.brain.reply([{'role':'user','content':'test'}]),'готово')
        url,request=self.brain.http.calls[0]
        self.assertEqual(url,'https://darkapi.shop/v1/chat/completions')
        self.assertEqual(request['json']['model'],'deepseek-v4-pro')
        self.assertEqual(self.brain.http.options['headers']['Authorization'],'Bearer test-placeholder')
        self.assertFalse(self.brain.http.options['follow_redirects'])
        await self.brain.close();self.assertTrue(self.brain.http.closed)
    async def test_no_retries_or_secret_in_error(self):
        self.brain.http.status=401
        with self.assertRaisesRegex(RuntimeError,'^AI HTTP 401$'):await self.brain.reply([])
        self.assertEqual(len(self.brain.http.calls),1)
    async def test_silent_and_bad_content(self):
        self.brain.http.content='[SILENT]'
        self.assertEqual(await self.brain.reply([]),'')
        self.brain.http.content=None
        with self.assertRaises(RuntimeError):await self.brain.reply([])
