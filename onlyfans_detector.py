#!/usr/bin/env python3
"""
Standalone OnlyFans Detector for n8n Integration
Detects OnlyFans links in bio landing pages (Linktree, Linkme, Beacons, etc.)
"""

import asyncio
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

import httpx
from playwright.async_api import async_playwright

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
            
            # Method 2: Interactive page analysis
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
        """Use Playwright to interact with the page and detect OnlyFans"""
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=self.headless)
                context = await browser.new_context()
                page = await context.new_page()
                
                # Track redirects
                onlyfans_redirects = []
                
                def handle_response(response):
                    if response.status >= 300 and response.status < 400:
                        location = response.headers.get('location', '')
                        if 'onlyfans.com' in location.lower() and '/files' not in location:
                            onlyfans_redirects.append(location)
                
                page.on('response', handle_response)
                
                try:
                    # Load the bio link page
                    await page.goto(bio_link, wait_until="domcontentloaded", timeout=30000)
                    await page.wait_for_timeout(3000)  # Wait for JS to load
                    
                    # Accept cookies if present
                    try:
                        accept_selectors = [
                            "button:has-text('Accept All')",
                            "button:has-text('Accept')",
                            "button:has-text('OK')",
                            "button:has-text('Got it')"
                        ]
                        for selector in accept_selectors:
                            if await page.locator(selector).count() > 0:
                                await page.locator(selector).click()
                                await page.wait_for_timeout(2000)
                                break
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
            self.results["errors"].append(f"Playwright setup failed: {str(e)}")
        
        return False
    
    async def _extract_all_links(self, page, base_url: str) -> List[str]:
        """Extract all links from the page"""
        links = []
        
        try:
            # Get all href attributes
            anchors = page.locator("a[href]")
            count = await anchors.count()
            for i in range(min(count, 100)):
                try:
                    href = await anchors.nth(i).get_attribute("href")
                    if href:
                        if href.startswith('/'):
                            full_url = urljoin(base_url, href)
                            links.append(full_url)
                        elif href.startswith('http'):
                            links.append(href)
                except Exception:
                    continue
            
            # Check for data attributes
            data_attrs = ["data-url", "data-href", "data-link", "data-target"]
            for attr in data_attrs:
                elements = page.locator(f"[{attr}]")
                count = await elements.count()
                for i in range(min(count, 50)):
                    try:
                        value = await elements.nth(i).get_attribute(attr)
                        if value and ('http' in value or '/' in value):
                            if value.startswith('http'):
                                links.append(value)
                            elif value.startswith('/'):
                                links.append(urljoin(base_url, value))
                    except Exception:
                        continue
            
            # Check page content for OnlyFans URLs
            try:
                page_text = await page.content()
                text_urls = re.findall(r'https?://[^\s<>"\']*onlyfans\.com[^\s<>"\']*', page_text, re.IGNORECASE)
                links.extend(text_urls)
            except Exception:
                pass
                
        except Exception as e:
            self.results["errors"].append(f"Link extraction failed: {str(e)}")
        
        return list(set(links))  # Remove duplicates
    
    async def _try_interactive_clicks(self, page, base_url: str) -> bool:
        """Try clicking interactive elements to trigger OnlyFans redirects"""
        try:
            domain = urlparse(base_url).netloc.lower()
            
            # Platform-specific click strategies
            if 'link.me' in domain:
                return await self._handle_linkme_clicks(page)
            elif 'linktr.ee' in domain:
                return await self._handle_linktree_clicks(page)
            elif 'beacons.ai' in domain or 'getmysocial.com' in domain:
                return await self._handle_generic_clicks(page)
            
        except Exception as e:
            self.results["errors"].append(f"Interactive clicks failed: {str(e)}")
        
        return False
    
    async def _handle_linkme_clicks(self, page) -> bool:
        """Handle Link.me specific click patterns"""
        try:
            # Look for OnlyFans container and click it
            onlyfans_container = page.locator(".singlealbum.singlebigitem.socialmedialink:has-text('OnlyFans')")
            
            if await onlyfans_container.count() > 0:
                await onlyfans_container.click(force=True)
                await page.wait_for_timeout(3000)
                
                # Look for Continue button
                continue_selectors = [
                    "button:has-text('Continue')",
                    "button:has-text('CONTINUE')",
                    "button:has-text('Proceed')",
                    "button:has-text('Enter')"
                ]
                
                for selector in continue_selectors:
                    try:
                        continue_btn = page.locator(selector)
                        if await continue_btn.count() > 0:
                            await continue_btn.click()
                            await page.wait_for_timeout(5000)
                            
                            current_url = page.url
                            if 'onlyfans.com' in current_url.lower() and '/files' not in current_url:
                                self.results["has_onlyfans"] = True
                                self.results["onlyfans_urls"] = [current_url]
                                self.results["detection_method"] = "linkme_interactive"
                                self.results["debug_info"].append("Successfully clicked through Link.me OnlyFans flow")
                                return True
                    except Exception:
                        continue
            
        except Exception as e:
            self.results["errors"].append(f"Link.me clicks failed: {str(e)}")
        
        return False
    
    async def _handle_linktree_clicks(self, page) -> bool:
        """Handle Linktree specific click patterns"""
        try:
            # Look for LinkButton elements
            link_buttons = page.locator("[data-testid*='LinkButton']")
            count = await link_buttons.count()
            
            for i in range(min(count, 10)):
                try:
                    element = link_buttons.nth(i)
                    href = await element.get_attribute('href')
                    if href and 'onlyfans.com' in href.lower() and '/files' not in href:
                        self.results["has_onlyfans"] = True
                        self.results["onlyfans_urls"] = [href]
                        self.results["detection_method"] = "linktree_direct"
                        self.results["debug_info"].append("Found OnlyFans link in Linktree")
                        return True
                except Exception:
                    continue
                    
        except Exception as e:
            self.results["errors"].append(f"Linktree clicks failed: {str(e)}")
        
        return False
    
    async def _handle_generic_clicks(self, page) -> bool:
        """Handle generic platform clicks"""
        try:
            # Look for common button/link classes
            button_selectors = [
                ".link-button", ".social-link", ".external-link", 
                "[class*='button']", "[class*='link']", "[class*='social']"
            ]
            
            for selector in button_selectors:
                elements = page.locator(selector)
                count = await elements.count()
                
                for i in range(min(count, 20)):
                    try:
                        element = elements.nth(i)
                        href = await element.get_attribute('href')
                        if href and 'onlyfans.com' in href.lower() and '/files' not in href:
                            self.results["has_onlyfans"] = True
                            self.results["onlyfans_urls"] = [href]
                            self.results["detection_method"] = "generic_platform"
                            self.results["debug_info"].append("Found OnlyFans link in generic platform")
                            return True
                    except Exception:
                        continue
                        
        except Exception as e:
            self.results["errors"].append(f"Generic clicks failed: {str(e)}")
        
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
        print("Usage: python onlyfans_detector.py <bio_link>")
        print("Example: python onlyfans_detector.py 'https://link.me/username'")
        sys.exit(1)
    
    bio_link = sys.argv[1]
    
    # Run detection
    result = asyncio.run(detect_onlyfans_in_bio_link(bio_link))
    
    # Output JSON result for n8n
    print(json.dumps(result, indent=2))

if __name__ == "__main__":
    main()
