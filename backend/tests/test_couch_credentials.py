import logging

from app.couch import CouchClient, split_credentials
from app.logging_setup import setup_logging


def test_credentials_leave_the_url():
    base, auth = split_credentials("http://apex:s3cr%40t@couchdb:5984")
    assert base == "http://couchdb:5984"
    assert auth == ("apex", "s3cr@t")
    assert split_credentials("http://couchdb:5984") == ("http://couchdb:5984", None)


def test_client_base_url_has_no_password():
    client = CouchClient("http://apex:hunter22@couchdb:5984", timeout_s=1)
    assert "hunter22" not in str(client._client.base_url)


def test_httpx_request_logging_is_quiet():
    setup_logging("info")
    assert logging.getLogger("httpx").getEffectiveLevel() >= logging.WARNING
