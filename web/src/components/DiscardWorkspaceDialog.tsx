import { useEffect, useRef } from 'react'
import { TriangleAlert } from 'lucide-react'
import { Button } from './ui'

export function DiscardWorkspaceDialog({
  open, hasProgress, onCancel, onConfirm,
}: {
  open: boolean
  hasProgress: boolean
  onCancel: () => void
  onConfirm: () => void
}) {
  const dialogRef = useRef<HTMLDialogElement>(null)

  useEffect(() => {
    const dialog = dialogRef.current
    if (!dialog) return
    if (open && !dialog.open) dialog.showModal()
    if (!open && dialog.open) dialog.close()
  }, [open])

  return (
    <dialog
      ref={dialogRef}
      role="alertdialog"
      aria-modal="true"
      aria-labelledby="discard-workspace-title"
      aria-describedby="discard-workspace-description"
      className="discard-workspace-dialog w-[min(430px,calc(100%-34px))] border border-c4
                 bg-c0 p-0 text-c9 shadow-[var(--shadow-float)]"
      onCancel={(event) => {
        event.preventDefault()
        onCancel()
      }}
      onClick={(event) => {
        if (event.target === event.currentTarget) onCancel()
      }}
    >
      <div>
        <header className="flex items-center gap-[9px] border-b border-c3 px-[17px] py-[13px]">
          <span className="grid h-[27px] w-[27px] shrink-0 place-items-center border
                           border-danger-line bg-danger-wash text-danger">
            <TriangleAlert size={15} strokeWidth={1.8} aria-hidden />
          </span>
          <h2 id="discard-workspace-title" className="text-[14px] font-semibold">
            Return to access options?
          </h2>
        </header>

        <div className="px-[17px] py-[17px]">
          <p id="discard-workspace-description" className="text-[13px] leading-[1.6] text-c8">
            {hasProgress
              ? 'Your current run, conversation, revisions, and unsaved changes will be removed from this browser. This cannot be undone.'
              : 'Any unsaved workspace changes will be discarded. You will return to the demo or bring-your-own-API choice.'}
          </p>
          <p className="mt-[8px] text-[11.5px] leading-[1.5] text-c6">
            Download anything you need before leaving the workspace.
          </p>
        </div>

        <footer className="flex justify-end gap-[7px] border-t border-c3 bg-c1 px-[13px] py-[11px]">
          <Button intent="outline" size="md" onClick={onCancel} autoFocus>
            Stay here
          </Button>
          <Button intent="danger" size="md" onClick={onConfirm}>
            Leave workspace
          </Button>
        </footer>
      </div>
    </dialog>
  )
}
