/**
 * Agency website cell — one-click "open in new tab" link with icon.
 * The whole cell is an anchor (target=_blank); clicking it opens the
 * agency's site directly instead of the generic text-expand modal.
 */
import { ExternalLink } from "lucide-react";
import type { PropertiesTableRow } from "../types";

export function WebsiteCell({ property }: { property: PropertiesTableRow }) {
  const raw = (property.agency_website ?? "").toString().trim();
  if (!raw) return <span className="text-[var(--muted-foreground)]">—</span>;

  // Normalise so a bare "www.x.nl" still opens correctly.
  const href = /^https?:\/\//i.test(raw) ? raw : `https://${raw}`;
  const label = raw.replace(/^https?:\/\//i, "").replace(/\/$/, "");

  return (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      title={`Open ${label} in new tab`}
      className="inline-flex w-full max-w-full items-center gap-1 overflow-hidden text-[var(--color-brand-600)] hover:underline"
    >
      <span className="truncate">{label}</span>
      <ExternalLink className="h-3.5 w-3.5 shrink-0" />
    </a>
  );
}
