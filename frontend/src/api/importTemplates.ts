import { getApiBase } from "./baseUrl";
import { ApiHttpError, readApiErrorMessage } from "./errors";

export { ApiHttpError };

export type ImportColumnDataType = "string" | "numeric" | "date" | "datetime";

export interface ImportTemplateColumn {
  attribute_name: string | null;
  data_type: ImportColumnDataType;
  date_format: string | null;
}

export interface ImportTemplateSummary {
  id: number;
  name: string;
  updated_at: string;
}

export type ImportTemplateNormalBalance = "debit" | "credit";

export interface ImportTemplate extends ImportTemplateSummary {
  has_header_row: boolean;
  columns: ImportTemplateColumn[];
  cel_rule_set_id: number | null;
  default_import_account_id: number | null;
  default_import_normal_balance: ImportTemplateNormalBalance | null;
  created_at: string;
  updated_at: string;
}

export interface SaveImportTemplatePayload {
  name: string;
  has_header_row: boolean;
  columns: ImportTemplateColumn[];
  cel_rule_set_id: number | null;
  default_import_account_id?: number | null;
  default_import_normal_balance?: ImportTemplateNormalBalance | null;
}

export interface CsvImportExecutePayload {
  csv_text: string;
  has_header_row: boolean;
  columns: ImportTemplateColumn[];
  cel_rule_set_id: number | null;
  default_import_account_id?: number | null;
  default_import_normal_balance?: ImportTemplateNormalBalance | null;
}

/** One `debug(x)` record from CEL (same shape as optional `entries[].debug` on success). */
export interface CsvImportCelDebugEvent {
  rule: string;
  value: unknown;
  row_number?: number;
}

export interface CsvImportRowError {
  row_number: number;
  errors: string[];
  /** Present when CEL ran and `debug()` was used — same as for a successful `entries[]` row (#57). */
  debug?: CsvImportCelDebugEvent[];
}

export interface CsvImportExecuteResult {
  posted_entries: number;
  dropped_rows: number;
  row_errors: CsvImportRowError[];
}

/** 422 from POST /imports/csv/execute with full `row_errors` for UI display. */
export class CsvImportValidationError extends ApiHttpError {
  readonly rowErrors: CsvImportRowError[];

  constructor(status: number, message: string, rowErrors: CsvImportRowError[]) {
    super(status, message);
    this.name = "CsvImportValidationError";
    this.rowErrors = rowErrors;
  }
}

async function throwIfNotOk(response: Response): Promise<void> {
  if (!response.ok) {
    throw new ApiHttpError(response.status, await readApiErrorMessage(response));
  }
}

export async function listImportTemplates(): Promise<ImportTemplateSummary[]> {
  const response = await fetch(`${getApiBase()}/import-templates`);
  await throwIfNotOk(response);
  return response.json();
}

export async function getImportTemplate(templateId: number): Promise<ImportTemplate> {
  const response = await fetch(`${getApiBase()}/import-templates/${templateId}`);
  await throwIfNotOk(response);
  return response.json();
}

export async function createImportTemplate(payload: SaveImportTemplatePayload): Promise<ImportTemplate> {
  const response = await fetch(`${getApiBase()}/import-templates`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    throw new ApiHttpError(response.status, await readApiErrorMessage(response));
  }
  return response.json();
}

export async function patchImportTemplate(
  templateId: number,
  payload: Partial<SaveImportTemplatePayload>,
): Promise<ImportTemplate> {
  const response = await fetch(`${getApiBase()}/import-templates/${templateId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    throw new ApiHttpError(response.status, await readApiErrorMessage(response));
  }
  return response.json();
}

export async function executeCsvImport(payload: CsvImportExecutePayload): Promise<CsvImportExecuteResult> {
  const base = getApiBase();
  let response: Response;
  try {
    response = await fetch(`${base}/imports/csv/execute`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  } catch (err) {
    if (err instanceof TypeError) {
      throw new ApiHttpError(
        0,
        `Cannot reach API at ${base} (${err.message}). Is the API running on that host/port?`,
      );
    }
    throw err;
  }
  if (!response.ok) {
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (
        typeof body.detail === "object" &&
        body.detail !== null &&
        "row_errors" in body.detail
      ) {
        const detail = body.detail as {
          message?: string;
          row_errors?: CsvImportRowError[];
        };
        const rowErrors = (detail.row_errors ?? []).map((r) => ({
          row_number: r.row_number ?? 0,
          errors: r.errors ?? [],
        }));
        const prefix = detail.message ?? "CSV import failed validation";
        const summary =
          rowErrors.length > 0
            ? `${prefix} (${rowErrors.length} row${rowErrors.length === 1 ? "" : "s"} with errors).`
            : prefix;
        throw new CsvImportValidationError(response.status, summary, rowErrors);
      }
      throw new ApiHttpError(response.status, await readApiErrorMessage(response));
    } catch (err) {
      if (err instanceof ApiHttpError) {
        throw err;
      }
      throw new ApiHttpError(response.status, `Request failed (${response.status})`);
    }
  }
  return response.json();
}
