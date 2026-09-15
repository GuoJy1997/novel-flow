// Novel Pipeline Studio - 前端画布交互与调度逻辑 (v1.0)
(function () {
  'use strict';

  // 全局应用状态
  let currentProject = '';
  let currentGraph = null;
  let currentState = null;
  let selectedNodeId = null;
  let activeEventSource = null;

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

  // 连线状态
  let connectingFromId = null;
  let isDraggingConnect = false;
  let tempEdgeStartPos = { x: 0, y: 0 };

  // 动态章节状态
  let currentChapter = 1;

  // DOM 元素引用
  const projectSelect = document.getElementById('projectSelect');
  const btnOpenNewProjectModal = document.getElementById('btnOpenNewProjectModal');
  const btnOpenAddPathModal = document.getElementById('btnOpenAddPathModal');

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

  function formatModelShort(model) {
    if (!model) return '⚡ Gemini 3.8 Flash (High)';
    const m = model.toLowerCase();
    if (m.includes('opus')) return '🧠 Claude Opus 4.6 (Thinking)';
    if (m.includes('sonnet')) return '🧠 Claude 3.7 Sonnet (Thinking)';
    if (m === 'gemini-3.8-flash-high') return '⚡ Gemini 3.8 Flash (High)';
    if (m === 'gemini-3.8-flash-medium') return '⚡ Gemini 3.8 Flash (Medium)';
    if (m === 'gemini-3.8-flash-low') return '⚡ Gemini 3.8 Flash (Low)';
    if (m.includes('flash')) return '⚡ Gemini 3.8 Flash';
    return `🤖 ${model.length > 25 ? model.substring(0, 23) + '..' : model}`;
  }

  function getModelClass(model) {
    if (!model) return 'model-default';
    const m = model.toLowerCase();
    if (m.includes('opus') || m.includes('claude')) return 'model-claude';
    if (m.includes('gemini') || m.includes('flash')) return 'model-gemini';
    return 'model-custom';
  }

  // ==========================================
  // 1. 初始化与项目加载
  // ==========================================
  async function init() {
    setupEventListeners();
    await fetchAvailableSkills();
    await loadProjects();
  }

  async function fetchAvailableSkills() {
    try {
      const res = await fetch('/api/skills');
      const data = await res.json();
      availableSkills = data.skills || [];
      populateAvailableSkillsDropdown();
    } catch (e) {
      console.error('Failed to load skills:', e);
    }
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

  async function loadProjects() {
    try {
      const res = await fetch('/api/projects');
      const data = await res.json();
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

      if (!currentProject || !data.projects.some(p => p.slug === currentProject)) {
        currentProject = data.projects[0].slug;
      }
      projectSelect.value = currentProject;
      await loadGraph(currentProject);
    } catch (err) {
      appendLog(`[error] 加载课题列表失败: ${err.message}`);
    }
  }

  async function loadGraph(projectSlug, targetChapter = null) {
    if (!projectSlug) return;
    if (targetChapter !== null && !isNaN(targetChapter)) {
      currentChapter = parseInt(targetChapter, 10);
    }
    try {
      appendLog(`[studio] 正在加载小说项目 [${projectSlug}] 第 ${currentChapter} 章拓扑与状态...`);
      const res = await fetch(`/api/graph?project=${encodeURIComponent(projectSlug)}&chapter=${currentChapter}`);
      const data = await res.json();

      if (!data.hasGraph || !data.graph) {
        appendLog(`[warn] 该项目尚未配置 graph.yaml`);
        nodesLayer.innerHTML = '<div style="padding:40px;color:#94a3b8;">该项目尚未创建 graph.yaml，请添加节点并保存。</div>';
        edgesGroup.innerHTML = '';
        currentGraph = { version: 1, name: projectSlug, nodes: {} };
        currentState = null;
        return;
      }

      currentGraph = data.graph;
      currentState = data.state;
      if (data.currentChapter !== undefined) {
        currentChapter = data.currentChapter;
      }
      if (chapterInput) chapterInput.value = currentChapter;

      // 自动计算初始拓扑位置
      autoComputeLayout();
      renderGraph();
      if (selectedNodeId && currentGraph.nodes[selectedNodeId]) {
        selectNode(selectedNodeId);
      }
    } catch (err) {
      appendLog(`[error] 加载节点图失败: ${err.message}`);
    }
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
      const status = stateEntry ? stateEntry.status : 'stale';

      const card = document.createElement('div');
      card.className = `node-card status-${status} ${selectedNodeId === id ? 'selected' : ''}`;
      card.id = `node-${id}`;
      card.style.transform = `translate(${pos.x}px, ${pos.y}px)`;

      const roleText = node.role || (node.kind === 'command' ? '命令行工具' : '人工检查点');
      const promptBrief = node.prompt || node.ask || (node.run ? node.run.join(' ') : '无指令说明');
      const modelBadgeHtml = (node.kind === 'agent' && node.model)
        ? `<div class="node-model-row"><span class="node-model-chip ${getModelClass(node.model)}" title="执行模型: ${escapeHtml(node.model)}">${formatModelShort(node.model)}</span></div>`
        : '';

      card.innerHTML = `
        <div class="node-header">
          <div class="node-title-group">
            <span class="status-indicator ${status}"></span>
            <span class="node-title" title="${id}">${id}</span>
          </div>
          <span class="kind-badge kind-badge-${node.kind}">${node.kind}</span>
        </div>
        <div class="node-body">
          <div class="node-role">${escapeHtml(roleText)}</div>
          ${modelBadgeHtml}
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
        selectNode(id);
        draggingNodeId = id;
        dragOffsetX = (e.clientX - panX) / zoom - pos.x;
        dragOffsetY = (e.clientY - panY) / zoom - pos.y;
        e.stopPropagation();
      });

      // 右侧输出端口事件：支持按住拖拽连线与点击连线双模
      const portOut = card.querySelector('.port-out');
      portOut.addEventListener('mousedown', (e) => {
        e.stopPropagation();
        e.preventDefault();
        startConnectFrom(id, true);
      });
      portOut.addEventListener('click', (e) => {
        e.stopPropagation();
        if (!connectingFromId) {
          startConnectFrom(id, false);
        }
      });

      // 左侧输入端口事件：点击完成连线
      const portIn = card.querySelector('.port-in');
      portIn.addEventListener('click', (e) => {
        e.stopPropagation();
        if (connectingFromId && connectingFromId !== id) {
          completeConnectTo(id);
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
        g.className = 'edge-item';

        const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
        path.setAttribute('d', d);
        path.setAttribute('class', 'edge-path');

        const stateTarget = (currentState && currentState.nodes) ? currentState.nodes[targetId] : null;
        if (stateTarget && stateTarget.status === 'current') {
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
  function startConnectFrom(nodeId, isDrag = false) {
    connectingFromId = nodeId;
    isDraggingConnect = isDrag;
    tempEdgeStartPos = getNodeCenterPort(nodeId, true);
    document.body.classList.add('is-connecting');
    connectTipBar.classList.remove('hidden');
    appendLog(`[studio] 🔗 连线起点已锁定: [${nodeId}]，按住拖拽至目标节点释放或直接点击目标节点完成连接（按 ESC 取消）。`);
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
    if (selectedNodeId === targetId) selectNode(targetId);
  }

  function cancelConnect() {
    connectingFromId = null;
    isDraggingConnect = false;
    document.body.classList.remove('is-connecting');
    connectTipBar.classList.add('hidden');
    tempEdge.setAttribute('d', '');
    document.querySelectorAll('.node-card').forEach(c => c.classList.remove('connect-target-candidate'));
  }

  function disconnectNodes(sourceId, targetId) {
    const targetNode = currentGraph.nodes[targetId];
    if (!targetNode || !targetNode.after) return;
    targetNode.after = targetNode.after.filter(x => x !== sourceId);
    appendLog(`[studio] ✂️ 已剪断依赖: [${sourceId}] ➔ [${targetId}]`);
    renderEdges();
    if (selectedNodeId === targetId) selectNode(targetId);
    saveGraphToServer();
  }

  // ==========================================
  // 5. 属性检查器 Inspector
  // ==========================================
  function selectNode(id) {
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
    const status = stateEntry ? stateEntry.status : 'stale';
    inspectorStatusPill.textContent = status;
    inspectorStatusPill.className = `status-pill status-${status}`;
    inspectorStatusReason.textContent = (stateEntry && stateEntry.staleBecause) ? stateEntry.staleBecause : '';

    // 依赖多选渲染
    renderAfterCheckboxes(id, node.after || []);

    // 区分展示专有字段
    sectionAgentFields.classList.toggle('hidden', node.kind !== 'agent');
    sectionCommandFields.classList.toggle('hidden', node.kind !== 'command');
    sectionHumanFields.classList.toggle('hidden', node.kind !== 'human');

    if (node.kind === 'agent') {
      const currentModel = node.model || 'gemini-3.8-flash-high';
      const knownModels = [
        'gemini-3.8-flash-high',
        'gemini-3.8-flash-medium',
        'gemini-3.8-flash-low',
        'claude-opus-4.6-thinking',
        'claude-3.7-sonnet-thinking'
      ];
      if (selectNodeModel) {
        if (knownModels.includes(currentModel)) {
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
      fieldRole.value = node.role || '';
      fieldPrompt.value = node.prompt || '';
      fieldSkills.value = (node.skills || []).join(', ');
      renderNodeSkills(node.skills || []);
      btnDispatchHost.textContent = '🚀 在 Antigravity 中执行';
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

  function saveCurrentNodeFromInspector() {
    if (!selectedNodeId || !currentGraph.nodes[selectedNodeId]) return;
    const node = currentGraph.nodes[selectedNodeId];

    node.inputs = fieldInputs.value.split(',').map(s => s.trim()).filter(Boolean);
    node.outputs = fieldOutputs.value.split(',').map(s => s.trim()).filter(Boolean);

    if (node.kind === 'agent') {
      node.role = fieldRole.value.trim();
      node.prompt = fieldPrompt.value;
      node.skills = fieldSkills.value.split(',').map(s => s.trim()).filter(Boolean);
      if (selectNodeModel) {
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

    renderGraph();
    saveGraphToServer();
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
    selectedNodeId = null;
    renderGraph();
    saveGraphToServer();
    appendLog(`[studio] 🗑️ 节点 [${id}] 已删除。`);
  }

  // ==========================================
  // 6. 保存与后端交互
  // ==========================================
  async function saveGraphToServer() {
    if (!currentProject || !currentGraph) return;
    try {
      appendLog(`[studio] 正在保存配置至 graph.yaml 并重算状态...`);
      const res = await fetch('/api/graph/save', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ project: currentProject, graph: currentGraph })
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || '保存失败');

      currentState = data.state;
      renderGraph();
      if (selectedNodeId) selectNode(selectedNodeId);
      appendLog(`[studio] ✅ graph.yaml 保存成功，依赖哈希与状态已刷新。`);
    } catch (err) {
      appendLog(`[error] 保存异常: ${err.message}`);
      alert(`保存失败: ${err.message}`);
    }
  }

  // ==========================================
  // 7. 任务执行与 Antigravity 派发
  // ==========================================
  async function runNode(nodeId, action = 'run_node') {
    try {
      appendLog(`[studio] 触发执行任务: action=${action}, nodeId=${nodeId || 'all'}...`);
      openTerminal();

      if (nodeId && currentState && currentState.nodes && currentState.nodes[nodeId]) {
        currentState.nodes[nodeId].status = 'running';
        renderGraph();
      }

      const res = await fetch('/api/node/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          project: currentProject,
          node_id: nodeId,
          action: action,
          chapter: currentChapter
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
          setTimeout(() => { loadGraph(currentProject); }, 500);
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
    if (!selectedNodeId || !currentGraph.nodes[selectedNodeId]) return;
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
    if (node.assert) {
      lines.push(`- 质量硬断言要求：${JSON.stringify(node.assert)}`);
    }
    lines.push(`\n【核心执行指令】：\n${(node.prompt || node.ask || '').trim()}`);
    lines.push(`\n请直接使用你的文件写入工具生成内容写入产出文件，完成后执行状态刷新。`);

    const promptText = lines.join('\n');
    navigator.clipboard.writeText(promptText).then(() => {
      alert('已成功复制 Agent 任务指令卡到剪贴板！可直接粘贴给宿主 Agent (Antigravity) 执行。');
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
    readerFileList.innerHTML = '';
    readerTextarea.value = '请在左侧选择要审阅的产物文件...';

    const pad = String(currentChapter).padStart(2, '0');
    // 优先收录当前章节工作区核心演进文稿与模块化设定
    const filesSet = new Set([
      `工作区/第${pad}章/03_去AI味润色稿.md`,
      `工作区/第${pad}章/04_盲审质检报告.md`,
      `工作区/第${pad}章/02_正文初稿.md`,
      `工作区/第${pad}章/01_状态上下文.md`,
      '设定/世界观/01_法则与力量体系.md',
      '设定/人物/01_主要人物小传.md',
      '设定/人物/02_人际关系矩阵.md',
      '设定/大纲/02_分卷细纲_第一卷.md',
      '资产/voice_sample.md'
    ]);

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
    currentReadingFile = filename;
    readerFileName.textContent = filename;
    document.querySelectorAll('.reader-file-item').forEach(el => {
      el.classList.toggle('active', el.textContent === filename);
    });

    try {
      const res = await fetch(`/api/chapter/read?project=${encodeURIComponent(currentProject)}&file=${encodeURIComponent(filename)}`);
      const data = await res.json();
      if (!data.exists) {
        readerTextarea.value = `[文件尚未生成: ${filename}]`;
        readerWordCountBadge.textContent = '字数: 0 (未生成)';
      } else {
        readerTextarea.value = data.content;
        updateWordCount(data.content);
      }
    } catch (err) {
      readerTextarea.value = `加载失败: ${err.message}`;
    }
  }

  function updateWordCount(text) {
    const cjk = (text.match(/[\u4e00-\u9fa5\u3040-\u30ff\u3400-\u4dbf]/g) || []).length;
    const words = (text.match(/\b[a-zA-Z0-9_-]+\b/g) || []).length;
    readerWordCountBadge.textContent = `有效字数: ${cjk + words}`;
  }

  async function saveReaderContent() {
    if (!currentReadingFile) return;
    try {
      const res = await fetch('/api/chapter/save', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ project: currentProject, file: currentReadingFile, content: readerTextarea.value })
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || '保存失败');
      appendLog(`[studio] 💾 ${currentReadingFile} 已成功保存修改。`);
      alert(`${currentReadingFile} 保存成功！`);
      setTimeout(() => { loadGraph(currentProject); }, 400);
    } catch (err) {
      alert(`保存失败: ${err.message}`);
    }
  }

  // ==========================================
  // 9. 事件绑定
  // ==========================================
  function setupEventListeners() {
    projectSelect.addEventListener('change', (e) => {
      currentProject = e.target.value;
      loadGraph(currentProject);
    });

    if (chapterInput) {
      chapterInput.addEventListener('change', (e) => {
        const val = parseInt(e.target.value, 10);
        if (!isNaN(val) && val > 0) {
          loadGraph(currentProject, val);
        }
      });
      chapterInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
          const val = parseInt(e.target.value, 10);
          if (!isNaN(val) && val > 0) {
            loadGraph(currentProject, val);
          }
        }
      });
    }

    if (btnPrevChapter) {
      btnPrevChapter.addEventListener('click', () => {
        const prev = Math.max(1, currentChapter - 1);
        loadGraph(currentProject, prev);
      });
    }

    if (btnNextChapter) {
      btnNextChapter.addEventListener('click', () => {
        const next = currentChapter + 1;
        loadGraph(currentProject, next);
      });
    }

    btnRefreshStatus.addEventListener('click', () => { loadGraph(currentProject, currentChapter); });
    btnSaveGraph.addEventListener('click', saveGraphToServer);
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
      inspectorDrawer.classList.remove('open');
      selectedNodeId = null;
      document.querySelectorAll('.node-card').forEach(c => c.classList.remove('selected'));
    });
    btnSaveNode.addEventListener('click', saveCurrentNodeFromInspector);
    btnDeleteNode.addEventListener('click', deleteSelectedNode);

    if (selectNodeModel) {
      selectNodeModel.addEventListener('change', () => {
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
        saveCurrentNodeFromInspector();
      });
    }

    if (fieldModel) {
      fieldModel.addEventListener('input', () => {
        saveCurrentNodeFromInspector();
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
      if (e.target === canvasViewport || e.target.id === 'edgesSvg') {
        isPanning = true;
        startMouseX = e.clientX - panX;
        startMouseY = e.clientY - panY;
      }
    });

    window.addEventListener('mousemove', (e) => {
      if (isPanning) {
        panX = e.clientX - startMouseX;
        panY = e.clientY - startMouseY;
        applyCanvasTransform();
      } else if (draggingNodeId) {
        const x = (e.clientX - panX) / zoom - dragOffsetX;
        const y = (e.clientY - panY) / zoom - dragOffsetY;
        nodePositions[draggingNodeId] = { x: Math.round(x), y: Math.round(y) };
        const card = document.getElementById(`node-${draggingNodeId}`);
        if (card) card.style.transform = `translate(${x}px, ${y}px)`;
        renderEdges();
      } else if (connectingFromId) {
        // 连线中：实时计算逻辑坐标并更新动态贝塞尔虚线
        const mouseCanvasX = (e.clientX - panX) / zoom;
        const mouseCanvasY = (e.clientY - panY) / zoom;
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
      if (isDraggingConnect && connectingFromId) {
        const targetCard = document.elementFromPoint(e.clientX, e.clientY)?.closest('.node-card');
        if (targetCard) {
          const targetId = targetCard.id.replace('node-', '');
          if (targetId && targetId !== connectingFromId) {
            completeConnectTo(targetId);
            isPanning = false;
            draggingNodeId = null;
            return;
          }
        }
        cancelConnect();
      }
      isPanning = false;
      draggingNodeId = null;
    });

    // ESC 键随时取消连线
    window.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && connectingFromId) {
        cancelConnect();
      }
    });

    btnCancelConnect.addEventListener('click', cancelConnect);

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
    btnCloseReaderModal.addEventListener('click', () => { readerModal.classList.add('hidden'); });
    btnSaveReaderContent.addEventListener('click', saveReaderContent);
    readerTextarea.addEventListener('input', (e) => { updateWordCount(e.target.value); });
  }

  async function handleCreateProject() {
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
    const id = newNodeId.value.trim().replace(/\s+/g, '_').toLowerCase();
    const kind = newNodeKind.value;
    const role = newNodeRole.value.trim();

    if (!id) return alert('请输入合法节点 ID');
    if (currentGraph.nodes[id]) return alert(`节点 [${id}] 已存在！`);

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
