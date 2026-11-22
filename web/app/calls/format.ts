/** Labels and small helpers for the call floor. */
import type { HouseholdRecord } from "@/lib/api";

export const STAGE_LABEL: Record<string, string> = {
  greet: "Greeting",
  confirm_address: "Address",
  can_leave: "Can leave?",
  household: "Household",
  needs: "Needs",
  chair_kind: "Chair kind",
  assistance: "Assistance",
  readback: "Read-back",
  neighbor: "Neighbors",
  status: "Status",
  hold: "Anything else",
  goodbye: "Ended",
};

export const STATUS_LABEL: Record<string, string> = {
  received: "On the list",
  approved: "Approved (not told)",
  driver_accepted: "Driver accepted",
  en_route: "En route",
  arrived: "Arrived",
  closed: "Closed",
  reassigning: "Reassigning",
};

export const ESCALATION_LABEL: Record<string, string> = {
  medical: "Medical",
  flames: "Flames",
  address_unconfirmed: "Address unclear",
  unservable: "Unservable",
  language: "Not understood",
};

const MOBILITY: Record<string, string> = {
  walks: "Walks",
  walker: "Walker",
  manual_wheelchair: "Manual wheelchair",
  power_wheelchair: "Power wheelchair",
  bedbound: "Bedbound",
};
const ASSISTANCE: Record<string, string> = {
  none: "None",
  one_person: "One person",
  two_person_lift: "Two-person lift",
};
const yesNo = (v: boolean | undefined) => (v === undefined ? undefined : v ? "Yes" : "No");

/** The record fields in the order the call asks for them. `undefined` = not heard yet. */
export function recordRows(r: HouseholdRecord | undefined): { key: string; label: string; value?: string }[] {
  const rec = r ?? {};
  return [
    { key: "canLeave", label: "Can leave", value: rec.canLeave && { yes: "Yes", no: "No", unsure: "Unsure" }[rec.canLeave] },
    { key: "peopleCount", label: "People", value: rec.peopleCount?.toString() },
    { key: "pets", label: "Pets", value: yesNo(rec.pets) },
    { key: "hasCar", label: "Car", value: yesNo(rec.hasCar) },
    { key: "mobility", label: "Mobility", value: rec.mobility && MOBILITY[rec.mobility] },
    {
      key: "medical",
      label: "Medical",
      value: rec.medical === undefined ? undefined : rec.medical.length ? rec.medical.join(", ") : "None",
    },
    { key: "assistance", label: "Help out", value: rec.assistance && ASSISTANCE[rec.assistance] },
  ];
}

export function ago(iso?: string | null, now = Date.now()): string {
  if (!iso) return "";
  const s = Math.max(0, Math.round((now - new Date(iso).getTime()) / 1000));
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m`;
  return `${Math.floor(s / 3600)}h`;
}

export function clock(iso?: string | null): string {
  if (!iso) return "";
  return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

/** Red is reserved for fire / a person who needs help; slow turns are amber, not red. */
export function latencyTone(ms: number): string {
  if (ms < 1000) return "text-out border-out/40";
  if (ms < 2500) return "text-help border-help/40";
  return "text-help border-help bg-help/10";
}
