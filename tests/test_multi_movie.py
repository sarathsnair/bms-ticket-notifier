import sys
import os
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import main
from main import ShowInfo


def show(venue):
    return ShowInfo(
        venue_code="", venue_name=venue, session_id="",
        date_code="", time="", time_code="", screen_attr="",
    )


class ParseWatchUrls(unittest.TestCase):
    def test_one_per_line(self):
        raw = "https://in.bookmyshow.com/a/ET1\nhttps://in.bookmyshow.com/b/ET2"
        self.assertEqual(
            main.parse_watch_urls(raw),
            ["https://in.bookmyshow.com/a/ET1", "https://in.bookmyshow.com/b/ET2"],
        )

    def test_blank_lines_and_whitespace_ignored(self):
        raw = "\n  https://in.bookmyshow.com/a/ET1  \n\n"
        self.assertEqual(main.parse_watch_urls(raw), ["https://in.bookmyshow.com/a/ET1"])

    def test_cap_at_three(self):
        raw = "\n".join(f"https://x/ET{i}" for i in range(5))
        self.assertEqual(
            main.parse_watch_urls(raw),
            ["https://x/ET0", "https://x/ET1", "https://x/ET2"],
        )

    def test_empty_returns_empty_list(self):
        self.assertEqual(main.parse_watch_urls(""), [])
        self.assertEqual(main.parse_watch_urls(None), [])

    def test_commas_in_url_preserved(self):
        raw = "https://x/ET1?lat=9.5,76.5"
        self.assertEqual(main.parse_watch_urls(raw), ["https://x/ET1?lat=9.5,76.5"])


class SortPriority(unittest.TestCase):
    def test_ugm_first_then_goodwill_then_rest(self):
        shows = [
            show("Goodwill Cinemas 4K RGB LASER Atmos 3D: Kallara"),
            show("Anand Theatre Dolby ATMOS: Kottayam"),
            show("UGM Cinemas: Ettumanoor"),
        ]
        out = [s.venue_name for s in main.sort_shows_by_priority(shows, "UGM,Goodwill")]
        self.assertEqual(out, [
            "UGM Cinemas: Ettumanoor",
            "Goodwill Cinemas 4K RGB LASER Atmos 3D: Kallara",
            "Anand Theatre Dolby ATMOS: Kottayam",
        ])

    def test_stable_within_same_rank(self):
        shows = [show("UGM Cinemas: A"), show("UGM Cinemas: B")]
        out = [s.venue_name for s in main.sort_shows_by_priority(shows, "UGM,Goodwill")]
        self.assertEqual(out, ["UGM Cinemas: A", "UGM Cinemas: B"])

    def test_empty_filter_preserves_order(self):
        shows = [show("B"), show("A")]
        out = [s.venue_name for s in main.sort_shows_by_priority(shows, "")]
        self.assertEqual(out, ["B", "A"])


class MovieChanges(unittest.TestCase):
    def _slice(self, status):
        return {
            "shows": {
                "UGM|s1|D|Gold": {
                    "venue": "UGM Cinemas: Ettumanoor", "time": "7:00 PM",
                    "date": "D", "cat": "Gold", "price": "150", "status": status,
                }
            },
            "dates": {},
        }

    def test_no_prior_state_is_empty(self):
        self.assertEqual(
            main.compute_movie_changes({}, "ET1", self._slice("3")), []
        )

    def test_legacy_flat_state_is_empty(self):
        legacy = {"shows": {}, "dates": {}}
        self.assertEqual(
            main.compute_movie_changes(legacy, "ET00502600", self._slice("3")), []
        )

    def test_detects_soldout_to_available(self):
        old = {"ET1": self._slice("0")}
        new = self._slice("3")
        changes = main.compute_movie_changes(old, "ET1", new)
        self.assertTrue(any("BACK" in c for c in changes), changes)

    def test_other_movies_do_not_leak(self):
        old = {"ET_OTHER": self._slice("0")}
        # ET1 has no prior slice, so no changes even though ET_OTHER changed
        self.assertEqual(main.compute_movie_changes(old, "ET1", self._slice("3")), [])


