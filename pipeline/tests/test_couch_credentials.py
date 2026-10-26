from scorer.couch import CouchWriter, split_credentials


def test_credentials_leave_the_url():
    assert split_credentials("http://apex:pw@couchdb:5984") == ("http://couchdb:5984", ("apex", "pw"))


def test_writer_base_url_has_no_password():
    assert "pw" not in str(CouchWriter("http://apex:pw@couchdb:5984", "x")._client.base_url)
