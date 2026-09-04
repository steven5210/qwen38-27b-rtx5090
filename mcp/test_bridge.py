import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import select
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

SOURCE = Path(__file__).with_name('qwen_mcp.py')


def frame(data):
    return ('data: '+(data if isinstance(data,str) else json.dumps(data))+'\n\n').encode()


def chunk(content=None, finish=None, reasoning=None):
    delta={}
    if content is not None: delta['content']=content
    if reasoning is not None: delta['reasoning_content']=reasoning
    return {'choices':[{'delta':delta,'finish_reason':finish}]}


class BridgeUnitTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        spec=importlib.util.spec_from_file_location('bridge_test_'+str(id(self)),SOURCE)
        self.m=importlib.util.module_from_spec(spec); spec.loader.exec_module(self.m)
        self.m.JOBS_DIR=os.path.join(self.temp.name,'jobs')
        os.makedirs(self.m.JOBS_DIR)

    def tearDown(self):
        for handle in self.m.OWNERS.values(): handle.close()
        self.temp.cleanup()

    def record(self, **overrides):
        rec=dict(state='running',started=time.time(),ended=None,phase='connecting',
                 task_preview='test',answer='',thinking_chars=0,usage=None,error=None,finish=None,effort='xhigh')
        rec.update(overrides); return rec

    def consume(self, data):
        rec=self.record()
        self.m.consume_stream(io.BytesIO(data),rec,lambda:None)
        return rec

    def test_valid_stream_reasoning_usage_and_done(self):
        rec=self.consume(b': keep-alive\n\n'+frame(chunk(reasoning='think'))+
                         frame(chunk(content='answer',finish='stop'))+
                         frame({'choices':[],'usage':{'completion_tokens':7}})+frame('[DONE]'))
        self.assertEqual((rec['state'],rec['answer'],rec['thinking_chars']),('done','answer',5))
        self.assertEqual(rec['usage']['completion_tokens'],7)

    def test_empty_eof_partial_eof_missing_finish_and_malformed_json_fail(self):
        for data in [b'',frame(chunk(content='partial')),frame('[DONE]'),
                     frame(chunk(finish='stop')),b'data: bad-json\n\n',b'data: [DONE]']:
            with self.subTest(data=data),self.assertRaises(Exception): self.consume(data)

    def test_sse_error_and_json_nonobject_fail(self):
        for data in [frame({'error':{'message':'queue timeout'}}),frame('[]')]:
            with self.subTest(data=data),self.assertRaises(self.m.ToolError):self.consume(data)

    def test_length_is_incomplete_and_partial_result_is_error(self):
        rec=self.consume(frame(chunk(content='partial',finish='length'))+frame('[DONE]'))
        self.assertEqual(rec['state'],'incomplete')
        with self.assertRaisesRegex(self.m.ToolError,'PARTIAL OUTPUT'):
            self.m.render_result('a'*32,rec)

    def test_unexpected_tools_not_success(self):
        rec=self.consume(frame({'choices':[{'delta':{'tool_calls':[{'index':0}]},'finish_reason':'tool_calls'}]})+frame('[DONE]'))
        self.assertEqual(rec['state'],'incomplete')

    def test_no_space_after_data_and_multiline_json(self):
        data=b'data:{"choices":\ndata: [{"delta":{"content":"ok"},"finish_reason":"stop"}]}\n\ndata:[DONE]\n\n'
        self.assertEqual(self.consume(data)['answer'],'ok')

    def test_mcp_validation_failure_has_is_error(self):
        output=io.StringIO()
        with contextlib.redirect_stdout(output):self.m.handle_call(1,'qwen_submit',{})
        self.assertTrue(json.loads(output.getvalue())['result']['isError'])

    def test_invalid_tool_name_gets_reply(self):
        output=io.StringIO()
        with contextlib.redirect_stdout(output):self.m.handle_call(1,[],{})
        self.assertIn('error',json.loads(output.getvalue()))

    def test_invalid_job_id_cannot_escape_registry(self):
        for jid in ['../secret','x',None,123]:
            with self.subTest(jid=jid),self.assertRaises(self.m.ToolError):self.m.get_job(jid)

    def test_retention_by_completion_preserves_new_uuid_and_live_records(self):
        with self.m.registry():
            for i in range(55):self.m.write_record('%032x'%(i+10),self.record(state='done',ended=i))
            # The lexicographically smallest job is newest.
            newest='0'*32
            self.m.write_record(newest,self.record(state='done',ended=1000))
            active='f'*32
            self.m.write_record(active,self.record(state='queued',started=1))
            self.m.prune_records()
            records=self.m.all_records()
        self.assertIn(newest,records);self.assertIn(active,records)
        self.assertNotIn('%032x'%10,records)
        self.assertEqual(sum(r['state']=='done' for r in records.values()),50)

    def test_legacy_completed_results_read_without_changes(self):
        rec=self.record(state='done',ended=100,answer='old answer',finish='stop')
        with self.m.registry():self.m.write_record('1234abcd',rec)
        self.assertEqual(self.m.get_job('1234abcd'),rec)

    def test_live_ownership_does_not_get_recovered(self):
        with self.m.registry():
            self.m.ensure_owner()
            self.m.write_record('a'*32,self.record(owner=self.m.OWNER))
        self.assertEqual(self.m.get_job('a'*32)['state'],'running')

    def test_dead_owner_partial_is_incomplete(self):
        with self.m.registry():self.m.write_record('a'*32,self.record(owner='b'*32,answer='partial'))
        rec=self.m.get_job('a'*32)
        self.assertEqual(rec['state'],'incomplete');self.assertEqual(rec['answer'],'partial')

    def test_default_xhigh_and_output_budget_unchanged(self):
        with mock.patch.object(self.m,'start_job',return_value='a'*32) as start:
            self.m.t_submit({'task':'test task'})
        body=start.call_args.args[1]
        self.assertEqual(body['reasoning_effort'],'xhigh')
        self.assertEqual(body['max_tokens'],131072)
        self.assertEqual(self.m.WINDOW,262144)

    def test_quick_tool_returns_job_id_when_wait_ends(self):
        with mock.patch.object(self.m,'start_job',return_value='a'*32),mock.patch.object(self.m,'wait_job',return_value={'state':'queued'}) as wait:
            response=self.m.t_ask({'question':'hello'})
        self.assertIn('a'*32,response);self.assertIn('Do not resubmit',response)
        self.assertLessEqual(wait.call_args.args[1],50)

    def test_worker_persists_partial_on_connection_error(self):
        rec=self.record(owner=self.m.OWNER)
        def fake_consume(response,rec,checkpoint):
            rec['answer']='partial';raise OSError('connection dropped')
        with mock.patch.object(self.m,'http',return_value=io.BytesIO(b'')),mock.patch.object(self.m,'consume_stream',side_effect=fake_consume):
            self.m.run_job('a'*32,{},rec)
        with self.m.registry():saved=self.m.read_record('a'*32)
        self.assertEqual(saved['state'],'incomplete');self.assertEqual(saved['answer'],'partial')

    def test_final_storage_failure_releases_lease(self):
        jid='a'*32;rec=self.record(owner=jid)
        with self.m.registry():
            self.m.ensure_owner(jid);self.m.write_record(jid,rec)
        with mock.patch.object(self.m,'http',return_value=io.BytesIO(frame(chunk(content='answer',finish='stop'))+frame('[DONE]'))),mock.patch.object(self.m,'persist',side_effect=[None,OSError('disk full')]),contextlib.redirect_stderr(io.StringIO()):
            self.m.run_job(jid,{},rec)
        self.assertFalse(self.m.owner_alive(jid))
        self.assertEqual(self.m.get_job(jid)['state'],'error')


