"""Tests for bird_x module."""

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Add lib to path
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from lib import bird_x


class TestParseBirdResponse(unittest.TestCase):
    """Tests for parse_bird_response function."""

    def test_parses_successful_response(self):
        """Test parsing a successful bird CLI response."""
        response = {
            "success": True,
            "tweets": [
                {
                    "id": "1234567890",
                    "text": "Test tweet about TypeScript",
                    "author": {"username": "devuser", "name": "Dev User"},
                    "createdAt": "Mon Jan 15 17:32:45 +0000 2026",
                    "likeCount": 25,
                    "retweetCount": 10,
                    "replyCount": 5,
                },
                {
                    "id": "0987654321",
                    "text": "Another test tweet",
                    "author": {"username": "coder123", "name": "Coder"},
                    "createdAt": "Tue Jan 14 10:15:30 +0000 2026",
                    "likeCount": 100,
                    "retweetCount": 50,
                    "replyCount": 20,
                },
            ],
        }

        items = bird_x.parse_bird_response(response)

        self.assertEqual(len(items), 2)
        # First item
        self.assertEqual(items[0]["id"], "X1")
        self.assertEqual(items[0]["text"], "Test tweet about TypeScript")
        self.assertEqual(items[0]["author_handle"], "devuser")
        self.assertEqual(items[0]["url"], "https://x.com/devuser/status/1234567890")
        self.assertEqual(items[0]["date"], "2026-01-15")
        self.assertEqual(items[0]["engagement"]["likes"], 25)
        self.assertEqual(items[0]["engagement"]["reposts"], 10)
        self.assertEqual(items[0]["engagement"]["replies"], 5)
        self.assertEqual(items[0]["relevance"], 0.75)  # Default flat score
        self.assertEqual(items[0]["why_relevant"], "")  # Empty without enrichment

    def test_handles_failed_response(self):
        """Test handling of failed bird CLI response."""
        response = {
            "success": False,
            "error": "bird CLI not found",
            "tweets": [],
        }

        items = bird_x.parse_bird_response(response)

        self.assertEqual(len(items), 0)

    def test_handles_empty_tweets(self):
        """Test handling of empty tweets array."""
        response = {
            "success": True,
            "tweets": [],
        }

        items = bird_x.parse_bird_response(response)

        self.assertEqual(len(items), 0)

    def test_skips_invalid_tweets(self):
        """Test that invalid tweets are skipped."""
        response = {
            "success": True,
            "tweets": [
                # Missing id
                {"text": "No ID tweet", "author": {"username": "user1"}},
                # Valid tweet
                {
                    "id": "123",
                    "text": "Valid tweet",
                    "author": {"username": "user2"},
                    "likeCount": 5,
                },
                # Empty author username
                {"id": "456", "text": "No author", "author": {"username": ""}},
            ],
        }

        items = bird_x.parse_bird_response(response)

        # Only the valid tweet should be included
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["author_handle"], "user2")

    def test_handles_missing_engagement(self):
        """Test handling tweets with missing engagement metrics."""
        response = {
            "success": True,
            "tweets": [
                {
                    "id": "123",
                    "text": "Tweet without engagement",
                    "author": {"username": "user"},
                }
            ],
        }

        items = bird_x.parse_bird_response(response)

        self.assertEqual(len(items), 1)
        self.assertIsNone(items[0]["engagement"])

    def test_truncates_long_text(self):
        """Test that long tweet text is truncated."""
        long_text = "A" * 600  # Longer than 500 char limit
        response = {
            "success": True,
            "tweets": [
                {
                    "id": "123",
                    "text": long_text,
                    "author": {"username": "user"},
                }
            ],
        }

        items = bird_x.parse_bird_response(response)

        self.assertEqual(len(items), 1)
        self.assertEqual(len(items[0]["text"]), 500)


class TestDateParsing(unittest.TestCase):
    """Tests for _parse_twitter_date function."""

    def test_parses_twitter_format(self):
        """Test parsing Twitter's standard date format."""
        result = bird_x._parse_twitter_date("Mon Jan 15 17:32:45 +0000 2026")
        self.assertEqual(result, "2026-01-15")

    def test_parses_different_months(self):
        """Test parsing dates with different months."""
        test_cases = [
            ("Wed Feb 28 12:00:00 +0000 2026", "2026-02-28"),
            ("Thu Mar 01 09:30:00 +0000 2026", "2026-03-01"),
            ("Fri Dec 31 23:59:59 +0000 2025", "2025-12-31"),
        ]
        for input_date, expected in test_cases:
            with self.subTest(input_date=input_date):
                result = bird_x._parse_twitter_date(input_date)
                self.assertEqual(result, expected)

    def test_handles_none(self):
        """Test handling None input."""
        result = bird_x._parse_twitter_date(None)
        self.assertIsNone(result)

    def test_handles_empty_string(self):
        """Test handling empty string."""
        result = bird_x._parse_twitter_date("")
        self.assertIsNone(result)

    def test_handles_invalid_format(self):
        """Test handling invalid date format."""
        result = bird_x._parse_twitter_date("invalid date")
        self.assertIsNone(result)

    def test_handles_iso_format(self):
        """Test parsing ISO format as fallback."""
        result = bird_x._parse_twitter_date("2026-01-15T17:32:45Z")
        self.assertEqual(result, "2026-01-15")


