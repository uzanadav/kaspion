from kaspion.ingest.crypto import company_of, next_connection_id


def test_company_of_plain_and_suffixed():
    assert company_of("max") == "max"
    assert company_of("max:2") == "max"
    assert company_of("max:12") == "max"


def test_next_connection_id_first_connection_keeps_plain_company_id():
    """First connection to an institution must keep the plain company id — every
    credential file saved before multi-account support existed reads back unchanged."""
    assert next_connection_id({}, "max") == "max"
    assert next_connection_id({"beinleumi": {}}, "max") == "max"


def test_next_connection_id_increments_for_additional_connections():
    creds = {"max": {}}
    assert next_connection_id(creds, "max") == "max:2"
    creds["max:2"] = {}
    assert next_connection_id(creds, "max") == "max:3"
    # unrelated companies never affect the count
    assert next_connection_id(creds, "beinleumi") == "beinleumi"
