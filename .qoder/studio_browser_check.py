"""只验收本地工作台；禁止执行节点、修改正文或请求外部服务。"""
from pathlib import Path
import json
from playwright.sync_api import sync_playwright

OUT = Path(__file__).resolve().parent
BASE = 'http://127.0.0.1:8830'

with sync_playwright() as p:
    browser = p.chromium.launch(channel='chrome', headless=True)
    page = browser.new_page(viewport={'width': 1440, 'height': 1000}, device_scale_factor=1)
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))

    def allowed(route):
        request = route.request
        if not request.url.startswith(BASE + '/'):
            route.abort()
        elif request.method != 'GET' and request.url not in (BASE + '/api/ui/session', BASE + '/api/ui/ready'):
            route.abort()
        else:
            route.continue_()

    page.route('**/*', allowed)
    page.goto(BASE, wait_until='domcontentloaded')
    page.wait_for_function("document.querySelector('.studio-layout').inert === false && document.querySelectorAll('.chapter-card').length === 4", timeout=60000)
    outer = page.locator('.chapter-card').all_inner_texts()
    assert all(f'ch{n:03d}' in outer[n - 51] for n in range(51, 55))
    assert page.locator('.edge-item').count() == 3
    page.screenshot(path=str(OUT / 'production-overview.png'))

    models = {}
    for number, title in [(51, '回响'), (52, '同行'), (53, '问道'), (54, '引信')]:
        page.get_by_role('button', name=f'进入第{number}章 · {title}标准流程', exact=True).click()
        page.wait_for_function("document.querySelector('.studio-main').inert === false && document.querySelectorAll('.node-card').length === 10", timeout=60000)
        assert page.locator('.edge-item').count() == 9
        assert f'ch{number:03d}' in page.locator('#boundStudioContext').inner_text()
        # 浏览器真实鼠标点击，而非注入 DOM click。
        page.locator('#node-explore_context').click()
        assert page.locator('#inspectorDrawer').evaluate("el => el.classList.contains('open')")
        assert page.locator('#fieldModel').input_value() == 'qfmodel'
        assert page.locator('#fieldModel').evaluate('el => el.readOnly')
        assert page.locator('#fieldPrompt').evaluate('el => el.readOnly')
        assert not page.locator('#fieldPromptAppend').evaluate('el => el.readOnly || el.disabled')
        models[f'ch{number:03d}'] = page.locator('#fieldModel').input_value()
        if number == 51:
            page.screenshot(path=str(OUT / 'production-ch051-inspector.png'))
        page.locator('#btnProductionRoot').click()
        page.wait_for_function("document.querySelector('.studio-main').inert === false && document.querySelectorAll('.chapter-card').length === 4", timeout=60000)

    assert errors == [], errors
    result = {'viewport': '1440x1000', 'real_mouse_navigation': '4/4', 'nodes_per_chapter': 10,
              'edges_per_chapter': 9, 'outer_edges': 3, 'context_model': models,
              'page_errors': errors, 'novel_execution': False, 'external_requests': False,
              'screenshots': ['production-overview.png', 'production-ch051-inspector.png']}
    (OUT / 'studio-browser-result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False))
    browser.close()