class TestBuildSearchQuery(unittest.TestCase):
    """Tests for _build_search_query function."""

    def test_builds_query_with_dates(self):
        """Test building search query with date operators."""
        query = bird_x._build_search_query("typescript", "2026-01-01", "2026-01-31")
        self.assertEqual(query, "typescript since:2026-01-01 until:2026-01-31")

    def test_preserves_complex_topic(self):
        """Test that complex topics are preserved."""
        query = bird_x._build_search_query("react hooks tutorial", "2026-01-01", "2026-01-15")
        self.assertEqual(query, "react hooks tutorial since:2026-01-01 until:2026-01-15")


class TestDepthConfig(unittest.TestCase):
    """Tests for depth configuration."""

    def test_quick_depth(self):
        """Test quick depth returns 15 tweets."""
        self.assertEqual(bird_x.DEPTH_CONFIG["quick"], 15)

    def test_default_depth(self):
        """Test default depth returns 30 tweets."""
        self.assertEqual(bird_x.DEPTH_CONFIG["default"], 30)

    def test_deep_depth(self):
        """Test deep depth returns 60 tweets."""
        self.assertEqual(bird_x.DEPTH_CONFIG["deep"], 60)


class TestFormatForClaudeEnrichment(unittest.TestCase):
    """Tests for format_for_claude_enrichment function."""

    def test_formats_items_for_enrichment(self):
        """Test formatting items for Claude enrichment."""
        items = [
            {
                "id": "X1",
                "text": "Test tweet",
                "relevance": 0.75,
                "why_relevant": "",
            }
        ]

        prompt = bird_x.format_for_claude_enrichment(items, "typescript")

        self.assertIn("typescript", prompt)
        self.assertIn("relevance", prompt)
        self.assertIn("why_relevant", prompt)
        self.assertIn("Test tweet", prompt)


class TestSearchXBird(unittest.TestCase):
    """Tests for search_x_bird function."""

    def test_uses_mock_response(self):
        """Test that mock_response is used when provided."""
        mock_response = {
            "success": True,
            "tweets": [{"id": "123", "text": "Mock tweet", "author": {"username": "user"}}],
        }

        result = bird_x.search_x_bird(
            "test",
            "2026-01-01",
            "2026-01-31",
            mock_response=mock_response,
        )

        self.assertEqual(result, mock_response)

    @patch("lib.bird_x._call_bird_cli")
    def test_calls_cli_with_correct_params(self, mock_cli):
        """Test that bird CLI is called with correct parameters."""
        mock_cli.return_value = {"success": True, "tweets": []}

        bird_x.search_x_bird(
            "typescript",
            "2026-01-01",
            "2026-01-31",
            depth="quick",
            cookie_source="chrome",
        )

        mock_cli.assert_called_once()
        args = mock_cli.call_args
        # Query should include date operators
        self.assertIn("since:2026-01-01", args[0][0])
        self.assertIn("until:2026-01-31", args[0][0])
        # Count should be 15 for quick depth
        self.assertEqual(args[0][1], 15)
        # Cookie source should be chrome
        self.assertEqual(args[0][2], "chrome")


class TestCheckBirdAvailable(unittest.TestCase):
    """Tests for check_bird_available function."""

    @patch("lib.bird_x._find_bird_cli")
    def test_returns_false_when_not_found(self, mock_find):
        """Test returns False when bird CLI not found."""
        mock_find.return_value = None

        available, error = bird_x.check_bird_available()

        self.assertFalse(available)
        self.assertIn("bird CLI not found", error)

    @patch("lib.bird_x._find_bird_cli")
    @patch("subprocess.run")
    def test_returns_true_when_working(self, mock_run, mock_find):
        """Test returns True when bird CLI is working."""
        mock_find.return_value = "/usr/local/bin/bird"
        mock_run.return_value = MagicMock(returncode=0, stdout="bird 0.8.0")

        available, error = bird_x.check_bird_available()

        self.assertTrue(available)
        self.assertIsNone(error)


if __name__ == "__main__":
    unittest.main()
