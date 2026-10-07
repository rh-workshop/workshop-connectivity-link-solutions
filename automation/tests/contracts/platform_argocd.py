"""Contratos offline de instancia aislada, ownership y verificación sin escrituras."""
import copy
from pathlib import Path
import unittest
import yaml
from jinja2 import Environment, StrictUndefined

ROOT = Path(__file__).resolve().parents[3]
ROLE = ROOT/'automation/common/roles/platform_argocd'


class PlatformArgoCD(unittest.TestCase):
    def setUp(self):
        self.identity = yaml.safe_load((ROOT/'automation/common/platform-argocd.yml').read_text())
        self.defaults = yaml.safe_load((ROLE/'defaults/main.yml').read_text())
        self.tasks = yaml.safe_load((ROLE/'tasks/main.yml').read_text())
        self.env = Environment(undefined=StrictUndefined)
        self.env.filters['bool'] = bool
        self.env.filters['dict2items'] = lambda obj: [{'key':k, 'value':v} for k,v in obj.items()]

    def accepted(self, task_name, obj):
        task = next(t for t in self.tasks if t['name'] == task_name)
        variables = dict(self.defaults, item=obj)
        return all(self.env.compile_expression(expr)(**variables)
                   for expr in task['ansible.builtin.assert']['that'])

    def test_template_is_isolated_without_rbac_or_global_configuration(self):
        rendered = self.env.from_string((ROLE/'templates/instance.yml.j2').read_text()).render(
            wk_platform_argocd=self.identity)
        namespace, instance = list(yaml.safe_load_all(rendered))
        self.assertEqual([namespace['kind'],instance['kind']], ['Namespace','ArgoCD'])
        self.assertEqual(namespace['metadata']['name'], self.identity['namespace'])
        self.assertEqual(instance['metadata']['name'], self.identity['name'])
        self.assertEqual(instance['metadata']['namespace'], self.identity['namespace'])
        self.assertEqual(instance['spec'], {'defaultClusterScopedRoleDisabled':True,
            'controller':{'respectRBAC':'normal'},
            'extraConfig':{'application.resourceTrackingMethod':'annotation'}})
        self.assertNotIn('managed-by', rendered)
        self.assertNotIn('ARGOCD_CLUSTER_CONFIG_NAMESPACES', rendered)

    def test_readonly_default_writes_only_explicit_install(self):
        self.assertEqual(self.defaults['platform_argocd_operation'],'verificar')
        writes = [t for t in self.tasks if 'kubernetes.core.k8s' in t]
        self.assertEqual(len(writes),1)
        guard = self.env.compile_expression(writes[0]['when'])
        self.assertFalse(guard(platform_argocd_operation='verificar'))
        self.assertTrue(guard(platform_argocd_operation='instalar'))
        self.assertFalse(any('ansible.builtin.command' in t or 'kubernetes.core.k8s_exec' in t for t in self.tasks))
        shared = next(t for t in self.tasks if t.get('ansible.builtin.include_role',{}).get('tasks_from')=='operador')
        self.assertTrue(shared['vars']['gitops_bootstrap_verificar_solo'])

    def test_foreign_namespace_rejected_by_actual_guards(self):
        obj = {'metadata':{'labels':copy.deepcopy(self.defaults['platform_argocd_labels'])}}
        name = 'Rechazar un namespace ajeno o gestionado por otra instancia'
        self.assertTrue(self.accepted(name,obj))
        for labels in [{}, {'workshop.module':'foreign'},
                       dict(obj['metadata']['labels'], **{'argocd.argoproj.io/managed-by':'other'}),
                       dict(obj['metadata']['labels'], **{'argocd.argoproj.io/managed-by-cluster-argocd':'other'})]:
            changed = copy.deepcopy(obj);changed['metadata']['labels']=labels
            self.assertFalse(self.accepted(name,changed))
        obj['metadata']['deletionTimestamp']='2026-01-01'
        self.assertFalse(self.accepted(name,obj))

    def test_foreign_or_unrestricted_instance_rejected(self):
        obj = {'metadata':{'labels':copy.deepcopy(self.defaults['platform_argocd_labels'])},
               'spec':{'defaultClusterScopedRoleDisabled':True,'controller':{'respectRBAC':'normal'},
                       'extraConfig':{'application.resourceTrackingMethod':'annotation'}}}
        name = 'Rechazar una instancia ajena antes de instalar o verificar'
        self.assertTrue(self.accepted(name,obj))
        for path, value in [(('metadata','labels','workshop.component'),'foreign'),
                            (('spec','defaultClusterScopedRoleDisabled'),False),
                            (('spec','controller','respectRBAC'),'strict'),
                            (('spec','extraConfig','application.resourceTrackingMethod'),'label')]:
            changed=copy.deepcopy(obj);node=changed
            for key in path[:-1]:node=node[key]
            node[path[-1]]=value
            self.assertFalse(self.accepted(name,changed))

    def test_schema_check_precedes_the_only_write(self):
        schema = next(i for i,t in enumerate(self.tasks) if 'campos del aislamiento' in t['name'])
        write = next(i for i,t in enumerate(self.tasks) if 'kubernetes.core.k8s' in t)
        self.assertLess(schema,write)
        task = self.tasks[schema]
        fields = {'defaultClusterScopedRoleDisabled':{'type':'boolean'},
                  'controller':{'properties':{'respectRBAC':{'type':'string'}}},
                  'extraConfig':{'type':'object','additionalProperties':{'type':'string'}}}
        version = {'schema':{'openAPIV3Schema':{'properties':{'spec':{'properties':fields}}}}}
        def accepted(value):
            return all(self.env.compile_expression(expr)(platform_argocd_versions=[value])
                       for expr in task['ansible.builtin.assert']['that'])
        self.assertTrue(accepted(version))
        changed=copy.deepcopy(version)
        changed['schema']['openAPIV3Schema']['properties']['spec']['properties']['extraConfig']['type']='string'
        self.assertFalse(accepted(changed))

    def test_shared_operator_keeps_default_instance_behavior(self):
        tasks=ROOT/'automation/common/roles/gitops_bootstrap/tasks'
        main=yaml.safe_load((tasks/'main.yml').read_text())
        self.assertEqual(main[0]['ansible.builtin.import_tasks'],'operador.yml')
        self.assertEqual(main[1]['ansible.builtin.include_tasks'],'esperar_argocd.yml')
        operator=(tasks/'operador.yml').read_text()
        self.assertNotIn('esperar_argocd.yml',operator)
        defaults=yaml.safe_load((tasks.parent/'defaults/main.yml').read_text())
        self.assertEqual(defaults['gitops_bootstrap_argocd_namespace'],'openshift-gitops')
        self.assertEqual(defaults['gitops_bootstrap_argocd_instancia'],'openshift-gitops')
        common=yaml.safe_load((ROOT/'automation/common/roles/comun/tasks/main.yml').read_text())
        lookup=common[0]['ansible.builtin.set_fact']['wk_platform_argocd']
        self.assertIn("role_path ~ '/../../platform-argocd.yml'",lookup)

    def test_workload_readiness_rejects_foreign_owner_and_zero_replicas(self):
        task=next(t for t in self.tasks if t['name']=='Verificar readiness y ownership de cada componente generado')
        obj={'metadata':{'generation':2,'ownerReferences':[{
            'kind':'ArgoCD','name':self.identity['name'],'uid':'instance-uid'}]},
            'spec':{'replicas':1},'status':{'observedGeneration':2,'readyReplicas':1}}
        def accepted(value):
            variables={'item':value,'wk_platform_argocd':self.identity,
                       'gitops_bootstrap_argocd':{'resources':[{'metadata':{'uid':'instance-uid'}}]}}
            return all(self.env.compile_expression(expr)(**variables)
                       for expr in task['ansible.builtin.assert']['that'])
        self.assertTrue(accepted(obj))
        for path,value in [(('metadata','ownerReferences',0,'uid'),'foreign'),
                           (('status','readyReplicas'),0),(('status','observedGeneration'),1),
                           (('spec','replicas'),0)]:
            changed=copy.deepcopy(obj);node=changed
            for key in path[:-1]:node=node[key]
            node[path[-1]]=value
            self.assertFalse(accepted(changed))

    def test_operator_tracking_configmap_name_is_namespace_local(self):
        task=next(t for t in self.tasks if 'ConfigMap local de tracking' in t['name'])
        info=task['kubernetes.core.k8s_info']
        self.assertEqual(info['name'],'argocd-cm')
        self.assertEqual(info['namespace'],'{{ wk_platform_argocd.namespace }}')
        assertion=next(t for t in self.tasks if 'tracking por annotation' in t['name'])
        def accepted(data):
            result={'resources':[{'data':data}]}
            return all(self.env.compile_expression(expr)(platform_argocd_cm=result)
                       for expr in assertion['ansible.builtin.assert']['that'])
        self.assertTrue(accepted({'application.resourceTrackingMethod':'annotation'}))
        self.assertFalse(accepted({'application.resourceTrackingMethod':'label'}))
        self.assertFalse(accepted({}))


if __name__ == '__main__':
    unittest.main()
