/** Значок Tabler (webfont). size: s = 16, по умолчанию 20, l = 24, xl = 40. */
export function Icon({ name, size, className }: { name: string; size?: 's' | 'l' | 'xl'; className?: string }) {
  return <i className={`ti ti-${name}${size ? ' ' + size : ''}${className ? ' ' + className : ''}`} aria-hidden="true" />;
}
