"use client";

import { use, useEffect, useState } from "react";
import Link from "next/link";
import {
  ArrowLeft,
  Building2,
  Check,
  ExternalLink,
  Loader2,
  Mail,
  Phone,
  Save,
  Globe,
  MapPin,
  Calendar,
  Euro,
  Zap,
  Home,
  Ruler,
  Bed,
  Car,
  TrendingUp,
  Sparkles,
} from "lucide-react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { propertiesApi, type Property } from "@/lib/api/properties";
import { PageContainer } from "@/components/page-container";
import { EmailModal } from "@/components/email-modal";
import { cn, formatDate } from "@/lib/utils";

const EMAIL_STATUSES = [
  { value: "not_sent", label: "Not sent" },
  { value: "queued", label: "Queued" },
  { value: "sent", label: "Sent" },
  { value: "failed", label: "Failed" },
  { value: "replied", label: "Replied" },
];

export default function PropertyProfilePage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const numericId = Number(id);
  const qc = useQueryClient();
  const [showEmail, setShowEmail] = useState(false);
  const [notes, setNotes] = useState<string | null>(null);
  const [status, setStatus] = useState<string | null>(null);
  const [bidding, setBidding] = useState<string | null>(null);
  const [biddingBaseline, setBiddingBaseline] = useState<string>("");

  const { data: prop, isLoading, error } = useQuery({
    queryKey: ["properties", "detail", numericId],
    queryFn: () => propertiesApi.get(numericId),
    enabled: Number.isFinite(numericId),
    refetchInterval: 15_000,
  });

  // Sync bidding baseline from backend (without nuking user's in-flight typing).
  // setState-in-effect is the documented prop-sync pattern in React 19.
  useEffect(() => {
    if (!prop) return;
    const v = prop.bidding_price ?? "";
    if (v !== biddingBaseline) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setBiddingBaseline(v);
      if (bidding === null) setBidding(v);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [prop?.bidding_price]);

  const saveM = useMutation({
    mutationFn: (patch: { notes?: string; email_status?: string; bidding_price?: string }) =>
      propertiesApi.update(numericId, patch),
    onSuccess: (updated) => {
      qc.setQueryData(["properties", "detail", numericId], updated);
      qc.invalidateQueries({ queryKey: ["properties", "list"] });
      toast.success("Saved");
    },
    onError: () => toast.error("Save failed"),
  });

  if (isLoading) {
    return (
      <PageContainer>
        <div className="card grid place-items-center p-10">
          <Loader2 className="h-6 w-6 animate-spin text-[var(--color-brand-600)]" />
        </div>
      </PageContainer>
    );
  }
  if (error || !prop) {
    return (
      <PageContainer>
        <div className="card p-6">
          <p className="text-sm text-rose-700">Property not found.</p>
          <Link href="/data" className="btn-outline mt-4">
            <ArrowLeft className="h-4 w-4" />
            Back to data
          </Link>
        </div>
      </PageContainer>
    );
  }

  const effectiveNotes = notes ?? prop.notes ?? "";
  const effectiveStatus = status ?? prop.email_status ?? "not_sent";
  const effectiveBidding = bidding ?? prop.bidding_price ?? "";
  const biddingDirty = effectiveBidding !== biddingBaseline;

  return (
    <PageContainer>
      {/* Header card */}
      <div className="card flex flex-wrap items-start justify-between gap-4 p-6">
        <div className="min-w-0">
          <Link
            href="/data"
            className="inline-flex items-center gap-1 text-xs text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
          >
            <ArrowLeft className="h-3.5 w-3.5" />
            Back to Global Data
          </Link>
          <h2 className="mt-2 truncate text-xl font-semibold">{prop.address ?? "Unnamed property"}</h2>
          <a
            href={prop.url}
            target="_blank"
            rel="noopener noreferrer"
            className="mt-1 inline-flex items-center gap-1 text-xs text-[var(--color-brand-600)] hover:underline"
          >
            View on Funda
            <ExternalLink className="h-3 w-3" />
          </a>
        </div>
        <div className="flex flex-col items-end gap-2">
          <button type="button" className="btn-primary" onClick={() => setShowEmail(true)}>
            <Mail className="h-4 w-4" />
            Send email
          </button>
          <select
            className="input max-w-[200px]"
            value={effectiveStatus}
            onChange={(e) => {
              const v = e.target.value;
              setStatus(v);
              saveM.mutate({ email_status: v });
            }}
          >
            {EMAIL_STATUSES.map((s) => (
              <option key={s.value} value={s.value}>
                {s.label}
              </option>
            ))}
          </select>
        </div>
      </div>

      {/* Bento grid */}
      <div className="mt-6 grid grid-cols-1 gap-4 md:grid-cols-6 md:grid-rows-[auto_auto_auto]">
        {/* Big bidding tile — top left, 3 cols × 2 rows */}
        <Bento className="md:col-span-3 md:row-span-2 bg-gradient-to-br from-[var(--color-brand-600)] to-[var(--color-brand-800)] text-white">
          <div className="flex h-full flex-col">
            <div className="flex items-center gap-2 text-xs font-medium opacity-80">
              <Sparkles className="h-4 w-4" />
              YOUR BID
            </div>
            <div className="mt-3 text-sm opacity-80">Your bidding price</div>
            <div className="mt-2 flex items-center gap-2">
              <span className="text-3xl font-bold">€</span>
              <input
                type="text"
                inputMode="numeric"
                className="w-full rounded-xl border border-white/30 bg-white/10 px-3 py-2 text-3xl font-bold text-white placeholder:text-white/50 focus:border-white/60 focus:outline-none"
                value={effectiveBidding}
                placeholder="—"
                onChange={(e) => setBidding(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && biddingDirty) saveM.mutate({ bidding_price: effectiveBidding });
                }}
              />
              {biddingDirty && (
                <button
                  type="button"
                  onClick={() => saveM.mutate({ bidding_price: effectiveBidding })}
                  disabled={saveM.isPending}
                  className="grid h-12 w-12 shrink-0 place-items-center rounded-xl bg-white text-[var(--color-brand-700)] hover:bg-white/90"
                >
                  {saveM.isPending ? <Loader2 className="h-5 w-5 animate-spin" /> : <Check className="h-5 w-5" />}
                </button>
              )}
            </div>
            <div className="mt-auto grid grid-cols-3 gap-3 pt-6 text-xs">
              <MiniWhiteStat label="Asking" value={prop.asking_price} />
              <MiniWhiteStat label="WOZ" value={prop.woz_value} />
              <MiniWhiteStat label="Suggested" value={prop.suggested_bid} />
            </div>
          </div>
        </Bento>

        {/* Address card */}
        <Bento className="md:col-span-3">
          <BentoHeader icon={<MapPin className="h-4 w-4" />} title="Location" />
          <div className="mt-1 text-lg font-semibold">{prop.address ?? "—"}</div>
          <div className="mt-2 grid grid-cols-2 gap-3 text-xs">
            <KV k="Listed since" v={prop.listed_since} />
            <KV k="Days on market" v={prop.days_on_market} />
            <KV k="Acceptance" v={prop.acceptance} />
            <KV k="Scraped" v={prop.scrape_date} />
          </div>
        </Bento>

        {/* Energy */}
        <Bento className="md:col-span-1 bg-emerald-50 dark:bg-emerald-950/30">
          <BentoHeader icon={<Zap className="h-4 w-4 text-emerald-700" />} title="Energy" />
          <div className="mt-2 text-3xl font-bold text-emerald-700">{prop.energy_label ?? "—"}</div>
          <div className="mt-2 text-xs text-emerald-700/80">{prop.heating ?? ""}</div>
        </Bento>

        {/* Price / m² */}
        <Bento className="md:col-span-2 bg-amber-50 dark:bg-amber-950/30">
          <BentoHeader icon={<Euro className="h-4 w-4 text-amber-700" />} title="Price / m²" />
          <div className="mt-2 text-2xl font-bold text-amber-800">{prop.price_per_m2 ?? "—"}</div>
          <div className="mt-1 text-xs text-amber-800/80">{prop.living_area ? `${prop.living_area} m² living` : ""}</div>
        </Bento>

        {/* Specs */}
        <Bento className="md:col-span-3">
          <BentoHeader icon={<Home className="h-4 w-4" />} title="Property" />
          <div className="mt-2 grid grid-cols-2 gap-3 text-sm">
            <KV k="Type" v={prop.property_type} />
            <KV k="Build year" v={prop.construction_year} />
            <KV icon={<Ruler className="h-3.5 w-3.5" />} k="Living area" v={prop.living_area} />
            <KV k="Plot area" v={prop.plot_area} />
            <KV icon={<Bed className="h-3.5 w-3.5" />} k="Rooms" v={prop.rooms} />
            <KV k="Bedrooms" v={prop.bedrooms} />
            <KV icon={<Car className="h-3.5 w-3.5" />} k="Parking" v={prop.parking} />
            <KV k="Garden" v={prop.garden} />
          </div>
        </Bento>

        {/* Agency */}
        <Bento className="md:col-span-3">
          <BentoHeader icon={<Building2 className="h-4 w-4" />} title="Agency" />
          <div className="mt-2 text-base font-semibold">{prop.agency_name ?? "—"}</div>
          <div className="mt-2 space-y-1.5 text-sm">
            <Contact icon={<Phone className="h-3.5 w-3.5" />} value={prop.agency_phone} />
            <Contact
              icon={<Mail className="h-3.5 w-3.5" />}
              value={prop.agency_email}
              href={prop.agency_email ? `mailto:${prop.agency_email}` : undefined}
            />
            <Contact
              icon={<Globe className="h-3.5 w-3.5" />}
              value={prop.agency_website}
              href={prop.agency_website ?? undefined}
              external
            />
          </div>
        </Bento>

        {/* Condition (full width row) */}
        <Bento className="md:col-span-6">
          <BentoHeader icon={<TrendingUp className="h-4 w-4" />} title="Condition & Features" />
          <div className="mt-2 grid grid-cols-2 gap-3 text-sm md:grid-cols-4">
            <KV k="Heating" v={prop.heating} />
            <KV k="Insulation" v={prop.insulation} />
            <KV k="Maint. inside" v={prop.maintenance_inside} />
            <KV k="Maint. outside" v={prop.maintenance_outside} />
            <KV k="Garden orient." v={prop.garden_orientation} />
            <KV k="VVE / month" v={prop.vve} />
            <KV k="Erfpacht" v={prop.erfpacht} />
            <KV k="Last synced" v={formatDate(prop.last_synced_at)} />
          </div>
        </Bento>

        {/* Description */}
        {prop.description && (
          <Bento className="md:col-span-4">
            <BentoHeader icon={<Calendar className="h-4 w-4" />} title="Description" />
            <p className="mt-2 max-h-72 overflow-auto whitespace-pre-wrap text-sm leading-relaxed">
              {prop.description}
            </p>
          </Bento>
        )}

        {/* Notes */}
        <Bento className={cn(prop.description ? "md:col-span-2" : "md:col-span-6")}>
          <BentoHeader icon={<Save className="h-4 w-4" />} title="Notes" />
          <textarea
            className="input mt-2 min-h-[140px] resize-y"
            value={effectiveNotes}
            onChange={(e) => setNotes(e.target.value)}
            placeholder="Internal notes…"
          />
          <button
            type="button"
            onClick={() => saveM.mutate({ notes: effectiveNotes })}
            className="btn-outline mt-3 w-full"
            disabled={saveM.isPending}
          >
            {saveM.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
            Save notes
          </button>
        </Bento>
      </div>

      <EmailModal property={prop as Property} open={showEmail} onClose={() => setShowEmail(false)} />
    </PageContainer>
  );
}

