// ISAC WebUI 前端 - 调用 G1 Admin API
// 纯 Vanilla JS, 不依赖 Vue 构建工具链

const API_BASE = "/api/v1";

// Fix-17: 读输入框里的 Bearer Token, 仅用于 login()/legacy fallback, 不再是
// 每次请求都要读、和 sessionStorage 联动的凭据来源 (见下方 login()/apiCall())。
function getToken() {
    const token = document.getElementById("api-token").value.trim();
    if (!token) {
        showToast("请先输入 API Token", "error");
        return null;
    }
    return token;
}

// Fix-17: 从 document.cookie 读取 csrf_token (非 HttpOnly, 前端本来就应该能读到,
// 用于按 CONTROL_PLANE_SPEC.md §8.2 第 5 条的双提交校验回填请求头)。
function getCsrfTokenFromCookie() {
    const match = document.cookie.match(/(?:^|;\s*)csrf_token=([^;]+)/);
    return match ? decodeURIComponent(match[1]) : null;
}

let usingLegacyBearerAuth = false;

// Fix-17: 用一次性 Bearer Token 换取 HttpOnly 会话 Cookie + CSRF Cookie
// (CONTROL_PLANE_SPEC.md §8.2 第 5 条), 不再把裸 Token 长期存进 sessionStorage。
// /auth/session 404 (会话 Cookie 机制未启用, 如 session_auth_enabled=False)
// 时降级到旧的纯 Bearer Header 方式, 保持向后兼容。
async function login() {
    const token = getToken();
    if (!token) return;
    try {
        const res = await fetch(API_BASE + "/auth/session", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ token }),
        });
        if (res.status === 404) {
            usingLegacyBearerAuth = true;
            sessionStorage.setItem("isac_token", token);
            showToast("会话 Cookie 机制未启用, 使用 Bearer Header 兼容模式", "success");
        } else if (res.ok) {
            usingLegacyBearerAuth = false;
            sessionStorage.removeItem("isac_token");
            showToast("登录成功", "success");
        } else {
            showToast("登录失败: Token 无效", "error");
            return;
        }
    } catch (err) {
        showToast(`网络错误: ${err.message}`, "error");
        return;
    }
    refreshAll();
}

function authHeaders(method) {
    const headers = { "Content-Type": "application/json" };
    // Fix-17: 会话 Cookie 认证下不需要 (也读不到 HttpOnly 的) Bearer Token,
    // 只有降级到 legacy 模式时才手动带 Authorization 头。
    if (usingLegacyBearerAuth) {
        const token = getToken();
        if (!token) return null;
        headers["Authorization"] = `Bearer ${token}`;
    }
    // Fix-17: 写方法且走会话 Cookie 认证时, 按双提交约定回填 X-CSRF-Token
    // (安全方法 GET/HEAD/OPTIONS 不需要, 与 CSRFProtectionMiddleware 的校验范围对应)。
    if (!usingLegacyBearerAuth && method && !["GET", "HEAD", "OPTIONS"].includes(method)) {
        const csrf = getCsrfTokenFromCookie();
        if (csrf) headers["X-CSRF-Token"] = csrf;
    }
    return headers;
}

async function apiCall(method, path, body) {
    const headers = authHeaders(method);
    if (!headers) return null;
    // credentials: "same-origin" 让浏览器把 HttpOnly 会话 Cookie 自动带上
    // (fetch 默认值已经是 same-origin, 这里显式写出便于阅读)。
    const opts = { method, headers, credentials: "same-origin" };
    if (body !== undefined) opts.body = JSON.stringify(body);
    try {
        const res = await fetch(API_BASE + path, opts);
        if (res.status === 204) return {};
        if (res.status >= 400) {
            const err = await res.json().catch(() => ({ detail: res.statusText }));
            showToast(`${path} 失败: ${err.detail?.message || err.detail || res.status}`, "error");
            return null;
        }
        return await res.json();
    } catch (err) {
        showToast(`网络错误: ${err.message}`, "error");
        return null;
    }
}

function showToast(msg, type = "success") {
    const toast = document.createElement("div");
    toast.className = `toast ${type === "error" ? "error" : ""}`;
    toast.textContent = msg;
    document.body.appendChild(toast);
    setTimeout(() => {
        toast.classList.add("fade-out");
        setTimeout(() => toast.remove(), 300);
    }, 2000);
}

