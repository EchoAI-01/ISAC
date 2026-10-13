import { useState, type FormEvent } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";

import { errorMessage } from "@/api/errors";
import { useAuth } from "@/auth/AuthProvider";
import { Button } from "@/components/Button";
import { Callout } from "@/components/Card";
import { TextField } from "@/components/Form";
import { useToast } from "@/components/Toast";

interface LocationState {
  from?: { pathname?: string; search?: string };
}

function targetAfterLogin(state: unknown): string {
  const from = (state as LocationState | null)?.from;
  if (!from?.pathname) return "/";
  return `${from.pathname}${from.search ?? ""}`;
}

/**
 * 登录页 (F1)。
 *
 * 凭据轨说明:
 * - 配置了 `control.api_token` / `control.tokens[]` → 后端挂载 `/auth/session`,
 *   登录会把一次性凭据换成 HttpOnly 会话 Cookie + CSRF Cookie, 浏览器不留裸 Token;
 * - 纯 setup 密码部署 (无静态凭证) → `/auth/session` 返回 404
 *   SESSION_AUTH_DISABLED, 自动降级 Bearer 轨 (Token 只在内存, 刷新需重登)。
 */
export function LoginPage() {
  const { login, connectionError, health, status } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const toast = useToast();

  const [credential, setCredential] = useState("");
  const [reveal, setReveal] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    if (submitting) return;
    setError(null);
    setSubmitting(true);
    try {
      await login(credential);
      setCredential("");
      toast.success("登录成功");
      navigate(targetAfterLogin(location.state), { replace: true });
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="standalone-screen">
      <div className="standalone-card stack">
        <header className="stack stack--tight">
          <h1 className="page-header__title">登录 ISAC 控制台</h1>
          <p className="small muted">
            使用 <code className="code-inline">control.api_token</code>、
            <code className="code-inline">control.tokens[]</code> 里的某个 Token, 或首登设置的管理密码。
          </p>
        </header>

        {connectionError ? (
          <Callout tone="danger" title="无法连接控制面">
            <div>{connectionError}</div>
            <div className="small" style={{ marginTop: "var(--space-2)" }}>
              确认后端已启动 (<code className="code-inline">uv run python -m isac</code>, 默认 127.0.0.1:8765),
              或检查 Vite 代理 <code className="code-inline">ISAC_API_TARGET</code> / 后端{" "}
              <code className="code-inline">control.cors.origins</code>。
            </div>
          </Callout>
        ) : null}

        {status === "setup_required" || health?.setup_required ? (
          <Callout tone="warning" title="控制面处于首登待设置态">
            全部管理端点返回 428 SETUP_REQUIRED, 需要先设置管理密码。
            <div style={{ marginTop: "var(--space-2)" }}>
              <Link to="/setup">进入首登设置向导</Link>
            </div>
          </Callout>
        ) : null}

        <form onSubmit={onSubmit} className="stack" noValidate>
          <TextField
            label="Token 或管理密码"
            type={reveal ? "text" : "password"}
            value={credential}
            autoComplete="current-password"
            autoFocus
            required
            onChange={(event) => setCredential(event.target.value)}
            error={error ?? undefined}
            hint="凭据不会被写入 localStorage; 会话 Cookie 轨下浏览器只保存 HttpOnly Cookie。"
            data-testid="login-credential"
          />
          <div className="row row--between">
            <label className="checkbox">
              <input type="checkbox" checked={reveal} onChange={(event) => setReveal(event.target.checked)} />
              <span>显示内容</span>
            </label>
            <Button type="submit" loading={submitting} data-testid="login-submit">
              登录
            </Button>
          </div>
        </form>

        <div className="small muted stack stack--tight">
          <div>
            健康状态:{" "}
            <strong data-testid="login-health">
              {health ? `${health.status} · agents ${health.subsystems.agents.running}/${health.subsystems.agents.total}` : "未知"}
            </strong>
          </div>
          <div>
            忘记密码 / 需要轮换: 在后端执行 <code className="code-inline">isac password reset</code> 回到首登态。
          </div>
        </div>
      </div>
    </div>
  );
}
