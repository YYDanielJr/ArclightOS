#!/usr/bin/env python3
"""Prepare, build and optionally install a same-series upstream stable update.

Known patch stacks are tried exactly. Conflicts stop the pipeline; this tool
never invents a semantic port, uses patch fuzz, or reboots the workstation.
"""
import argparse
import datetime as dt
from email.parser import Parser
import fcntl
import hashlib
import json
import lzma
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import tarfile
import time
import urllib.request
from kernel_patchset import apply_stack, load_stack, affected_files, compare_pristine, restore_upstream_links, sha

REPO = Path(__file__).resolve().parents[1]
SIGNERS = ('647F28654894E3BD457199BE38DBBDC86092693E', 'E27E5D8A3403A2EF66873BBCDEA66FF797772CDC')


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix+'.new')
    temp.write_text(json.dumps(value, indent=2, ensure_ascii=False)+'\n')
    temp.replace(path)


def fetch(path, urls, expected=None):
    if path.is_file():
        if expected and sha(path) != expected:
            raise ValueError('Cached input hash mismatch: '+str(path))
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    failures = []
    for url in urls:
        try:
            temporary = path.with_name(path.name+'.partial')
            with urllib.request.urlopen(url, timeout=45) as response, temporary.open('wb') as target:
                if response.status != 200:
                    raise ValueError('Expected complete HTTP 200')
                shutil.copyfileobj(response, target, 2**20)
            if expected and sha(temporary) != expected:
                raise ValueError('Downloaded SHA256 mismatch')
            temporary.replace(path)
            print('Verified download:', path.name, sha(path), flush=True)
            return path
        except Exception as error:
            failures.append(url+': '+str(error))
    raise RuntimeError('\n'.join(failures))


def parse_config(path):
    values = {}
    for line in path.read_text().splitlines():
        match = re.fullmatch(r'(CONFIG_\w+)=(.*)', line)
        disabled = re.fullmatch(r'# (CONFIG_\w+) is not set', line)
        if match: values[match[1]] = match[2]
        elif disabled: values[disabled[1]] = 'n'
    return values