function Bento({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <div
      className={cn(
        "card flex min-h-[120px] flex-col p-5 transition-shadow hover:shadow-md",
        className,
      )}
    >
      {children}
    </div>
  );
}

function BentoHeader({ icon, title }: { icon: React.ReactNode; title: string }) {
  return (
    <div className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-wider text-[var(--muted-foreground)]">
      {icon}
      {title}
    </div>
  );
}

function KV({
  k,
  v,
  icon,
}: {
  k: string;
  v?: React.ReactNode;
  icon?: React.ReactNode;
}) {
  const empty = v === null || v === undefined || v === "";
  return (
    <div className="flex flex-col gap-0.5">
      <div className="flex items-center gap-1 text-[10px] uppercase tracking-wider text-[var(--muted-foreground)]">
        {icon}
        {k}
      </div>
      <div className="font-medium">{empty ? <span className="text-[var(--muted-foreground)]">—</span> : v}</div>
    </div>
  );
}

function Contact({
  icon,
  value,
  href,
  external,
}: {
  icon: React.ReactNode;
  value?: string | null;
  href?: string;
  external?: boolean;
}) {
  if (!value) {
    return (
      <div className="flex items-center gap-2 text-[var(--muted-foreground)]">
        {icon}
        <span>—</span>
      </div>
    );
  }
  const inner = (
    <span className="inline-flex items-center gap-2">
      {icon}
      <span className="truncate">{value}</span>
      {external && href && <ExternalLink className="h-3 w-3 shrink-0" />}
    </span>
  );
  if (href) {
    return (
      <a
        href={href}
        target={external ? "_blank" : undefined}
        rel={external ? "noopener noreferrer" : undefined}
        className="block truncate text-[var(--color-brand-600)] hover:underline"
      >
        {inner}
      </a>
    );
  }
  return <div className="truncate">{inner}</div>;
}

function MiniWhiteStat({ label, value }: { label: string; value?: string | null }) {
  return (
    <div className="rounded-xl border border-white/20 bg-white/10 p-2">
      <div className="text-[10px] uppercase tracking-wider opacity-80">{label}</div>
      <div className="mt-0.5 truncate font-semibold">{value ?? "—"}</div>
    </div>
  );
}
