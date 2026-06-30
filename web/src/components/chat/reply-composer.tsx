"use client";

import { useRef, useState } from "react";
import { Paperclip, Send, X } from "lucide-react";
import { cn } from "@/lib/utils";

export function ReplyComposer({
  onSend,
  disabled,
  sending,
  placeholder = "Type a reply…",
}: {
  onSend: (text: string, files: File[]) => void;
  disabled?: boolean;
  sending?: boolean;
  placeholder?: string;
}) {
  const [text, setText] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const fileRef = useRef<HTMLInputElement>(null);

  const submit = () => {
    const t = text.trim();
    if (!t && files.length === 0) return;
    onSend(t, files);
    setText("");
    setFiles([]);
  };

  return (
    <div className="shrink-0 border-t border-[var(--border)] bg-[var(--surface)] p-3">
      {files.length > 0 && (
        <div className="mb-2 flex flex-wrap gap-2">
          {files.map((f, i) => (
            <span
              key={i}
              className="inline-flex items-center gap-1 rounded-md border border-[var(--border)] bg-[var(--surface-2)] px-2 py-1 text-xs"
            >
              {f.name}
              <button type="button" onClick={() => setFiles(files.filter((_, j) => j !== i))}>
                <X className="h-3 w-3 text-[var(--muted-foreground)]" />
              </button>
            </span>
          ))}
        </div>
      )}
      <div className="flex items-end gap-2">
        <button
          type="button"
          onClick={() => fileRef.current?.click()}
          disabled={disabled}
          className="grid h-10 w-10 shrink-0 place-items-center rounded-lg text-[var(--muted-foreground)] hover:bg-[var(--muted)] disabled:opacity-40"
          title="Attach files"
        >
          <Paperclip className="h-5 w-5" />
        </button>
        <input
          ref={fileRef}
          type="file"
          multiple
          className="hidden"
          onChange={(e) => setFiles([...files, ...Array.from(e.target.files ?? [])])}
        />
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              submit();
            }
          }}
          rows={1}
          disabled={disabled}
          placeholder={disabled ? "Connect Gmail to reply" : placeholder}
          className="input max-h-32 min-h-[2.5rem] flex-1 resize-none py-2"
        />
        <button
          type="button"
          onClick={submit}
          disabled={disabled || sending || (!text.trim() && files.length === 0)}
          className={cn(
            "grid h-10 w-10 shrink-0 place-items-center rounded-lg bg-[var(--color-brand-600)] text-white",
            "hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40",
          )}
          title="Send (Enter)"
        >
          <Send className="h-5 w-5" />
        </button>
      </div>
    </div>
  );
}
