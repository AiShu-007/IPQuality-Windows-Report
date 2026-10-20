"""Windows portable entry point. Copyright (C) 2026 sunzh815. AGPL-3.0.

Added 2026-10-20: portable runtimes, proxy selection, progress and completion status.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import socket
import ssl
import subprocess
import sys
import time
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent


def proxy_url(value):
    if value.isdecimal():
        value = 'http://127.0.0.1:' + value
    item = urlsplit(value)
    if item.scheme not in ('http', 'https') or not item.hostname:
        raise ValueError('请输入 HTTP / mixed 代理地址，例如 http://127.0.0.1:7890')
    if item.username or item.password:
        raise ValueError('便携入口暂不支持带账号密码的代理，请使用本机 HTTP / mixed 端口。')
    if not item.port or item.path not in ('', '/') or item.query or item.fragment:
        raise ValueError('代理地址需要明确端口，且不能包含路径或查询参数。')
    return value.rstrip('/')


def system_proxies():
    """Read static Windows proxy settings without changing them or executing PAC."""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r'Software\Microsoft\Windows\CurrentVersion\Internet Settings') as key:
            if not winreg.QueryValueEx(key, 'ProxyEnable')[0]:
                return []
            value = winreg.QueryValueEx(key, 'ProxyServer')[0]
    except (ImportError, OSError):
        return []
    if '=' not in value:
        return [value]
    settings = dict(part.split('=', 1) for part in value.split(';') if '=' in part)
    return [settings[k] for k in ('https', 'http') if settings.get(k)]


def proxy_candidates():
    values = system_proxies()
    values += [os.environ.get(k, '') for k in
               ('HTTPS_PROXY', 'https_proxy', 'HTTP_PROXY', 'http_proxy', 'ALL_PROXY', 'all_proxy')]
    values += [str(p) for p in (7890, 7897, 10809, 1080, 8080, 1087, 7891, 2080, 20171)]
    candidates = []
    for value in values:
        if not value:
            continue
        try:
            if not value.isdecimal() and '://' not in value:
                value = 'http://' + value
            value = proxy_url(value)
        except ValueError:
            continue
        if value not in candidates:
            candidates.append(value)
    return candidates


def verify_proxy(value, env, endpoints=None):
    """Require a successful proxied HTTP request and a valid public IPv4 reply."""
    import ipaddress
    item = urlsplit(value)
    try:
        with socket.create_connection((item.hostname, item.port), timeout=0.3):
            pass
    except OSError:
        return None
    endpoints = endpoints or ('https://api.ipify.org', 'https://checkip.amazonaws.com')
    curl = ROOT / 'ipquality-tools/curl.exe'
    for endpoint in endpoints:
        try:
            response = subprocess.run(
                [str(curl), '--silent', '--show-error', '--fail', '--proxy', value,
                 '--noproxy', '', '--connect-timeout', '3', '--max-time', '7',
                 '--max-filesize', '1024', '--cacert',
                 str(ROOT / 'ipquality-tools/windows-trusted-ca.pem'), endpoint],
                env=env, capture_output=True, text=True, timeout=9)
            if response.returncode:
                continue
            address = ipaddress.ip_address(response.stdout.strip())
            if address.version == 4 and address.is_global:
                return str(address)
        except (OSError, ValueError, subprocess.TimeoutExpired):
            continue
    return None


def find_proxy(env):
    for candidate in proxy_candidates():
        address = verify_proxy(candidate, env)
        if address:
            return candidate, address
    return None


def environment():
    bash = ROOT / 'runtime/git/usr/bin/bash.exe'
    python = ROOT / 'runtime/python/python.exe'
    if not bash.is_file() or not python.is_file():
        raise RuntimeError('运行环境不完整。请下载 Releases 中的 Windows-x64-Portable.zip 并完整解压，不能只下载源码。')
    env = os.environ.copy()
    for key in ('PYTHONHOME', 'PYTHONPATH', 'BASH_ENV', 'ENV'):
        env.pop(key, None)
    # The portable package must work without Git or Python installed globally.
    env['PATH'] = os.pathsep.join(map(str, [ROOT / 'ipquality-tools', bash.parent,
                                           Path(os.environ.get('SystemRoot', 'C:/Windows')) / 'System32']))
    env['IPQ_PYTHON'] = str(python)
    env['PYTHONUTF8'] = '1'
    env['PYTHONDONTWRITEBYTECODE'] = '1'
    return bash, python, env


def local_ca_bundle():
    # Export public roots on the recipient's machine, never ship the builder's trust store.
    context = ssl.create_default_context()
    certificates = context.get_ca_certs(binary_form=True)
    if not certificates:
        raise RuntimeError('系统没有可用的可信 CA 根证书，请先修复系统证书配置。')
    target = ROOT / 'ipquality-tools/windows-trusted-ca.pem'
    target.write_text(''.join(ssl.DER_cert_to_PEM_cert(c) for c in certificates), encoding='ascii')


def self_test(bash, python, env):
    from supplement_ipquality import classify_dns_answer
    assert classify_dns_answer('list.dnswl.org', 0, ['127.0.0.255']) == 'restricted'
    assert classify_dns_answer('list.dnswl.org', 0, ['127.0.5.2']) == 'allowlist_code'
    assert classify_dns_answer('test.invalid', 2, []) == 'dns_error'
    assert classify_dns_answer('test.invalid', 3, []) == 'not_listed'
    subprocess.run([str(bash), '--noprofile', '--norc', '-c',
                    'set -e; bash --version | head -n 1; jq --version; curl --version | head -n 1; test "$(echo 2+2 | bc)" = 4; date +%Y; uname -s'],
                   env=env, cwd=ROOT, check=True)
    subprocess.run([str(python), '-X', 'utf8', str(ROOT / 'render_ipquality_report.py'),
                    '--input', str(ROOT / 'examples/demo.raw.ansi'), '--json', str(ROOT / 'examples/demo.json'),
                    '--output', str(ROOT / 'reports/self-test.png')], cwd=ROOT, env=env, check=True)
    from PIL import Image
    with Image.open(ROOT / 'reports/self-test.png') as picture:
        picture.verify()
    print('自检通过：内置 Bash、curl、jq、bc、Python、Pillow 和中文图片报告均可使用。')
    return 0


def main():
    parser = argparse.ArgumentParser(description='IPQuality Windows 便携版：检测当前代理出口并生成完整图片报告。')
    parser.add_argument('--proxy', help='HTTP/mixed 代理地址或本机端口')
    parser.add_argument('--self-test', action='store_true', help='离线检查运行环境和示例报告')
    parser.add_argument('--no-open', action='store_true', help='完成后不自动打开报告')
    parser.add_argument('--timeout', type=int, default=900, help='总超时秒数，默认900')
    args = parser.parse_args()
    bash, python, env = environment()
    (ROOT / 'reports').mkdir(exist_ok=True)
    local_ca_bundle()
    if args.self_test:
        return self_test(bash, python, env)
    print('IPQuality Windows 便携版 v1.0.1 | AGPL-3.0 | 上游 xykt/IPQuality', flush=True)
    print('结果取决于当前代理规则；不同网站可能经过不同出口。', flush=True)
    selected = args.proxy or os.environ.get('IPQ_PROXY')
    if selected:
        selected = proxy_url(selected)
        address = verify_proxy(selected, env)
        if not address:
            raise RuntimeError('指定的 HTTP/mixed 代理未通过联网验证，请检查端口和当前节点。')
        print(f'使用指定代理：{selected}；连通性检查出口 IPv4：{address}', flush=True)
    else:
        print('正在自动识别代理（系统设置、环境变量和常见本机端口）……', flush=True)
        found = find_proxy(env)
        if found:
            selected, address = found
            print(f'已自动识别并验证代理：{selected}；连通性检查出口 IPv4：{address}', flush=True)
        else:
            print('未找到能联网的 HTTP/mixed 代理，请确认代理软件和节点已开启。', flush=True)
            if not sys.stdin.isatty():
                raise RuntimeError('自动识别失败，请使用 --proxy 指定 HTTP/mixed 代理端口。')
            selected = proxy_url(input('请输入 HTTP/mixed 端口或地址（关闭窗口取消）：').strip())
            if not verify_proxy(selected, env):
                raise RuntimeError('该地址未通过 HTTP 代理联网验证，请检查端口和当前节点。')
    print('如需检测其他代理，可运行 Start.cmd --proxy 端口号。', flush=True)
    env.update(IPQ_PROXY=selected, IPQ_OPEN_REPORT='0' if args.no_open else '1')
    # Replace inherited proxy variables for this process tree only.
    for key in ('HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'http_proxy', 'https_proxy', 'all_proxy'):
        env[key] = selected
    run_id = datetime.now().strftime('%Y%m%d-%H%M%S') + '-' + str(os.getpid())
    relative = 'reports/ipquality-' + run_id
    status_path = ROOT / (relative + '.status.json')

    def status(state, **extra):
        status_path.write_text(json.dumps({'state': state, 'updated': datetime.now(timezone.utc).isoformat(), **extra},
                                          ensure_ascii=False, indent=2), encoding='utf-8')

    status('running')
    print('\n开始检测，通常需要数分钟。看到“检测完成”并生成 PNG 后才算结束。', flush=True)
    process = subprocess.Popen([str(bash), '--noprofile', '--norc', './ipquality-run.sh', '-o', relative + '.json'],
                               cwd=ROOT, env=env)
    started = time.monotonic()
    try:
        while True:
            remaining = args.timeout - (time.monotonic() - started)
            if remaining <= 0:
                raise subprocess.TimeoutExpired(process.args, args.timeout)
            try:
                code = process.wait(timeout=min(30, remaining))
                break
            except subprocess.TimeoutExpired:
                print(f'仍在检测，已用时 {int(time.monotonic() - started)} 秒；请等待完成提示。', flush=True)
    except (subprocess.TimeoutExpired, KeyboardInterrupt) as error:
        subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'], capture_output=True)
        status('failed', reason='timeout' if isinstance(error, subprocess.TimeoutExpired) else 'cancelled')
        print('检测超时或已取消；现有中间文件保留，不能当作完成报告。')
        return 1
    image = ROOT / (relative + '.png')
    if code or not image.is_file():
        status('failed', exit_code=code)
        print('检测失败，未生成完整图片报告。请查看上方错误提示。')
        return code or 1
    status('completed', image=image.name, data=relative + '.json')
    print('\n检测完成：PNG、JSON、TXT、ANSI 和完整查询明细已保存。')
    print('报告文件夹：' + str(ROOT / 'reports'))
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as error:
        print('错误：' + str(error), file=sys.stderr)
        raise SystemExit(1)
