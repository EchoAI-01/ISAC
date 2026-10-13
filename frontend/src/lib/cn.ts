/** 类名拼接工具 (条件类名)。 */
export type ClassValue = string | number | false | null | undefined;

export function cn(...values: ClassValue[]): string {
  return values.filter((v): v is string | number => Boolean(v) === true).join(" ");
}
