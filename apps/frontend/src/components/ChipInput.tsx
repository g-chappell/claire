import { useMemo } from "react";

export default function ChipInput({
  label,
  value,
  onChange,
  placeholder,
  disabled,
}: {
  label: string;
  value: string[];
  onChange: (next: string[]) => void;
  placeholder?: string;
  disabled?: boolean;
}) {
  const csv = useMemo(() => value.join(", "), [value]);

  function parseAndSet(s: string) {
    const next = s
      .split(",")
      .map((x) => x.trim())
      .filter(Boolean);
    onChange(next);
  }

  return (
    <div>
      <label className="block text-sm mb-1 opacity-80">{label}</label>
      <input
        className="w-full rounded-md bg-white border border-slate-300 px-3 py-2 text-sm text-slate-900 placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500"
        placeholder={placeholder ?? "comma, separated, values"}
        value={csv}
        onChange={(e) => parseAndSet(e.target.value)}
        disabled={disabled}
      />
      {!!value.length && (
        <div className="mt-2 flex flex-wrap gap-1">
          {value.map((v) => (
            <span
              key={v}
              className="px-2 py-0.5 rounded-full text-xs bg-indigo-50 border border-indigo-100 text-indigo-800"
            >
              {v}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
