import type {
  ChartRange,
  Check,
  Incident,
  Monitor,
  MonitorDetail,
  MonitorInput,
  MonitorPatch,
  ResponseTimes,
} from "./types";

/**
 * Error thrown for any failed API call.
 * - status 0: the API could not be reached at all (network error).
 * - fieldErrors: FastAPI 422 details mapped to form fields, e.g. { url: "Private or local ..." }.
 */
export class ApiError extends Error {
  readonly status: number;
  readonly fieldErrors: Record<string, string>;

  constructor(status: number, message: string, fieldErrors: Record<string, string> = {}) {
    super(message);
    this.status = status;
    this.fieldErrors = fieldErrors;
  }

  static fromResponse(status: number, body: unknown): ApiError {
    const detail = (body as { detail?: unknown } | null)?.detail;
    if (typeof detail === "string") return new ApiError(status, detail);
    if (Array.isArray(detail)) {
      // [{ loc: ["body", "url"], msg: "..." }, ...]
      const fieldErrors: Record<string, string> = {};
      for (const item of detail as { loc?: unknown[]; msg?: string }[]) {
        const field = item.loc?.filter((part) => part !== "body").join(".") || "form";
        fieldErrors[field] ??= item.msg ?? "Invalid value";
      }
      return new ApiError(status, Object.values(fieldErrors)[0] ?? "Invalid request", fieldErrors);
    }
    return new ApiError(status, `Request failed (${status})`);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`/api${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...init?.headers },
    });
  } catch {
    throw new ApiError(0, "Cannot reach the API. Is the backend running?");
  }
  if (response.status === 204) return undefined as T;
  const body: unknown = await response.json().catch(() => null);
  if (!response.ok) throw ApiError.fromResponse(response.status, body);
  return body as T;
}

const json = (data: unknown) => JSON.stringify(data);

export const api = {
  listMonitors: () => request<Monitor[]>("/monitors"),
  getMonitor: (id: number) => request<MonitorDetail>(`/monitors/${id}`),
  createMonitor: (input: MonitorInput) => request<Monitor>("/monitors", { method: "POST", body: json(input) }),
  updateMonitor: (id: number, patch: MonitorPatch) =>
    request<Monitor>(`/monitors/${id}`, { method: "PATCH", body: json(patch) }),
  deleteMonitor: (id: number) => request<void>(`/monitors/${id}`, { method: "DELETE" }),

  listChecks: (id: number, params: { limit?: number; before?: string } = {}) => {
    const query = new URLSearchParams();
    if (params.limit) query.set("limit", String(params.limit));
    if (params.before) query.set("before", params.before);
    return request<Check[]>(`/monitors/${id}/checks?${query}`);
  },
  responseTimes: (id: number, range: ChartRange) =>
    request<ResponseTimes>(`/monitors/${id}/response-times?range=${range}`),
  listIncidents: (id: number, limit = 20) => request<Incident[]>(`/monitors/${id}/incidents?limit=${limit}`),
};
