"""Fuente Git real local: SHA/árbol Kustomize y contrato Application, sin publicación."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import yaml
import adoption_gate as FIXTURE
G, SOURCE = FIXTURE.G, FIXTURE.SOURCE


class SourceProof(unittest.TestCase):
    def test_real_snapshot_commit_and_kustomize_match(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp);expected=FIXTURE.Adoption().fixture(folder)
            proof=SOURCE.verify(folder,expected['git_source'])
            self.assertEqual(proof['resource_count'],1)
            self.assertEqual(proof['revision'],expected['git_source']['revision'])

    def test_storage_drift_in_real_committed_tree_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp);expected=FIXTURE.Adoption().fixture(folder)
            manifest=folder/'export/platform/components/keycloak/manifests.yaml'
            resource=yaml.safe_load(manifest.read_text());resource['spec']['resources']['requests']['storage']='20Gi'
            manifest.write_text(yaml.safe_dump(resource))
            bundle=folder/'different.bundle';SOURCE.P.create_bundle(folder/'export',bundle)
            revision=SOURCE.run(['git','bundle','list-heads',str(bundle),'refs/heads/main']).split()[0]
            contract=expected['git_source']|{'bundle':str(bundle),'revision':revision}
            app=folder/'applications/keycloak.yaml';data=yaml.safe_load(app.read_text())
            data['spec']['source']['targetRevision']=revision;app.write_text(yaml.safe_dump(data))
            with self.assertRaisesRegex(ValueError,'kustomize_content_drift'):SOURCE.verify(folder,contract)

    def test_repo_path_project_destination_and_zero_sha_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp);expected=FIXTURE.Adoption().fixture(folder);file=folder/'applications/keycloak.yaml';original=yaml.safe_load(file.read_text())
            for field,value in [('repoURL','https://github.com/other/source.git'),('path','different/components/keycloak')]:
                data=copy.deepcopy(original);data['spec']['source'][field]=value;file.write_text(yaml.safe_dump(data))
                with self.assertRaisesRegex(ValueError,'application_contract_mismatch'):SOURCE.verify(folder,expected['git_source'])
            for field,value in [('project','other-project'),('destination',{'server':'https://other.cluster.invalid'})]:
                data=copy.deepcopy(original);data['spec'][field]=value;file.write_text(yaml.safe_dump(data))
                with self.assertRaisesRegex(ValueError,'application_contract_mismatch'):SOURCE.verify(folder,expected['git_source'])
            data=copy.deepcopy(original);data['metadata']['namespace']='openshift-gitops';file.write_text(yaml.safe_dump(data))
            with self.assertRaisesRegex(ValueError,'application_identity_mismatch'):SOURCE.verify(folder,expected['git_source'])
            file.write_text(yaml.safe_dump(original))
            with self.assertRaisesRegex(ValueError,'revision_invalid'):SOURCE.verify(folder,expected['git_source']|{'revision':'0'*40})

    def test_remote_release_exact_sha_and_guarded_pod(self):
        revision='a'*40;contract={'revision':revision,'repo_url':SOURCE.INTERNAL_REPO,'repo_server':{'name':'repo-server','uid':'pod-uid'}}
        pod={'metadata':{'uid':'pod-uid'},'spec':{'containers':[{'name':'argocd-repo-server'}]}}
        commands=[]
        def run(command,**kwargs):
            commands.append(command)
            return type('Result',(),{'returncode':0,'stdout':revision+'\trefs/tags/releases/'+revision+'\n','stderr':''})()
        with patch.object(G.Oc,'get',return_value=pod),patch.object(G.subprocess,'run',run):
            self.assertEqual(G.Oc().remote_reference(contract),revision)
        self.assertEqual(commands[0][-4:],['git','ls-remote',SOURCE.INTERNAL_REPO,'refs/tags/releases/'+revision])
        with patch.object(G.Oc,'get',return_value=pod),patch.object(G.subprocess,'run',return_value=type('Result',(),{'returncode':0,'stdout':'b'*40+'\trefs/tags/releases/'+revision,'stderr':''})()):
            with self.assertRaisesRegex(ValueError,'reference_mismatch'):G.Oc().remote_reference(contract)
        pod['metadata']['uid']='wrong'
        with patch.object(G.Oc,'get',return_value=pod):
            with self.assertRaisesRegex(ValueError,'uid_mismatch'):G.Oc().remote_reference(contract)


if __name__=='__main__':unittest.main()
