import { getApiBase } from "./baseUrl";
import { readApiErrorMessage } from "./errors";

export class ApiHttpError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiHttpError";
    this.status = status;
  }
}

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
