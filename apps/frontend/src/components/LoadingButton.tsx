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
      className={`px-3 py-2 rounded-md disabled:opacity-50 ${className}`}
      disabled={disabled || loading}
    >
      {loading ? "…" : children}
    </button>
  );
}
