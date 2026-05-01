import { FormEvent, useCallback, useEffect, useState } from "react";

import {
  createCelRuleSet,
  deleteCelRuleSet,
  getCelRuleSet,
  listCelRuleSets,
  patchCelRuleSet,
  type CelRule,
  type CelRegexCapture,
  type CelRuleSetSummary,
} from "../api/celRuleSets";
import { ApiHttpError } from "../api/errors";

const FLAG_OPTIONS: { value: string; label: string }[] = [
  { value: "ignorecase", label: "Ignore case" },
  { value: "multiline", label: "Multiline" },
  { value: "dotall", label: "Dotall" },
];

function expressionPreview(expr: string): string {
  const line = expr.replace(/\r\n/g, "\n").split("\n")[0]?.trim() ?? "";
  if (line.length <= 80) {
    return line || "(empty)";
  }
  return `${line.slice(0, 77)}…`;
}

function matcherRowTitle(cap: CelRegexCapture): string {
  const t = cap.label?.trim();
  if (t) {
    return t;
  }
  return cap.attribute;
}

function renumber(rules: CelRule[]): CelRule[] {
  return [...rules].sort((a, b) => a.sort_order - b.sort_order || 0).map((r, i) => ({ ...r, sort_order: i }));
}

function serializeState(name: string, rules: CelRule[]): string {
  const ordered = renumber(rules);
  return JSON.stringify({
    name: name.trim(),
    rule_set: {
      rules: ordered.map((r, idx) => ({
        id: r.id,
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

function cloneRules(rules: CelRule[]): CelRule[] {
  return JSON.parse(JSON.stringify(rules)) as CelRule[];
}

function normalizeRulesFromApi(rules: CelRule[]): CelRule[] {
  return renumber(
    rules.map((r) => ({
      ...r,
      captures: r.captures.map((c) => ({ ...c, label: c.label ?? null, flags: c.flags ?? [] })),
    })),
  );
}

function newRule(sortOrder: number): CelRule {
  return {
    id: null,
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
        id: r.id?.trim() ? r.id.trim() : null,
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
  }, []);

  const applyNew = useCallback(() => {
    setEditingId(null);
    setDraftName("");
    setDraftRules([]);
    setSelectedRuleIndex(null);
    setBaseline(serializeState("", []));
    setSelectKey("new");
    setSaveError(null);
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

  function handleSelectKey(next: string) {
    if (next === selectKey) {
      return;
    }
    if (hasSelection && dirty && !window.confirm("Discard unsaved changes to this rule set?")) {
      return;
    }
    setSaveError(null);
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

  function handleRevert() {
    if (!hasSelection) {
      return;
    }
    if (editingId != null) {
      void applyExisting(editingId);
    } else if (selectKey === "new") {
      applyNew();
    }
  }

  async function handleSave(e: FormEvent) {
    e.preventDefault();
    if (!draftName.trim()) {
      setSaveError("Rule set name is required.");
      return;
    }
    setSaveError(null);
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
    } catch (err) {
      if (err instanceof ApiHttpError) {
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
    let newIndex = 0;
    setRules((prev) => {
      const next = [...prev, newRule(prev.length)];
      newIndex = next.length - 1;
      return next;
    });
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
        <form className="rule-sets-form" onSubmit={(e) => void handleSave(e)}>
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
              <button type="submit" disabled={saving || !dirty}>
                {saving ? "Saving…" : "Save"}
              </button>
              <button type="button" onClick={() => handleRevert()} disabled={saving || !dirty}>
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
                    <li key={`${index}-${rule.sort_order}`}>
                      <button
                        type="button"
                        className={
                          selectedRuleIndex === index ? "rule-sets-rule-row is-active" : "rule-sets-rule-row"
                        }
                        onClick={() => setSelectedRuleIndex(index)}
                      >
                        <span className="rule-sets-rule-name">{ruleDisplayName(rule)}</span>
                        <span className="rule-sets-rule-preview">{expressionPreview(rule.expression)}</span>
                      </button>
                      <div className="rule-sets-rule-tools">
                        <button type="button" onClick={() => moveRule(index, -1)} disabled={index === 0}>
                          Up
                        </button>
                        <button
                          type="button"
                          onClick={() => moveRule(index, 1)}
                          disabled={index === draftRules.length - 1}
                        >
                          Down
                        </button>
                        <button type="button" onClick={() => removeRule(index)}>
                          Remove
                        </button>
                      </div>
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
                      placeholder="Human-readable name"
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
                  <label>
                    Rule id (optional)
                    <input
                      type="text"
                      value={selectedRule.id ?? ""}
                      onChange={(e) =>
                        updateRuleAt(selectedRuleIndex!, {
                          id: e.target.value.trim() ? e.target.value : null,
                        })
                      }
                      placeholder="Stable id for traces"
                      autoComplete="off"
                    />
                  </label>

                  <h4>Regex matchers</h4>
                  <p className="muted rule-sets-hint">
                    Matchers run in order; all must match before the CEL expression evaluates. Use a label so
                    you can recognize each matcher in the list.
                  </p>
                  {selectedRule.captures.length === 0 ? (
                    <p className="muted">No matchers (expression always runs).</p>
                  ) : (
                    <ul className="rule-sets-capture-summary">
                      {selectedRule.captures.map((cap, ci) => (
                        <li key={`cap-${ci}`}>
                          <span className="rule-sets-capture-chip">{matcherRowTitle(cap)}</span>
                        </li>
                      ))}
                    </ul>
                  )}

                  <div className="rule-sets-capture-actions">
                    <button type="button" onClick={() => addCapture(selectedRuleIndex!)}>
                      Add matcher
                    </button>
                  </div>

                  {selectedRule.captures.map((cap, ci) => (
                    <fieldset key={`cap-edit-${ci}`} className="rule-sets-capture-fieldset">
                      <legend>
                        Matcher {ci + 1}: {matcherRowTitle(cap)}
                      </legend>
                      <div className="rule-sets-capture-toolbar">
                        <button
                          type="button"
                          onClick={() => moveCapture(selectedRuleIndex!, ci, -1)}
                          disabled={ci === 0}
                        >
                          Move up
                        </button>
                        <button
                          type="button"
                          onClick={() => moveCapture(selectedRuleIndex!, ci, 1)}
                          disabled={ci === selectedRule.captures.length - 1}
                        >
                          Move down
                        </button>
                        <button type="button" onClick={() => removeCapture(selectedRuleIndex!, ci)}>
                          Remove matcher
                        </button>
                      </div>
                      <label>
                        Matcher label
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
                      <label>
                        Attribute
                        <input
                          type="text"
                          value={cap.attribute}
                          onChange={(e) => updateCaptureAt(selectedRuleIndex!, ci, { attribute: e.target.value })}
                          required
                          autoComplete="off"
                        />
                      </label>
                      <label>
                        Pattern
                        <input
                          type="text"
                          value={cap.pattern}
                          onChange={(e) => updateCaptureAt(selectedRuleIndex!, ci, { pattern: e.target.value })}
                          required
                          autoComplete="off"
                        />
                      </label>
                      <div className="rule-sets-flags">
                        {FLAG_OPTIONS.map((f) => (
                          <label key={f.value} className="rule-sets-checkbox">
                            <input
                              type="checkbox"
                              checked={cap.flags.includes(f.value)}
                              onChange={(e) =>
                                toggleFlag(selectedRuleIndex!, ci, f.value, e.target.checked)
                              }
                            />
                            {f.label}
                          </label>
                        ))}
                      </div>
                    </fieldset>
                  ))}

                  <label>
                    CEL expression
                    <textarea
                      value={selectedRule.expression}
                      onChange={(e) => updateRuleAt(selectedRuleIndex!, { expression: e.target.value })}
                      rows={8}
                      className="rule-sets-cel-textarea"
                      spellCheck={false}
                    />
                  </label>
                </>
              )}
            </div>
          </div>
        </form>
      )}
    </section>
  );
}
