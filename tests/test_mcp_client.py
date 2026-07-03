"""Unit tests for the Google Docs & Gmail MCP client (Phase 4)."""

import pytest
from unittest.mock import patch, MagicMock
import httpx
from pulse.agent.mcp_client import MCPClient, MCPClientError


@pytest.fixture
def mcp_client():
    return MCPClient(server_url="https://test-mcp.up.railway.app", api_key="test-secret-key")


def test_client_init():
    client = MCPClient("https://example.com/", api_key="secret")
    assert client.server_url == "https://example.com"
    assert client.api_key == "secret"


@patch("httpx.Client")
def test_search_doc_found(mock_client_cls, mcp_client):
    mock_instance = MagicMock()
    mock_client_cls.return_value.__enter__.return_value = mock_instance
    
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"status": "success", "found": True, "anchor": "groww-2026-W23"}
    mock_instance.post.return_value = mock_response

    res = mcp_client.search_doc("doc_123", "groww-2026-W23")
    assert res == {"status": "success", "found": True, "anchor": "groww-2026-W23"}
    
    mock_instance.post.assert_called_once_with(
        "https://test-mcp.up.railway.app/search_doc",
        json={"doc_id": "doc_123", "anchor": "groww-2026-W23"},
        headers={"Content-Type": "application/json", "X-API-Key": "test-secret-key"}
    )


@patch("httpx.Client")
def test_search_doc_404_fallback(mock_client_cls, mcp_client):
    """If /search_doc returns 404 (older server without search endpoint), handle gracefully."""
    mock_instance = MagicMock()
    mock_client_cls.return_value.__enter__.return_value = mock_instance
    
    mock_response = MagicMock()
    mock_response.status_code = 404
    mock_instance.post.return_value = mock_response

    res = mcp_client.search_doc("doc_123", "groww-2026-W23")
    assert res["status"] == "not_found"
    assert res["found"] is False
    assert "404 Not Found" in res["warning"]


@patch("httpx.Client")
def test_append_to_doc_success(mock_client_cls, mcp_client):
    mock_instance = MagicMock()
    mock_client_cls.return_value.__enter__.return_value = mock_instance
    
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"status": "success", "documentId": "doc_abc", "insertedText": "hello"}
    mock_instance.post.return_value = mock_response

    res = mcp_client.append_to_doc("doc_abc", "hello")
    assert res["status"] == "success"
    assert res["docUrl"] == "https://docs.google.com/document/d/doc_abc/edit"
    assert res["doc_url"] == "https://docs.google.com/document/d/doc_abc/edit"


@patch("time.sleep", return_value=None)
@patch("httpx.Client")
def test_append_to_doc_retry_on_500(mock_client_cls, mock_sleep, mcp_client):
    mock_instance = MagicMock()
    mock_client_cls.return_value.__enter__.return_value = mock_instance
    
    resp_500 = MagicMock()
    resp_500.status_code = 500
    resp_500.text = "Internal Server Error"
    
    resp_200 = MagicMock()
    resp_200.status_code = 200
    resp_200.json.return_value = {"status": "success", "documentId": "doc_abc"}
    
    # Fail twice with 500, then succeed on 3rd attempt
    mock_instance.post.side_effect = [resp_500, resp_500, resp_200]

    res = mcp_client.append_to_doc("doc_abc", "content")
    assert res["status"] == "success"
    assert mock_instance.post.call_count == 3
    assert mock_sleep.call_count == 2


@patch("httpx.Client")
def test_append_to_doc_fail_fast_on_401(mock_client_cls, mcp_client):
    mock_instance = MagicMock()
    mock_client_cls.return_value.__enter__.return_value = mock_instance
    
    resp_401 = MagicMock()
    resp_401.status_code = 401
    resp_401.text = "Unauthorized API Key"
    mock_instance.post.return_value = resp_401

    with pytest.raises(MCPClientError, match="Client error 401"):
        mcp_client.append_to_doc("doc_abc", "content")
        
    # Should fail immediately on attempt 1 without retrying
    assert mock_instance.post.call_count == 1