class ProcessClient:
    def __init__(self,source,url):
        self.seq=0
        self.proc=subprocess.Popen([sys.executable,'-u','-B',str(source)],stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,env={**os.environ,'QWEN_URL':url})
    def rpc(self,method,params=None):
        self.seq+=1
        self.proc.stdin.write(json.dumps({'jsonrpc':'2.0','id':self.seq,'method':method,'params':params or {}})+'\n');self.proc.stdin.flush()
        if not select.select([self.proc.stdout],[],[],6)[0]:raise AssertionError('MCP did not reply')
        line=self.proc.stdout.readline()
        if not line:raise AssertionError('MCP exited: '+self.proc.stderr.read())
        return json.loads(line)
    def tool(self,name,args=None):return self.rpc('tools/call',{'name':name,'arguments':args or {}})['result']
    def submit(self,text):
        result=self.tool('qwen_submit',{'task':text})
        assert not result['isError'],result
        return re.search(r'Job ([0-9a-f]+) submitted',result['content'][0]['text']).group(1)
    def status(self,jid):return json.loads(self.tool('qwen_status',{'job_id':jid})['content'][0]['text'])
    def close(self):
        if self.proc.poll() is None:self.proc.terminate()
        self.proc.communicate(timeout=6)


class ProcessTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.source=Path(self.temp.name)/'qwen_mcp.py'
        shutil.copy2(SOURCE,self.source)
        self.release=threading.Event();self.entered=threading.Event();self.count=0;self.active=0;self.peak=0
        self.mutex=threading.Lock();self.clients=[];parent=self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_GET(self):
                data={'status':'ok'} if self.path=='/health' else {'data':[{'id':'qwen3.8-27b','max_model_len':262144}]}
                data=json.dumps(data).encode();self.send_response(200);self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
            def do_POST(self):
                body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                text=body['messages'][-1]['content']
                with parent.mutex:parent.count+=1;parent.active+=1;parent.peak=max(parent.peak,parent.active)
                try:
                    self.send_response(200);self.send_header('Content-Type','text/event-stream');self.end_headers()
                    self.wfile.write(frame(chunk(content='partial:')));self.wfile.flush()
                    if 'hold' in text:parent.entered.set();parent.release.wait(8)
                    self.wfile.write(frame(chunk(content='answer',finish='stop'))+frame('[DONE]'));self.wfile.flush()
                except (BrokenPipeError,ConnectionResetError):pass
                finally:
                    with parent.mutex:parent.active-=1
        self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        self.server.daemon_threads=True
        threading.Thread(target=self.server.serve_forever,daemon=True).start()
        self.url='http://127.0.0.1:%s'%self.server.server_port
    def client(self):
        client=ProcessClient(self.source,self.url);self.clients.append(client);return client
    def tearDown(self):
        self.release.set()
        for client in self.clients:client.close()
        self.server.shutdown();self.server.server_close();self.temp.cleanup()
    def until(self,fn):
        end=time.monotonic()+6
        while time.monotonic()<end:
            value=fn()
            if value:return value
            time.sleep(.05)
        self.fail('Condition did not become true')

    def test_two_processes_share_status_and_serialize_generations(self):
        a=self.client();first=a.submit('hold first')
        self.assertTrue(self.entered.wait(3))
        b=self.client()  # Startup during a live job must not mark it lost.
        self.assertEqual(b.status(first)['state'],'running')
        second=b.submit('second')
        self.assertEqual(a.status(second)['state'],'queued')
        time.sleep(.3);self.assertEqual(self.count,1)
        self.release.set()
        self.until(lambda:b.status(first)['state']=='done')
        self.until(lambda:a.status(second)['state']=='done')
        self.assertEqual(self.peak,1);self.assertEqual(self.count,2)
        self.assertFalse(b.tool('qwen_result',{'job_id':first})['isError'])

    def test_crashed_owner_detected_and_slot_released(self):
        a=self.client();first=a.submit('hold first');self.assertTrue(self.entered.wait(3))
        b=self.client();a.close()
        self.assertIn(b.status(first)['state'],('error','incomplete'))
        self.assertTrue(b.tool('qwen_result',{'job_id':first})['isError'])
        self.release.set()
        second=b.submit('second')
        self.until(lambda:b.status(second)['state']=='done')

    def test_completed_result_survives_all_process_restarts(self):
        a=self.client();jid=a.submit('short task')
        self.until(lambda:a.status(jid)['state']=='done');a.close()
        b=self.client();result=b.tool('qwen_result',{'job_id':jid})
        self.assertFalse(result['isError']);self.assertIn('partial:answer',result['content'][0]['text'])
        init=b.rpc('initialize',{'protocolVersion':'2025-06-18'})
        self.assertEqual(init['result']['serverInfo']['version'],'1.3.0')


if __name__=='__main__':unittest.main(verbosity=2)
