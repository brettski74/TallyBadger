import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import { RegisterListCard, RegisterListChrome, RegisterListTable } from "./RegisterListLayout";

describe("RegisterListLayout", () => {
  it("renders shared register scroll structure with tbody inside scroll area", () => {
    render(
      <RegisterListCard>
        <RegisterListChrome>
          <h2>Example register</h2>
        </RegisterListChrome>
        <RegisterListTable
          aria-label="Example register"
          header={
            <tr>
              <th>Name</th>
            </tr>
          }
        >
          <tr>
            <td>Row</td>
          </tr>
        </RegisterListTable>
      </RegisterListCard>,
    );

    expect(screen.getByRole("heading", { name: "Example register" })).toBeInTheDocument();
    const area = screen.getByTestId("register-list-table-area");
    expect(area.querySelector(".register-list-table-scroll-x")).toBeTruthy();
    const table = screen.getByRole("table", { name: "Example register" });
    expect(table).toHaveClass("register-list-table");
    expect(table.querySelector("thead")).toBeTruthy();
    expect(table.querySelector("tbody")).toBeTruthy();
    expect(screen.getByRole("cell", { name: "Row" })).toBeInTheDocument();
  });
});
