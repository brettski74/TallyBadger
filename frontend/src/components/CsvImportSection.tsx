import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";

import type { Account } from "../api/accounts";
import { listCelRuleSets, type CelRuleSetSummary } from "../api/celRuleSets";
import {
  ApiHttpError,
  createImportTemplate,
  CsvImportDuplicateContentError,
  executeCsvImport,
  getImportTemplate,
  listImportTemplates,
  patchImportTemplate,
  type CsvImportExecuteResult,
  type ImportColumnDataType,
  type ImportTemplate,
  type ImportTemplateColumn,
  type ImportTemplateNormalBalance,
  type ImportTemplateSummary,
} from "../api/importTemplates";
import {
  listImportBatches,
  unloadImportBatch,
  type ImportBatchListItem,
} from "../api/importBatches";
import { parseCsv } from "../lib/csvParse";
import { readFileAsText } from "../lib/readFileAsText";

type Step = "start" | "preview";

type PreviewRowLimit = 10 | 25 | 50 | 100;

interface EditableColumn {
  attributeName: string;
  dataType: ImportColumnDataType;
  dateFormat: string;
}

const PREVIEW_LIMITS: PreviewRowLimit[] = [10, 25, 50, 100];

const DATA_TYPES: ImportColumnDataType[] = ["string", "numeric", "date", "datetime"];

function inferImportNormalFromAccountType(type: Account["type"]): ImportTemplateNormalBalance {
  if (type === "asset" || type === "expense" || type === "suspense") {
    return "debit";
  }
  return "credit";
}

function defaultColumns(count: number): EditableColumn[] {
  return Array.from({ length: count }, () => ({
    attributeName: "",
    dataType: "string",
    dateFormat: "",
  }));
}

function fromApiColumn(c: ImportTemplateColumn): EditableColumn {
  return {
    attributeName: c.attribute_name ?? "",
    dataType: c.data_type,
    dateFormat: c.date_format ?? "",
  };
}

function mergeTemplateColumns(templateCols: ImportTemplateColumn[] | undefined, csvColCount: number): EditableColumn[] {
  const defaults = defaultColumns(csvColCount);
  if (!templateCols?.length) {
    return defaults;
  }
  return defaults.map((d, i) => (templateCols[i] ? fromApiColumn(templateCols[i]!) : d));
}

function toApiColumns(cols: EditableColumn[]): ImportTemplateColumn[] {
  return cols.map((c) => {
    const attribute_name = c.attributeName.trim() ? c.attributeName.trim() : null;
    const data_type = c.dataType;
    const date_format = data_type === "date" || data_type === "datetime" ? c.dateFormat.trim() || null : null;
    return { attribute_name, data_type, date_format };
  });
}

function fillBlankAttributesFromHeader(columns: EditableColumn[], headerRow: string[] | undefined): EditableColumn[] {
  if (!headerRow) {
    return columns;
  }
  return columns.map((column, index) => {
    if (column.attributeName.trim()) {
      return column;
    }
    const headerValue = (headerRow[index] ?? "").trim();
    if (!headerValue) {
      return column;
    }
    return { ...column, attributeName: headerValue };
  });
}

function baselineKey(parts: {
  hasHeaderRow: boolean;
  celRuleSetId: string;
  templateName: string;
  columns: EditableColumn[];
  defaultImportAccountId: string;
  defaultImportNormalBalance: string;
}): string {
  return JSON.stringify({
    hasHeaderRow: parts.hasHeaderRow,
    celRuleSetId: parts.celRuleSetId,
    templateName: parts.templateName.trim(),
    columns: parts.columns,
    defaultImportAccountId: parts.defaultImportAccountId,
    defaultImportNormalBalance: parts.defaultImportNormalBalance,
  });
}

export interface CsvImportSectionProps {
  accounts: Account[];
  /** After a successful import that created a batch: switch tab and pass canonical basename (#136). */
  onImportSucceeded?: (info: { basename: string }) => void;
}

