"""临时项目上的真实浏览器验收：补充保存往返、展示与执行契约同源、阅读器资格门控。

只在系统临时目录的副本上写入；不触碰 D:/桃园密码，不执行任何小说节点，
不调用外部或收费服务（路由层拦截所有非本地请求）。
"""
import json
import shutil
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path

import yaml
from playwright.sync_api import sync_playwright

ENGINE = Path(r'D:\novelFlow')
OUT = ENGINE / '.qoder'
SRC = Path(r'D:\桃园密码\interlude-production.yaml')
WORKFLOW = 'interlude-production.yaml'
PORT = 8831
BASE = f'http://127.0.0.1:{PORT}'
SUPPLEMENT = '【临时验收】本章补充：保持克制，不得改变既定事实。'
ALLOWED_POST = {BASE + '/api/ui/session', BASE + '/api/ui/ready', BASE + '/api/production/chapter'}

result = {'steps': [], 'passed': False}
SOURCE_BYTES = SRC.read_bytes()
FROZEN_HASH = yaml.safe_load(SOURCE_BYTES.decode('utf-8'))['template']['hash']


def step(name, ok, detail=None):
    result['steps'].append({'step': name, 'ok': bool(ok), 'detail': detail})
    if not ok:
        raise SystemExit(f'验收失败：{name} -> {detail}')


