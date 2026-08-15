"""Form 5500 sponsor-universe ingestion and validation.

The implementation intentionally treats raw DOL data as immutable external
evidence. Raw files are hashed and recorded in a manifest. Derived data are
generated from those immutable artifacts.
"""

from __future__ import annotations

import csv
import hashlib
import re
import shutil
import subprocess
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse

import pandas as pd
import requests
from bs4 import BeautifulSoup

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/151 Safari/537.36"


@dataclass(frozen=True)
class Resource:
    year: int
    dataset: str
    url: str
    link_text: str


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)

    return digest.hexdigest().upper()


def normalize_ein(value: object) -> str:
    if value is None or pd.isna(value):
        return ""

    digits = re.sub(r"\D", "", str(value))

    if not digits:
        return ""

    return digits.zfill(9)[-9:]


def normalize_plan_number(value: object) -> str:
    if value is None or pd.isna(value):
        return ""

    digits = re.sub(r"\D", "", str(value))

    if not digits:
        return ""

    return digits.zfill(3)[-3:]


def normalize_sponsor_name(value: object) -> str:
    if value is None or pd.isna(value):
        return ""

    text = str(value).upper().strip()
    text = re.sub(r"\s+", " ", text)
    return text


def make_sponsor_id(ein: str, sponsor_name: str) -> str:
    if re.fullmatch(r"\d{9}", ein):
        return f"SP-{ein}"

    digest = hashlib.sha256(sponsor_name.encode("utf-8")).hexdigest()[:16].upper()
    return f"SP-NAME-{digest}"


def make_plan_id(ein: str, plan_number: str, sponsor_name: str) -> str:
    if re.fullmatch(r"\d{9}", ein) and re.fullmatch(r"\d{3}", plan_number):
        return f"PL-{ein}-{plan_number}"

    material = f"{ein}|{plan_number}|{sponsor_name}"
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()[:20].upper()
    return f"PL-HASH-{digest}"


def _compact(value: str) -> str:
    value = value.lower()
    value = value.replace("-", " ").replace("_", " ")
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def classify_resource(blob: str) -> str | None:
    text = _compact(blob)

    if "data dictionary" in text or "data dictionary" in text.replace("_", " "):
        return "data_dictionary"

    if "latest" not in text:
        return None

    if "schedule sb" in text or "sch sb" in text:
        return "schedule_sb_latest"

    if "schedule h" in text or "sch h" in text:
        return "schedule_h_latest"

    if "schedule i" in text or "sch i" in text:
        return "schedule_i_latest"

    if "5500 sf" in text or "5500sf" in text:
        return "form5500_sf_latest"

    if "form 5500" in text or re.search(r"\bf 5500\b", text):
        return "form5500_latest"

    return None


def fetch_html(url: str, destination: Path) -> str:
    destination.parent.mkdir(parents=True, exist_ok=True)

    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml",
    }

    try:
        response = requests.get(url, headers=headers, timeout=90)
        response.raise_for_status()
        destination.write_bytes(response.content)
        return response.text
    except Exception as exc:
        curl = shutil.which("curl.exe") or shutil.which("curl")

        if not curl:
            raise RuntimeError(
                f"Unable to retrieve {url} with requests and curl is unavailable."
            ) from exc

        command = [
            curl,
            "-fL",
            "--retry",
            "5",
            "--retry-delay",
            "3",
            "-A",
            USER_AGENT,
            "-o",
            str(destination),
            url,
        ]

        completed = subprocess.run(command, check=False)

        if completed.returncode != 0:
            raise RuntimeError(f"Unable to retrieve authoritative DOL page: {url}") from exc

        return destination.read_text(encoding="utf-8", errors="replace")


