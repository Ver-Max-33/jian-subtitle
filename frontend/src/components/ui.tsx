// Adapted from shadcn/ui Base UI. Fixed upstream source and license: ../THIRD_PARTY.md.
import { useEffect, useRef, useState, type ButtonHTMLAttributes, type CSSProperties, type ReactElement, type ReactNode } from 'react';
import { Dialog } from '@base-ui/react/dialog';
import { Select as SelectPrimitive } from '@base-ui/react/select';
import { Menu as MenuPrimitive } from '@base-ui/react/menu';
import { ContextMenu } from '@base-ui/react/context-menu';
import { Switch as SwitchPrimitive } from '@base-ui/react/switch';
import { Checkbox as CheckboxPrimitive } from '@base-ui/react/checkbox';
import { Tooltip } from '@base-ui/react/tooltip';
import { ToggleGroup } from '@base-ui/react/toggle-group';
import { Toggle } from '@base-ui/react/toggle';
import { Check, ChevronDown, ChevronRight, Minus, Plus, X } from 'lucide-react';
import { useApp } from '../state';
import { isMac, shortcutText } from '../keymap';

type Variant = 'primary' | 'secondary' | 'soft' | 'danger' | 'ghost' | 'link';
type Side = 'top' | 'bottom' | 'left' | 'right';

export function Button({ variant = 'secondary', className = '', children, ...props }: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant }) {
  return <button type="button" className={`button ${variant} ${className}`} {...props}>{children}</button>;
}

/** 500 ms to appear; moving to a neighbour switches at once (Tooltip.Provider in App). */
/** `shortcut` is written the Windows way (「Ctrl+Z」, 「→」); macOS shows ⌘ and ⇧ (spec 4.6). */
export function Tip({ label, shortcut, side = 'top', children }: { label: ReactNode; shortcut?: string; side?: Side; children: ReactElement }) {
  return <Tooltip.Root>
    <Tooltip.Trigger render={children} />
    <Tooltip.Portal><Tooltip.Positioner side={side} sideOffset={8} className="positioner"><Tooltip.Popup className="tooltip">{label}{shortcut && <kbd className="tip-key">{shortcutText(shortcut, isMac)}</kbd>}</Tooltip.Popup></Tooltip.Positioner></Tooltip.Portal>
  </Tooltip.Root>;
}

export function IconButton({ label, shortcut, side, tip = true, active = false, toggled = false, className = '', children, ...props }: ButtonHTMLAttributes<HTMLButtonElement> & { label: string; shortcut?: string; side?: Side; tip?: boolean; active?: boolean; toggled?: boolean }) {
  // Tools are solid blue when active; switches are light blue when on (E5).
  const button = <button type="button" aria-label={label} className={`icon-button ${active ? 'active' : ''} ${toggled ? 'toggled' : ''} ${className}`} {...props}>{children}</button>;
  return tip ? <Tip label={label} shortcut={shortcut} side={side}>{button}</Tip> : button;
}

export interface MenuEntry {
  label?: ReactNode; action?: () => void; danger?: boolean; disabled?: boolean; hint?: ReactNode;
  checked?: boolean; separator?: boolean; heading?: string; children?: MenuEntry[]; keepOpen?: boolean;
}
type MenuParts = typeof MenuPrimitive | typeof ContextMenu;
function entries(Parts: MenuParts, items: MenuEntry[]): ReactNode {
  // A check column only when something in this menu can be checked, so plain menus stay compact.
  const checkable = items.some(item => item.checked !== undefined);
  return items.map((item, i) => {
    if (item.separator) return <Parts.Separator key={i} className="menu-separator" />;
    if (item.heading) return <div key={i} className="menu-heading">{item.heading}</div>;
    if (item.children) return <Parts.SubmenuRoot key={i}>
      <Parts.SubmenuTrigger className="menu-item" disabled={item.disabled}>{checkable && <span className="menu-check" />}<span className="menu-label">{item.label}</span><ChevronRight className="menu-chevron" /></Parts.SubmenuTrigger>
      <Parts.Portal><Parts.Positioner className="positioner" sideOffset={2} alignOffset={-5}><Parts.Popup className="menu-popup">{entries(Parts, item.children)}</Parts.Popup></Parts.Positioner></Parts.Portal>
    </Parts.SubmenuRoot>;
    return <Parts.Item key={i} className={`menu-item ${item.danger ? 'danger' : ''}`} disabled={item.disabled} closeOnClick={!item.keepOpen} onClick={item.action}>
      {checkable && <span className="menu-check">{item.checked && <Check />}</span>}<span className="menu-label">{item.label}</span>{item.hint !== undefined && <span className="menu-hint">{item.hint}</span>}
    </Parts.Item>;
  });
}

