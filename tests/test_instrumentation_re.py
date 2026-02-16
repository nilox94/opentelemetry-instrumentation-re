"""Tests for opentelemetry-instrumentation-re."""

from __future__ import annotations

import re
from typing import override

from opentelemetry.test.test_base import TestBase

from opentelemetry_instrumentation_re import ReInstrumentor


class TestReInstrumentor(TestBase):
    """Test suite for ReInstrumentor."""

    @override
    def setUp(self):
        super().setUp()
        ReInstrumentor().instrument()

    @override
    def tearDown(self):
        ReInstrumentor().uninstrument()
        super().tearDown()

    def test_instrument_re_search_creates_span(self):
        """Instrumenting and calling re.search creates a span with expected attributes."""
        m = re.search(r"\d+", "hello 42 world")

        assert m is not None
        assert m.group() == "42"

        spans = self.memory_exporter.get_finished_spans()
        assert len(spans) == 1
        span = spans[0]
        assert span.name == "re.search"
        assert span.attributes is not None
        assert span.attributes.get("re.function") == "search"
        assert span.attributes.get("re.pattern") == "\\d+"
        assert span.attributes.get("re.string_length") == 14

    def test_instrument_re_match(self):
        """re.match is instrumented."""
        _ = re.match(r"hello", "hello world")

        spans = self.memory_exporter.get_finished_spans()
        assert len(spans) == 1
        span = spans[0]
        assert span.name == "re.match"
        assert span.attributes is not None
        assert span.attributes.get("re.function") == "match"

    def test_instrument_re_findall_sets_match_count(self):
        """re.findall sets re.match_count attribute."""
        result = re.findall(r"\d+", "a1 b2 c3")

        assert result == ["1", "2", "3"]
        spans = self.memory_exporter.get_finished_spans()
        assert len(spans) == 1
        span = spans[0]
        assert span.attributes is not None
        assert span.attributes.get("re.match_count") == 3

    def test_instrument_compiled_pattern_search(self):
        """Compiled pattern.search is instrumented."""
        pat = re.compile(r"\w+")
        _ = pat.search("hello world")

        spans = self.memory_exporter.get_finished_spans()
        assert len(spans) == 1
        span = spans[0]
        assert span.name == "re.search"
        assert span.attributes is not None
        assert span.attributes.get("re.pattern") == "\\w+"

    def test_instrument_re_sub(self):
        """re.sub is instrumented."""
        result = re.sub(r"\d+", "0", "a1b2c3")

        assert result == "a0b0c0"
        spans = self.memory_exporter.get_finished_spans()
        assert len(spans) == 1
        assert spans[0].name == "re.sub"

    def test_instrument_re_subn_sets_match_count(self):
        """re.subn sets re.match_count."""
        result = re.subn(r"x", "y", "xxy")

        assert result == ("yyy", 2)
        spans = self.memory_exporter.get_finished_spans()
        assert len(spans) == 1
        span = spans[0]
        assert span.attributes is not None
        assert span.attributes.get("re.match_count") == 2

    def test_uninstrument_restores_behavior(self):
        """After uninstrument, re module works as before and no spans are created."""
        _ = re.search(r"\d+", "hello 42")
        ReInstrumentor().uninstrument()

        assert len(self.memory_exporter.get_finished_spans()) == 1

        _ = re.search(r"\d+", "again 99")
        assert len(self.memory_exporter.get_finished_spans()) == 1  # no new span

    def test_pattern_always_captured(self):
        """Patterns are always captured unconditionally."""
        _ = re.search(r"secret", "a secret")

        spans = self.memory_exporter.get_finished_spans()
        assert len(spans) == 1
        span = spans[0]
        assert span.attributes is not None
        assert span.attributes.get("re.pattern") == "secret"

    def test_full_pattern_captured(self):
        """Full patterns are captured without truncation."""
        long_pattern = "a" * 1000
        _ = re.search(long_pattern, "a" * 5)

        spans = self.memory_exporter.get_finished_spans()
        assert len(spans) == 1
        span = spans[0]
        assert span.attributes is not None
        pattern_attr = span.attributes.get("re.pattern")
        assert isinstance(pattern_attr, str)
        assert len(pattern_attr) == 1000  # full pattern, no truncation
        assert pattern_attr == long_pattern

    def test_re_finditer_instrumented(self):
        """re.finditer is instrumented and does not set match_count."""
        it = re.finditer(r"\d", "a1b2")
        _ = list(it)

        spans = self.memory_exporter.get_finished_spans()
        assert len(spans) == 1
        span = spans[0]
        assert span.name == "re.finditer"
        assert span.attributes is not None
        assert span.attributes.get("re.function") == "finditer"
        # finditer wrapper does not compute match_count
        assert "re.match_count" not in span.attributes

    def test_compiled_pattern_findall_sets_match_count(self):
        """Compiled Pattern.findall sets re.match_count."""
        pat = re.compile(r"\d+")
        result = pat.findall("x1y22z333")

        assert result == ["1", "22", "333"]
        spans = self.memory_exporter.get_finished_spans()
        assert len(spans) == 1
        span = spans[0]
        assert span.name == "re.findall"
        assert span.attributes is not None
        assert span.attributes.get("re.match_count") == 3

    def test_bytes_pattern(self):
        """Bytes patterns are decoded and captured."""
        _ = re.search(b"\\d+", b"hello 42")

        spans = self.memory_exporter.get_finished_spans()
        assert len(spans) == 1
        span = spans[0]
        assert span.attributes is not None
        assert span.attributes.get("re.pattern") == "\\d+"

    def test_compiled_pattern_fullmatch(self):
        """Compiled Pattern.fullmatch is instrumented."""
        pat = re.compile(r"hello")
        _ = pat.fullmatch("hello")

        spans = self.memory_exporter.get_finished_spans()
        assert len(spans) == 1
        span = spans[0]
        assert span.name == "re.fullmatch"
        assert span.attributes is not None
        assert span.attributes.get("re.pattern") == "hello"

    def test_re_split(self):
        """re.split is instrumented."""
        result = re.split(r",", "a,b,c")

        assert result == ["a", "b", "c"]
        spans = self.memory_exporter.get_finished_spans()
        assert len(spans) == 1
        span = spans[0]
        assert span.name == "re.split"
        assert span.attributes is not None
        assert span.attributes.get("re.pattern") == ","

    def test_double_instrumentation_safe(self):
        """Test that double instrumentation is safe"""
        instrumentor = ReInstrumentor()
        instrumentor.instrument()
        # Second instrumentation should be safe
        instrumentor.instrument()

        # Should still work
        _ = re.search(r"\d+", "test 123")

        spans = self.memory_exporter.get_finished_spans()
        assert len(spans) == 1


    def test_uninstrument_without_instrument(self):
        """Test that uninstrument without prior instrument is safe."""
        instrumentor = ReInstrumentor()
        # Should not raise
        instrumentor.uninstrument()

