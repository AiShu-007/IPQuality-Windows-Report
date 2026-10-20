"""Build a self-contained Windows x64 distribution. AGPL-3.0, sunzh815, 2026-10-20."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
from urllib.request import Request, build_opener, ProxyHandler
import zipfile

ROOT = Path(__file__).resolve().parent
VERSION = '1.0.1'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build(git_root, proxy):
    if not (git_root / 'usr/bin/bash.exe').is_file():
        raise ValueError('--git-root must contain usr/bin/bash.exe (Git for Windows x64)')
    lock = json.loads((ROOT / 'assets.lock.json').read_text(encoding='utf-8'))
    cache = ROOT / 'work/downloads'
    cache.mkdir(parents=True, exist_ok=True)
    opener = build_opener(ProxyHandler({'https': proxy, 'http': proxy})) if proxy else build_opener()
    for asset in lock.values():
        path = cache / asset['file']
        if not path.exists():
            print('Downloading ' + asset['file'], flush=True)
            with opener.open(Request(asset['url'], headers={'User-Agent': 'IPQuality-Windows-Report-build'}), timeout=90) as response:
                path.write_bytes(response.read())
        if sha(path) != asset['sha256']:
            raise ValueError('SHA256 mismatch: ' + asset['file'])

    # Each build gets a fresh directory; never merge in logs or real reports.
    stage = ROOT / 'work' / ('portable-stage-' + str(os.getpid()))
    stage.mkdir()
    package = stage / 'IPQuality-Windows-Report'
    package.mkdir()
    allowed = ['launcher.py', 'Start.cmd', 'Self-Test.cmd', 'ipquality-run.sh', 'ipquality-original.sh',
               'render_ipquality_report.py', 'full_report_sections.py', 'supplement_ipquality.py',
               'README.md', 'NOTICE.md', 'LICENSE', 'assets.lock.json', 'build_portable.py',
               'make_demo.py', 'requirements.txt', 'RELEASE_NOTES.md']
    for name in allowed:
        shutil.copyfile(ROOT / name, package / name)
    shutil.copytree(ROOT / 'examples', package / 'examples', ignore=shutil.ignore_patterns('*.details.txt', '__pycache__'))
    runtime = package / 'runtime'
    pyroot = runtime / 'python'
    pyroot.mkdir(parents=True)
    with zipfile.ZipFile(cache / lock['python']['file']) as archive:
        archive.extractall(pyroot)
    site = pyroot / 'Lib/site-packages'
    with zipfile.ZipFile(cache / lock['pillow']['file']) as archive:
        archive.extractall(site)
    (pyroot / 'python314._pth').write_text('python314.zip\n.\nLib\\site-packages\n..\\..\n', encoding='ascii')

    # Include the Unix command runtime; no installer, registry entries or user configuration.
    git = runtime / 'git'
    shutil.copytree(git_root / 'usr/bin', git / 'usr/bin')
    for relative in ['usr/share/licenses', 'usr/share/terminfo']:
        if (git_root / relative).exists():
            shutil.copytree(git_root / relative, git / relative)
    (git / 'etc').mkdir(parents=True)
    (git / 'tmp').mkdir()
    (git / 'tmp/.keep').write_text('Portable MSYS temporary directory.\n', encoding='ascii')
    for name in ['services', 'protocols', 'nsswitch.conf', 'package-versions.txt']:
        if (git_root / 'etc' / name).is_file():
            shutil.copyfile(git_root / 'etc' / name, git / 'etc' / name)
    shutil.copyfile(git_root / 'LICENSE.txt', git / 'LICENSE.txt')

    tools = package / 'ipquality-tools'
    tools.mkdir()
    with zipfile.ZipFile(cache / lock['curl']['file']) as archive:
        for item in archive.namelist():
            if item.endswith('/bin/curl.exe'):
                (tools / 'curl.exe').write_bytes(archive.read(item))
            elif item.endswith('/bin/curl-ca-bundle.crt'):
                (tools / 'curl-ca-bundle.crt').write_bytes(archive.read(item))
            elif 'copying' in item.lower() or item.lower().endswith('license.txt'):
                if not item.endswith('/'):
                    target = tools / 'licenses/curl' / item
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(archive.read(item))
    shutil.copyfile(cache / lock['jq']['file'], tools / 'jq.exe')
    with tarfile.open(cache / lock['bc']['file'], 'r:*') as archive:
        for member in archive.getmembers():
            if member.name == 'usr/bin/bc.exe':
                (tools / 'bc.exe').write_bytes(archive.extractfile(member).read())
    for name in ['curl.exe', 'jq.exe', 'bc.exe']:
        if not (tools / name).is_file():
            raise RuntimeError('Missing bundled executable: ' + name)
    licenses = ROOT / 'vendor-licenses'
    if licenses.exists():
        shutil.copytree(licenses, tools / 'licenses/extra')
    (package / 'fonts').mkdir()
    shutil.copyfile(cache / lock['cjk_font']['file'], package / 'fonts/NotoSansMonoCJKsc-Regular.otf')

    git_version = subprocess.run([str(git_root / 'cmd/git.exe'), '--version'], capture_output=True, text=True, check=True).stdout.strip()
    sources = {
        'Python': 'https://www.python.org/ftp/python/' + lock['python']['version'] + '/Python-' + lock['python']['version'] + '.tar.xz',
        'Pillow': 'https://pypi.org/project/pillow/' + lock['pillow']['version'] + '/#files',
        'curl': 'https://curl.se/download/curl-8.23.0.tar.xz',
        'jq': 'https://github.com/jqlang/jq/releases/tag/jq-1.8.2',
        'bc': 'https://ftp.gnu.org/gnu/bc/bc-1.08.2.tar.gz',
        'Git/MSYS tools': 'https://github.com/git-for-windows/build-extra/tree/main/ReleaseNotes.md',
        'Git for Windows MSYS package recipes': 'https://github.com/git-for-windows/MSYS2-packages',
        'MSYS runtime source': 'https://github.com/git-for-windows/msys2-runtime',
        'MSYS package sources': 'https://repo.msys2.org/msys/sources/',
        'Noto CJK font (SIL OFL)': 'https://github.com/notofonts/noto-cjk',
    }
    notices = ['# Third-party runtime components', '', git_version, '',
               'Git/MSYS component versions: runtime/git/etc/package-versions.txt.',
               'Git notices: runtime/git/LICENSE.txt and runtime/git/usr/share/licenses.',
               'Python license: runtime/python/LICENSE.txt; Pillow license: its dist-info/licenses directory.',
               'curl/jq/bc additional licenses: ipquality-tools/licenses.', '', '## Official downloads and pinned SHA256', '']
    for key, asset in lock.items():
        notices += [f'- {key} {asset["version"]}: {asset["url"]}', '  SHA256: ' + asset['sha256']]
    notices += ['', '## Corresponding source and build recipes', '']
    notices += [f'- {key}: {url}' for key, url in sources.items()]
    (package / 'THIRD_PARTY.md').write_text('\n'.join(notices) + '\n', encoding='utf-8')
    manifest = {str(p.relative_to(package)).replace('\\', '/'): sha(p) for p in sorted(package.rglob('*')) if p.is_file()}
    (package / 'FILES.sha256.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    dist = ROOT / 'dist'
    dist.mkdir(exist_ok=True)
    output = dist / f'IPQuality-Windows-x64-Portable-v{VERSION}.zip'
    with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for p in sorted(package.rglob('*')):
            if p.is_file():
                archive.write(p, str(p.relative_to(stage)))
    digest = sha(output)
    output.with_suffix('.zip.sha256').write_text(digest + '  ' + output.name + '\n', encoding='ascii')
    print(json.dumps({'zip': str(output), 'sha256': digest, 'bytes': output.stat().st_size, 'stage': str(package)}), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--git-root', type=Path, required=True)
    parser.add_argument('--proxy', default=os.environ.get('HTTPS_PROXY'))
    args = parser.parse_args()
    build(args.git_root.resolve(), args.proxy)
