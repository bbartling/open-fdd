import type { ReactNode } from "react";
import Spinner from "./Spinner";

type Props = {
  pending?: boolean;
  pendingLabel?: string;
  disabled?: boolean;
  secondary?: boolean;
  onClick?: () => void;
  children: ReactNode;
  type?: "button" | "submit";
};

export default function ActionButton({
  pending = false,
  pendingLabel,
  disabled = false,
  secondary = false,
  onClick,
  children,
  type = "button",
}: Props) {
  return (
    <button
      type={type}
      className={secondary ? "secondary-btn action-btn" : "action-btn"}
      disabled={disabled || pending}
      onClick={onClick}
    >
      {pending ? <Spinner label={pendingLabel} /> : children}
    </button>
  );
}
