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
