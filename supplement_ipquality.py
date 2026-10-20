# Copyright (C) 2026 sunzh815. AGPL-3.0. Modified 2026-10-20.
"""Additional read-only probes for the Windows/proxy IPQuality report."""
import argparse
import base64
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
from datetime import datetime, timezone
import ipaddress
import json
import re
import socket
import ssl
import sys
import time
from pathlib import Path
from urllib.parse import urlencode, urlsplit, unquote
from urllib.request import Request, ProxyHandler, build_opener


def classify_dns_answer(zone, code, values):
    if code == 3 or (code == 0 and not values):
        return 'not_listed'
    if code != 0:
        return 'dns_error'
    if zone == 'list.dnswl.org' or zone.endswith('.dnswl.org'):
        # DNSWL documents 127.0.0.255 as a resolver quota/block response,
        # and its ordinary 127.0.x.y records as allowlist trust levels.
        if '127.0.0.255' in values:
            return 'restricted'
        if any(x.startswith('127.0.') for x in values):
            return 'allowlist_code'
    if any(x.startswith('127.255.') for x in values):
        return 'restricted'
    if any(x.startswith('127.') for x in values):
        return 'listed_code'
    return 'unexpected_answer'


class Probes:
    def __init__(self, proxy):
        self.proxy = proxy
        self.resolver = 'https://dns.google/resolve'

    def get(self, url, timeout=8, dns=False):
        opener = build_opener(ProxyHandler({'http': self.proxy, 'https': self.proxy}))
        headers = {'User-Agent': 'IPQuality-Windows-Report/2.0', 'Accept': 'application/dns-json' if dns else 'application/json, */*'}
        with opener.open(Request(url, headers=headers), timeout=timeout) as response:
            return response.read()

    def json(self, url, timeout=8, dns=False):
        return json.loads(self.get(url, timeout, dns))

    def dns(self, name, kind='A', timeout=6):
        return self.json(self.resolver + '?' + urlencode({'name': name, 'type': kind}), timeout, True)

    def smtp(self, item):
        name, domain = item
        result = {'Provider': name, 'Domain': domain, 'Port': 25, 'Status': 'unknown'}
        try:
            answer = self.dns(domain, 'MX')
            mx = sorted((int(x['data'].split()[0]), x['data'].split()[1].rstrip('.'))
                        for x in answer.get('Answer', []) if x.get('type') == 15 and len(x['data'].split()) == 2)
            if not mx or not mx[0][1]:
                result.update(Status='dns_failed', Reason=f'MX query returned DNS status {answer.get("Status")} without a usable MX')
                return result
            host = mx[0][1]
            result['MX'] = host
            proxy = urlsplit(self.proxy)
            if proxy.scheme not in ('http', 'https'):
                result.update(Status='unsupported', Reason='SMTP supplement requires the configured HTTP CONNECT proxy')
                return result
            with socket.create_connection((proxy.hostname, proxy.port or 80), timeout=8) as stream:
                stream.settimeout(8)
                if proxy.scheme == 'https':
                    stream = ssl.create_default_context().wrap_socket(stream, server_hostname=proxy.hostname)
                auth = ''
                if proxy.username:
                    token = base64.b64encode((unquote(proxy.username) + ':' + unquote(proxy.password or '')).encode()).decode()
                    auth = f'Proxy-Authorization: Basic {token}\r\n'
                stream.sendall((f'CONNECT {host}:25 HTTP/1.1\r\nHost: {host}:25\r\n{auth}\r\n').encode('ascii'))
                buffer = b''
                while b'\r\n\r\n' not in buffer and len(buffer) < 16384:
                    part = stream.recv(1024)
                    if not part:
                        break
                    buffer += part
                header, _, banner = buffer.partition(b'\r\n\r\n')
                status = header.split(b'\r\n', 1)[0].decode('ascii', errors='replace')
                if not re.match(r'^HTTP/\d(?:\.\d)? 200\b', status):
                    result.update(Status='proxy_rejected', Reason=status[:140])
                    return result
                while b'\n' not in banner and len(banner) < 2048:
                    part = stream.recv(1024)
                    if not part:
                        break
                    banner += part
                result['Banner'] = banner.decode('utf-8', errors='replace').strip()[:500]
                result['Status'] = 'available' if re.match(rb'^220[ -]', banner) else 'unexpected_banner'
                # No email or account information is transmitted.
                stream.sendall(b'QUIT\r\n')
        except Exception as error:
            result.update(Status='timeout' if isinstance(error, (TimeoutError, socket.timeout)) else 'failed', Reason=str(error)[:240])
        return result

    def blacklist(self, zone, tested_ip):
        reverse = '.'.join(reversed(tested_ip.split('.')))
        try:
            answer = self.dns(reverse + '.' + zone)
            code = answer.get('Status')
            values = [x['data'] for x in answer.get('Answer', []) if x.get('type') == 1]
            status = classify_dns_answer(zone, code, values)
            return {'Zone': zone, 'Status': status, 'DNSStatus': code, 'Answers': values}
        except Exception as error:
            return {'Zone': zone, 'Status': 'failed', 'Reason': str(error)[:240]}


