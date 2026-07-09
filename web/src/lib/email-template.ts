/**
 * Bid-email template (NL). Builds the subject, a plain-text fallback, and a
 * professional inline-styled HTML body from a property's dynamic values:
 *   companyName    -> agency name
 *   propertyAddress-> address
 *   biddingPrice   -> Bidding Price (asking - 22%), falls back to suggested bid
 *   validityDays   -> bid validity (working days)
 *
 * Inline styles only — email clients (Gmail/Outlook) strip <style>/external CSS.
 * Layout is table-based for the same reason (Outlook ignores flex/grid and
 * mangles <ul> padding).
 */
import type { Property } from "./api/properties";

const SENDER_NAME = "Direct Verkocht Met Zekerheid";
const SENDER_PHONE = "085-2082323";

// Brand palette — deep teal reads as trust/certainty ("zekerheid") and stays
// legible against the neutral slate body text.
const BRAND_DARK = "#0f4f47"; // header
const BRAND = "#0f766e"; // headings, accents
const BRAND_ACCENT = "#14b8a6"; // thin accent bar
const BRAND_TINT = "#f0fdfa"; // callout / footer wash
const BRAND_BORDER = "#ccfbf1";
const INK = "#0f172a"; // strong text
const BODY = "#334155"; // body text
const MUTED = "#94a3b8";

function euro(v: string | null | undefined): string {
  const n = parseInt(String(v ?? "").replace(/[^0-9]/g, ""), 10);
  if (!n) return "—";
  return `€ ${n.toLocaleString("nl-NL")}`;
}

export type BidEmail = { subject: string; text: string; html: string };

