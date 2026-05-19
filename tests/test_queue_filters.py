"""Table intelligence bullets (compact factual copy)."""
from uk_leads.enrichment import build_table_intelligence_bullets, enrich_row


def test_table_bullets_are_factual():
    row = enrich_row(
        {
            "company_name": "Harbour Fintech Payments Ltd",
            "jurisdiction": "UK",
            "entity_type": "ltd",
            "source": "companies_house",
            "sic_codes": "64999",
            "incorporation_date": "2026-05-16",
        }
    )
    bullets = row.get("table_intelligence_bullets") or build_table_intelligence_bullets(row)
    assert bullets
    text = " ".join(bullets).lower()
    for phrase in ("promising", "priority outreach", "high growth", "ideal fit"):
        assert phrase not in text