function clearTableBody(id) {
    document.querySelector(`#${id} tbody`).innerHTML = "";
}

function addRow(tableId, cells, actions = null) {
    const tbody = document.querySelector(`#${tableId} tbody`);
    const tr = document.createElement("tr");
    cells.forEach(text => {
        const td = document.createElement("td");
        td.textContent = text === null || text === undefined ? "" : String(text);
        tr.appendChild(td);
    });
    if (actions) {
        const td = document.createElement("td");
        td.className = "row-actions";
        actions(td);
        tr.appendChild(td);
    }
    tbody.appendChild(tr);
}

async function refreshAgents() {
    const agents = await apiCall("GET", "/agents");
    if (agents === null) return;
    clearTableBody("agents-table");
    if (agents.length === 0) {
        addRow("agents-table", ["(无 Agent)", "", "", ""]);
        return;
    }
    agents.forEach(a => {
        addRow("agents-table", [a.agent_id, "", a.status], (td) => {
            if (a.status === "stopped") {
                const btn = document.createElement("button");
                btn.textContent = "启动";
                btn.onclick = () => startAgent(a.agent_id);
                td.appendChild(btn);
            } else if (a.status === "running") {
                const btn = document.createElement("button");
                btn.textContent = "停止";
                btn.className = "secondary";
                btn.onclick = () => stopAgent(a.agent_id);
                td.appendChild(btn);
            }
            const del = document.createElement("button");
            del.textContent = "删除";
            del.className = "danger";
            del.onclick = () => destroyAgent(a.agent_id);
            td.appendChild(del);
        });
    });
}

async function createAgent() {
    const agent_id = document.getElementById("new-agent-id").value.trim();
    const display_name = document.getElementById("new-agent-name").value.trim();
    if (!agent_id) { showToast("请输入 agent_id", "error"); return; }
    const result = await apiCall("POST", "/agents", { agent_id, display_name });
    if (result) {
        showToast(`Agent ${agent_id} 已创建`);
        await refreshAgents();
    }
}

async function startAgent(id) {
    if (await apiCall("POST", `/agents/${id}/start`)) {
        showToast(`Agent ${id} 已启动`);
        await refreshAgents();
    }
}

async function stopAgent(id) {
    if (await apiCall("POST", `/agents/${id}/stop`)) {
        showToast(`Agent ${id} 已停止`);
        await refreshAgents();
    }
}

async function destroyAgent(id) {
    if (!confirm(`确认删除 Agent ${id}?`)) return;
    if (await apiCall("DELETE", `/agents/${id}`)) {
        showToast(`Agent ${id} 已删除`);
        await refreshAgents();
    }
}

async function refreshRules() {
    const rules = await apiCall("GET", "/routing/rules");
    if (!rules) return;
    clearTableBody("rules-table");
    if (rules.bindings.length === 0) {
        addRow("rules-table", ["(无绑定)", "", "", ""]);
        return;
    }
    rules.bindings.forEach(b => {
        addRow("rules-table", [b.platform, b.agent_id, b.group_id, b.user_id]);
    });
}

async function updateRules() {
    const platform = document.getElementById("new-binding-platform").value.trim();
    const agent_id = document.getElementById("new-binding-agent").value.trim();
    const isDefault = document.getElementById("new-binding-default").checked;
    if (!platform || !agent_id) { showToast("platform 和 agent_id 必填", "error"); return; }
    const body = {
        bindings: isDefault ? [] : [{ platform, agent_id, group_id: null, user_id: null }],
        default_agents: isDefault ? { [platform]: agent_id } : {},
    };
    if (await apiCall("PUT", "/routing/rules", body)) {
        showToast("路由规则已更新");
        await refreshRules();
    }
}

async function refreshLinks() {
    const links = await apiCall("GET", "/links");
    if (!links) return;
    clearTableBody("links-table");
    if (links.length === 0) {
        addRow("links-table", ["(无 Link)", "", "", "", ""]);
        return;
    }
    links.forEach(l => {
        addRow("links-table", [l.from_agent, l.to_agent, l.direction, l.enabled], (td) => {
            const btn = document.createElement("button");
            btn.textContent = "删除";
            btn.className = "danger";
            btn.onclick = () => removeLink(l.from_agent, l.to_agent);
            td.appendChild(btn);
        });
    });
}