export function Menu({ label, items, children, className = 'icon-button', align = 'start', side = 'bottom', tip, disabled }: { label: string; items: MenuEntry[]; children: ReactNode; className?: string; align?: 'start' | 'center' | 'end'; side?: Side; tip?: boolean; disabled?: boolean }) {
  const trigger = <MenuPrimitive.Trigger className={className} aria-label={label} disabled={disabled}>{children}</MenuPrimitive.Trigger>;
  return <MenuPrimitive.Root>
    {tip ? <Tip label={label}>{trigger}</Tip> : trigger}
    <MenuPrimitive.Portal><MenuPrimitive.Positioner className="positioner" side={side} align={align} sideOffset={6} collisionPadding={8}><MenuPrimitive.Popup className="menu-popup">{entries(MenuPrimitive, items)}</MenuPrimitive.Popup></MenuPrimitive.Positioner></MenuPrimitive.Portal>
  </MenuPrimitive.Root>;
}

/** Right-click menu around a row; the row itself stays the trigger element. */
export function RowMenu({ items, children }: { items: MenuEntry[]; children: ReactElement }) {
  return <ContextMenu.Root>
    <ContextMenu.Trigger render={children} />
    <ContextMenu.Portal><ContextMenu.Positioner className="positioner" collisionPadding={8}><ContextMenu.Popup className="menu-popup">{entries(ContextMenu, items)}</ContextMenu.Popup></ContextMenu.Positioner></ContextMenu.Portal>
  </ContextMenu.Root>;
}

export interface Option<T extends string = string> { value: T; label: ReactNode; text?: string; disabled?: boolean; hint?: ReactNode }
export function Select<T extends string>({ value, onChange, options, label, prefix, placeholder = '请选择', mixed = false, disabled = false, className = '', invalid = false, header }: { value: T | ''; onChange: (value: T) => void; options: Option<T>[]; label: string; prefix?: ReactNode; placeholder?: string; mixed?: boolean; disabled?: boolean; className?: string; invalid?: boolean; header?: ReactNode }) {
  const current = options.find(o => o.value === value);
  return <SelectPrimitive.Root value={mixed ? null : value || null} onValueChange={v => { if (v !== null) onChange(v as T); }} disabled={disabled}>
    <SelectPrimitive.Trigger className={`field select ${invalid ? 'invalid' : ''} ${className}`} aria-label={label}>
      {prefix && <span className="field-prefix">{prefix}</span>}
      <span className={`field-value ${mixed || !current ? 'placeholder' : ''}`}>{mixed ? '混合' : current?.label ?? placeholder}</span><ChevronDown className="field-chevron" />
    </SelectPrimitive.Trigger>
    <SelectPrimitive.Portal><SelectPrimitive.Positioner className="positioner" sideOffset={4} align="start" alignItemWithTrigger={false} collisionPadding={8}>
      <SelectPrimitive.Popup className="menu-popup select-popup">{header && <div className="menu-head-block">{header}</div>}<SelectPrimitive.List>{options.map(o => <SelectPrimitive.Item key={o.value} value={o.value} disabled={o.disabled} className="menu-item">
        <span className="menu-check"><SelectPrimitive.ItemIndicator><Check /></SelectPrimitive.ItemIndicator></span><SelectPrimitive.ItemText className="menu-label">{o.label}</SelectPrimitive.ItemText>{o.hint !== undefined && <span className="menu-hint">{o.hint}</span>}
      </SelectPrimitive.Item>)}</SelectPrimitive.List></SelectPrimitive.Popup>
    </SelectPrimitive.Positioner></SelectPrimitive.Portal>
  </SelectPrimitive.Root>;
}

