# Copyright (C) 2026 sunzh815. AGPL-3.0. Modified 2026-10-20.
"""All-field ANSI report, with explicit unknown/unsupported states."""
import re
import unicodedata

RESET = '\x1b[0m'
CYAN = '\x1b[36m'
GREEN = '\x1b[32m'
YELLOW = '\x1b[33m'
RED = '\x1b[31m'
GRAY = '\x1b[37m'
SGR = re.compile(r'\x1b\[[0-9;?]*[A-Za-z]')


def width(value):
    return sum(0 if unicodedata.combining(c) else 2 if unicodedata.east_asian_width(c) in 'WF' else 1 for c in SGR.sub('', str(value)))


def pad(value, size):
    return str(value) + ' ' * max(0, size - width(value))


def present(value):
    return value is not None and value != '' and value != 'null' and value != 'N/A'


def build_full_report(data, original, stamp, proxy, version):
    lines = []

    def heading(value):
        lines.append(RESET + GRAY + value)

    def field(label, value=None, color=GREEN, source=None):
        if not present(value):
            value, color = '未返回数据', YELLOW
        text = str(value) + (f' [{source}]' if source else '')
        # Wrap at terminal cell boundaries, including long map/MX URLs.
        prefix = pad(label + '：', 18)
        part, used, first = '', 0, True
        for c in text:
            cells = 2 if unicodedata.east_asian_width(c) in 'WF' else 1
            if used + cells > 60:
                lines.append(CYAN + (prefix if first else ' ' * 18) + color + part + RESET)
                part, used, first = '', 0, False
            part += c
            used += cells
        lines.append(CYAN + (prefix if first else ' ' * 18) + color + part + RESET)

    def flag(value):
        if value is True:
            return RED + '是' + RESET
        if value is False:
            return GREEN + '否' + RESET
        return YELLOW + '未知' + RESET

    heading('#' * 78)
    heading('IP质量体检报告：' + CYAN + data['Head']['IP'])
    heading('https://github.com/xykt/IPQuality')
    heading(f'图片生成：{stamp}  版本：{version}')
    heading(f'本机代理：{proxy} / Windows Git Bash / 全字段显示')
    heading('#' * 78)
    extra = data.get('Supplemental', {})
    info = data.get('Info', {})
    geo = extra.get('Geolocation', {})
    sources = geo.get('FilledFields', {})
    city = info.get('City', {})
    heading('一、基础信息（MaxMind；缺项注明补充来源）')
    field('IPv4出口', data['Head']['IP'])
    ipv6 = extra.get('IPv6', {})
    ipv6_text = ipv6.get('IP') if ipv6.get('Status') == 'available' else '未确认；接口或链路失败，详见明细' if ipv6 else '未检测'
    field('IPv6出口', ipv6_text, YELLOW if ipv6.get('Status') != 'available' else GREEN)
    asn = info.get('ASN')
    field('自治系统号', ('AS' + str(asn).removeprefix('AS')) if present(asn) else None)
    field('组织', info.get('Organization'))
    field('国家/地区', info.get('Region', {}).get('Name'))
    field('注册地区', info.get('RegisteredRegion', {}).get('Name'))
    field('洲', info.get('Continent', {}).get('Name'))
    for label, key in [('省/州', 'Subdivisions'), ('城市', 'Name'), ('邮编', 'PostalCode')]:
        field(label, city.get(key), source=sources.get('City.' + key))
    for label, key in [('时区', 'TimeZone'), ('纬度', 'Latitude'), ('经度', 'Longitude'), ('坐标', 'DMS'), ('地图', 'Map')]:
        field(label, info.get(key), source=sources.get(key))
    field('地区口径', info.get('Type'))
    field('标签解释', '“原生IP”为地域标签，不等于住宅网络。', GRAY)
    network = geo.get('Network', {})
    field('ASN域名', (network.get('asn') or {}).get('domain'), source='IPinfo')
    field('网络前缀', (network.get('asn') or {}).get('route'), source='IPinfo')
    field('公司名称', (network.get('company') or {}).get('name'), source='IPinfo')
    for label, key in [('任播网络', 'is_anycast'), ('移动网络', 'is_mobile'), ('匿名网络', 'is_anonymous'), ('卫星网络', 'is_satellite'), ('托管网络', 'is_hosting')]:
        value = network.get(key)
        field(label, '是' if value is True else '否' if value is False else None, source='IPinfo')

    heading('二、IP类型属性（未知表示未获得字段）')
    providers = [('IPinfo', 'IPinfo'), ('ipregistry', 'ipregistry'), ('ipapi', 'ipapi'), ('IP2Location', 'IP2LOCATION'), ('AbuseIPDB', 'AbuseIPDB')]
    lines.append(CYAN + pad('数据库', 14) + ''.join(pad(name, 12) for name, key in providers) + RESET)
    for label, key in [('使用类型', 'Usage'), ('公司类型', 'Company')]:
        values = data.get('Type', {}).get(key, {})
        cells = []
        for name, provider in providers:
            value = values.get(provider)
            cells.append((GREEN if present(value) else YELLOW) + pad(value if present(value) else '未知', 12))
        lines.append(CYAN + pad(label, 14) + ''.join(cells) + RESET)

    heading('三、风险评分（保留各数据库原口径，不互相换算）')
    source_lines = original.replace('\r', '').splitlines()
    for label, key in [('IP2Location', 'IP2LOCATION'), ('Scamalytics', 'SCAMALYTICS'), ('ipapi', 'ipapi'), ('AbuseIPDB', 'AbuseIPDB'), ('IPQS', 'IPQS'), ('DB-IP', 'DBIP')]:
        pattern = re.compile(r'^' + re.escape(label) + r'[:：]', re.I)
        found = next((line for line in source_lines if pattern.match(SGR.sub('', line))), None)
        if found:
            lines.append(found + RESET)
        else:
            value = data.get('Score', {}).get(key)
            field(label, value if present(value) else '未返回评分（不代表低风险）', YELLOW if not present(value) else CYAN)
    field('Cloudflare', '旧版截图项目；当前脚本无评分查询模块', YELLOW)

    heading('四、风险因子（未知不等于否）')
    groups = [ [('IP2Location','IP2LOCATION'),('ipapi','ipapi'),('ipregistry','ipregistry'),('IPQS','IPQS')],
               [('Scamalytics','SCAMALYTICS'),('ipdata','ipdata'),('IPinfo','IPinfo'),('DB-IP','DBIP'),('IPWHOIS','IPWHOIS')] ]
    for group in groups:
        lines.append(CYAN + pad('数据库', 14) + ''.join(pad(name, 12) for name, key in group) + RESET)
        for label, key in [('国家', 'CountryCode'), ('代理', 'Proxy'), ('Tor', 'Tor'), ('VPN', 'VPN'), ('服务器', 'Server'), ('滥用', 'Abuser'), ('机器人', 'Robot')]:
            cells = []
            for name, provider in group:
                value = data.get('Factor', {}).get(key, {}).get(provider)
                text = (GREEN + str(value) + RESET) if key == 'CountryCode' and present(value) else flag(value)
                cells.append(pad(text, 12))
            lines.append(CYAN + pad(label, 14) + ''.join(cells) + RESET)
    field('IPWHOIS说明', '当前版本仅保留字段，未提供查询模块。', YELLOW)

    heading('五、流媒体及AI服务（HTTP探测，不验证账号功能）')
    lines.append(CYAN + pad('服务', 18) + pad('状态', 14) + pad('地区', 12) + '解锁方式' + RESET)
    for name, key in [('TikTok','TikTok'),('Disney+','DisneyPlus'),('Netflix','Netflix'),('YouTube','Youtube'),('AmazonPV','AmazonPrimeVideo'),('Reddit','Reddit'),('ChatGPT','ChatGPT')]:
        row = data.get('Media', {}).get(key, {})
        status = row.get('Status') if present(row.get('Status')) else '未知'
        color = GREEN if status == '解锁' else RED if status == '屏蔽' else YELLOW
        region = row.get('Region') if present(row.get('Region')) else '未知'
        method = row.get('Type') if present(row.get('Type')) else '未检测'
        lines.append(CYAN + pad(name,18) + pad(color + status + RESET,14) + pad(GREEN + region + RESET,12) + YELLOW + method + RESET)
    field('方式说明', '代理模式不根据本机DNS推断原生或DNS解锁。', GRAY)

    heading('六、邮件连通性（经当前HTTP代理访问目标MX的25端口）')
    field('本机源端口25', '代理模式无法验证远端节点绑定源端口25。', YELLOW)
    statuses = {'available':'可连接（收到220）','proxy_rejected':'代理拒绝/目标连接失败','dns_failed':'MX查询失败','timeout':'超时，未确认','failed':'连接失败，未确认','unexpected_banner':'非预期SMTP响应','unsupported':'代理协议不支持','unknown':'未检测'}
    smtp = extra.get('SMTP', [])
    if smtp:
        for row in smtp:
            status = row.get('Status', 'unknown')
            field(row['Provider'], statuses.get(status, status), GREEN if status == 'available' else YELLOW)
            field('  MX', row.get('MX'))
    else:
        for name in ['Gmail','Outlook','Yahoo','Apple','QQ','MailRU','AOL','GMX','MailCOM','163','Sohu','Sina']:
            field(name, '未检测；见扩展检测状态', YELLOW)
    field('邮件范围', '只连接并读取SMTP欢迎语，未发送邮件。', GRAY)
    field('MX范围', '每家测试一个首选MX；失败不代表所有MX不可用。', GRAY)

    heading('七、DNS黑/白名单查询（原项目混合清单，DoH）')
    dnsbl = extra.get('DNSBL', {})
    counts = dnsbl.get('Counts', {})
    if dnsbl.get('Status') == 'completed':
        field('清单总数', dnsbl.get('Total'))
        field('未命中', counts.get('not_listed', 0))
        field('命中返回码', counts.get('listed_code', 0), RED if counts.get('listed_code', 0) else GREEN)
        field('白名单返回', counts.get('allowlist_code', 0))
        field('查询受限', counts.get('restricted', 0), YELLOW)
        field('DNS错误', counts.get('dns_error', 0), YELLOW)
        field('连接失败', counts.get('failed', 0), YELLOW)
        field('异常响应', counts.get('unexpected_answer', 0), YELLOW)
        field('查询解析器', dnsbl.get('Resolver'), GRAY)
        for row in dnsbl.get('Results', []):
            if row['Status'] == 'listed_code':
                field('  命中项', row['Zone'] + ' -> ' + ','.join(row.get('Answers', [])), RED)
    else:
        field('查询状态', '未完成；详细报告保留失败原因', YELLOW)
    field('结果口径', '未命中不验证列表活性；命中码需按列表核查。', GRAY)
    field('受限码说明', 'DNSWL的127.0.0.255等策略码不计作命中。', GRAY)
    field('完整逐项结果', '同名 .details.txt 与 .json，包含全部清单查询。', GRAY)

    heading('八、检测口径与缺项')
    field('地理信息来源', 'MaxMind缺项由IPinfo补充；不伪造精度。', GRAY)
    field('分流规则', '不同网站可能经过不同出站节点。', GRAY)
    field('未知/无数据', '接口未提供、查询失败或当前模式无法验证。', GRAY)
    field('未采集项目', 'Cloudflare评分、IPWHOIS、DNS解锁方式。', YELLOW)
    heading('=' * 78)
    heading('每项真实状态均保留；失败与未知不作为正常或低风险。')
    return lines
