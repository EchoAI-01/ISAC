import { useMemo, useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";

import { errorMessage, isApiError } from "@/api/errors";
import { useAuth } from "@/auth/AuthProvider";
import { Button } from "@/components/Button";
import { Callout } from "@/components/Card";
import { TextField } from "@/components/Form";
import { useToast } from "@/components/Toast";

/** 与后端 `isac/control/setup.py::MIN_PASSWORD_LENGTH` 一致 (服务端仍会 422 复核)。 */
const MIN_PASSWORD_LENGTH = 8;

interface Requirement {
  label: string;
  met: boolean;
}

function requirements(password: string): Requirement[] {
  return [
    { label: `至少 ${MIN_PASSWORD_LENGTH} 位`, met: password.length >= MIN_PASSWORD_LENGTH },
    { label: "包含字母", met: /[A-Za-z]/.test(password) },
    { label: "包含数字或符号", met: /[^A-Za-z]/.test(password) },
    { label: "不是常见弱口令 (admin/password/123456…)", met: !/^(admin|password|123456|12345678|qwerty|isac)$/i.test(password) },
  ];
}

/**
 * 首登强制设密码向导 (F1, 对接 T3-backend)。
 *
 * 后端语义 (routes_setup.py + setup.py):
 * - 未配任何静态凭证且未设密码 → 全部 admin 端点 428 SETUP_REQUIRED, 仅 /health 与 /setup 可达;
 * - `POST /setup {password}` 以 PBKDF2-HMAC-SHA256 (20 万次) 哈希落盘, 密码本身随后成为有效 Bearer 凭据;
 * - 409 SETUP_ALREADY_DONE (已设置, 轮换走 CLI); 403 SETUP_NOT_ALLOWED (已配静态凭证);
 *   422 密码短于 8 位。
 */
export function SetupPage() {
  const { completeSetup, health, connectionError } = useAuth();
  const navigate = useNavigate();
  const toast = useToast();

  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [reveal, setReveal] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [acknowledged, setAcknowledged] = useState(false);

  const checks = useMemo(() => requirements(password), [password]);
  const allMet = checks.every((item) => item.met);
  const mismatch = confirm.length > 0 && confirm !== password;
  const canSubmit = allMet && !mismatch && acknowledged && !submitting;

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    if (!canSubmit) return;
    setError(null);
    setSubmitting(true);
    try {
      await completeSetup(password);
      toast.success("管理密码已设置", "已用该密码登录 (Bearer 内存轨); 控制面退出首登态。");
      setPassword("");
      setConfirm("");
      navigate("/", { replace: true });
    } catch (err) {
      if (isApiError(err)) {
        switch (err.code) {
          case "SETUP_ALREADY_DONE":
            setError("首登密码已设置过。轮换请在后端执行 `isac password reset` 后重新进入本向导。");
            break;
          case "SETUP_NOT_ALLOWED":
            setError("已配置 control.api_token / tokens[], setup 通道已关闭 —— 请回登录页用静态凭据登录。");
            break;
          default:
            setError(`${err.message} (${err.code})`);
        }
      } else {
        setError(errorMessage(err));
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="standalone-screen">
      <div className="standalone-card stack">
        <header className="stack stack--tight">
          <h1 className="page-header__title">首登设置</h1>
          <p className="small muted">
            控制面处于<strong>首登待设置态</strong>: 未配置任何静态凭证, 全部管理端点返回{" "}
            <code className="code-inline">428 SETUP_REQUIRED</code>, 仅 <code className="code-inline">/health</code> 与{" "}
            <code className="code-inline">/setup</code> 可达。
          </p>
        </header>

        <Callout tone="info" title="这一步在做什么">
          设置管理密码后, 密码经 PBKDF2-HMAC-SHA256 (20 万次迭代) 哈希落盘到{" "}
          <code className="code-inline">data/control/setup_state.json</code> (不落明文, 无硬编码默认密码),
          并立即成为有效的 Bearer 凭据。
        </Callout>

        {connectionError ? (
          <Callout tone="danger" title="无法连接控制面">
            {connectionError}
          </Callout>
        ) : null}

        <form onSubmit={onSubmit} className="stack" noValidate>
          <TextField
            label="管理密码"
            type={reveal ? "text" : "password"}
            value={password}
            autoComplete="new-password"
            autoFocus
            required
            minLength={MIN_PASSWORD_LENGTH}
            onChange={(event) => setPassword(event.target.value)}
            error={error ?? undefined}
            data-testid="setup-password"
            aria-describedby="setup-requirements"
          />

          <ul className="stack stack--tight small" id="setup-requirements" aria-label="密码要求">
            {checks.map((item) => (
              <li key={item.label} style={{ listStyle: "none" }}>
                <span aria-hidden="true">{item.met ? "✓ " : "○ "}</span>
                <span className={item.met ? undefined : "muted"}>{item.label}</span>
                <span className="sr-only">{item.met ? " (已满足)" : " (未满足)"}</span>
              </li>
            ))}
          </ul>

          <TextField
            label="确认密码"
            type={reveal ? "text" : "password"}
            value={confirm}
            autoComplete="new-password"
            required
            onChange={(event) => setConfirm(event.target.value)}
            error={mismatch ? "两次输入不一致" : undefined}
            data-testid="setup-password-confirm"
          />

          <label className="checkbox">
            <input
              type="checkbox"
              checked={acknowledged}
              onChange={(event) => setAcknowledged(event.target.checked)}
              data-testid="setup-ack"
            />
            <span>
              我已理解: 该密码是本控制面的管理凭据, 遗失需在服务端执行{" "}
              <code className="code-inline">isac password reset</code> 重置。
            </span>
          </label>

          <div className="row row--between">
            <label className="checkbox">
              <input type="checkbox" checked={reveal} onChange={(event) => setReveal(event.target.checked)} />
              <span>显示密码</span>
            </label>
            <Button type="submit" disabled={!canSubmit} loading={submitting} data-testid="setup-submit">
              设置密码并进入控制台
            </Button>
          </div>
        </form>

        <div className="small muted">
          若你已配置 <code className="code-inline">control.api_token</code> 或{" "}
          <code className="code-inline">control.tokens[]</code>, setup 通道会自动关闭 (403), 请改用 Token 登录。
          {health ? <span> · 当前 /health: {health.status}</span> : null}
        </div>
      </div>
    </div>
  );
}
