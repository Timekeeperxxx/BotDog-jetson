import { ConfigPanel } from '../ConfigPanel';
import { hasAuthSession, hasRole, useAuthState } from '../../stores/authStore';

export interface ConfigModalProps {
  isOpen: boolean;
  onClose: () => void;
}

export function ConfigModal({ isOpen, onClose }: ConfigModalProps) {
  useAuthState()
  if (!hasAuthSession() || !hasRole('admin')) return null
  if (!isOpen) return null;

  return (
    <div
      className="fixed inset-0 z-[1000] flex items-center justify-center bg-black/80 px-4"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="w-full max-w-[1000px]">
        <ConfigPanel onClose={onClose} />
      </div>
    </div>
  );
}
