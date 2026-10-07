"""Contratos reales de las señales: fixtures Ansible, sin red ni clúster."""
import copy
import json
import importlib.util
import os
from pathlib import Path
import unittest
import subprocess
import time
import yaml
from common_roles import run_tasks

ROOT=Path(__file__).resolve().parents[3]
TASKS=yaml.safe_load((ROOT/'automation/labs/lab05/roles/lab05/tasks/validar.yml').read_text())
SPEC=importlib.util.spec_from_file_location('tempo_query',ROOT/'automation/labs/lab05/roles/lab05/files/tempo-query.py')
TEMPO=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(TEMPO)

class Signals(unittest.TestCase):
    def test_policy_trace_actual_semantics_and_parent_chain(self):
        def attr(key,value):return {'key':key,'value':{'stringValue':value}}
        trace={'batches':[
            {'resource':{'attributes':[attr('service.name','wasm-shim')]},'scopeSpans':[{'spans':[
                {'spanId':'root','name':'kuadrant_filter','startTimeUnixNano':str(101*1000000000),'attributes':[attr('request_id','fresh-rid')]},
                {'spanId':'grpc','parentSpanId':'root','name':'grpc'},
                {'spanId':'req','parentSpanId':'grpc','name':'grpc_request'}]}]},
            {'resource':{'attributes':[attr('service.name','authorino')]},'scopeSpans':[{'spans':[
                {'spanId':'authrpc','parentSpanId':'req','name':'envoy.service.auth.v3.Authorization/Check'},
                {'spanId':'auth','parentSpanId':'authrpc','name':'Check','attributes':[attr('authorino.request_id','fresh-rid'),attr('guid:x-request-id','fresh-rid')]}]}]}]}
        self.assertTrue(TEMPO.policy_evidence(trace,'fresh-rid',100)['ancestryVerified'])
        self.assertIsNone(TEMPO.policy_evidence(trace,'other-rid',100))
        self.assertIsNone(TEMPO.policy_evidence(trace,'fresh-rid',102))
        for alteration in ['disconnected','cycle','wrong-service','wrong-rid','wrong-operation','missing-auth-rid']:
            invalid=copy.deepcopy(trace)
            root=invalid['batches'][0]['scopeSpans'][0]['spans'][0]
            auth=invalid['batches'][1]['scopeSpans'][0]['spans'][-1]
            if alteration=='disconnected':auth['parentSpanId']='unrelated'
            if alteration=='cycle':auth['parentSpanId']='auth'
            if alteration=='wrong-service':invalid['batches'][1]['resource']['attributes'][0]['value']['stringValue']='other'
            if alteration=='wrong-rid':auth['attributes'][0]['value']['stringValue']='old-rid'
            if alteration=='wrong-operation':root['name']='other'
            if alteration=='missing-auth-rid':auth['attributes']=[]
            self.assertIsNone(TEMPO.policy_evidence(invalid,'fresh-rid',100),alteration)

    def test_policy_gate_rejects_unrelated_evidence(self):
        parent=next(t for t in TASKS if t['name'].startswith('Correlacionar la traza de políticas'))
        for rid,verified,success in [('fresh-rid',True,True),('old-rid',True,False),('fresh-rid',False,False)]:
            values={'lab05_response_rid':'fresh-rid','lab05_policy_trace':{'return_code':0,'stdout':json.dumps({'policyEvidence':{'requestId':rid,'ancestryVerified':verified}})}}
            result=run_tasks([parent['block'][-1]],values)
            self.assertEqual(result.returncode==0,success,result.stdout+result.stderr)

    def test_epoch_independent_of_local_timezone(self):
        task=next(t for t in TASKS if t['name'].startswith('Leer epoch portable'))
        self.assertEqual(task['ansible.builtin.command'],'date +%s')
        self.assertFalse(task['changed_when'])
        for timezone in ['UTC','America/Lima']:
            epoch=int(subprocess.check_output(['date','+%s'],env={**os.environ,'TZ':timezone},text=True))
            self.assertLessEqual(abs(epoch-time.time()),2)

    def test_nontransient_tempo_error_ends_retry_and_fails_assertion(self):
        parent=next(t for t in TASKS if t['name'].startswith('Comprobar que Tempo recibe'))
        original=parent['block'][1]
        task=copy.deepcopy(original);task.pop('kubernetes.core.k8s_exec');task.pop('register')
        task['ansible.builtin.set_fact']={'lab05_tempo':{'return_code':0,'stdout':json.dumps({'httpError':400,'reason':'Bad Request'})}}
        task['retries']=1;task['delay']=0
        values={'wk_gateway':'gw','gateway_class':'istio','wk_ns_gateway':'gateway-demo','lab05_started':100,'lab05_tempo_tenant':'dev','lab05_tempo_reintentos':1}
        self.assertEqual(run_tasks([task],values).returncode,0)
        result=run_tasks([task,parent['block'][-1]],values)
        self.assertNotEqual(result.returncode,0)
        self.assertIn('Bad Request',result.stdout)

    def test_metrics_reject_historical_counters_and_error_schema(self):
        parent=next(t for t in TASKS if t['name'].startswith('Esperar a las series'))
        original=parent['block'][0]
        for value,status,success in [(10,'success',False),(11,'success',True),(11,'error',False)]:
            task=copy.deepcopy(original);task.pop('ansible.builtin.uri');task.pop('register')
            task['ansible.builtin.set_fact']={'lab05_prom':{'json':{'status':status,'data':{
                'resultType':'vector','result':[{'metric':{'response_code':code},'value':[100,str(value)]} for code in ['200','401','429']]}}}}
            task['retries']=1;task['delay']=0
            result=run_tasks([task],{'lab05_baseline':{'200':10,'401':10,'429':10},'lab05_metricas_reintentos':1})
            self.assertEqual(result.returncode==0,success,result.stdout+result.stderr)

    def test_tempo_requires_fresh_structured_trace_and_successful_exec(self):
        parent=next(t for t in TASKS if t['name'].startswith('Comprobar que Tempo recibe'))
        assertion=parent['block'][-1]
        for stamp,rc,success in [(99,0,False),(101,0,True),(101,1,False)]:
            result=run_tasks([assertion],{'lab05_started':100,'lab05_tempo':{
                'return_code':rc,'stdout':json.dumps({'traces':[{'traceID':'0123456789abcdef','startTimeUnixNano':str(stamp*1000000000)}]})},
                'lab05_tempo_tenant':'dev','wk_gateway':'gw','gateway_class':'istio','wk_ns_gateway':'gateway-demo'})
            self.assertEqual(result.returncode==0,success,result.stdout+result.stderr)

    def test_response_request_id_must_match_actual_access_log(self):
        task=next(t for t in TASKS if t['name'].startswith('Correlacionar JSON'))
        for rid,success in [('returned-id',True),('unrelated-id',False)]:
            row={'response_code':401,'request_id':rid,'upstream_host':None,'route_name':'app-demo.api-route-demo.0','user_agent':'run-401'}
            result=run_tasks([task],{'lab05_response_rid':'returned-id','lab05_ua':'run','lab05_log':{'log_lines':[json.dumps(row,separators=(',',':'))]},'wk_ns_app':'app-demo','lab_id':'demo'})
            self.assertEqual(result.returncode==0,success,result.stdout+result.stderr)

    def test_shared_http_contract_and_baseline_order(self):
        authenticated=next(t for t in TASKS if t['name'].startswith('Petición con JWT'))
        self.assertEqual(authenticated['vars']['http_json_contract'],'{{ wk_bank_json_contract }}')
        names=[t['name'] for t in TASKS]
        self.assertLess(names.index('Leer contador inicial antes de las peticiones de esta ejecución'),names.index('Petición sin credencial'))

if __name__=='__main__':unittest.main()
