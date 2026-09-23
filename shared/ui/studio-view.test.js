'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const view = require('./studio-view.js');

const production = { id: 'interlude', chapters: [{ id: 'ch051' }, { id: 'ch052' }] };

test('计划模型只取状态，不采用图谱原始 Gemini 或实际模型', () => {
  assert.equal(typeof view.getResolvedModel, 'function');
  assert.equal(view.getResolvedModel({ model: 'Qwen' }, { model: 'Gemini' }), 'Qwen');
  assert.equal(view.getResolvedModel({}, { model: 'Gemini' }), null);
  assert.equal(view.getResolvedModel({ actual_model: 'Qwen' }), null);
  assert.equal(view.getResolvedModel({ model: '  ' }), null);
});

test('实际派发仅在模型及非空证据同时存在时标注宿主回报', () => {
  assert.equal(typeof view.modelPresentation, 'function');
  assert.equal(view.modelPresentation({}).planned, '未配置');
  assert.equal(view.modelPresentation({ actual_model: 'Qwen' }).actual, '实际派发尚未核验');
  assert.equal(view.modelPresentation({ actual_model: 'Qwen', model_evidence: {} }).actual, '实际派发尚未核验');
  assert.equal(view.modelPresentation({ actual_model: 'Qwen', model_evidence: [] }).actual, '实际派发尚未核验');
  assert.equal(view.modelPresentation({ actual_model: 'Qwen', model_evidence: { log: 'dispatch:17' } }).actual, '宿主回报：Qwen');
});

test('节点状态中文标签覆盖生产与旧工作流状态', () => {
  assert.equal(typeof view.statusPresentation, 'function');
  for (const [status, label] of Object.entries({ pending: '待开始', running: '运行中', succeeded: '已完成', failed: '失败', 'pending-human': '待人工确认', blocked: '已阻塞', stale: '已过期', current: '已完成' })) {
    assert.equal(view.statusPresentation({ status }).label, label);
  }
  assert.equal(view.statusPresentation({}, true).status, 'pending');
  assert.equal(view.statusPresentation({ status: 'stale', running: true }).status, 'running');
  assert.equal(view.statusPresentation({ status: 'unknown' }).label, '未知状态');
});

test('生产内外层结构只读，仅白名单实例开放补充字段', () => {
  assert.equal(typeof view.viewPolicy, 'function');
  const outer = view.viewPolicy({ kind: 'production' }, production, null);
  const inner = view.viewPolicy({ nodes: {} }, production, 'ch051');
  assert.equal(outer.structureReadonly, true);
  assert.equal(outer.canEditSupplements, false);
  assert.equal(inner.structureReadonly, true);
  assert.equal(inner.canEditSupplements, true);
  assert.equal(inner.canRun, false);
  assert.equal(view.viewPolicy({}, production, 'ch999').canEditSupplements, false);
  assert.equal(view.viewPolicy({}, null, null, true).canRun, false);
  assert.equal(view.viewPolicy({}, null, null).structureReadonly, false);
});

test('导航白名单仅允许本任务章节与外层', () => {
  assert.equal(typeof view.canNavigate, 'function');
  assert.equal(view.canNavigate(production, null), true);
  assert.equal(view.canNavigate(production, 'ch051'), true);
  assert.equal(view.canNavigate(production, 'ch999'), false);
  assert.equal(view.canNavigate(null, 'ch051'), false);
});

test('布局缓存按项目、工作流、实例完全隔离', () => {
  assert.equal(typeof view.layoutKey, 'function');
  assert.notEqual(view.layoutKey('p', 'w', null), view.layoutKey('p', 'w', 'ch051'));
  assert.notEqual(view.layoutKey('p', 'w', 'ch051'), view.layoutKey('p', 'w', 'ch052'));
});

test('生产阅读器仅使用当前实例已解析输出，无外层或默认旧章路径', () => {
  assert.equal(typeof view.productionOutputs, 'function');
  const graph = { params: { chapter_workspace: '工作区/插曲/第51章', chapter_output: '正文/第51章.md' }, nodes: { draft: { outputs: ['{chapter_workspace}/初稿.md', '{chapter_output}', '{unknown}/旧稿.md'] }, final: { outputs: ['{chapter_output}'] } } };
  assert.deepEqual(view.productionOutputs(graph, production, null), []);
  assert.deepEqual(view.productionOutputs(graph, production, 'ch999'), []);
  assert.deepEqual(view.productionOutputs(graph, production, 'ch051'), ['工作区/插曲/第51章/初稿.md', '正文/第51章.md']);
});

test('Windows正反斜杠路径属于同一通知上下文，其他任务仍被隔离', () => {
  const scope = { bound_project: 'novel', project_path: 'D:\\books\\novel' };
  assert.equal(view.eventMatchesContext({ project: 'novel', path: 'D:/books/novel', workflow: 'production.yaml' }, 'production.yaml', scope, 'novel'), true);
  assert.equal(view.eventMatchesContext({ project: 'novel', path: 'D:/books/other', workflow: 'production.yaml' }, 'production.yaml', scope, 'novel'), false);
  assert.equal(view.eventMatchesContext({ project: 'novel', path: 'D:/books/novel', workflow: 'graph.yaml' }, 'production.yaml', scope, 'novel'), false);
});

