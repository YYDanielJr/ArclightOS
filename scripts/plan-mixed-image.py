#!/usr/bin/env python3
"""Freeze authenticated distribution binaries and recorded local source builds."""
import argparse
import concurrent.futures
import datetime as dt
from email.parser import Parser
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import time
import sys
import urllib.request
from urllib.parse import unquote
import apt
from rebuild_plan import effective_packages
from apt_inputs import download_uris, allowed_list_file


def sha(p):
    with Path(p).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()


def evidence(p):
    p=Path(p).resolve()
    return dict(file=str(p),bytes=p.stat().st_size,sha256=sha(p))


def control(p):
    return Parser().parsestr(subprocess.check_output(['dpkg-deb','-f',str(p)],text=True))


def source_identity(c):
    m=re.fullmatch(r'(\S+)(?:\s+\(([^)]+)\))?',c.get('Source',c['Package']))
    assert m
    return m[1],m[2] or c['Version']


def write(p,v):
    t=p.with_suffix(p.suffix+'.new');t.write_text(json.dumps(v,indent=2)+'\n');t.replace(p)


p=argparse.ArgumentParser(description=__doc__)
p.add_argument('work',type=Path)
p.add_argument('--fetch',action='store_true')
p.add_argument('--from-release',action='store_true',help='Finalize explicitly recovered release inputs')
a=p.parse_args();work=a.work.resolve();root=work/'full-rebuild';out=work/'mixed-build'
out.mkdir(exist_ok=True);repo=Path(__file__).resolve().parents[1]
if a.from_release:
    subprocess.run([sys.executable,str(repo/'scripts/finalize-release-inputs.py'),str(work)],check=True)
    raise SystemExit(0)
release_config=json.loads((repo/'config/release.json').read_text())
sources_lock=json.loads((repo/'config/sources.lock.json').read_text())
policy=json.loads((repo/'config/build-policy.json').read_text())
assert policy['policy']=='apt-native-custom-source' and policy['custom_source_build_required']
plan=json.loads((root/'source-plan.json').read_text());packages=effective_packages(root,plan)
custom=json.loads((root/'custom-components.json').read_text())
cache=apt.Cache();selected=[];replacements=[];errors=[];proofs={}
native_names={b['binary'].split(':')[0] for item in packages for b in item['binaries']}
runtime_additions=json.loads((repo/'config/mixed-runtime-additions.json').read_text())['packages']
runtime_additions += [dict(package=n,source=n,version=v) for n,v in
                     sources_lock['open_base'].get('native_preinstalled',{}).items()]
for extra in runtime_additions:
    name=extra['package']
    if name in native_names:
        if extra.get('version'):
            for item in packages:
                for binary in item['binaries']:
                    if binary['binary'].split(':')[0]==name:
                        assert item['source']==extra['source']
                        binary['version']=extra['version']
        continue
    versions=[v for v in cache[name].versions if v.source_name==extra['source'] and
              any(o.trusted and o.origin in policy['native_repositories'] for o in v.origins)]
    if extra.get('version'):
        versions=[v for v in versions if v.version==extra['version']]
    if extra.get('version_from'):
        # Bind Qt runtime modules to the exact library that this planner will
        # select, including an authenticated same-source update of that library.
        library=next(b for item in packages for b in item['binaries'] if b['binary'].split(':')[0]==extra['version_from'])
        candidates=[v for v in cache[extra['version_from']].versions if v.source_name==extra['source'] and
                    any(o.trusted and o.origin in policy['native_repositories'] for o in v.origins)]
        exact=[v for v in candidates if v.version==library['version']]
        expected=(exact or candidates)[0].version
        versions=[v for v in versions if v.version==expected]
    if not versions:raise SystemExit('No authenticated matching runtime addition: '+name)
    v=versions[0]
    packages.append(dict(source=v.source_name,version=v.source_version,origin_source=v.source_name,
        origin_version=v.source_version,recipe={},binaries=[dict(binary=name,version=v.version,source=v.source_name)]))
    native_names.add(name)
