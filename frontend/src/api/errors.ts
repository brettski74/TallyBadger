function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

/** Best-effort message from FastAPI JSON error bodies (string detail or validation list). */
export function messageFromErrorBody(data: unknown): string | null {
  if (!isRecord(data)) {
    return null;
  }
  const detail = data.detail;
  if (typeof detail === "string") {
    return detail;
  }
  if (Array.isArray(detail)) {
    const parts = detail
      .map((item) => {
        if (isRecord(item) && typeof item.msg === "string") {
          return item.msg;
        }
        return null;
      })
      .filter(Boolean) as string[];
    if (parts.length > 0) {
      return parts.join("; ");
    }
  }
  return null;
}

export async function readApiErrorMessage(response: Response): Promise<string> {
  try {
    const data: unknown = await response.json();
    return messageFromErrorBody(data) ?? `Request failed (${response.status})`;
  } catch {
    return `Request failed (${response.status})`;
  }
}
