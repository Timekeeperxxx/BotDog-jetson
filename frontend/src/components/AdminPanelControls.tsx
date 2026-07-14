import type { ReactNode } from 'react';

export function FormRow({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-1.5">
      <label className="text-[9px] font-bold uppercase tracking-[0.2em] text-zinc-400">{label}</label>
      {children}
    </div>
  );
}

export function TextInput({ value, onChange, placeholder, disabled }: {
  value: string; onChange: (v: string) => void; placeholder?: string; disabled?: boolean;
}) {
  return (
    <input
      type="text"
      value={value}
      onChange={e => onChange(e.target.value)}
      placeholder={placeholder}
      disabled={disabled}
      className="bg-zinc-950 border border-zinc-700 px-3 py-2 text-xs text-white font-mono
        focus:outline-none focus:border-white transition-all placeholder-zinc-600
        disabled:opacity-40 disabled:cursor-not-allowed w-full"
    />
  );
}

export function Toggle({ checked, onChange, label, disabled }: {
  checked: boolean; onChange: (v: boolean) => void; label: string; disabled?: boolean;
}) {
  return (
    <label className="flex items-center gap-3 cursor-pointer select-none">
      <div className="relative" onClick={() => !disabled && onChange(!checked)}>
        <div className={`w-9 h-[18px] border transition-all ${
          checked ? 'bg-white border-white' : 'bg-zinc-900 border-zinc-600'
        }`} />
        <div className={`absolute top-[1px] w-4 h-4 transition-transform duration-200 ${
          checked ? 'translate-x-[18px] bg-black' : 'translate-x-[1px] bg-zinc-500'
        }`} />
      </div>
      <span className={`text-[10px] font-bold uppercase tracking-[0.15em] ${
        checked ? 'text-white' : 'text-zinc-500'
      }`}>{label}</span>
    </label>
  );
}
