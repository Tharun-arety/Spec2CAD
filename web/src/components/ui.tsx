/**
 * Primitives.
 *
 * Hue is reserved for meaning: accent for selection and the primary action,
 * danger/success/warn for outcomes. Nothing relies on hue alone -- every status
 * also carries a glyph and a weight change, so the interface still reads if you
 * cannot separate red from green, or if it is printed.
 */
import { cva, type VariantProps } from 'class-variance-authority'
import * as TooltipPrimitive from '@radix-ui/react-tooltip'
import type { ReactNode } from 'react'
import { cn } from '../lib/cn'

/* --------------------------------------------------------------- buttons */

const buttonVariants = cva(
  'inline-flex cursor-pointer select-none items-center justify-center gap-1.5 whitespace-nowrap ' +
  'rounded-[--radius-sm] border font-medium ' +
  'transition-[background-color,border-color,color,box-shadow] duration-150 ' +
  'disabled:cursor-not-allowed disabled:opacity-45',
  {
    variants: {
      intent: {
        solid:
          'border-accent bg-accent text-accent-fg shadow-[var(--shadow-raised)] ' +
          'hover:border-accent-hover hover:bg-accent-hover',
        outline:
          'border-c4 bg-c0 text-c8 shadow-[var(--shadow-raised)] ' +
          'hover:border-c5 hover:text-c9',
        ghost: 'border-transparent bg-transparent text-c7 hover:bg-c2 hover:text-c9',
        danger:
          'border-danger-line bg-danger-wash text-danger hover:border-danger',
      },
      size: {
        sm: 'h-[29px] px-[13px] text-[11px]',
        md: 'h-[34px] px-[21px] text-[14px]',
      },
    },
    defaultVariants: { intent: 'outline', size: 'sm' },
  },
)

export function Button({
  intent, size, className, ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement> & VariantProps<typeof buttonVariants>) {
  return <button className={cn(buttonVariants({ intent, size }), className)} {...props} />
}

/* ----------------------------------------------------------------- marks */

export const GLYPH: Record<string, string> = {
  pass: '✓', fail: '✕', warn: '!', skipped: '–',
}

const markVariants = cva(
  'inline-flex items-center gap-1 whitespace-nowrap text-[11px] leading-[1.4]',
  {
    variants: {
      state: {
        fail: 'font-semibold text-danger',
        pass: 'font-normal text-success',
        warn: 'font-medium text-warn',
        skipped: 'font-normal text-c6',
      },
      box: { true: 'rounded-[--radius-sm] border px-[6px] py-[1px]', false: '' },
    },
    compoundVariants: [
      { box: true, state: 'fail', class: 'border-danger-line bg-danger-wash' },
      { box: true, state: 'pass', class: 'border-success-line bg-success-wash' },
      { box: true, state: 'warn', class: 'border-warn-line bg-warn-wash' },
      { box: true, state: 'skipped', class: 'border-c4 bg-c2' },
    ],
    defaultVariants: { state: 'pass', box: false },
  },
)

export function Mark({
  state, box, glyph, children, className,
}: VariantProps<typeof markVariants> & {
  glyph?: boolean
  children?: ReactNode
  className?: string
}) {
  const key = (state ?? 'pass') as string
  return (
    <span className={cn(markVariants({ state, box }), className)}>
      {glyph && <span aria-hidden className="num text-[10px] leading-none">{GLYPH[key]}</span>}
      {children}
    </span>
  )
}

/* -------------------------------------------------------------- numerals */

export function Num({
  value, unit, strong, className,
}: { value: ReactNode; unit?: string | null; strong?: boolean; className?: string }) {
  return (
    <span className={cn('num text-[12.5px]', strong && 'font-semibold', className)}>
      {value}
      {unit && <span className="ml-[3px] text-[10.5px] font-normal text-c6">{unit}</span>}
    </span>
  )
}

/* -------------------------------------------------------------- tooltips */

export function Tip({ label, children, side = 'top' }: {
  label: ReactNode
  children: ReactNode
  side?: 'top' | 'right' | 'bottom' | 'left'
}) {
  return (
    <TooltipPrimitive.Provider delayDuration={250}>
      <TooltipPrimitive.Root>
        <TooltipPrimitive.Trigger asChild>{children}</TooltipPrimitive.Trigger>
        <TooltipPrimitive.Portal>
          <TooltipPrimitive.Content
            side={side}
            sideOffset={8}
            className="z-50 max-w-[300px] rounded-[--radius-sm] bg-c9 px-[10px] py-[6px]
                       text-[11px] leading-snug text-c1 shadow-[var(--shadow-float)]"
          >
            {label}
          </TooltipPrimitive.Content>
        </TooltipPrimitive.Portal>
      </TooltipPrimitive.Root>
    </TooltipPrimitive.Provider>
  )
}

/* ----------------------------------------------------------- panel parts */

export function PanelHead({ title, note, aside }: {
  title: string
  note?: ReactNode
  aside?: ReactNode
}) {
  return (
    <div className="sticky top-0 z-10 flex items-center gap-[8px] border-b border-c3
                    bg-c0/90 px-[13px] py-[10px] backdrop-blur-md">
      <h2 className="text-[14px] font-semibold tracking-[-0.011em]">{title}</h2>
      {note && <span className="truncate text-[11px] text-c6">{note}</span>}
      {aside && <div className="ml-auto flex items-center gap-[5px]">{aside}</div>}
    </div>
  )
}

/** A labelled field row, the way a CAD properties panel lists them. */
export function Field({ label, children, dense }: {
  label: ReactNode
  children: ReactNode
  dense?: boolean
}) {
  return (
    <div className={cn(
      'flex items-baseline gap-[13px] border-b border-c3 px-[13px]',
      dense ? 'py-[5px]' : 'py-[8px]',
    )}>
      <span className="w-[123px] shrink-0 truncate text-[11px] text-c7">{label}</span>
      <span className="min-w-0 flex-1 text-[12.5px]">{children}</span>
    </div>
  )
}

export function Empty({ children }: { children: ReactNode }) {
  return (
    <p className="px-[21px] py-[34px] text-center text-[12.5px] leading-relaxed text-c6">
      {children}
    </p>
  )
}
