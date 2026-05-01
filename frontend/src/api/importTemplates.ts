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

export interface ImportTemplate extends ImportTemplateSummary {
  has_header_row: boolean;
  columns: ImportTemplateColumn[];
  cel_rule_set_id: number | null;
  created_at: string;
}

export interface SaveImportTemplatePayload {
  name: string;
  has_header_row: boolean;
  columns: ImportTemplateColumn[];
  cel_rule_set_id: number | null;
}

export interface CsvImportExecutePayload {
  csv_text: string;
  has_header_row: boolean;
  columns: ImportTemplateColumn[];
  cel_rule_set_id: number | null;
}

export interface CsvImportRowError {
  row_number: number;
  errors: string[];
}

export interface CsvImportExecuteResult {
  posted_entries: number;
  dropped_rows: number;
  row_errors: CsvImportRowError[];
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
  const response = await fetch(`${getApiBase()}/imports/csv/execute`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (
        typeof body.detail === "object" &&
        body.detail !== null &&
        "row_errors" in body.detail
      ) {
        const detail = body.detail as { message?: string; row_errors?: Array<{ row_number?: number; errors?: string[] }> };
        const first = detail.row_errors?.[0];
        const firstMsg = first?.errors?.[0];
        const prefix = detail.message ?? "CSV import failed validation";
        const rowPart = first?.row_number ? ` (row ${first.row_number})` : "";
        throw new ApiHttpError(response.status, `${prefix}${rowPart}${firstMsg ? `: ${firstMsg}` : ""}`);
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
