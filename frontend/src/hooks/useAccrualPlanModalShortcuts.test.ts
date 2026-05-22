import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, renderHook } from "@testing-library/react";

import { useAccrualPlanModalShortcuts } from "./useAccrualPlanModalShortcuts";

afterEach(() => {
  vi.restoreAllMocks();
});

describe("useAccrualPlanModalShortcuts", () => {
  it("closes create form on Escape when create dialog is open", () => {
    const onCreateClose = vi.fn();
    renderHook(() =>
      useAccrualPlanModalShortcuts({
        createDialogOpen: true,
        createDialogView: "form",
        editDialogOpen: false,
        editDialogView: "form",
        viewDialogOpen: false,
        canSubmitCreate: true,
        canSubmitEdit: false,
        createSubmitting: false,
        editSubmitting: false,
        onCreateSave: vi.fn(),
        onEditSave: vi.fn(),
        onCreateClose,
        onEditClose: vi.fn(),
        onViewClose: vi.fn(),
        onCreateReturnToForm: vi.fn(),
        onEditReturnToForm: vi.fn(),
      }),
    );

    fireEvent.keyDown(document, { key: "Escape", code: "Escape", bubbles: true });
    expect(onCreateClose).toHaveBeenCalledTimes(1);
  });

  it("closes create dialog on Escape when create preview is open", () => {
    const onCreateClose = vi.fn();
    renderHook(() =>
      useAccrualPlanModalShortcuts({
        createDialogOpen: true,
        createDialogView: "preview",
        editDialogOpen: false,
        editDialogView: "form",
        viewDialogOpen: false,
        canSubmitCreate: true,
        canSubmitEdit: false,
        createSubmitting: false,
        editSubmitting: false,
        onCreateSave: vi.fn(),
        onEditSave: vi.fn(),
        onCreateClose,
        onEditClose: vi.fn(),
        onViewClose: vi.fn(),
        onCreateReturnToForm: vi.fn(),
        onEditReturnToForm: vi.fn(),
      }),
    );

    fireEvent.keyDown(document, { key: "Escape", code: "Escape", bubbles: true });
    expect(onCreateClose).toHaveBeenCalledTimes(1);
  });

  it("returns to create form on Ctrl+Shift+D when create preview is open", () => {
    const onCreateReturnToForm = vi.fn();
    renderHook(() =>
      useAccrualPlanModalShortcuts({
        createDialogOpen: true,
        createDialogView: "preview",
        editDialogOpen: false,
        editDialogView: "form",
        viewDialogOpen: false,
        canSubmitCreate: true,
        canSubmitEdit: false,
        createSubmitting: false,
        editSubmitting: false,
        onCreateSave: vi.fn(),
        onEditSave: vi.fn(),
        onCreateClose: vi.fn(),
        onEditClose: vi.fn(),
        onViewClose: vi.fn(),
        onCreateReturnToForm,
        onEditReturnToForm: vi.fn(),
      }),
    );

    fireEvent.keyDown(document, {
      key: "d",
      code: "KeyD",
      ctrlKey: true,
      shiftKey: true,
      bubbles: true,
    });
    expect(onCreateReturnToForm).toHaveBeenCalledTimes(1);
  });

  it("opens a new plan from Ctrl+N when no modal is open", () => {
    const onNewPlan = vi.fn();
    renderHook(() =>
      useAccrualPlanModalShortcuts({
        createDialogOpen: false,
        createDialogView: "form",
        editDialogOpen: false,
        editDialogView: "form",
        viewDialogOpen: false,
        canSubmitCreate: false,
        canSubmitEdit: false,
        createSubmitting: false,
        editSubmitting: false,
        onCreateSave: vi.fn(),
        onEditSave: vi.fn(),
        onCreateClose: vi.fn(),
        onEditClose: vi.fn(),
        onViewClose: vi.fn(),
        onCreateReturnToForm: vi.fn(),
        onEditReturnToForm: vi.fn(),
        onNewPlan,
      }),
    );

    fireEvent.keyDown(document, {
      code: "KeyN",
      key: "\u000e",
      ctrlKey: true,
      bubbles: true,
    });
    expect(onNewPlan).toHaveBeenCalledTimes(1);
  });

  it("fires create save from Ctrl+S without focus in the form", () => {
    const onCreateSave = vi.fn();
    renderHook(() =>
      useAccrualPlanModalShortcuts({
        createDialogOpen: true,
        createDialogView: "form",
        editDialogOpen: false,
        editDialogView: "form",
        viewDialogOpen: false,
        canSubmitCreate: true,
        canSubmitEdit: false,
        createSubmitting: false,
        editSubmitting: false,
        onCreateSave,
        onEditSave: vi.fn(),
        onCreateClose: vi.fn(),
        onEditClose: vi.fn(),
        onViewClose: vi.fn(),
        onCreateReturnToForm: vi.fn(),
        onEditReturnToForm: vi.fn(),
      }),
    );

    fireEvent.keyDown(document, {
      key: "s",
      code: "KeyS",
      ctrlKey: true,
      bubbles: true,
    });
    expect(onCreateSave).toHaveBeenCalledTimes(1);
  });
});
