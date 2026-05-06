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
      className="fixed inset-0 bg-black/85 flex items-center justify-center z-[1000] backdrop-blur-sm"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="w-[1000px] max-h-[90vh] rounded-none">
        <ConfigPanel onClose={onClose} />
      </div>
    </div>
  );
}