test('旧正式稿没有本轮成功归档回执时不冒充本轮可读产物', () => {
  const graph = { nodes: { draft: { kind: 'agent', outputs: ['work/new.md'] }, author_accept: { kind: 'human', outputs: ['正文/old.md'] } } };
  assert.deepEqual(view.productionOutputs(graph, production, 'ch051', { nodes: {} }), ['work/new.md']);
  assert.deepEqual(view.productionOutputs(graph, production, 'ch051', { nodes: { author_accept: { status: 'succeeded', attempt_count: 1 } } }), ['work/new.md', '正文/old.md']);
});

test('补充保存仅包含合法节点的两个允许字段且不改写展开图谱', () => {
  assert.equal(typeof view.chapterOverrides, 'function');
  const nodes = { draft: { kind: 'agent', prompt: 'base' }, stats: { kind: 'command' } };
  const result = view.chapterOverrides(nodes, { draft: { prompt_append: '原补充', model: 'bad' }, stats: { prompt_append: 'bad', inputs_add: ['source.md'] }, unknown: { inputs_add: ['bad'] } }, 'draft', { prompt_append: '本章要求', inputs_add: ['extra.md'], role: 'bad' });
  assert.deepEqual(result, { draft: { prompt_append: '本章要求', inputs_add: ['extra.md'] }, stats: { inputs_add: ['source.md'] } });
  assert.equal(nodes.draft.prompt, 'base');
});

test('旧图谱保存不再发送 node.model，且不修改内存原图', () => {
  assert.equal(typeof view.legacyGraphForSave, 'function');
  const graph = { nodes: { draft: { kind: 'agent', model: 'Gemini', prompt: 'base' } }, params: { chapter: 51 } };
  const saved = view.legacyGraphForSave(graph);
  assert.deepEqual(saved.nodes.draft, { kind: 'agent', prompt: 'base' });
  assert.equal(graph.nodes.draft.model, 'Gemini');
  assert.equal(saved.params.chapter, 51);
});

test('旧图保存保留宿主认可的显式模型绑定，只剥离未生效的跨宿主残值', () => {
  const graph = { nodes: {
    pinned: { kind: 'agent', model: 'qmodel_38max', model_tier: 'flash', role: 'writer' },
    mapped: { kind: 'agent', model: 'gemini-3.8-flash-high', subagent_type: 'researcher' },
    leftover: { kind: 'agent', model: 'Gemini', model_tier: 'flash' }
  }, params: { chapter: 51 } };
  const state = { nodes: {
    pinned: { model: 'qmodel_38max', model_origin: 'explicit-matched' },
    mapped: { model: 'qfmodel', model_origin: 'role-mapped' },
    leftover: { model: 'qfmodel', model_origin: 'tier-mapped' }
  } };
  const saved = view.legacyGraphForSave(graph, state);
  assert.equal(saved.nodes.pinned.model, 'qmodel_38max', '宿主生效的显式绑定不得被普通保存删除');
  assert.equal(saved.nodes.pinned.model_tier, 'flash');
  assert.equal(saved.nodes.mapped.model, undefined, '角色映射忽略遗留 model，应剥离');
  assert.equal(saved.nodes.leftover.model, undefined, '未被宿主采纳的跨宿主残值应剥离');
  assert.equal(graph.nodes.pinned.model, 'qmodel_38max', '不修改内存原图');
  assert.equal(graph.nodes.mapped.model, 'gemini-3.8-flash-high');
  assert.equal(graph.nodes.leftover.model, 'Gemini');
});

test('跨实例、跨工作流、往返同视图及旧请求的迟到响应均失效', () => {
  assert.equal(typeof view.responseMatches, 'function');
  const request = { query: 'workflow=w&instance=ch051', contextVersion: 2, graphLoadVersion: 5 };
  assert.equal(view.responseMatches(request, { ...request }), true);
  assert.equal(view.responseMatches(request, { ...request, query: 'workflow=w&instance=ch052' }), false);
  assert.equal(view.responseMatches(request, { ...request, query: 'workflow=x&instance=ch051' }), false);
  assert.equal(view.responseMatches(request, { ...request, contextVersion: 4 }), false);
  assert.equal(view.responseMatches(request, { ...request, graphLoadVersion: 6 }), false);
});

test('生产总览按章节白名单顺序显示串行依赖，不修改内层结构', () => {
  assert.equal(typeof view.displayAfter, 'function');
  const graph = { kind: 'production', nodes: { ch052: { instance: 'ch052', after: [] }, ch051: { instance: 'ch051', after: [] } } };
  assert.deepEqual(view.displayAfter(graph, production, 'ch051'), []);
  assert.deepEqual(view.displayAfter(graph, production, 'ch052'), ['ch051']);
  assert.deepEqual(graph.nodes.ch052.after, []);
  const inner = { nodes: { review: { after: ['draft', 'context'] } } };
  assert.deepEqual(view.displayAfter(inner, production, 'review'), ['draft', 'context']);
});
