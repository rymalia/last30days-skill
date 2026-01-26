"""Bird CLI wrapper for X (Twitter) discovery - alternative to xAI API."""

import json
import re
import shutil
import subprocess
import sys
from datetime import datetime
from typing import Any, Dict, List, Optional

# Depth configurations: number of tweets to request
DEPTH_CONFIG = {
    "quick": 15,
    "default": 30,
    "deep": 60,
}

# Default flat relevance score when not using Claude enrichment
# X search already filters for relevance, so 0.75 is a reasonable baseline
DEFAULT_RELEVANCE = 0.75


def _log_error(msg: str) -> None:
    """Log error to stderr."""
    sys.stderr.write(f"[BIRD ERROR] {msg}\n")
    sys.stderr.flush()


def _log_debug(msg: str) -> None:
    """Log debug message to stderr if DEBUG is enabled."""
    import os
    if os.environ.get("LAST30DAYS_DEBUG"):
        sys.stderr.write(f"[BIRD DEBUG] {msg}\n")
        sys.stderr.flush()


def _find_bird_cli() -> Optional[str]:
    """Find the bird CLI executable.

    Returns:
        Path to bird CLI or None if not found
    """
    # Check if bird is in PATH
    bird_path = shutil.which("bird")
    if bird_path:
        return bird_path

    # Check common locations
    import os
    from pathlib import Path

    common_paths = [
        Path.home() / ".local" / "bin" / "bird",
        Path("/usr/local/bin/bird"),
        Path("/opt/homebrew/bin/bird"),
    ]

    for path in common_paths:
        if path.exists() and os.access(path, os.X_OK):
            return str(path)

    return None


def _parse_twitter_date(date_str: Optional[str]) -> Optional[str]:
    """Parse Twitter's date format to YYYY-MM-DD.

    Twitter uses format like: "Mon Jan 26 15:30:45 +0000 2026"

    Args:
        date_str: Twitter date string or None

    Returns:
        Date in YYYY-MM-DD format or None
    """
    if not date_str:
        return None

    try:
        # Twitter format: "Wed Jan 15 17:32:45 +0000 2025"
        dt = datetime.strptime(date_str, "%a %b %d %H:%M:%S %z %Y")
        return dt.strftime("%Y-%m-%d")
    except ValueError:
        # Try ISO format as fallback
        try:
            dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            _log_debug(f"Could not parse date: {date_str}")
            return None


def _build_search_query(topic: str, from_date: str, to_date: str) -> str:
    """Build X search query with date filters.

    Args:
        topic: Search topic
        from_date: Start date (YYYY-MM-DD)
        to_date: End date (YYYY-MM-DD)

    Returns:
        Search query with date operators
    """
    # X search supports since: and until: operators
    return f"{topic} since:{from_date} until:{to_date}"


def _call_bird_cli(
    query: str,
    count: int,
    cookie_source: str = "safari",
    timeout: int = 60,
) -> Dict[str, Any]:
    """Execute bird CLI search command.

    Args:
        query: Search query
        count: Number of tweets to fetch
        cookie_source: Browser for cookie extraction (safari|chrome|firefox)
        timeout: Command timeout in seconds

    Returns:
        Dict with 'success', 'tweets', and optionally 'error'
    """
    bird_path = _find_bird_cli()
    if not bird_path:
        return {
            "success": False,
            "error": "bird CLI not found. Install with: npm install -g @steipete/bird",
            "tweets": [],
        }

    cmd = [
        bird_path,
        "search",
        query,
        "--count", str(count),
        "--json",
        "--cookie-source", cookie_source,
    ]

    _log_debug(f"Running: {' '.join(cmd)}")

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )

        if result.returncode != 0:
            error_msg = result.stderr.strip() if result.stderr else f"Exit code {result.returncode}"
            _log_error(f"bird CLI error: {error_msg}")
            return {
                "success": False,
                "error": error_msg,
                "tweets": [],
            }

        # Parse JSON output
        output = result.stdout.strip()
        if not output:
            return {
                "success": True,
                "tweets": [],
            }

        try:
            data = json.loads(output)
            # bird outputs an array of tweets directly when using --json
            if isinstance(data, list):
                return {
                    "success": True,
                    "tweets": data,
                }
            elif isinstance(data, dict):
                # Handle object response format
                if "tweets" in data:
                    return {
                        "success": True,
                        "tweets": data["tweets"],
                        "nextCursor": data.get("nextCursor"),
                    }
                elif "error" in data:
                    return {
                        "success": False,
                        "error": data["error"],
                        "tweets": [],
                    }
            return {
                "success": True,
                "tweets": [],
            }
        except json.JSONDecodeError as e:
            _log_error(f"Failed to parse bird output: {e}")
            _log_debug(f"Raw output: {output[:500]}")
            return {
                "success": False,
                "error": f"JSON parse error: {e}",
                "tweets": [],
            }

    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "error": f"bird CLI timed out after {timeout}s",
            "tweets": [],
        }
    except FileNotFoundError:
        return {
            "success": False,
            "error": "bird CLI not found in PATH",
            "tweets": [],
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "tweets": [],
        }