export function Switch({ checked, onChange, label, disabled = false }: { checked: boolean; onChange: (value: boolean) => void; label: string; disabled?: boolean }) {
  return <SwitchPrimitive.Root className="switch" checked={checked} onCheckedChange={onChange} aria-label={label} disabled={disabled}><SwitchPrimitive.Thumb className="switch-thumb" /></SwitchPrimitive.Root>;
}
export function SwitchRow({ label, checked, onChange, disabled }: { label: string; checked: boolean; onChange: (value: boolean) => void; disabled?: boolean }) {
  return <div className="switch-row"><span>{label}</span><Switch label={label} checked={checked} onChange={onChange} disabled={disabled} /></div>;
}

export function Checkbox({ checked, onChange, label, mixed = false, tabIndex, className = '' }: { checked: boolean; onChange: (value: boolean, shift: boolean) => void; label: string; mixed?: boolean; tabIndex?: number; className?: string }) {
  return <CheckboxPrimitive.Root checked={checked} indeterminate={mixed} onCheckedChange={(value, details) => onChange(value, (details.event as MouseEvent | undefined)?.shiftKey === true)} className={`checkbox ${className}`} aria-label={label} tabIndex={tabIndex} onClick={e => e.stopPropagation()}><CheckboxPrimitive.Indicator className="checkbox-mark">{mixed ? <Minus /> : <Check />}</CheckboxPrimitive.Indicator></CheckboxPrimitive.Root>;
}

export function Segmented<T extends string>({ value, onChange, options, label, className = '' }: { value: T | null; onChange: (value: T) => void; options: { value: T; label: ReactNode; disabled?: boolean; title?: string }[]; label: string; className?: string }) {
  const index = options.findIndex(o => o.value === value);
  return <ToggleGroup value={value ? [value] : []} onValueChange={next => { if (next[0]) onChange(next[0] as T); }} aria-label={label}
    className={`segmented ${index < 0 ? 'unset' : ''} ${className}`} style={{ '--segment': Math.max(0, index), '--segments': options.length } as CSSProperties}>
    {options.map(o => <Toggle key={o.value} value={o.value} disabled={o.disabled} title={o.title} className="segment">{o.label}</Toggle>)}
  </ToggleGroup>;
}

const valid = (text: string, min: number, max: number, step: number) => {
  const n = Number(text);
  return text.trim() !== '' && Number.isFinite(n) && n >= min && n <= max && (step < 1 || Number.isInteger(n));
};
/**
 * Inline-labelled number, like the Figma inspector. Enter or blur commits one undoable change; Esc restores;
 * ↑↓ step (Shift ×10); dragging the label scrubs with a live preview and commits on release.
 */