records=[r for f in (root/'build').rglob('results.json') for r in json.loads(f.read_text()) if not r['exit_code']]


def build_proof(item):
    key=(item['source'],item['version'])
    if key in proofs:return proofs[key]
    dsc=next(f for f in item['files'] if f['name'].endswith('.dsc'))
    matches=[r for r in records if (r['source'],r['version'],r['dsc_sha256'])==(*key,dsc['sha256'])]
    assert matches,'No successful source build: '+repr(key)
    r=sorted(matches,key=lambda x:x['finished'])[-1];directory=Path(r['directory'])
    info=list(directory.glob('*.buildinfo'));logs=list(directory.glob('*.build'))
    assert info and logs,(key,'missing buildinfo/compiler log')
    inputs=[]
    for f in item['files']:
        path=item['directory']/f['name']
        assert path.stat().st_size==f['size'] and sha(path)==f['sha256'],path
        inputs.append(evidence(path))
    proof=dict(kind='source-build',source=key[0],source_version=key[1],dsc_sha256=dsc['sha256'],
               source_inputs=inputs,buildinfo=[evidence(f) for f in info],logs=[evidence(f) for f in logs],
               ledger=evidence(next(f for f in (root/'build').rglob('results.json') if r in json.loads(f.read_text()))),
               finished=r['finished'],artifacts=r['artifacts'])
    proofs[key]=proof;return proof


def compiled(item,binary):
    proof=build_proof(item);name=binary['binary'].split(':')[0]
    target=binary.get('rebuilt_binary',item['recipe'].get('binary_renames',{}).get(name,name))
    candidates=[]
    for artifact in proof['artifacts']:
        path=Path(artifact['file'])
        if path.suffix!='.deb' or not path.name.startswith(target+'_'):continue
        c=control(path)
        if c['Package']!=target or source_identity(c)!=(item['source'],item['version']):continue
        assert sha(path)==artifact['sha256'] and path.stat().st_size==artifact['bytes'],path
        candidates.append(dict(**artifact,package=target,architecture=c['Architecture'],version=c['Version'],
            source=item['source'],source_version=item['version'],provenance='source-build',
            build_proof=proof['dsc_sha256'],image_binary=name,image_version=binary['version']))
    assert len(candidates)==1,(target,len(candidates))
    if target!=name:replacements.append(dict(image_binary=name,package=target,architecture=candidates[0]['architecture']))
    return candidates[0]


for item in packages:
    local=item['source']!=item['origin_source'] or item['version']!=item['origin_version'] or item['source']=='grub2'
    for b in item['binaries']:
        try:
            if local:
                selected.append(compiled(item,b));continue
            name=b['binary'].split(':')[0];pkg=cache[b['binary']]
            def trusted(v):
                return any(o.trusted and o.origin in policy['native_repositories'] for o in v.origins)
            versions=[v for v in pkg.versions if v.version==b['version'] and trusted(v)]
            if not versions and policy['native_missing_version']=='authenticated-same-source-update':
                versions=[v for v in pkg.versions if v.source_name==b['source'] and trusted(v)]
            assert versions,'No authenticated binary from the same upstream source is available'
            v=versions[0]
            origins=[dict(origin=o.origin,site=o.site,archive=o.archive,component=o.component)
                     for o in v.origins if o.trusted and o.origin in policy['native_repositories']]
            assert origins,'No authenticated Debian/Pi repository'
            digest=v.record['SHA256'];size=int(v.record['Size'])
            uris=download_uris(v.uris)
            assert uris and re.fullmatch('[0-9a-f]{64}',digest)
            selected.append(dict(package=name,architecture=v.architecture,version=v.version,
                source=v.source_name,source_version=v.source_version,bytes=size,sha256=digest,
                file=str(out/'debs'/unquote(Path(uris[0]).name)),uris=uris,provenance='authenticated-apt',
                repositories=origins,image_binary=name,image_version=b['version'],
                version_change_reason='Original version superseded in the signed repository; using the current same-source distribution binary' if v.version!=b['version'] else None))
        except Exception as error:
            errors.append(dict(binary=b['binary'],version=b['version'],error=str(error)))

