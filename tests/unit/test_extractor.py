import pytest
from bs4 import BeautifulSoup

from mf_faq.ingestion.phase_1_2_extractor.extractor import Extractor, ExtractionError, ExtractedScheme

@pytest.fixture
def extractor():
    return Extractor()

def test_extract_basic(extractor):
    html = """
    <html>
        <body>
            <table>
                <tr><td>Expense Ratio</td><td>0.8%</td></tr>
                <tr><td>Exit Load</td><td>1% within 1 year</td></tr>
                <tr><td>Min SIP</td><td>500</td></tr>
            </table>
            <div><h2>Fund Overview</h2><p>This is a good fund.</p></div>
        </body>
    </html>
    """
    result = extractor.extract(
        html=html,
        scheme_id="test_scheme",
        scheme_name="Test Scheme",
        source_url="https://groww.in/test",
        sections_required=["expense_ratio", "exit_load", "min_sip_amount"],
        sections_optional=["fund_overview"]
    )
    assert result.sections["expense_ratio"] == "0.8%"
    assert result.sections["exit_load"] == "1% within 1 year"
    assert result.sections["min_sip_amount"] == "500"
    assert result.sections["fund_overview"] == "This is a good fund."

def test_extract_missing_required(extractor):
    # Missing min_sip_amount
    html = """
    <html>
        <body>
            <table>
                <tr><td>Expense Ratio</td><td>0.8%</td></tr>
                <tr><td>Exit Load</td><td>1% within 1 year</td></tr>
            </table>
        </body>
    </html>
    """
    with pytest.raises(ExtractionError, match="min_sip_amount"):
        extractor.extract(
            html=html,
            scheme_id="test_scheme",
            scheme_name="Test Scheme",
            source_url="https://groww.in/test",
            sections_required=["expense_ratio", "exit_load", "min_sip_amount"]
        )

def test_extract_missing_optional(extractor):
    # Missing lock_in_period, which is optional
    html = """
    <html>
        <body>
            <table>
                <tr><td>Expense Ratio</td><td>0.8%</td></tr>
                <tr><td>Exit Load</td><td>1% within 1 year</td></tr>
                <tr><td>Min SIP</td><td>500</td></tr>
            </table>
        </body>
    </html>
    """
    result = extractor.extract(
        html=html,
        scheme_id="test_scheme",
        scheme_name="Test Scheme",
        source_url="https://groww.in/test",
        sections_required=["expense_ratio", "exit_load", "min_sip_amount"],
        sections_optional=["lock_in_period"]
    )
    assert "lock_in_period" not in result.sections
    assert result.sections["expense_ratio"] == "0.8%"

def test_extract_thin_content(extractor):
    # P1E-EC-005
    html = "<html><body>Maintenance</body></html>"
    with pytest.raises(ExtractionError, match="content too thin"):
        extractor.extract(
            html=html,
            scheme_id="test",
            scheme_name="Test",
            source_url="http://test",
            sections_required=["expense_ratio"]
        )

def test_extract_multiple_values_ter(extractor):
    # P1E-EC-004
    html = """
    <html>
        <body>
            <div>Expense Ratio</div>
            <div>Regular: 1.2% Direct: 0.5%</div>
            <div>Exit Load</div><div>1%</div>
            <div>Minimum SIP</div><div>500</div>
        </body>
    </html>
    """
    result = extractor.extract(
        html=html,
        scheme_id="test_scheme",
        scheme_name="Test Scheme",
        source_url="https://groww.in/test",
        sections_required=["expense_ratio", "exit_load", "min_sip_amount"]
    )
    assert result.sections["expense_ratio"] == "Regular: 1.2% Direct: 0.5%"
