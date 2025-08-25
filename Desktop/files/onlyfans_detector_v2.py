#!/usr/bin/env python3
"""
Standalone OnlyFans Detector for n8n Integration - V2
Detects OnlyFans links in bio landing pages (Linktree, Linkme, Beacons, etc.)
Uses pyppeteer (Puppeteer for Python) for better Heroku compatibility
"""

import asyncio
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

import httpx
from pyppeteer import launch

# OnlyFans detection regex
OF_REGEX = re.compile(r"onlyfans\.com", re.IGNORECASE)

class OnlyFansDetector:
    """Detects OnlyFans links in bio landing pages"""
    
    def __init__(self, headless: bool = True):
        self.headless = headless
        self.results = {
            "has_onlyfans": False,
            "onlyfans_urls": [],
            "detection_method": None,
            "errors": [],
            "debug_info": []
        }
    
    async def detect_onlyfans(self, bio_link: str) -> Dict:
        """Main detection method - checks if bio link contains OnlyFans"""
        self.results = {
            "has_onlyfans": False,
            "onlyfans_urls": [],
            "detection_method": None,
            "errors": [],
            "debug_info": []
        }
        
        try:
            # Method 1: Direct link check
            if await self._check_direct_links(bio_link):
                return self.results
            
            # Method 2: Interactive page analysis with Puppeteer
            if await self._check_interactive_page(bio_link):
                return self.results
            
            # Method 3: Redirect chain analysis
            if await self._check_redirect_chains(bio_link):
                return self.results
                
        except Exception as e:
            self.results["errors"].append(f"Detection failed: {str(e)}")
        
        return self.results
    
    async def _check_direct_links(self, bio_link: str) -> bool:
        """Check for direct OnlyFans links in the page HTML"""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(bio_link, timeout=15)
                if response.status_code == 200:
                    content = response.text.lower()
                    
                    # Look for OnlyFans URLs in HTML
                    of_urls = re.findall(r'https?://[^\s<>"\']*onlyfans\.com[^\s<>"\']*', content, re.IGNORECASE)
                    
                    if of_urls:
                        # Filter out /files and /public (not creator profiles)
                        valid_urls = [url for url in of_urls if '/files' not in url and '/public' not in url]
                        if valid_urls:
                            self.results["has_onlyfans"] = True
                            self.results["onlyfans_urls"] = valid_urls
                            self.results["detection_method"] = "direct_html_scan"
                            self.results["debug_info"].append(f"Found {len(valid_urls)} direct OnlyFans links")
                            return True
                            
        except Exception as e:
            self.results["errors"].append(f"Direct link check failed: {str(e)}")
        
        return False
    
    async def _check_interactive_page(self, bio_link: str) -> bool:
        """Use Puppeteer to interact with the page and detect OnlyFans"""
        try:
            # Launch Puppeteer with Heroku-compatible options
            browser = await launch(
                headless=self.headless,
                args=[
                    '--no-sandbox',
                    '--disable-setuid-sandbox',
                    '--disable-dev-shm-usage',
                    '--disable-accelerated-2d-canvas',
                    '--no-first-run',
                    '--no-zygote',
                    '--disable-gpu',
                    '--single-process',
                    '--disable-web-security',
                    '--disable-features=VizDisplayCompositor'
                ]
            )
            
            page = await browser.newPage()
            
            # Track redirects
            onlyfans_redirects = []
            
            # Listen for redirects
            page.on('response', lambda response: self._handle_response(response, onlyfans_redirects))
            
            try:
                # Load the bio link page
                await page.goto(bio_link, {'waitUntil': 'domcontentloaded', 'timeout': 30000})
                await page.waitFor(3000)  # Wait for JS to load
                
                # Accept cookies if present
                try:
                    accept_selectors = [
                        "button:has-text('Accept All')",
                        "button:has-text('Accept')",
                        "button:has-text('OK')",
                        "button:has-text('Got it')"
                    ]
                    for selector in accept_selectors:
                        try:
                            accept_btn = await page.querySelector(selector)
                            if accept_btn:
                                await accept_btn.click()
                                await page.waitFor(2000)
                                break
                        except:
                            continue
                except:
                    pass
                
                # Get all links from the page
                all_links = await self._extract_all_links(page, bio_link)
                
                # Check for OnlyFans in extracted links
                of_links = [link for link in all_links if OF_REGEX.search(link) and '/files' not in link and '/public' not in link]
                
                if of_links:
                    self.results["has_onlyfans"] = True
                    self.results["onlyfans_urls"] = of_links
                    self.results["detection_method"] = "interactive_link_extraction"
                    self.results["debug_info"].append(f"Found {len(of_links)} OnlyFans links via interactive extraction")
                    await browser.close()
                    return True
                
                # Try clicking interactive elements to trigger redirects
                if await self._try_interactive_clicks(page, bio_link):
                    await browser.close()
                    return True
                
                # Check if we captured any redirects
                if onlyfans_redirects:
                    self.results["has_onlyfans"] = True
                    self.results["onlyfans_urls"] = onlyfans_redirects
                    self.results["detection_method"] = "redirect_capture"
                    self.results["debug_info"].append(f"Captured {len(onlyfans_redirects)} OnlyFans redirects")
                    await browser.close()
                    return True
                
            except Exception as e:
                self.results["errors"].append(f"Interactive page check failed: {str(e)}")
            finally:
                await browser.close()
                
        except Exception as e:
            self.results["errors"].append(f"Puppeteer setup failed: {str(e)}")
        
        return False
    
    def _handle_response(self, response, onlyfans_redirects):
        """Handle response events to capture redirects"""
        try:
            if response.status >= 300 and response.status < 400:
                location = response.headers.get('location', '')
                if 'onlyfans.com' in location.lower() and '/files' not in location:
                    onlyfans_redirects.append(location)
        except:
            pass
    
    async def _extract_all_links(self, page, base_url: str) -> List[str]:
        """Extract all links from the page"""
        links = []
        
        try:
            # Get all href attributes
            hrefs = await page.evaluate('''
                () => {
                    const anchors = document.querySelectorAll('a[href]');
                    return Array.from(anchors).map(a => a.href);
                }
            ''')
            
            # Get all data-url attributes
            data_urls = await page.evaluate('''
                () => {
                    const elements = document.querySelectorAll('[data-url]');
                    return Array.from(elements).map(el => el.getAttribute('data-url'));
                }
            ''')
            
            # Combine and filter
            all_urls = hrefs + data_urls
            for url in all_urls:
                if url and url.startswith('http'):
                    links.append(url)
                elif url and url.startswith('/'):
                    links.append(urljoin(base_url, url))
                    
        except Exception as e:
            self.results["errors"].append(f"Link extraction failed: {str(e)}")
        
        return links
    
    async def _try_interactive_clicks(self, page, base_url: str) -> bool:
        """Try clicking various interactive elements to trigger redirects"""
        try:
            # Common button selectors that might lead to OnlyFans
            click_selectors = [
                'button',
                '.btn',
                '.button',
                '[role="button"]',
                'a[href="#"]',
                '.social-link',
                '.profile-link'
            ]
            
            for selector in click_selectors:
                try:
                    elements = await page.querySelectorAll(selector)
                    for element in elements[:5]:  # Limit to first 5 elements
                        try:
                            # Check if element has text that might indicate OnlyFans
                            text = await page.evaluate('el => el.textContent', element)
                            if text and any(keyword in text.lower() for keyword in ['onlyfans', 'of', 'premium', 'exclusive']):
                                await element.click()
                                await page.waitFor(3000)
                                
                                # Check if we got redirected to OnlyFans
                                current_url = page.url
                                if OF_REGEX.search(current_url) and '/files' not in current_url and '/public' not in current_url:
                                    self.results["has_onlyfans"] = True
                                    self.results["onlyfans_urls"] = [current_url]
                                    self.results["detection_method"] = "interactive_click"
                                    self.results["debug_info"].append(f"Found OnlyFans via click: {text}")
                                    return True
                                
                                # Go back to original page
                                await page.goto(base_url, {'waitUntil': 'domcontentloaded'})
                                
                        except Exception:
                            continue
                            
                except Exception:
                    continue
                    
        except Exception as e:
            self.results["errors"].append(f"Interactive clicks failed: {str(e)}")
        
        return False
    
    async def _check_redirect_chains(self, bio_link: str) -> bool:
        """Check redirect chains for OnlyFans destinations"""
        try:
            async with httpx.AsyncClient() as client:
                # Get all links from the page first
                response = await client.get(bio_link, timeout=15)
                if response.status_code == 200:
                    content = response.text
                    
                    # Extract all links
                    all_links = re.findall(r'href=["\']([^"\']+)["\']', content)
                    all_links.extend(re.findall(r'data-url=["\']([^"\']+)["\']', content))
                    
                    # Check first 20 links for redirects
                    for link in all_links[:20]:
                        if not link or link.startswith('#') or link.startswith('mailto:'):
                            continue
                        
                        try:
                            if link.startswith('/'):
                                link = urljoin(bio_link, link)
                            
                            # Follow redirects
                            final_url, _ = await self._follow_redirects(client, link)
                            
                            if OF_REGEX.search(final_url) and '/files' not in final_url and '/public' not in final_url:
                                self.results["has_onlyfans"] = True
                                self.results["onlyfans_urls"] = [final_url]
                                self.results["detection_method"] = "redirect_chain"
                                self.results["debug_info"].append(f"Found OnlyFans via redirect: {link} → {final_url}")
                                return True
                                
                        except Exception:
                            continue
                            
        except Exception as e:
            self.results["errors"].append(f"Redirect chain check failed: {str(e)}")
        
        return False
    
    async def _follow_redirects(self, client: httpx.AsyncClient, url: str, max_redirects: int = 5) -> Tuple[str, List[str]]:
        """Follow redirect chain and return final URL"""
        chain = [url]
        current = url
        
        for _ in range(max_redirects):
            try:
                resp = await client.head(current, follow_redirects=False, timeout=10)
                if resp.status_code in (301, 302, 303, 307, 308):
                    location = resp.headers.get('location')
                    if location:
                        if location.startswith('/'):
                            current = urljoin(current, location)
                        else:
                            current = location
                        chain.append(current)
                    else:
                        break
                else:
                    break
            except Exception:
                break
        
        return current, chain

async def detect_onlyfans_in_bio_link(bio_link: str, headless: bool = True) -> Dict:
    """Main function to detect OnlyFans in a bio link"""
    detector = OnlyFansDetector(headless=headless)
    return await detector.detect_onlyfans(bio_link)

def main():
    """Command line interface for n8n integration"""
    if len(sys.argv) != 2:
        print("Usage: python onlyfans_detector_v2.py <bio_link>")
        print("Example: python onlyfans_detector_v2.py 'https://link.me/username'")
        sys.exit(1)
    
    bio_link = sys.argv[1]
    
    # Run detection
    result = asyncio.run(detect_onlyfans_in_bio_link(bio_link))
    
    # Output JSON result for n8n
    print(json.dumps(result, indent=2))

if __name__ == "__main__":
    main()
