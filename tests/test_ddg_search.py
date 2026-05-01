#!/usr/bin/env python
"""Quick test of DuckDuckGo search tool."""

import asyncio
import sys
import re
from urllib.parse import unquote
from aeon.tools.web_tools import search_web, search_news, scrape_page


def extract_real_url(ddg_url):
    """Extract the real URL from a DuckDuckGo redirect."""
    if not ddg_url:
        return None
    
    # DuckDuckGo URLs look like: //duckduckgo.com/l/?uddg=https%3A%2F%2F...&rut=...
    match = re.search(r'uddg=([^&]+)', ddg_url)
    if match:
        encoded_url = match.group(1)
        return unquote(encoded_url)
    return ddg_url


async def test_search():
    """Test the search_web and search_news functions."""
    print("=" * 80)
    print("Testing DuckDuckGo Search Tool + Content Scraping")
    print("=" * 80)
    
    # Test 1: General web search for Apple latest news
    print("\n[TEST 1] search_web('Apple latest news')")
    print("-" * 80)
    result = await search_web("Apple latest news", num_results=5)
    
    urls_to_scrape = []
    if "error" in result:
        print(f"ERROR: {result['error']}")
    else:
        print(f"Query: {result.get('query')}")
        print(f"Source: {result.get('source')}")
        print(f"Result count: {result.get('result_count')}")
        print(f"Timestamp: {result.get('timestamp')}")
        print("\nResults:")
        for i, res in enumerate(result.get("results", []), 1):
            print(f"\n  {i}. {res.get('title')}")
            print(f"     Rank: {res.get('rank')}")
            
            # Extract real URL from DuckDuckGo redirect
            real_url = extract_real_url(res.get('url'))
            print(f"     Real URL: {real_url}")
            print(f"     Snippet: {res.get('snippet')[:100] if res.get('snippet') else '(no snippet)'}...")
            
            # Save URLs for scraping
            if real_url and i <= 3:  # Scrape first 3 sources
                urls_to_scrape.append((res.get('title'), real_url))
    
    # Test 2: Scrape content from the actual sources
    print("\n" + "=" * 80)
    print("[TEST 2] scrape_page() - Extract content from real sources")
    print("-" * 80)
    
    for title, url in urls_to_scrape:
        print(f"\n🔍 Scraping: {title}")
        print(f"   URL: {url}")
        print("-" * 80)
        
        scrape_result = await scrape_page(url)
        
        if "error" in scrape_result:
            print(f"   ❌ ERROR: {scrape_result['error']}")
        else:
            print(f"   ✓ Page Title: {scrape_result.get('title')}")
            print(f"   Word count: {scrape_result.get('word_count')}")
            print(f"\n   Content (first 600 chars):")
            print("   " + "-" * 76)
            text = scrape_result.get('text', '')
            content_preview = text[:600] + "..." if len(text) > 600 else text
            # Indent the content for readability
            for line in content_preview.split('\n'):
                print(f"   {line}")
            print("   " + "-" * 76)
    
    print("\n" + "=" * 80)
    print("Test Complete")
    print("=" * 80)


if __name__ == "__main__":
    try:
        asyncio.run(test_search())
    except Exception as e:
        print(f"FATAL ERROR: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)