class SendEmailNonFatal(unittest.TestCase):
    def test_resend_failure_does_not_exit(self):
        fake_resp = mock.Mock(status_code=500, text="server error")
        with mock.patch.object(main, "RESEND_API_KEY", "test-key"), \
             mock.patch.object(main, "RESEND_TO_EMAIL", "to@example.com"), \
             mock.patch.object(main.requests, "post", return_value=fake_resp):
            # Must return normally, not raise SystemExit
            main.send_email("subj", ["change"], [], {"name": "Movie"})

    def test_resend_network_error_does_not_exit(self):
        with mock.patch.object(main, "RESEND_API_KEY", "test-key"), \
             mock.patch.object(main, "RESEND_TO_EMAIL", "to@example.com"), \
             mock.patch.object(main.requests, "post",
                               side_effect=main.requests.RequestException("boom")):
            main.send_email("subj", ["change"], [], {"name": "Movie"})


class ParseDateRange(unittest.TestCase):
    def test_valid_range(self):
        self.assertEqual(main.parse_date_range("20260805-20260812"), ("20260805", "20260812"))
    def test_same_day_range_ok(self):
        self.assertEqual(main.parse_date_range("20260805-20260805"), ("20260805", "20260805"))
    def test_comma_list_is_not_range(self):
        self.assertIsNone(main.parse_date_range("20260805,20260830"))
    def test_single_date_is_not_range(self):
        self.assertIsNone(main.parse_date_range("20260805"))
    def test_empty_and_none(self):
        self.assertIsNone(main.parse_date_range(""))
        self.assertIsNone(main.parse_date_range(None))
    def test_invalid_calendar_date(self):
        self.assertIsNone(main.parse_date_range("20261305-20261320"))
    def test_start_after_end(self):
        self.assertIsNone(main.parse_date_range("20260830-20260805"))


class ResolveFetchDates(unittest.TestCase):
    def _adv(self, pairs):
        from main import DateInfo
        return [DateInfo(date_code=c, status=s) for c, s in pairs]
    def test_only_open_dates_in_window_sorted(self):
        adv = self._adv([
            ("20260804", "AVAILABLE"), ("20260805", "BOOKABLE"),
            ("20260806", "NOT_OPEN"), ("20260813", "AVAILABLE"),
        ])
        self.assertEqual(main.resolve_fetch_dates("20260805", "20260810", adv),
                         ["20260805"])
    def test_excludes_not_open(self):
        adv = self._adv([("20260805", "NOT_OPEN")])
        self.assertEqual(main.resolve_fetch_dates("20260801", "20260831", adv), [])
    def test_dedup_and_sort(self):
        adv = self._adv([("20260807", "AVAILABLE"), ("20260806", "BOOKABLE"),
                         ("20260807", "AVAILABLE")])
        self.assertEqual(main.resolve_fetch_dates("20260801", "20260831", adv),
                         ["20260806", "20260807"])
    def test_empty_advertised(self):
        self.assertEqual(main.resolve_fetch_dates("20260801", "20260831", []), [])


class SendTelegram(unittest.TestCase):
    def test_skips_when_unconfigured(self):
        called = []
        with mock.patch.object(main, "TELEGRAM_BOT_TOKEN", ""), \
             mock.patch.object(main, "TELEGRAM_CHAT_ID", ""), \
             mock.patch.object(main.requests, "post",
                               side_effect=lambda *a, **k: called.append(1)):
            main.send_telegram("hello")
        self.assertEqual(called, [], "must not POST when unconfigured")

    def test_posts_message_when_configured(self):
        captured = {}
        def fake_post(url, **kw):
            captured["url"] = url
            captured["json"] = kw.get("json")
            return mock.Mock(status_code=200)
        with mock.patch.object(main, "TELEGRAM_BOT_TOKEN", "Tok:123"), \
             mock.patch.object(main, "TELEGRAM_CHAT_ID", "999"), \
             mock.patch.object(main.requests, "post", fake_post):
            main.send_telegram("hello world")
        self.assertIn("botTok:123/sendMessage", captured["url"])
        self.assertEqual(captured["json"]["chat_id"], "999")
        self.assertEqual(captured["json"]["text"], "hello world")

    def test_nonfatal_on_http_error(self):
        with mock.patch.object(main, "TELEGRAM_BOT_TOKEN", "T"), \
             mock.patch.object(main, "TELEGRAM_CHAT_ID", "9"), \
             mock.patch.object(main.requests, "post",
                               return_value=mock.Mock(status_code=400, text="bad")):
            main.send_telegram("x")  # must return, not raise

    def test_nonfatal_on_exception(self):
        with mock.patch.object(main, "TELEGRAM_BOT_TOKEN", "T"), \
             mock.patch.object(main, "TELEGRAM_CHAT_ID", "9"), \
             mock.patch.object(main.requests, "post",
                               side_effect=main.requests.RequestException("boom")):
            main.send_telegram("x")  # must return, not raise