def api(path, payload=None):
    url = BASE + path
    data = json.dumps(payload).encode('utf-8') if payload is not None else None
    request = urllib.request.Request(url, data=data, method='POST' if data else 'GET',
                                     headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def query(instance):
    return urllib.parse.urlencode({'project': str(tmp), 'workflow': WORKFLOW, 'instance': instance})


tmp = Path(tempfile.mkdtemp(prefix='studio-verify-'))
server = None
try:
    shutil.copy(SRC, tmp / WORKFLOW)
    server = subprocess.Popen(
        [sys.executable, '-u', str(ENGINE / 'shared' / 'server.py'), '--host', '127.0.0.1',
         '--port', str(PORT), '--project', str(tmp), '--workflow', WORKFLOW],
        cwd=str(ENGINE / 'shared'), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    health = None
    for _ in range(60):
        try:
            health = api('/api/health')
            break
        except OSError:
            server.poll()
            if server.returncode is not None:
                raise SystemExit(f'服务启动失败，退出码 {server.returncode}')
    step('临时项目绑定服务启动', health and health.get('studio_protocol') == 1, health)
    step('副本与真实项目隔离', str(tmp) not in str(SRC.parent), {'temp': str(tmp), 'source': str(SRC.parent)})

    with sync_playwright() as p:
        browser = p.chromium.launch(channel='chrome', headless=True)
        page = browser.new_page(viewport={'width': 1440, 'height': 1000})
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))

        def guard(route):
            request = route.request
            if not request.url.startswith(BASE + '/'):
                route.abort()
            elif request.method != 'GET' and request.url not in ALLOWED_POST:
                route.abort()
            else:
                route.continue_()

        page.route('**/*', guard)
        page.goto(BASE, wait_until='domcontentloaded')
        page.wait_for_function(
            "document.querySelector('.studio-layout').inert === false && document.querySelectorAll('.chapter-card').length === 4",
            timeout=60000)
        step('外层四章串行总览', page.locator('.edge-item').count() == 3, {'outer_edges': page.locator('.edge-item').count()})

        page.get_by_role('button', name='进入第51章 · 回响标准流程', exact=True).click()
        page.wait_for_function(
            "document.querySelector('.studio-main').inert === false && document.querySelectorAll('.node-card').length === 10",
            timeout=60000)
        step('下钻第51章完整十节点', page.locator('.edge-item').count() == 9, {'edges': page.locator('.edge-item').count()})

        page.locator('#node-draft_chapter').click()
        page.wait_for_selector('#inspectorDrawer.open', timeout=15000)
        baseline = page.locator('#fieldPrompt').input_value()
        step('基础提示词只读', page.locator('#fieldPrompt').evaluate('el => el.readOnly'))
        step('补充字段可编辑', not page.locator('#fieldPromptAppend').evaluate('el => el.readOnly || el.disabled'))

        page.locator('#fieldPromptAppend').fill(SUPPLEMENT)
        page.locator('#btnSaveNode').click()
        # 关键：保存成功后，详情里的只读提示词必须立刻反映服务端重新展开的新契约。
        page.wait_for_function(
            "document.getElementById('fieldPrompt').value.includes('【临时验收】')", timeout=20000)
        shown = page.locator('#fieldPrompt').input_value()
        step('保存后详情立即采用服务端展开契约', SUPPLEMENT in shown and shown != baseline,
             {'baseline_len': len(baseline), 'shown_len': len(shown)})

        on_disk = yaml.safe_load((tmp / WORKFLOW).read_text(encoding='utf-8'))
        saved = on_disk['chapters'][0]['overrides']['draft_chapter'].get('prompt_append')
        step('补充已持久化到副本 yaml', saved == SUPPLEMENT, {'prompt_append': saved})
        template_prompt = on_disk['template']['snapshot']['nodes']['draft_chapter']['prompt']
        step('章节补充未写进冻结模板', SUPPLEMENT not in template_prompt
             and len(on_disk['template']['snapshot']['nodes']) == 10
             and on_disk['template']['hash'] == FROZEN_HASH,
             {'template_nodes': len(on_disk['template']['snapshot']['nodes']),
              'template_hash': on_disk['template']['hash'], 'frozen_hash': FROZEN_HASH})

        executed = api('/api/production/prompt', {'project': str(tmp), 'workflow': WORKFLOW,
                                                 'instance': 'ch051', 'node_id': 'draft_chapter'})['prompt']
        step('执行指令卡包含同一补充', SUPPLEMENT in executed, {'len': len(executed)})
        graph = api('/api/graph?' + query('ch051'))
        step('画布图与详情同源', graph['graph']['nodes']['draft_chapter']['prompt'] == shown,
             {'api_len': len(graph['graph']['nodes']['draft_chapter']['prompt']), 'shown_len': len(shown)})

        # 窗口聚焦会触发自动同步；详情不得因此退回旧契约。
        # （同 revision 的静默图刷新短路由 studio-runtime 单元测试直接驱动真实 loadGraph 覆盖。）
        page.evaluate("window.dispatchEvent(new Event('focus'))")
        page.wait_for_timeout(1500)
        step('自动同步后详情仍为新契约', SUPPLEMENT in page.locator('#fieldPrompt').input_value())

        page.locator('#btnToggleReader').click()
        page.wait_for_selector('#readerFileList li', timeout=15000)
        listed = page.locator('#readerFileList li').all_inner_texts()
        formal = on_disk['chapters'][0]['params']['chapter_output']
        step('阅读器只列本轮有效产物', formal not in listed and any('02_正文初稿' in f for f in listed),
             {'listed': listed, 'formal_excluded': formal})
        page.locator('#btnCloseReaderModal').click()

        page.reload(wait_until='domcontentloaded')
        page.wait_for_function(
            "document.querySelector('.studio-layout').inert === false && document.querySelectorAll('.chapter-card').length === 4",
            timeout=60000)
        page.get_by_role('button', name='进入第51章 · 回响标准流程', exact=True).click()
        page.wait_for_function("document.querySelectorAll('.node-card').length === 10", timeout=60000)
        page.locator('#node-draft_chapter').click()
        page.wait_for_selector('#inspectorDrawer.open', timeout=15000)
        step('重载后补充仍在', page.locator('#fieldPromptAppend').input_value() == SUPPLEMENT
             and SUPPLEMENT in page.locator('#fieldPrompt').input_value())

        step('无页面错误', errors == [], errors)
        result['page_errors'] = errors
        browser.close()

    result['temp_project'] = str(tmp)
finally:
    if server is not None:
        server.terminate()
        try:
            server.wait(timeout=15)
        except subprocess.TimeoutExpired:
            server.kill()
    # 真实小说项目必须零改动：验收只在临时副本上写入。
    result['real_project_untouched'] = SRC.read_bytes() == SOURCE_BYTES
    result['passed'] = result['real_project_untouched'] and all(s['ok'] for s in result['steps'])
    (OUT / 'studio-browser-fix-verify.json').write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    shutil.rmtree(tmp, ignore_errors=True)

print(json.dumps({'passed': result['passed'], 'steps': len(result['steps'])}, ensure_ascii=False))
for item in result['steps']:
    print(('PASS ' if item['ok'] else 'FAIL ') + item['step'])