@patch("httpx.Client")
def test_append_to_doc_tool_error_status(mock_client_cls, mcp_client):
    mock_instance = MagicMock()
    mock_client_cls.return_value.__enter__.return_value = mock_instance
    
    resp_200 = MagicMock()
    resp_200.status_code = 200
    resp_200.json.return_value = {"status": "error", "error": "Google API Quota Exceeded"}
    mock_instance.post.return_value = resp_200

    with pytest.raises(MCPClientError, match="Google API Quota Exceeded"):
        mcp_client.append_to_doc("doc_abc", "content")


@patch.object(MCPClient, "append_to_doc")
@patch.object(MCPClient, "search_doc")
def test_append_section_already_exists(mock_search, mock_append, mcp_client):
    mock_search.return_value = {"status": "success", "found": True, "anchor": "groww-2026-W23"}
    
    res = mcp_client.append_section("doc_abc", "groww-2026-W23", "content")
    assert res["status"] == "already_exists"
    assert res["docUrl"] == "https://docs.google.com/document/d/doc_abc/edit"
    mock_search.assert_called_once_with(doc_id="doc_abc", anchor="groww-2026-W23")
    mock_append.assert_not_called()


@patch.object(MCPClient, "append_to_doc")
@patch.object(MCPClient, "search_doc")
def test_append_section_not_found_appends(mock_search, mock_append, mcp_client):
    mock_search.return_value = {"status": "success", "found": False, "anchor": "groww-2026-W23"}
    mock_append.return_value = {"status": "success", "documentId": "doc_abc", "docUrl": "https://docs.google.com/document/d/doc_abc/edit"}
    
    res = mcp_client.append_section("doc_abc", "groww-2026-W23", "content")
    assert res["status"] == "success"
    assert res["anchor"] == "groww-2026-W23"
    mock_search.assert_called_once_with(doc_id="doc_abc", anchor="groww-2026-W23")
    mock_append.assert_called_once_with(doc_id="doc_abc", content="content")


@patch.object(MCPClient, "append_to_doc")
@patch.object(MCPClient, "search_doc")
def test_append_section_with_404_fallback_appends(mock_search, mock_append, mcp_client):
    mock_search.return_value = {"status": "not_found", "found": False, "warning": "404 Not Found on /search_doc"}
    mock_append.return_value = {"status": "success", "documentId": "doc_abc", "docUrl": "https://docs.google.com/document/d/doc_abc/edit"}
    
    res = mcp_client.append_section("doc_abc", "groww-2026-W23", "content")
    assert res["status"] == "success"
    assert res["anchor"] == "groww-2026-W23"
    mock_append.assert_called_once_with(doc_id="doc_abc", content="content")


@patch("httpx.Client")
def test_create_email_draft(mock_client_cls, mcp_client):
    mock_instance = MagicMock()
    mock_client_cls.return_value.__enter__.return_value = mock_instance
    
    resp_200 = MagicMock()
    resp_200.status_code = 200
    resp_200.json.return_value = {"status": "success", "draft_id": "draft_xyz", "message_id": "msg_xyz"}
    mock_instance.post.return_value = resp_200

    res = mcp_client.create_email_draft(
        to=["leads@example.com", "support@example.com"],
        subject="Weekly Review",
        body="Draft email content"
    )
    assert res["status"] == "success"
    assert res["draft_id"] == "draft_xyz"
    
    # Ensure recipient list was joined into comma-separated string
    mock_instance.post.assert_called_once()
    args, kwargs = mock_instance.post.call_args
    assert kwargs["json"]["to"] == "leads@example.com, support@example.com"
    assert kwargs["json"]["body"] == "Draft email content"


@patch.object(MCPClient, "create_email_draft")
@patch("httpx.Client")
def test_send_email_fallback_to_draft_on_404(mock_client_cls, mock_draft, mcp_client):
    mock_instance = MagicMock()
    mock_client_cls.return_value.__enter__.return_value = mock_instance
    
    resp_404 = MagicMock()
    resp_404.status_code = 404
    resp_404.text = "Not Found"
    mock_instance.post.return_value = resp_404
    
    mock_draft.return_value = {"status": "success", "draft_id": "draft_fallback"}
    
    res = mcp_client.send_email(to="user@example.com", subject="Test", body="Body")
    assert res["draft_id"] == "draft_fallback"
    mock_draft.assert_called_once_with(to="user@example.com", subject="Test", body="Body")