async function addLink() {
    const from = document.getElementById("new-link-from").value.trim();
    const to = document.getElementById("new-link-to").value.trim();
    const direction = document.getElementById("new-link-direction").value;
    if (!from || !to) { showToast("from_agent 和 to_agent 必填", "error"); return; }
    if (await apiCall("POST", "/links", { from_agent: from, to_agent: to, direction })) {
        showToast("Link 已添加");
        await refreshLinks();
    }
}

async function removeLink(from, to) {
    if (!confirm(`删除 Link ${from} → ${to}?`)) return;
    if (await apiCall("DELETE", `/links?from_agent=${from}&to_agent=${to}`)) {
        showToast("Link 已删除");
        await refreshLinks();
    }
}

async function refreshAudit() {
    const entries = await apiCall("GET", "/audit?limit=20");
    if (!entries) return;
    clearTableBody("audit-table");
    if (entries.length === 0) {
        addRow("audit-table", ["(无审计日志)", "", "", "", "", ""]);
        return;
    }
    entries.forEach(e => {
        addRow("audit-table", [
            new Date(e.timestamp * 1000).toLocaleString(),
            e.method, e.path, e.action, e.target || "", e.status_code,
        ]);
    });
}

async function refreshAll() {
    // Fix-17: 会话 Cookie 模式下凭据在 Cookie 里, 不需要 (也不应该要求) 输入框
    // 有值; 只有降级到 legacy Bearer Header 模式时才需要输入框里的 Token。
    if (usingLegacyBearerAuth && !getToken()) return;
    await Promise.all([refreshAgents(), refreshRules(), refreshLinks(), refreshAudit(), refreshDashboard()]);
}

// J3-5: SPA 导航 (10 域, 当前页 active)
function navigate(page) {
    document.querySelectorAll(".page").forEach(el => el.classList.remove("active"));
    document.querySelectorAll("nav.sidebar a").forEach(el => el.classList.remove("active"));
    const pageEl = document.getElementById(`page-${page}`);
    if (pageEl) pageEl.classList.add("active");
    const navEl = document.querySelector(`nav.sidebar a[data-page="${page}"]`);
    if (navEl) navEl.classList.add("active");
    // 进入页面时刷新对应数据
    if (page === "dashboard") refreshDashboard();
    if (page === "agents") refreshAgents();
    if (page === "channels") { refreshRules(); refreshLinks(); }
    if (page === "logs") refreshAudit();
    if (page === "providers") refreshProviders();
    if (page === "usage") refreshUsage();
    if (page === "extensions") refreshExtensions();
    if (page === "memory") refreshMemory();
    if (page === "sessions") refreshSessions();
    if (page === "system") refreshSystem();
}

// J3-5: Dashboard 数据加载
async function refreshDashboard() {
    // 并发加载 agents + sessions + audit + health
    const [agents, sessions, audit, health] = await Promise.all([
        apiCall("GET", "/agents"),
        apiCall("GET", "/sessions").catch(() => ({ sessions: [] })),
        apiCall("GET", "/audit?limit=10"),
        apiCall("GET", "/health").catch(() => ({ status: "unknown" })),
    ]);
    if (agents === null) return;  // token 错误
    // 统计
    const running = (agents || []).filter(a => a.status === "running").length;
    document.getElementById("stat-agents").textContent = running;
    document.getElementById("stat-sessions").textContent = (sessions?.sessions || []).length;
    document.getElementById("stat-messages").textContent = "-";  // TODO J3-6 接入 metrics
    document.getElementById("stat-health").textContent = health?.status || "-";
    // 近期审计
    if (document.querySelector("#dashboard-audit-table tbody")) {
        clearTableBody("dashboard-audit-table");
        const recent = (audit || []).slice(0, 10);
        recent.forEach(e => {
            const ts = e.timestamp ? new Date(e.timestamp * 1000).toLocaleString() : "";
            // Fix-16: 审计字段 (action/target) 来自用户可控输入 (如 InterAgentLink
            // 的 from_agent/to_agent), 必须用 textContent 逐格赋值, 不能用
            // innerHTML 字符串拼接 (会执行嵌入的 <script>, 构成存储型 XSS)。
            addRow("dashboard-audit-table", [ts, e.action || "", e.target || ""]);
        });
        if (recent.length === 0) {
            addRow("dashboard-audit-table", ["暂无审计记录", "", ""]);
        }
    }
}

