export default function KeyValueInput({
  label,
  value,
  onChange,
  placeholder,
  disabled,
}: {
  label: string;
  value: Record<string, string>;
  onChange: (next: Record<string, string>) => void;
  placeholder?: string;
  disabled?: boolean;
}) {
  function toText(obj: Record<string, string>) {
    return Object.entries(obj)
      .map(([k, v]) => `${k}:${v}`)
      .join(", ");
  }
  function fromText(s: string) {
    const out: Record<string, string> = {};
    s.split(",")
      .map((x) => x.trim())
      .filter(Boolean)
      .forEach((pair) => {
        const [k, ...rest] = pair.split(":");
        if (!k || !rest.length) return;
        out[k.trim()] = rest.join(":").trim();
      });
    return out;
  }
  return (
    <div>
      <label className="block text-sm mb-1 opacity-80">{label}</label>
      <input
        className="w-full rounded bg-slate-800 border border-slate-700 px-3 py-2"
        placeholder={placeholder ?? "api:REST, db:SQLite"}
        value={toText(value)}
        onChange={(e) => onChange(fromText(e.target.value))}
        disabled={disabled}
      />
    </div>
  );
}
