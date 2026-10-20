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


def find_proxy():
    for port in (7890, 7897, 10809, 1080, 8080):
        try:
            with socket.create_connection(('127.0.0.1', port), timeout=0.15):
                return f'http://127.0.0.1:{port}'
        except OSError:
            pass
    return 'http://127.0.0.1:7890'


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
    selected = args.proxy or os.environ.get('IPQ_PROXY')
    if not selected:
        default = find_proxy()
        print('IPQuality Windows 便携版 v1.0.0 | AGPL-3.0 | 上游 xykt/IPQuality')
        print('请先打开代理软件；使用 HTTP / mixed 端口，不是 SOCKS 专用端口。')
        print('结果取决于当前代理规则；不同网站可能经过不同出口。')
        selected = input(f'代理地址或端口 [回车使用 {default}]：').strip() or default
    selected = proxy_url(selected)
    item = urlsplit(selected)
    try:
        with socket.create_connection((item.hostname, item.port), timeout=3):
            pass
    except OSError as error:
        raise RuntimeError('无法连接代理，请检查代理软件是否已开启以及 HTTP/mixed 端口是否正确。') from error
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