// J3-6: Providers / Models / Artifacts
async function refreshProviders() {
    const [providers, models, artifacts] = await Promise.all([
        apiCall("GET", "/providers"),
        apiCall("GET", "/providers/models"),
        apiCall("GET", "/artifacts").catch(() => ({ artifacts: [] })),
    ]);
    if (providers === null) return;
    // providers 表
    clearTableBody("providers-table");
    (providers?.providers || []).forEach(p => {
        addRow("providers-table", [p.provider_id, p.model_id], (td) => {
            const btn = document.createElement("button");
            btn.textContent = "测试";
            btn.className = "secondary";
            btn.onclick = () => testProvider(p.provider_id, p.model_id);
            td.appendChild(btn);
        });
    });
    if ((providers?.providers || []).length === 0) {
        addRow("providers-table", ["(无 Provider)", ""]);
    }
    // models 表
    clearTableBody("models-table");
    (models?.models || []).forEach(m => {
        addRow("models-table", [
            m.provider_id, m.model_id,
            (m.operations || []).join(","),
            (m.modalities_in || []).join(","),
            (m.modalities_out || []).join(","),
            m.cost_tier, m.latency_tier,
        ]);
    });
    if ((models?.models || []).length === 0) {
        addRow("models-table", ["(无模型)", "", "", "", "", "", ""]);
    }
    // artifacts 表
    clearTableBody("artifacts-table");
    (artifacts?.artifacts || []).forEach(a => {
        addRow("artifacts-table", [
            a.artifact_id?.slice(0, 12),
            a.kind, a.mime_type, a.size_bytes,
            a.created_at ? new Date(a.created_at * 1000).toLocaleString() : "",
        ], (td) => {
            const btn = document.createElement("button");
            btn.textContent = "删除";
            btn.className = "danger";
            btn.onclick = () => deleteArtifact(a.artifact_id);
            td.appendChild(btn);
        });
    });
    if ((artifacts?.artifacts || []).length === 0) {
        addRow("artifacts-table", ["(无制品)", "", "", "", "", ""]);
    }
}

async function testProvider(providerId, modelId) {
    const result = await apiCall("POST", `/providers/${providerId}/test?model_id=${encodeURIComponent(modelId)}`);
    if (result) showToast(`Provider ${providerId} 测试通过`);
}

async function deleteArtifact(artifactId) {
    if (!confirm(`确认删除制品 ${artifactId.slice(0, 12)}?`)) return;
    if (await apiCall("DELETE", `/artifacts/${artifactId}`)) {
        showToast("制品已删除");
        await refreshProviders();
    }
}

// J3-6: Usage / 成本
async function refreshUsage() {
    const groupBy = document.getElementById("usage-group-by")?.value || "provider";
    const [summary, events] = await Promise.all([
        apiCall("GET", `/usage/models/summary?group_by=${groupBy}`).catch(() => []),
        apiCall("GET", "/usage/models/events?limit=50").catch(() => ({ events: [] })),
    ]);
    if (summary === null) return;
    // summary 表
    clearTableBody("usage-summary-table");
    (summary || []).forEach(s => {
        const groupKey = s[groupBy] || s.provider || s.model || "unknown";
        addRow("usage-summary-table", [
            groupKey, s.request_count || 0,
            s.prompt_tokens || 0, s.completion_tokens || 0, s.total_tokens || 0,
            s.estimated_cost_sum || "-",
        ]);
    });
    if ((summary || []).length === 0) {
        addRow("usage-summary-table", ["(无数据)", "", "", "", "", ""]);
    }
    // events 表
    clearTableBody("usage-events-table");
    (events?.events || []).forEach(e => {
        addRow("usage-events-table", [
            e.created_at ? new Date(e.created_at * 1000).toLocaleString() : "",
            e.provider, e.model, e.modality, e.operation,
            e.total_tokens || 0, e.estimated_cost || "-", e.status,
        ]);
    });
    if ((events?.events || []).length === 0) {
        addRow("usage-events-table", ["(无事件)", "", "", "", "", "", "", ""]);
    }
}