class Update:
    def __init__(self, args):
        self.args, self.work = args, args.work.resolve()
        self.source = self.work/'sources'
        self.logs = self.work/'logs'
        self.repo = self.work/'repo'
        self.tree = self.work/'build'/('linux-'+args.version)
        self.release = args.version+'-ascalonkernel'
        self.obj = self.work/'build'/('obj-'+self.release)
        self.statefile = self.work/'kernel-update.json'
        for path in (self.work, self.source, self.logs, self.work/'build', self.work/'dist'):
            path.mkdir(parents=True, exist_ok=True)
        self.state = json.loads(self.statefile.read_text()) if self.statefile.exists() else dict(
            schema='arclight.kernel-update.v1', version=args.version, release=self.release,
            debian_version=args.version+'-1+arclight1', source_date_epoch=int(time.time())//86400*86400,
            stages={}, boot_tested=False, running_kernel=os.uname().release)
        if self.state['version'] != args.version or self.state['release'] != self.release:
            raise ValueError('Workspace belongs to another kernel update')
        self.env = {**os.environ, 'LC_ALL':'C', 'PYTHONDONTWRITEBYTECODE':'1', 'ARCLIGHT_WORK':str(self.work)}
        self.env.update(KBUILD_BUILD_USER='arclight',KBUILD_BUILD_HOST='arclight-builder',
            SOURCE_DATE_EPOCH=str(self.state['source_date_epoch']))
        self.env.pop('PYTHONOPTIMIZE', None)
        if args.tools_root:
            root = args.tools_root.resolve()
            self.env.update(ARCLIGHT_TOOLS=str(root), PATH=str(root/'usr/bin')+':'+str(root/'usr/sbin')+':'+os.environ['PATH'],
                LD_LIBRARY_PATH=str(root/'usr/lib/x86_64-linux-gnu'), LIBRARY_PATH=str(root/'usr/lib/x86_64-linux-gnu'),
                CPATH=str(root/'usr/include')+':'+str(root/'usr/include/x86_64-linux-gnu'),
                PKG_CONFIG_PATH=str(root/'usr/lib/x86_64-linux-gnu/pkgconfig'), BISON_PKGDATADIR=str(root/'usr/share/bison'))

    def run(self, command, logfile, cwd=None, build=False):
        log = self.logs/logfile
        if log.exists():
            number = 1
            while log.with_name(log.name+f'.attempt-{number}').exists(): number += 1
            log.rename(log.with_name(log.name+f'.attempt-{number}'))
        command = list(map(str, command))
        print('Running:', ' '.join(command), 'log:', log, flush=True)
        with log.open('x') as output:
            child = subprocess.Popen(command, cwd=cwd or REPO, env=self.env, stdout=output,
                stderr=subprocess.STDOUT, start_new_session=True, umask=0o022)
            try:
                while child.poll() is None:
                    try: child.wait(timeout=15)
                    except subprocess.TimeoutExpired:
                        if build:
                            mem = dict(l.split(':',1) for l in Path('/proc/meminfo').read_text().splitlines())
                            if shutil.disk_usage(self.work).free < 12*2**30 or int(mem['MemAvailable'].split()[0]) < 1536*1024:
                                raise RuntimeError('Build resource reserve reached; keeping logs and inputs')
                        print('Still running:', logfile, log.stat().st_size, 'bytes', flush=True)
            except BaseException:
                os.killpg(child.pid, signal.SIGTERM)
                try: child.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(child.pid, signal.SIGKILL); child.wait()
                raise
        if child.returncode: raise RuntimeError(f'Exit {child.returncode}: {log}')

    def signature(self, archive, signature):
        home = self.source/'gnupg'; home.mkdir(mode=0o700, exist_ok=True)
        for fp in SIGNERS:
            key = fetch(self.source/(fp+'.asc'), ['https://keys.openpgp.org/vks/v1/by-fingerprint/'+fp])
            info = subprocess.check_output(['gpg','--homedir',str(home),'--batch','--with-colons','--show-keys',str(key)],text=True)
            if 'fpr:::::::::'+fp+':' not in info: raise ValueError('Release signing-key fingerprint mismatch')
            self.run(['gpg','--homedir',home,'--batch','--import',key], 'key-import-'+fp+'.log')
            present = subprocess.run(['gpg','--homedir',str(home),'--batch','--list-keys',fp], capture_output=True)
            if present.returncode:
                # keys.openpgp.org can omit unverified UIDs; GnuPG then skips
                # the key. A different transport is safe only after matching
                # the independently pinned full primary fingerprint again.
                key = fetch(self.source/(fp+'.full.asc'),
                    ['https://keyserver.ubuntu.com/pks/lookup?op=get&search=0x'+fp])
                info = subprocess.check_output(['gpg','--homedir',str(home),'--batch','--with-colons','--show-keys',str(key)],text=True)
                if 'fpr:::::::::'+fp+':' not in info: raise ValueError('Fallback signing-key fingerprint mismatch')
                self.run(['gpg','--homedir',home,'--batch','--import',key], 'key-import-full-'+fp+'.log')
        with lzma.open(archive, 'rb') as unpacked, (self.logs/'upstream-signature.log').open('wb') as log:
            verifier = subprocess.Popen(['gpg','--homedir',str(home),'--batch','--status-fd','1','--verify',str(signature),'-'],
                stdin=subprocess.PIPE, stdout=log, stderr=subprocess.STDOUT)
            try:
                shutil.copyfileobj(unpacked, verifier.stdin, 2**20)
                verifier.stdin.close()
                code = verifier.wait()
            except BaseException:
                verifier.kill(); verifier.wait(); raise
        text = (self.logs/'upstream-signature.log').read_text()
        if code or not any('[GNUPG:] VALIDSIG ' in line and any(fp in line for fp in SIGNERS) for line in text.splitlines()):
            raise ValueError('Upstream developer signature failed')

    def prepare(self):
        if self.state['stages'].get('prepare'):
            if sha(self.source/('linux-'+self.args.version+'.tar.xz')) != self.state['upstream_sha256']:
                raise ValueError('Prepared source archive changed')
            return
        if self.repo.exists() or self.tree.exists():
            raise ValueError('Incomplete preparation retained; use a new workspace after inspecting the failure')
        if shutil.disk_usage(self.work).free < 60*2**30: raise ValueError('Need at least 60 GiB free for debug-enabled kernel staging and reserve')
        original = json.loads((REPO/'config/sources.lock.json').read_text())
        current = tuple(int(x) for x in original['kernel']['version'].split('.'))
        target = tuple(int(x) for x in self.args.version.split('.'))
        if current[:2] != target[:2] or target <= current+(0,)*(3-len(current)):
            raise ValueError('Automatic update only accepts a newer patchlevel in the current series')
        major = str(target[0]); base = 'https://cdn.kernel.org/pub/linux/kernel/v'+major+'.x/'
        sums = fetch(self.source/'sha256sums.asc', [base+'sha256sums.asc'])
        filename = 'linux-'+self.args.version+'.tar.xz'
        found = re.findall(r'^([a-f0-9]{64})\s+'+re.escape(filename)+r'\s*$', sums.read_text(), re.M)
        if len(found) != 1: raise ValueError('Target is absent from official checksums')
        digest = found[0]
        mirrors = ['https://mirrors.ustc.edu.cn/kernel.org/linux/kernel/v'+major+'.x/'+filename,
                   'https://mirrors.nju.edu.cn/kernel.org/linux/kernel/v'+major+'.x/'+filename, base+filename]
        archive = fetch(self.source/filename, mirrors, digest)
        signature = fetch(self.source/('linux-'+self.args.version+'.tar.sign'), [base+'linux-'+self.args.version+'.tar.sign'])
        self.signature(archive, signature)
        export = 'arclightos-source-kernel-'+self.args.version+'-input.tar.xz'
        env = self.env; self.env = env | {'SOURCE_EXPORT_NAME':export}
        self.run(['bash',REPO/'scripts/export-source.sh'], 'project-snapshot.log')
        self.env = env
        self.repo.mkdir()
        with tarfile.open(self.work/'dist'/export) as tar: tar.extractall(self.repo, filter='data')
        with tarfile.open(archive) as tar: tar.extractall(self.work/'build', filter='data')
        restore_upstream_links(self.tree,archive,self.logs/'upstream-links-restored.json')
        stack = load_stack(self.repo/'kernel',self.args.version)
        apply_stack(self.tree, stack, dict(version=self.args.version,sha256=digest), self.logs/'patch-application.json')
        lock = json.loads((self.repo/'config/sources.lock.json').read_text())
        lock['kernel'].update(version=self.args.version, release=self.release, filename=filename, url=mirrors[0],
            upstream=base+filename, sha256=digest, debian_version=self.state['debian_version'],
            meta_debian_version=self.state['debian_version'], source_date_epoch=self.state['source_date_epoch'])
        write(self.repo/'config/sources.lock.json', lock)
        previous_notes = json.loads((REPO/'kernel/maintenance.json').read_text())
        previous = next(r for r in previous_notes['artifacts'] if r['file'].startswith('configs/config-') and not r['file'].endswith('.json'))
        config = REPO/'kernel'/previous['file']
        if sha(config) != previous['sha256']: raise ValueError('Previous verified config changed')
        self.obj.mkdir()
        shutil.copy2(config, self.obj/'.config')
        self.run([self.tree/'scripts/config','--file',self.obj/'.config','--set-str','LOCALVERSION','-ascalonkernel',
                  '--disable','LOCALVERSION_AUTO'], 'config-release.log')
        self.run(['make','-C',self.tree,'O='+str(self.obj),'olddefconfig'], 'olddefconfig.log')
        effective = parse_config(self.obj/'.config')
        for symbol,value in dict(CONFIG_SCHED_BORE='y',CONFIG_PREEMPT_DYNAMIC='y',CONFIG_HZ='1000',
                                 CONFIG_BLK_DEV_NVME='y',CONFIG_HYPERV='y',CONFIG_CPU_MITIGATIONS='y').items():
            if effective.get(symbol) != value: raise ValueError('Required kernel configuration changed: '+symbol)
        old = parse_config(config)
        differences = [dict(symbol=k,before=old.get(k),after=effective.get(k)) for k in sorted(old.keys()|effective.keys()) if old.get(k)!=effective.get(k)]
        write(self.logs/'configuration-diff.json',dict(previous_release=original['kernel']['release'],target_release=self.release,
            changes=differences,required_config_checks_passed=True))
        if differences and self.args.accept_config_diff!=sha(self.logs/'configuration-diff.json'):
            raise ValueError('Configuration symbols changed: review configuration-diff.json, then use its SHA256 '
                             'with --accept-config-diff in a fresh workspace; refusing unattended defaults')
        self.state.update(upstream_sha256=digest,previous_kernel=original['kernel'],configuration_changes=len(differences))
        self.notes(lock, previous_notes, differences)
        self.run([sys.executable,self.repo/'scripts/install-kernel-notes.py',self.tree], 'kernel-notes.log')
        self.state['stages']['prepare'] = True
        write(self.statefile,self.state)

    def notes(self, lock, previous, differences):
        root = self.repo/'kernel'; config = root/'configs'/('config-'+self.release)
        shutil.copy2(self.obj/'.config',config)
        audit = config.with_name(config.name+'.audit.json')
        write(audit,dict(schema='arclight.kernel-update-config.v1',previous_kernel=self.state['previous_kernel'],
                        target_kernel=lock['kernel'],changes=differences,config_sha256=sha(config)))
        historical = root/'history'; historical.mkdir(exist_ok=True)
        old_name = self.state['previous_kernel']['release']+'.md'
        old_manifest=self.state['previous_kernel']['release']+'.json'
        write(historical/old_manifest,previous)
        old_text=((historical/old_name) if (historical/old_name).exists() else root/'UPSTREAM-CHANGES.md').read_text().replace('](maintenance.json)',']('+old_manifest+')')
        old_text=re.sub(r'\]\((configs/[^)]+|patches/[^)]+)\)',r'](../\1)',old_text)
        old_text=re.sub(r'\]\(history/([^)]+)\)',r'](\1)',old_text)
        (historical/old_name).write_text(old_text)
        changed='\n'.join('- `'+p['file']+'`' for p in previous['bore']['published_files'])
        (root/'UPSTREAM-CHANGES.md').write_text('# AscalonKernel '+self.release+' 上游修改清单\n\n'
            f'本版从全新的 Linux **{self.args.version}** 正式源码开始，上一版为 '
            f'`{self.state["previous_kernel"]["release"]}`。上游 stable 修复与本地补丁分别记录。\n\n'
            f'- 原始归档 SHA256：`{self.state["upstream_sha256"]}`；开发者签名另行验证。\n'
            f'- Debian 包版本：`{self.state["debian_version"]}`；ABI：`{self.release}`。\n'
            '- 本地 Linux 实现补丁仅有现存 BORE 移植，严格应用原文件，未改写算法、未使用 fuzz 或三方自动合并。\n'
            '- [补丁顺序与固定哈希](patches/series.json)、[完整补丁](patches/0001-bore-mainline.patch)、'
            '[机器可读来源与逐文件哈希](maintenance.json)。\n'
            f'- 相对上次已验证配置有 **{len(differences)}** 项符号差异，见 '
            f'[逐符号审计](configs/{audit.name})；[实际完整配置](configs/{config.name})。\n'
            '- 必要的 BORE、动态抢占、1000 Hz、安全缓解、NVMe 内建与 Hyper-V 配置已检查。\n'
            '- ABI/DEB 包装、构建来源说明不是 Linux 算法补丁；NVIDIA 开放模块在内核树外单独编译和记录。\n'
            f'- BORE 来源、九行 Cachy 专用上下文移除、配置请求与包装的详细理由见 '
            f'[上一版完整记录](history/{old_name})，不重复伪造为本版新改动。\n\n'
            '## 补丁实际涉及的文件\n\n'+changed+'\n\n'
            '## 证据边界\n\n构建、五个 NVIDIA 模块验证、安装、实体启动和睡眠是不同阶段。'
            '具体结果见发行附件中的 kernel-update.json 与独立验收记录；'
            '文档写入源码或编译完成不代表实体启动、性能或稳定性验收通过。\n')
        metadata = dict(previous)
        metadata['bore']=dict(previous['bore'])
        metadata['bore']['published_files']=[dict(file=p['file'],sha256=sha(self.tree/p['file']))
                                             for p in previous['bore']['published_files']]
        metadata['kernel'] = {k:lock['kernel'][k] for k in ('version','release','debian_version','sha256','upstream')}
        metadata['audited_release'] = dict(id='kernel-'+self.args.version,config_sha256=sha(config),
            installed_config_matches=False,full_pristine_tree_comparison_performed=False)
        metadata['artifacts'] = [dict(file=str(p.relative_to(root)),bytes=p.stat().st_size,sha256=sha(p))
            for p in sorted((root/'patches').iterdir()) if p.is_file()]+[
            dict(file=str(p.relative_to(root)),bytes=p.stat().st_size,sha256=sha(p)) for p in (config,audit)]
        write(root/'maintenance.json', metadata)
        (root/'README.md').write_text('# AscalonKernel source maintenance records\n\n'
            f'Current prepared kernel: `{self.release}`. Read [UPSTREAM-CHANGES.md](UPSTREAM-CHANGES.md).\n\n'
            'The complete upstream source lives in the corresponding-source archive, not this directory.\n'
            f'Current configuration: [configs/config-{self.release}](configs/config-{self.release}).\n'
            'Earlier configuration snapshots and change records remain in configs/ and history/.\n')

    def build(self):
        if self.state['stages'].get('build'): return
        self.env.update(KBUILD_BUILD_USER='arclight',KBUILD_BUILD_HOST='arclight-builder',
            SOURCE_DATE_EPOCH=str(self.state['source_date_epoch']),
            KBUILD_BUILD_TIMESTAMP=dt.datetime.fromtimestamp(self.state['source_date_epoch'],dt.timezone.utc).strftime('%Y-%m-%d %H:%M:%S +0000'),
            KDEB_PKGVERSION=self.state['debian_version'],KDEB_SOURCENAME='ascalon-linux',KDEB_COMPRESS='zstd')
        command = ['make','-C',self.tree,'O='+str(self.obj),'-j'+str(self.args.jobs),'bindeb-pkg']
        if self.args.tools_root: command += ['DPKG_FLAGS=--no-check-builddeps']
        self.run(command,'kernel-build.log',build=True)
        for file in (self.work/'build').glob('*_'+self.state['debian_version']+'_*'):
            if file.suffix in ('.deb','.buildinfo','.changes'): shutil.copy2(file,self.work/'dist'/file.name)
        self.run([sys.executable,self.repo/'scripts/package-kernel-meta.py'],'kernel-meta.log')
        shutil.copy2(self.obj/'.config',self.work/'dist'/('config-'+self.release))
        self.state['stages']['build'] = True; write(self.statefile,self.state)

    def nvidia(self):
        if self.state['stages'].get('nvidia'): return
        lock=json.loads((self.repo/'config/sources.lock.json').read_text())['nvidia']
        source=self.source/('open-gpu-kernel-modules-'+lock['version']+'.tar.gz')
        patch=self.source/'nvidia-sysfs-7.3.patch'
        # Reuse only exact, hash-checked inputs, never old compiled modules.
        for old in REPO.glob('.local/iso-*/sources/nvidia/'+source.name):
            if old.is_file() and sha(old)==lock['source_sha256']:
                shutil.copy2(old,source);break
        fetch(source,[lock['source_url']],lock['source_sha256'])
        fetch(patch,[lock['compatibility_patch_url']],lock['compatibility_patch_sha256'])
        directory=self.work/'build/nvidia-validation'
        if directory.exists(): raise ValueError('Partial NVIDIA validation retained; use a fresh validation directory')
        directory.mkdir()
        with tarfile.open(source) as tar:
            top=tar.getmembers()[0].name.split('/')[0]
            tar.extractall(directory,filter='data')
        tree=directory/top
        apply_stack(tree,[dict(id='nvidia-sysfs-compatibility',file=patch,sha256=lock['compatibility_patch_sha256'])],
                    dict(version=lock['version'],source_sha256=lock['source_sha256']),self.logs/'nvidia-patch-application.json')
        self.run(['make','-C',tree,'-j'+str(self.args.jobs),'KERNEL_UNAME='+self.release,
                  'SYSSRC='+str(self.tree),'SYSOUT='+str(self.obj),'modules'],'nvidia-modules.log',build=True)
        modules=[]
        for name in ('nvidia','nvidia-modeset','nvidia-drm','nvidia-uvm','nvidia-peermem'):
            file=tree/'kernel-open'/(name+'.ko')
            vermagic=subprocess.check_output(['modinfo','-F','vermagic',str(file)],text=True).strip()
            version=subprocess.check_output(['modinfo','-F','version',str(file)],text=True).strip()
            if not vermagic.startswith(self.release+' ') or version!=lock['version']:
                raise ValueError('NVIDIA module release/version mismatch')
            modules.append(dict(module=name,sha256=sha(file),vermagic=vermagic,version=version))
        write(self.logs/'nvidia-module-validation.json',dict(passed=True,kernel=self.release,modules=modules,
            clean_source=True,hardware_loading_tested=False,source_sha256=sha(source),patch_sha256=sha(patch)))
        self.state['stages']['nvidia']=True;write(self.statefile,self.state)

    def finish(self):
        if self.state['stages'].get('finish'): return
        # Refresh evidence after all build gates; this does not alter Linux code.
        lock=json.loads((self.repo/'config/sources.lock.json').read_text())
        history=self.repo/'kernel/history'/(self.state['previous_kernel']['release']+'.json')
        previous=json.loads(history.read_text()) if history.exists() else json.loads((REPO/'kernel/maintenance.json').read_text())
        series=REPO/'kernel/patches/series.json'
        if series.exists():shutil.copy2(series,self.repo/'kernel/patches/series.json')
        self.notes(lock,previous,json.loads((self.logs/'configuration-diff.json').read_text())['changes'])
        apply_stack(self.tree,load_stack(self.repo/'kernel',self.args.version),
                    dict(version=self.args.version,sha256=self.state['upstream_sha256']),self.logs/'patch-application-final.json')
        self.run([sys.executable,REPO/'scripts/install-kernel-notes.py',self.tree,'--repo',self.repo], 'kernel-notes-final.log')
        comparison=self.logs/'pristine-source-comparison.json'
        restore_upstream_links(self.tree,self.source/('linux-'+self.args.version+'.tar.xz'),self.logs/'upstream-links-restored-final.json')
        compare_pristine(self.tree,self.source/('linux-'+self.args.version+'.tar.xz'),
                         affected_files(self.tree,load_stack(self.repo/'kernel',self.args.version)),comparison)
        audit=self.repo/'kernel/audits'/('linux-'+self.args.version+'-source.json');audit.parent.mkdir(exist_ok=True)
        shutil.copy2(comparison,audit)
        metadata=json.loads((self.repo/'kernel/maintenance.json').read_text())
        metadata['audited_release'].update(full_pristine_tree_comparison_performed=True,source_comparison_sha256=sha(audit))
        metadata['artifacts'].append(dict(file=str(audit.relative_to(self.repo/'kernel')),bytes=audit.stat().st_size,sha256=sha(audit)))
        write(self.repo/'kernel/maintenance.json',metadata)
        entry=self.repo/'kernel/UPSTREAM-CHANGES.md'
        with entry.open('a') as stream:stream.write('\n原始上游归档的逐文件内容比较已通过，Linux 实现差异仅限上述补丁路径。'
            f'完整计数、前后哈希和说明文件排除清单见 [源码比较审计](audits/{audit.name})。\n')
        self.run([sys.executable,REPO/'scripts/install-kernel-notes.py',self.tree,'--repo',self.repo], 'kernel-notes-audited.log')
        target=self.work/'dist'/('linux-source-'+self.release+'.tar.xz')
        if target.exists(): raise ValueError('Refusing to overwrite a frozen corresponding-source archive')
        recipe=self.work/'build/build-ascalon.sh'
        recipe.write_text('#!/bin/bash\nset -euo pipefail\ncd "$(dirname "$0")"\n'
            'export KBUILD_BUILD_USER=arclight KBUILD_BUILD_HOST=arclight-builder\n'
            f'export KDEB_PKGVERSION={self.state["debian_version"]} KDEB_SOURCENAME=ascalon-linux KDEB_COMPRESS=zstd\n'
            f'export SOURCE_DATE_EPOCH={self.state["source_date_epoch"]}\n'
            'export KBUILD_BUILD_TIMESTAMP="$(date -u -d "@$SOURCE_DATE_EPOCH" "+%Y-%m-%d %H:%M:%S +0000")"\n'
            'make olddefconfig\nmake -j"${JOBS:-3}" bindeb-pkg\n')
        recipe.chmod(0o755)
        def metadata(item):
            if Path(item.name).name=='.arclight-patchset.json': return None
            item.uid=item.gid=0;item.uname=item.gname='';item.mtime=self.state['source_date_epoch'];return item
        partial=target.with_name(target.name+'.partial')
        with tarfile.open(partial,'x:xz',preset=1) as tar:
            root='linux-'+self.args.version
            tar.add(self.tree,arcname=root,filter=metadata)
            tar.add(self.obj/'.config',arcname=root+'/.config',filter=metadata)
            tar.add(recipe,arcname=root+'/build-ascalon.sh',filter=metadata)
            tar.add(self.repo/'config/sources.lock.json',arcname=root+'/arclight-sources.lock.json',filter=metadata)
        partial.rename(target)
        packages=[]
        compiled={}
        for info in (self.work/'dist').glob('*.buildinfo'):
            fields=Parser().parsestr(info.read_text())
            for row in fields.get('Checksums-Sha256','').splitlines():
                if row.strip():
                    digest,size,name=row.split();compiled[name]=(digest,int(size))
        for file in sorted((self.work/'dist').glob('*.deb')):
            name=subprocess.check_output(['dpkg-deb','-f',str(file),'Package'],text=True).strip()
            if name=='linux-libc-dev' or name.endswith('-dbg'): continue
            if name.startswith(('linux-image-','linux-headers-')) and compiled.get(file.name)!=(sha(file),file.stat().st_size):
                raise ValueError('Kernel package differs from its compiler buildinfo: '+file.name)
            packages.append(dict(file=str(file),package=name,bytes=file.stat().st_size,sha256=sha(file)))
        if not any(p['package']=='linux-image-'+self.release for p in packages) or not any(p['package']=='linux-headers-'+self.release for p in packages):
            raise ValueError('Kernel image/headers missing from build outputs')
        artifact=dict(schema='arclight.kernel-build-artifacts.v1',passed=True,kernel=self.release,
            version=self.state['debian_version'],packages=packages,source_archive=dict(file=str(target),sha256=sha(target)),
            nvidia_validation_sha256=sha(self.logs/'nvidia-module-validation.json'),
            upstream_signature_sha256=sha(self.logs/'upstream-signature.log'),boot_tested=False)
        environment={name:subprocess.check_output([name,'--version'],env=self.env,text=True).splitlines()[0]
                     for name in ('gcc','make','bison','flex')}
        if self.args.tools_root:
            manifest=self.args.tools_root.resolve().parent/'packages.json'
            if not manifest.is_file():raise ValueError('Unpacked tools require their authenticated package manifest')
            environment['unpacked_tools_manifest_sha256']=sha(manifest)
        artifact['build_environment']=environment
        write(self.work/'dist/kernel-build-artifacts.json',artifact)
        self.state['stages']['finish']=True;self.state['artifacts']=artifact;write(self.statefile,self.state)
        write(self.work/'dist/kernel-update.json',self.state)

    def promote(self):
        current=json.loads((REPO/'config/sources.lock.json').read_text())
        candidate=json.loads((self.repo/'config/sources.lock.json').read_text())
        if current['bore']['sha256']!=candidate['bore']['sha256']:raise ValueError('Repository patch input changed during the build')
        if sha(REPO/'kernel/patches/series.json')!=sha(self.repo/'kernel/patches/series.json'):
            raise ValueError('Repository patch series changed during the build')
        if current['kernel']['release'] not in (self.state['previous_kernel']['release'],self.release):
            raise ValueError('Another kernel update changed the repository')
        current['kernel']=candidate['kernel'];write(REPO/'config/sources.lock.json',current)
        shutil.copytree(self.repo/'kernel',REPO/'kernel',dirs_exist_ok=True)
        self.state['repository_promoted']=True;write(self.statefile,self.state)

    def cleanup(self):
        if self.args.keep_objects or self.state.get('objects_cleaned'):return
        # All compiler children finished; source, recipe, hashes, logs and five
        # NVIDIA-module checks have already been frozen successfully.
        if not self.state['stages'].get('finish'):raise ValueError('Cannot clean an unverified build')
        removed=[]
        for directory in (self.work/'build',self.work/'dist'):
            for file in directory.glob('*.deb'):
                name=subprocess.check_output(['dpkg-deb','-f',str(file),'Package'],text=True).strip()
                if name.endswith('-dbg'):
                    removed.append(dict(file=str(file.relative_to(self.work)),bytes=file.stat().st_size,sha256=sha(file)))
                    file.unlink()
        if self.obj.exists():
            if self.obj.is_symlink() or self.obj.parent!=self.work/'build' or self.obj.name!='obj-'+self.release:
                raise ValueError('Unexpected object-directory cleanup target')
            shutil.rmtree(self.obj)
        self.state.update(objects_cleaned=True,excluded_debug_outputs=removed)
        write(self.statefile,self.state);write(self.work/'dist/kernel-update.json',self.state)

    def execute(self):
        self.prepare()
        if not self.args.prepare_only:
            self.build()
            self.nvidia()
            self.finish()
            if self.args.promote: self.promote()
            self.cleanup()
            if self.args.install:
                receipt=self.work/'dist/kernel-build-artifacts.json'
                self.run(['pkexec','/usr/bin/python3',REPO/'scripts/install-kernel-update.py','--work',self.work,
                          '--receipt-sha256',sha(receipt)],'kernel-install-controller.log')
                self.state['stages']['install']=True
                self.state.update(installed_kernel=self.release,running_kernel=os.uname().release,boot_tested=False)
                write(self.statefile,self.state);write(self.work/'dist/kernel-update.json',self.state)
        print('Kernel update state:',self.statefile,flush=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--version',required=True)
    parser.add_argument('--work',type=Path,required=True)
    parser.add_argument('--jobs',type=int,default=3)
    parser.add_argument('--tools-root',type=Path)
    parser.add_argument('--prepare-only',action='store_true')
    parser.add_argument('--keep-objects',action='store_true',help='Keep regenerable object/debug files after successful source/evidence export')
    parser.add_argument('--accept-config-diff',help='SHA256 of an explicitly reviewed configuration-diff.json; use a fresh workspace')
    parser.add_argument('--promote',action='store_true',help='Publish verified kernel lock/notes to the source checkout after all build gates')
    parser.add_argument('--install',action='store_true',help='Request native administrator authentication and install after all build gates; never reboot')
    args=parser.parse_args()
    if not re.fullmatch(r'\d+\.\d+\.\d+',args.version) or not 1<=args.jobs<=8: parser.error('Use X.Y.Z and 1..8 jobs')
    if args.work.resolve() in (Path('/'),REPO) or REPO.is_relative_to(args.work.resolve()): parser.error('Use an isolated new workspace')
    update=Update(args)
    with (update.work/'.update.lock').open('a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise ValueError('Another update process is using this workspace')
        update.execute()


if __name__=='__main__':
    main()
