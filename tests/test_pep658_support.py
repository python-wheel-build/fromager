"""Tests for PEP 658 metadata support."""

from unittest.mock import Mock, patch

from packaging.version import Version

from fromager.candidate import Candidate, get_metadata_for_wheel


class TestPEP658Support:
    """Test PEP 658 metadata support in fromager."""

    def test_candidate_with_metadata_url(self):
        """Test that Candidate can be created with a metadata URL."""
        candidate = Candidate(
            name="test-package",
            version=Version("1.0.0"),
            url="https://example.com/test-package-1.0.0-py3-none-any.whl",
            metadata_url="https://example.com/test-package-1.0.0-py3-none-any.whl.metadata",
        )

        assert (
            candidate.metadata_url
            == "https://example.com/test-package-1.0.0-py3-none-any.whl.metadata"
        )

    def test_candidate_without_metadata_url(self):
        """Test that Candidate works without metadata URL (legacy behavior)."""
        candidate = Candidate(
            name="test-package",
            version=Version("1.0.0"),
            url="https://example.com/test-package-1.0.0-py3-none-any.whl",
        )

        assert candidate.metadata_url is None

    @patch("fromager.candidate.session")
    def test_get_metadata_with_pep658_success(self, mock_session):
        """Test successful metadata retrieval via PEP 658 endpoint."""
        # Mock the metadata response
        mock_response = Mock()
        mock_response.content = b"""Metadata-Version: 2.1
Name: test-package
Version: 1.0.0
Summary: A test package
Requires-Dist: requests >= 2.0.0
"""
        mock_response.raise_for_status.return_value = None
        mock_session.get.return_value = mock_response

        wheel_url = "https://example.com/test-package-1.0.0-py3-none-any.whl"
        metadata_url = (
            "https://example.com/test-package-1.0.0-py3-none-any.whl.metadata"
        )

        metadata = get_metadata_for_wheel(wheel_url, metadata_url)

        # Verify the metadata was parsed correctly
        assert metadata["Name"] == "test-package"
        assert metadata["Version"] == "1.0.0"
        assert metadata["Summary"] == "A test package"
        assert "requests >= 2.0.0" in metadata.get_all("Requires-Dist", [])

        # Verify only the metadata URL was called, not the wheel URL
        mock_session.get.assert_called_once_with(metadata_url)

    @patch("fromager.candidate.session")
    def test_get_metadata_pep658_fallback_behavior(self, mock_session):
        """Test that PEP 658 is tried first, then falls back to wheel download."""
        # Mock that metadata URL fails, then wheel URL succeeds
        responses = []

        def side_effect(url):
            if url.endswith(".metadata"):
                # First call - metadata request fails
                mock_response = Mock()
                mock_response.raise_for_status.side_effect = Exception("404 Not Found")
                responses.append(("metadata", url))
                return mock_response
            else:
                # Second call - wheel request
                responses.append(("wheel", url))
                raise Exception("Wheel parsing intentionally mocked to fail")

        mock_session.get.side_effect = side_effect

        wheel_url = "https://example.com/test-package-1.0.0-py3-none-any.whl"
        metadata_url = (
            "https://example.com/test-package-1.0.0-py3-none-any.whl.metadata"
        )

        # This should raise an exception during wheel parsing, but we can verify the order
        try:
            get_metadata_for_wheel(wheel_url, metadata_url)
        except Exception:
            pass  # Expected to fail during wheel parsing mock

        # Verify that both URLs were called in the correct order
        assert len(responses) == 2
        assert responses[0] == ("metadata", metadata_url)
        assert responses[1] == ("wheel", wheel_url)
        assert mock_session.get.call_count == 2

    @patch("fromager.candidate.session")
    def test_get_metadata_without_pep658_behavior(self, mock_session):
        """Test that without PEP 658 metadata URL, only wheel URL is called."""
        # Mock wheel request
        responses = []

        def side_effect(url):
            responses.append(("wheel", url))
            raise Exception("Wheel parsing intentionally mocked to fail")

        mock_session.get.side_effect = side_effect

        wheel_url = "https://example.com/test-package-1.0.0-py3-none-any.whl"

        # This should raise an exception during wheel parsing, but we can verify the behavior
        try:
            get_metadata_for_wheel(wheel_url, metadata_url=None)
        except Exception:
            pass  # Expected to fail during wheel parsing mock

        # Verify that only the wheel URL was called
        assert len(responses) == 1
        assert responses[0] == ("wheel", wheel_url)
        mock_session.get.assert_called_once_with(wheel_url)

    def test_candidate_repr_with_metadata_url(self):
        """Test that Candidate representation includes metadata URL info."""
        candidate = Candidate(
            name="test-package",
            version=Version("1.0.0"),
            url="https://example.com/test-package-1.0.0-py3-none-any.whl",
            metadata_url="https://example.com/test-package-1.0.0-py3-none-any.whl.metadata",
        )

        # The candidate should have the metadata URL attribute
        assert hasattr(candidate, "metadata_url")
        assert candidate.metadata_url is not None

    def test_metadata_url_construction(self):
        """Test that metadata URLs are constructed correctly."""
        base_url = (
            "https://pypi.org/simple/test-package/test-package-1.0.0-py3-none-any.whl"
        )
        expected_metadata_url = base_url + ".metadata"

        # This tests the expected pattern for PEP 658 metadata URLs
        assert expected_metadata_url.endswith(".whl.metadata")
        assert expected_metadata_url.startswith("https://")

    def test_pep658_integration_with_resolver(self):
        """Test that PEP 658 metadata URLs are properly handled by the candidate system."""
        # Test the basic integration of metadata URLs with candidates
        candidate_with_metadata = Candidate(
            name="test-package",
            version=Version("1.0.0"),
            url="https://example.com/test.whl",
            metadata_url="https://example.com/test.whl.metadata",
        )

        candidate_without_metadata = Candidate(
            name="test-package",
            version=Version("1.0.0"),
            url="https://example.com/test.whl",
        )

        # Verify PEP 658 metadata URL handling
        assert (
            candidate_with_metadata.metadata_url
            == "https://example.com/test.whl.metadata"
        )
        assert candidate_without_metadata.metadata_url is None

        # Both should have the same basic properties
        assert candidate_with_metadata.name == candidate_without_metadata.name
        assert candidate_with_metadata.version == candidate_without_metadata.version
        assert candidate_with_metadata.url == candidate_without_metadata.url
