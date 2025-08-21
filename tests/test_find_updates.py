from packaging.requirements import Requirement
from packaging.version import Version

from fromager.commands.find_updates import _get_constraint_version


class TestGetConstraintVersion:
    """Test cases for _get_constraint_version function."""

    def test_equality_constraint(self):
        """Test that equality constraints return the correct version."""
        req = Requirement("package==1.2.3")
        result = _get_constraint_version(req)
        assert result == Version("1.2.3")

    def test_less_than_constraint(self):
        """Test that less than constraints return the correct version."""
        req = Requirement("package<2.0.0")
        result = _get_constraint_version(req)
        assert result == Version("2.0.0")

    def test_less_than_or_equal_constraint(self):
        """Test that less than or equal constraints return the correct version."""
        req = Requirement("package<=1.5.0")
        result = _get_constraint_version(req)
        assert result == Version("1.5.0")

    def test_greater_than_constraint_unsupported(self):
        """Test that greater than constraints return None (unsupported)."""
        req = Requirement("package>1.0.0")
        result = _get_constraint_version(req)
        assert result is None

    def test_greater_than_or_equal_constraint_unsupported(self):
        """Test that greater than or equal constraints return None (unsupported)."""
        req = Requirement("package>=1.0.0")
        result = _get_constraint_version(req)
        assert result is None

    def test_no_version_constraint(self):
        """Test that requirements without version constraints return None."""
        req = Requirement("package")
        result = _get_constraint_version(req)
        assert result is None

    def test_multiple_constraints_with_one_supported(self):
        """Test that multiple constraints with one supported constraint return the supported one."""
        req = Requirement("package>=1.0.0,<2.0.0")
        result = _get_constraint_version(req)
        assert result == Version("2.0.0")

    def test_constraint_with_markers(self):
        """Test that constraints with environment markers still work correctly."""
        req = Requirement("package==1.2.3; python_version >= '3.8'")
        result = _get_constraint_version(req)
        assert result == Version("1.2.3")

    def test_tilde_equal_constraint_supported(self):
        """Test that tilde equal constraints (~=) return the correct version."""
        req = Requirement("package~=1.4.2")
        result = _get_constraint_version(req)
        assert result == Version("1.4.2")

    def test_not_equal_constraint_supported(self):
        """Test that not equal constraints (!=) return the correct version."""
        req = Requirement("package!=1.0.0")
        result = _get_constraint_version(req)
        assert result == Version("1.0.0")

    def test_arbitrary_equality_constraint_supported(self):
        """Test that arbitrary equality constraints (===) return the correct version."""
        req = Requirement("package===1.0.0")
        result = _get_constraint_version(req)
        assert result == Version("1.0.0")

    def test_invalid_version_format(self):
        """Test that invalid version formats return None."""
        # We need to test the case where Version() construction fails
        # Let's create a requirement and then mock the Version parsing
        import unittest.mock

        req = Requirement("package==1.0.0")

        with unittest.mock.patch(
            "fromager.commands.find_updates.Version"
        ) as mock_version:
            mock_version.side_effect = ValueError("Invalid version")
            result = _get_constraint_version(req)
            assert result is None