def discover_resources(
    html: str,
    source_url: str,
    start_year: int,
    end_year: int,
) -> list[Resource]:
    soup = BeautifulSoup(html, "lxml")
    years = set(range(start_year, end_year + 1))
    resources: list[Resource] = []
    current_year: int | None = None

    year_pattern = re.compile(r"\b(20\d{2})\b")

    for tag in soup.find_all(["h1", "h2", "h3", "h4", "h5", "button", "a"]):
        text = " ".join(tag.stripped_strings)

        heading_match = re.search(r"\b(20\d{2})\s+Form\s+5500\b", text, re.I)

        if heading_match:
            candidate = int(heading_match.group(1))
            if candidate in years:
                current_year = candidate

        if tag.name != "a":
            continue

        href = tag.get("href")

        if not href:
            continue

        absolute = urljoin(source_url, href)

        parent_text = ""
        if tag.parent is not None and tag.parent.name not in {"body", "html"}:
            parent_text = " ".join(tag.parent.stripped_strings)

        blob = f"{text} {href} {parent_text}"

        matches = [int(match) for match in year_pattern.findall(blob) if int(match) in years]

        year = matches[0] if matches else current_year

        if year is None or year not in years:
            continue

        dataset = classify_resource(blob)

        if dataset is None:
            continue

        resources.append(
            Resource(
                year=year,
                dataset=dataset,
                url=absolute,
                link_text=text,
            )
        )

    unique: dict[tuple[int, str, str], Resource] = {}

    for resource in resources:
        unique[(resource.year, resource.dataset, resource.url)] = resource

    return sorted(
        unique.values(),
        key=lambda item: (item.year, item.dataset, item.url),
    )


def choose_resources(resources: list[Resource]) -> list[Resource]:
    selected: list[Resource] = []

    grouped: dict[tuple[int, str], list[Resource]] = {}

    for resource in resources:
        grouped.setdefault((resource.year, resource.dataset), []).append(resource)

    for _, candidates in sorted(grouped.items()):
        candidates = sorted(
            candidates,
            key=lambda x: (
                ".zip" not in x.url.lower(),
                "latest" not in x.url.lower(),
                len(x.url),
            ),
        )

        selected.append(candidates[0])

    return selected


def _filename_from_url(resource: Resource) -> str:
    name = Path(urlparse(resource.url).path).name

    if name and "." in name:
        return name

    return f"{resource.dataset}_{resource.year}.download"


def download_resource(resource: Resource, root: Path) -> tuple[Path, bool]:
    destination_dir = root / str(resource.year) / resource.dataset
    destination_dir.mkdir(parents=True, exist_ok=True)

    destination = destination_dir / _filename_from_url(resource)

    if destination.exists() and destination.stat().st_size > 0:
        return destination, False

    partial = destination.with_suffix(destination.suffix + ".part")

    curl = shutil.which("curl.exe") or shutil.which("curl")

    if curl:
        command = [
            curl,
            "-fL",
            "--retry",
            "5",
            "--retry-all-errors",
            "--retry-delay",
            "5",
            "--continue-at",
            "-",
            "-A",
            USER_AGENT,
            "-o",
            str(partial),
            resource.url,
        ]

        completed = subprocess.run(command, check=False)

        if completed.returncode != 0:
            raise RuntimeError(f"Download failed: {resource.url}")

        partial.replace(destination)
        return destination, True

    headers = {"User-Agent": USER_AGENT}

    with requests.get(
        resource.url,
        headers=headers,
        stream=True,
        timeout=180,
    ) as response:
        response.raise_for_status()

        with partial.open("wb") as output:
            for block in response.iter_content(chunk_size=1024 * 1024):
                if block:
                    output.write(block)

    partial.replace(destination)
    return destination, True


def extract_if_zip(path: Path) -> Path:
    destination = path.parent / "extracted"
    destination.mkdir(parents=True, exist_ok=True)

    if zipfile.is_zipfile(path):
        marker = destination / ".extract_complete"

        if not marker.exists():
            with zipfile.ZipFile(path) as archive:
                archive.extractall(destination)

            marker.write_text(
                datetime.now(UTC).isoformat(),
                encoding="utf-8",
            )

    return destination


