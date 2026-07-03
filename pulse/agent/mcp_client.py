"""HTTP client for communicating with remote Google Docs and Gmail MCP servers (Phases 4 & 5)."""

import logging
import time
from typing import Dict, Any, Optional, List, Union
import httpx

logger = logging.getLogger(__name__)


class MCPClientError(Exception):
    """Exception raised for non-transient or exhausted retry errors when calling MCP servers."""
    pass


class MCPClient:
    """REST client for remote MCP-style servers providing Workspace delivery."""

    def __init__(self, server_url: str, api_key: Optional[str] = None):
        self.server_url = server_url.rstrip("/")
        self.api_key = api_key

    def _post_with_retry(self, endpoint: str, payload: Dict[str, Any], max_retries: int = 3) -> Dict[str, Any]:
        """Make an HTTP POST request with exponential backoff for transient errors."""
        url = f"{self.server_url}/{endpoint.lstrip('/')}"
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["X-API-Key"] = self.api_key

        with httpx.Client(timeout=30.0) as client:
            for attempt in range(1, max_retries + 1):
                try:
                    response = client.post(url, json=payload, headers=headers)
                except (httpx.RequestError, httpx.TimeoutException) as e:
                    if attempt == max_retries:
                        raise MCPClientError(f"Network error calling {url} after {max_retries} attempts: {e}") from e
                    logger.warning(f"Transient network error calling {url} (attempt {attempt}/{max_retries}): {e}. Retrying...")
                    time.sleep(2 ** (attempt - 1))
                    continue

                # Handle graceful fallback for search_doc if endpoint is 404 (not yet deployed on remote server)
                if response.status_code == 404 and endpoint == "search_doc":
                    logger.warning(f"Endpoint {url} returned 404 Not Found. Server may be older version without search_doc. Proceeding gracefully.")
                    return {"status": "not_found", "found": False, "warning": "404 Not Found on /search_doc"}

                # Handle transient server errors (5xx)
                if response.status_code >= 500:
                    if attempt == max_retries:
                        raise MCPClientError(f"Server error {response.status_code} calling {url} after {max_retries} attempts: {response.text}")
                    logger.warning(f"Transient server error {response.status_code} calling {url} (attempt {attempt}/{max_retries}). Retrying...")
                    time.sleep(2 ** (attempt - 1))
                    continue

                # Handle non-transient client errors (4xx) - fail fast!
                if response.status_code >= 400:
                    raise MCPClientError(f"Client error {response.status_code} calling {url}: {response.text}")

                try:
                    data = response.json()
                except ValueError as e:
                    raise MCPClientError(f"Invalid JSON response from {url}: {response.text}") from e

                # Check if payload returned an internal tool error
                if isinstance(data, dict) and data.get("status") == "error":
                    raise MCPClientError(f"MCP server returned error status for {endpoint}: {data.get('error', 'Unknown error')}")

                return data

            raise MCPClientError(f"Failed to execute POST {url} after {max_retries} attempts.")

    @staticmethod
    def _sanitize_doc_id(doc_id: str) -> str:
        """Extract clean alphanumeric doc ID if a URL or path is passed."""
        if doc_id and ("/" in doc_id or "http" in doc_id):
            import re
            match = re.search(r"([a-zA-Z0-9_-]{25,})", doc_id)
            if match:
                return match.group(1)
        return doc_id

    def search_doc(self, doc_id: str, anchor: str) -> Dict[str, Any]:
        """Search Google Doc for existing section anchor heading."""
        clean_id = self._sanitize_doc_id(doc_id)
        payload = {"doc_id": clean_id, "anchor": anchor}
        return self._post_with_retry("search_doc", payload)

    def append_to_doc(self, doc_id: str, content: str) -> Dict[str, Any]:
        """Append weekly report section to Google Doc via MCP server."""
        clean_id = self._sanitize_doc_id(doc_id)
        payload = {"doc_id": clean_id, "content": content}
        result = self._post_with_retry("append_to_doc", payload)
        
        # Inject standard Google Doc editing URL for downstream referencing
        doc_url = f"https://docs.google.com/document/d/{clean_id}/edit"
        if isinstance(result, dict):
            result["docUrl"] = doc_url
            result["doc_url"] = doc_url
        return result

    def append_section(self, doc_id: str, anchor: str, content: str) -> Dict[str, Any]:
        """Idempotently append section to Google Doc: search first, append only if not found."""
        clean_id = self._sanitize_doc_id(doc_id)
        search_res = self.search_doc(doc_id=clean_id, anchor=anchor)
        
        if isinstance(search_res, dict) and search_res.get("found") is True:
            logger.info(f"Section with anchor '{anchor}' already exists in document '{clean_id}'. Skipping duplicate append.")
            doc_url = f"https://docs.google.com/document/d/{clean_id}/edit"
            return {
                "status": "already_exists",
                "documentId": clean_id,
                "anchor": anchor,
                "docUrl": doc_url,
                "doc_url": doc_url,
                "searchResult": search_res
            }
            
        # If not found (or 404 fallback), proceed to append content
        append_res = self.append_to_doc(doc_id=clean_id, content=content)
        if isinstance(append_res, dict):
            append_res["anchor"] = anchor
        return append_res

    def create_email_draft(self, to: Union[List[str], str], subject: str, html_body: str = "", text_body: str = "", body: str = "") -> Dict[str, Any]:
        """Create draft email in Gmail via MCP server (`/create_email_draft`)."""
        to_str = ", ".join(to) if isinstance(to, list) else str(to)
        email_body = body or text_body or html_body
        payload = {"to": to_str, "subject": subject, "body": email_body}
        result = self._post_with_retry("create_email_draft", payload)
        return result

    def send_email(self, to: Union[List[str], str], subject: str, html_body: str = "", text_body: str = "", body: str = "") -> Dict[str, Any]:
        """Send email in Gmail via MCP server (`/send_email`), falling back to draft if only draft mode is deployed."""
        to_str = ", ".join(to) if isinstance(to, list) else str(to)
        email_body = body or text_body or html_body
        payload = {"to": to_str, "subject": subject, "body": email_body}
        try:
            return self._post_with_retry("send_email", payload)
        except MCPClientError as e:
            if "404" in str(e) or "not found" in str(e).lower():
                logger.warning("Endpoint /send_email not found on remote server. Falling back to /create_email_draft.")
                return self.create_email_draft(to=to_str, subject=subject, body=email_body)
            raise
