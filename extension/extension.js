// Novel Pipeline Studio - 桌面 Agent 宿主通用插件核心
// 兼容 Qoder / Cursor / Antigravity / VS Code / Windsurf
const vscode = require('vscode');
const http = require('http');
const path = require('path');
const { spawn } = require('child_process');

let serverProcess = null;
const SERVER_PORT = 8766;
const SERVER_URL = `http://127.0.0.1:${SERVER_PORT}`;

function checkServerHealth() {
  return new Promise((resolve) => {
    const req = http.get(`${SERVER_URL}/api/health`, (res) => {
      resolve(res.statusCode === 200);
    });
    req.on('error', () => resolve(false));
    req.setTimeout(1000, () => {
      req.destroy();
      resolve(false);
    });
  });
}

async function ensureServerRunning(extensionRoot) {
  const isHealthy = await checkServerHealth();
  if (isHealthy) {
    console.log('[NovelStudio] 后台服务正在运行:', SERVER_URL);
    return true;
  }

  // 计算 shared/server.py 绝对路径
  const serverScript = path.join(extensionRoot, 'shared', 'server.py');
  console.log('[NovelStudio] 正在启动服务:', serverScript);

  try {
    serverProcess = spawn('python', [serverScript, '--port', String(SERVER_PORT)], {
      cwd: extensionRoot,
      detached: false,
      stdio: 'pipe'
    });

    serverProcess.stdout.on('data', (d) => console.log(`[Server] ${d}`));
    serverProcess.stderr.on('data', (d) => console.error(`[Server Err] ${d}`));
    serverProcess.on('close', (code) => {
      console.log(`[NovelStudio] 后台服务退出，代码: ${code}`);
      serverProcess = null;
    });

    for (let i = 0; i < 15; i++) {
      await new Promise(r => setTimeout(r, 250));
      if (await checkServerHealth()) {
        console.log('[NovelStudio] 后台服务就绪!');
        return true;
      }
    }
  } catch (err) {
    console.error('[NovelStudio] 启动异常:', err);
  }
  return false;
}

class StudioViewProvider {
  constructor(context, studioRoot) {
    this.context = context;
    this.studioRoot = studioRoot;
    this._view = null;
  }

  async resolveWebviewView(webviewView) {
    this._view = webviewView;
    const webview = webviewView.webview;

    webview.options = {
      enableScripts: true,
      enableForms: true,
      localResourceRoots: [vscode.Uri.file(this.studioRoot)]
    };

    webview.html = this.getLoadingHtml();

    const ready = await ensureServerRunning(this.studioRoot);
    if (ready) {
      webview.html = this.getFrameHtml();
    } else {
      webview.html = this.getErrorHtml();
    }
  }

  getLoadingHtml() {
    return `<!DOCTYPE html><html><body style="background:#0b0f17;color:#94a3b8;display:flex;align-items:center;justify-content:center;height:100vh;font-family:sans-serif;">
      <div style="text-align:center;">
        <div style="font-size:18px;font-weight:600;color:#38bdf8;margin-bottom:8px;">笔心 Studio</div>
        <div>正在连接小说流水线引擎...</div>
      </div>
    </body></html>`;
  }

  getFrameHtml() {
    return `<!DOCTYPE html>
    <html style="height:100%;width:100%;margin:0;padding:0;overflow:hidden;">
    <body style="height:100%;width:100%;margin:0;padding:0;overflow:hidden;background:#0b0f17;">
      <iframe src="${SERVER_URL}" style="width:100%;height:100%;border:none;" allow="clipboard-read; clipboard-write"></iframe>
    </body>
    </html>`;
  }

  getErrorHtml() {
    return `<!DOCTYPE html><html><body style="background:#0b0f17;color:#f87171;display:flex;align-items:center;justify-content:center;height:100vh;font-family:sans-serif;padding:20px;text-align:center;">
      <div>
        <div style="font-size:16px;font-weight:600;margin-bottom:8px;">服务启动失败</div>
        <div style="font-size:12px;color:#94a3b8;">请在终端中手动运行：<br><code>python novel_studio/shared/server.py --port ${SERVER_PORT}</code></div>
      </div>
    </body></html>`;
  }
}

function activate(context) {
  const studioRoot = path.resolve(context.extensionPath, '..');
  const provider = new StudioViewProvider(context, studioRoot);

  context.subscriptions.push(
    vscode.window.registerWebviewViewProvider('novelStudio.mainView', provider)
  );

  context.subscriptions.push(
    vscode.commands.registerCommand('novelStudio.openBrowser', () => {
      vscode.env.openExternal(vscode.Uri.parse(SERVER_URL));
    })
  );

  context.subscriptions.push(
    vscode.commands.registerCommand('novelStudio.restartServer', async () => {
      if (serverProcess) {
        serverProcess.kill();
        serverProcess = null;
      }
      await ensureServerRunning(studioRoot);
      vscode.window.showInformationMessage('Novel Studio 服务已重新启动！');
    })
  );

  console.log('[NovelStudio] 插件已激活');
}

function deactivate() {
  if (serverProcess) {
    serverProcess.kill();
    serverProcess = null;
  }
}

module.exports = {
  activate,
  deactivate
};