def find_csv(year_root: Path, year: int, kind: str) -> Path | None:
    candidates = list(year_root.rglob("*.csv"))

    def score(path: Path) -> int:
        name = _compact(path.name)
        value = 0

        if str(year) in name:
            value += 5

        if "latest" in name:
            value += 3

        if kind == "main":
            if "5500" in name:
                value += 8
            if "sch " in name or "schedule" in name:
                value -= 15
            if "5500 sf" in name or "5500sf" in name:
                value -= 15

        elif kind == "sb":
            if "sch sb" in name or "schedule sb" in name:
                value += 20

        elif kind == "h":
            if "sch h" in name or "schedule h" in name:
                value += 20

        elif kind == "i":
            if "sch i" in name or "schedule i" in name:
                value += 20

        return value

    if not candidates:
        return None

    ranked = sorted(candidates, key=score, reverse=True)

    if score(ranked[0]) <= 0:
        return None

    return ranked[0]


def choose_column(columns: list[str], aliases: list[str]) -> str | None:
    exact = {column.upper(): column for column in columns}

    for alias in aliases:
        if alias.upper() in exact:
            return exact[alias.upper()]

    return None


def read_columns(
    path: Path, aliases: dict[str, list[str]]
) -> tuple[pd.DataFrame, dict[str, str | None]]:
    header = pd.read_csv(path, nrows=0)
    columns = list(header.columns)

    mapping: dict[str, str | None] = {
        logical: choose_column(columns, candidates) for logical, candidates in aliases.items()
    }

    usecols = sorted({field for field in mapping.values() if field})

    if not usecols:
        raise RuntimeError(f"No expected fields found in {path}")

    frame = pd.read_csv(
        path,
        usecols=usecols,
        dtype=str,
        low_memory=False,
    )

    rename = {physical: logical for logical, physical in mapping.items() if physical is not None}

    return frame.rename(columns=rename), mapping


MAIN_ALIASES = {
    "ack_id": ["ACK_ID"],
    "ein_raw": ["SPONS_DFE_EIN", "SPONS_EIN", "SPONSOR_EIN"],
    "plan_number_raw": ["SPONS_DFE_PN", "PLAN_NUM", "PLAN_NUMBER"],
    "sponsor_name_raw": ["SPONSOR_DFE_NAME", "SPONS_DFE_NAME", "SPONS_NAME", "SPONSOR_NAME"],
    "plan_year_begin": [
        "FORM_PLAN_YEAR_BEGIN_DATE",
        "PLAN_YEAR_BEGIN_DATE",
    ],
    "participants": [
        "TOT_PARTCP_EOY_CNT",
        "TOT_PARTCP_BOY_CNT",
        "TOT_PARTCP_CNT",
    ],
    "schedule_sb_indicator": ["SCH_SB_ATTACHED_IND"],
    "information_date": [
        "FILING_RECEIVED_DATE",
        "RECEIVED_DATE",
        "DATE_RECEIVED",
        "FILING_DATE",
    ],
}


H_ALIASES = {
    "ack_id": ["ACK_ID"],
    "h_assets": [
        "TOT_ASSETS_EOY_AMT",
        "TOTAL_ASSETS_EOY_AMT",
    ],
    "h_liabilities": [
        "TOT_LIABILITIES_EOY_AMT",
        "TOTAL_LIABILITIES_EOY_AMT",
    ],
    "h_contributions": [
        "TOT_CONTRIB_AMT",
        "TOTAL_CONTRIB_AMT",
    ],
    "h_benefit_payments": [
        "TOT_DISTRIB_BNFT_AMT",
        "TOTAL_DISTRIB_BNFT_AMT",
        "BNFT_PAYMENT_AMT",
        "BENEFIT_PAYMENT_AMT",
    ],
}


