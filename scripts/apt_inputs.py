"""Reviewed HTTPS mirrors for mixed-image downloads and index snapshots."""

PREFIXES = (
    'https://mirrors.ustc.edu.cn/debian/',
    'https://mirrors.ustc.edu.cn/debian-security/',
    'https://mirrors.nju.edu.cn/debian/',
    'https://mirrors.nju.edu.cn/debian-security/',
    'https://deb.debian.org/debian/',
    'https://deb.debian.org/debian-security/',
    'https://security.debian.org/debian-security/',
    'https://archive.raspberrypi.com/debian/',
)


def download_uris(uris):
    """Prefer mainland mirrors, upgrading an official HTTP URI to HTTPS.

    This is a transport policy, not authentication: callers still require a
    trusted APT version, then independently verify official signatures/hashes.
    """
    accepted = []
    for uri in uris:
        uri = 'https://' + uri[7:] if uri.startswith('http://') else uri
        if any(uri.startswith(prefix) for prefix in PREFIXES) and uri not in accepted:
            accepted.append(uri)
    return sorted(accepted, key=lambda uri: next(i for i, prefix in enumerate(PREFIXES) if uri.startswith(prefix)))


def allowed_list_file(name):
    prefixes = [p.removeprefix('https://').rstrip('/').replace('/', '_') + '_' for p in PREFIXES]
    return any(name.startswith(prefix) for prefix in prefixes)