export function CsvImportSection({ accounts, onImportSucceeded }: CsvImportSectionProps) {
  const [step, setStep] = useState<Step>("start");
  const [listError, setListError] = useState<string | null>(null);
  const [templates, setTemplates] = useState<ImportTemplateSummary[]>([]);
  const [ruleSets, setRuleSets] = useState<CelRuleSetSummary[]>([]);

  const [file, setFile] = useState<File | null>(null);
  const [dragActive, setDragActive] = useState(false);
  const [startTemplateId, setStartTemplateId] = useState<string>("");
  const [prefetchError, setPrefetchError] = useState<string | null>(null);
  const [prefetchedTemplate, setPrefetchedTemplate] = useState<ImportTemplate | null>(null);
  const [prefetching, setPrefetching] = useState(false);

  const [rawRows, setRawRows] = useState<string[][]>([]);
  const [hasHeaderRow, setHasHeaderRow] = useState(false);
  const [previewRowLimit, setPreviewRowLimit] = useState<PreviewRowLimit>(10);
  const [columns, setColumns] = useState<EditableColumn[]>([]);
  const [celRuleSetId, setCelRuleSetId] = useState<string>("");
  const [templateNameInput, setTemplateNameInput] = useState("");
  const [loadedTemplateId, setLoadedTemplateId] = useState<number | null>(null);
  const [defaultImportAccountId, setDefaultImportAccountId] = useState("");
  const [defaultImportNormalBalance, setDefaultImportNormalBalance] = useState<"" | ImportTemplateNormalBalance>("");
  const [baseline, setBaseline] = useState<string>("");

  const [saveError, setSaveError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [continueError, setContinueError] = useState<string | null>(null);
  const [executeError, setExecuteError] = useState<string | null>(null);
  const [executeRowErrors, setExecuteRowErrors] = useState<
    { row_number: number; errors: string[] }[] | null
  >(null);
  const [executing, setExecuting] = useState(false);
  const [executeResult, setExecuteResult] = useState<CsvImportExecuteResult | null>(null);
  const [duplicateImportPrompt, setDuplicateImportPrompt] = useState<string | null>(null);
  const [importBatches, setImportBatches] = useState<ImportBatchListItem[]>([]);
  const [unloadingBatchId, setUnloadingBatchId] = useState<number | null>(null);
  const [unloadError, setUnloadError] = useState<string | null>(null);

  const loadLists = useCallback(async () => {
    setListError(null);
    try {
      const [t, r, b] = await Promise.all([listImportTemplates(), listCelRuleSets(), listImportBatches()]);
      setTemplates(t);
      setRuleSets(r);
      setImportBatches(b);
    } catch (err) {
      setListError(err instanceof Error ? err.message : "Failed to load templates or rule sets");
    }
  }, []);

  useEffect(() => {
    void loadLists();
  }, [loadLists]);

  useEffect(() => {
    if (!startTemplateId) {
      setPrefetchedTemplate(null);
      setPrefetchError(null);
      return;
    }
    let cancelled = false;
    setPrefetching(true);
    setPrefetchError(null);
    void (async () => {
      try {
        const t = await getImportTemplate(Number(startTemplateId));
        if (!cancelled) {
          setPrefetchedTemplate(t);
        }
      } catch (err) {
        if (!cancelled) {
          setPrefetchedTemplate(null);
          setPrefetchError(err instanceof Error ? err.message : "Failed to load template");
        }
      } finally {
        if (!cancelled) {
          setPrefetching(false);
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [startTemplateId]);

  const isDirty = useMemo(
    () =>
      baseline !==
      baselineKey({
        hasHeaderRow,
        celRuleSetId,
        templateName: templateNameInput,
        columns,
        defaultImportAccountId,
        defaultImportNormalBalance,
      }),
    [baseline, hasHeaderRow, celRuleSetId, templateNameInput, columns, defaultImportAccountId, defaultImportNormalBalance],
  );

  const dataRows = useMemo(() => {
    if (rawRows.length === 0) {
      return [];
    }
    return hasHeaderRow ? rawRows.slice(1) : rawRows;
  }, [rawRows, hasHeaderRow]);

  const previewRows = useMemo(() => dataRows.slice(0, previewRowLimit), [dataRows, previewRowLimit]);

  const canSaveNamed = templateNameInput.trim().length > 0;
  const saveDisabled =
    saving || !canSaveNamed || (loadedTemplateId != null && !isDirty) || columns.length === 0;

  function resetPreviewState() {
    setRawRows([]);
    setHasHeaderRow(false);
    setPreviewRowLimit(10);
    setColumns([]);
    setCelRuleSetId("");
    setTemplateNameInput("");
    setLoadedTemplateId(null);
    setDefaultImportAccountId("");
    setDefaultImportNormalBalance("");
    setBaseline("");
    setSaveError(null);
    setContinueError(null);
    setExecuteError(null);
    setExecuteResult(null);
    setDuplicateImportPrompt(null);
  }

  function applySnapshot(
    nextColumns: EditableColumn[],
    header: boolean,
    ruleId: string,
    name: string,
    templateId: number | null,
    importDefaults?: { accountId: string; normal: "" | ImportTemplateNormalBalance },
  ) {
    const acctId = importDefaults?.accountId ?? "";
    const normalBal = importDefaults?.normal ?? "";
    setColumns(nextColumns);
    setHasHeaderRow(header);
    setCelRuleSetId(ruleId);
    setTemplateNameInput(name);
    setLoadedTemplateId(templateId);
    setDefaultImportAccountId(acctId);
    setDefaultImportNormalBalance(normalBal);
    setBaseline(
      baselineKey({
        hasHeaderRow: header,
        celRuleSetId: ruleId,
        templateName: name,
        columns: nextColumns,
        defaultImportAccountId: acctId,
        defaultImportNormalBalance: normalBal,
      }),
    );
  }

  async function handleContinue(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setContinueError(null);
    if (!file) {
      setContinueError("Choose a CSV file first.");
      return;
    }
    if (startTemplateId && prefetchError) {
      setContinueError(prefetchError);
      return;
    }
    if (startTemplateId && prefetching) {
      setContinueError("Template is still loading.");
      return;
    }

    let text: string;
    try {
      text = await readFileAsText(file);
    } catch {
      setContinueError("Could not read the file.");
      return;
    }

    const rows = parseCsv(text);
    if (rows.length === 0) {
      setContinueError("The CSV has no data rows.");
      return;
    }

    const colCount = rows[0]!.length;
    const tpl = startTemplateId ? prefetchedTemplate : null;

    let nextColumns = tpl
      ? mergeTemplateColumns(tpl.columns, colCount)
      : defaultColumns(colCount);
    const header = tpl ? tpl.has_header_row : false;
    const ruleId = tpl?.cel_rule_set_id != null ? String(tpl.cel_rule_set_id) : "";
    const name = tpl?.name ?? "";
    const tid = tpl?.id ?? null;

    if (header) {
      nextColumns = fillBlankAttributesFromHeader(nextColumns, rows[0]);
    }

    setRawRows(rows);
    applySnapshot(nextColumns, header, ruleId, name, tid, {
      accountId: tpl?.default_import_account_id != null ? String(tpl.default_import_account_id) : "",
      normal:
        tpl?.default_import_normal_balance === "debit" || tpl?.default_import_normal_balance === "credit"
          ? tpl.default_import_normal_balance
          : "",
    });
    setStep("preview");
  }

  function handleBack() {
    setStep("start");
    resetPreviewState();
  }

  function updateColumn(index: number, patch: Partial<EditableColumn>) {
    setColumns((prev) =>
      prev.map((c, i) => {
        if (i !== index) {
          return c;
        }
        const next = { ...c, ...patch };
        if (patch.dataType && patch.dataType !== "date" && patch.dataType !== "datetime") {
          next.dateFormat = "";
        }
        return next;
      }),
    );
  }

  async function persistWithOptionalOverwrite(body: {
    name: string;
    has_header_row: boolean;
    columns: ImportTemplateColumn[];
    cel_rule_set_id: number | null;
    default_import_account_id: number | null;
    default_import_normal_balance: ImportTemplateNormalBalance | null;
  }): Promise<ImportTemplate | null> {
    const tryPatch = async (id: number) => patchImportTemplate(id, body);

    if (loadedTemplateId != null) {
      try {
        return await tryPatch(loadedTemplateId);
      } catch (err) {
        if (err instanceof ApiHttpError && err.status === 409) {
          const ok = window.confirm(
            "Another template already uses this name. Overwrite that saved template?",
          );
          if (!ok) {
            return null;
          }
          const fresh = await listImportTemplates();
          const hit = fresh.find((t) => t.name === body.name);
          if (!hit) {
            throw err;
          }
          const updated = await tryPatch(hit.id);
          setLoadedTemplateId(hit.id);
          return updated;
        }
        throw err;
      }
    }

    try {
      return await createImportTemplate(body);
    } catch (err) {
      if (err instanceof ApiHttpError && err.status === 409) {
        const ok = window.confirm(
          "A template with this name already exists. Overwrite the saved template?",
        );
        if (!ok) {
          return null;
        }
        const fresh = await listImportTemplates();
        const hit = fresh.find((t) => t.name === body.name);
        if (!hit) {
          throw err;
        }
        const updated = await patchImportTemplate(hit.id, body);
        setLoadedTemplateId(hit.id);
        return updated;
      }
      throw err;
    }
  }

  async function handleSaveTemplate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaveError(null);
    const name = templateNameInput.trim();
    if (!name) {
      setSaveError("Add a template name to save, or leave blank for a one-off import only.");
      return;
    }
    if (loadedTemplateId != null && !isDirty) {
      return;
    }

    setSaving(true);
    try {
      const body = {
        name,
        has_header_row: hasHeaderRow,
        columns: toApiColumns(columns),
        cel_rule_set_id: celRuleSetId ? Number(celRuleSetId) : null,
        default_import_account_id: defaultImportAccountId ? Number(defaultImportAccountId) : null,
        default_import_normal_balance:
          defaultImportNormalBalance === "debit" || defaultImportNormalBalance === "credit"
            ? defaultImportNormalBalance
            : null,
      };
      const saved = await persistWithOptionalOverwrite(body);
      if (!saved) {
        return;
      }
      setTemplates(await listImportTemplates());
      setLoadedTemplateId(saved.id);
      const nextAcct =
        saved.default_import_account_id != null ? String(saved.default_import_account_id) : "";
      const nextNorm =
        saved.default_import_normal_balance === "debit" || saved.default_import_normal_balance === "credit"
          ? saved.default_import_normal_balance
          : "";
      setDefaultImportAccountId(nextAcct);
      setDefaultImportNormalBalance(nextNorm);
      setBaseline(
        baselineKey({
          hasHeaderRow: saved.has_header_row,
          celRuleSetId: saved.cel_rule_set_id != null ? String(saved.cel_rule_set_id) : "",
          templateName: saved.name,
          columns: saved.columns.map(fromApiColumn),
          defaultImportAccountId: nextAcct,
          defaultImportNormalBalance: nextNorm,
        }),
      );
      setTemplateNameInput(saved.name);
      setHasHeaderRow(saved.has_header_row);
      setCelRuleSetId(saved.cel_rule_set_id != null ? String(saved.cel_rule_set_id) : "");
      setColumns(saved.columns.map(fromApiColumn));
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : "Save failed");
    } finally {
      setSaving(false);
    }
  }

  function csvTextFromRows(rows: string[][]): string {
    return rows
      .map((row) =>
        row
          .map((cell) => {
            if (cell.includes('"') || cell.includes(",") || cell.includes("\n")) {
              return `"${cell.replace(/"/g, '""')}"`;
            }
            return cell;
          })
          .join(","),
      )
      .join("\n");
  }

  async function handleExecuteImport(options?: { confirmDuplicateContent?: boolean }) {
    if (!rawRows.length) {
      setExecuteError("No CSV rows are loaded.");
      return;
    }
    if (!file) {
      setExecuteError("Choose a CSV file first (the upload name is sent as the import basename).");
      return;
    }
    setExecuteError(null);
    setExecuteRowErrors(null);
    setExecuteResult(null);
    if (!options?.confirmDuplicateContent) {
      setDuplicateImportPrompt(null);
    }
    setExecuting(true);
    try {
      const result = await executeCsvImport({
        csv_text: csvTextFromRows(rawRows),
        basename: file.name,
        confirm_duplicate_content: options?.confirmDuplicateContent ?? false,
        has_header_row: hasHeaderRow,
        columns: toApiColumns(columns),
        cel_rule_set_id: celRuleSetId ? Number(celRuleSetId) : null,
        default_import_account_id: defaultImportAccountId ? Number(defaultImportAccountId) : null,
        default_import_normal_balance:
          defaultImportNormalBalance === "debit" || defaultImportNormalBalance === "credit"
            ? defaultImportNormalBalance
            : null,
      });
      setExecuteResult(result);
      setDuplicateImportPrompt(null);
      try {
        setImportBatches(await listImportBatches());
      } catch {
        /* list refresh is best-effort */
      }
      if (result.import_batch_id != null) {
        const basename = (result.basename ?? file?.name ?? "").trim();
        if (basename) {
          onImportSucceeded?.({ basename });
        }
      }
    } catch (err) {
      const rowErrors =
        err !== null &&
        typeof err === "object" &&
        "rowErrors" in err &&
        Array.isArray((err as { rowErrors: unknown }).rowErrors)
          ? (err as { rowErrors: { row_number: number; errors: string[] }[] }).rowErrors
          : null;
      if (rowErrors !== null && err instanceof Error) {
        setExecuteError(err.message);
        setExecuteRowErrors([...rowErrors].sort((a, b) => a.row_number - b.row_number));
        setDuplicateImportPrompt(null);
      } else if (err instanceof CsvImportDuplicateContentError) {
        setExecuteError(err.message);
        setExecuteRowErrors(null);
        setDuplicateImportPrompt(err.message);
      } else if (err instanceof ApiHttpError) {
        setExecuteError(err.message);
        setExecuteRowErrors(null);
        setDuplicateImportPrompt(null);
      } else {
        setExecuteError(err instanceof Error ? err.message : "Failed to execute import");
        setExecuteRowErrors(null);
        setDuplicateImportPrompt(null);
      }
    } finally {
      setExecuting(false);
    }
  }

  async function handleUnloadImportBatch(batch: ImportBatchListItem) {
    setUnloadError(null);
    if (!batch.is_latest_loaded_import) {
      const proceed = window.confirm(
        "This file is not the most recent CSV import (by load time). Unloading it can leave the ledger inconsistent " +
          "if later imports or work depended on it. Only continue if you know the blast radius. Continue?",
      );
      if (!proceed) {
        return;
      }
    }
    const confirmUnload = window.confirm(
      `Unload "${batch.basename}"? All journal entries posted from this import will be permanently removed, ` +
        "including rolling back settlements, obligations, and cheque clearances tied to those entries.",
    );
    if (!confirmUnload) {
      return;
    }
    setUnloadingBatchId(batch.id);
    try {
      await unloadImportBatch(batch.id);
      await loadLists();
    } catch (err) {
      setUnloadError(err instanceof Error ? err.message : "Unload failed");
    } finally {
      setUnloadingBatchId(null);
    }
  }

  function onDropFiles(files: FileList | null) {
    const next = files?.[0];
    if (!next) {
      return;
    }
    if (!next.name.toLowerCase().endsWith(".csv")) {
      setContinueError("Please drop a .csv file.");
      return;
    }
    setContinueError(null);
    setFile(next);
  }

  return (
    <>
      <section className="card csv-import-card">
        <h2>CSV import</h2>
        <p className="muted">
          Choose a file, map columns, optionally save a reusable template, then execute the import.
        </p>
        {listError && (
          <p className="error" role="alert">
            {listError}
          </p>
        )}

        <div className="csv-import-loaded-batches">
          <h3>Loaded CSV imports</h3>
          <p className="muted">
            Unload removes the batch row and all journal lines created for that file, and rolls back settlements,
            accrual obligations, and cheque links on those entries where the API can do so safely.
          </p>
          {unloadError ? (
            <p className="error" role="alert">
              {unloadError}
            </p>
          ) : null}
          {importBatches.length === 0 ? (
            <p className="muted">No import batches in the ledger yet.</p>
          ) : (
            <table className="csv-import-batches-table">
              <thead>
                <tr>
                  <th scope="col">File</th>
                  <th scope="col">Loaded</th>
                  <th scope="col" />
                </tr>
              </thead>
              <tbody>
                {importBatches.map((b) => (
                  <tr key={b.id}>
                    <td>{b.basename}</td>
                    <td>
                      <span className="muted">{new Date(b.loaded_at).toLocaleString()}</span>
                      {!b.is_latest_loaded_import ? (
                        <span className="csv-import-batch-flag"> · not latest import</span>
                      ) : null}
                    </td>
                    <td>
                      <button
                        type="button"
                        className="button-secondary"
                        disabled={unloadingBatchId !== null || !!listError}
                        aria-label={`Unload import ${b.basename}`}
                        onClick={() => void handleUnloadImportBatch(b)}
                      >
                        {unloadingBatchId === b.id ? "Unloading…" : "Unload"}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        {step === "start" && (
          <form className="csv-import-start" onSubmit={(e) => void handleContinue(e)}>
            <label>
              Import template (optional)
              <select
                aria-label="Import template"
                value={startTemplateId}
                onChange={(e) => setStartTemplateId(e.target.value)}
                disabled={!!listError}
              >
                <option value="">— None —</option>
                {templates.map((t) => (
                  <option key={t.id} value={String(t.id)}>
                    {t.name}
                  </option>
                ))}
              </select>
            </label>
            {prefetching && startTemplateId ? <p className="muted">Loading template…</p> : null}
            {prefetchError && startTemplateId ? (
              <p className="error" role="alert">
                {prefetchError}
              </p>
            ) : null}

            <div
              className={`csv-drop-zone ${dragActive ? "csv-drop-zone-active" : ""}`}
              onDragEnter={(e) => {
                e.preventDefault();
                setDragActive(true);
              }}
              onDragOver={(e) => {
                e.preventDefault();
                setDragActive(true);
              }}
              onDragLeave={(e) => {
                e.preventDefault();
                if (!e.currentTarget.contains(e.relatedTarget as Node)) {
                  setDragActive(false);
                }
              }}
              onDrop={(e) => {
                e.preventDefault();
                setDragActive(false);
                onDropFiles(e.dataTransfer.files);
              }}
            >
              <p className="csv-drop-zone-title">Drag and drop a CSV file here</p>
              <label className="csv-file-label">
                Or choose file
                <input
                  aria-label="CSV file"
                  type="file"
                  accept=".csv,text/csv"
                  className="csv-file-input"
                  onChange={(e) => onDropFiles(e.target.files)}
                />
              </label>
              {file ? <p className="muted csv-selected-file">Selected: {file.name}</p> : null}
            </div>

            {continueError ? (
              <p className="error" role="alert">
                {continueError}
              </p>
            ) : null}

            <div className="form-actions-inline">
              <button type="submit" disabled={!file || !!listError || (!!startTemplateId && (!!prefetchError || prefetching))}>
                Continue to preview
              </button>
            </div>
          </form>
        )}

        {step === "preview" && (
          <div className="csv-import-preview">
            <div className="csv-preview-toolbar">
              <button type="button" className="button-secondary" onClick={handleBack}>
                Back
              </button>
              <span className="muted">{file?.name}</span>
            </div>

            <label className="checkbox">
              <input
                aria-label="First row is a header"
                type="checkbox"
                checked={hasHeaderRow}
                onChange={(e) => {
                  const checked = e.target.checked;
                  setHasHeaderRow(checked);
                  if (checked) {
                    setColumns((prev) => fillBlankAttributesFromHeader(prev, rawRows[0]));
                  }
                }}
              />
              First row is a header (not imported as data)
            </label>

            <label>
              Preview row limit (display only)
              <select
                aria-label="Preview row limit"
                value={previewRowLimit}
                onChange={(e) => setPreviewRowLimit(Number(e.target.value) as PreviewRowLimit)}
              >
                {PREVIEW_LIMITS.map((n) => (
                  <option key={n} value={n}>
                    {n}
                  </option>
                ))}
              </select>
            </label>

            <div className="csv-preview-table-wrap">
              <table className="csv-preview-table">
                <thead>
                  <tr>
                    <th scope="col" />
                    {columns.map((_, colIndex) => (
                      <th key={colIndex} scope="col">
                        Column {colIndex + 1}
                      </th>
                    ))}
                  </tr>
                  <tr>
                    <th scope="row">Attribute</th>
                    {columns.map((c, colIndex) => (
                      <td key={colIndex}>
                        <input
                          aria-label={`Attribute for column ${colIndex + 1}`}
                          value={c.attributeName}
                          placeholder="blank = omit"
                          onChange={(e) => updateColumn(colIndex, { attributeName: e.target.value })}
                        />
                      </td>
                    ))}
                  </tr>
                  <tr>
                    <th scope="row">Type</th>
                    {columns.map((c, colIndex) => (
                      <td key={colIndex}>
                        <select
                          aria-label={`Type for column ${colIndex + 1}`}
                          value={c.dataType}
                          onChange={(e) =>
                            updateColumn(colIndex, { dataType: e.target.value as ImportColumnDataType })
                          }
                        >
                          {DATA_TYPES.map((dt) => (
                            <option key={dt} value={dt}>
                              {dt}
                            </option>
                          ))}
                        </select>
                      </td>
                    ))}
                  </tr>
                  <tr>
                    <th scope="row">Date format</th>
                    {columns.map((c, colIndex) => (
                      <td key={colIndex}>
                        <input
                          aria-label={`Date format for column ${colIndex + 1}`}
                          value={c.dateFormat}
                          placeholder="YYYY-MM-DD"
                          disabled={c.dataType !== "date" && c.dataType !== "datetime"}
                          onChange={(e) => updateColumn(colIndex, { dateFormat: e.target.value })}
                        />
                      </td>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {previewRows.map((row, rowIndex) => (
                    <tr key={rowIndex}>
                      <th scope="row">Row {rowIndex + 1}</th>
                      {columns.map((_, colIndex) => (
                        <td key={colIndex}>{row[colIndex] ?? ""}</td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <form className="csv-save-form" onSubmit={(e) => void handleSaveTemplate(e)}>
              <label>
                Rule set (optional)
                <select
                  aria-label="CEL rule set"
                  value={celRuleSetId}
                  onChange={(e) => setCelRuleSetId(e.target.value)}
                >
                  <option value="">— None —</option>
                  {ruleSets.map((r) => (
                    <option key={r.id} value={String(r.id)}>
                      {r.name}
                    </option>
                  ))}
                </select>
              </label>

              <label>
                Default import account (optional)
                <select
                  aria-label="Default import account"
                  value={defaultImportAccountId}
                  onChange={(e) => {
                    const v = e.target.value;
                    setDefaultImportAccountId(v);
                    if (!v) {
                      setDefaultImportNormalBalance("");
                      return;
                    }
                    const acct = accounts.find((a) => String(a.id) === v);
                    if (acct) {
                      setDefaultImportNormalBalance(inferImportNormalFromAccountType(acct.type));
                    }
                  }}
                >
                  <option value="">— None —</option>
                  {accounts
                    .filter((a) => a.is_active)
                    .map((a) => (
                      <option key={a.id} value={String(a.id)}>
                        {a.name} ({a.type})
                      </option>
                    ))}
                </select>
              </label>
              <label>
                Amount sign treats default account as
                <select
                  aria-label="Default import account normal balance"
                  value={defaultImportNormalBalance}
                  disabled={!defaultImportAccountId}
                  onChange={(e) =>
                    setDefaultImportNormalBalance(
                      e.target.value === "debit" || e.target.value === "credit"
                        ? e.target.value
                        : "",
                    )
                  }
                >
                  <option value="">Infer from account type</option>
                  <option value="debit">Debit-normal (e.g. asset — +amount increases via debit)</option>
                  <option value="credit">Credit-normal (e.g. liability — +amount increases via credit)</option>
                </select>
              </label>
              <p className="muted">
                For simple rows, a signed amount together with this setting fills the default account on the correct
                side when rules leave a side blank; the other side uses unallocated suspense if needed (those entries
                are flagged for review). If unset, only unallocated accounts apply.
              </p>

              <label>
                Template name (optional)
                <input
                  aria-label="Template name"
                  value={templateNameInput}
                  placeholder="Leave blank for a one-off import only"
                  onChange={(e) => setTemplateNameInput(e.target.value)}
                />
              </label>
              <p className="muted">
                Named templates are saved when you click Save. Blank name keeps this run anonymous (no template write).
              </p>

              {saveError ? (
                <p className="error" role="alert">
                  {saveError}
                </p>
              ) : null}
              {executeError ? (
                <div className="error" role="alert">
                  <p className="csv-import-error-summary">{executeError}</p>
                  {executeRowErrors && executeRowErrors.length > 0 ? (
                    <ul className="csv-import-validation-rows">
                      {executeRowErrors.map((row) => (
                        <li key={row.row_number}>
                          <strong>Row {row.row_number}:</strong> {row.errors.join("; ")}
                        </li>
                      ))}
                    </ul>
                  ) : null}
                </div>
              ) : null}
              {duplicateImportPrompt ? (
                <div className="csv-import-duplicate-panel" role="region" aria-label="Duplicate file contents">
                  <button
                    type="button"
                    className="button-secondary"
                    onClick={() => void handleExecuteImport({ confirmDuplicateContent: true })}
                    disabled={executing}
                  >
                    Post anyway (duplicate file contents)
                  </button>
                </div>
              ) : null}
              {executeResult ? (
                <p className="banner-info" role="status">
                  Import complete: {executeResult.posted_entries} entries posted
                  {executeResult.dropped_rows > 0 ? `, ${executeResult.dropped_rows} rows dropped by rules` : ""}.
                </p>
              ) : null}

              <div className="form-actions-inline">
                <button type="submit" disabled={saveDisabled}>
                  {saving ? "Saving…" : "Save template"}
                </button>
                <button type="button" onClick={() => void handleExecuteImport()} disabled={executing || columns.length === 0}>
                  {executing ? "Executing…" : "Execute import"}
                </button>
              </div>
            </form>
          </div>
        )}
      </section>
    </>
  );
}
