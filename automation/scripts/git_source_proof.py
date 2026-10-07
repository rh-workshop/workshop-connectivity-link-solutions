"""Prueba offline del commit bundle y componentes Kustomize; no publica ni sincroniza."""
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys
import subprocess
import tempfile
import yaml

sys.path.insert(0,str(Path(__file__).resolve().parent))
from platform_identity import load_identity
IDENTITY=load_identity()

ROOT=Path(__file__).resolve().parents[1]
SPEC=importlib.util.spec_from_file_location('platform_repository',ROOT/'common/roles/platform_git_repository/files/repository.py')
P=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(P)
INTERNAL_REPO='http://cl-platform-git-repository.cl-platform-gitops.svc:8080/platform.git'


def run(command):
    result=subprocess.run(command,capture_output=True,text=True,timeout=120)
    if result.returncode:raise ValueError('git_source_command_failed')
    return result.stdout


def identity(resource):
    meta=resource['metadata']
    return '|'.join([resource['apiVersion'],resource['kind'],meta.get('namespace',''),meta['name']])


def verify(folder,contract):
    revision=contract.get('revision','')
    if not re.fullmatch('[0-9a-f]{40}',revision) or revision=='0'*40:raise ValueError('git_source_revision_invalid')
    prefix=contract.get('published_path','')
    if not prefix or Path(prefix).is_absolute() or any(p in {'.','..'} for p in prefix.split('/')) or not re.fullmatch('[A-Za-z0-9_./-]+',prefix):
        raise ValueError('git_source_path_invalid')
    repo=contract.get('repo_url','')
    if repo!=INTERNAL_REPO and not re.fullmatch(r'https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:\.git)?',repo):
        raise ValueError('git_source_repo_invalid')
    bundle=P.outside_git(contract.get('bundle',''))
    if not bundle.is_file() or bundle.stat().st_mode & 0o077:raise ValueError('git_source_bundle_not_private')
    try:P.validate_bundle(bundle)
    except (ValueError,OSError,subprocess.CalledProcessError):raise ValueError('git_source_bundle_invalid') from None
    apps=list((folder/'applications').glob('*.yaml'))
    if not apps:raise ValueError('git_source_applications_missing')
    phases={}
    for file in apps:
        app=yaml.safe_load(file.read_text())
        name=app['metadata']['name']
        if app['metadata'].get('namespace') != IDENTITY['namespace'] or not name.startswith(IDENTITY['name']+'-'):raise ValueError('git_source_application_identity_mismatch')
        phase=name.removeprefix(IDENTITY['name']+'-')
        source={'repoURL':repo,'targetRevision':revision,'path':prefix+'/components/'+phase}
        if app['spec']['source']!=source or app['spec']['project']!=IDENTITY['name'] or app['spec']['destination']!={'server':'https://kubernetes.default.svc'}:
            raise ValueError('git_source_application_contract_mismatch')
        phases[phase]=file
    expected_phases={p.parent.name for p in (folder/'components').glob('*/manifests.yaml')}
    if set(phases)!=expected_phases or len(phases)!=len(apps):raise ValueError('git_source_phase_inventory_mismatch')
    trees={}
    with tempfile.TemporaryDirectory() as tmp:
        clone=Path(tmp)/'source'
        run(['git','clone','-q','--no-checkout',str(bundle),str(clone)])
        actual=run(['git','-C',str(clone),'rev-parse','--verify',revision+'^{commit}']).strip()
        if actual!=revision:raise ValueError('git_source_commit_mismatch')
        run(['git','-C',str(clone),'checkout','-q','--detach',revision])
        for file in (clone/prefix).rglob('kustomization.y*ml'):
            config=yaml.safe_load(file.read_text())
            if config.get('helmCharts') or config.get('generators'):
                raise ValueError('git_source_external_generator_not_allowed')
            for field in ('resources','components','bases'):
                for target in config.get(field,[]):
                    if not isinstance(target,str) or ':' in target or not (file.parent/target).resolve().is_relative_to((clone/prefix).resolve()):
                        raise ValueError('git_source_nonlocal_reference_not_allowed')
        for phase in sorted(phases):
            text=run(['oc','kustomize',str(clone/prefix/'components'/phase)])
            built=[r for r in yaml.safe_load_all(text) if r is not None]
            wanted=[r for r in yaml.safe_load_all((folder/'components'/phase/'manifests.yaml').read_text()) if r is not None]
            def index(resources):
                keys=[identity(r) for r in resources]
                if len(keys)!=len(set(keys)) or any(r.get('kind')=='Secret' for r in resources):raise ValueError('git_source_invalid_resource_inventory')
                return {identity(r):r for r in resources}
            if index(built)!=index(wanted):raise ValueError('git_source_kustomize_content_drift')
            trees[phase]=index(built)
    return {'revision':revision,'tree_sha256':hashlib.sha256(json.dumps(trees,sort_keys=True,separators=(',',':')).encode()).hexdigest(),
            'phases':sorted(trees),'resource_count':sum(len(v) for v in trees.values())}
