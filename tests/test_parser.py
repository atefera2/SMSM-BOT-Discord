"""
Parser tests.

Every case here comes from something that actually broke or would have. If a
change makes one fail, the change is wrong — not the test. Read
docs/ARCHITECTURE.md before editing expectations.
"""

import pytest


# (message, {item_id: expected_level})
PHRASES = [
    # --- multi-item: the headline feature -----------------------------------
    ("we need 2 bashamel, 2 foul sandwich and 3 koshary trays",
     {"macaroni": "need", "ful": "need", "koushary": "need"}),
    ("out of bashamel, koshary and foul",
     {"macaroni": "out", "koushary": "out", "ful": "out"}),
    ("need 2 hummus, 1 baba and some pita",
     {"hummus": "need", "baba": "need", "pita": "need"}),
    ("we're out of falafel and tawook",
     {"falafel": "out", "tawook": "out"}),
    ("konafa and basbousa are getting low",
     {"konafa": "low", "basbosa": "low"}),

    # --- mixed levels in one sentence ---------------------------------------
    ("falafel is out but koshary is fine",
     {"falafel": "out", "koushary": "good"}),

    # --- remaining vs requested quantities ----------------------------------
    ("we have two trays of koshary left", {"koushary": "low"}),
    ("down to one pan of mac bechamel", {"macaroni": "need"}),
    ("half a tray of hummus left", {"hummus": "need"}),
    ("2 trays of foul left and 1 tray of hawashy",
     {"ful": "low", "hawawshi": "need"}),

    # --- unit words must not steal the Trays/Plates supply item -------------
    ("we need 4 trays", {"trays": "need"}),
    ("bring 4 bags of ice and 2 propane tanks",
     {"ice": "need", "propane": "need"}),

    # --- clearing an alert ---------------------------------------------------
    ("we are good on fries", {"fries": "good"}),
    ("we're covered on hummus and baba", {"hummus": "good", "baba": "good"}),

    # --- urgency wording -----------------------------------------------------
    ("shwarma almost out", {"shawarma": "need"}),
    ("prepping more kofta now", {"kofta": "prepping"}),

    # --- no item at all: spoken and logged, but nothing on the board ---------
    ("the front gate needs another table", {}),
]


@pytest.mark.parametrize("text,expected", PHRASES, ids=[p[0][:44] for p in PHRASES])
def test_parses(bot, text, expected):
    got = {r["item"]: r["level"] for r in bot.parse_all(text)}
    assert got == expected


def test_quantity_semantics_remaining(bot):
    """'2 trays left' is what remains — it should escalate urgency."""
    (r,) = bot.parse_all("two trays of koshary left")
    assert r["level"] == "low"
    assert "left" in r["detail"]


def test_quantity_semantics_requested(bot):
    """'need 2' is a request — the number must NOT escalate urgency."""
    (r,) = bot.parse_all("we need 2 bechamel")
    assert r["level"] == "need"
    assert r["detail"].startswith("need")


def test_one_remaining_is_urgent(bot):
    (r,) = bot.parse_all("only one tray of koshary left")
    assert r["level"] == "need"


def test_unstated_urgency_stays_silent(bot):
    """
    Item matched, urgency not stated: board updates, kitchen is NOT interrupted.
    This is what stops the speaker crying wolf.
    """
    (r,) = bot.parse_all("can somebody check the propane tank")
    assert r["item"] == "propane"
    assert r["explicit"] is False


def test_stated_urgency_is_explicit(bot):
    (r,) = bot.parse_all("we're out of falafel")
    assert r["explicit"] is True


def test_duplicate_item_keeps_worst_level(bot):
    got = {r["item"]: r["level"] for r in bot.parse_all("koshary is low, actually koshary is out")}
    assert got == {"koushary": "out"}


def test_item_cap(bot):
    many = ", ".join(["koshary", "falafel", "tawook", "kofta", "hummus",
                      "baba", "pita", "fries", "gyro", "shawarma"])
    assert len(bot.parse_all(f"we need {many}")) <= bot.MAX_ITEMS_PER_MESSAGE


@pytest.mark.parametrize("spelling", [
    "bashamel", "bachamel", "beshamel", "bechamel", "bashamil", "macaroni",
])
def test_bechamel_spellings(bot, spelling):
    (r,) = bot.parse_all(f"we're out of {spelling}")
    assert r["item"] == "macaroni"


@pytest.mark.parametrize("spelling", [
    "koshary", "koshari", "kushari", "kosheri", "kosharee", "koushari",
])
def test_koushary_spellings(bot, spelling):
    (r,) = bot.parse_all(f"we're out of {spelling}")
    assert r["item"] == "koushary"


@pytest.mark.parametrize("spelling", ["ful", "fool", "foul", "fava beans"])
def test_ful_spellings(bot, spelling):
    (r,) = bot.parse_all(f"we're out of {spelling}")
    assert r["item"] == "ful"


def test_no_alias_collisions(bot):
    """Two items must never claim the same alias — silent misrouting."""
    seen, clashes = {}, []
    for item in bot.ITEMS:
        names = [item["name"].lower()] + [a.lower() for a in item.get("aliases", [])]
        for a in names:
            if a in seen and seen[a] != item["id"]:
                clashes.append((a, seen[a], item["id"]))
            seen[a] = item["id"]
    assert clashes == []


def test_every_item_has_a_prep_time(bot):
    missing = [i["id"] for i in bot.ITEMS if not bot.prep_minutes(i["id"])]
    assert missing == []


def test_announcement_is_one_sentence_per_level(bot):
    results = bot.parse_all("we need 2 bashamel, 2 foul sandwich and 3 koshary trays")
    line = bot.compose_announcement(results)
    assert line.count("Need") == 1          # grouped, not repeated per item
    assert "Mac Bechamel" in line
    assert "Koushary" in line


def test_announcement_handles_mixed_levels(bot):
    results = bot.parse_all("we're out of falafel and koshary is getting low")
    line = bot.compose_announcement(results)
    assert "out of" in line.lower()
    assert "low" in line.lower()
