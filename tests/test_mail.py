"""Email delivery (PRD 4.7): the public sandbox never sends; the owner space sends to the test inbox and marks an
email delivered only after IMAP finds its Message-ID. No network: SMTP and IMAP are stand-ins."""

import smtplib

import pytest

from lafaz import config
from lafaz.agent import gate
from lafaz.agent.context import load
from lafaz.mail import delivery, transport
from memory_helpers import D2, meeting, open_db

ENV = config.mail()["env"]
INBOX = "inbox@example.test"
TEXT = "Faris: I'll fix the payment page by Wednesday."
ACTION = {"kind": "action", "text": "Fix the payment page", "owner": "Faris", "due_date": "2026-11-25",
          "quotes": ["I'll fix the payment page by Wednesday"]}


class FakeSMTP:
    def __init__(self, sent, fail=None):
        self.sent, self.fail = sent, fail

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def login(self, user, password):
        if self.fail:
            raise self.fail

    def send_message(self, msg):
        self.sent.append(msg)


class FakeIMAP:
    def __init__(self, inbox):
        self.inbox, self.searches = inbox, []

    def login(self, user, password):
        pass

    def select(self, folder, readonly=False):
        return "OK", [b"1"]

    def search(self, charset, *criteria):
        self.searches.append(criteria)
        wanted = criteria[-1].strip('"')
        found = [str(i + 1).encode() for i, m in enumerate(self.inbox) if m["Message-ID"] == wanted]
        return "OK", [b" ".join(found)]

    def logout(self):
        pass


@pytest.fixture()
def creds(monkeypatch):
    monkeypatch.setenv(ENV["user"], INBOX)
    monkeypatch.setenv(ENV["password"], "not-a-real-password")


def approved_email(tmp_path, space):
    conn = open_db(tmp_path)
    run_id = meeting(conn, TEXT, D2, [ACTION])
    conn.execute("UPDATE runs SET space=? WHERE id=?", (space, run_id))
    ctx = load(conn, run_id)
    card = gate.dispatch(ctx, "send_summary", {"person": "Faris", "subject": "Payment page", "body": "Due Wednesday."})
    gate.approve(conn, card.approval_id)
    outbox_id = conn.execute("SELECT id FROM outbox").fetchone()[0]
    return conn, outbox_id


def outbox(conn, outbox_id):
    return dict(conn.execute("SELECT * FROM outbox WHERE id=?", (outbox_id,)).fetchone())


def no_smtp():
    raise AssertionError("the public sandbox must never open an SMTP connection")


def test_public_sandbox_never_sends(tmp_path, creds):
    conn, oid = approved_email(tmp_path, "public")
    assert outbox(conn, oid)["status"] == "queued"
    assert delivery.deliver(conn, oid, smtp_connect=no_smtp, imap_connect=no_smtp) == "sandbox"
    row = outbox(conn, oid)
    assert row["status"] == "sandbox" and row["message_id"] is None and row["address"] is None


def test_runs_without_a_space_are_public(tmp_path, creds):
    conn, oid = approved_email(tmp_path, None)
    assert delivery.deliver(conn, oid, smtp_connect=no_smtp) == "sandbox"


def test_owner_space_sends_to_the_alias_and_marks_delivered_after_imap(tmp_path, creds):
    conn, oid = approved_email(tmp_path, "owner")
    sent, waits = [], []
    imap = FakeIMAP(sent)
    status = delivery.deliver(conn, oid, smtp_connect=lambda: FakeSMTP(sent), imap_connect=lambda: imap,
                              sleep=waits.append)
    assert status == "delivered"
    msg = sent[0]
    assert msg["To"] == "inbox+faris@example.test"
    assert msg["Subject"].endswith("Payment page")
    assert "Due Wednesday." in msg.get_content()
    row = outbox(conn, oid)
    assert row["message_id"] == msg["Message-ID"] and row["address"] == msg["To"]
    assert row["sent_at"] and row["delivered_at"]
    assert imap.searches[0][:2] == ("HEADER", "Message-ID")
    steps = [tuple(r) for r in conn.execute("SELECT tool, status FROM steps WHERE status LIKE 'mail_%' ORDER BY seq")]
    assert steps == [("send_summary", "mail_sent"), ("send_summary", "mail_delivered")]
    assert "not-a-real-password" not in repr([dict(r) for r in conn.execute("SELECT * FROM steps")])


