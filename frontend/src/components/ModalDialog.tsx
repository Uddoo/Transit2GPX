import { useEffect, useRef, type ReactNode } from "react";

export function ModalDialog({
  children,
  className,
  labelledBy,
  onClose,
}: {
  children: ReactNode;
  className: string;
  labelledBy: string;
  onClose: () => void;
}) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const returnFocusRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    returnFocusRef.current =
      document.activeElement instanceof HTMLElement ? document.activeElement : null;
    dialog.showModal();
    return () => {
      if (dialog.open) dialog.close();
      returnFocusRef.current?.focus();
    };
  }, []);

  return (
    <dialog
      aria-labelledby={labelledBy}
      className={className}
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
      ref={dialogRef}
    >
      {children}
    </dialog>
  );
}