SB_ALIASES = {
    "ack_id": ["ACK_ID"],
    "sb_assets": [
        "SB_ACTRL_VALUE_AST_AMT",
        "SB_CURR_VALUE_AST_01_AMT",
        "ACTUARIAL_VALUE_ASSETS_AMT",
        "ACTUARIAL_VAL_ASSETS_AMT",
        "ASSETS_VAL_AMT",
    ],
    "sb_liabilities": [
        "SB_TOT_FNDNG_TGT_AMT",
        "SB_LIAB_ACT_TOT_FNDNG_TGT_AMT",
        "FUNDING_TARGET_AMT",
        "FUNDING_TGT_AMT",
    ],
    "sb_contributions": [
        "SB_TOT_EMPLR_CONTRIB_AMT",
        "TOT_EMPLOYER_CONTRIB_AMT",
        "TOTAL_EMPLOYER_CONTRIB_AMT",
    ],
}


I_ALIASES = {
    "ack_id": ["ACK_ID"],
    "i_assets": [
        "SMALL_TOT_ASSETS_EOY_AMT",
        "TOT_ASSETS_EOY_AMT",
        "TOTAL_ASSETS_EOY_AMT",
    ],
    "i_liabilities": [
        "SMALL_TOT_LIABILITIES_EOY_AMT",
        "TOT_LIABILITIES_EOY_AMT",
        "TOTAL_LIABILITIES_EOY_AMT",
    ],
    "i_contributions": [
        "TOT_CONTRIB_AMT",
        "TOTAL_CONTRIB_AMT",
    ],
    "i_benefit_payments": [
        "SMALL_TOT_DISTRIB_BNFT_AMT",
        "TOT_DISTRIB_BNFT_AMT",
        "TOTAL_DISTRIB_BNFT_AMT",
        "BNFT_PAYMENT_AMT",
    ],
}


def numeric(series: pd.Series) -> pd.Series:
    return pd.to_numeric(
        series.astype(str).str.replace(",", "", regex=False),
        errors="coerce",
    )