# Project packages have standard buildinfo/checksums, except the dependency-only
# kernel metapackages, whose exact packaging recipe and log are retained.
dist=work/'dist'
source_archives=[evidence(dist/n) for n in (release_config['source_archive'],
    f'linux-source-{sources_lock["kernel"]["release"]}.tar.xz')]
for b in custom:
    try:
        files=list(dist.glob(b['binary']+'_'+b['version'].split(':')[-1]+'_*.deb'));assert len(files)==1
        path=files[0];c=control(path);assert source_identity(c)==(b['source'],b['source_version'])
        assert c['Version']==b['version']
        info=[]
        for f in dist.glob('*.buildinfo'):
            record=Parser().parsestr(f.read_text())
            if record['Source']==b['source'] and record['Version']==b['source_version']:info.append(f)
        if b['source']=='ascalon-kernel':
            logs=[work/'logs/kernel-build.log'];assert not c.get('Depends','').startswith('python')
        else:
            assert info,(b['source'],'missing buildinfo')
            checks=[line.split() for f in info for line in Parser().parsestr(f.read_text())['Checksums-Sha256'].splitlines() if line.strip()]
            assert any(n==path.name and h==sha(path) and int(s)==path.stat().st_size for h,s,n in checks),path
            logname={'ascalon-linux':'kernel-build.log','arclight-desktop':'desktop-build.log',
                     'arclight-live':'live-build.log','arclight-branding':'branding-build.log'}[b['source']]
            logs=[work/'logs'/logname]
        key=(b['source'],b['source_version'])
        proofs[key]=dict(kind='project-source-build',source=key[0],source_version=key[1],
            source_inputs=source_archives,buildinfo=[evidence(f) for f in info],logs=[evidence(f) for f in logs],
            packaging_recipe=evidence(repo/'scripts/package-kernel-meta.py') if key[0]=='ascalon-kernel' else None)
        selected.append(dict(**evidence(path),package=c['Package'],architecture=c['Architecture'],version=c['Version'],
            source=key[0],source_version=key[1],provenance='source-build',custom=True,
            image_binary=c['Package'],image_version=c['Version'],build_proof='project:'+':'.join(key)))
    except Exception as error:errors.append(dict(binary=b['binary'],version=b['version'],error=str(error)))

keys=[(s['package'],s['architecture']) for s in selected];assert len(keys)==len(set(keys))
snapshot=out/'apt-snapshot';snapshot.mkdir(exist_ok=True)
for directory,target in [(Path('/var/lib/apt/lists'),snapshot/'lists')]:
    target.mkdir(exist_ok=True)
    for f in directory.iterdir():
        if f.is_file() and f.name!='lock' and allowed_list_file(f.name):shutil.copy2(f,target/f.name)
# Do not copy unrelated/private host repository configurations into evidence.
write(snapshot/'repository-selection.json', dict(repositories=sorted({u.rsplit('/pool/',1)[0]
    for s in selected if s['provenance']=='authenticated-apt' for u in s['uris']})))
keys_dir=snapshot/'keyrings';keys_dir.mkdir(exist_ok=True)
for name in ('debian-archive-keyring.pgp','raspberrypi-archive-keyring.pgp'):
    shutil.copy2(Path('/usr/share/keyrings')/name,keys_dir/name)
receipt=dict(schema='arclight.image-inputs.v1',policy=policy['policy'],policy_sha256=sha(repo/'config/build-policy.json'),
    created=dt.datetime.now(dt.timezone.utc).isoformat(),complete=False,
    native_full_source_rebuild_required=False,custom_source_builds_checked=True,
    plan_sha256=sha(root/'source-plan.json'),extension_plan_sha256=sha(root/'source-plan-extension.json'),
    custom_manifest_sha256=sha(root/'custom-components.json'),source_builds=list(proofs.values()),
    apt_snapshot=[evidence(f) for f in snapshot.rglob('*') if f.is_file()],
    required_binaries=sum(len(s['binaries']) for s in packages)+len(custom),selected=selected,
    replaced_binaries=replacements,errors=errors)
