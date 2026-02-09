"""BACnet CSV validation — no platform/DB deps. Use for --validate-only."""

import csv
from pathlib import Path

REQUIRED_COLUMNS = ("device_id", "object_identifier")


def validate_bacnet_csv(csv_path: Path) -> list[tuple[int, str]]:
    """
    Validate BACnet CSV config. Returns list of (line_number, error_message).
    Empty list = valid.
    """
    errors: list[tuple[int, str]] = []
    path = Path(csv_path)

    if not path.exists():
        return [(0, f"CSV file not found: {path}")]

    try:
        with open(path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            fieldnames = reader.fieldnames or []
            for col in REQUIRED_COLUMNS:
                if col not in fieldnames:
                    errors.append((1, f"Missing required column: {col}. Have: {list(fieldnames)}"))
                    break

            for line_num, row in enumerate(reader, start=2):
                did = row.get("device_id", "").strip().strip('"')
                oid = row.get("object_identifier", "").strip().strip('"')

                if not did:
                    errors.append((line_num, f"Line {line_num}: empty device_id"))
                elif "," not in did:
                    errors.append((line_num, f"Line {line_num}: device_id must be 'device,123' format, got: {did!r}"))
                else:
                    try:
                        inst = int(did.split(",")[-1].strip())
                        if inst < 1 or inst > 4194303:
                            errors.append((line_num, f"Line {line_num}: device instance {inst} out of BACnet range 1–4194303"))
                    except ValueError as e:
                        errors.append((line_num, f"Line {line_num}: invalid device_id {did!r}: {e}"))

                if not oid:
                    errors.append((line_num, f"Line {line_num}: empty object_identifier"))
                elif "," not in oid:
                    errors.append((line_num, f"Line {line_num}: object_identifier must be 'analog-input,1' format, got: {oid!r}"))
                else:
                    parts = oid.split(",", 1)
                    try:
                        inst = int(parts[1].strip())
                        if inst < 0:
                            errors.append((line_num, f"Line {line_num}: object instance {inst} must be >= 0"))
                    except ValueError as e:
                        errors.append((line_num, f"Line {line_num}: invalid object_identifier {oid!r}: {e}"))

    except csv.Error as e:
        errors.append((0, f"CSV parse error: {e}"))
    except Exception as e:
        errors.append((0, f"Error reading CSV: {e}"))

    return errors
