import {
  useId,
  type InputHTMLAttributes,
  type ReactNode,
  type SelectHTMLAttributes,
  type TextareaHTMLAttributes,
} from "react";

import { cn } from "@/lib/cn";

export interface FieldProps {
  label: ReactNode;
  hint?: ReactNode;
  error?: ReactNode;
  required?: boolean;
  /** 控件 (自动注入 id/aria-*); 或直接传 children 由本组件包裹。 */
  children: ReactNode;
  className?: string;
  htmlFor?: string;
}

/** 表单字段容器: label + hint + error 的统一排版与 aria 关联。 */
export function Field({ label, hint, error, required, children, className, htmlFor }: FieldProps) {
  return (
    <div className={cn("field", className)}>
      <label className="field__label" htmlFor={htmlFor}>
        {label}
        {required ? (
          <span aria-hidden="true" className="muted">
            {" "}
            *
          </span>
        ) : null}
        {required ? <span className="sr-only"> (必填)</span> : null}
      </label>
      {children}
      {hint && !error ? <span className="field__hint">{hint}</span> : null}
      {error ? (
        <span className="field__error" role="alert">
          {error}
        </span>
      ) : null}
    </div>
  );
}

export interface TextFieldProps extends InputHTMLAttributes<HTMLInputElement> {
  label: ReactNode;
  hint?: ReactNode;
  error?: ReactNode;
  mono?: boolean;
}

/** 文本输入 (自动生成 id 并关联 label / aria-describedby / aria-invalid)。 */
export function TextField({ label, hint, error, mono, className, id, ...rest }: TextFieldProps) {
  const autoId = useId();
  const inputId = id ?? autoId;
  const hintId = hint ? `${inputId}-hint` : undefined;
  const errorId = error ? `${inputId}-error` : undefined;
  return (
    <Field label={label} htmlFor={inputId} required={rest.required} error={error} hint={hint}>
      <input
        id={inputId}
        className={cn("input", mono && "input--mono", className)}
        aria-invalid={error ? true : undefined}
        aria-describedby={[hintId, errorId].filter(Boolean).join(" ") || undefined}
        {...rest}
      />
    </Field>
  );
}

export interface TextAreaProps extends TextareaHTMLAttributes<HTMLTextAreaElement> {
  label: ReactNode;
  hint?: ReactNode;
  error?: ReactNode;
  mono?: boolean;
}

export function TextArea({ label, hint, error, mono, className, id, ...rest }: TextAreaProps) {
  const autoId = useId();
  const inputId = id ?? autoId;
  const hintId = hint ? `${inputId}-hint` : undefined;
  const errorId = error ? `${inputId}-error` : undefined;
  return (
    <Field label={label} htmlFor={inputId} required={rest.required} error={error} hint={hint}>
      <textarea
        id={inputId}
        className={cn("textarea", mono && "textarea--mono", className)}
        aria-invalid={error ? true : undefined}
        aria-describedby={[hintId, errorId].filter(Boolean).join(" ") || undefined}
        {...rest}
      />
    </Field>
  );
}

export interface SelectFieldProps extends SelectHTMLAttributes<HTMLSelectElement> {
  label: ReactNode;
  hint?: ReactNode;
  error?: ReactNode;
  options: Array<{ value: string; label: ReactNode; disabled?: boolean }>;
}

export function SelectField({ label, hint, error, options, className, id, ...rest }: SelectFieldProps) {
  const autoId = useId();
  const inputId = id ?? autoId;
  return (
    <Field label={label} htmlFor={inputId} required={rest.required} error={error} hint={hint}>
      <select id={inputId} className={cn("select", className)} {...rest}>
        {options.map((option) => (
          <option key={option.value} value={option.value} disabled={option.disabled}>
            {option.label}
          </option>
        ))}
      </select>
    </Field>
  );
}

export interface CheckboxFieldProps extends InputHTMLAttributes<HTMLInputElement> {
  label: ReactNode;
  hint?: ReactNode;
}

export function CheckboxField({ label, hint, className, id, ...rest }: CheckboxFieldProps) {
  const autoId = useId();
  const inputId = id ?? autoId;
  return (
    <label className={cn("checkbox", className)} htmlFor={inputId}>
      <input id={inputId} type="checkbox" {...rest} />
      <span>
        {label}
        {hint ? <span className="field__hint"> {hint}</span> : null}
      </span>
    </label>
  );
}

/** 工具条里的紧凑筛选控件 (无 Field 包装, label 用小标题样式)。 */
export function InlineFilter({ label, children }: { label: ReactNode; children: ReactNode }) {
  const labelId = useId();
  return (
    <div className="toolbar__group">
      <span className="toolbar__label" id={labelId}>
        {label}
      </span>
      {children}
    </div>
  );
}
