from __future__ import annotations

import argparse
import csv
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from zipfile import ZipFile


def _normalize_name(value: str) -> str:
    return " ".join((value or "").strip().lower().split())


def _first_sheet_rows(xlsx_path: Path) -> list[list[str]]:
    ns = {
        "main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
        "rel": "http://schemas.openxmlformats.org/package/2006/relationships",
    }

    with ZipFile(xlsx_path) as zf:
        shared_strings: list[str] = []
        if "xl/sharedStrings.xml" in zf.namelist():
            sst = ET.fromstring(zf.read("xl/sharedStrings.xml"))
            for si in sst.findall("main:si", ns):
                text = "".join(t.text or "" for t in si.findall(".//main:t", ns))
                shared_strings.append(text)

        workbook = ET.fromstring(zf.read("xl/workbook.xml"))
        wb_rels = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))

        rel_by_id: dict[str, str] = {}
        for rel in wb_rels.findall("rel:Relationship", ns):
            rel_by_id[rel.attrib.get("Id", "")] = rel.attrib.get("Target", "")

        sheet_target = ""
        for sheet in workbook.findall("main:sheets/main:sheet", ns):
            rid = sheet.attrib.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
            target = rel_by_id.get(rid or "", "")
            if target:
                sheet_target = target
                break
        if not sheet_target:
            return []

        if not sheet_target.startswith("worksheets/"):
            sheet_target = sheet_target.lstrip("/")
        sheet_xml_path = f"xl/{sheet_target}"
        worksheet = ET.fromstring(zf.read(sheet_xml_path))

        rows: list[list[str]] = []
        for row in worksheet.findall("main:sheetData/main:row", ns):
            cells: dict[int, str] = {}
            max_col = -1
            for c in row.findall("main:c", ns):
                ref = c.attrib.get("r", "")
                col_letters = "".join(ch for ch in ref if ch.isalpha())
                col_idx = _col_to_index(col_letters)
                max_col = max(max_col, col_idx)
                value = ""
                cell_type = c.attrib.get("t")
                if cell_type == "inlineStr":
                    value = "".join(t.text or "" for t in c.findall(".//main:t", ns))
                else:
                    v = c.find("main:v", ns)
                    if v is not None and v.text is not None:
                        if cell_type == "s":
                            try:
                                value = shared_strings[int(v.text)]
                            except (ValueError, IndexError):
                                value = v.text
                        else:
                            value = v.text
                cells[col_idx] = value.strip()
            if max_col < 0:
                continue
            rows.append([cells.get(i, "") for i in range(max_col + 1)])

    return rows


def _col_to_index(col: str) -> int:
    idx = 0
    for ch in col:
        idx = idx * 26 + (ord(ch.upper()) - ord("A") + 1)
    return idx - 1


def _clean_url(raw: str) -> str:
    url = (raw or "").strip()
    if not url:
        return ""
    if re.match(r"^https?://", url, flags=re.IGNORECASE):
        return url
    return f"https://{url}"


def _build_notes(parts: list[str]) -> str:
    cleaned = [p.strip() for p in parts if p and p.strip()]
    return " | ".join(cleaned)


def _mauritius_rows(xlsx_path: Path) -> list[dict[str, str]]:
    rows = _first_sheet_rows(xlsx_path)
    if not rows:
        return []

    header = [h.strip() for h in rows[0]]
    idx = {name: i for i, name in enumerate(header)}

    out: list[dict[str, str]] = []
    for row in rows[1:]:
        name = row[idx.get("Company Name", -1)].strip() if idx.get("Company Name", -1) >= 0 and len(row) > idx.get("Company Name", -1) else ""
        if not name:
            continue

        col2 = row[idx.get("Column2", -1)].strip() if idx.get("Column2", -1) >= 0 and len(row) > idx.get("Column2", -1) else ""
        col3 = row[idx.get("Column3", -1)].strip() if idx.get("Column3", -1) >= 0 and len(row) > idx.get("Column3", -1) else ""
        website = row[idx.get("Website", -1)].strip() if idx.get("Website", -1) >= 0 and len(row) > idx.get("Website", -1) else ""
        contact_number = row[idx.get("Contact Number", -1)].strip() if idx.get("Contact Number", -1) >= 0 and len(row) > idx.get("Contact Number", -1) else ""
        contact_person = row[idx.get("Contact Person", -1)].strip() if idx.get("Contact Person", -1) >= 0 and len(row) > idx.get("Contact Person", -1) else ""
        email = row[idx.get("Email", -1)].strip() if idx.get("Email", -1) >= 0 and len(row) > idx.get("Email", -1) else ""
        address = row[idx.get("Address", -1)].strip() if idx.get("Address", -1) >= 0 and len(row) > idx.get("Address", -1) else ""

        out.append(
            {
                "company_name": name,
                "normalized_name": _normalize_name(name),
                "jurisdiction": "Mauritius",
                "entity_type": col2 or "Management Company",
                "incorporation_date": "",
                "source": "mauritius_management_company",
                "company_number": "",
                "file_no": "",
                "sic_codes": "",
                "verify_url": _clean_url(website),
                "contact_email": email,
                "phone_number": contact_number,
                "contact_name": contact_person,
                "notes": _build_notes([
                    "Imported from Mauritius Management Companies List",
                    col3,
                    address,
                ]),
            }
        )
    return out


def _adgm_rows(csv_path: Path) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    with csv_path.open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        for raw in reader:
            name = (raw.get("ADGM Licensed CSP name") or "").strip()
            if not name:
                continue
            contact_name = (raw.get("Contact name") or "").strip()
            email = (raw.get("Email") or "").strip()
            out.append(
                {
                    "company_name": name,
                    "normalized_name": _normalize_name(name),
                    "jurisdiction": "UAE (ADGM)",
                    "entity_type": "Corporate Service Provider",
                    "incorporation_date": "",
                    "source": "adgm_csp",
                    "company_number": "",
                    "file_no": "",
                    "sic_codes": "",
                    "verify_url": "",
                    "contact_email": email,
                    "phone_number": "",
                    "contact_name": contact_name,
                    "notes": "Imported from ADGM CSPs List",
                }
            )
    return out


def _dedupe(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for row in rows:
        key = (row.get("normalized_name", ""), row.get("jurisdiction", ""))
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    out.sort(key=lambda r: (r.get("jurisdiction", ""), r.get("company_name", "")))
    return out


def import_lists(mauritius_xlsx: Path, adgm_csv: Path, output_csv: Path) -> int:
    rows = _dedupe(_mauritius_rows(mauritius_xlsx) + _adgm_rows(adgm_csv))
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "company_name",
        "normalized_name",
        "jurisdiction",
        "entity_type",
        "incorporation_date",
        "source",
        "company_number",
        "file_no",
        "sic_codes",
        "verify_url",
        "contact_email",
        "phone_number",
        "contact_name",
        "notes",
    ]
    with output_csv.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Normalize external introducer lists into uk_leads/sources/external_introducers.csv"
    )
    parser.add_argument("--mauritius-xlsx", required=True)
    parser.add_argument("--adgm-csv", required=True)
    parser.add_argument(
        "--output",
        default="uk_leads/sources/external_introducers.csv",
    )
    args = parser.parse_args()

    count = import_lists(
        Path(args.mauritius_xlsx),
        Path(args.adgm_csv),
        Path(args.output),
    )
    print(f"Wrote {count} rows to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