def geolocation(probes, result):
    ip = result['Head']['IP']
    response = probes.json('https://ipinfo.io/widget/demo/' + ip, 12)
    record = response.get('data', {})
    if record.get('ip') != ip:
        raise ValueError('Geolocation response IP does not match the tested IP')
    info = result.setdefault('Info', {})
    sources = {}
    result['Supplemental']['OriginalInfo'] = deepcopy(info)

    def fill(container, key, value, field):
        if container.get(key) in (None, '', 'null', 'N/A') and value not in (None, '', 'null', 'N/A'):
            container[key] = value
            sources[field] = 'IPinfo'

    city = info.setdefault('City', {})
    for key, source in [('Name', 'city'), ('Subdivisions', 'region'), ('PostalCode', 'postal')]:
        fill(city, key, record.get(source), 'City.' + key)
    fill(info, 'TimeZone', record.get('timezone'), 'TimeZone')
    location = record.get('loc', '').split(',')
    if len(location) == 2:
        lat, lon = float(location[0]), float(location[1])
        fill(info, 'Latitude', lat, 'Latitude')
        fill(info, 'Longitude', lon, 'Longitude')
        fill(info, 'Map', f'https://www.google.com/maps?q={lat},{lon}', 'Map')
        def dms(value, positive, negative):
            absolute = abs(value)
            degrees = int(absolute)
            minutes = int((absolute - degrees) * 60)
            seconds = ((absolute - degrees) * 60 - minutes) * 60
            return f'{degrees}° {minutes}′ {seconds:.2f}″ {positive if value >= 0 else negative}'
        fill(info, 'DMS', dms(lon, 'E', 'W') + ', ' + dms(lat, 'N', 'S'), 'DMS')
    result['Supplemental']['Geolocation'] = {
        'Status': 'ok', 'Source': 'IPinfo', 'FilledFields': sources,
        'Network': {k: record.get(k) for k in ['org', 'asn', 'company', 'privacy', 'is_anycast', 'is_mobile', 'is_anonymous', 'is_satellite', 'is_hosting']}}


