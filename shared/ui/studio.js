// Novel Pipeline Studio - 前端画布交互与调度逻辑 (v1.0)
(function () {
  'use strict';

  // 全局应用状态
  let currentProject = '';
  let currentGraph = null;
  let currentState = null;
  let selectedNodeId = null;
  let activeEventSource = null;
  let detectedHost = null; // 当前宿主 Agent（由服务端环境指纹感知: qoder/antigravity/unknown）

  // 画布变换状态 (Pan & Zoom)
  let zoom = 1.0;
  let panX = 40;
  let panY = 60;
  let isPanning = false;
  let startMouseX = 0;
  let startMouseY = 0;

  // 节点拖拽与位置缓存
  let draggingNodeId = null;
  let dragOffsetX = 0;
  let dragOffsetY = 0;
  let nodePositions = {}; // nodeId -> { x, y }
  let currentWorkflow = 'graph.yaml';
  let workflowPositions = {}; // project::workflow -> nodePositions

  // 连线状态
  let connectingFromId = null;
  let isDragConnecting = false;
  let connectStartMousePos = null;
  let tempEdgeStartPos = { x: 0, y: 0 };

  // 动态章节/分卷状态
  let currentChapter = 1;

  // DOM 元素引用
  const projectSelect = document.getElementById('projectSelect');
  const workflowSelect = document.getElementById('workflowSelect');
  const btnOpenNewProjectModal = document.getElementById('btnOpenNewProjectModal');
  const btnOpenAddPathModal = document.getElementById('btnOpenAddPathModal');

  const chapterSelectorGroup = document.getElementById('chapterSelectorGroup');
  const chapterSelectorLabel = document.getElementById('chapterSelectorLabel');
  const chapterUnitPrefix = document.getElementById('chapterUnitPrefix');
  const chapterUnitSuffix = document.getElementById('chapterUnitSuffix');
  const chapterInput = document.getElementById('chapterInput');
  const btnPrevChapter = document.getElementById('btnPrevChapter');
  const btnNextChapter = document.getElementById('btnNextChapter');

  const btnOpenAddNodeModal = document.getElementById('btnOpenAddNodeModal');
  const btnSaveGraph = document.getElementById('btnSaveGraph');
  const btnRefreshStatus = document.getElementById('btnRefreshStatus');
  const btnReconcile = document.getElementById('btnReconcile');
  const btnToggleReader = document.getElementById('btnToggleReader');
  const btnToggleTerminal = document.getElementById('btnToggleTerminal');

  const canvasViewport = document.getElementById('canvasViewport');
  const nodesLayer = document.getElementById('nodesLayer');
  const edgesGroup = document.getElementById('edgesGroup');
  const tempEdge = document.getElementById('tempEdge');
  const connectTipBar = document.getElementById('connectTipBar');
  const btnCancelConnect = document.getElementById('btnCancelConnect');

  const btnZoomIn = document.getElementById('btnZoomIn');
  const btnZoomReset = document.getElementById('btnZoomReset');
  const btnZoomOut = document.getElementById('btnZoomOut');
  const btnAutoLayout = document.getElementById('btnAutoLayout');

  const inspectorDrawer = document.getElementById('inspectorDrawer');
  const btnCloseInspector = document.getElementById('btnCloseInspector');
  const inspectorNodeId = document.getElementById('inspectorNodeId');
  const inspectorKindBadge = document.getElementById('inspectorKindBadge');
  const inspectorStatusPill = document.getElementById('inspectorStatusPill');
  const inspectorStatusReason = document.getElementById('inspectorStatusReason');
  const btnDispatchHost = document.getElementById('btnDispatchHost');
  const btnCopyPrompt = document.getElementById('btnCopyPrompt');
  const btnSaveNode = document.getElementById('btnSaveNode');
  const btnDeleteNode = document.getElementById('btnDeleteNode');

  const afterNodesContainer = document.getElementById('afterNodesContainer');
  const sectionAgentFields = document.getElementById('sectionAgentFields');
  const sectionCommandFields = document.getElementById('sectionCommandFields');
  const sectionHumanFields = document.getElementById('sectionHumanFields');

  const selectNodeModel = document.getElementById('selectNodeModel');
  const fieldModel = document.getElementById('fieldModel');
  const fieldRole = document.getElementById('fieldRole');
  const fieldPrompt = document.getElementById('fieldPrompt');
  const fieldSkills = document.getElementById('fieldSkills');
  const nodeSkillsTags = document.getElementById('nodeSkillsTags');
  const skillCountBadge = document.getElementById('skillCountBadge');
  const selectAvailableSkill = document.getElementById('selectAvailableSkill');
  const btnAddSystemSkill = document.getElementById('btnAddSystemSkill');
  const inputCustomSkill = document.getElementById('inputCustomSkill');
  const btnAddCustomSkill = document.getElementById('btnAddCustomSkill');
  const fieldRun = document.getElementById('fieldRun');
  const fieldAsk = document.getElementById('fieldAsk');
  const fieldInputs = document.getElementById('fieldInputs');
  const fieldOutputs = document.getElementById('fieldOutputs');
  const fieldAssertMinWords = document.getElementById('fieldAssertMinWords');
  const fieldAssertMaxWords = document.getElementById('fieldAssertMaxWords');
  const fieldAssertMinScore = document.getElementById('fieldAssertMinScore');
  const fieldAssertScoreField = document.getElementById('fieldAssertScoreField');

  const terminalDrawer = document.getElementById('terminalDrawer');
  const terminalLogs = document.getElementById('terminalLogs');
  const btnClearLog = document.getElementById('btnClearLog');
  const btnCloseTerminal = document.getElementById('btnCloseTerminal');

  // 模态框
  const createProjectModal = document.getElementById('createProjectModal');
  const btnCloseCreateProjectModal = document.getElementById('btnCloseCreateProjectModal');
  const btnConfirmCreateProject = document.getElementById('btnConfirmCreateProject');
  const newProjSlug = document.getElementById('newProjSlug');
  const newProjTitle = document.getElementById('newProjTitle');
  const newProjGenre = document.getElementById('newProjGenre');
  const newProjProtagonist = document.getElementById('newProjProtagonist');
  const newProjLogline = document.getElementById('newProjLogline');

  const addPathModal = document.getElementById('addPathModal');
  const btnCloseAddPathModal = document.getElementById('btnCloseAddPathModal');
  const btnConfirmAddPath = document.getElementById('btnConfirmAddPath');
  const customPathInput = document.getElementById('customPathInput');

  const addNodeModal = document.getElementById('addNodeModal');
  const btnCloseAddNodeModal = document.getElementById('btnCloseAddNodeModal');
  const btnConfirmAddNode = document.getElementById('btnConfirmAddNode');
  const newNodeId = document.getElementById('newNodeId');
  const newNodeKind = document.getElementById('newNodeKind');
  const newNodeRole = document.getElementById('newNodeRole');

  const readerModal = document.getElementById('readerModal');
  const btnCloseReaderModal = document.getElementById('btnCloseReaderModal');
  const readerFileList = document.getElementById('readerFileList');
  const readerFileName = document.getElementById('readerFileName');
  const readerTextarea = document.getElementById('readerTextarea');
  const readerWordCountBadge = document.getElementById('readerWordCountBadge');
  const btnSaveReaderContent = document.getElementById('btnSaveReaderContent');

  let currentReadingFile = '';
  let availableSkills = [];

  let boundContext = null;
  let uiSession = null;
  let uiReady = false;
  let graphRevision = null;
  let graphDirty = false;
  let inspectorDirty = false;
  let readerDirty = false;
  let editVersion = 0;
  let graphLoadVersion = 0;
  let pendingGraphRefresh = false;
  let graphRefreshTimer = null;
  let stateRefreshTimer = null;
  let graphRefreshInFlight = false;
  let stateRefreshInFlight = false;
  let stateRefreshAgain = false;
  let saveQueue = Promise.resolve();
  let pendingSaves = 0;
  let saveConflict = false;
  let persistedEditVersion = 0;
  let readerLoadVersion = 0;
  let explicitChapter = null;

  function projectRequestValue() {
    return boundContext ? boundContext.project_path : currentProject;
  }

  function contextQuery(targetChapter = explicitChapter) {
    const query = new URLSearchParams({ project: projectRequestValue(), workflow: currentWorkflow });
    // 绑定服务自己的 chapter 是唯一来源；旧入口只在用户明确切换时覆盖。
    if (!boundContext && targetChapter !== null) query.set('chapter', targetChapter);
    return query.toString();
  }

  async function requestJson(url, options = {}) {
    const response = await fetch(url, { cache: 'no-store', ...options });
    const data = await response.json();
    if (!response.ok) {
      const error = new Error(typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail || `HTTP ${response.status}`));
      error.status = response.status;
      throw error;
    }
    return data;
  }

  function showSyncNotice(message, error = false) {
    const notice = document.getElementById('studioSyncNotice');
    document.getElementById('studioSyncMessage').textContent = message;
    notice.classList.remove('hidden');
    notice.classList.toggle('has-error', error);
  }

  function reportSyncError(error) {
    appendLog(`[error] ${error.message}`);
    showSyncNotice(`同步失败：${error.message}。可点击重新载入重试；未保存内容仍保留。`, true);
  }

  function hasUnsavedChanges() {
    return graphDirty || inspectorDirty || readerDirty;
  }

  function graphRefreshBlocked() {
    return hasUnsavedChanges() || pendingSaves > 0 || draggingNodeId || connectingFromId || isPanning ||
      inspectorDrawer.contains(document.activeElement) ||
      Array.from(document.querySelectorAll('.modal-backdrop')).some(el => !el.classList.contains('hidden'));
  }

  function markInspectorDirty() {
    if (!selectedNodeId) return;
    inspectorDirty = true;
    editVersion++;
  }

  function confirmInspectorDiscard() {
    if (inspectorDirty && !confirm('当前节点属性尚未保存，确定丢弃这些输入吗？')) return false;
    inspectorDirty = false;
    return true;
  }

  function allowContextSwitch() {
    if (!uiReady || boundContext) return false;
    if (pendingSaves) { showSyncNotice('请等待配置保存完成后再切换。'); return false; }
    if (hasUnsavedChanges() && !confirm('切换目标会丢弃未保存的配置与文件编辑，确定继续吗？')) return false;
    graphDirty = inspectorDirty = readerDirty = false;
    pendingGraphRefresh = false;
    currentReadingFile = '';
    readerLoadVersion++;
    readerModal.classList.add('hidden');
    selectedNodeId = null;
    inspectorDrawer.classList.remove('open');
    currentGraph = null;
    graphRevision = null;
    nodesLayer.innerHTML = '';
    renderEdges();
    return true;
  }

  function deferGraphRefresh() {
    pendingGraphRefresh = true;
    showSyncNotice(saveConflict
      ? '保存冲突：磁盘图谱已变化，草稿仍保留。请先复制保留需要的内容，再点击重新载入并确认丢弃。'
      : '图谱同步待检查；拖拽或编辑期间暂缓载入。保存若有版本冲突会保留草稿，也可明确重新载入。', saveConflict);
  }

  function scheduleGraphRefresh() {
    pendingGraphRefresh = true;
    clearTimeout(graphRefreshTimer);
    graphRefreshTimer = setTimeout(flushGraphRefresh, 180);
  }

  async function flushGraphRefresh() {
    if (!uiReady || !pendingGraphRefresh || graphRefreshInFlight) return;
    if (graphRefreshBlocked()) {
      deferGraphRefresh();
      return;
    }
    pendingGraphRefresh = false;
    graphRefreshInFlight = true;
    try {
      await loadGraph(currentProject, null, true);
    } catch (error) {
      reportSyncError(error);
    } finally {
      graphRefreshInFlight = false;
      if (pendingGraphRefresh && !graphRefreshBlocked()) scheduleGraphRefresh();
    }
  }

  function scheduleStateRefresh() {
    clearTimeout(stateRefreshTimer);
    stateRefreshTimer = setTimeout(() => refreshState().catch(reportSyncError), 120);
  }

  async function refreshState() {
    if (!uiReady || !currentProject) return;
    if (stateRefreshInFlight) { stateRefreshAgain = true; return; }
    const query = contextQuery();
    const loadedVersion = graphLoadVersion;
    stateRefreshInFlight = true;
    try {
      const data = await requestJson(`/api/state?${query}`);
      if (query !== contextQuery() || loadedVersion !== graphLoadVersion) return;
      if (data.revision !== graphRevision) {
        scheduleGraphRefresh();
        return;
      }
      applyStateUpdate(data);
    } finally {
      stateRefreshInFlight = false;
      if (stateRefreshAgain) { stateRefreshAgain = false; scheduleStateRefresh(); }
    }
  }

  function eventMatchesContext(data) {
    if (data.workflow !== currentWorkflow) return false;
    if (boundContext) {
      return data.project === boundContext.bound_project && data.path === boundContext.project_path;
    }
    return data.project === currentProject || data.path === currentProject;
  }

  function formatModelShort(model) {
    if (!model) return '🤖 未指定模型';
    const m = model.toLowerCase();
    // Qoder 系统模型内部名 + BYOK slug 与显示名对照 (见 docs/qoder-model-routing.md)
    if (m === 'qfmodel' || m.includes('qwen')) return '⚡ Qwen 3.8 Flash';
    if (m === 'qmodel_38max') return '⚡ Qwen 3.8 Max';
    if (m === 'kmodel_latest' || m.includes('kimi')) return '🔍 Kimi K3';
    if (m === 'kmodel') return '🔍 Kimi K2.7 Code';
    if (m.includes('opus')) return '🧠 Claude Opus 4.6 (Thinking)';
    if (m.includes('sonnet')) return '🧠 Claude 3.7 Sonnet (Thinking)';
    if (m === 'gemini-3.8-flash-high') return '⚡ Gemini 3.8 Flash (High)';
    if (m === 'gemini-3.8-flash-medium') return '⚡ Gemini 3.8 Flash (Medium)';
    if (m === 'gemini-3.8-flash-low') return '⚡ Gemini 3.8 Flash (Low)';
    if (m.includes('gemini') || m.includes('flash')) return '⚡ Gemini 3.8 Flash';
    return `🤖 ${model.length > 25 ? model.substring(0, 23) + '..' : model}`;
  }

  function getModelClass(model) {
    if (!model) return 'model-default';
    const m = model.toLowerCase();
    if (m === 'qfmodel' || m === 'qmodel_38max' || m.includes('qwen')) return 'model-qwen';
    if (m === 'kmodel_latest' || m === 'kmodel' || m.includes('kimi')) return 'model-kimi';
    if (m.includes('opus') || m.includes('claude')) return 'model-claude';
    if (m.includes('gemini') || m.includes('flash')) return 'model-gemini';
    return 'model-custom';
  }

  // 宿主 Agent 感知：显示名与徽标更新
  function hostDisplayName() {
    if (detectedHost === 'qoder') return 'Qoder';
    if (detectedHost === 'antigravity') return 'Antigravity';
    return '宿主 Agent';
  }

  function updateHostBadge() {
    const badge = document.getElementById('hostBadge');
    const nameEl = document.getElementById('hostBadgeName');
    if (!badge || !nameEl) return;
    if (!detectedHost || detectedHost === 'unknown') {
      badge.classList.add('hidden');
      return;
    }
    badge.classList.remove('hidden');
    badge.className = `host-badge host-${detectedHost}`;
    badge.title = `当前由 ${hostDisplayName()} 驱动工作流，各节点模型档位已按该宿主的模型档案自动适配`;
    nameEl.textContent = hostDisplayName();
  }

  // 取节点的"实际执行模型"：状态文件中的宿主解析结果优先，图谱原始声明兜底
  function getResolvedModel(id, node) {
    const stateEntry = (currentState && currentState.nodes) ? currentState.nodes[id] : null;
    return (stateEntry && stateEntry.model) ? stateEntry.model : node.model;
  }

  function getStateEntry(id) {
    return (currentState && currentState.nodes) ? currentState.nodes[id] : null;
  }

  function nodeStatus(id) {
    const entry = getStateEntry(id);
    return entry && (entry.running || entry.status === 'running') ? 'running' : (entry?.status || 'stale');
  }

  function updateInspectorStatus() {
    if (!selectedNodeId) return;
    const entry = getStateEntry(selectedNodeId);
    const status = nodeStatus(selectedNodeId);
    inspectorStatusPill.textContent = status === 'running' ? '正在运行中...' : status;
    inspectorStatusPill.className = `status-pill status-${status}`;
    inspectorStatusReason.textContent = entry?.staleBecause || (status === 'running' ? '智能体任务正在执行中...' : '');
  }

  function applyStateUpdate(data) {
    if (!data.state || !data.state.nodes) throw new Error('节点状态响应格式错误');
    currentState = data.state;
    if (data.host !== undefined) { detectedHost = data.host || null; updateHostBadge(); }
    // 只修改状态元素；不 renderGraph，不 selectNode，也不重填任何输入。
    Object.keys(currentGraph?.nodes || {}).forEach(id => {
      const card = document.getElementById(`node-${id}`);
      if (!card) return;
      const status = nodeStatus(id);
      Array.from(card.classList).filter(name => name.startsWith('status-')).forEach(name => card.classList.remove(name));
      card.classList.add(`status-${status}`);
      const indicator = card.querySelector('.status-indicator');
      indicator.className = `status-indicator ${status}`;
      indicator.title = `节点状态: ${status}`;
      let badge = card.querySelector('.node-running-badge');
      if (status === 'running' && !badge) {
        badge = document.createElement('div');
        badge.className = 'node-running-badge';
        badge.innerHTML = '<span class="running-dot-pulse"></span><span>正在由智能体执行中...</span>';
        card.querySelector('.node-body').appendChild(badge);
      } else if (status !== 'running' && badge) badge.remove();
    });
    updateInspectorStatus();
    renderEdges();
  }

  // ==========================================
  // 0. 全局轻量通知反馈 (Toast)
  // ==========================================
  let toastTimer = null;
  function showToast(msg, type = 'success', duration = 2500) {
    const toast = document.getElementById('studioToast');
    const toastIcon = document.getElementById('toastIcon');
    const toastMsg = document.getElementById('toastMsg');
    if (!toast || !toastMsg) return;

    toast.className = `studio-toast toast-${type}`;
    if (toastIcon) {
      toastIcon.textContent = type === 'success' ? '✅' : (type === 'error' ? '❌' : 'ℹ️');
    }
    toastMsg.textContent = msg;
    toast.classList.remove('hidden');

    if (toastTimer) clearTimeout(toastTimer);
    toastTimer = setTimeout(() => {
      toast.classList.add('hidden');
    }, duration);
  }

  // ==========================================
  // 0. WebSocket 双向实时同步引擎
  // ==========================================
  let liveWs = null;
  let livePingTimer = null;
  let liveReconnectTimer = null;
  const liveStatusBadge = document.getElementById('liveStatusBadge');

  function updateLiveBadge(online, text = null) {
    if (!liveStatusBadge) return;
    const textEl = liveStatusBadge.querySelector('.live-text');
    if (online) {
      liveStatusBadge.className = 'live-status-badge live-online';
      liveStatusBadge.title = '实时双向同步已连接：底层文件变动与 Agent 执行状态将自动秒级刷新';
      if (textEl) textEl.textContent = text || '实时同步中';
    } else {
      liveStatusBadge.className = 'live-status-badge live-offline';
      liveStatusBadge.title = '实时通道已断开，正在尝试自动重连...点击可立即重试';
      if (textEl) textEl.textContent = text || '重连中...';
    }
  }

  function initLiveWebSocket() {
    if (liveWs && (liveWs.readyState === WebSocket.OPEN || liveWs.readyState === WebSocket.CONNECTING)) {
      return;
    }
    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${location.host}/ws/live`;

    try {
      liveWs = new WebSocket(wsUrl);

      liveWs.onopen = () => {
        updateLiveBadge(true, '实时同步中');
        scheduleStateRefresh(); // 补齐初次连接或断线期间漏掉的通知。
        if (liveReconnectTimer) {
          clearTimeout(liveReconnectTimer);
          liveReconnectTimer = null;
        }
        // 心跳保活 (每 15 秒 ping 一次)
        if (livePingTimer) clearInterval(livePingTimer);
        livePingTimer = setInterval(() => {
          if (liveWs && liveWs.readyState === WebSocket.OPEN) {
            liveWs.send('ping');
          }
        }, 15000);
      };

      liveWs.onmessage = (evt) => {
        try {
          const data = JSON.parse(evt.data);
          if (!eventMatchesContext(data)) return;
          if (data.type === 'graph-changed') {
            scheduleGraphRefresh();
          } else if (data.type === 'status-changed') {
            scheduleStateRefresh();
          }
        } catch (e) {
          // 忽略非 json 或 pong
        }
      };

      liveWs.onclose = () => {
        updateLiveBadge(false, '连接已断开');
        if (livePingTimer) clearInterval(livePingTimer);
        // 自动重连 (2.5 秒后)
        if (!liveReconnectTimer) {
          liveReconnectTimer = setTimeout(() => {
            liveReconnectTimer = null;
            initLiveWebSocket();
          }, 2500);
        }
      };

      liveWs.onerror = () => {
        updateLiveBadge(false, '重连中...');
        try { liveWs.close(); } catch (e) {}
      };
    } catch (err) {
      updateLiveBadge(false, '通道异常');
      if (!liveReconnectTimer) {
        liveReconnectTimer = setTimeout(() => {
          liveReconnectTimer = null;
          initLiveWebSocket();
        }, 3000);
      }
    }
  }

  // ==========================================
  // 1. 初始化与项目加载
  // ==========================================
  async function init() {
    try {
      setupEventListeners();
      const health = await requestJson('/api/health');
      if (!Object.prototype.hasOwnProperty.call(health, 'bound_project')) {
        throw new Error('服务未返回工作台绑定信息，请升级或重启服务');
      }
      if (health.bound_project !== null) {
        if (health.studio_protocol !== 1 || !health.project_path || !health.workflow || !health.bound_project) {
          throw new Error('绑定服务身份或协议不完整');
        }
        boundContext = health;
        currentProject = health.bound_project;
        currentWorkflow = health.workflow;
        currentChapter = health.chapter;
        document.body.classList.add('studio-bound');
        document.getElementById('boundStudioNotice').classList.remove('hidden');
        document.getElementById('boundModelNote').classList.remove('hidden');
        document.getElementById('boundStudioContext').textContent = `${health.bound_project} · ${health.workflow} · 章节 ${health.chapter} · ${health.project_path}`;
        [projectSelect, workflowSelect, chapterInput, btnPrevChapter, btnNextChapter,
          btnOpenNewProjectModal, btnOpenAddPathModal, btnDispatchHost, btnCopyPrompt,
          btnReconcile, selectNodeModel, fieldModel].forEach(el => { el.disabled = true; });
        const launchParams = new URLSearchParams(location.search);
        const launchId = launchParams.get('launch_id');
        if (launchParams.has('launch_id') && !launchId) throw new Error('工作台会话标识为空');
        uiSession = launchId
          ? await requestJson(`/api/ui/session/${encodeURIComponent(launchId)}`)
          : await requestJson('/api/ui/session', { method: 'POST' });
        if (!uiSession.launch_id || (launchId && uiSession.launch_id !== launchId) ||
            uiSession.project !== currentProject || uiSession.project_path !== health.project_path ||
            uiSession.workflow !== currentWorkflow || uiSession.chapter !== health.chapter ||
            !['pending', 'ready'].includes(uiSession.status)) {
          throw new Error('本次工作台会话与服务上下文不匹配，请从主对话重新打开');
        }
      } else if (new URLSearchParams(location.search).has('launch_id')) {
        throw new Error('就绪会话需要单项目绑定服务，当前入口未绑定');
      }
      await fetchAvailableSkills();
      if (boundContext) await loadGraph(currentProject);
      else await loadProjects();
      await waitForGraphPaint();
      if (boundContext) {
        const ready = await requestJson('/api/ui/ready', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ launch_id: uiSession.launch_id, revision: graphRevision })
        });
        if (ready.status !== 'ready') throw new Error('服务尚未确认本次渲染就绪');
      }
      uiReady = true;
      const layout = document.querySelector('.studio-layout');
      layout.inert = false;
      layout.removeAttribute('inert');
      layout.setAttribute('aria-busy', 'false');
      document.body.classList.remove('studio-loading');
      document.getElementById('studioLoadingOverlay').classList.add('hidden');
      initLiveWebSocket();
    } catch (error) {
      const overlay = document.getElementById('studioLoadingOverlay');
      overlay.classList.add('has-error');
      document.getElementById('studioLoadingTitle').textContent = '工作台尚未就绪';
      document.getElementById('studioLoadingMessage').textContent = `${error.message}。请刷新重试；会话失效时请从主对话重新打开。`;
      appendLog(`[error] 初始化失败：${error.message}`);
    }
  }

  async function waitForGraphPaint() {
    await new Promise(resolve => {
      // 后台标签页浏览器会暂停 rAF；退化为短宏任务，否则就绪回执永不发出。
      const fallback = setTimeout(() => { clearTimeout(fallback); resolve(); }, 120);
      requestAnimationFrame(() => requestAnimationFrame(() => { clearTimeout(fallback); resolve(); }));
    });
    if (!currentGraph) {
      if (boundContext) throw new Error('没有可绘制的工作流');
      return; // 旧入口允许空项目列表。
    }
    const ids = Object.keys(currentGraph.nodes);
    const expectedEdges = ids.reduce((count, id) => count + (currentGraph.nodes[id].after || []).length, 0);
    const cards = nodesLayer.querySelectorAll('.node-card');
    const paths = edgesGroup.querySelectorAll('.edge-path');
    if (cards.length !== ids.length || paths.length !== expectedEdges ||
        Array.from(cards).some(card => !card.offsetWidth || !card.offsetHeight) ||
        Array.from(paths).some(path => !path.getAttribute('d') || /NaN|Infinity/.test(path.getAttribute('d')))) {
      throw new Error('节点或连线未完成绘制');
    }
  }

  async function fetchAvailableSkills() {
    const data = await requestJson('/api/skills');
    if (!Array.isArray(data.skills)) throw new Error('技能库响应格式错误');
    availableSkills = data.skills;
    populateAvailableSkillsDropdown();
  }

  function populateAvailableSkillsDropdown() {
    if (!selectAvailableSkill) return;
    selectAvailableSkill.innerHTML = '<option value="">-- 选择系统技能库预设 --</option>';

    const categories = {};
    availableSkills.forEach(s => {
      const cat = s.category || '通用技能';
      if (!categories[cat]) categories[cat] = [];
      categories[cat].push(s);
    });

    Object.keys(categories).forEach(cat => {
      const group = document.createElement('optgroup');
      group.label = `【${cat}】`;
      categories[cat].forEach(s => {
        const opt = document.createElement('option');
        opt.value = s.id;
        opt.textContent = `${s.id} - ${s.name}`;
        opt.title = s.description;
        group.appendChild(opt);
      });
      selectAvailableSkill.appendChild(group);
    });
  }

  function renderNodeSkills(skills) {
    if (!nodeSkillsTags) return;
    nodeSkillsTags.innerHTML = '';
    const skillList = Array.isArray(skills) ? skills : [];

    if (skillCountBadge) {
      skillCountBadge.textContent = `${skillList.length} 个`;
    }

    if (skillList.length === 0) {
      nodeSkillsTags.innerHTML = '<span class="skills-empty-hint">暂未绑定任何专业技能</span>';
      return;
    }

    skillList.forEach(sid => {
      const badge = document.createElement('span');
      badge.className = 'skill-tag-badge';
      const meta = availableSkills.find(s => s.id === sid);
      const desc = meta ? meta.description : '自定义小说技能';
      const cat = meta ? meta.category : '';
      badge.title = desc;

      badge.innerHTML = `
        <span class="skill-tag-name">${escapeHtml(sid)}</span>
        ${cat ? `<span class="skill-tag-cat">${escapeHtml(cat)}</span>` : ''}
        <span class="skill-tag-del" title="移除该技能">&times;</span>
      `;

      badge.querySelector('.skill-tag-del').addEventListener('click', (e) => {
        e.stopPropagation();
        removeSkillFromCurrentNode(sid);
      });

      nodeSkillsTags.appendChild(badge);
    });
  }

  function addSkillToCurrentNode(skillId) {
    if (!selectedNodeId || !currentGraph || !currentGraph.nodes || !currentGraph.nodes[selectedNodeId]) return;
    const node = currentGraph.nodes[selectedNodeId];
    if (!node.skills) node.skills = [];
    if (!node.skills.includes(skillId)) {
      node.skills.push(skillId);
      if (fieldSkills) fieldSkills.value = node.skills.join(', ');
      renderNodeSkills(node.skills);
      saveGraphToServer();
      appendLog(`[studio] 🎯 节点 [${selectedNodeId}] 绑定技能: ${skillId}`);
    }
  }

  function removeSkillFromCurrentNode(skillId) {
    if (!selectedNodeId || !currentGraph || !currentGraph.nodes || !currentGraph.nodes[selectedNodeId]) return;
    const node = currentGraph.nodes[selectedNodeId];
    if (!node.skills) return;
    node.skills = node.skills.filter(s => s !== skillId);
    if (fieldSkills) fieldSkills.value = node.skills.join(', ');
    renderNodeSkills(node.skills);
    saveGraphToServer();
    appendLog(`[studio] 🗑️ 节点 [${selectedNodeId}] 移除技能: ${skillId}`);
  }

  async function loadWorkflows(projectSlug) {
    if (!workflowSelect || !projectSlug) return;
    try {
      const data = await requestJson(`/api/workflows?project=${encodeURIComponent(projectSlug)}`);
      if (data.workflows && data.workflows.length > 0) {
        workflowSelect.innerHTML = '';
        data.workflows.forEach(wf => {
          const opt = document.createElement('option');
          opt.value = wf.id;
          opt.textContent = `${wf.icon || '⚙️'} ${wf.name}`;
          opt.title = wf.desc || '';
          workflowSelect.appendChild(opt);
        });

        const savedWf = localStorage.getItem(`studio_wf_${projectSlug}`);
        if (savedWf && data.workflows.some(w => w.id === savedWf)) {
          currentWorkflow = savedWf;
        } else if (!data.workflows.some(w => w.id === currentWorkflow)) {
          currentWorkflow = data.workflows[0].id;
        }
        workflowSelect.value = currentWorkflow;
      }
    } catch (e) {
      throw new Error(`工作流列表加载失败：${e.message}`);
    }
    updateChapterSelectorUI();
  }

  function updateChapterSelectorUI() {
    const isVolume = currentWorkflow.includes('volume');
    if (chapterSelectorLabel) {
      chapterSelectorLabel.textContent = isVolume ? '目标卷号：' : '目标章节：';
    }
    if (chapterUnitPrefix) {
      chapterUnitPrefix.textContent = '第';
    }
    if (chapterUnitSuffix) {
      chapterUnitSuffix.textContent = isVolume ? '卷' : '章';
    }
  }

  async function loadProjects() {
    if (boundContext) return;
    try {
      const data = await requestJson('/api/projects');
      projectSelect.innerHTML = '';

      if (!data.projects || data.projects.length === 0) {
        projectSelect.innerHTML = '<option value="">(暂无项目，请新建)</option>';
        return;
      }

      data.projects.forEach(p => {
        const opt = document.createElement('option');
        opt.value = p.slug;
        opt.textContent = `${p.name} (${p.slug})`;
        projectSelect.appendChild(opt);
      });

      const savedProject = localStorage.getItem('studio_selected_project');
      if (savedProject && data.projects.some(p => p.slug === savedProject)) {
        currentProject = savedProject;
      } else if (!currentProject || !data.projects.some(p => p.slug === currentProject)) {
        currentProject = data.projects[0].slug;
      }
      projectSelect.value = currentProject;
      await loadWorkflows(currentProject);
      await loadGraph(currentProject);
    } catch (err) {
      throw new Error(`加载课题列表失败：${err.message}`);
    }
  }

  async function loadGraph(projectSlug, targetChapter = null, silent = false, force = false) {
    if (!projectSlug) return false;
    if (boundContext && (projectSlug !== boundContext.bound_project || targetChapter !== null)) return false;
    if (silent && graphRefreshBlocked()) { deferGraphRefresh(); return false; }
    const loadVersion = ++graphLoadVersion;
    const editAtStart = editVersion;
    const requestedChapter = targetChapter === null ? explicitChapter : parseInt(targetChapter, 10);
    const query = contextQuery(requestedChapter);
    const data = await requestJson(`/api/graph?${query}`);
    if (loadVersion !== graphLoadVersion || projectSlug !== currentProject) return false;
    // 请求期间开始输入或拖拽，同样不能用迟到的响应覆盖编辑。
    if (uiReady && (editAtStart !== editVersion || pendingSaves || (silent && graphRefreshBlocked()))) {
      deferGraphRefresh();
      return false;
    }
    if (!data.hasGraph || !data.graph) {
      if (boundContext) throw new Error(`工作流 ${currentWorkflow} 不存在或不可读取`);
      data.graph = { version: 1, name: projectSlug, nodes: {} };
    }
    if (!data.graph.nodes || typeof data.graph.nodes !== 'object' || Array.isArray(data.graph.nodes)) {
      throw new Error('工作流节点结构无效');
    }
    if (boundContext && (!data.revision || !data.state)) throw new Error('工作流版本或状态缺失');
    if (silent && !force && data.revision === graphRevision && currentGraph) {
      applyStateUpdate(data);
      if (!pendingGraphRefresh) document.getElementById('studioSyncNotice').classList.add('hidden');
      return true;
    }
    currentGraph = data.graph;
    graphRevision = data.revision || null;
    explicitChapter = requestedChapter;
    currentState = data.state || null;
    if (data.host !== undefined) { detectedHost = data.host || null; updateHostBadge(); }
    const isVolume = currentWorkflow.includes('volume');
    currentChapter = boundContext ? boundContext.chapter :
      (isVolume ? data.currentVolume : data.currentChapter) ?? requestedChapter ?? currentChapter;
    chapterInput.value = currentChapter;
    updateChapterSelectorUI();
    graphDirty = false;
    inspectorDirty = false;
    saveConflict = false;
    const posKey = `${projectRequestValue()}::${currentWorkflow}`;
    nodePositions = workflowPositions[posKey] || (workflowPositions[posKey] = {});
    if (Object.keys(currentGraph.nodes).some(id => !nodePositions[id])) autoComputeLayout();
    renderGraph();
    if (selectedNodeId && currentGraph.nodes[selectedNodeId]) selectNode(selectedNodeId, true);
    else { selectedNodeId = null; inspectorDrawer.classList.remove('open'); }
    if (!pendingGraphRefresh) document.getElementById('studioSyncNotice').classList.add('hidden');
    return true;
  }

  async function refreshGraphExplicitly() {
    if (pendingSaves) { showSyncNotice('正在保存配置，请等待保存结束后再刷新。'); return; }
    if (hasUnsavedChanges() && !confirm('重新载入将丢弃未保存的节点配置和文件编辑。确定从磁盘重新载入吗？')) return;
    const original = btnRefreshStatus.innerHTML;
    btnRefreshStatus.disabled = true;
    btnRefreshStatus.textContent = '正在刷新...';
    try {
      pendingGraphRefresh = false;
      if (await loadGraph(currentProject, null, false, true)) {
        if (readerDirty) {
          readerDirty = false;
          currentReadingFile = '';
          readerLoadVersion++;
          readerModal.classList.add('hidden');
        }
        showToast('已从磁盘重新载入配置与状态', 'info');
      }
    } catch (error) { reportSyncError(error); }
    finally { btnRefreshStatus.innerHTML = original; btnRefreshStatus.disabled = false; }
  }

  // ==========================================
  // 2. 自动拓扑布局算法
  // ==========================================
  function autoComputeLayout() {
    if (!currentGraph || !currentGraph.nodes) return;
    const nodes = currentGraph.nodes;
    const nodeIds = Object.keys(nodes);

    // 计算入度与层级
    const levels = {};
    nodeIds.forEach(id => { levels[id] = 0; });

    // 简单松弛计算层级
    for (let i = 0; i < nodeIds.length; i++) {
      nodeIds.forEach(id => {
        const after = nodes[id].after || [];
        after.forEach(dep => {
          if (levels[dep] !== undefined) {
            levels[id] = Math.max(levels[id], levels[dep] + 1);
          }
        });
      });
    }

    // 按层级分组
    const columns = {};
    nodeIds.forEach(id => {
      const lvl = levels[id];
      if (!columns[lvl]) columns[lvl] = [];
      columns[lvl].push(id);
    });

    const colWidth = 320;
    const rowHeight = 150;
    const startX = 60;
    const startY = 80;

    Object.keys(columns).forEach(lvlStr => {
      const lvl = parseInt(lvlStr, 10);
      const colNodes = columns[lvl];
      colNodes.forEach((id, rowIdx) => {
        nodePositions[id] = {
          x: startX + lvl * colWidth,
          y: startY + rowIdx * rowHeight
        };
      });
    });
  }

  // ==========================================
  // 3. 画布渲染（节点与贝塞尔连线）
  // ==========================================
  function renderGraph() {
    if (!currentGraph || !currentGraph.nodes) return;
    nodesLayer.innerHTML = '';
    const nodes = currentGraph.nodes;

    Object.keys(nodes).forEach(id => {
      const node = nodes[id];
      const pos = nodePositions[id] || { x: 100, y: 100 };
      const stateEntry = (currentState && currentState.nodes) ? currentState.nodes[id] : null;
      const rawStatus = stateEntry ? stateEntry.status : 'stale';
      const isRunning = (rawStatus === 'running') || (stateEntry && stateEntry.running);
      const status = isRunning ? 'running' : rawStatus;

      const card = document.createElement('div');
      card.className = `node-card status-${status} ${selectedNodeId === id ? 'selected' : ''}`;
      card.id = `node-${id}`;
      card.style.transform = `translate(${pos.x}px, ${pos.y}px)`;

      const roleText = node.role || (node.kind === 'command' ? '命令行工具' : '人工检查点');
      const promptBrief = node.prompt || node.ask || (node.run ? node.run.join(' ') : '无指令说明');
      const resolvedModel = getResolvedModel(id, node);
      const stateEntryForModel = getStateEntry(id);
      const modelSwapped = node.kind === 'agent' && node.model && resolvedModel && node.model !== resolvedModel;
      const originNote = (stateEntryForModel && stateEntryForModel.model_note) ? stateEntryForModel.model_note : '';
      const modelBadgeHtml = (node.kind === 'agent' && resolvedModel)
        ? `<div class="node-model-row"><span class="node-model-chip ${getModelClass(resolvedModel)}" title="执行模型: ${escapeHtml(resolvedModel)}">${formatModelShort(resolvedModel)}</span>${modelSwapped ? `<span class="node-model-swap" title="${escapeHtml(originNote || `图谱声明的 ${node.model} 已按当前宿主（${hostDisplayName()}）模型档案自动适配为 ${resolvedModel}`)}">已自动适配</span>` : ''}</div>`
        : '';
      const runningBadgeHtml = isRunning
        ? `<div class="node-running-badge"><span class="running-dot-pulse"></span><span>正在由智能体执行中...</span></div>`
        : '';

      card.innerHTML = `
        <div class="node-header">
          <div class="node-title-group">
            <span class="status-indicator ${status}" title="节点状态: ${status}"></span>
            <span class="node-title" title="${id}">${id}</span>
          </div>
          <span class="kind-badge kind-badge-${node.kind}">${node.kind}</span>
        </div>
        <div class="node-body">
          <div class="node-role">${escapeHtml(roleText)}</div>
          ${modelBadgeHtml}
          ${runningBadgeHtml}
          <div class="node-brief">${escapeHtml(promptBrief)}</div>
        </div>
        <div class="node-ports">
          <div class="port port-in" data-port-in="${id}" title="输入依赖锚点（可接收连线）"></div>
          <div class="port port-out" data-port-out="${id}" title="输出供应锚点（按住拖拽或点击连线）"></div>
        </div>
      `;

      // 拖拽与点击事件
      card.addEventListener('mousedown', (e) => {
        if (e.target.classList.contains('port')) return;
        if (connectingFromId) return;
        if (!selectNode(id)) return;
        draggingNodeId = id;
        const rect = canvasViewport.getBoundingClientRect();
        const currentPos = nodePositions[id] || pos;
        dragOffsetX = (e.clientX - rect.left - panX) / zoom - currentPos.x;
        dragOffsetY = (e.clientY - rect.top - panY) / zoom - currentPos.y;
        e.stopPropagation();
      });

      // 右侧输出端口事件：支持按住拖拽连线与点击连线双模
      const portOut = card.querySelector('.port-out');
      portOut.addEventListener('mousedown', (e) => {
        e.stopPropagation();
        if (connectingFromId === id) {
          cancelConnect();
          return;
        }
        startConnectFrom(id);
        connectStartMousePos = { x: e.clientX, y: e.clientY };
        isDragConnecting = false;
      });

      // 左侧输入端口事件：点击完成连线或提供引导
      const portIn = card.querySelector('.port-in');
      portIn.addEventListener('click', (e) => {
        e.stopPropagation();
        if (connectingFromId && connectingFromId !== id) {
          completeConnectTo(id);
        } else if (!connectingFromId) {
          appendLog(`[studio] 💡 提示：连线方向为 [上游输出 (蓝色)] ➔ [下游输入 (绿色)]。请先点击上游节点的右侧蓝色端口。`);
          selectNode(id);
        }
      });

      // 连线激活状态下，点击目标卡片主体也能完成连接
      card.addEventListener('click', (e) => {
        if (connectingFromId && connectingFromId !== id) {
          e.stopPropagation();
          completeConnectTo(id);
        }
      });

      nodesLayer.appendChild(card);
    });

    renderEdges();
    applyCanvasTransform();
  }

  function getNodeCenterPort(nodeId, isOut) {
    const pos = nodePositions[nodeId] || { x: 100, y: 100 };
    const card = document.getElementById(`node-${nodeId}`);
    const h = (card && card.offsetHeight) ? card.offsetHeight : 120;
    return {
      x: isOut ? pos.x + 250 : pos.x,
      y: pos.y + h / 2
    };
  }

  function renderEdges() {
    // 仅清空已生成的连线元素，保留 tempEdge
    edgesGroup.querySelectorAll('.edge-item').forEach(el => el.remove());
    if (!currentGraph || !currentGraph.nodes) return;
    const nodes = currentGraph.nodes;

    Object.keys(nodes).forEach(targetId => {
      const after = nodes[targetId].after || [];
      after.forEach(sourceId => {
        if (!nodes[sourceId]) return;
        const sourcePt = getNodeCenterPort(sourceId, true);
        const targetPt = getNodeCenterPort(targetId, false);

        const x1 = sourcePt.x;
        const y1 = sourcePt.y;
        const x2 = targetPt.x;
        const y2 = targetPt.y;

        const dx = Math.max(40, Math.abs(x2 - x1) * 0.5);
        const d = `M ${x1} ${y1} C ${x1 + dx} ${y1}, ${x2 - dx} ${y2}, ${x2} ${y2}`;

        const g = document.createElementNS('http://www.w3.org/2000/svg', 'g');
        g.setAttribute('class', 'edge-item');

        const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
        path.setAttribute('d', d);
        path.setAttribute('class', 'edge-path');

        const stateTarget = (currentState && currentState.nodes) ? currentState.nodes[targetId] : null;
        if (nodeStatus(targetId) === 'running') {
          path.classList.add('edge-active');
          path.setAttribute('marker-end', 'url(#arrow-active)');
        } else if (stateTarget && stateTarget.status === 'current') {
          path.classList.add('edge-current');
          path.setAttribute('marker-end', 'url(#arrow-current)');
        } else if (stateTarget && stateTarget.status === 'stale') {
          path.classList.add('edge-stale');
          path.setAttribute('marker-end', 'url(#arrow-stale)');
        } else {
          path.setAttribute('marker-end', 'url(#arrow-default)');
        }

        // 中点删除按钮（剪线）
        const midX = (x1 + x2) / 2;
        const midY = (y1 + y2) / 2;
        const delBtn = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
        delBtn.setAttribute('cx', midX);
        delBtn.setAttribute('cy', midY);
        delBtn.setAttribute('r', 7);
        delBtn.setAttribute('class', 'edge-delete-btn');
        delBtn.setAttribute('title', `剪断依赖: ${sourceId} ➔ ${targetId}`);

        delBtn.addEventListener('click', (e) => {
          e.stopPropagation();
          disconnectNodes(sourceId, targetId);
        });

        g.appendChild(path);
        g.appendChild(delBtn);
        edgesGroup.appendChild(g);
      });
    });
  }

  function applyCanvasTransform() {
    nodesLayer.style.transform = `translate(${panX}px, ${panY}px) scale(${zoom})`;
    nodesLayer.style.transformOrigin = '0 0';
    edgesGroup.style.transform = `translate(${panX}px, ${panY}px) scale(${zoom})`;
    edgesGroup.style.transformOrigin = '0 0';
  }

  // ==========================================
  // 4. 连线与剪线逻辑
  // ==========================================
  function startConnectFrom(nodeId) {
    connectingFromId = nodeId;
    isDragConnecting = false;
    tempEdgeStartPos = getNodeCenterPort(nodeId, true);
    document.body.classList.add('is-connecting');
    connectTipBar.classList.remove('hidden');
    appendLog(`[studio] 🔗 连线起点已锁定: [${nodeId}]。可按住拖拽至目标节点释放，或移动鼠标点击目标节点（按 ESC 或点击空白处取消）。`);
  }

  function updateTempEdge(targetX, targetY) {
    if (!connectingFromId) return;
    const x1 = tempEdgeStartPos.x;
    const y1 = tempEdgeStartPos.y;
    const x2 = targetX;
    const y2 = targetY;
    const dx = Math.max(40, Math.abs(x2 - x1) * 0.5);
    const d = `M ${x1} ${y1} C ${x1 + dx} ${y1}, ${x2 - dx} ${y2}, ${x2} ${y2}`;
    tempEdge.setAttribute('d', d);
  }

  function isReachable(fromId, toId, visited = new Set()) {
    if (fromId === toId) return true;
    if (visited.has(fromId)) return false;
    visited.add(fromId);
    const after = (currentGraph && currentGraph.nodes && currentGraph.nodes[fromId]?.after) || [];
    for (const dep of after) {
      if (isReachable(dep, toId, visited)) return true;
    }
    return false;
  }

  function completeConnectTo(targetId) {
    if (!connectingFromId || connectingFromId === targetId) {
      cancelConnect();
      return;
    }
    const targetNode = currentGraph.nodes[targetId];
    if (!targetNode) {
      cancelConnect();
      return;
    }

    // 环依赖检查：如果 targetId 已经在 connectingFromId 的上游链条中，则建立依赖会导致死锁
    if (isReachable(connectingFromId, targetId)) {
      alert(`⚠️ 无法建立依赖: [${connectingFromId}] ➔ [${targetId}] 会导致循环依赖 (Cycle)！\n因为 [${connectingFromId}] 已经是 [${targetId}] 的下游节点。`);
      cancelConnect();
      return;
    }

    if (!targetNode.after) targetNode.after = [];
    if (!targetNode.after.includes(connectingFromId)) {
      targetNode.after.push(connectingFromId);
      appendLog(`[studio] 🔗 成功建立依赖: [${connectingFromId}] ➔ [${targetId}]`);
      saveGraphToServer();
    } else {
      appendLog(`[studio] ℹ️ 依赖 [${connectingFromId}] ➔ [${targetId}] 已存在。`);
    }

    cancelConnect();
    renderEdges();
    if (selectedNodeId === targetId) renderAfterCheckboxes(targetId, targetNode.after);
  }

  function cancelConnect() {
    connectingFromId = null;
    isDragConnecting = false;
    connectStartMousePos = null;
    document.body.classList.remove('is-connecting');
    connectTipBar.classList.add('hidden');
    tempEdge.setAttribute('d', '');
    document.querySelectorAll('.node-card').forEach(c => c.classList.remove('connect-target-candidate'));
    if (pendingGraphRefresh) scheduleGraphRefresh();
  }

  function disconnectNodes(sourceId, targetId) {
    const targetNode = currentGraph.nodes[targetId];
    if (!targetNode || !targetNode.after) return;
    targetNode.after = targetNode.after.filter(x => x !== sourceId);
    appendLog(`[studio] ✂️ 已剪断依赖: [${sourceId}] ➔ [${targetId}]`);
    renderEdges();
    if (selectedNodeId === targetId) renderAfterCheckboxes(targetId, targetNode.after);
    saveGraphToServer();
  }

  // ==========================================
  // 5. 属性检查器 Inspector
  // ==========================================
  function selectNode(id, refill = false) {
    if (!refill && selectedNodeId === id) return true;
    if (!refill && !confirmInspectorDiscard()) return false;
    selectedNodeId = id;
    document.querySelectorAll('.node-card').forEach(c => c.classList.remove('selected'));
    const el = document.getElementById(`node-${id}`);
    if (el) el.classList.add('selected');

    const node = currentGraph.nodes[id];
    if (!node) return;

    inspectorNodeId.textContent = id;
    inspectorKindBadge.textContent = node.kind;
    inspectorKindBadge.className = `kind-badge kind-badge-${node.kind}`;

    const stateEntry = (currentState && currentState.nodes) ? currentState.nodes[id] : null;
    const rawStatus = stateEntry ? stateEntry.status : 'stale';
    const isRunning = (rawStatus === 'running') || (stateEntry && stateEntry.running);
    const status = isRunning ? 'running' : rawStatus;
    inspectorStatusPill.textContent = isRunning ? '⚡ 正在运行中...' : status;
    inspectorStatusPill.className = `status-pill status-${status}`;
    inspectorStatusReason.textContent = (stateEntry && stateEntry.staleBecause) ? stateEntry.staleBecause : (isRunning ? '智能体任务正在活跃生产中...' : '');

    // 依赖多选渲染
    renderAfterCheckboxes(id, node.after || []);

    // 区分展示专有字段
    sectionAgentFields.classList.toggle('hidden', node.kind !== 'agent');
    sectionCommandFields.classList.toggle('hidden', node.kind !== 'command');
    sectionHumanFields.classList.toggle('hidden', node.kind !== 'human');

    if (node.kind === 'agent') {
      const stateEntry = getStateEntry(id);
      const resolvedModel = (stateEntry && stateEntry.model) ? stateEntry.model : null;
      const currentModel = node.model || '';
      const knownModels = Array.from(selectNodeModel.options, option => option.value);
      if (selectNodeModel) {
        if (currentModel && knownModels.includes(currentModel)) {
          selectNodeModel.value = currentModel;
          if (fieldModel) {
            fieldModel.value = currentModel;
            fieldModel.classList.add('hidden');
          }
        } else {
          selectNodeModel.value = 'custom';
          if (fieldModel) {
            fieldModel.value = currentModel;
            fieldModel.classList.remove('hidden');
          }
        }
      }
      // 宿主适配提示行：展示状态文件解析出的实际执行模型（只读，不写回图谱）
      const adaptEl = document.getElementById('inspectorModelAdapt');
      if (adaptEl) {
        if (resolvedModel) {
          const swapped = currentModel && resolvedModel !== currentModel;
          const note = (stateEntry && stateEntry.model_note) ? stateEntry.model_note : '';
          adaptEl.innerHTML =
            `<span class="node-model-chip ${getModelClass(resolvedModel)}">${formatModelShort(resolvedModel)}</span>` +
            (swapped ? `<span class="node-model-swap">宿主已自动适配</span>` : '') +
            (note ? `<span class="model-adapt-note">${escapeHtml(note)}</span>` : '');
          adaptEl.classList.remove('hidden');
        } else {
          adaptEl.classList.add('hidden');
          adaptEl.innerHTML = '';
        }
      }
      fieldRole.value = node.role || '';
      fieldPrompt.value = node.prompt || '';
      fieldSkills.value = (node.skills || []).join(', ');
      renderNodeSkills(node.skills || []);
      btnDispatchHost.textContent = `🚀 在 ${hostDisplayName()} 中执行`;
    } else if (node.kind === 'command') {
      fieldRun.value = (node.run || []).join(' ');
      btnDispatchHost.textContent = '▶ 执行命令行脚本';
    } else if (node.kind === 'human') {
      fieldAsk.value = node.ask || '';
      btnDispatchHost.textContent = '✓ 创作者确认审批放行';
    }

    fieldInputs.value = (node.inputs || []).join(', ');
    fieldOutputs.value = (node.outputs || []).join(', ');

    const asserts = node.assert || {};
    fieldAssertMinWords.value = asserts.min_words || '';
    fieldAssertMaxWords.value = asserts.max_words || '';
    fieldAssertMinScore.value = asserts.min_score || '';
    fieldAssertScoreField.value = asserts.score_field || 'overall';

    inspectorDrawer.classList.add('open');
    return true;
  }

  function renderAfterCheckboxes(currentNodeId, currentAfter) {
    afterNodesContainer.innerHTML = '';
    const otherNodes = Object.keys(currentGraph.nodes || {}).filter(nid => nid !== currentNodeId);
    if (otherNodes.length === 0) {
      afterNodesContainer.innerHTML = '<span style="color:#64748b;font-size:11px;">无可选前置节点</span>';
      return;
    }

    otherNodes.forEach(nid => {
      const label = document.createElement('label');
      label.className = 'dep-checkbox-item';
      const checked = currentAfter.includes(nid) ? 'checked' : '';
      label.innerHTML = `<input type="checkbox" value="${nid}" ${checked}> <span>${nid}</span>`;
      label.querySelector('input').addEventListener('change', (e) => {
        const node = currentGraph.nodes[currentNodeId];
        if (!node.after) node.after = [];
        if (e.target.checked) {
          if (!node.after.includes(nid)) node.after.push(nid);
        } else {
          node.after = node.after.filter(x => x !== nid);
        }
        renderEdges();
        saveGraphToServer();
      });
      afterNodesContainer.appendChild(label);
    });
  }

  function saveCurrentNodeFromInspector(triggerBtn = null) {
    if (!selectedNodeId || !currentGraph.nodes[selectedNodeId]) return;
    const node = currentGraph.nodes[selectedNodeId];

    node.inputs = fieldInputs.value.split(',').map(s => s.trim()).filter(Boolean);
    node.outputs = fieldOutputs.value.split(',').map(s => s.trim()).filter(Boolean);

    if (node.kind === 'agent') {
      node.role = fieldRole.value.trim();
      node.prompt = fieldPrompt.value;
      node.skills = fieldSkills.value.split(',').map(s => s.trim()).filter(Boolean);
      if (selectNodeModel && !boundContext) {
        node.model = (selectNodeModel.value === 'custom' && fieldModel)
          ? fieldModel.value.trim()
          : selectNodeModel.value;
      }
    } else if (node.kind === 'command') {
      node.run = fieldRun.value.split(' ').map(s => s.trim()).filter(Boolean);
    } else if (node.kind === 'human') {
      node.ask = fieldAsk.value;
    }

    const asserts = {};
    if (fieldAssertMinWords.value) asserts.min_words = parseInt(fieldAssertMinWords.value, 10);
    if (fieldAssertMaxWords.value) asserts.max_words = parseInt(fieldAssertMaxWords.value, 10);
    if (fieldAssertMinScore.value) asserts.min_score = parseFloat(fieldAssertMinScore.value);
    if (fieldAssertScoreField.value) asserts.score_field = fieldAssertScoreField.value.trim();

    if (Object.keys(asserts).length > 0) {
      node.assert = asserts;
    } else {
      delete node.assert;
    }

    inspectorDirty = false; // 草稿已并入 currentGraph；保存失败时由 graphDirty 继续保护。
    renderGraph();
    return saveGraphToServer(triggerBtn, `节点 [${selectedNodeId}] 属性已保存至 ${currentWorkflow}`);
  }

  function deleteSelectedNode() {
    if (!selectedNodeId) return;
    const id = selectedNodeId;
    if (!confirm(`确定要删除节点 [${id}] 吗？`)) return;

    delete currentGraph.nodes[id];
    delete nodePositions[id];

    // 清理下游依赖
    Object.keys(currentGraph.nodes).forEach(k => {
      const n = currentGraph.nodes[k];
      if (n.after) n.after = n.after.filter(x => x !== id);
    });

    inspectorDrawer.classList.remove('open');
    inspectorDirty = false;
    selectedNodeId = null;
    renderGraph();
    saveGraphToServer(null, `🗑️ 节点 [${id}] 已删除并更新至磁盘`);
    appendLog(`[studio] 🗑️ 节点 [${id}] 已删除。`);
  }

  // ==========================================
  // 6. 保存与后端交互
  // ==========================================
  function saveGraphToServer(triggerBtn = null, successMsg = null) {
    if (!uiReady || !currentProject || !currentGraph) return Promise.resolve(false);
    graphDirty = true;
    const version = ++editVersion;
    persistedEditVersion = version;
    const snapshot = JSON.parse(JSON.stringify(currentGraph));
    const project = projectRequestValue();
    const workflow = currentWorkflow;
    const original = triggerBtn?.innerHTML;
    if (triggerBtn) { triggerBtn.disabled = true; triggerBtn.textContent = '正在保存...'; }
    pendingSaves++;
    // 串行写入：后一笔使用前一笔返回的 revision，不会因快速编辑制造自身冲突。
    saveQueue = saveQueue.then(async () => {
      try {
        if (saveConflict) throw new Error('磁盘版本已改变，请保留草稿或确认重新载入后再编辑');
        const data = await requestJson('/api/graph/save', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ project, workflow, graph: snapshot, revision: graphRevision })
        });
        if (!data.success || !data.revision) throw new Error('保存响应缺少成功标记或版本，请刷新核对磁盘');
        graphRevision = data.revision;
        if (persistedEditVersion === version) graphDirty = false;
        applyStateUpdate(data);
        appendLog(`[studio] ${workflow} 已保存，版本已更新。`);
        showToast(successMsg || `配置已保存至 ${workflow}`);
        return true;
      } catch (error) {
        graphDirty = true;
        if (error.status === 409) {
          saveConflict = true;
          showSyncNotice('保存冲突：宿主已修改工作流，当前草稿未被覆盖。请先复制保留需要的内容，再点击重新载入并确认丢弃。', true);
        } else reportSyncError(error);
        showToast(`保存失败：${error.message}`, 'error', 5000);
        return false;
      } finally {
        pendingSaves--;
        if (triggerBtn) { triggerBtn.innerHTML = original; triggerBtn.disabled = false; }
        if (pendingGraphRefresh) scheduleGraphRefresh();
      }
    });
    return saveQueue;
  }

  // ==========================================
  // 7. 任务执行与 Antigravity 派发
  // ==========================================
  async function runNode(nodeId, action = 'run_node') {
    if (!uiReady || boundContext) {
      showToast('请回主对话等待 supervisor 询问并明确确认执行。', 'info');
      return;
    }
    try {
      appendLog(`[studio] 触发执行任务: action=${action}, nodeId=${nodeId || 'all'}, workflow=${currentWorkflow}...`);
      openTerminal();

      if (nodeId && currentState && currentState.nodes && currentState.nodes[nodeId]) {
        currentState.nodes[nodeId].status = 'running';
        applyStateUpdate({ state: currentState });
      }

      const res = await fetch('/api/node/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          project: currentProject,
          node_id: nodeId,
          action: action,
          chapter: currentChapter,
          workflow: currentWorkflow
        })
      });

      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || '启动任务失败');

      subscribeLogs(data.taskId);
    } catch (err) {
      appendLog(`[error] 任务触发异常: ${err.message}`);
    }
  }

  function subscribeLogs(taskId) {
    if (activeEventSource) activeEventSource.close();

    activeEventSource = new EventSource(`/api/node/logs/${taskId}`);
    activeEventSource.onmessage = (event) => {
      try {
        const payload = JSON.parse(event.data);
        if (payload.type === 'log') {
          appendLog(payload.line, false);
        } else if (payload.type === 'end') {
          appendLog(`[studio] 🏁 任务结束，状态: ${payload.status}`);
          activeEventSource.close();
          activeEventSource = null;
          scheduleStateRefresh();
        }
      } catch {
        appendLog(event.data);
      }
    };

    activeEventSource.onerror = () => {
      appendLog('[studio] 日志流连接关闭');
      if (activeEventSource) {
        activeEventSource.close();
        activeEventSource = null;
      }
    };
  }

  function copyAgentRunPrompt() {
    if (!uiReady || boundContext || !selectedNodeId || !currentGraph.nodes[selectedNodeId]) return;
    const node = currentGraph.nodes[selectedNodeId];
    const skillList = node.skills || [];
    const skillDescriptions = skillList.map(sid => {
      const meta = availableSkills.find(s => s.id === sid);
      return meta ? `  * ${sid}【${meta.category}】：${meta.description}` : `  * ${sid}`;
    });

    const lines = [
      `【小说工作流任务派发】请执行项目 [${currentProject}] 的节点 [${selectedNodeId}]：`,
      `- 担当角色：${node.role || '小说主创作家'}`,
      `- 关联专业技能指导：\n${skillDescriptions.length > 0 ? skillDescriptions.join('\n') : '  * 无'}`,
      `- 输入文件契约：${(node.inputs || []).join(', ') || '无'}`,
      `- 产出文件契约：${(node.outputs || []).join(', ') || '无'}`,
    ];
    const stateEntry = getStateEntry(selectedNodeId);
    if (stateEntry && stateEntry.model) {
      lines.push(`- 执行模型（宿主 ${hostDisplayName()} 自动适配）：${stateEntry.model}`);
      if (stateEntry.model_note) {
        lines.push(`- ⚠ 模型适配说明：${stateEntry.model_note}`);
      }
    }
    if (node.assert) {
      lines.push(`- 质量硬断言要求：${JSON.stringify(node.assert)}`);
    }
    lines.push(`\n【核心执行指令】：\n${(node.prompt || node.ask || '').trim()}`);
    lines.push(`\n请直接使用你的文件写入工具生成内容写入产出文件，完成后执行状态刷新。`);

    const promptText = lines.join('\n');
    navigator.clipboard.writeText(promptText).then(() => {
      alert(`已成功复制 Agent 任务指令卡到剪贴板！可直接粘贴给宿主 Agent (${hostDisplayName()}) 执行。`);
    }).catch(() => {
      prompt('请手动复制任务指令：', promptText);
    });
  }

  function expandParamStr(text) {
    if (!text || !currentGraph || !currentGraph.params) return text;
    const params = currentGraph.params;
    return text.replace(/\{([a-zA-Z_][a-zA-Z0-9_]*)\}/g, (match, key) => {
      return params[key] !== undefined ? String(params[key]) : match;
    });
  }

  // ==========================================
  // 8. 章节审阅阅读器 (Reader)
  // ==========================================
  async function openReaderModal() {
    readerModal.classList.remove('hidden');
    if (currentReadingFile) return; // 再打开保留文件编辑，不重填草稿。
    readerFileList.innerHTML = '';
    readerTextarea.value = '请在左侧选择要审阅的产物文件...';

    const pad = String(currentChapter).padStart(2, '0');
    // 优先收录当前章节或分卷工作区核心演进文稿与模块化设定
    const filesSet = new Set();
    if (currentWorkflow.includes('volume')) {
      filesSet.add(`工作区/分卷策划/第${pad}卷_01_立意与核心命题.md`);
      filesSet.add(`工作区/分卷策划/第${pad}卷_02_副本物理与生存法则.md`);
      filesSet.add(`工作区/分卷策划/第${pad}卷_03_势力暗算盘与博弈矩阵.md`);
      filesSet.add(`工作区/分卷策划/第${pad}卷_04_四阶认知反转链.md`);
      filesSet.add(`工作区/分卷策划/第${pad}卷_05_逐章细纲矩阵.md`);
      filesSet.add(`工作区/分卷策划/第${pad}卷_06_伏笔生命周期总账.md`);
      filesSet.add('设定/大纲/01_全书宏观设定.md');
      filesSet.add('设定/世界观/01_法则与力量体系.md');
    } else {
      filesSet.add(`工作区/第${pad}章/03_去AI味润色稿.md`);
      filesSet.add(`工作区/第${pad}章/03_3_朱雀检测报告.md`);
      filesSet.add(`工作区/第${pad}章/04_盲审质检报告.md`);
      filesSet.add(`工作区/第${pad}章/03_5_人设审查报告.md`);
      filesSet.add(`工作区/第${pad}章/02_正文初稿.md`);
      filesSet.add(`工作区/第${pad}章/01_5_分场节拍表.md`);
      filesSet.add(`工作区/第${pad}章/01_状态上下文.md`);
      filesSet.add('设定/世界观/01_法则与力量体系.md');
      filesSet.add('设定/人物/01_主要人物小传.md');
      filesSet.add('设定/人物/02_人际关系矩阵.md');
      filesSet.add('设定/大纲/02_分卷细纲_第一卷.md');
      filesSet.add('资产/voice_sample.md');
    }

    if (currentGraph && currentGraph.nodes) {
      Object.values(currentGraph.nodes).forEach(n => {
        (n.outputs || []).forEach(o => filesSet.add(expandParamStr(o)));
      });
    }

    Array.from(filesSet).forEach(f => {
      const li = document.createElement('li');
      li.className = 'reader-file-item';
      li.textContent = f;
      li.addEventListener('click', () => { loadFileContent(f); });
      readerFileList.appendChild(li);
    });

    // 默认加载第一个
    const first = Array.from(filesSet)[0];
    if (first) loadFileContent(first);
  }

  async function loadFileContent(filename) {
    if (readerDirty && !confirm('当前文件尚未保存，确定丢弃编辑并读取另一个文件吗？')) return;
    const version = ++readerLoadVersion;
    readerTextarea.disabled = true;
    btnSaveReaderContent.disabled = true;
    try {
      const data = await requestJson(`/api/chapter/read?project=${encodeURIComponent(projectRequestValue())}&file=${encodeURIComponent(filename)}`);
      if (version !== readerLoadVersion) return;
      currentReadingFile = filename;
      readerFileName.textContent = filename;
      document.querySelectorAll('.reader-file-item').forEach(el => {
        el.classList.toggle('active', el.textContent === filename);
      });
      readerTextarea.value = data.exists ? data.content : '';
      readerTextarea.placeholder = data.exists ? '' : `文件尚未生成: ${filename}`;
      readerDirty = false;
      updateWordCount(readerTextarea.value);
    } catch (error) {
      reportSyncError(error);
      showToast(`文件读取失败：${error.message}`, 'error', 5000);
    } finally {
      if (version === readerLoadVersion) {
        readerTextarea.disabled = false;
        btnSaveReaderContent.disabled = !currentReadingFile;
      }
    }
  }

  function updateWordCount(text) {
    const cjk = (text.match(/[\u4e00-\u9fa5\u3040-\u30ff\u3400-\u4dbf]/g) || []).length;
    const words = (text.match(/\b[a-zA-Z0-9_-]+\b/g) || []).length;
    readerWordCountBadge.textContent = `有效字数: ${cjk + words}`;
  }

  async function saveReaderContent() {
    if (!currentReadingFile || readerTextarea.disabled) return;
    const file = currentReadingFile;
    const content = readerTextarea.value;
    const project = projectRequestValue();
    btnSaveReaderContent.disabled = true;
    try {
      await requestJson('/api/chapter/save', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ project, file, content })
      });
      if (file === currentReadingFile && content === readerTextarea.value && project === projectRequestValue()) readerDirty = false;
      showToast(`${file} 已保存`);
      scheduleStateRefresh();
      if (pendingGraphRefresh) scheduleGraphRefresh();
    } catch (error) {
      reportSyncError(error);
      showToast(`文件保存失败：${error.message}`, 'error', 5000);
    } finally { btnSaveReaderContent.disabled = readerTextarea.disabled || !currentReadingFile; }
  }

  // ==========================================
  // 9. 事件绑定
  // ==========================================
  function setupEventListeners() {
    projectSelect.addEventListener('change', async (e) => {
      if (!allowContextSwitch()) { projectSelect.value = currentProject; return; }
      currentProject = e.target.value;
      explicitChapter = null;
      selectedNodeId = null;
      inspectorDrawer.classList.remove('open');
      try {
        localStorage.setItem('studio_selected_project', currentProject);
        await loadWorkflows(currentProject);
        await loadGraph(currentProject);
      } catch (error) { reportSyncError(error); }
    });

    workflowSelect.addEventListener('change', async (e) => {
      if (!allowContextSwitch()) { workflowSelect.value = currentWorkflow; return; }
      currentWorkflow = e.target.value;
      explicitChapter = null;
      selectedNodeId = null;
      inspectorDrawer.classList.remove('open');
      try {
        localStorage.setItem(`studio_wf_${currentProject}`, currentWorkflow);
        await loadGraph(currentProject);
      } catch (error) { reportSyncError(error); }
    });

    function switchChapter(value) {
      if (Number.isInteger(value) && value > 0 && value !== currentChapter && allowContextSwitch()) {
        loadGraph(currentProject, value).catch(reportSyncError);
      } else chapterInput.value = currentChapter;
    }
    chapterInput.addEventListener('change', e => switchChapter(parseInt(e.target.value, 10)));
    chapterInput.addEventListener('keydown', e => {
      if (e.key === 'Enter') { e.preventDefault(); chapterInput.blur(); }
    });
    btnPrevChapter.addEventListener('click', () => switchChapter(Math.max(1, currentChapter - 1)));
    btnNextChapter.addEventListener('click', () => switchChapter(currentChapter + 1));

    btnRefreshStatus.addEventListener('click', refreshGraphExplicitly);
    document.getElementById('btnReloadGraph').addEventListener('click', refreshGraphExplicitly);
    inspectorDrawer.addEventListener('focusout', () => { if (pendingGraphRefresh) scheduleGraphRefresh(); });
    [fieldRole, fieldPrompt, fieldRun, fieldAsk, fieldInputs, fieldOutputs,
      fieldAssertMinWords, fieldAssertMaxWords, fieldAssertMinScore, fieldAssertScoreField].forEach(el => {
      el.addEventListener('input', markInspectorDirty);
    });
    window.addEventListener('beforeunload', e => {
      if (hasUnsavedChanges() || pendingSaves) { e.preventDefault(); e.returnValue = ''; }
    });
    if (liveStatusBadge) {
      liveStatusBadge.addEventListener('click', () => {
        if (!liveWs || liveWs.readyState !== WebSocket.OPEN) {
          showToast('🔄 正在重新连接实时双向通道...', 'info', 1500);
          initLiveWebSocket();
        } else {
          showToast('🟢 实时通道正常连接中（底层文件变动将秒级推送）', 'info', 2000);
        }
      });
    }

    btnSaveGraph.addEventListener('click', () => {
      if (inspectorDirty) saveCurrentNodeFromInspector(btnSaveGraph);
      else saveGraphToServer(btnSaveGraph);
    });
    btnReconcile.addEventListener('click', () => { runNode(null, 'reconcile'); });

    btnToggleTerminal.addEventListener('click', () => {
      terminalDrawer.classList.toggle('collapsed');
    });
    btnCloseTerminal.addEventListener('click', () => {
      terminalDrawer.classList.add('collapsed');
    });
    btnClearLog.addEventListener('click', () => {
      terminalLogs.innerHTML = '';
    });

    // Inspector
    btnCloseInspector.addEventListener('click', () => {
      if (!confirmInspectorDiscard()) return;
      inspectorDrawer.classList.remove('open');
      selectedNodeId = null;
      document.querySelectorAll('.node-card').forEach(c => c.classList.remove('selected'));
      if (pendingGraphRefresh) scheduleGraphRefresh();
    });
    btnSaveNode.addEventListener('click', () => {
      saveCurrentNodeFromInspector(btnSaveNode);
    });
    btnDeleteNode.addEventListener('click', deleteSelectedNode);

    if (selectNodeModel) {
      selectNodeModel.addEventListener('change', () => {
        if (boundContext) return;
        if (selectNodeModel.value === 'custom') {
          if (fieldModel) {
            fieldModel.classList.remove('hidden');
            fieldModel.focus();
          }
        } else {
          if (fieldModel) {
            fieldModel.classList.add('hidden');
            fieldModel.value = selectNodeModel.value;
          }
        }
        markInspectorDirty();
      });
    }

    if (fieldModel) {
      fieldModel.addEventListener('input', () => {
        if (!boundContext) markInspectorDirty();
      });
    }
    btnDispatchHost.addEventListener('click', () => {
      if (selectedNodeId) runNode(selectedNodeId, 'run_node');
    });
    btnCopyPrompt.addEventListener('click', copyAgentRunPrompt);

    // 技能管理器事件
    if (btnAddSystemSkill) {
      btnAddSystemSkill.addEventListener('click', () => {
        const val = selectAvailableSkill.value;
        if (val) {
          addSkillToCurrentNode(val);
          selectAvailableSkill.value = '';
        }
      });
    }
    if (btnAddCustomSkill) {
      btnAddCustomSkill.addEventListener('click', () => {
        const val = inputCustomSkill.value.trim();
        if (val) {
          addSkillToCurrentNode(val);
          inputCustomSkill.value = '';
        }
      });
    }
    if (inputCustomSkill) {
      inputCustomSkill.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
          e.preventDefault();
          btnAddCustomSkill.click();
        }
      });
    }

    // 缩放与平移
    btnZoomIn.addEventListener('click', () => { zoom = Math.min(2.0, zoom + 0.15); applyCanvasTransform(); });
    btnZoomOut.addEventListener('click', () => { zoom = Math.max(0.4, zoom - 0.15); applyCanvasTransform(); });
    btnZoomReset.addEventListener('click', () => { zoom = 1.0; panX = 40; panY = 60; applyCanvasTransform(); });
    btnAutoLayout.addEventListener('click', () => { autoComputeLayout(); renderGraph(); saveGraphToServer(); });

    canvasViewport.addEventListener('wheel', (e) => {
      e.preventDefault();
      const delta = e.deltaY > 0 ? -0.08 : 0.08;
      zoom = Math.min(2.0, Math.max(0.4, zoom + delta));
      applyCanvasTransform();
    }, { passive: false });

    canvasViewport.addEventListener('mousedown', (e) => {
      if (connectingFromId) return;
      if (e.target === canvasViewport || e.target.id === 'edgesSvg') {
        isPanning = true;
        startMouseX = e.clientX - panX;
        startMouseY = e.clientY - panY;
      }
    });

    canvasViewport.addEventListener('click', (e) => {
      if (connectingFromId && !e.target.closest('.node-card') && !e.target.closest('.connect-tip-bar')) {
        cancelConnect();
      }
    });

    window.addEventListener('mousemove', (e) => {
      if (isPanning) {
        panX = e.clientX - startMouseX;
        panY = e.clientY - startMouseY;
        applyCanvasTransform();
      } else if (draggingNodeId) {
        const rect = canvasViewport.getBoundingClientRect();
        const x = (e.clientX - rect.left - panX) / zoom - dragOffsetX;
        const y = (e.clientY - rect.top - panY) / zoom - dragOffsetY;
        nodePositions[draggingNodeId] = { x: Math.round(x), y: Math.round(y) };
        const card = document.getElementById(`node-${draggingNodeId}`);
        if (card) card.style.transform = `translate(${x}px, ${y}px)`;
        renderEdges();
      } else if (connectingFromId) {
        if (connectStartMousePos) {
          const dist = Math.hypot(e.clientX - connectStartMousePos.x, e.clientY - connectStartMousePos.y);
          if (dist > 6) {
            isDragConnecting = true;
          }
        }
        const rect = canvasViewport.getBoundingClientRect();
        const mouseCanvasX = (e.clientX - rect.left - panX) / zoom;
        const mouseCanvasY = (e.clientY - rect.top - panY) / zoom;
        updateTempEdge(mouseCanvasX, mouseCanvasY);

        // 目标悬浮卡片高亮
        const hoveredCard = document.elementFromPoint(e.clientX, e.clientY)?.closest('.node-card');
        document.querySelectorAll('.node-card').forEach(c => c.classList.remove('connect-target-candidate'));
        if (hoveredCard) {
          const hoveredId = hoveredCard.id.replace('node-', '');
          if (hoveredId && hoveredId !== connectingFromId) {
            hoveredCard.classList.add('connect-target-candidate');
          }
        }
      }
    });

    window.addEventListener('mouseup', (e) => {
      if (connectingFromId) {
        if (isDragConnecting) {
          const targetCard = document.elementFromPoint(e.clientX, e.clientY)?.closest('.node-card');
          if (targetCard) {
            const targetId = targetCard.id.replace('node-', '');
            if (targetId && targetId !== connectingFromId) {
              completeConnectTo(targetId);
              isPanning = false;
              draggingNodeId = null;
              connectStartMousePos = null;
              isDragConnecting = false;
              return;
            }
          }
          cancelConnect();
        }
        connectStartMousePos = null;
      }
      isPanning = false;
      draggingNodeId = null;
      if (pendingGraphRefresh) scheduleGraphRefresh();
    });

    // ESC 键随时取消连线
    window.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && connectingFromId) {
        cancelConnect();
      }
    });

    btnCancelConnect.addEventListener('click', cancelConnect);

    // 跨浏览器窗口切换自动同步（当从其他浏览器如 Edge 切回 Chrome 时，自动静默刷新最新磁盘状态）
    window.addEventListener('focus', () => {
      if (uiReady && currentProject) scheduleStateRefresh();
      if (pendingGraphRefresh) scheduleGraphRefresh();
    });

    // 模态框打开与关闭
    btnOpenNewProjectModal.addEventListener('click', () => { createProjectModal.classList.remove('hidden'); });
    btnCloseCreateProjectModal.addEventListener('click', () => { createProjectModal.classList.add('hidden'); });
    btnConfirmCreateProject.addEventListener('click', handleCreateProject);

    btnOpenAddPathModal.addEventListener('click', () => { addPathModal.classList.remove('hidden'); });
    btnCloseAddPathModal.addEventListener('click', () => { addPathModal.classList.add('hidden'); });
    btnConfirmAddPath.addEventListener('click', handleAddPath);

    btnOpenAddNodeModal.addEventListener('click', () => { addNodeModal.classList.remove('hidden'); });
    btnCloseAddNodeModal.addEventListener('click', () => { addNodeModal.classList.add('hidden'); });
    btnConfirmAddNode.addEventListener('click', handleAddNode);

    btnToggleReader.addEventListener('click', openReaderModal);
    btnCloseReaderModal.addEventListener('click', () => {
      readerModal.classList.add('hidden');
      if (pendingGraphRefresh) scheduleGraphRefresh();
    });
    btnSaveReaderContent.addEventListener('click', saveReaderContent);
    readerTextarea.addEventListener('input', (e) => {
      readerDirty = true;
      editVersion++;
      updateWordCount(e.target.value);
    });
  }

  async function handleCreateProject() {
    if (boundContext || !uiReady) return;
    const slug = newProjSlug.value.trim();
    if (!slug) return alert('请输入工程标识 (Slug)');

    try {
      appendLog(`[studio] 正在脚手架初始化小说工程 [${slug}]...`);
      const res = await fetch('/api/projects/create', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          slug: slug,
          title: newProjTitle.value.trim() || '未命名小说',
          genre: newProjGenre.value.trim() || '科幻悬疑',
          protagonist: newProjProtagonist.value.trim() || '主角',
          logline: newProjLogline.value.trim() || '故事主旨梗概...'
        })
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || '创建失败');

      createProjectModal.classList.add('hidden');
      currentProject = slug;
      await loadProjects();
      appendLog(`[studio] ✅ 小说新工程 [${slug}] 创建成功并加载！`);
    } catch (err) {
      alert(`创建失败: ${err.message}`);
    }
  }

  async function handleAddPath() {
    if (boundContext || !uiReady) return;
    const rawPath = customPathInput.value.trim();
    if (!rawPath) return alert('请输入有效路径');

    try {
      const res = await fetch('/api/projects/add', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path: rawPath })
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || '关联失败');

      addPathModal.classList.add('hidden');
      await loadProjects();
      appendLog(`[studio] ✅ 已成功关联外部小说目录: ${data.path}`);
    } catch (err) {
      alert(`关联失败: ${err.message}`);
    }
  }

  function handleAddNode() {
    if (!uiReady || !currentGraph) return;
    const id = newNodeId.value.trim().replace(/\s+/g, '_').toLowerCase();
    const kind = newNodeKind.value;
    const role = newNodeRole.value.trim();

    if (!id) return alert('请输入合法节点 ID');
    if (currentGraph.nodes[id]) return alert(`节点 [${id}] 已存在！`);
    if (!confirmInspectorDiscard()) return;

    const node = { kind: kind };
    if (kind === 'agent') {
      node.role = role || '小说创作智能体';
      node.prompt = '编写该节点的创作或审校任务要求...';
      node.inputs = [];
      node.outputs = [];
    } else if (kind === 'command') {
      node.run = ['python', 'shared/novel_stats.py'];
      node.inputs = [];
      node.outputs = [];
    } else if (kind === 'human') {
      node.ask = role || '请作者审阅并放行';
      node.inputs = [];
      node.outputs = [];
    }

    if (selectedNodeId && selectedNodeId !== id) {
      node.after = [selectedNodeId];
    }

    currentGraph.nodes[id] = node;
    nodePositions[id] = {
      x: (canvasViewport.clientWidth / 2 - panX) / zoom,
      y: (canvasViewport.clientHeight / 2 - panY) / zoom
    };

    addNodeModal.classList.add('hidden');
    newNodeId.value = '';
    newNodeRole.value = '';

    renderGraph();
    selectNode(id);
    saveGraphToServer();
    appendLog(`[studio] ➕ 新增节点 [${id}] (${kind})，请在右侧完善配置。`);
  }

  // 辅助函数
  function appendLog(text, addNewline = true) {
    const div = document.createElement('div');
    div.textContent = text + (addNewline ? '\n' : '');
    terminalLogs.appendChild(div);
    terminalLogs.scrollTop = terminalLogs.scrollHeight;
  }

  function openTerminal() {
    terminalDrawer.classList.remove('collapsed');
  }

  function escapeHtml(str) {
    return (str || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  // 启动
  window.addEventListener('DOMContentLoaded', init);
})();
