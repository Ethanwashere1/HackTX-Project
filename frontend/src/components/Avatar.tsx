function initials(name: string) {
  return name
    .split(/\s+/)
    .map((p) => p[0])
    .join("")
    .slice(0, 2)
    .toUpperCase();
}

export function Avatar({
  name,
  size = 34,
}: {
  name: string;
  size?: number;
}) {
  return (
    <span
      className="su-avatar"
      style={{ width: size, height: size, fontSize: size * 0.32 }}
      aria-hidden
    >
      {initials(name)}
    </span>
  );
}
