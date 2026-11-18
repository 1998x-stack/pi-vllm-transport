from pi_delta.report import summarize


def test_report_summarizes_and_handles_missing_ttft():
    rows = [
        {"mode": "full", "http_request_body_bytes": "100", "full_request_bytes": "100", "ttft_ms": "1.1", "total_ms": "5.0", "first_byte_ms": "0.2", "prompt_tokens": "10"},
        {"mode": "full", "http_request_body_bytes": "200", "full_request_bytes": "200", "ttft_ms": "", "total_ms": "6.0", "first_byte_ms": "0.3", "prompt_tokens": ""},
        {"mode": "gzip", "http_request_body_bytes": "50", "full_request_bytes": "100", "ttft_ms": "1.0", "total_ms": "4.0", "first_byte_ms": "0.2", "prompt_tokens": "10"},
        {"mode": "delta", "http_request_body_bytes": "60", "full_request_bytes": "100", "ttft_ms": "1.4", "total_ms": "5.0", "first_byte_ms": "0.2", "prompt_tokens": "10"},
    ]
    s = summarize(rows)
    assert s["full"]["http_upload_bytes"] == 300
    assert s["gzip"]["upload_savings_vs_full_pct"] == 83.333
    assert s["full"]["ttft_ms"]["n"] == 1
    assert "delta-gzip" not in s
