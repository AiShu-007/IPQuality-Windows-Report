"""Create synthetic documentation data only; never reuse a real user's report."""
import json
from pathlib import Path
import subprocess
import sys

root = Path(__file__).resolve().parent
example = root / 'examples'
example.mkdir(exist_ok=True)
data = {
    'Head': {'IP': '203.0.113.10', 'Version': 'DEMO - synthetic data, not a real measurement'},
    'Info': {'ASN': '64500', 'Organization': 'Documentation Example Network',
             'Region': {'Name': '演示地区（非实测）'}, 'RegisteredRegion': {'Name': '演示地区'},
             'Continent': {'Name': '演示'}, 'City': {'Name': '示例城市'}, 'Type': '演示数据'},
    'Type': {'Usage': {'IPinfo': '演示', 'ipregistry': '演示'}},
    'Supplemental': {
        'IPv6': {'Status': 'unconfirmed'},
        'DNSBL': {'Status': 'completed', 'Resolver': 'https://dns.google/resolve', 'Total': 4,
                  'Counts': {'not_listed': 1, 'restricted': 1, 'dns_error': 1, 'allowlist_code': 1},
                  'Results': []},
        'SMTP': [{'Provider': x, 'Status': 'unknown'} for x in ['Gmail', 'Outlook', 'Yahoo', 'Apple', 'QQ', 'MailRU', 'AOL', 'GMX', 'MailCOM', '163', 'Sohu', 'Sina']]}}
(example / 'demo.json').write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
(example / 'demo.raw.ansi').write_text('DEMO ONLY - NOT A REAL MEASUREMENT\n203.0.113.10\n', encoding='utf-8')
subprocess.run([sys.executable, '-X', 'utf8', str(root / 'render_ipquality_report.py'),
                '--input', str(example / 'demo.raw.ansi'), '--json', str(example / 'demo.json'),
                '--output', str(example / 'demo.png')], check=True)
