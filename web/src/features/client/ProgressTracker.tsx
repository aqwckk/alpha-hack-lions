import { IconAlertTriangle, IconCheck, IconMinus, IconX } from '@tabler/icons-react';
import type { ProgressStep } from '@/shared/api/types';

const STATE_TEXT: Record<ProgressStep['state'], string> = {
  DONE: 'выполнено',
  CURRENT: 'текущий шаг',
  ACTION_REQUIRED: 'нужно ваше действие',
  PENDING: 'впереди',
  SKIPPED: 'не потребовался',
  STOPPED: 'остановлено',
};

const CLASS: Record<ProgressStep['state'], string> = {
  DONE: 'is-done',
  CURRENT: 'is-current',
  ACTION_REQUIRED: 'is-action',
  PENDING: '',
  SKIPPED: 'is-skipped',
  STOPPED: 'is-stopped',
};

/** 8-step progress of the application; each state has an icon and a text, not only a color. */
export function ProgressTracker({ steps }: { steps: ProgressStep[] }) {
  return (
    <ol className="progress-track" aria-label="Этапы заявки">
      {steps.map((s) => (
        <li key={s.step} className={`progress-step ${CLASS[s.state]}`} aria-current={s.state === 'CURRENT' || s.state === 'ACTION_REQUIRED' ? 'step' : undefined}>
          <span className="progress-dot" aria-hidden>
            {s.state === 'DONE' && <IconCheck size={16} stroke={3} />}
            {s.state === 'ACTION_REQUIRED' && <IconAlertTriangle size={16} />}
            {s.state === 'STOPPED' && <IconX size={16} />}
            {s.state === 'SKIPPED' && <IconMinus size={16} />}
            {(s.state === 'CURRENT' || s.state === 'PENDING') && <span>{s.step}</span>}
          </span>
          <span>
            {s.title}
            <span className="visually-hidden">: {STATE_TEXT[s.state]}</span>
            {(s.note || s.state === 'SKIPPED') && <span className="progress-note"> {s.note ?? STATE_TEXT.SKIPPED}</span>}
          </span>
        </li>
      ))}
    </ol>
  );
}
