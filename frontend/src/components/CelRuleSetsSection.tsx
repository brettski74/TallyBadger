import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  CaseSensitive,
  CornerDownLeft,
  FileText,
  MoveDown,
  MoveUp,
  SquareCheckBig,
  SquareX,
  Trash2,
} from "lucide-react";

import {
  CelRuleSetSaveValidationError,
  createCelRuleSet,
  deleteCelRuleSet,
  getCelRuleSet,
  listCelRuleSets,
  patchCelRuleSet,
  type CelRule,
  type CelRegexCapture,
  type CelRuleSetSummary,
  type CelRuleSetValidationErrorItem,
} from "../api/celRuleSets";
import { ApiHttpError } from "../api/errors";
import { useFormSaveRevertShortcuts } from "../hooks/useFormSaveRevertShortcuts";
import {
  discardActionTooltip,
  discardAriaKeyShortcuts,
  saveActionTooltip,
  saveAriaKeyShortcuts,
} from "../lib/keyboardHints";
import { isMacLikeUserAgent } from "../lib/platformKeyboard";
import { TableRowIconButton } from "./TableRowIconButton";

/** Excerpt for the rules list body (wraps; CSS limits block to ~two lines). */
function expressionPreviewDisplay(expr: string): string {
  const normalized = expr.replace(/\r\n/g, "\n").trim();
  if (!normalized) {
    return "(empty)";
  }
  const max = 220;
  return normalized.length <= max ? normalized : `${normalized.slice(0, max - 1)}…`;
}

/** Assign sort_order from current array position (display order is authoritative). */
function renumber(rules: CelRule[]): CelRule[] {
  return rules.map((r, i) => ({ ...r, sort_order: i }));
}

function serializeState(name: string, rules: CelRule[]): string {
  const ordered = renumber(rules);
  return JSON.stringify({
    name: name.trim(),
    rule_set: {
      rules: ordered.map((r, idx) => ({
        name: r.name,
        enabled: r.enabled,
        sort_order: idx,
        expression: r.expression,
        captures: r.captures.map((c) => ({
          attribute: c.attribute,
          pattern: c.pattern,
          flags: [...c.flags].sort(),
          label: c.label?.trim() ? c.label.trim() : null,
        })),
      })),
    },
  });
}

function normalizeRulesFromApi(rules: CelRule[]): CelRule[] {
  const sorted = [...rules].sort((a, b) => a.sort_order - b.sort_order || 0);
  return sorted.map((r, i) => ({
    ...r,
    sort_order: i,
    captures: r.captures.map((c) => ({ ...c, label: c.label ?? null, flags: c.flags ?? [] })),
  }));
}

function newRule(sortOrder: number): CelRule {
  return {
    name: null,
    enabled: true,
    sort_order: sortOrder,
    expression: "null",
    captures: [],
  };
}

function newCapture(): CelRegexCapture {
  return {
    attribute: "description",
    pattern: ".*",
    flags: [],
    label: null,
  };
}

function buildPayload(name: string, rules: CelRule[]): { name: string; rule_set: { rules: CelRule[] } } {
  const ordered = renumber(rules);
  return {
    name: name.trim(),
    rule_set: {
      rules: ordered.map((r, i) => ({
        name: r.name?.trim() ? r.name.trim() : null,
        enabled: r.enabled,
        sort_order: i,
        expression: r.expression,
        captures: r.captures.map((c) => ({
          attribute: c.attribute.trim(),
          pattern: c.pattern,
          flags: c.flags,
          label: c.label?.trim() ? c.label.trim() : null,
        })),
      })),
    },
  };
}

function ruleDisplayName(rule: CelRule): string {
  const n = rule.name?.trim();
  if (n) {
    return n;
  }
  return "Untitled rule";
}

function errorsForRule(
  errors: CelRuleSetValidationErrorItem[],
  ruleIndex: number,
): CelRuleSetValidationErrorItem[] {
  return errors.filter((e) => e.rule_index === ruleIndex);
}