def run(json_path, proxy):
    data = json.loads(json_path.read_text(encoding='utf-8-sig'))
    tested_ip = str(ipaddress.ip_address(data['Head']['IP']))
    extra = data.setdefault('Supplemental', {})
    extra['GeneratedAt'] = datetime.now(timezone.utc).isoformat(timespec='seconds')
    extra['Scope'] = 'Current HTTP proxy rules; SMTP tests remote destination port 25, not a locally bound source port.'
    probes = Probes(proxy)
    try:
        geolocation(probes, data)
    except Exception as error:
        extra['Geolocation'] = {'Status': 'failed', 'Reason': str(error)[:240]}
    try:
        reply = probes.json('https://api6.ipify.org?format=json', 8)
        address = ipaddress.ip_address(reply['ip'])
        extra['IPv6'] = {'Status': 'available' if address.version == 6 else 'unconfirmed', 'IP': str(address), 'Endpoint': 'api6.ipify.org'}
    except Exception as error:
        extra['IPv6'] = {'Status': 'unconfirmed', 'Reason': str(error)[:240], 'Endpoint': 'api6.ipify.org'}

    providers = [('Gmail', 'gmail.com'), ('Outlook', 'outlook.com'), ('Yahoo', 'yahoo.com'), ('Apple', 'me.com'),
                 ('QQ', 'qq.com'), ('MailRU', 'mail.ru'), ('AOL', 'aol.com'), ('GMX', 'gmx.com'),
                 ('MailCOM', 'mail.com'), ('163', '163.com'), ('Sohu', 'sohu.com'), ('Sina', 'sina.com')]
    print('Additional check: 12 SMTP destinations through the configured proxy...', file=sys.stderr, flush=True)
    with ThreadPoolExecutor(max_workers=6) as pool:
        extra['SMTP'] = list(pool.map(probes.smtp, providers))

    print('Additional check: upstream DNSBL list over DNS-over-HTTPS...', file=sys.stderr, flush=True)
    listing = {'Status': 'failed', 'Resolver': probes.resolver, 'TestedIP': tested_ip,
               'ActiveListVerification': False,
               'Interpretation': 'NXDOMAIN/no A is not listed in this query; list activity is not verified. The upstream list mixes list types; DNSWL allowlist/quota responses are not blacklist hits.',
               'ReturnCodeReferences': ['https://www.dnswl.org/?page_id=15']}
    try:
        source = 'https://raw.githubusercontent.com/xykt/IPQuality/main/ref/dnsbl.list'
        text = probes.get(source, 15).decode('utf-8-sig')
        zones = sorted(set(x.strip() for x in text.splitlines()
                           if re.fullmatch(r'[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)+', x.strip())))
        if not zones:
            raise ValueError('The upstream list contained no valid zones')
        if ipaddress.ip_address(tested_ip).version != 4:
            raise ValueError('The upstream DNSBL list is used for IPv4 only')
        rows = []
        with ThreadPoolExecutor(max_workers=12) as pool:
            futures = [pool.submit(probes.blacklist, zone, tested_ip) for zone in zones]
            for future in as_completed(futures):
                rows.append(future.result())
                if len(rows) % 100 == 0:
                    print(f'DNSBL: {len(rows)}/{len(zones)} queries finished', file=sys.stderr, flush=True)
        rows.sort(key=lambda x: x['Zone'])
        listing.update(Status='completed', Source=source, Total=len(zones), Results=rows,
                       Counts=dict(Counter(x['Status'] for x in rows)))
    except Exception as error:
        listing['Reason'] = str(error)[:240]
    extra['DNSBL'] = listing
    extra['NotCollected'] = {
        'LocalSourcePort25': 'HTTP proxy mode cannot test binding the remote node source port 25.',
        'DNSBasedUnlockType': 'Not inferred from local DNS in proxy mode.',
        'CloudflareScore': 'No query module in the installed upstream version.',
        'IPWHOIS': 'Reserved output fields only; no query module in the installed upstream version.'}
    json_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    details = json_path.with_suffix('.details.txt')
    translations = {'not_listed':'本次未命中（未验证列表活性）','listed_code':'命中返回码，需按列表核查',
                    'restricted':'查询受限','dns_error':'DNS错误','failed':'连接失败',
                    'unexpected_answer':'异常响应','allowlist_code':'白名单返回码'}
    text_rows = ['完整检测明细', '检测IP：' + tested_ip, '', '邮件连通性：']
    text_rows.extend(f'{x["Provider"]}: {x["Status"]}; MX={x.get("MX", "未知")}; {x.get("Reason", x.get("Banner", ""))}' for x in extra['SMTP'])
    text_rows += ['', 'DNSBL逐项查询：']
    for row in listing.get('Results', []):
        text_rows.append(f'{row["Zone"]}: {translations.get(row["Status"], row["Status"])}; ' +
                         ','.join(row.get('Answers', [])) + ' ' + row.get('Reason', ''))
    text_rows += ['', '以下保留完整JSON数据与各字段来源：', json.dumps(data, ensure_ascii=False, indent=2)]
    details.write_text('\n'.join(text_rows), encoding='utf-8-sig')
    print(f'Additional checks saved: {details}', file=sys.stderr, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--json', required=True, type=Path)
    parser.add_argument('--proxy', required=True)
    args = parser.parse_args()
    run(args.json, args.proxy)
