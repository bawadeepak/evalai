import * as RadixDialog from '@radix-ui/react-dialog'
import type { ReactNode } from 'react'

type Props = {
  open: boolean
  onOpenChange: (open: boolean) => void
  title: string
  description?: ReactNode
  children?: ReactNode
  footer?: ReactNode
}

export function Dialog({ open, onOpenChange, title, description, children, footer }: Props) {
  return (
    <RadixDialog.Root open={open} onOpenChange={onOpenChange}>
      <RadixDialog.Portal>
        <RadixDialog.Overlay className="dialog-overlay" />
        <RadixDialog.Content className="dialog" aria-describedby={description ? undefined : undefined}>
          <RadixDialog.Title asChild>
            <h2>{title}</h2>
          </RadixDialog.Title>
          {description ? (
            <RadixDialog.Description asChild>
              <div className="muted">{description}</div>
            </RadixDialog.Description>
          ) : (
            <RadixDialog.Description className="sr-only">{title}</RadixDialog.Description>
          )}
          {children}
          {footer && <div className="row" style={{ justifyContent: 'flex-end' }}>{footer}</div>}
        </RadixDialog.Content>
      </RadixDialog.Portal>
    </RadixDialog.Root>
  )
}

/** A concise confirmation for actions that interrupt active work (e.g. cancelling a run). */
export function ConfirmDialog({
  open,
  onOpenChange,
  title,
  description,
  confirmLabel,
  onConfirm,
  busy,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  title: string
  description: ReactNode
  confirmLabel: string
  onConfirm: () => void
  busy?: boolean
}) {
  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title={title}
      description={description}
      footer={
        <>
          <button type="button" className="btn" onClick={() => onOpenChange(false)}>
            Keep running
          </button>
          <button type="button" className="btn btn-danger" onClick={onConfirm} disabled={busy}>
            {confirmLabel}
          </button>
        </>
      }
    />
  )
}
