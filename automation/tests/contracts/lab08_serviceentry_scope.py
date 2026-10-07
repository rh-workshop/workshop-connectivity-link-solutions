"""Paridad y visibilidad del ServiceEntry publicado, sin leer el clúster."""
import importlib.util
from pathlib import Path
import re
import sys
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[3]
ROLE = ROOT / 'automation/labs/lab08/roles/lab08'
SPEC = importlib.util.spec_from_file_location('render', ROOT / 'automation/scripts/check_render.py')
RENDER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RENDER)
sys.path.insert(0, str(ROOT / 'automation/scripts'))
from workshop_pages import SKIP, workshop_root
WORKSHOP = workshop_root()


class Lab08ServiceEntryScope(unittest.TestCase):
    def render(self, participant):
        values = dict(lab_id=participant, wk_ns_app='atp-'+participant,
                      wk_ns_gateway='gateway-'+participant,
                      lab08_ext_host='shared-external.example.com', lab08_ext_port=8080)
        template = (ROLE / 'templates/service-entry.yaml.j2').read_text()
        return yaml.safe_load(RENDER.environment(ROLE).from_string(template).render(values))

    def test_same_host_is_exported_only_to_own_app_and_gateway(self):
        one, two = self.render('user1'), self.render('user2')
        self.assertEqual(one['spec']['hosts'], two['spec']['hosts'])
        for item in [one, two]:
            owner = item['metadata']['labels']['workshop.user']
            self.assertEqual(item['spec']['exportTo'], ['.', 'gateway-'+owner])
            self.assertNotIn('*', item['spec']['exportTo'])
            self.assertNotIn('gateway-'+('user2' if owner=='user1' else 'user1'), item['spec']['exportTo'])

    @unittest.skipUnless(WORKSHOP, SKIP)
    def test_published_manifest_matches_rendered_serviceentry(self):
        page = (WORKSHOP / 'modules/ROOT/pages/lab8-servicios-externos.adoc').read_text()
        block = next(b for b in re.findall(r'^----\n(.*?)^----$', page, re.M | re.S)
                     if '\nkind: ServiceEntry\n' in b)
        body = block[block.index('apiVersion:'):block.rindex('\nEOF')]
        for source, value in {'${NS_APP}':'atp-user1', '${NS_GATEWAY}':'gateway-user1',
                              '${LAB_ID}':'user1', '${EXT_HOST}':'shared-external.example.com',
                              '${EXT_PORT}':'8080'}.items():
            body = body.replace(source, value)
        self.assertEqual(yaml.safe_load(body), self.render('user1'))


if __name__ == '__main__':
    unittest.main()
