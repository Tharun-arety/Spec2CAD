import { cn } from '../lib/cn'

/** A plate, governed bore and four measured mounting points—the product in one mark. */
export function Spec2CADMark({ size = 28, className }: { size?: number; className?: string }) {
  return (
    <svg
      viewBox="0 0 32 32"
      width={size}
      height={size}
      fill="none"
      className={cn('text-accent', className)}
      aria-hidden
    >
      <path d="M6.5 5.5h19v21h-19z" stroke="currentColor" strokeWidth="1.35" />
      <circle cx="16" cy="16" r="5.1" stroke="currentColor" strokeWidth="1.35" />
      <circle cx="10" cy="10" r="1.35" fill="currentColor" />
      <circle cx="22" cy="10" r="1.35" fill="currentColor" />
      <circle cx="10" cy="22" r="1.35" fill="currentColor" />
      <circle cx="22" cy="22" r="1.35" fill="currentColor" />
      <path d="M3 16h7.8M21.2 16H29M16 2v8.8M16 21.2V30" stroke="currentColor"
            strokeWidth=".8" strokeDasharray="1.5 1.5" opacity=".72" />
      <path d="m4 5.5 2.5-2.5M25.5 29l2.5-2.5" stroke="currentColor" strokeWidth="1" />
    </svg>
  )
}
/** Decorative measured projection used as the entry page's characteristic object. */
export function IntentBlueprint() {
  return (
    <div className="instrument-plot mt-[26px] hidden h-[154px] overflow-hidden lg:block"
         aria-hidden>
      <svg viewBox="0 0 420 154" className="h-full w-full text-accent">
        <g fill="none" stroke="currentColor">
          <path d="M118 31h132l32 32v60H86V63z" strokeWidth="1.35" opacity=".8" />
          <circle cx="184" cy="77" r="27" strokeWidth="1.2" />
          <circle cx="113" cy="56" r="5" strokeWidth="1.1" />
          <circle cx="255" cy="56" r="5" strokeWidth="1.1" />
          <circle cx="113" cy="108" r="5" strokeWidth="1.1" />
          <circle cx="255" cy="108" r="5" strokeWidth="1.1" />
          <path d="M184 18v118M69 77h231" strokeWidth=".7" strokeDasharray="4 4" opacity=".45" />
          <path d="M86 134v10M282 134v10M86 141h196M82 138l4 3-4 3M286 138l-4 3 4 3"
                strokeWidth=".8" opacity=".7" />
          <path d="M305 39h73M305 77h73M305 115h73" strokeWidth=".8" opacity=".3" />
          <path d="M316 31v92" strokeWidth="1" opacity=".5" />
          <path d="m311 42 5-5 5 5M311 80l5-5 5 5M311 118l5-5 5 5"
                strokeWidth="1" opacity=".8" />
        </g>
        <g fill="currentColor" fontFamily="IBM Plex Mono, monospace" fontSize="8.5">
          <text x="171" y="151" opacity=".72">196.00</text>
          <text x="328" y="40" opacity=".9">EVIDENCE</text>
          <text x="328" y="78" opacity=".9">FEATURE IR</text>
          <text x="328" y="116" opacity=".9">MEASURED</text>
          <text x="190" y="73" opacity=".85">Ø54</text>
          <text x="190" y="85" opacity=".55">H7</text>
        </g>
      </svg>
    </div>
  )
}
