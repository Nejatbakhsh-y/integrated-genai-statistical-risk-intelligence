"""Regression test for Form 5500 fallback discovery."""

from risk_intelligence.ingestion.form5500 import (
    choose_resources,
    discover_resources,
)


def test_body_level_fallback_links_are_classified_independently() -> None:
    html = """
    <html>
    <body>
    <h2>2025 Form 5500</h2>
    <a href="/F_5500_2025_Latest.zip">2025 Latest Form 5500</a>
    <a href="/F_SCH_H_2025_Latest.zip">2025 Latest Schedule H</a>
    <a href="/F_SCH_I_2025_Latest.zip">2025 Latest Schedule I</a>
    <a href="/F_SCH_SB_2025_Latest.zip">2025 Latest Schedule SB</a>
    </body>
    </html>
    """

    resources = discover_resources(
        html,
        "https://www.dol.gov/",
        2025,
        2025,
    )

    selected = choose_resources(resources)
    datasets = {resource.dataset for resource in selected}

    assert datasets == {
        "form5500_latest",
        "schedule_h_latest",
        "schedule_i_latest",
        "schedule_sb_latest",
    }