export function NumberField({ label, prefix, value, onCommit, onPreview, min, max, step = 1, unit, mixed = false, disabled = false, className = '', digits = 0, marker, hint }: { label: string; prefix?: ReactNode; value: number; onCommit: (value: number) => void; onPreview?: (value: number | undefined) => void; min: number; max: number; step?: number; unit?: string; mixed?: boolean; disabled?: boolean; className?: string; digits?: number; marker?: ReactNode; hint?: ReactNode }) {
  const shown = (n: number) => (mixed ? '' : String(Number(n.toFixed(digits))));
  const [draft, setDraft] = useState(shown(value));
  const editing = useRef(false);
  // `value` follows the live preview while typing, so a commit compares against the value editing started from.
  const start = useRef(value);
  useEffect(() => { if (!editing.current) setDraft(shown(value)); }, [value, mixed]);
  const invalid = draft !== '' && !valid(draft, min, max, step);
  const clamp = (n: number) => Math.min(max, Math.max(min, Number(n.toFixed(Math.max(digits, step < 1 ? 1 : 0)))));
  const commit = (text: string) => {
    editing.current = false;
    if (text === '' && mixed) { onPreview?.(undefined); return; }
    if (!valid(text, min, max, step)) return;
    const next = Number(text);
    if (mixed || next !== start.current) onCommit(next); else onPreview?.(undefined);
  };
  const scrub = useRef<{ x: number; start: number; last: number; id: number } | null>(null);
  return <label className={`field number ${invalid ? 'invalid' : ''} ${disabled ? 'disabled' : ''} ${className}`} title={invalid ? `请输入 ${min}–${max}${step >= 1 ? ' 的整数' : ''}` : undefined}>
    {marker}
    {prefix !== undefined && <span className="field-prefix scrub" aria-hidden
      onPointerDown={e => {
        if (disabled || e.button !== 0) return;
        e.preventDefault(); e.currentTarget.setPointerCapture(e.pointerId);
        scrub.current = { x: e.clientX, start: mixed ? min : value, last: mixed ? min : value, id: e.pointerId };
      }}
      onPointerMove={e => {
        const s = scrub.current;
        if (!s || s.id !== e.pointerId) return;
        const next = clamp(s.start + Math.round((e.clientX - s.x) / 2) * step * (e.shiftKey ? 10 : 1));
        if (next !== s.last) { s.last = next; setDraft(shown(next)); onPreview?.(next); }
      }}
      onPointerUp={e => { const s = scrub.current; if (!s || s.id !== e.pointerId) return; scrub.current = null; if (s.last !== s.start) onCommit(s.last); else onPreview?.(undefined); }}
      onLostPointerCapture={() => { if (scrub.current) { scrub.current = null; setDraft(shown(value)); onPreview?.(undefined); } }}>{prefix}</span>}
    <input aria-label={label} inputMode="decimal" value={draft} placeholder={mixed ? '混合' : undefined} disabled={disabled} aria-invalid={invalid}
      onFocus={e => { editing.current = true; start.current = value; e.currentTarget.select(); }}
      onChange={e => { const text = e.target.value; setDraft(text); onPreview?.(valid(text, min, max, step) ? Number(text) : undefined); }}
      onBlur={e => commit(e.target.value)}
      onKeyDown={e => {
        if (e.key === 'Enter' && !e.nativeEvent.isComposing) e.currentTarget.blur();
        else if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); editing.current = false; setDraft(shown(value)); onPreview?.(undefined); e.currentTarget.blur(); }
        else if (e.key === 'ArrowUp' || e.key === 'ArrowDown') {
          e.preventDefault();
          const base = valid(draft, min, max, step) ? Number(draft) : mixed ? min : value;
          const next = clamp(base + (e.key === 'ArrowUp' ? 1 : -1) * step * (e.shiftKey ? 10 : 1));
          setDraft(shown(next)); onPreview?.(next);
        }
      }} />
    {unit && <span className="field-suffix">{unit}</span>}
    {hint !== undefined && <span className="field-hint numeric">{hint}</span>}
  </label>;
}

export function TextField({ label, prefix, value, onChange, placeholder, maxLength = 100, className = '', invalid = false }: { label: string; prefix?: ReactNode; value: string; onChange: (value: string) => void; placeholder?: string; maxLength?: number; className?: string; invalid?: boolean }) {
  return <label className={`field ${invalid ? 'invalid' : ''} ${className}`}>{prefix && <span className="field-prefix">{prefix}</span>}<input aria-label={label} value={value} placeholder={placeholder} maxLength={maxLength} aria-invalid={invalid || undefined} onChange={e => onChange(e.target.value)} /></label>;
}

