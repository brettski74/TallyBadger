import type { ReactNode } from "react";

/** Full-height register card; pair with {@link RegisterListChrome} and {@link RegisterListTable}. */
export function RegisterListCard({
  className,
  children,
}: {
  className?: string;
  children: ReactNode;
}) {
  const classes = ["card", "journal-card-wide", "register-list-card", className].filter(Boolean).join(" ");
  return <section className={classes}>{children}</section>;
}

/** Toolbar, filters, and list-level status messages (does not scroll with tbody). */
export function RegisterListChrome({ children }: { children: ReactNode }) {
  return <div className="register-list-chrome">{children}</div>;
}

type RegisterListTableProps = {
  "aria-label"?: string;
  className?: string;
  header: ReactNode;
  children: ReactNode;
};

/** Semantic table with fixed thead and vertically scrolling tbody. */
export function RegisterListTable({
  "aria-label": ariaLabel,
  className,
  header,
  children,
}: RegisterListTableProps) {
  const tableClass = className ? `register-list-table ${className}` : "register-list-table";
  return (
    <div className="register-list-table-area" data-testid="register-list-table-area">
      <div className="register-list-table-scroll-x">
        <table className={tableClass} aria-label={ariaLabel}>
          <thead>{header}</thead>
          <tbody>{children}</tbody>
        </table>
      </div>
    </div>
  );
}
