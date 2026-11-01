"""Export a clean corresponding-source tree with fixed tar metadata."""
import hashlib
import os
from pathlib import Path
import tarfile


def archive_source_tree(root, target, top, epoch=1793318400):
    root, target = Path(root).resolve(), Path(target).resolve()
    checksum = target.with_name(target.name + '.sha256')
    if target.exists() or checksum.exists():
        raise FileExistsError('Refusing to overwrite corresponding source: ' + str(target))
    if not root.is_dir() or '/' in top or not top or target.is_relative_to(root):
        raise ValueError('Invalid source export paths')
    for file in root.rglob('*'):
        if file.is_symlink() and not file.resolve().is_relative_to(root):
            raise ValueError('Source symlink escapes tree: ' + str(file))
        if file.is_file():
            with file.open('rb') as stream:
                if file.suffix in {'.o', '.ko', '.deb', '.so', '.a'} or stream.read(4) == b'\x7fELF':
                    raise ValueError('Compiled payload in source tree: ' + str(file))
    def metadata(info):
        if any(part in {'.git', '.local', '.aws', '.env', '__pycache__'} for part in Path(info.name).parts):
            return None
        info.uid = info.gid = 0
        info.uname = info.gname = ''
        info.mtime = epoch
        return info
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + '.partial')
    with tarfile.open(temporary, 'x:xz', preset=1) as archive:
        archive.add(root, arcname=top, filter=metadata)
    # Exclusive destination creation: never replace a frozen input, including
    # one that appeared while this export was being compressed.
    os.link(temporary, target)
    temporary.unlink()
    with target.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    with checksum.open('x') as stream:
        stream.write(digest + '  ' + target.name + '\n')
    return digest
