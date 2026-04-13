"""Tests for scope parsing and tier resolution."""

import pytest

from agent_auth.errors import ScopeDeniedError
from agent_auth.scopes import check_scope, parse_scope_arg


def test_parse_scope_with_tier():
    name, tier = parse_scope_arg("things:read=allow")
    assert name == "things:read"
    assert tier == "allow"


def test_parse_scope_without_tier():
    name, tier = parse_scope_arg("things:read")
    assert name == "things:read"
    assert tier == "allow"


def test_parse_scope_prompt_tier():
    name, tier = parse_scope_arg("outlook:mail:send=prompt")
    assert name == "outlook:mail:send"
    assert tier == "prompt"


def test_parse_scope_deny_tier():
    name, tier = parse_scope_arg("things:write=deny")
    assert name == "things:write"
    assert tier == "deny"


def test_parse_scope_invalid_tier():
    with pytest.raises(ValueError, match="Invalid tier"):
        parse_scope_arg("things:read=invalid")


def test_check_scope_allow():
    scopes = {"things:read": "allow", "things:write": "prompt"}
    assert check_scope("things:read", scopes) == "allow"


def test_check_scope_prompt():
    scopes = {"things:read": "allow", "things:write": "prompt"}
    assert check_scope("things:write", scopes) == "prompt"


def test_check_scope_deny():
    scopes = {"things:read": "allow", "things:write": "deny"}
    with pytest.raises(ScopeDeniedError, match="denied"):
        check_scope("things:write", scopes)


def test_check_scope_not_granted():
    scopes = {"things:read": "allow"}
    with pytest.raises(ScopeDeniedError, match="not granted"):
        check_scope("things:write", scopes)
