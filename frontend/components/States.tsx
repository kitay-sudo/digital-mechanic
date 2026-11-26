import { Icon } from './Icon';

export function Loading({ text = 'Загружаю…' }: { text?: string }) {
  return (
    <div className="center">
      <Icon name="loader-2" size="l" className="spin" />
      <div>{text}</div>
    </div>
  );
}

export function ErrorState({ text, onRetry }: { text: string; onRetry: () => void }) {
  return (
    <div className="center">
      <Icon name="plug-connected-x" size="xl" />
      <div className="e1">Не получилось загрузить</div>
      <div>{text}</div>
      <button type="button" className="btn" onClick={onRetry}>
        <Icon name="refresh" />
        Повторить
      </button>
    </div>
  );
}
