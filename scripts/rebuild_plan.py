"""Resolve explicit local source revisions without replacing the frozen baseline."""
import json
import hashlib
from pathlib import Path


def recipe_fingerprint(recipe):
    repo=Path(__file__).resolve().parents[1]
    data={k:v for k,v in recipe.items() if k not in ('priority','space_gib','jobs')}
    for field in ('setup_hook','cleanup_hook'):
        if recipe.get(field):data[field+'_sha256']=hashlib.sha256((repo/recipe[field]).read_bytes()).hexdigest()
    return hashlib.sha256(json.dumps(data,sort_keys=True).encode()).hexdigest()


def effective_packages(root,plan):
    root=Path(root)
    ledger=root/'derived-manifest.json'
    derived={x['origin_source']:x for x in json.loads(ledger.read_text())} if ledger.exists() else {}
    repo=Path(__file__).resolve().parents[1]
    recipes=json.loads((repo/'config/base-build-recipes.json').read_text())['packages']
    originals={x['source']:dict(x,binaries=list(x['binaries'])) for x in plan['packages']}
    extension_path=root/'source-plan-extension.json'
    if extension_path.exists():
        extension=json.loads(extension_path.read_text())
        assert extension['base_plan_sha256']==hashlib.sha256((root/'source-plan.json').read_bytes()).hexdigest()
        for extra in extension['packages']:
            if extra['source'] in originals:
                base=originals[extra['source']]
                inputs=lambda p: sorted((f['name'],f['size'],f['sha256']) for f in p['files'])
                assert base['version']==extra['version'] and inputs(base)==inputs(extra)
                names={b['binary'] for b in base['binaries']}
                assert not names.intersection(b['binary'] for b in extra['binaries'])
                base['binaries']+=extra['binaries']
            else:
                originals[extra['source']]=extra
    result=[]
    for original in originals.values():
        item=dict(original,origin_source=original['source'],origin_version=original['version'])
        recipe=recipes.get(original['source'],{})
        item['recipe']=recipe
        if original['source'] in derived and derived[original['source']]['recipe']==recipe:
            local=derived[original['source']]
            expected_dsc=next(x['sha256'] for x in original['files'] if x['name'].endswith('.dsc'))
            assert local['origin_version']==original['version'] and local['origin_dsc_sha256']==expected_dsc
            assert local['version']==recipe['version'] and local['recipe']==recipe
            directory=(root/local['relative_directory']).resolve()
            assert directory.is_relative_to((root/'derived-sources').resolve())
            item.update(source=local['source'],version=local['version'],files=local['files'],
                        directory=directory,original_files=original['files'])
        else:
            item['directory']=root/'sources'/(item['source']+'_'+item['version'].replace(':','_'))
            item['derivation_pending']=bool(recipe.get('transform'))
        result.append(item)
    return result


def known_revision_keys(root,plan):
    """Recognize retained prior local DSCs without counting them as current."""
    root=Path(root)
    origins={p['source']:(p['version'],next(f['sha256'] for f in p['files'] if f['name'].endswith('.dsc'))) for p in plan['packages']}
    result=set()
    for marker in (root/'derived-sources').glob('*/.source-verified.json'):
        value=json.loads(marker.read_text())
        if origins.get(value['origin_source'])!=(value['origin_version'],value['origin_dsc_sha256']):continue
        if (root/value['relative_directory']).resolve()!=marker.parent.resolve():continue
        for f in value['files']:
            if not f['name'].endswith('.dsc'):continue
            path=marker.parent/f['name']
            if path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest()==f['sha256']:
                result.add((value['source'],value['version'],f['sha256']))
    return result
