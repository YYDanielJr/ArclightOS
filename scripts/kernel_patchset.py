"""Apply a hash-locked kernel patch stack without fuzz or conflict resolution."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import re
import tarfile


def restore_upstream_links(tree, archive, report):
    """Undo data_filter's link-text normalization without changing destinations."""
    tree,archive,report=map(Path,(tree,archive,report));restored=[]
    with tarfile.open(archive,mode='r|xz') as source:
        for item in source:
            if not item.issym():continue
            parts=Path(item.name).parts
            if len(parts)<2 or '..' in parts or Path(item.linkname).is_absolute():raise ValueError('Unsafe upstream link')
            name=Path(*parts[1:]);file=tree/name
            if not file.is_symlink():raise ValueError('Upstream symbolic link was replaced: '+str(name))
            actual=os.readlink(file)
            if actual==item.linkname:continue
            target=(file.parent/item.linkname).resolve()
            if os.path.normpath(item.linkname)!=actual or target!=file.resolve() or not target.is_relative_to(tree.resolve()):
                raise ValueError('Upstream link destination changed: '+str(name))
            file.unlink();file.symlink_to(item.linkname)
            restored.append(dict(file=name.as_posix(),normalized=actual,restored=item.linkname))
    report.parent.mkdir(parents=True,exist_ok=True)
    report.write_text(json.dumps(dict(passed=True,restored=restored),indent=2)+'\n')
    return restored


def load_stack(root, version):
    root = Path(root)
    manifest = json.loads((root/'patches/series.json').read_text())
    if manifest['schema'] != 'arclight.kernel-patch-series.v1' or '.'.join(version.split('.')[:2]) not in manifest['series']:
        raise ValueError('No reviewed patch series for this upstream version')
    stack = []
    for patch in manifest['patches']:
        file = (root/'patches'/patch['file']).resolve()
        if not file.is_relative_to((root/'patches').resolve()) or not re.fullmatch('[a-f0-9]{64}',patch['sha256']):
            raise ValueError('Invalid patch-series entry')
        stack.append(dict(id=patch['id'],file=file,sha256=patch['sha256']))
    if not stack or len({p['id'] for p in stack}) != len(stack):
        raise ValueError('Empty or duplicate patch series')
    return stack


def affected_files(tree, stack):
    names=set()
    for patch in stack:
        for line in Path(patch['file']).read_text().splitlines():
            if line.startswith(('+++ b/','--- a/')):
                name=line[6:].split('\t')[0]
                path=Path(name)
                if path.is_absolute() or '..' in path.parts: raise ValueError('Unsafe patch path')
                names.add(name)
    return {name:sha(tree/name) if (tree/name).is_file() else None for name in sorted(names)}


def compare_pristine(tree, archive, allowed, report):
    """Compare all Linux files, allowing only declared patch paths and notes."""
    tree,archive,report=map(Path,(tree,archive,report));expected=set();changes=[];checked=0
    with tarfile.open(archive,mode='r|xz') as source:
        for item in source:
            if item.isdir():continue
            parts=Path(item.name).parts
            if len(parts)<2 or '..' in parts:raise ValueError('Unexpected upstream archive path')
            name=Path(*parts[1:]).as_posix();expected.add(name);file=tree/name
            if item.isfile():
                before=hashlib.file_digest(source.extractfile(item),'sha256').hexdigest()
                after=sha(file) if file.is_file() and not file.is_symlink() else None
            elif item.issym():
                before='symlink:'+item.linkname
                after='symlink:'+os.readlink(file) if file.is_symlink() else None
            else:raise ValueError('Unsupported upstream member type: '+name)
            checked+=1
            if before!=after:changes.append(dict(file=name,before=before,after=after))
    extras=[];notes=[]
    for file in tree.rglob('*'):
        if file.is_dir() and not file.is_symlink():continue
        name=file.relative_to(tree).as_posix()
        if name in expected:continue
        if name=='.arclight-patchset.json' or name=='ASCALON-CHANGES.md' or name.startswith('arclight-maintenance/'):
            notes.append(name);continue
        extras.append(name)
        changes.append(dict(file=name,before=None,after=sha(file) if file.is_file() and not file.is_symlink() else 'unsupported'))
    unexpected=[row['file'] for row in changes if row['file'] not in allowed]
    value=dict(schema='arclight.kernel-pristine-comparison.v1',passed=not unexpected,
        upstream_archive_sha256=sha(archive),checked_upstream_files=checked,implementation_changes=changes,
        allowed_patch_files=sorted(allowed),maintenance_files_excluded=sorted(notes),unexpected_changes=unexpected)
    report.parent.mkdir(parents=True,exist_ok=True);report.write_text(json.dumps(value,indent=2)+'\n')
    if unexpected:raise ValueError('Undeclared Linux source changes: '+', '.join(unexpected))
    return value


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def apply_stack(tree, stack, identity, report):
    tree, report = Path(tree).resolve(), Path(report)
    marker = tree / '.arclight-patchset.json'
    inputs = dict(upstream=identity, patches=[dict(id=p['id'], sha256=p['sha256']) for p in stack])
    env = {k:v for k,v in os.environ.items() if not k.startswith('GIT_')}
    env.update(LC_ALL='C',GIT_CEILING_DIRECTORIES=str(tree.parent),
               GIT_CONFIG_NOSYSTEM='1',GIT_CONFIG_GLOBAL='/dev/null')
    for patch in stack:
        if sha(patch['file']) != patch['sha256']:
            raise ValueError('Patch hash mismatch: ' + patch['id'])
    if marker.exists():
        previous=json.loads(marker.read_text())
        if previous['inputs'] != inputs:
            raise ValueError('Patch inputs changed: use a clean source directory')
        if 'result_files' in previous:
            if previous['result_files'] != affected_files(tree,stack):
                raise ValueError('Recorded patch result files changed: use a clean source directory')
            report.write_text(json.dumps({**previous,'reused_verified_tree':True},indent=2)+'\n')
            return previous
        # Verify the recorded stack is still present; never trust only a flag.
        result = subprocess.run(['git', 'apply', '--reverse', '--check',
            *[str(Path(p['file']).resolve()) for p in reversed(stack)]], cwd=tree, env=env,
            capture_output=True, text=True)
        if result.returncode:
            raise ValueError('Recorded patch stack no longer matches the source tree: ' + result.stderr)
        previous['result_files']=affected_files(tree,stack)
        marker.write_text(json.dumps(previous,indent=2)+'\n')
        report.write_text(json.dumps({**previous,'reused_verified_tree':True},indent=2)+'\n')
        return previous
    commands = []
    for patch in stack:
        path = str(Path(patch['file']).resolve())
        for arguments in (['--check', '--verbose'], ['--verbose']):
            command = ['git', 'apply', *arguments, path]
            result = subprocess.run(command, cwd=tree, env=env, capture_output=True, text=True)
            commands.append(dict(argv=command, returncode=result.returncode, stdout=result.stdout, stderr=result.stderr))
            if result.returncode:
                report.write_text(json.dumps(dict(passed=False, inputs=inputs, commands=commands), indent=2)+'\n')
                raise ValueError('Patch needs human adaptation; refusing automatic conflict resolution: '+patch['id'])
    value = dict(schema='arclight.kernel-patchset.v1', passed=True, inputs=inputs, commands=commands,
                 automatic_conflict_resolution=False, fuzz_used=False,result_files=affected_files(tree,stack))
    marker.write_text(json.dumps(value, indent=2)+'\n')
    report.write_text(json.dumps(value, indent=2)+'\n')
    return value
