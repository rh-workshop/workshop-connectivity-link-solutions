"""Ejecutar contratos nativos de gates con fixtures, sin cliente Kubernetes."""
import copy
from pathlib import Path
import unittest
import yaml
from common_roles import run_tasks

ROOT=Path(__file__).resolve().parents[3]
ROLE=ROOT/'automation/common/roles/platform_gate'


class NativeGate(unittest.TestCase):
    def test_phase_and_reference_guard(self):
        task=yaml.safe_load((ROLE/'tasks/main.yml').read_text())[0]
        for phase,allowed,success in [('operators',False,True),('gateway-defaults',False,True),('ingress-certificate',False,True),
                                      ('invalid',False,False),('ingress-reference',False,False),
                                      ('ingress-reference',True,True)]:
            result=run_tasks([task],{'platform_gate_phase':phase,'platform_gate_allow_reference_change':allowed})
            self.assertEqual(result.returncode==0,success,result.stdout+result.stderr)

    def test_actual_generation_until(self):
        original=yaml.safe_load((ROLE/'tasks/esperar.yml').read_text())[1]
        for status,observed,success in [('True',2,True),('true',2,True),('False',2,False),('True',1,False)]:
            task=copy.deepcopy(original)
            task.pop('kubernetes.core.k8s_info');task.pop('register')
            task['ansible.builtin.set_fact']={'gate_generation':{'resources':[{
                'metadata':{'generation':2},'status':{'conditions':[
                    {'type':'Ready','status':status,'observedGeneration':observed}]}}]}}
            task['retries']=1;task['delay']=0
            result=run_tasks([task],{'gate_resource':{'condition':'Ready'}})
            self.assertEqual(result.returncode==0,success,result.stdout+result.stderr)

    def test_read_only_role_and_canonical_tls(self):
        tasks=yaml.safe_load((ROLE/'tasks/main.yml').read_text())
        for path in (ROLE/'tasks').glob('*.yml'):
            self.assertNotIn('kubernetes.core.k8s:',path.read_text())
            self.assertNotIn('ansible.builtin.command:',path.read_text())
        ingress=[t for t in tasks if t.get('ansible.builtin.include_role',{}).get('name')=='ingress_certificate']
        self.assertEqual([t['vars']['ingress_certificate_mode'] for t in ingress],['verify','apply'])
        self.assertFalse(ingress[0]['vars']['ingress_certificate_verificar_servicio'])
        self.assertTrue(ingress[1]['vars']['ingress_certificate_verificar_servicio'])
        self.assertIn("platform_gate_phase == 'ingress-reference'",ingress[1]['when'])
        gateway=next(t for t in tasks if t.get('ansible.builtin.include_role',{}).get('name')=='gateway_defaults')
        self.assertTrue(gateway['vars']['gateway_defaults_verificar_solo'])
        self.assertEqual(gateway['when'],"platform_gate_phase == 'gateway-defaults'")
        plugin=next(t for t in tasks if t.get('ansible.builtin.include_role',{}).get('name')=='console_plugin_configuration')
        self.assertTrue(plugin['vars']['console_plugin_verificar_solo'])
        self.assertEqual(plugin['when'],"platform_gate_phase == 'observability'")
        operators=yaml.safe_load((ROLE/'tasks/operators.yml').read_text())
        self.assertEqual(operators[0]['ansible.builtin.include_tasks'],'operador.yml')
        self.assertEqual(operators[1]['vars']['gate_resource']['condition'],'Established')

    def test_subscription_installed_csv_native_until(self):
        original=yaml.safe_load((ROLE/'tasks/operador.yml').read_text())[0]
        for package,csv,success in [('rhcl-operator','rhcl-operator.v1.4',True),
                                    ('rhcl-operator','',False),('other-operator','other.v1',False)]:
            task=copy.deepcopy(original)
            task.pop('kubernetes.core.k8s_info');task.pop('register')
            task['ansible.builtin.set_fact']={'gate_subscriptions':{'resources':[
                {'spec':{'name':package},'status':{'installedCSV':csv}}]}}
            task['retries']=1;task['delay']=0
            result=run_tasks([task],{'gate_operator':{'nombre':'rhcl-operator'}})
            self.assertEqual(result.returncode==0,success,result.stdout+result.stderr)


if __name__=='__main__':unittest.main()
