"""Sentiment analysis connectors for the Senses framework.

Currently provides:
- TwitterSentimentConnector -- OPTIONAL, requires Twitter/X API credentials
"""

from aeon.senses.sentiment.twitter import TwitterSentimentConnector

__all__ = ["TwitterSentimentConnector"]
