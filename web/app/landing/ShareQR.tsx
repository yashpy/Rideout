"use client";

/** Scan to open RideOut on another device: a QR code for this site's Try-it page, plus copy-link. */
import QRCode from "qrcode";
import { useEffect, useState } from "react";

export function ShareQR({ path = "/try", className = "" }: { path?: string; className?: string }) {
  const [url, setUrl] = useState("");
  const [svg, setSvg] = useState("");
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    const u = `${window.location.origin}${path}`;
    setUrl(u);
    QRCode.toString(u, { type: "svg", margin: 1, errorCorrectionLevel: "M", color: { dark: "#0b1020", light: "#ffffff" } })
      .then(setSvg)
      .catch(() => setSvg(""));
  }, [path]);

  return (
    <div className={`glass flex items-center gap-4 p-4 ${className}`}>
      <div
        className="h-28 w-28 shrink-0 overflow-hidden rounded-xl bg-white p-1.5 [&>svg]:h-full [&>svg]:w-full"
        role="img"
        aria-label={`QR code for ${url}`}
        dangerouslySetInnerHTML={{ __html: svg }}
      />
      <div className="min-w-0">
        <p className="text-sm font-semibold text-ink">Open it on your phone</p>
        <p className="mt-1 text-xs leading-relaxed text-muted">Scan to try it: take the call, or drive as a neighbor.</p>
        <button
          type="button"
          className="btn mt-2.5 min-h-8 px-3! text-xs"
          onClick={async () => {
            try {
              await navigator.clipboard.writeText(url);
              setCopied(true);
              setTimeout(() => setCopied(false), 1600);
            } catch {
              /* clipboard blocked: the QR still works */
            }
          }}
        >
          {copied ? "Link copied" : "Copy link"}
        </button>
      </div>
    </div>
  );
}
