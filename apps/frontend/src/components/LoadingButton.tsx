export default function LoadingButton({
  children,
  loading,
  className = "",
  disabled,
  ...rest
}: React.ButtonHTMLAttributes<HTMLButtonElement> & {
  loading?: boolean;
}) {
  return (
    <button
      {...rest}
      className={`inline-flex items-center px-3 py-2 rounded-md text-sm font-medium disabled:opacity-50 focus:outline-none focus:ring-2 focus:ring-offset-1 ${className}`}
      disabled={disabled || loading}
    >
      {loading ? "…" : children}
    </button>
  );
}
