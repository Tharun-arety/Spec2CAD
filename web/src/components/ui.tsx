/**
 * Monochrome primitives.
 *
 * With no colour available, state is carried by weight, fill, rule thickness,
 * hatching and an explicit glyph. Nothing in this file relies on hue, so every
 * status remains legible to anyone who cannot separate red from green -- and
 * every pairing sits at a neutral contrast well above 4.5:1.
 */
import { cva, type VariantProps } from 'class-variance-authority'
import * as TooltipPrimitive from '@radix-ui/react-tooltip'
import type { ReactNode } from 'react'
import { cn } from '../lib/cn'

/* --------------------------------------------------------------- buttons */

const buttonVariants = cva(
  'inline-flex cursor-pointer select-none items-center justify-center gap-1.5 whitespace-nowrap ' +
  'border font-medium transition-[background-color,border-color,color] duration-100 ' +
  'disabled:cursor-not-allowed disabled:opacity-40',
  {
    variants: {
      intent: {
        solid: 'border-c9 bg-c9 text-c0 hover:bg-c8 hover:border-c8',
        outline: 'border-c4 bg-c0 text-c9 hover:border-c9',
        ghost: 'border-transparent bg-transparent text-c7 hover:bg-c2 hover:text-c9',
      },
      size: {
        sm: 'h-[26px] px-2.5 text-[12px]',
        md: 'h-[32px] px-3.5 text-[12.5px]',
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
        /* failure is the heaviest thing on screen; everything else recedes */
        fail: 'font-semibold text-c9',
        pass: 'font-normal text-c7',
        warn: 'font-medium text-c8',
        skipped: 'font-normal text-c6',
      },
      box: { true: 'border px-1.5 py-px', false: '' },
    },
    compoundVariants: [
      { box: true, state: 'fail', class: 'border-c9 bg-c9 text-c0' },
      { box: true, state: 'pass', class: 'border-c4 bg-c0' },
      { box: true, state: 'warn', class: 'border-c8 bg-c0' },
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
    <span className={cn('num text-[12px]', strong && 'font-semibold', className)}>
      {value}
      {unit && <span className="ml-0.5 text-[10.5px] text-c6">{unit}</span>}
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
            sideOffset={6}
            className="z-50 max-w-[300px] border border-c9 bg-c9 px-2.5 py-1.5
                       text-[11.5px] leading-snug text-c0"
          >
            {label}
          </TooltipPrimitive.Content>
        </TooltipPrimitive.Portal>
      </TooltipPrimitive.Root>
    </TooltipPrimitive.Provider>
  )
}

/* ----------------------------------------------------------- panel parts */

/** Section heading inside the inspector. Sentence case, no eyebrow labels. */
export function PanelHead({ title, note, aside }: {
  title: string
  note?: ReactNode
  aside?: ReactNode
}) {
  return (
    <div className="sticky top-0 z-10 flex items-center gap-2 border-b border-c3
                    bg-c0/95 px-3.5 py-2.5 backdrop-blur-sm">
      <h2 className="text-[12.5px] font-semibold">{title}</h2>
      {note && <span className="truncate text-[11.5px] text-c6">{note}</span>}
      {aside && <div className="ml-auto flex items-center gap-1.5">{aside}</div>}
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
      'flex items-baseline gap-3 border-b border-c3 px-3.5',
      dense ? 'py-1.5' : 'py-2',
    )}>
      <span className="w-[124px] shrink-0 truncate text-[11.5px] text-c7">{label}</span>
      <span className="min-w-0 flex-1 text-[12px]">{children}</span>
    </div>
  )
}

export function Empty({ children }: { children: ReactNode }) {
  return (
    <p className="px-6 py-10 text-center text-[12px] leading-relaxed text-c6">{children}</p>
  )
}

/* ----------------------------------------------------------------- stamp */

export function ReleaseStamp({ blocked }: { blocked: boolean }) {
  return (
    <div
      className={cn('stamp', blocked ? 'stamp-blocked' : 'stamp-released')}
      role="img"
      aria-label={blocked ? 'Not for manufacture' : 'Released'}
    >
      {blocked ? <>Not for<br />manufacture</> : <>Released</>}
    </div>
  )
}