// J3-6: Extensions (插件 + SubAgent)
async function refreshExtensions() {
    // 插件列表 (无专门 API, 暂用 /agents 占位; 实际插件 API 待 J3 后续)
    clearTableBody("plugins-table");
    addRow("plugins-table", ["(插件 API 待实现)", "", ""]);
    // SubAgent 任务
    const runs = await apiCall("GET", "/agents/_/subagent-runs").catch(() => []);
    if (runs === null) return;
    clearTableBody("subagent-runs-table");
    (runs || []).forEach(r => {
        addRow("subagent-runs-table", [
            r.task_id?.slice(0, 12), r.status,
            r.started_at ? new Date(r.started_at * 1000).toLocaleString() : "",
            r.finished_at ? new Date(r.finished_at * 1000).toLocaleString() : "",
            (r.result_summary || "").slice(0, 60),
        ]);
    });
    if ((runs || []).length === 0) {
        addRow("subagent-runs-table", ["(无 SubAgent 任务)", "", "", "", ""]);
    }
}

// 页面加载后自动恢复会话。
// Fix-17: 会话 Cookie 是 HttpOnly, 前端读不到, 用同时签发的非 HttpOnly
// csrf_token Cookie 作为"是否已登录"的判断依据 (存在即尝试刷新; 如果服务端已
// 重启/Cookie 已过期, 请求会 401, 用户看到错误提示后重新登录即可)。legacy
// fallback (会话 Cookie 机制未启用时降级到的纯 Bearer Header 模式) 仍用
// sessionStorage 记住 Token, 标签页关闭即清除, 不长期持久化。
document.addEventListener("DOMContentLoaded", () => {
    if (getCsrfTokenFromCookie()) {
        usingLegacyBearerAuth = false;
        refreshAll();
        return;
    }
    const saved = sessionStorage.getItem("isac_token");
    if (saved) {
        usingLegacyBearerAuth = true;
        document.getElementById("api-token").value = saved;
        refreshAll();
    }
});

// J3-7: Memory 页
async function refreshMemory() {
    const agentId = document.getElementById("memory-agent-id")?.value.trim() || "default";
    const [episodes, profiles, jargon] = await Promise.all([
        apiCall("GET", `/memory/${encodeURIComponent(agentId)}/episodes?limit=50`).catch(() => ({ episodes: [] })),
        apiCall("GET", `/memory/${encodeURIComponent(agentId)}/profiles`).catch(() => ({ profiles: [] })),
        apiCall("GET", `/memory/${encodeURIComponent(agentId)}/jargon`).catch(() => ({ jargon: [] })),
    ]);
    if (episodes === null) return;
    clearTableBody("memory-episodes-table");
    (episodes?.episodes || []).forEach(e => {
        addRow("memory-episodes-table", [
            (e.id || "").slice(0, 12), (e.session_id || "").slice(0, 12),
            (e.content || "").slice(0, 60), e.importance || "",
            e.created_at ? new Date(e.created_at * 1000).toLocaleString() : "",
        ]);
    });
    if ((episodes?.episodes || []).length === 0) {
        addRow("memory-episodes-table", ["(无 episode)", "", "", "", ""]);
    }
    clearTableBody("memory-profiles-table");
    (profiles?.profiles || []).forEach(p => {
        addRow("memory-profiles-table", [
            (p.person_id || "").slice(0, 12), p.name,
            p.relationship_depth, p.interaction_count,
            p.last_seen ? new Date(p.last_seen * 1000).toLocaleString() : "",
        ]);
    });
    if ((profiles?.profiles || []).length === 0) {
        addRow("memory-profiles-table", ["(无画像)", "", "", "", ""]);
    }
    clearTableBody("memory-jargon-table");
    (jargon?.jargon || []).forEach(j => {
        addRow("memory-jargon-table", [j.word, (j.meaning || "").slice(0, 60), j.usage_count]);
    });
    if ((jargon?.jargon || []).length === 0) {
        addRow("memory-jargon-table", ["(无术语)", "", ""]);
    }
}

// J3-7: Sessions 页
async function refreshSessions() {
    const sessions = await apiCall("GET", "/sessions");
    if (sessions === null) return;
    clearTableBody("sessions-table");
    (sessions?.sessions || []).forEach(s => {
        addRow("sessions-table", [
            (s.session_id || "").slice(0, 12), s.agent_id, s.user_id,
            s.platform, s.state || "active",
            s.last_active ? new Date(s.last_active * 1000).toLocaleString() : "",
        ]);
    });
    if ((sessions?.sessions || []).length === 0) {
        addRow("sessions-table", ["(无活跃会话)", "", "", "", "", ""]);
    }
}