def build_year(
    raw_root: Path,
    year: int,
) -> tuple[pd.DataFrame, list[dict[str, object]]]:
    year_root = raw_root / str(year)

    main_csv = find_csv(year_root, year, "main")
    sb_csv = find_csv(year_root, year, "sb")
    h_csv = find_csv(year_root, year, "h")
    i_csv = find_csv(year_root, year, "i")

    if main_csv is None:
        raise RuntimeError(f"{year}: latest Form 5500 CSV not found.")

    if sb_csv is None:
        raise RuntimeError(f"{year}: latest Schedule SB CSV not found.")

    main, main_map = read_columns(main_csv, MAIN_ALIASES)
    sb, sb_map = read_columns(sb_csv, SB_ALIASES)

    if "ack_id" not in main.columns or "ack_id" not in sb.columns:
        raise RuntimeError(f"{year}: ACK_ID is required in Form 5500 and Schedule SB.")

    sb_ack = set(sb["ack_id"].dropna().astype(str))

    db = main.loc[main["ack_id"].astype(str).isin(sb_ack)].copy()

    if db.empty:
        raise RuntimeError(f"{year}: no Schedule-SB-linked DB filings found.")

    h_map: dict[str, str | None] = {}
    i_map: dict[str, str | None] = {}

    if h_csv is not None:
        h, h_map = read_columns(h_csv, H_ALIASES)

        if "ack_id" in h.columns:
            h = h.drop_duplicates("ack_id", keep="last")
            db = db.merge(h, on="ack_id", how="left")

    if i_csv is not None:
        i, i_map = read_columns(i_csv, I_ALIASES)

        if "ack_id" in i.columns:
            i = i.drop_duplicates("ack_id", keep="last")
            db = db.merge(i, on="ack_id", how="left")

    sb = sb.drop_duplicates("ack_id", keep="last")
    db = db.merge(sb, on="ack_id", how="left")

    for column in [
        "participants",
        "h_assets",
        "h_liabilities",
        "h_contributions",
        "h_benefit_payments",
        "i_assets",
        "i_liabilities",
        "i_contributions",
        "i_benefit_payments",
        "sb_assets",
        "sb_liabilities",
        "sb_contributions",
    ]:
        if column in db.columns:
            db[column] = numeric(db[column])

    if "ein_raw" not in db.columns:
        raise RuntimeError(f"{year}: sponsor EIN field was not located.")

    if "plan_number_raw" not in db.columns:
        raise RuntimeError(f"{year}: plan number field was not located.")

    if "sponsor_name_raw" not in db.columns:
        raise RuntimeError(f"{year}: sponsor name field was not located.")

    db["ein"] = db["ein_raw"].map(normalize_ein)
    db["plan_number"] = db["plan_number_raw"].map(normalize_plan_number)
    db["sponsor_name"] = db["sponsor_name_raw"].map(normalize_sponsor_name)

    db["sponsor_id"] = [
        make_sponsor_id(ein, name) for ein, name in zip(db["ein"], db["sponsor_name"], strict=False)
    ]

    db["plan_id"] = [
        make_plan_id(ein, pn, name)
        for ein, pn, name in zip(
            db["ein"],
            db["plan_number"],
            db["sponsor_name"],
            strict=False,
        )
    ]

    if "plan_year_begin" in db.columns:
        plan_year = pd.to_datetime(
            db["plan_year_begin"],
            errors="coerce",
        ).dt.year

        db["plan_year"] = plan_year.fillna(year).astype(int)
    else:
        db["plan_year"] = year

    if "information_date" in db.columns:
        db["information_date"] = pd.to_datetime(
            db["information_date"],
            errors="coerce",
        )
    else:
        db["information_date"] = pd.NaT

    def first_available(names: list[str]) -> pd.Series:
        result = pd.Series(pd.NA, index=db.index, dtype="Float64")

        for name in names:
            if name in db.columns:
                values = pd.to_numeric(db[name], errors="coerce")
                result = result.fillna(values)

        return result

    db["assets"] = first_available(["sb_assets", "h_assets", "i_assets"])

    db["liabilities"] = first_available(["sb_liabilities", "h_liabilities", "i_liabilities"])

    db["contributions"] = first_available(
        ["h_contributions", "i_contributions", "sb_contributions"]
    )

    db["benefit_payments"] = first_available(["h_benefit_payments", "i_benefit_payments"])

    if "participants" not in db.columns:
        db["participants"] = pd.NA

    db["source_file"] = ";".join(
        str(path.relative_to(raw_root))
        for path in [main_csv, sb_csv, h_csv, i_csv]
        if path is not None
    )

    db["db_identification_method"] = "SCHEDULE_SB_ACK_ID_LINK"

    output_columns = [
        "sponsor_id",
        "plan_id",
        "ein",
        "plan_number",
        "sponsor_name",
        "plan_year",
        "assets",
        "liabilities",
        "contributions",
        "benefit_payments",
        "participants",
        "source_file",
        "information_date",
        "ack_id",
        "db_identification_method",
    ]

    output = db[output_columns].copy()

    mapping_rows: list[dict[str, object]] = []

    for source, mapping in [
        ("FORM_5500", main_map),
        ("SCHEDULE_H", h_map),
        ("SCHEDULE_I", i_map),
        ("SCHEDULE_SB", sb_map),
    ]:
        for logical, physical in mapping.items():
            mapping_rows.append(
                {
                    "year": year,
                    "source": source,
                    "logical_field": logical,
                    "physical_field": physical or "",
                }
            )

    return output, mapping_rows


def write_manifest(
    manifest_path: Path,
    rows: list[dict[str, object]],
) -> None:
    manifest_path.parent.mkdir(parents=True, exist_ok=True)

    fields = [
        "year",
        "dataset",
        "source_url",
        "retrieved_utc",
        "local_path",
        "size_bytes",
        "sha256",
        "source_page",
        "status",
    ]

    with manifest_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