# Drivers are an optional offline payload, not preinstalled on the Hyper-V host.
# Their closed userspace/firmware remain explicitly identified vendor inputs.
nv=json.loads((repo/'config/sources.lock.json').read_text())['nvidia']
nv_inputs=[work/'sources/nvidia'/f"open-gpu-kernel-modules-{nv['version']}.tar.gz",
           work/'sources/nvidia'/f"NVIDIA-Linux-x86_64-{nv['version']}.run"]
assert sha(nv_inputs[0])==nv['source_sha256'] and sha(nv_inputs[1])==nv['binary_sha256']
drivers=[]
for name in ('arclight-nvidia-userspace','arclight-nvidia-open-dkms','arclight-nvidia-driver'):
    path=dist/f"{name}_{nv['debian_version']}_amd64.deb";c=control(path)
    assert c['Package']==name and c['Version']==nv['debian_version']
    drivers.append(dict(**evidence(path),package=name,version=c['Version'],architecture=c['Architecture']))
receipt['bundled_drivers']=dict(packages=drivers,installed_in_live_image=False,
    open_module_source=evidence(dist/f"arclight-nvidia-open-source-{nv['version']}.tar.xz"),
    official_closed_userspace_and_firmware=evidence(nv_inputs[1]),
    build_log=evidence(work/'logs/nvidia-build.log'),
    kernel_build_logs=[evidence(work/'logs'/f'nvidia-modules-{r}.log') for r in (sources_lock['kernel']['release'],release_config['fallback_kernel'])],
    hardware_validation='deferred until installation on physical NVIDIA hardware')
write(out/'image-inputs.json',receipt)
print(json.dumps(dict(required=receipt['required_binaries'],selected=len(selected),
    apt=sum(s['provenance']=='authenticated-apt' for s in selected),compiled=sum(s['provenance']=='source-build' for s in selected),errors=errors),indent=2),flush=True)
if errors:raise SystemExit(1)
if not a.fetch:raise SystemExit(0)
(out/'debs').mkdir(exist_ok=True)


def fetch(s):
    target=Path(s['file'])
    if s['provenance']!='authenticated-apt':return
    for cached in (target,Path('/var/cache/apt/archives')/target.name):
        if cached.is_file() and cached.stat().st_size==s['bytes'] and sha(cached)==s['sha256']:
            if cached!=target:shutil.copy2(cached,target)
            return
    temp=target.with_suffix('.deb.partial')
    for attempt in range(3):
        try:
            req=urllib.request.Request(s['uris'][attempt%len(s['uris'])],headers={'User-Agent':'Arclight-ImageBuilder/1'})
            with urllib.request.urlopen(req,timeout=120) as src,temp.open('wb') as dst:shutil.copyfileobj(src,dst,1024*1024)
            assert temp.stat().st_size==s['bytes'] and sha(temp)==s['sha256'],target.name+' differs from authenticated index'
            temp.replace(target);return
        except Exception:
            if attempt==2:raise
            time.sleep(2)


with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
    futures={pool.submit(fetch,s):s for s in selected}
    for n,f in enumerate(concurrent.futures.as_completed(futures),1):
        try:f.result()
        except Exception as error:errors.append(dict(binary=futures[f]['package'],error=str(error)))
        if n%50==0:print('Verified inputs',n,'/',len(selected),flush=True)
for s in selected:
    if Path(s['file']).is_file() and sha(s['file'])==s['sha256']:continue
    errors.append(dict(binary=s['package'],error='Final artifact verification failed'))
receipt.update(complete=not errors and len(selected)==receipt['required_binaries'],errors=errors)
write(out/'image-inputs.json',receipt)
print('Mixed image inputs complete:',receipt['complete'],flush=True)
raise SystemExit(0 if receipt['complete'] else 1)