async function refreshSessionMessages() {
    const sid = document.getElementById("session-messages-id")?.value.trim();
    if (!sid) { showToast("请输入 session_id", "error"); return; }
    const result = await apiCall("GET", `/sessions/${encodeURIComponent(sid)}/messages?limit=100`);
    if (result === null) return;
    clearTableBody("session-messages-table");
    (result?.messages || []).forEach(m => {
        addRow("session-messages-table", [
            (m.memory_id || "").slice(0, 12), (m.content || "").slice(0, 80),
            m.created_at ? new Date(m.created_at * 1000).toLocaleString() : "",
        ]);
    });
    if ((result?.messages || []).length === 0) {
        addRow("session-messages-table", ["(无消息)", "", ""]);
    }
}

// J3-7: System 页 + 配置编辑事务
async function refreshSystem() {
    const [health, metrics] = await Promise.all([
        apiCall("GET", "/health").catch(() => ({ status: "unknown" })),
        apiCall("GET", "/metrics").catch(() => null),
    ]);
    if (health === null) return;
    document.getElementById("sys-version").textContent = "1.0.0";
    document.getElementById("sys-health").textContent = health?.status || "-";
    document.getElementById("sys-metrics").textContent = metrics ? "ok" : "-";
}

// 配置编辑事务
let _loadedConfig = null;  // 缓存加载的配置, 供 diff/patch 使用

async function loadConfigForEdit() {
    const agentId = document.getElementById("config-edit-agent-id")?.value.trim();
    if (!agentId) { showToast("请输入 agent_id", "error"); return; }
    // GET /agents/{id} 当前只返回 agent_id + status; 需要从 config 文件读
    // 这里简化: 直接构造一个示例 config (实际应从 /agents/{id}/config 读取, 待 J3 后续)
    const agent = await apiCall("GET", `/agents/${encodeURIComponent(agentId)}`);
    if (agent === null) return;
    _loadedConfig = { agent_id: agentId, display_name: agentId, enabled: true, revision: 1 };
    document.getElementById("config-revision").value = _loadedConfig.revision;
    document.getElementById("config-new-name").value = _loadedConfig.display_name;
    showToast("配置已加载");
}

async function validateConfig() {
    const newName = document.getElementById("config-new-name")?.value.trim();
    if (!newName) { showToast("请输入 display_name", "error"); return; }
    const candidate = { agent_id: _loadedConfig?.agent_id || "x", display_name: newName, enabled: true };
    const result = await apiCall("POST", "/config/validate", candidate);
    if (result === null) return;
    if (result.valid) {
        showToast("校验通过");
    } else {
        showToast(`校验失败: ${result.errors.join("; ")}`, "error");
    }
}

async function diffConfig() {
    const newName = document.getElementById("config-new-name")?.value.trim();
    if (!_loadedConfig) { showToast("请先加载配置", "error"); return; }
    const before = { ..._loadedConfig };
    const after = { ..._loadedConfig, display_name: newName };
    const result = await apiCall("POST", "/config/diff", { before, after });
    if (result === null) return;
    const out = document.getElementById("config-diff-output");
    out.style.display = "block";
    out.textContent = JSON.stringify(result.changes, null, 2);
    showToast(`Diff: ${result.changes.length} 个字段变更`);
}

async function patchConfig() {
    const newName = document.getElementById("config-new-name")?.value.trim();
    const agentId = _loadedConfig?.agent_id;
    if (!agentId || !newName) { showToast("请先加载配置并填写新值", "error"); return; }
    if (!confirm(`确认 PATCH ${agentId}: display_name → ${newName}?`)) return;
    // If-Match 用当前 revision (乐观锁)
    const rev = _loadedConfig.revision;
    const result = await apiCall("PATCH", `/agents/${encodeURIComponent(agentId)}?if_match=${rev}`, { display_name: newName });
    if (result === null) return;
    document.getElementById("config-revision").value = result.revision;
    _loadedConfig.revision = result.revision;
    _loadedConfig.display_name = newName;
    showToast(`配置已更新, 新 revision=${result.revision}`);
}
