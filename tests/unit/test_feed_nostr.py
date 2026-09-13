"""NIP-19 (bech32) e BIP-340 (firme): i due pezzi del dominio feed che sbagliano in silenzio.

Un codec bech32 con la costante di checksum sbagliata accetta comunque i round-trip con se
stesso: per questo si verifica sui **vettori ufficiali BIP-173** e su `npub` presi dal mondo
reale, non solo su andata-e-ritorno.
"""
import pytest

from src.domains.feed.nostr import events as ev
from src.domains.feed.nostr import nip19, schnorr
from tests.nostr_fixtures import make_event, pubkey_of

SK = "b7" * 32

# BIP-173, appendice "Test vectors".
BECH32_VALID = [
    "A12UEL5L", "a12uel5l",
    "an83characterlonghumanreadablepartthatcontainsthenumber1andtheexcludedcharactersbio1tt5tgs",
    "abcdef1qpzry9x8gf2tvdw0s3jn54khce6mua7lmqqqxw",
    "split1checkupstagehandshakeupstreamerranterredcaperred2y9e3w", "?1ezyfcl",
]
BECH32_INVALID = [
    "\x201nwldj5", "\x7f1axkwrx", "pzry9x0s0muk", "1pzry9x0s0muk", "x1b4n0q5v",
    "li1dgmt3", "de1lg7wt\xff", "A1G7SGD8", "10a06t8", "1qzzfhee",
]
# npub reali: se la costante del checksum fosse sbagliata verrebbero rifiutati.
REAL_NPUBS = {
    "npub1sg6plzptd64u62a878hep2kev88swjh3tw00gjsfl8f237lmu63q0uf63m":
        "82341f882b6eabcd2ba7f1ef90aad961cf074af15b9ef44a09f9d2a8fbfbe6a2",
    "npub180cvv07tjdrrgpa0j7j7tmnyl2yr6yr7l8j4s3evf6u64th6gkwsyjh6w6":
        "3bf0c63fcb93463407af97a5e5ee64fa883d107ef9e558472c4eb9aaaefa459d",
}


@pytest.mark.parametrize("value", BECH32_VALID)
def test_bech32_official_valid_vectors(value):
    nip19.bech32_decode(value)


@pytest.mark.parametrize("value", BECH32_INVALID)
def test_bech32_official_invalid_vectors(value):
    with pytest.raises(nip19.Nip19Error):
        nip19.bech32_decode(value)


@pytest.mark.parametrize("npub,hexkey", REAL_NPUBS.items())
def test_real_npub_decodes_and_round_trips(npub, hexkey):
    assert nip19.npub_to_hex(npub) == hexkey
    assert nip19.hex_to_npub(hexkey) == npub


def test_corrupted_npub_is_rejected():
    npub = next(iter(REAL_NPUBS))
    corrupted = npub[:-1] + ("q" if npub[-1] != "q" else "p")
    with pytest.raises(nip19.Nip19Error):
        nip19.npub_to_hex(corrupted)


def test_normalize_pubkey_accepts_both_forms():
    npub, hexkey = next(iter(REAL_NPUBS.items()))
    assert nip19.normalize_pubkey(npub) == hexkey
    assert nip19.normalize_pubkey(hexkey.upper()) == hexkey
    for bad in ("", "npub1", "zz" * 32, "non-un-npub"):
        with pytest.raises(nip19.Nip19Error):
            nip19.normalize_pubkey(bad)


def test_nevent_carries_relay_hints_and_exceeds_bip173_length_limit():
    """NIP-19 rimuove il limite di 90 caratteri di BIP-173: con piu' relay hint si supera."""
    encoded = nip19.encode_nevent("aa" * 32, relays=["wss://relay.damus.io", "wss://nos.lol"],
                                  author_hex="bb" * 32, kind=54)
    assert len(encoded) > 90
    assert nip19.decode_nevent(encoded) == {
        "id": "aa" * 32, "author": "bb" * 32, "kind": 54,
        "relays": ["wss://relay.damus.io", "wss://nos.lol"],
    }


# ── firme ───────────────────────────────────────────────────────────────────────

def test_sign_and_verify_agree():
    event = make_event(SK, kind=54, created_at=1757100000, content="x")
    assert schnorr.verify(bytes.fromhex(event["id"]), bytes.fromhex(event["pubkey"]),
                          bytes.fromhex(event["sig"]))


def test_verify_rejects_tampered_signature():
    event = make_event(SK, kind=54, created_at=1757100000, content="x")
    for index in (0, 31, 63):
        sig = bytearray(bytes.fromhex(event["sig"]))
        sig[index] ^= 1
        assert not schnorr.verify(bytes.fromhex(event["id"]), bytes.fromhex(event["pubkey"]),
                                  bytes(sig))


def test_verify_rejects_wrong_pubkey_and_malformed_input():
    event = make_event(SK, kind=54, created_at=1757100000, content="x")
    other = bytes.fromhex(pubkey_of("c9" * 32))
    assert not schnorr.verify(bytes.fromhex(event["id"]), other, bytes.fromhex(event["sig"]))
    assert not schnorr.verify(b"corto", bytes.fromhex(event["pubkey"]), bytes.fromhex(event["sig"]))
    assert not schnorr.verify(bytes.fromhex(event["id"]), b"\xff" * 32, bytes.fromhex(event["sig"]))


# ── validazione dell'evento ─────────────────────────────────────────────────────

def test_is_valid_accepts_a_well_formed_signed_event():
    assert ev.is_valid(make_event(SK, kind=54, created_at=1, content="ok"))


def test_is_valid_rejects_content_tampering():
    """Alterare il contenuto rompe l'id: lo scopre anche senza verificare la firma."""
    event = make_event(SK, kind=54, created_at=1, content="ok")
    event["content"] = "contenuto sostituito da un relay ostile"
    assert not ev.is_valid(event, verify_signature=False)


def test_is_valid_rejects_a_forged_event_that_recomputes_the_id():
    """Il falsificatore ricalcola l'id ma non sa rifirmare: solo la firma lo scopre."""
    event = make_event(SK, kind=54, created_at=1, content="ok")
    event["content"] = "contenuto fabbricato"
    event["id"] = ev.compute_id(event)
    assert ev.is_valid(event, verify_signature=False)     # l'id torna: non basta
    assert not ev.is_valid(event, verify_signature=True)  # la firma no


def test_is_valid_rejects_other_authors_and_malformed():
    mine = make_event(SK, kind=54, created_at=1)
    assert not ev.is_valid(mine, pubkey="ab" * 32)
    for bad in (None, {}, {"id": "x"}, [1, 2]):
        assert not ev.is_valid(bad)


def test_verify_signatures_can_be_disabled_by_env(monkeypatch):
    monkeypatch.setenv("FEED_VERIFY_SIGNATURES", "0")
    assert ev.verify_signatures_enabled() is False
    monkeypatch.setenv("FEED_VERIFY_SIGNATURES", "1")
    assert ev.verify_signatures_enabled() is True
