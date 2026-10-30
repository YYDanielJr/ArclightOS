#!/usr/bin/env python3
"""Produce complete local source revisions while retaining their exact origins."""
import argparse
import datetime as dt
from email.parser import Parser
import hashlib
import json
import os
from pathlib import Path
import subprocess
import source_transforms


def digest(path):
    with path.open('rb') as handle:return hashlib.file_digest(handle,'sha256').hexdigest()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('root',type=Path)
    p.add_argument('--only',nargs='+',required=True)
    p.add_argument('--finish-existing',type=Path,help='Finish packaging a retained tree after a tool/packaging failure')
    a=p.parse_args();root=a.root.resolve();repo=Path(__file__).resolve().parents[1]
    plan=json.loads((root/'source-plan.json').read_text())
    recipes=json.loads((repo/'config/base-build-recipes.json').read_text())['packages']
    ledger=root/'derived-manifest.json'
    records=json.loads(ledger.read_text()) if ledger.exists() else []
    result={x['origin_source']:x for x in records}
    env={**os.environ,'LC_ALL':'C.UTF-8','SOURCE_DATE_EPOCH':'1793145600','PYTHONDONTWRITEBYTECODE':'1'}
    if a.finish_existing:assert len(a.only)==1
    for name in a.only:
        recipe=recipes[name]
        for resource in recipe.get('auxiliary_inputs',[]):
            assert digest(repo/resource['path'])==resource['sha256']
        prior=result.get(name)
        if not a.finish_existing and prior and prior['recipe']==recipe:
            saved=(root/prior['relative_directory']).resolve()
            assert saved.is_relative_to((root/'derived-sources').resolve())
            if (saved/'.source-verified.json').is_file() and all(
                (saved/x['name']).is_file() and (saved/x['name']).stat().st_size==x['size'] and digest(saved/x['name'])==x['sha256']
                for x in prior['files']):
                print('ALREADY DERIVED',name,recipe['version'],flush=True)
                continue
        if prior and prior['recipe']!=recipe and prior['version']==recipe['version']:
            for ledger in (root/'build').rglob('results.json'):
                if any(r['source']==name and r['version']==recipe['version'] and not r['exit_code'] for r in json.loads(ledger.read_text())):
                    raise SystemExit('Increment the source version before changing an already successful recipe: '+name)
        item=next(x for x in plan['packages'] if x['source']==name and x['version']==recipe['original_version'])
        original=root/'sources'/(name+'_'+item['version'].replace(':','_'))
        dsc=next(original.glob('*.dsc'))
        expected=next(x['sha256'] for x in item['files'] if x['name']==dsc.name)
        assert digest(dsc)==expected
        output=root/'derived-sources'/(name+'_'+recipe['version'].replace(':','_'))
        if a.finish_existing:
            output=a.finish_existing.resolve()
            assert output.is_relative_to((root/'derived-sources').resolve())
            provenance=json.loads((output/'tree/debian/arclight-build-recipe.json').read_text())
            assert provenance['recipe']==recipe and provenance['origin_dsc_sha256']==expected
        elif output.exists():
            if (output/'.source-verified.json').exists() and result[name]['recipe']==recipe:
                print('ALREADY DERIVED',name,recipe['version'],flush=True)
                continue
            base=output;attempt=2
            while output.exists():
                output=base.with_name(base.name+f'_derive-{attempt:03d}');attempt+=1
        output.mkdir(parents=True,exist_ok=bool(a.finish_existing))
        if not a.finish_existing:
            for source in original.glob('*.tar.*'):os.link(source,output/source.name)
        tree=output/'tree'
        with (output/'derive.log').open('a' if a.finish_existing else 'w') as log:
            if not a.finish_existing:
                subprocess.run(['dpkg-source','-x',str(dsc),str(tree)],stdout=log,stderr=subprocess.STDOUT,env=env,check=True)
                changelog=tree/'debian/changelog'
                entry=(f"{name} ({recipe['version']}) trixie; urgency=medium\n\n"
                   f"  * {recipe['reason']}.\n\n"
                   ' -- YYDaniel <yydaniel@localhost>  Wed, 28 Oct 2026 00:00:00 +0000\n\n')
                changelog.write_text(entry+changelog.read_text())
            # The transform's own command output joins the complete derive log.
                saved=os.dup(1);saved_err=os.dup(2)
                try:
                    os.dup2(log.fileno(),1);os.dup2(log.fileno(),2)
                    getattr(source_transforms,recipe['transform'])(tree)
                finally:
                    os.dup2(saved,1);os.dup2(saved_err,2);os.close(saved);os.close(saved_err)
                provenance=dict(origin_source=name,origin_version=item['version'],origin_dsc_sha256=expected,
                            recipe=recipe,transform_sha256=digest(Path(source_transforms.__file__)))
                (tree/'debian/arclight-build-recipe.json').write_text(json.dumps(provenance,indent=2)+'\n')
            # Preserve generated caches outside the source tree instead of
            # accidentally distributing them as source-package binaries.
            for i,cache in enumerate((tree/'debian').rglob('__pycache__')):
                if not cache.is_dir() or cache.is_symlink():continue
                assert cache.resolve().is_relative_to(tree.resolve())
                saved=output/'generated-bytecode'/str(i);saved.parent.mkdir(exist_ok=True)
                cache.rename(saved)
            subprocess.run(['dpkg-source','-b',str(tree)],cwd=output,stdout=log,stderr=subprocess.STDOUT,env=env,check=True)
        dsclist=list(output.glob('*.dsc'));assert len(dsclist)==1
        control=Parser().parsestr(dsclist[0].read_text())
        assert control['Source']==name and control['Version']==recipe['version']
        files=[]
        for line in control['Checksums-Sha256'].splitlines():
            if not line.strip():continue
            sha,size,filename=line.split();path=output/filename
            assert path.name==filename and digest(path)==sha and path.stat().st_size==int(size)
            files.append(dict(name=filename,size=int(size),sha256=sha))
        files.append(dict(name=dsclist[0].name,size=dsclist[0].stat().st_size,sha256=digest(dsclist[0])))
        record=dict(**provenance,source=name,version=recipe['version'],
                    relative_directory=str(output.relative_to(root)),files=files,
                    created=dt.datetime.now(dt.timezone.utc).isoformat())
        (output/'.source-verified.json').write_text(json.dumps(record,indent=2)+'\n')
        result[name]=record
        temp=ledger.with_suffix('.json.new');temp.write_text(json.dumps(list(result.values()),indent=2)+'\n');temp.replace(ledger)
        print('DERIVED',name,item['version'],'->',recipe['version'],flush=True)


if __name__=='__main__':main()