export function buildBidEmail(property: Property): BidEmail {
  const company = property.agency_name?.trim() || "team";
  const address = property.address?.trim() || property.url;
  const bidding = euro(property.bidding_price || property.suggested_bid);

  const subject = `Bod op ${address}`;

  const text = [
    `Beste team van ${company},`,
    ``,
    `Naar aanleiding van de verkoop van de woning aan de ${address} brengen wij u hierbij het volgende bod uit.`,
    ``,
    `Voorwaarden`,
    `- Koopsom: ${bidding}`,
    `- Financiering: Geen financieringsvoorbehoud`,
    `- Voorbehoud: Een conveniërend due diligence onderzoek van 3 werkdagen. Dit onderzoek gaat in na bezichtiging.`,
    `- Overdrachtsdatum: Volledig in overleg. Zowel op korte als lange termijn mogelijk.`,
    `- Roerende zaken: Kunnen indien gewenst achterblijven.`,
    `- Geldigheid bod: Tot vijf werkdagen na dagtekening van deze brief.`,
    ``,
    `Wij kopen de woning als professionele partij met direct beschikbare middelen. Daardoor is ons bod niet afhankelijk van een hypotheekaanvraag of andere externe goedkeuringen en kan bij overeenstemming direct worden doorgepakt.`,
    ``,
    `Wij realiseren ons dat iedere extra periode op de markt nieuwe bezichtigingen, onderhandelingen en onzekerheid met zich mee kan brengen. Met dit voorstel bieden wij een concreet aanbod waarbij u direct weet waar u aan toe bent, terwijl u zelf de regie houdt.`,
    ``,
    `Mocht jullie kantoor ander interessant vastgoed in de verkoop hebben of krijgen met potentie? Dan houden wij ons graag aanbevolen. Wij zijn op zoek naar transformatie objecten, verhuurde woningen, ontwikkelgronden, bedrijfspanden, klushuizen, en huizen van verkopers die direct of in stille verkoop wensen te verkopen. Wij kopen direct en met eigen middelen. Geen bestedingslimiet.`,
    ``,
    `Wij zien uw reactie graag tegemoet vóór bovengenoemde datum.`,
    ``,
    `Met vriendelijke groet,`,
    `${SENDER_NAME}`,
    `Telefoon: ${SENDER_PHONE}`,
  ].join("\n");

  // One condition = one table row (label left, value right). Table rows survive
  // Outlook; <ul> bullets do not render consistently.
  const row = (label: string, value: string, last = false) =>
    `<tr>
       <td style="padding:10px 0;${last ? "" : `border-bottom:1px solid #e2e8f0;`}
                  vertical-align:top;width:170px;color:${INK};font-weight:600;font-size:14px;">
         ${label}
       </td>
       <td style="padding:10px 0;${last ? "" : `border-bottom:1px solid #e2e8f0;`}
                  vertical-align:top;color:${BODY};font-size:14px;line-height:1.55;">
         ${value}
       </td>
     </tr>`;

  const p = (inner: string) =>
    `<p style="margin:0 0 16px 0;line-height:1.65;color:${BODY};font-size:15px;">${inner}</p>`;

  const html = `<!doctype html>
<html lang="nl">
<body style="margin:0;padding:0;background:#eef2f1;">
  <div style="display:none;max-height:0;overflow:hidden;opacity:0;">
    Bod op ${address} — ${bidding}
  </div>
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#eef2f1;padding:24px 0;">
    <tr><td align="center">
      <table role="presentation" width="600" cellpadding="0" cellspacing="0"
        style="max-width:600px;width:100%;background:#ffffff;border-radius:14px;overflow:hidden;
               font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;
               box-shadow:0 1px 3px rgba(15,23,42,0.08);">

        <!-- header -->
        <tr><td style="background:${BRAND_DARK};padding:24px 32px;">
          <span style="color:#ffffff;font-size:19px;font-weight:700;letter-spacing:.3px;">
            ${SENDER_NAME}
          </span>
        </td></tr>
        <tr><td style="background:${BRAND_ACCENT};height:4px;line-height:4px;font-size:0;">&nbsp;</td></tr>

        <!-- body -->
        <tr><td style="padding:32px;">
          ${p(`Beste team van <strong style="color:${INK};">${company}</strong>,`)}
          ${p(`Naar aanleiding van de verkoop van de woning aan de <strong style="color:${INK};">${address}</strong> brengen wij u hierbij het volgende bod uit.`)}

          <h3 style="margin:26px 0 4px 0;font-size:13px;color:${BRAND};text-transform:uppercase;letter-spacing:1px;font-weight:700;">
            Voorwaarden
          </h3>
          <div style="height:2px;width:44px;background:${BRAND_ACCENT};margin:0 0 14px 0;font-size:0;line-height:2px;">&nbsp;</div>

          <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin:0 0 24px 0;">
            ${row(
              "Koopsom",
              `<span style="color:${BRAND};font-weight:700;font-size:19px;">${bidding}</span>`,
            )}
            ${row("Financiering", "Geen financieringsvoorbehoud")}
            ${row(
              "Voorbehoud",
              "Een conveniërend due diligence onderzoek van 3 werkdagen. Dit onderzoek gaat in na bezichtiging.",
            )}
            ${row(
              "Overdrachtsdatum",
              "Volledig in overleg. Zowel op korte als lange termijn mogelijk.",
            )}
            ${row("Roerende zaken", "Kunnen indien gewenst achterblijven.")}
            ${row("Geldigheid bod", "Tot vijf werkdagen na dagtekening van deze brief.", true)}
          </table>

          ${p("Wij kopen de woning als professionele partij met direct beschikbare middelen. Daardoor is ons bod niet afhankelijk van een hypotheekaanvraag of andere externe goedkeuringen en kan bij overeenstemming direct worden doorgepakt.")}
          ${p("Wij realiseren ons dat iedere extra periode op de markt nieuwe bezichtigingen, onderhandelingen en onzekerheid met zich mee kan brengen. Met dit voorstel bieden wij een concreet aanbod waarbij u direct weet waar u aan toe bent, terwijl u zelf de regie houdt.")}
          ${p("Mocht jullie kantoor ander interessant vastgoed in de verkoop hebben of krijgen met potentie? Dan houden wij ons graag aanbevolen. Wij zijn op zoek naar transformatie objecten, verhuurde woningen, ontwikkelgronden, bedrijfspanden, klushuizen, en huizen van verkopers die direct of in stille verkoop wensen te verkopen. Wij kopen direct en met eigen middelen. Geen bestedingslimiet.")}
          ${p("Wij zien uw reactie graag tegemoet vóór bovengenoemde datum.")}

          <!-- signature -->
          <table role="presentation" cellpadding="0" cellspacing="0" style="margin:26px 0 0 0;background:${BRAND_TINT};border-left:3px solid ${BRAND};border-radius:0 8px 8px 0;">
            <tr><td style="padding:14px 18px;line-height:1.6;color:${BODY};font-size:15px;">
              Met vriendelijke groet,<br>
              <strong style="color:${INK};">${SENDER_NAME}</strong><br>
              Telefoon: ${SENDER_PHONE}
            </td></tr>
          </table>
        </td></tr>

        <!-- footer -->
        <tr><td style="background:${BRAND_TINT};padding:16px 32px;border-top:1px solid ${BRAND_BORDER};">
          <span style="color:${MUTED};font-size:12px;">
            ${SENDER_NAME} · Telefoon: ${SENDER_PHONE}
          </span>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body>
</html>`;

  return { subject, text, html };
}
