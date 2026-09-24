(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.StudioView = factory();
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  function getResolvedModel(entry) {
    return typeof entry?.model === 'string' ? entry.model.trim() || null : null;
  }

  function hasEvidence(value) {
    if (typeof value === 'string') return value.trim().length > 0;
    if (value && typeof value === 'object') return Object.values(value).some(hasEvidence);
    return typeof value === 'number' && Number.isFinite(value);
  }

  function modelPresentation(entry) {
    const actual = typeof entry?.actual_model === 'string' ? entry.actual_model.trim() : '';
    return {
      planned: getResolvedModel(entry) || '未配置',
      actual: actual && hasEvidence(entry?.model_evidence) ? `宿主回报：${actual}` : '实际派发尚未核验',
      note: typeof entry?.model_note === 'string' ? entry.model_note : ''
    };
  }

  function statusPresentation(entry, production = false) {
    const labels = { pending: '待开始', running: '运行中', succeeded: '已完成', current: '已完成', failed: '失败', 'pending-human': '待人工确认', blocked: '已阻塞', stale: '已过期' };
    const raw = entry?.running ? 'running' : entry?.status || (production ? 'pending' : 'stale');
    const status = Object.prototype.hasOwnProperty.call(labels, raw) ? raw : 'unknown';
    return { status, label: labels[status] || '未知状态' };
  }

  function canNavigate(production, instance) {
    return !!production && (instance === null || (production.chapters || []).some(ch => ch.id === instance));
  }

  function viewPolicy(graph, production, instance, bound = false) {
    const structureReadonly = !!production || graph?.kind === 'production';
    return {
      structureReadonly,
      canEditSupplements: structureReadonly && instance !== null && canNavigate(production, instance),
      canRun: !bound && !structureReadonly
    };
  }

  function layoutKey(project, workflow, instance) {
    return JSON.stringify([project, workflow, instance || null]);
  }

  function eventMatchesContext(data, workflow, bound, project) {
    const normalize = value => {
      const path = String(value || '').replace(/\\/g, '/').replace(/\/+$/, '');
      return /^[a-z]:/i.test(path) ? path.toLowerCase() : path;
    };
    if (data.workflow !== workflow) return false;
    if (bound) return data.project === bound.bound_project && normalize(data.path) === normalize(bound.project_path);
    return data.project === project || normalize(data.path) === normalize(project);
  }

  function productionOutputs(graph, production, instance, state = null) {
    if (!instance || !canNavigate(production, instance) || graph?.kind === 'production') return [];
    const params = graph?.params || {};
    const files = Object.entries(graph?.nodes || {}).filter(([id, node]) => node.kind !== 'human' ||
      (state?.nodes?.[id]?.status === 'succeeded' && state.nodes[id].attempt_count > 0))
      .flatMap(([, node]) => node.outputs || []).filter(file => typeof file === 'string').map(file => {
      for (let i = 0; i <= Object.keys(params).length; i++) {
        const expanded = file.replace(/\{([a-zA-Z_][a-zA-Z0-9_]*)\}/g, (match, key) => params[key] === undefined ? match : String(params[key]));
        if (expanded === file) break;
        file = expanded;
      }
      return file;
    }).filter(file => file && !/\{[^}]+\}/.test(file));
    return [...new Set(files)];
  }

  function chapterOverrides(nodes, existing, nodeId, fields) {
    const result = {};
    Object.entries(nodes || {}).forEach(([id, node]) => {
      const source = (id === nodeId ? fields : existing?.[id]) || {};
      const item = {};
      if (node.kind === 'agent' && typeof source.prompt_append === 'string' && source.prompt_append) item.prompt_append = source.prompt_append;
      if (Array.isArray(source.inputs_add)) {
        const inputs = source.inputs_add.filter(input => typeof input === 'string').map(input => input.trim()).filter(Boolean);
        if (inputs.length) item.inputs_add = inputs;
      }
      if (Object.keys(item).length) result[id] = item;
    });
    return result;
  }

  function legacyGraphForSave(graph, state = null) {
    const snapshot = JSON.parse(JSON.stringify(graph));
    Object.entries(snapshot.nodes || {}).forEach(([id, node]) => {
      // 只有宿主当前真正采纳的显式绑定 (explicit-matched) 才保留：那是无角色节点钉死模型的逃生舱，
      // 删掉会让下一次执行静默换成档位映射模型。角色映射按设计忽略遗留 model，档位映射/未识别
      // 宿主说明该值本就未生效，剥离以免把某个宿主的具体模型名写死进跨宿主图谱。
      if (state?.nodes?.[id]?.model_origin !== 'explicit-matched') delete node.model;
    });
    return snapshot;
  }

  function responseMatches(request, current) {
    return request.query === current.query && request.contextVersion === current.contextVersion &&
      request.graphLoadVersion === current.graphLoadVersion;
  }

  function displayAfter(graph, production, id) {
    const after = graph?.nodes[id]?.after || [];
    if (graph?.kind !== 'production' || after.length) return after;
    // 总览无显式边时，使用任务声明的章节顺序；只用于展示，不写回图谱。
    const ids = Object.keys(graph.nodes || {});
    const sequence = (production?.chapters || []).map(ch => ids.find(key => (graph.nodes[key].instance || key) === ch.id)).filter(Boolean);
    const index = sequence.indexOf(id);
    return index > 0 ? [sequence[index - 1]] : [];
  }

  return { getResolvedModel, modelPresentation, statusPresentation, viewPolicy, canNavigate, layoutKey, productionOutputs, chapterOverrides, legacyGraphForSave, responseMatches, displayAfter, eventMatchesContext };
});
