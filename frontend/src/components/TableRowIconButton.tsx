import type { ButtonHTMLAttributes, ReactNode } from "react";

type TableRowIconButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  children: ReactNode;
};

/** Fixed 32×32 CSS px hit target for compact table row actions (see global `.table-row-icon-button`). */
export function TableRowIconButton({
  children,
  className = "",
  type = "button",
  ...rest
}: TableRowIconButtonProps) {
  return (
    <button type={type} className={["table-row-icon-button", className].filter(Boolean).join(" ")} {...rest}>
      {children}
    </button>
  );
}
