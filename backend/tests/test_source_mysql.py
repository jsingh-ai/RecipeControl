from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from recipecontrol.config import Settings
from recipecontrol.source.factory import dispose_source_repository, get_source_repository
from recipecontrol.source.mysql import (
    MACHINE_SELECT,
    SAMPLE_SELECT,
    TAG_SELECT_PREFIX,
    decode_typed_value,
    display_name,
    normalize_data_kind,
)


@pytest.mark.parametrize(
    "raw_type",
    [
        "Byte",
        "sbyte",
        "INT16",
        "UInt16",
        "Int32",
        "UInt32",
        "Int64",
        "UInt64",
        "Float",
        "Double",
        "Decimal",
        "Number",
        "Integer",
        "UInteger",
    ],
)
def test_common_opc_numeric_types_are_case_insensitive(raw_type: str) -> None:
    assert normalize_data_kind(raw_type) == "numeric"


def test_boolean_and_text_type_mapping() -> None:
    assert normalize_data_kind("bOoLeAn") == "boolean"
    for raw_type in ("String", "Char", "DateTime", "Guid", "LocalizedText", "CustomAlarm"):
        assert normalize_data_kind(raw_type) == "text"


@pytest.mark.parametrize(
    ("raw_type", "expected"),
    [
        ("VariantType.Double", "numeric"),
        ("Opc.Ua.Double", "numeric"),
        ("Float64", "numeric"),
        ("System.Boolean", "boolean"),
        ("Opc.Ua.String", "text"),
    ],
)
def test_prefixed_and_decorated_opc_types(raw_type: str, expected: str) -> None:
    assert normalize_data_kind(raw_type) == expected


def test_observed_storage_is_only_a_safe_unknown_type_fallback() -> None:
    assert normalize_data_kind("CustomNumeric", observed_numeric=True) == "numeric"
    assert normalize_data_kind("CustomFlag", observed_boolean=True) == "boolean"
    assert normalize_data_kind("String", observed_numeric=True) == "text"
    assert normalize_data_kind("Boolean", observed_numeric=True) == "boolean"


def test_display_name_fallback_ignores_blanks() -> None:
    assert display_name("  ", " Browse name ", "ns=2;s=x") == "Browse name"
    assert display_name(None, "", "ns=2;s=x") == "ns=2;s=x"


def test_typed_value_decoding_never_parses_arbitrary_numeric_text() -> None:
    assert decode_typed_value("numeric", None, "12.5") is None
    assert decode_typed_value("numeric", 12.5, "ignored") == Decimal("12.5")
    assert decode_typed_value("text", 12.5, "") == ""
    assert decode_typed_value("text", 12.5, None) is None


@pytest.mark.parametrize(
    ("numeric", "textual", "expected"),
    [
        (0, None, False),
        (1, None, True),
        (None, "TRUE", True),
        (None, "false", False),
        (None, "0", False),
    ],
)
def test_boolean_decoding_uses_only_canonical_representations(
    numeric: object | None, textual: object | None, expected: bool
) -> None:
    assert decode_typed_value("boolean", numeric, textual) is expected


def test_naive_authoritative_datetime_contract_is_utc() -> None:
    naive = datetime(2026, 6, 23, 14, 20)
    assert naive.replace(tzinfo=UTC).isoformat() == "2026-06-23T14:20:00+00:00"


def test_collector_read_only_credential_cannot_be_reused_for_application_writes() -> None:
    with pytest.raises(ValidationError, match="must not use the collector read-only credential"):
        Settings(
            app_database_url="mysql+pymysql://collector_reader:secret@app-db:3306/recipecontrol",
            source_adapter="mysql",
            source_database_url=(
                "mysql+pymysql://collector_reader:secret@app-db:3306/opcua_collector"
            ),
        )


def test_process_local_source_repository_is_reused() -> None:
    dispose_source_repository()
    try:
        assert get_source_repository() is get_source_repository()
    finally:
        dispose_source_repository()


def test_collector_table_statements_are_select_only() -> None:
    for statement in (MACHINE_SELECT, TAG_SELECT_PREFIX, SAMPLE_SELECT):
        assert statement.lstrip().upper().startswith("SELECT")
        assert not any(
            keyword in statement.upper()
            for keyword in ("INSERT INTO", "UPDATE ", "DELETE FROM", "ALTER TABLE", "DROP TABLE")
        )
