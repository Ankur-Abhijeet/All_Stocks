import pytest

from mf_faq.ingestion.phase_1_2_extractor.extractor import ExtractedScheme
from mf_faq.ingestion.phase_1_3_cleaner.cleaner import Cleaner

@pytest.fixture
def cleaner():
    return Cleaner()

def test_clean_basic(cleaner):
    extracted = ExtractedScheme(
        scheme_id="test",
        scheme_name="Test",
        source_url="http://test",
        sections={
            "expense_ratio": "0.8%",
            "fund_overview": "This is a good fund. NAV is INR 100.23",
            "nav": "100.23",
            "aum": "5000 Cr",
            "exit_load": "1% if redeemed within 1 year"
        }
    )
    result = cleaner.clean(extracted)
    
    # Volatile keys dropped
    assert "nav" not in result.sections
    assert "aum" not in result.sections
    assert "nav" in result.dropped_keys
    
    # Text length validation - 'expense_ratio' is < 20 chars, so it gets dropped
    assert "expense_ratio" not in result.sections
    assert "expense_ratio" in result.dropped_keys

    # Valid sections kept
    assert "fund_overview" in result.sections
    assert "exit_load" in result.sections
    
    # NAV inline redaction
    assert "NAV" not in result.sections["fund_overview"]
    assert "[REDACTED]" in result.sections["fund_overview"]

def test_clean_rupee_symbol(cleaner):
    extracted = ExtractedScheme(
        scheme_id="test",
        scheme_name="Test",
        source_url="http://test",
        sections={
            "min_sip_amount": "The minimum amount is ₹ 500.",
        }
    )
    result = cleaner.clean(extracted)
    assert result.sections["min_sip_amount"] == "The minimum amount is INR 500."

def test_clean_zero_width_chars(cleaner):
    extracted = ExtractedScheme(
        scheme_id="test",
        scheme_name="Test",
        source_url="http://test",
        sections={
            "fund_overview": "This is a\u200b test with \u200c zero \u200d width chars.",
        }
    )
    result = cleaner.clean(extracted)
    assert result.sections["fund_overview"] == "This is a test with zero width chars."

def test_clean_whitespace_collapse(cleaner):
    extracted = ExtractedScheme(
        scheme_id="test",
        scheme_name="Test",
        source_url="http://test",
        sections={
            "fund_overview": "This   is \n a \t test.",
        }
    )
    result = cleaner.clean(extracted)
    # Actually dropped because it's < 20 chars. Let's make it longer.
    extracted.sections["fund_overview"] = "This   is \n a \t test string that is long enough to pass validation."
    result = cleaner.clean(extracted)
    assert result.sections["fund_overview"] == "This is a test string that is long enough to pass validation."

def test_clean_empty_section_drop(cleaner):
    extracted = ExtractedScheme(
        scheme_id="test",
        scheme_name="Test",
        source_url="http://test",
        sections={
            "short_text": "Too short",
            "long_text": "This text is definitely long enough."
        }
    )
    result = cleaner.clean(extracted)
    assert "short_text" not in result.sections
    assert "short_text" in result.dropped_keys
    assert "long_text" in result.sections