def search_x_bird(
    topic: str,
    from_date: str,
    to_date: str,
    depth: str = "default",
    cookie_source: str = "safari",
    mock_response: Optional[Dict] = None,
) -> Dict[str, Any]:
    """Search X for relevant posts using bird CLI.

    Args:
        topic: Search topic
        from_date: Start date (YYYY-MM-DD)
        to_date: End date (YYYY-MM-DD)
        depth: Research depth - "quick", "default", or "deep"
        cookie_source: Browser for cookie extraction
        mock_response: Mock response for testing

    Returns:
        Raw CLI response with tweets
    """
    if mock_response is not None:
        return mock_response

    count = DEPTH_CONFIG.get(depth, DEPTH_CONFIG["default"])
    query = _build_search_query(topic, from_date, to_date)

    # Adjust timeout based on depth
    timeout = 45 if depth == "quick" else 60 if depth == "default" else 90

    return _call_bird_cli(query, count, cookie_source, timeout)


def parse_bird_response(response: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Parse bird CLI response to extract X items in last30days format.

    Args:
        response: Raw CLI response

    Returns:
        List of item dicts matching xai_x.py output schema
    """
    items = []

    if not response.get("success", False):
        error = response.get("error", "Unknown error")
        _log_error(f"bird search failed: {error}")
        return items

    tweets = response.get("tweets", [])
    if not tweets:
        return items

    for i, tweet in enumerate(tweets):
        if not isinstance(tweet, dict):
            continue

        tweet_id = tweet.get("id", "")
        if not tweet_id:
            continue

        # Extract author info
        author = tweet.get("author", {})
        username = author.get("username", "") if isinstance(author, dict) else ""

        # Build URL
        url = f"https://x.com/{username}/status/{tweet_id}" if username else ""
        if not url:
            continue

        # Parse date
        date = _parse_twitter_date(tweet.get("createdAt"))

        # Extract engagement metrics
        engagement = {
            "likes": tweet.get("likeCount"),
            "reposts": tweet.get("retweetCount"),
            "replies": tweet.get("replyCount"),
            "quotes": None,  # bird doesn't provide quote count
        }

        # Only include engagement if we have at least one metric
        has_engagement = any(v is not None for v in engagement.values())

        clean_item = {
            "id": f"X{i+1}",
            "text": str(tweet.get("text", "")).strip()[:500],  # Truncate long text
            "url": url,
            "author_handle": username.lstrip("@"),
            "date": date,
            "engagement": engagement if has_engagement else None,
            "why_relevant": "",  # Empty unless Claude enrichment is used
            "relevance": DEFAULT_RELEVANCE,  # Flat score since X already filtered
        }

        items.append(clean_item)

    return items


def format_for_claude_enrichment(items: List[Dict], topic: str) -> str:
    """Format items for Claude to enrich with relevance scores.

    This is used when BIRD_ENRICH_RELEVANCE is enabled. The skill outputs
    this prompt, and Claude (running the skill) processes it inline.

    Args:
        items: List of parsed tweet items
        topic: Original search topic

    Returns:
        Prompt for Claude to analyze and score items
    """
    return f'''Please analyze these tweets about "{topic}" and add relevance scores.

For each tweet, update these fields:
- relevance: 0.0-1.0 (how relevant to the topic - 1.0 = highly relevant)
- why_relevant: Brief 1-sentence explanation of relevance

Current items:
```json
{json.dumps(items, indent=2)}
```

Return ONLY the JSON array with updated relevance and why_relevant fields.'''


def check_bird_available() -> tuple[bool, Optional[str]]:
    """Check if bird CLI is available and working.

    Returns:
        Tuple of (is_available, error_message)
    """
    bird_path = _find_bird_cli()
    if not bird_path:
        return False, (
            "bird CLI not found. Install with:\n"
            "  npm install -g @steipete/bird\n"
            "Or from source:\n"
            "  cd /path/to/bird && pnpm install && pnpm run build:dist && npm link"
        )

    # Try to run bird --version to verify it works
    try:
        result = subprocess.run(
            [bird_path, "--version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            version = result.stdout.strip()
            _log_debug(f"bird CLI version: {version}")
            return True, None
        else:
            return False, f"bird CLI returned error: {result.stderr.strip()}"
    except subprocess.TimeoutExpired:
        return False, "bird CLI timed out checking version"
    except Exception as e:
        return False, f"Error checking bird CLI: {e}"
