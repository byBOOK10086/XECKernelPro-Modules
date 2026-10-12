#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""收下一个模块 zip：校验 module.prop → 建 Release 存 zip → 更新 hosted.json → 重建索引。

两种触发：
  * 手动 / workflow_dispatch：环境变量 INPUT_URL（zip 直链）、INPUT_ID（可留空）
  * issue 表单（用户填直链）：环境变量 ISSUE_BODY / ISSUE_NUMBER，脚本自己解析表单

校验不过就**不写任何东西**并原样把原因回帖，避免索引里出现假条目。
"""
import hashlib
import io
import json
import os
import pathlib
import re
import subprocess
import sys
import urllib.parse
import urllib.request
import zipfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from build_index import API, REPO, TOKEN, api, download, parse_prop, read_module_prop  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
ID_RE = re.compile(r'^[a-zA-Z][a-zA-Z0-9._-]+$')
UA = 'xeckernelpro-modrepo'


def fail(message):
    print('REJECT: %s' % message)
    comment = ('❌ 这个模块没有通过校验：\n\n```\n%s\n```\n\n'
               '修好之后重新开一个 issue 就行。' % message)
    issue = os.environ.get('ISSUE_NUMBER')
    if issue:
        try:
            api('/repos/%s/issues/%s/comments' % (REPO, issue), 'POST', {'body': comment})
            api('/repos/%s/issues/%s' % (REPO, issue), 'PATCH', {'state': 'closed'})
        except Exception as exc:                                   # noqa: BLE001
            print('comment failed: %s' % exc)
    return 1


def parse_issue_body(body):
    """issue 表单渲染成 '### 标题\\n\\n值'，按标题取值。"""
    fields = {}
    key = None
    for line in (body or '').splitlines():
        if line.startswith('### '):
            key = line[4:].strip()
            fields[key] = ''
        elif key is not None and line.strip() and not line.startswith('_No response_'):
            fields[key] = (fields[key] + '\n' + line).strip()
    return fields


def pick(fields, *needles):
    for name, value in fields.items():
        if any(needle in name for needle in needles):
            return (value or '').strip()
    return ''


def upload_asset(release, name, blob):
    """Release 资产必须发到 uploads.github.com，且要带 Content-Type。"""
    url = ('https://uploads.github.com/repos/%s/releases/%s/assets?name=%s'
           % (REPO, release['id'], urllib.parse.quote(name)))
    req = urllib.request.Request(url, data=blob, method='POST')
    req.add_header('Authorization', 'Bearer ' + TOKEN)
    req.add_header('Accept', 'application/vnd.github+json')
    req.add_header('User-Agent', UA)
    req.add_header('Content-Type', 'application/zip')
    with urllib.request.urlopen(req, timeout=600) as resp:
        return json.loads(resp.read())


def register_source(repo):
    """方式一：模块作者自己的 GitHub 仓库。确认它最新 Release 里有能解析的 zip，再登记进 sources.json。"""
    if not re.match(r'^[\w.-]+/[\w.-]+$', repo):
        return fail('仓库格式不对：%r（应该形如 owner/repo）' % repo)
    try:
        release = api('/repos/%s/releases/latest' % repo)
    except Exception as exc:                                       # noqa: BLE001
        return fail('读不到 %s 的最新 Release：%s' % (repo, exc))
    assets = [a for a in release.get('assets', []) if a['name'].lower().endswith('.zip')]
    if not assets:
        return fail('%s 的最新 Release（%s）里没有 .zip 资产'
                    % (repo, release.get('tag_name') or '?'))
    try:
        prop = read_module_prop(download(assets[0]['browser_download_url']))
    except Exception as exc:                                       # noqa: BLE001
        return fail('下载 / 解析 %s 失败：%s' % (assets[0]['name'], exc))
    if not prop or not ID_RE.match(prop.get('id', '')):
        return fail('zip 里的 module.prop 没有合法 id')
    module_id = prop['id']

    path = ROOT / 'sources.json'
    data = json.loads(path.read_text(encoding='utf-8')) if path.is_file() else {'modules': []}
    modules = [m for m in data.get('modules', [])
               if m.get('id') != module_id and m.get('repo') != repo]
    modules.append({'id': module_id, 'repo': repo})
    data['modules'] = sorted(modules, key=lambda m: m['id'])
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print('sources.json updated: %s -> %s' % (repo, module_id))

    subprocess.check_call([sys.executable, str(ROOT / 'scripts' / 'build_index.py')])

    issue = os.environ.get('ISSUE_NUMBER')
    if issue:
        try:
            api('/repos/%s/issues/%s/comments' % (REPO, issue), 'POST', {
                'body': ('✅ 登记好了：`%s` → %s\n\n'
                         '索引已重建，管理器刷新一下就能看到；以后你在自己仓库发新 Release，'
                         '这里每 6 小时（以及你提交索引改动时）会自动跟进。'
                         % (module_id, repo)),
            })
            api('/repos/%s/issues/%s' % (REPO, issue), 'PATCH', {'state': 'closed'})
        except Exception as exc:                                   # noqa: BLE001
            print('comment failed: %s' % exc)
    return 0


def main():
    fields = parse_issue_body(os.environ.get('ISSUE_BODY', ''))
    url = (os.environ.get('INPUT_URL') or pick(fields, '直链', 'url', 'URL')).strip()
    module_id = (os.environ.get('INPUT_ID') or pick(fields, 'ID', 'id')).strip()
    repo = (os.environ.get('INPUT_REPO') or pick(fields, '仓库', 'repo', 'Repo')).strip()
    if not url and repo:
        return register_source(repo)
    if not url.startswith('http'):
        return fail('没有拿到 zip 直链，也没有 GitHub 仓库：issue 表单里两栏至少填一个')

    print('downloading %s' % url)
    try:
        blob = download(url)
    except Exception as exc:                                       # noqa: BLE001
        return fail('直链下载失败：%s' % exc)

    try:
        prop = read_module_prop(blob)
    except zipfile.BadZipFile:
        return fail('下载到的不是 zip（%d 字节）' % len(blob))
    if not prop:
        return fail('zip 里没有 module.prop')

    prop_id = prop.get('id', '').strip()
    if module_id and module_id != prop_id:
        return fail('issue 里写的 ID (%s) 与 module.prop 里的 id (%s) 不一致' % (module_id, prop_id))
    module_id = prop_id or module_id
    if not ID_RE.match(module_id or ''):
        return fail('module.prop 里的 id 不合法：%r（要求 ^[a-zA-Z][a-zA-Z0-9._-]+$）' % module_id)
    for key in ('version', 'versionCode', 'name'):
        if not prop.get(key):
            return fail('module.prop 缺少 %s' % key)
    try:
        version_code = int(prop['versionCode'])
    except ValueError:
        return fail('module.prop 的 versionCode 不是整数：%r' % prop['versionCode'])

    sha = hashlib.sha256(blob).hexdigest()
    tag = '%s-v%d' % (module_id, version_code)
    try:
        api('/repos/%s/releases/tags/%s' % (REPO, tag))
        tag = '%s-v%d-%s' % (module_id, version_code, sha[:8])      # 同版本重发不覆盖旧资产
        print('tag exists, using %s' % tag)
    except Exception:                                              # noqa: BLE001
        pass

    asset_name = '%s-%d.zip' % (module_id, version_code)
    print('creating release %s' % tag)
    release = api('/repos/%s/releases' % REPO, 'POST', {
        'tag_name': tag,
        'name': '%s %s' % (prop.get('name', module_id), prop.get('version', version_code)),
        'body': (prop.get('description', '') + '\n\n'
                 'sha256: `%s`\n\n由模块作者通过 issue 上传。' % sha).strip(),
    })
    upload_asset(release, asset_name, blob)
    print('asset uploaded: %s (%d bytes)' % (asset_name, len(blob)))

    hosted_path = ROOT / 'hosted.json'
    hosted = json.loads(hosted_path.read_text(encoding='utf-8')) if hosted_path.is_file() else {'modules': []}
    entry = {
        'id': module_id,
        'tag': tag,
        'asset': asset_name,
        'versionCode': version_code,
        'sha256': sha,
        'size': len(blob),
    }
    modules = [m for m in hosted.get('modules', []) if m.get('id') != module_id]
    modules.append(entry)
    hosted['modules'] = sorted(modules, key=lambda m: m['id'])
    hosted_path.write_text(json.dumps(hosted, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print('hosted.json updated')

    subprocess.check_call([sys.executable, str(ROOT / 'scripts' / 'build_index.py')])

    issue = os.environ.get('ISSUE_NUMBER')
    if issue:
        try:
            api('/repos/%s/issues/%s/comments' % (REPO, issue), 'POST', {
                'body': ('✅ 收下了：`%s` v%s（versionCode %d）\n\n'
                         '直链：https://github.com/%s/releases/download/%s/%s\n\n'
                         '索引已重建，管理器刷新一下就能看到。'
                         % (module_id, prop.get('version', version_code), version_code,
                            REPO, tag, asset_name)),
            })
            api('/repos/%s/issues/%s' % (REPO, issue), 'PATCH', {'state': 'closed'})
        except Exception as exc:                                   # noqa: BLE001
            print('comment failed: %s' % exc)
    return 0


if __name__ == '__main__':
    sys.exit(main())
