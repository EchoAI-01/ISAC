// ISAC WebUI 前端 - 调用 G1 Admin API
// 纯 Vanilla JS, 不依赖 Vue 构建工具链

const API_BASE = "/api/v1";

function getToken() {
    const token = document.getElementById("api-token").value.trim();
    if (!token) {
        showToast("请先输入 API Token", "error");
        return null;
    }
    return token;
}

function authHeaders() {
    const token = getToken();
    if (!token) return null;
    return { "Authorization": `Bearer ${token}`, "Content-Type": "application/json" };
}

async function apiCall(method, path, body) {
    const headers = authHeaders();
    if (!headers) return null;
    const opts = { method, headers };
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
    if (!getToken()) return;
    await Promise.all([refreshAgents(), refreshRules(), refreshLinks(), refreshAudit()]);
}

// 页面加载后自动刷新 (如果有保存的 token)
// K7: 用 sessionStorage 而非 localStorage, 标签页关闭即清除, 不长期持久化 Bearer Token。
// 生产场景 Bearer Token 应通过短期 Cookie + HttpOnly 或外置密码管理器提供, 这里仅为
// 开发态便利, 关闭浏览器不会留下凭据。
document.addEventListener("DOMContentLoaded", () => {
    const saved = sessionStorage.getItem("isac_token");
    if (saved) {
        document.getElementById("api-token").value = saved;
        refreshAll();
    }
});

document.getElementById("api-token").addEventListener("input", (e) => {
    sessionStorage.setItem("isac_token", e.target.value);
});