/**
 * An inspector block. `added` false shows only the title and +; list mode collapses blocks behind a chevron.
 * Height changes animate through grid rows, so blocks below slide instead of jumping (motion: 区块展开).
 */
export function Section({ title, note, actions, children, added, onAdd, onRemove, collapsed, onToggle, className = '' }: { title: ReactNode; note?: ReactNode; actions?: ReactNode; children?: ReactNode; added?: boolean; onAdd?: () => void; onRemove?: () => void; collapsed?: boolean; onToggle?: () => void; className?: string }) {
  const toggleable = added !== undefined;
  const open = toggleable ? added : !collapsed;
  return <section className={`section ${open ? 'open' : 'closed'} ${className}`}>
    <header className="section-head">
      {onToggle ? <button type="button" className="section-title toggle" aria-expanded={!collapsed} onClick={onToggle}>{title}<ChevronRight className="section-chevron" /></button> : <h3 className="section-title">{title}</h3>}
      {note}
      <div className="section-actions">{open && actions}
        {toggleable && (added ? <IconButton label={`移除${typeof title === 'string' ? title : ''}`} onClick={onRemove}><Minus /></IconButton> : <IconButton label={`添加${typeof title === 'string' ? title : ''}`} onClick={onAdd}><Plus /></IconButton>)}
      </div>
    </header>
    <div className="section-body" inert={!open}><div className="section-inner">{children}</div></div>
  </section>;
}

export function Highlight({ text, query }: { text: string; query: string }) {
  const needle = query.trim().toLocaleLowerCase();
  if (!needle) return <>{text}</>;
  const lower = text.toLocaleLowerCase(), parts: ReactNode[] = [];
  let from = 0;
  for (let at = lower.indexOf(needle); at >= 0; at = lower.indexOf(needle, from)) {
    parts.push(text.slice(from, at), <mark key={at}>{text.slice(at, at + needle.length)}</mark>);
    from = at + needle.length;
  }
  parts.push(text.slice(from));
  return <>{parts}</>;
}

// Dialogs with a field focus the field; confirmations focus their decision, or 取消 when the decision destroys something.
function firstFocus(popup: HTMLElement | null) {
  const field = popup?.querySelector<HTMLElement>('.dialog-body :is(input:not([type=checkbox]), textarea)');
  const buttons = [...popup?.querySelectorAll<HTMLElement>('.dialog-footer .button') ?? []];
  return field ?? (buttons.at(-1)?.classList.contains('danger') ? buttons[0] : buttons.at(-1)) ?? true;
}
export function Modal({ open, onClose, onClosed, title, children, footer, className = '' }: { open: boolean; onClose: () => void; onClosed?: () => void; title: string; children?: ReactNode; footer?: ReactNode; className?: string }) {
  const { error } = useApp();
  const popup = useRef<HTMLDivElement>(null);
  return <Dialog.Root open={open} onOpenChange={value => { if (!value) onClose(); }} onOpenChangeComplete={value => { if (!value) onClosed?.(); }}>
    <Dialog.Portal><Dialog.Backdrop className="dialog-backdrop" /><Dialog.Popup ref={popup} className={`dialog ${className}`} initialFocus={() => firstFocus(popup.current)}>
      <header className="dialog-header"><Dialog.Title className="dialog-title">{title}</Dialog.Title><Dialog.Close render={<IconButton label="关闭" tip={false} />}><X /></Dialog.Close></header>
      <div className="dialog-body">{children}{error && <p className="dialog-error" role="alert">{error.message}</p>}</div>
      {footer && <footer className="dialog-footer">{footer}</footer>}
    </Dialog.Popup></Dialog.Portal>
  </Dialog.Root>;
}

/** The fixed 幕 mark from the app icon board: dark tile, white character, blue caption bar. */
export function AppMark({ size = 24 }: { size?: number }) {
  return <span className="app-mark" style={{ '--mark': `${size}px` } as CSSProperties} aria-hidden><span>幕</span><i /></span>;
}