function expressionErrorsForRule(
  errors: CelRuleSetValidationErrorItem[],
  ruleIndex: number,
): CelRuleSetValidationErrorItem[] {
  return errors.filter((e) => e.rule_index === ruleIndex && e.field === "expression");
}

function patternErrorsForCapture(
  errors: CelRuleSetValidationErrorItem[],
  ruleIndex: number,
  captureIndex: number,
): CelRuleSetValidationErrorItem[] {
  return errors.filter(
    (e) =>
      e.rule_index === ruleIndex && e.field === "pattern" && e.capture_index === captureIndex,
  );
}

export function CelRuleSetsSection() {
  const [summaries, setSummaries] = useState<CelRuleSetSummary[]>([]);
  const [listLoading, setListLoading] = useState(true);
  const [listError, setListError] = useState<string | null>(null);

  const [selectKey, setSelectKey] = useState("");
  const [editingId, setEditingId] = useState<number | null>(null);
  const [draftName, setDraftName] = useState("");
  const [draftRules, setDraftRules] = useState<CelRule[]>([]);
  const [baseline, setBaseline] = useState("");

  const [selectedRuleIndex, setSelectedRuleIndex] = useState<number | null>(null);

  const [detailLoading, setDetailLoading] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [inlineValidationErrors, setInlineValidationErrors] = useState<
    CelRuleSetValidationErrorItem[]
  >([]);
  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState(false);

  const setRules = useCallback((updater: (prev: CelRule[]) => CelRule[]) => {
    setDraftRules((prev) => renumber(updater(prev)));
  }, []);

  const dirty = baseline !== "" && serializeState(draftName, draftRules) !== baseline;
  const hasSelection = selectKey !== "" && selectKey !== "__pick__";

  const refreshSummaries = useCallback(async () => {
    setListError(null);
    try {
      setSummaries(await listCelRuleSets());
    } catch (err) {
      setListError(err instanceof Error ? err.message : "Failed to load rule sets");
    } finally {
      setListLoading(false);
    }
  }, []);

  useEffect(() => {
    void refreshSummaries();
  }, [refreshSummaries]);

  useEffect(() => {
    if (!dirty) {
      return;
    }
    function onBeforeUnload(e: BeforeUnloadEvent) {
      e.preventDefault();
    }
    window.addEventListener("beforeunload", onBeforeUnload);
    return () => window.removeEventListener("beforeunload", onBeforeUnload);
  }, [dirty]);

  const resetToEmptyPicker = useCallback(() => {
    setSelectKey("");
    setEditingId(null);
    setDraftName("");
    setDraftRules([]);
    setSelectedRuleIndex(null);
    setBaseline("");
    setSaveError(null);
    setInlineValidationErrors([]);
  }, []);

  const applyNew = useCallback(() => {
    setEditingId(null);
    setDraftName("");
    setDraftRules([]);
    setSelectedRuleIndex(null);
    setBaseline(serializeState("", []));
    setSelectKey("new");
    setSaveError(null);
    setInlineValidationErrors([]);
  }, []);

  const applyExisting = useCallback(
    async (id: number) => {
      setDetailLoading(true);
      setSaveError(null);
      try {
        const row = await getCelRuleSet(id);
        const rules = normalizeRulesFromApi(row.rule_set.rules);
        setEditingId(id);
        setDraftName(row.name);
        setDraftRules(rules);
        setSelectedRuleIndex(rules.length ? 0 : null);
        setBaseline(serializeState(row.name, rules));
        setSelectKey(String(id));
      } catch (err) {
        setSaveError(err instanceof Error ? err.message : "Failed to load rule set");
        resetToEmptyPicker();
      } finally {
        setDetailLoading(false);
      }
    },
    [resetToEmptyPicker],
  );

  const formRef = useRef<HTMLFormElement>(null);
  const isMac = useMemo(() => isMacLikeUserAgent(), []);

  const handleRevert = useCallback(() => {
    if (!hasSelection) {
      return;
    }
    if (editingId != null) {
      void applyExisting(editingId);
    } else if (selectKey === "new") {
      applyNew();
    }
  }, [hasSelection, editingId, selectKey, applyExisting, applyNew]);

  useFormSaveRevertShortcuts({
    createFormRef: formRef,
    editFormRef: formRef,
    editingId,
    canSubmitCreate: dirty && draftName.trim().length > 0,
    canSubmitEdit: dirty && draftName.trim().length > 0,
    createSubmitting: saving,
    editSubmitting: saving,
    requestCreateSubmit: () => {
      formRef.current?.requestSubmit();
    },
    requestEditSubmit: () => {
      formRef.current?.requestSubmit();
    },
    requestEditRevert: handleRevert,
    requestCreateRevert: handleRevert,
  });

  function handleSelectKey(next: string) {
    if (next === selectKey) {
      return;
    }
    if (hasSelection && dirty && !window.confirm("Discard unsaved changes to this rule set?")) {
      return;
    }
    setSaveError(null);
    setInlineValidationErrors([]);
    if (next === "" || next === "__pick__") {
      resetToEmptyPicker();
      return;
    }
    if (next === "new") {
      applyNew();
      return;
    }
    void applyExisting(Number(next));
  }

  async function handleSave(e: FormEvent) {
    e.preventDefault();
    if (!draftName.trim()) {
      setSaveError("Rule set name is required.");
      return;
    }
    setSaveError(null);
    setInlineValidationErrors([]);
    setSaving(true);
    try {
      const payload = buildPayload(draftName, draftRules);
      if (editingId == null) {
        const created = await createCelRuleSet(payload);
        await refreshSummaries();
        const rules = normalizeRulesFromApi(created.rule_set.rules);
        setEditingId(created.id);
        setDraftName(created.name);
        setDraftRules(rules);
        setBaseline(serializeState(created.name, rules));
        setSelectKey(String(created.id));
        setSelectedRuleIndex(rules.length ? 0 : null);
      } else {
        const updated = await patchCelRuleSet(editingId, {
          name: payload.name,
          rule_set: payload.rule_set,
        });
        await refreshSummaries();
        const rules = normalizeRulesFromApi(updated.rule_set.rules);
        setDraftName(updated.name);
        setDraftRules(rules);
        setBaseline(serializeState(updated.name, rules));
        setSelectedRuleIndex((idx) =>
          idx != null && idx < rules.length ? idx : rules.length ? 0 : null,
        );
      }
      setInlineValidationErrors([]);
    } catch (err) {
      if (err instanceof CelRuleSetSaveValidationError) {
        setInlineValidationErrors(err.errors);
      } else if (err instanceof ApiHttpError) {
        setSaveError(err.message);
      } else {
        setSaveError(err instanceof Error ? err.message : "Save failed");
      }
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete() {
    if (editingId == null) {
      return;
    }
    if (!window.confirm(`Delete rule set “${draftName}”? This cannot be undone.`)) {
      return;
    }
    setDeleting(true);
    setSaveError(null);
    try {
      await deleteCelRuleSet(editingId);
      await refreshSummaries();
      resetToEmptyPicker();
    } catch (err) {
      if (err instanceof ApiHttpError) {
        setSaveError(err.message);
      } else {
        setSaveError(err instanceof Error ? err.message : "Delete failed");
      }
    } finally {
      setDeleting(false);
    }
  }

  function updateRuleAt(index: number, patch: Partial<CelRule>) {
    setRules((prev) => prev.map((r, i) => (i === index ? { ...r, ...patch } : r)));
  }

  function updateCaptureAt(ruleIndex: number, capIndex: number, patch: Partial<CelRegexCapture>) {
    setRules((prev) =>
      prev.map((r, i) => {
        if (i !== ruleIndex) {
          return r;
        }
        const captures = r.captures.map((c, j) => (j === capIndex ? { ...c, ...patch } : c));
        return { ...r, captures };
      }),
    );
  }

  function addRule() {
    const newIndex = draftRules.length;
    setRules((prev) => [...prev, newRule(prev.length)]);
    setSelectedRuleIndex(newIndex);
  }

  function removeRule(index: number) {
    setRules((prev) => {
      const filtered = prev.filter((_, i) => i !== index);
      setSelectedRuleIndex((cur) => {
        if (cur == null) {
          return null;
        }
        if (cur === index) {
          return filtered.length > 0 ? Math.min(index, filtered.length - 1) : null;
        }
        if (cur > index) {
          return cur - 1;
        }
        return cur;
      });
      return filtered;
    });
  }

  function moveRule(index: number, delta: number) {
    setRules((prev) => {
      const j = index + delta;
      if (j < 0 || j >= prev.length) {
        return prev;
      }
      const copy = [...prev];
      const tmp = copy[index];
      copy[index] = copy[j]!;
      copy[j] = tmp!;
      return copy;
    });
    setSelectedRuleIndex(index + delta);
  }

  function addCapture(ruleIndex: number) {
    setRules((prev) =>
      prev.map((r, i) => (i === ruleIndex ? { ...r, captures: [...r.captures, newCapture()] } : r)),
    );
  }

  function removeCapture(ruleIndex: number, capIndex: number) {
    setRules((prev) =>
      prev.map((r, i) =>
        i === ruleIndex ? { ...r, captures: r.captures.filter((_, j) => j !== capIndex) } : r,
      ),
    );
  }

  function moveCapture(ruleIndex: number, capIndex: number, delta: number) {
    setRules((prev) =>
      prev.map((r, i) => {
        if (i !== ruleIndex) {
          return r;
        }
        const j = capIndex + delta;
        if (j < 0 || j >= r.captures.length) {
          return r;
        }
        const caps = [...r.captures];
        const tmp = caps[capIndex];
        caps[capIndex] = caps[j]!;
        caps[j] = tmp!;
        return { ...r, captures: caps };
      }),
    );
  }

  function toggleFlag(ruleIndex: number, capIndex: number, flag: string, checked: boolean) {
    setRules((prev) =>
      prev.map((r, i) => {
        if (i !== ruleIndex) {
          return r;
        }
        const captures = r.captures.map((c, j) => {
          if (j !== capIndex) {
            return c;
          }
          const set = new Set(c.flags);
          if (checked) {
            set.add(flag);
          } else {
            set.delete(flag);
          }
          return { ...c, flags: [...set] };
        });
        return { ...r, captures };
      }),
    );
  }

  const selectedRule =
    selectedRuleIndex != null && draftRules[selectedRuleIndex] != null
      ? draftRules[selectedRuleIndex]
      : null;

  return (
    <section className="card rule-sets-card" aria-labelledby="rule-sets-heading">
      <h2 id="rule-sets-heading">Import rule sets (CEL)</h2>
      <p className="rule-sets-lead muted">
        Create and edit rule sets used by CSV import. Rules run in order; each can include regex matchers
        before the CEL expression runs.
      </p>

      {listError ? (
        <p className="error" role="alert">
          {listError}
        </p>
      ) : null}

      <div className="rule-sets-toolbar">
        <label className="rule-sets-select-label">
          <span className="sr-only">Rule set</span>
          <span aria-hidden>Rule set</span>
          <select
            value={selectKey === "" ? "__pick__" : selectKey}
            onChange={(e) => handleSelectKey(e.target.value === "__pick__" ? "" : e.target.value)}
            disabled={listLoading}
          >
            <option value="__pick__">Choose a rule set…</option>
            <option value="new">New rule set…</option>
            {summaries.map((s) => (
              <option key={s.id} value={String(s.id)}>
                {s.name}
              </option>
            ))}
          </select>
        </label>
        {dirty ? (
          <span className="rule-sets-unsaved" role="status">
            Unsaved changes
          </span>
        ) : null}
      </div>

      {!hasSelection ? (
        <p className="muted">Select an existing rule set or create a new one.</p>
      ) : detailLoading ? (
        <p className="muted">Loading…</p>
      ) : (
        <form ref={formRef} className="rule-sets-form" onSubmit={(e) => void handleSave(e)}>
          <div className="rule-sets-header-row">
            <label>
              Rule set name
              <input
                type="text"
                value={draftName}
                onChange={(e) => setDraftName(e.target.value)}
                required
                autoComplete="off"
                placeholder="e.g. Bank A interac"
              />
            </label>
            <div className="rule-sets-actions">
              <button
                type="submit"
                disabled={saving || !dirty}
                title={dirty && !saving ? saveActionTooltip(isMac) : undefined}
                aria-keyshortcuts={dirty && !saving ? saveAriaKeyShortcuts(isMac) : undefined}
              >
                {saving ? "Saving…" : "Save"}
              </button>
              <button
                type="button"
                className="button-secondary"
                onClick={handleRevert}
                disabled={saving || !dirty}
                title={discardActionTooltip(isMac)}
                aria-keyshortcuts={discardAriaKeyShortcuts(isMac)}
              >
                Revert
              </button>
              {editingId != null ? (
                <button
                  type="button"
                  className="button-danger"
                  onClick={() => void handleDelete()}
                  disabled={deleting || saving}
                >
                  {deleting ? "Deleting…" : "Delete"}
                </button>
              ) : null}
            </div>
          </div>

          {saveError ? (
            <p className="error" role="alert">
              {saveError}
            </p>
          ) : null}

          <div className="rule-sets-split">
            <div className="rule-sets-list-panel">
              <div className="rule-sets-list-head">
                <h3>Rules</h3>
                <button type="button" onClick={() => addRule()}>
                  Add rule
                </button>
              </div>
              {draftRules.length === 0 ? (
                <p className="muted">No rules yet. Add a rule to begin.</p>
              ) : (
                <ul className="rule-sets-rule-list">
                  {draftRules.map((rule, index) => (
                    <li
                      key={`${index}-${rule.sort_order}`}
                      className={
                        selectedRuleIndex === index ? "rule-sets-rule-li is-active" : "rule-sets-rule-li"
                      }
                    >
                      {/*
                        Issue #121 originally called for immediate API persist when toggling enabled on a rule row.
                        We keep enabled in the draft until Save instead so Discard applies to the whole rule set form.
                      */}
                      <div className="rule-sets-rule-row-layout">
                        <div className="rule-sets-rule-side-col rule-sets-rule-side-col--left" role="group" aria-label="Reorder rule">
                          <TableRowIconButton
                            type="button"
                            aria-label="Move rule up"
                            title="Move rule up"
                            disabled={index === 0}
                            onClick={() => moveRule(index, -1)}
                          >
                            <MoveUp size={18} strokeWidth={2} aria-hidden />
                          </TableRowIconButton>
                          <TableRowIconButton
                            type="button"
                            aria-label="Move rule down"
                            title="Move rule down"
                            disabled={index === draftRules.length - 1}
                            onClick={() => moveRule(index, 1)}
                          >
                            <MoveDown size={18} strokeWidth={2} aria-hidden />
                          </TableRowIconButton>
                        </div>
                        <button
                          type="button"
                          className="rule-sets-rule-row-main"
                          onClick={() => setSelectedRuleIndex(index)}
                        >
                          <span className="rule-sets-rule-name">{ruleDisplayName(rule)}</span>
                          <span className="rule-sets-rule-preview">{expressionPreviewDisplay(rule.expression)}</span>
                        </button>
                        <div className="rule-sets-rule-side-col rule-sets-rule-side-col--right" role="group" aria-label="Rule actions">
                          <TableRowIconButton
                            type="button"
                            aria-label="Delete"
                            title="Delete"
                            onClick={() => removeRule(index)}
                          >
                            <Trash2 size={18} strokeWidth={2} aria-hidden />
                          </TableRowIconButton>
                          {rule.enabled ? (
                            <TableRowIconButton
                              type="button"
                              aria-label="Disable rule"
                              title="Disable rule"
                              onClick={() => updateRuleAt(index, { enabled: false })}
                            >
                              <SquareX size={18} strokeWidth={2} aria-hidden />
                            </TableRowIconButton>
                          ) : (
                            <TableRowIconButton
                              type="button"
                              aria-label="Enable rule"
                              title="Enable rule"
                              onClick={() => updateRuleAt(index, { enabled: true })}
                            >
                              <SquareCheckBig size={18} strokeWidth={2} aria-hidden />
                            </TableRowIconButton>
                          )}
                        </div>
                      </div>
                      {errorsForRule(inlineValidationErrors, index).map((issue, ei) => (
                        <p key={`rule-err-${index}-${ei}`} className="error-text" role="alert">
                          {issue.message}
                        </p>
                      ))}
                    </li>
                  ))}
                </ul>
              )}
            </div>

            <div className="rule-sets-detail-panel">
              {selectedRule == null ? (
                <p className="muted">Select a rule to edit matchers and CEL.</p>
              ) : (
                <>
                  <h3>Rule detail</h3>
                  <label>
                    Rule name
                    <input
                      type="text"
                      value={selectedRule.name ?? ""}
                      onChange={(e) =>
                        updateRuleAt(selectedRuleIndex!, {
                          name: e.target.value === "" ? null : e.target.value,
                        })
                      }
                      placeholder="Shown in the rules list and in evaluation traces"
                      autoComplete="off"
                    />
                  </label>
                  <label className="rule-sets-checkbox">
                    <input
                      type="checkbox"
                      checked={selectedRule.enabled}
                      onChange={(e) => updateRuleAt(selectedRuleIndex!, { enabled: e.target.checked })}
                    />
                    Enabled
                  </label>

                  <h4>Regex matchers</h4>
                  <p className="muted rule-sets-hint">
                    Matchers run in order; all must match before the CEL expression evaluates. Use a label so
                    you can tell matchers apart in traces and when editing.
                  </p>
                  {selectedRule.captures.length === 0 ? (
                    <p className="muted">No matchers (expression always runs).</p>
                  ) : null}

                  <div className="rule-sets-capture-actions">
                    <button type="button" onClick={() => addCapture(selectedRuleIndex!)}>
                      Add matcher
                    </button>
                  </div>

                  {selectedRule.captures.map((cap, ci) => (
                    <fieldset key={`cap-edit-${ci}`} className="rule-sets-capture-fieldset">
                      <legend className="sr-only">Matcher {ci + 1}</legend>
                      <div className="rule-sets-matcher-layout">
                        <div className="rule-sets-matcher-reorder" role="group" aria-label="Reorder matcher">
                          <TableRowIconButton
                            type="button"
                            aria-label="Move matcher up"
                            title="Move matcher up"
                            disabled={ci === 0}
                            onClick={() => moveCapture(selectedRuleIndex!, ci, -1)}
                          >
                            <MoveUp size={18} strokeWidth={2} aria-hidden />
                          </TableRowIconButton>
                          <TableRowIconButton
                            type="button"
                            aria-label="Move matcher down"
                            title="Move matcher down"
                            disabled={ci === selectedRule.captures.length - 1}
                            onClick={() => moveCapture(selectedRuleIndex!, ci, 1)}
                          >
                            <MoveDown size={18} strokeWidth={2} aria-hidden />
                          </TableRowIconButton>
                        </div>
                        <div className="rule-sets-matcher-fields">
                          <div className="rule-sets-matcher-label-row">
                            <label className="rule-sets-matcher-field">
                              <span className="rule-sets-matcher-field-caption">Matcher label:</span>
                              <input
                                type="text"
                                value={cap.label ?? ""}
                                onChange={(e) =>
                                  updateCaptureAt(selectedRuleIndex!, ci, {
                                    label: e.target.value === "" ? null : e.target.value,
                                  })
                                }
                                placeholder="e.g. Interac description line"
                                autoComplete="off"
                              />
                            </label>
                            <label className="rule-sets-matcher-field">
                              <span className="rule-sets-matcher-field-caption">Attribute:</span>
                              <input
                                type="text"
                                value={cap.attribute}
                                onChange={(e) =>
                                  updateCaptureAt(selectedRuleIndex!, ci, { attribute: e.target.value })
                                }
                                required
                                autoComplete="off"
                              />
                            </label>
                          </div>
                          <label className="rule-sets-matcher-field rule-sets-matcher-field--pattern">
                            <span className="rule-sets-matcher-field-caption">Pattern:</span>
                            <input
                              type="text"
                              value={cap.pattern}
                              onChange={(e) =>
                                updateCaptureAt(selectedRuleIndex!, ci, { pattern: e.target.value })
                              }
                              required
                              autoComplete="off"
                            />
                            {patternErrorsForCapture(
                              inlineValidationErrors,
                              selectedRuleIndex!,
                              ci,
                            ).map((issue, ei) => (
                              <p
                                key={`pattern-err-${ci}-${ei}`}
                                className="error-text"
                                role="alert"
                              >
                                {issue.message}
                              </p>
                            ))}
                          </label>
                        </div>
                        <div
                          className="rule-sets-matcher-flag-grid"
                          role="group"
                          aria-label="Matcher flags and delete"
                        >
                          <TableRowIconButton
                            type="button"
                            aria-label="Ignore case"
                            title="Ignore case"
                            aria-pressed={cap.flags.includes("ignorecase")}
                            onClick={() =>
                              toggleFlag(
                                selectedRuleIndex!,
                                ci,
                                "ignorecase",
                                !cap.flags.includes("ignorecase"),
                              )
                            }
                          >
                            <CaseSensitive size={18} strokeWidth={2} aria-hidden />
                          </TableRowIconButton>
                          <TableRowIconButton
                            type="button"
                            aria-label="Delete"
                            title="Delete"
                            onClick={() => removeCapture(selectedRuleIndex!, ci)}
                          >
                            <Trash2 size={18} strokeWidth={2} aria-hidden />
                          </TableRowIconButton>
                          <TableRowIconButton
                            type="button"
                            aria-label="Multiline"
                            title="Multiline"
                            aria-pressed={cap.flags.includes("multiline")}
                            onClick={() =>
                              toggleFlag(
                                selectedRuleIndex!,
                                ci,
                                "multiline",
                                !cap.flags.includes("multiline"),
                              )
                            }
                          >
                            <FileText size={18} strokeWidth={2} aria-hidden />
                          </TableRowIconButton>
                          <TableRowIconButton
                            type="button"
                            aria-label="Dot matches newlines"
                            title="Dot matches newlines"
                            aria-pressed={cap.flags.includes("dotall")}
                            onClick={() =>
                              toggleFlag(selectedRuleIndex!, ci, "dotall", !cap.flags.includes("dotall"))
                            }
                          >
                            <CornerDownLeft size={18} strokeWidth={2} aria-hidden />
                          </TableRowIconButton>
                        </div>
                      </div>
                    </fieldset>
                  ))}

                  <div className="rule-sets-cel-field">
                    <label htmlFor={`rule-cel-expr-${selectedRuleIndex}`} className="rule-sets-cel-label">
                      CEL expression
                    </label>
                    <textarea
                      id={`rule-cel-expr-${selectedRuleIndex}`}
                      value={selectedRule.expression}
                      onChange={(e) => updateRuleAt(selectedRuleIndex!, { expression: e.target.value })}
                      rows={16}
                      className="rule-sets-cel-textarea"
                      spellCheck={false}
                    />
                    {expressionErrorsForRule(inlineValidationErrors, selectedRuleIndex!).map(
                      (issue, ei) => (
                        <p
                          key={`expr-err-${selectedRuleIndex}-${ei}`}
                          className="error-text"
                          role="alert"
                        >
                          {issue.message}
                        </p>
                      ),
                    )}
                  </div>
                </>
              )}
            </div>
          </div>
        </form>
      )}
    </section>
  );
}
