"""Contacts and calendar conversion: VCF (vCard) <-> CSV, ICS (iCalendar) <-> CSV.

Uses ``vobject`` (lightweight pip package, no binaries) to parse and build
vCard/iCalendar structures reliably; CSV I/O uses the stdlib ``csv`` module.
Note: VCF and ICS are different domains (contacts vs. events) and are not
cross-converted between each other, only to/from CSV.
"""

from __future__ import annotations

import csv

from ..core.base import BaseConverter, ConversionJob, ConversionResult, ProgressCallback
from ..core.exceptions import MissingDependencyError
from ..core.registry import register

# The only pairs this converter actually implements.
_SUPPORTED_PAIRS = frozenset(
    {("vcf", "csv"), ("csv", "vcf"), ("ics", "csv"), ("csv", "ics")}
)

_VCARD_FIELDS = ["full_name", "first_name", "last_name", "email", "phone", "org"]
_EVENT_FIELDS = ["summary", "start", "end", "location", "description"]


class ContactCalendarConverter(BaseConverter):
    name = "Contact & Calendar Converter"
    description = (
        "Converts contacts (VCF/vCard <-> CSV) and calendar events "
        "(ICS/iCalendar <-> CSV). Requires the vobject package."
    )
    input_formats = frozenset({"vcf", "ics", "csv"})
    output_formats = frozenset({"vcf", "ics", "csv"})

    def can_convert(self, src_format: str, dst_format: str) -> bool:
        # Without this, the registry assumed every input could reach every
        # output: VCF -> ICS was offered (and always failed), and this
        # converter claimed CSV -> CSV, shadowing the spreadsheet
        # converter's CSV re-delimiting.
        pair = (src_format.lower().lstrip("."), dst_format.lower().lstrip("."))
        return pair in _SUPPORTED_PAIRS

    def check_available(self) -> tuple[bool, str]:
        try:
            import vobject  # noqa: F401

            return True, "OK"
        except ImportError:
            return False, "Install with: pip install vobject"

    def convert(
        self, job: ConversionJob, progress_cb: ProgressCallback = None
    ) -> ConversionResult:
        def _do() -> None:
            try:
                import vobject
            except ImportError as exc:
                raise MissingDependencyError(
                    "vobject", "Install with: pip install vobject"
                ) from exc

            src_ext = job.src_format
            target = job.target_format.lower().lstrip(".")

            if progress_cb:
                progress_cb(0.1, f"Reading {src_ext}")

            if src_ext == "vcf" and target == "csv":
                self._vcf_to_csv(vobject, job)
            elif src_ext == "csv" and target == "vcf":
                self._csv_to_vcf(vobject, job)
            elif src_ext == "ics" and target == "csv":
                self._ics_to_csv(vobject, job)
            elif src_ext == "csv" and target == "ics":
                self._csv_to_ics(vobject, job)
            else:
                raise ValueError(
                    f"Unsupported contact/calendar conversion: {src_ext} -> {target} "
                    "(VCF and ICS only convert to/from CSV, not to each other)."
                )

            if progress_cb:
                progress_cb(0.95, "Done")

        return self._run_timed(job, _do)

    # -- Contacts (VCF <-> CSV) -------------------------------------------
    def _vcf_to_csv(self, vobject, job: ConversionJob) -> None:
        text = job.source_path.read_text(encoding="utf-8-sig")
        rows = []
        for card in vobject.readComponents(text):
            full_name = getattr(card, "fn", None)
            n = getattr(card, "n", None)
            email = getattr(card, "email", None)
            tel = getattr(card, "tel", None)
            org = getattr(card, "org", None)
            rows.append(
                {
                    "full_name": full_name.value if full_name else "",
                    "first_name": n.value.given if n else "",
                    "last_name": n.value.family if n else "",
                    "email": email.value if email else "",
                    "phone": tel.value if tel else "",
                    "org": " ".join(org.value) if org and org.value else "",
                }
            )
        with open(job.output_path, "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=_VCARD_FIELDS)
            writer.writeheader()
            writer.writerows(rows)

    def _csv_to_vcf(self, vobject, job: ConversionJob) -> None:
        cards = []
        with open(job.source_path, newline="", encoding="utf-8-sig") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                card = vobject.vCard()
                card.add("fn").value = row.get("full_name") or (
                    f"{row.get('first_name', '')} {row.get('last_name', '')}".strip()
                )
                n = card.add("n")
                n.value = vobject.vcard.Name(
                    family=row.get("last_name", ""), given=row.get("first_name", "")
                )
                if row.get("email"):
                    card.add("email").value = row["email"]
                if row.get("phone"):
                    card.add("tel").value = row["phone"]
                if row.get("org"):
                    card.add("org").value = [row["org"]]
                cards.append(card.serialize())
        job.output_path.write_text("".join(cards), encoding="utf-8")

    # -- Calendar (ICS <-> CSV) -------------------------------------------
    def _ics_to_csv(self, vobject, job: ConversionJob) -> None:
        text = job.source_path.read_text(encoding="utf-8-sig")
        rows = []
        for cal in vobject.readComponents(text):
            for component in getattr(cal, "vevent_list", []):
                summary = getattr(component, "summary", None)
                dtstart = getattr(component, "dtstart", None)
                dtend = getattr(component, "dtend", None)
                location = getattr(component, "location", None)
                desc = getattr(component, "description", None)
                rows.append(
                    {
                        "summary": summary.value if summary else "",
                        "start": _format_dt(dtstart.value) if dtstart else "",
                        "end": _format_dt(dtend.value) if dtend else "",
                        "location": location.value if location else "",
                        "description": desc.value if desc else "",
                    }
                )
        with open(job.output_path, "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=_EVENT_FIELDS)
            writer.writeheader()
            writer.writerows(rows)

    def _csv_to_ics(self, vobject, job: ConversionJob) -> None:
        cal = vobject.iCalendar()
        with open(job.source_path, newline="", encoding="utf-8-sig") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                event = cal.add("vevent")
                event.add("summary").value = row.get("summary", "")
                if row.get("start"):
                    event.add("dtstart").value = self._parse_dt(row["start"])
                if row.get("end"):
                    event.add("dtend").value = self._parse_dt(row["end"])
                if row.get("location"):
                    event.add("location").value = row["location"]
                if row.get("description"):
                    event.add("description").value = row["description"]
        job.output_path.write_text(cal.serialize(), encoding="utf-8")

    @staticmethod
    def _parse_dt(value: str):
        """Parse a CSV date/datetime cell. Accepts ISO 8601 (with or without
        a timezone offset — which is what ICS -> CSV writes, so the round
        trip works) plus a few common variants. A date-only value becomes
        an all-day event."""

        from datetime import date, datetime

        text = value.strip()
        if len(text) == 10:
            try:
                return date.fromisoformat(text)
            except ValueError:
                pass
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            pass
        else:
            if parsed.tzinfo is not None:
                # vobject can't serialize stdlib fixed-offset tzinfo objects
                # ("Unable to guess TZID"); normalize to UTC, which it writes
                # as the standard "...Z" form.
                from dateutil import tz

                parsed = parsed.astimezone(tz.tzutc())
            return parsed
        for fmt in ("%Y-%m-%d %H:%M", "%d/%m/%Y %H:%M", "%m/%d/%Y %H:%M", "%Y%m%dT%H%M%S"):
            try:
                return datetime.strptime(text, fmt)
            except ValueError:
                continue
        raise ValueError(
            f"Unrecognized date/time {value!r} — use ISO format, e.g. "
            "2024-05-01 14:30 or 2024-05-01T14:30:00+02:00."
        )


def _format_dt(value) -> str:
    """ISO 8601 text for a date/datetime from vobject (round-trips through
    :meth:`ContactCalendarConverter._parse_dt`)."""

    if hasattr(value, "isoformat"):
        return value.isoformat(sep=" ") if hasattr(value, "hour") else value.isoformat()
    return str(value)


register(ContactCalendarConverter())
