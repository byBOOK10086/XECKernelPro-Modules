#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从 sources.json / hosted.json 生成 modules.json（与官方 modules.kernelsu.org 同 schema）。

数据源两类：
  * sources.json —— {"modules": [{"id": "...", "repo": "owner/name"}]}
    取该仓库**最新 Release** 里的 zip 资产（模块作者自己的仓库，zip 直链指向他自己的 Release）。
  * hosted.json  —— {"modules": [{"id": "...", "tag": "...", "asset": "...", "versionCode": N,
                                   "sha256": "...", "size": N}]}
    取**本仓库** Release 里的 zip 资产（用户没有自己的仓库时，我们把 zip 收进来托管）。

name / summary / versionCode 一律以 zip 里 module.prop 的实际内容为准 —— 索引和模块本体
对不上是最容易出的坑（作者改了 prop 忘了改索引）。zip 打不开或没有 module.prop 就跳过并打印原因，
宁可少一条也不要写一条假的进索引。
"""
import hashlib
import io
import json
import os
import pathlib
import sys
import urllib.request
import zipfile

TOKEN = os.environ.get('GITHUB_TOKEN') or os.environ.get('GH_TOKEN') or ''
REPO = os.environ.get('GITHUB_REPOSITORY', 'byBOOK10086/XECKernelPro-Modules')
API = 'https://api.github.com'
ROOT = pathlib.Path(__file__).resolve().parent.parent

UA = 'xeckernelpro-modrepo'


def api(path, method='GET', body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(API + path, data=data, method=method)
    req.add_header('Accept', 'application/vnd.github+json')
    req.add_header('User-Agent', UA)
    if TOKEN:
        req.add_header('Authorization', 'Bearer ' + TOKEN)
    with urllib.request.urlopen(req, timeout=90) as resp:
        blob = resp.read()
    return json.loads(blob) if blob else None


def download(url):
    req = urllib.request.Request(url)
    req.add_header('User-Agent', UA)
    if TOKEN and url.startswith(API):
        req.add_header('Authorization', 'Bearer ' + TOKEN)
    with urllib.request.urlopen(req, timeout=300) as resp:
        return resp.read()


def parse_prop(text):
    out = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        out[key.strip()] = value.strip()
    return out


def read_module_prop(blob):
    """zip 里最短路径的 module.prop；找不到返回 None。"""
    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        names = [n for n in zf.namelist() if n.rsplit('/', 1)[-1] == 'module.prop']
        if not names:
            return None
        return parse_prop(zf.read(sorted(names, key=len)[0]).decode('utf-8', 'replace'))


def load_json(name, default):
    path = ROOT / name
    if not path.is_file():
        return default
    return json.loads(path.read_text(encoding='utf-8'))


def split_authors(value, link):
    parts = []
    for chunk in value.replace('&', ',').replace('、', ',').split(','):
        chunk = chunk.strip()
        if chunk:
            parts.append({'name': chunk, 'link': link})
    return parts


def entry_from(prop, *, module_id, download_url, version_code, release_time, created_at,
               stars, link):
    return {
        'moduleId': prop.get('id') or module_id,
        'moduleName': prop.get('name') or (prop.get('id') or module_id),
        'authors': split_authors(prop.get('author', ''), link),
        'summary': prop.get('description', ''),
        'metamodule': prop.get('metamodule', '0').strip() in ('1', 'true', 'yes'),
        'stargazerCount': stars,
        'updatedAt': release_time,
        'createdAt': created_at or release_time,
        'latestRelease': {
            'name': prop.get('version', str(version_code)),
            'time': release_time,
            'versionCode': int(prop.get('versionCode') or version_code or 0),
            'downloadUrl': download_url,
        },
    }


def build_from_sources(entries):
    for item in load_json('sources.json', {'modules': []}).get('modules', []):
        repo = (item.get('repo') or '').strip()
        if not repo:
            print('skip: entry without repo: %r' % item)
            continue
        try:
            meta = api('/repos/%s' % repo)
            release = api('/repos/%s/releases/latest' % repo)
        except Exception as exc:                                   # noqa: BLE001
            print('skip %s: %s' % (repo, exc))
            continue
        assets = [a for a in release.get('assets', []) if a['name'].lower().endswith('.zip')]
        if not assets:
            print('skip %s: latest release has no zip asset' % repo)
            continue
        asset = assets[0]
        try:
            prop = read_module_prop(download(asset['browser_download_url']))
        except Exception as exc:                                   # noqa: BLE001
            print('skip %s: %s' % (repo, exc))
            continue
        if not prop or not prop.get('id'):
            print('skip %s: no usable module.prop in %s' % (repo, asset['name']))
            continue
        module_id = item.get('id') or prop['id']
        if item.get('id') and item['id'] != prop['id']:
            print('warn %s: sources.json id=%s but module.prop id=%s (using prop id)'
                  % (repo, item['id'], prop['id']))
            module_id = prop['id']
        entries.append(entry_from(
            prop,
            module_id=module_id,
            download_url=asset['browser_download_url'],
            version_code=prop.get('versionCode', 0),
            release_time=release.get('published_at') or meta.get('pushed_at') or '',
            created_at=meta.get('created_at') or '',
            stars=meta.get('stargazers_count', 0),
            link='https://github.com/%s' % repo,
        ))
        print('ok   %s -> %s (%s)' % (repo, module_id, asset['name']))


def build_from_hosted(entries):
    for item in load_json('hosted.json', {'modules': []}).get('modules', []):
        module_id = (item.get('id') or '').strip()
        tag = (item.get('tag') or '').strip()
        asset = (item.get('asset') or '').strip()
        if not (module_id and tag and asset):
            print('skip: incomplete hosted entry: %r' % item)
            continue
        url = 'https://github.com/%s/releases/download/%s/%s' % (REPO, tag, asset)
        try:
            release = api('/repos/%s/releases/tags/%s' % (REPO, tag))
            blob = download(url)
        except Exception as exc:                                   # noqa: BLE001
            print('skip hosted %s: %s' % (module_id, exc))
            continue
        prop = read_module_prop(blob)
        if not prop or not prop.get('id'):
            print('skip hosted %s: no usable module.prop' % module_id)
            continue
        entries.append(entry_from(
            prop,
            module_id=module_id,
            download_url=url,
            version_code=item.get('versionCode') or prop.get('versionCode', 0),
            release_time=release.get('published_at') or '',
            created_at=release.get('created_at') or '',
            stars=0,
            link='https://github.com/%s' % REPO,
        ))
        print('ok   hosted %s (%s)' % (module_id, asset))


def main():
    entries = []
    build_from_sources(entries)
    build_from_hosted(entries)

    seen = {}
    for entry in entries:                       # 同 id 只留版本号最大的那条
        old = seen.get(entry['moduleId'])
        if old is None or entry['latestRelease']['versionCode'] >= old['latestRelease']['versionCode']:
            seen[entry['moduleId']] = entry
    ordered = sorted(seen.values(), key=lambda e: e['updatedAt'] or '', reverse=True)

    out = ROOT / 'modules.json'
    text = json.dumps(ordered, ensure_ascii=False, indent=2) + '\n'
    old_text = out.read_text(encoding='utf-8') if out.is_file() else ''
    out.write_text(text, encoding='utf-8')
    print('modules.json: %d entr%s %s'
          % (len(ordered), 'y' if len(ordered) == 1 else 'ies',
             '(changed)' if text != old_text else '(unchanged)'))
    for entry in ordered:
        print('  - %-28s v%-8s %s' % (entry['moduleId'],
                                      entry['latestRelease']['versionCode'],
                                      hashlib.sha256(entry['latestRelease']['downloadUrl'].encode()).hexdigest()[:8]))
    return 0


if __name__ == '__main__':
    sys.exit(main())
