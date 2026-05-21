/**
 * Fullscreen image carousel. Mobile-first: takes the full viewport,
 * larger tap targets, scaled image, swipeable thumbnail strip at the
 * bottom. ESC closes, ←/→ cycle, click outside dismisses.
 */
import { useEffect, useState } from "react";
import { ChevronLeft, ChevronRight, X } from "lucide-react";
import { cn } from "@/lib/utils";

export function Lightbox({
  images,
  address,
  onClose,
}: {
  images: string[];
  address: string;
  onClose: () => void;
}) {
  const [idx, setIdx] = useState(0);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
      if (e.key === "ArrowRight") setIdx((i) => (i + 1) % images.length);
      if (e.key === "ArrowLeft") setIdx((i) => (i - 1 + images.length) % images.length);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [images.length, onClose]);

  // Prevent body scroll while modal open.
  useEffect(() => {
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = prev;
    };
  }, []);

  if (images.length === 0) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex flex-col bg-black"
      style={{ minHeight: "100dvh" }}
      onClick={onClose}
    >
      {/* Top bar */}
      <div
        className="pt-safe flex shrink-0 items-center justify-between gap-3 px-3 py-3 text-white sm:px-5"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="min-w-0 flex-1">
          <div className="truncate text-sm font-medium">{address}</div>
          <div className="text-xs opacity-70">
            {idx + 1} / {images.length}
          </div>
        </div>
        <button
          type="button"
          onClick={onClose}
          className="grid h-10 w-10 shrink-0 place-items-center rounded-full bg-white/10 hover:bg-white/20"
          aria-label="Close"
        >
          <X className="h-5 w-5" />
        </button>
      </div>

      {/* Image stage — fills available vertical space */}
      <div
        className="relative flex min-h-0 flex-1 items-center justify-center"
        onClick={(e) => e.stopPropagation()}
      >
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src={images[idx]}
          alt={`Image ${idx + 1}`}
          className="max-h-full max-w-full object-contain"
          draggable={false}
        />

        {images.length > 1 && (
          <>
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                setIdx((i) => (i - 1 + images.length) % images.length);
              }}
              className="absolute left-2 top-1/2 grid h-11 w-11 -translate-y-1/2 place-items-center rounded-full bg-white/15 text-white hover:bg-white/30 sm:left-4"
              aria-label="Previous image"
            >
              <ChevronLeft className="h-6 w-6" />
            </button>
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                setIdx((i) => (i + 1) % images.length);
              }}
              className="absolute right-2 top-1/2 grid h-11 w-11 -translate-y-1/2 place-items-center rounded-full bg-white/15 text-white hover:bg-white/30 sm:right-4"
              aria-label="Next image"
            >
              <ChevronRight className="h-6 w-6" />
            </button>
          </>
        )}
      </div>

      {/* Thumbnail strip */}
      {images.length > 1 && (
        <div
          className="pb-safe shrink-0 overflow-x-auto px-3 py-2 sm:px-5"
          onClick={(e) => e.stopPropagation()}
        >
          <div className="flex gap-2">
            {images.map((src, i) => (
              <button
                key={i}
                type="button"
                onClick={() => setIdx(i)}
                className={cn(
                  "h-12 w-16 shrink-0 overflow-hidden rounded-md border-2 transition sm:h-14 sm:w-20",
                  i === idx ? "border-[var(--color-brand-400)]" : "border-transparent opacity-70 hover:opacity-100",
                )}
                aria-label={`Image ${i + 1}`}
              >
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img src={src} alt="" className="h-full w-full object-cover" loading="lazy" />
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
