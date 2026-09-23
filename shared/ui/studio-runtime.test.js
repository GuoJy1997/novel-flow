'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const view = require('./studio-view.js');

// 仅替身 DOM/HTTP/时钟；实际执行 studio.js 的保存、刷新与阅读器函数。
function runtime() {
  class Element {
    constructor() {
      const classes = new Set(['hidden']);
      this.classList = { add: x => classes.add(x), remove: x => classes.delete(x), contains: x => classes.has(x),
        toggle: (x, yes) => yes ? classes.add(x) : classes.delete(x), [Symbol.iterator]: () => classes.values() };
      this.children = []; this.style = {}; this.value = ''; this.textContent = ''; this._html = '';
    }
    set innerHTML(value) { this._html = value; this.children = []; }
    get innerHTML() { return this._html; }
    appendChild(el) { this.children.push(el); }
    append(el) { this.appendChild(el); }
    replaceChildren(...els) { this.children = els; }
    querySelector() { return new Element(); }
    querySelectorAll() { return []; }
    addEventListener() {}
    setAttribute() {}
    removeAttribute() {}
    contains() { return false; }
    remove() {}
  }
  const elements = new Map();
  const element = id => { if (!elements.has(id)) elements.set(id, new Element()); return elements.get(id); };
  const document = { body: new Element(), activeElement: null,
    getElementById: id => id.startsWith('node-') ? null : element(id),
    createElement: () => new Element(), createElementNS: () => new Element(),
    querySelector: () => new Element(), querySelectorAll: () => [] };
  let request;
  const context = vm.createContext({ document, window: { StudioView: view, addEventListener() {} },
    URLSearchParams, Option: function (label, value) { this.value = value; this.text = label; },
    setTimeout: () => 1, clearTimeout() {}, console, confirm: () => true,
    fetch: async (url, options) => ({ ok: true, json: async () => request(url, options) }) });
  const source = fs.readFileSync(require.resolve('./studio.js'), 'utf8').replace(
    "window.addEventListener('DOMContentLoaded', init);",
    `globalThis.app = {
      configure(data) { currentProject='p'; currentWorkflow='production.yaml'; currentInstance='ch051';
        currentGraph=data.graph; currentState=data.state; currentProduction=data.production;
        graphRevision=data.revision; uiReady=true; chapterOverrides={}; },
      read: () => ({ graph:currentGraph, reading:currentReadingFile, revision:graphRevision }),
      dirty: () => { inspectorDirty=true; editVersion++; fieldPromptAppend.value='newer unsaved'; },
      legacy: () => { currentProduction=null; currentInstance=null; readerDirty=true; },
      saveGraphToServer, loadGraph, applyStateUpdate, openReaderModal, loadFileContent
    };`);
  vm.runInContext(source, context);
  return { app: context.app, element, request: fn => { request = fn; } };
}

function data(status = 'pending', prompt = 'OLD', revision = 'r1') {
  return { revision, currentChapter: 51,
    production: { id: 'batch', instance: 'ch051', chapters: [{ id: 'ch051', params: { chapter_num: 51 }, overrides: {} }] },
    graph: { params: {}, nodes: {
      draft: { kind: 'agent', prompt, inputs: [prompt + '.txt'], outputs: ['draft.md'] },
      approve: { kind: 'human', inputs: ['draft.md'], outputs: ['formal.md'] }
    } },
    state: { nodes: { draft: { status: 'succeeded' }, approve: { status, attempt_count: status === 'pending' ? 0 : 1 } } }
  };
}
const flush = async () => { for (let i = 0; i < 8; i++) await Promise.resolve(); };

test('保存补充后详情与静默刷新均采用服务端已展开的新契约', async () => {
  const r = runtime(); r.app.configure(data());
  const saved = data('pending', 'NEW', 'r2');
  r.request(() => ({ success: true, ...saved }));
  assert.equal(await r.app.saveGraphToServer(), true);
  assert.equal(r.app.read().graph.nodes.draft.prompt, 'NEW');
  assert.equal(r.app.read().graph.nodes.draft.inputs[0], 'NEW.txt');
  assert.equal(await r.app.loadGraph('p', null, true), true);
  assert.equal(r.app.read().graph.nodes.draft.prompt, 'NEW');
});

test('保存响应更新只读契约但不覆盖响应期间新输入的补充草稿', async () => {
  const r = runtime(); r.app.configure(data());
  let release;
  r.request(() => new Promise(resolve => { release = resolve; }));
  const saving = r.app.saveGraphToServer();
  await flush(); r.app.dirty();
  release({ success: true, ...data('pending', 'SAVED', 'r2') });
  assert.equal(await saving, true);
  assert.equal(r.app.read().graph.nodes.draft.prompt, 'SAVED');
  assert.equal(r.element('fieldPromptAppend').value, 'newer unsaved');
});

test('归档失效时阅读器立即清除已不合格的正式稿', async () => {
  const r = runtime(); r.app.configure(data('succeeded'));
  r.request(() => ({ exists: true, content: 'FORMAL' }));
  await r.app.openReaderModal(); await r.app.loadFileContent('formal.md');
  assert.equal(r.element('readerTextarea').value, 'FORMAL');
  r.app.applyStateUpdate(data('stale'));
  assert.notEqual(r.app.read().reading, 'formal.md');
  assert.notEqual(r.element('readerTextarea').value, 'FORMAL');
});

test('归档由待确认变成功后重开阅读器可看到新增正式稿', async () => {
  const r = runtime(); r.app.configure(data());
  r.request(() => ({ exists: true, content: 'DRAFT' }));
  await r.app.openReaderModal(); await flush();
  r.app.applyStateUpdate(data('succeeded'));
  await r.app.openReaderModal();
  assert.ok(r.element('readerFileList').children.some(el => el.textContent === 'formal.md'));
});

test('正式稿读取期间失效，迟到正文不能再次进入阅读器', async () => {
  const r = runtime(); r.app.configure(data('succeeded'));
  let release;
  r.request(() => new Promise(resolve => { release = resolve; }));
  const reading = r.app.loadFileContent('formal.md'); await flush();
  r.app.applyStateUpdate(data('stale'));
  release({ exists: true, content: 'LATE FORMAL' }); await reading;
  assert.notEqual(r.app.read().reading, 'formal.md');
  assert.notEqual(r.element('readerTextarea').value, 'LATE FORMAL');
});

test('旧图阅读器重开不丢弃未保存手稿', async () => {
  const r = runtime(); r.app.configure(data('succeeded'));
  r.request(() => ({ exists: true, content: 'ORIGINAL' }));
  await r.app.loadFileContent('draft.md'); r.app.legacy();
  r.element('readerTextarea').value = 'UNSAVED';
  await r.app.openReaderModal();
  assert.equal(r.element('readerTextarea').value, 'UNSAVED');
});