def test_sent_but_never_seen_is_unverified_not_delivered(tmp_path, creds):
    conn, oid = approved_email(tmp_path, "owner")
    sent, waits = [], []
    status = delivery.deliver(conn, oid, smtp_connect=lambda: FakeSMTP(sent), imap_connect=lambda: FakeIMAP([]),
                              sleep=waits.append)
    assert status == "unverified" and len(sent) == 1
    assert len(waits) == config.mail()["verify"]["attempts"]
    assert outbox(conn, oid)["delivered_at"] is None


def test_refused_by_smtp_is_failed_and_names_the_error_only(tmp_path, creds):
    conn, oid = approved_email(tmp_path, "owner")
    refuse = smtplib.SMTPAuthenticationError(535, b"bad login")
    status = delivery.deliver(conn, oid, smtp_connect=lambda: FakeSMTP([], fail=refuse), imap_connect=no_smtp)
    assert status == "failed"
    assert outbox(conn, oid)["error"] == "SMTPAuthenticationError"


def test_owner_space_without_credentials_holds_the_email(tmp_path, monkeypatch):
    monkeypatch.delenv(ENV["user"], raising=False)
    monkeypatch.delenv(ENV["password"], raising=False)
    conn, oid = approved_email(tmp_path, "owner")
    assert delivery.deliver(conn, oid, smtp_connect=no_smtp) == "held"


def test_a_row_is_delivered_once(tmp_path, creds):
    conn, oid = approved_email(tmp_path, "owner")
    sent = []
    kwargs = dict(smtp_connect=lambda: FakeSMTP(sent), imap_connect=lambda: FakeIMAP(sent), sleep=lambda s: None)
    delivery.deliver(conn, oid, **kwargs)
    assert delivery.deliver(conn, oid, **kwargs) == "delivered" and len(sent) == 1


def test_interrupted_send_is_marked_not_resent(tmp_path, creds):
    conn, oid = approved_email(tmp_path, "owner")
    conn.execute("UPDATE outbox SET status='sending' WHERE id=?", (oid,))
    assert delivery.recover(conn) == 1
    row = outbox(conn, oid)
    assert (row["status"], row["error"]) == ("unverified", "interrupted")


def test_dispatch_handles_every_queued_row(tmp_path, creds, monkeypatch):
    conn, oid = approved_email(tmp_path, "public")
    monkeypatch.setenv("LAFAZ_DB", str(tmp_path / "memory.db"))
    assert delivery.dispatch(smtp_connect=no_smtp) == {oid: "sandbox"}
    assert delivery.dispatch(smtp_connect=no_smtp) == {}


def test_addresses_are_aliases_of_the_one_inbox(monkeypatch):
    assert delivery.address_for("Faris", INBOX) == "inbox+faris@example.test"
    assert delivery.address_for("Nur Aisyah", INBOX) == "inbox+nur-aisyah@example.test"
    assert delivery.address_for("Zoë", INBOX) == "inbox+zoe@example.test"
    assert delivery.address_for("team", INBOX) == f"inbox+{config.mail()['team_alias']}@example.test"
    assert delivery.address_for("界", INBOX) == INBOX  # nothing left to alias: the plain inbox
    monkeypatch.setitem(config.mail(), "plus_alias", False)
    assert delivery.address_for("Faris", INBOX) == INBOX


def test_without_alias_the_name_goes_in_the_subject(tmp_path, creds, monkeypatch):
    monkeypatch.setitem(config.mail(), "plus_alias", False)
    conn, oid = approved_email(tmp_path, "owner")
    sent = []
    delivery.deliver(conn, oid, smtp_connect=lambda: FakeSMTP(sent), imap_connect=lambda: FakeIMAP(sent),
                     sleep=lambda s: None)
    assert sent[0]["To"] == INBOX and sent[0]["Subject"].endswith("(Faris)")


def test_imap_search_only_takes_a_message_id_shape(creds):
    with pytest.raises(ValueError):
        transport.arrived('<a@b>" OR ALL "', connect=lambda: FakeIMAP([]))
